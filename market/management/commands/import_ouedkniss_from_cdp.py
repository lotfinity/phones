from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from market.collectors.ouedkniss_cdp import (
    extract_rows,
    extract_rows_with_obsidian,
    parse_cdp_endpoint,
    parse_dzd_price,
    is_within_max_age,
    normalize_ouedkniss_url,
    save_raw_row,
    target_ouedkniss_page,
    wait_for_ouedkniss_cards,
)
from market.models import RawImportRun, Source, SourceType, Country

import time

try:
    from market.collectors.ouedkniss_cdp import ChromeCdp, CdpSocket
except ImportError:
    ChromeCdp = None
    CdpSocket = None


class Command(BaseCommand):
    help = "Import visible Ouedkniss listing cards into RawListing via CDP."

    def add_arguments(self, parser):
        parser.add_argument("--cdp", default=settings.CHROME_CDP_ENDPOINT)
        parser.add_argument("--limit", type=int, default=200)
        parser.add_argument("--scrolls", type=int, default=30)
        parser.add_argument("--wait", type=float, default=1.0)
        parser.add_argument(
            "--target-url",
            default="",
            help="Ouedkniss URL or URL substring used to select an already-open tab.",
        )
        parser.add_argument("--load-timeout", type=float, default=45.0)
        parser.add_argument(
            "--open",
            dest="open_if_missing",
            action="store_true",
            default=False,
        )
        parser.add_argument(
            "--no-open",
            dest="open_if_missing",
            action="store_false",
        )
        parser.add_argument(
            "--extractor",
            choices=["obsidian", "dom", "auto"],
            default="obsidian",
        )
        parser.add_argument(
            "--max-age-days",
            type=int,
            default=30,
        )
        parser.add_argument(
            "--category",
            choices=["phones", "laptops", "unknown"],
            default="unknown",
            help="Category hint for raw listings.",
        )
        parser.add_argument(
            "--query",
            default="",
            help="Search query text for the import run.",
        )

    def handle(self, *args, **options):
        import_run = RawImportRun.objects.create(
            source_type=SourceType.OUEDKNISS,
            country=Country.ALGERIA,
            category_hint=options["category"],
            query_text=options["query"],
            target_url=options["target_url"],
            cdp_endpoint=options["cdp"],
            status=RawImportRun.Status.RUNNING,
        )

        host, port = parse_cdp_endpoint(options["cdp"])
        cdp = ChromeCdp(host, port)

        target = target_ouedkniss_page(
            cdp,
            target_url=options["target_url"],
            open_if_missing=options["open_if_missing"],
            load_timeout=options["load_timeout"],
        )
        source, _ = Source.objects.get_or_create(
            source_type=SourceType.OUEDKNISS,
            username="ouedkniss-cdp",
            defaults={
                "name": "Ouedkniss CDP",
                "country": Country.ALGERIA,
                "profile_url": target.url,
                "notes": "Imported from a user-opened Ouedkniss tab via Chrome CDP.",
            },
        )

        category_hint = options["category"]
        max_age_days = options["max_age_days"]

        wait_for_ouedkniss_cards(target, timeout=options["load_timeout"])

        used_extractor = options["extractor"]
        if used_extractor in {"obsidian", "auto"}:
            try:
                rows = extract_rows_with_obsidian(cdp, target, scrolls=options["scrolls"], wait=options["wait"])
                used_extractor = "obsidian"
            except RuntimeError:
                if used_extractor == "obsidian":
                    import_run.status = RawImportRun.Status.FAILED
                    import_run.error_message = "Obsidian extraction failed"
                    import_run.finished_at = timezone.now()
                    import_run.save(update_fields=["status", "error_message", "finished_at"])
                    raise
                used_extractor = "dom"
                sock = CdpSocket(target)
                try:
                    rows = extract_rows(sock, scrolls=options["scrolls"], wait=options["wait"])
                finally:
                    sock.close()
        else:
            used_extractor = "dom"
            sock = CdpSocket(target)
            try:
                rows = extract_rows(sock, scrolls=options["scrolls"], wait=options["wait"])
                if not rows:
                    time.sleep(options["wait"])
                    wait_for_ouedkniss_cards(target, timeout=options["load_timeout"])
                    rows = extract_rows(sock, scrolls=options["scrolls"], wait=options["wait"])
            finally:
                sock.close()

        saved_rows = skipped_rows = skipped_old_rows = skipped_no_price_rows = 0
        seen_urls = set()
        for row in rows[: options["limit"]]:
            url = normalize_ouedkniss_url(row.get("href", ""))
            row["href"] = url
            if not parse_dzd_price(row.get("priceText")) and not parse_dzd_price(row.get("text", "")):
                skipped_no_price_rows += 1
                continue
            if not url or url in seen_urls:
                skipped_rows += 1
                continue
            if not is_within_max_age(row, max_age_days):
                skipped_old_rows += 1
                continue
            seen_urls.add(url)
            _, created = save_raw_row(row, source, import_run=import_run, category_hint=category_hint)
            if created:
                saved_rows += 1
            else:
                skipped_rows += 1

        import_run.created_count = saved_rows
        import_run.skipped_count = skipped_rows
        import_run.status = RawImportRun.Status.COMPLETED
        import_run.finished_at = timezone.now()
        import_run.save(update_fields=["created_count", "skipped_count", "status", "finished_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Import run #{import_run.pk}: extracted {len(rows)} Ouedkniss cards, "
                f"saved {saved_rows} raw, skipped {skipped_rows}, "
                f"skipped old {skipped_old_rows}, skipped no price {skipped_no_price_rows}. "
                f"Extractor {used_extractor}."
            )
        )
