import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from market.collectors.sahibinden_cdp import (
    ChromeCdp,
    CdpSocket,
    absolute_sahibinden_url,
    extract_laptop_rows,
    extract_rows,
    parse_cdp_endpoint,
    save_raw_row,
    with_paging_offset,
)
from market.models import Country, RawImportRun, Source, SourceType


def _target_score(target, target_url=""):
    if target.type != "page" or "sahibinden.com" not in target.url:
        return 0
    if not target_url:
        return 1
    wanted = target_url.strip()
    if not wanted:
        return 1
    if target.url == wanted:
        return 100
    if wanted in target.url:
        return 50
    return 0


def _select_sahibinden_target(cdp, target_url=""):
    targets = [target for target in cdp.targets() if _target_score(target, target_url)]
    if targets:
        return max(targets, key=lambda target: _target_score(target, target_url))
    if target_url:
        raise RuntimeError(f"No open Sahibinden tab matched target URL: {target_url}")
    raise RuntimeError("No open Sahibinden page target found in Chrome CDP.")


def _enriched_raw_text(row):
    return " ".join(
        str(part).strip()
        for part in [
            row.get("model", ""),
            row.get("title", ""),
            row.get("price", ""),
            row.get("date", ""),
            row.get("place", ""),
            row.get("processor", ""),
            row.get("ram", ""),
            row.get("screenSize", ""),
        ]
        if str(part).strip()
    )


class Command(BaseCommand):
    help = "Import Sahibinden search-result table rows into RawListing via CDP."

    def add_arguments(self, parser):
        parser.add_argument("--cdp", default=settings.CHROME_CDP_ENDPOINT)
        parser.add_argument("--max-rows", type=int, default=300)
        parser.add_argument("--paging-size", type=int, default=50)
        parser.add_argument("--wait", type=float, default=2.0)
        parser.add_argument(
            "--target-url",
            default="",
            help="Sahibinden URL used to select an already-open tab.",
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
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            category_hint=options["category"],
            query_text=options["query"],
            target_url=options["target_url"],
            cdp_endpoint=options["cdp"],
            params_json={
                "max_rows": options["max_rows"],
                "paging_size": options["paging_size"],
                "wait": options["wait"],
            },
            status=RawImportRun.Status.RUNNING,
        )

        sock = None
        visited_pages = extracted_rows = saved_rows = skipped_rows = 0
        try:
            host, port = parse_cdp_endpoint(options["cdp"])
            cdp = ChromeCdp(host, port)
            target = _select_sahibinden_target(cdp, options["target_url"])
            source, _ = Source.objects.get_or_create(
                source_type=SourceType.SAHIBINDEN,
                username="sahibinden-cdp",
                defaults={
                    "name": "Sahibinden CDP",
                    "country": Country.TURKIYE,
                    "profile_url": target.url,
                    "notes": "Imported from a user-opened Chrome tab via CDP.",
                },
            )

            category_hint = options["category"]
            is_laptop = category_hint == "laptops"

            sock = CdpSocket(target)
            seen_urls = set()
            sock.call("Runtime.enable")
            sock.call("Page.enable")
            for offset in range(0, options["max_rows"], options["paging_size"]):
                sock.call("Page.navigate", {"url": with_paging_offset(target.url, offset, options["paging_size"])})
                time.sleep(options["wait"])
                rows = extract_laptop_rows(sock) if is_laptop else extract_rows(sock)
                visited_pages += 1
                if not rows:
                    break
                for row in rows:
                    listing_url = absolute_sahibinden_url(row.get("href", ""))
                    if listing_url in seen_urls:
                        skipped_rows += 1
                        continue
                    seen_urls.add(listing_url)
                    if extracted_rows >= options["max_rows"]:
                        break
                    extracted_rows += 1
                    raw, created = save_raw_row(row, source, import_run=import_run, category_hint=category_hint)
                    enriched_text = _enriched_raw_text(row)
                    if enriched_text and raw.raw_text != enriched_text:
                        raw.raw_text = enriched_text
                        raw.save(update_fields=["raw_text", "updated_at"])
                    if created:
                        saved_rows += 1
                    else:
                        skipped_rows += 1
                if len(rows) < options["paging_size"] or extracted_rows >= options["max_rows"]:
                    break
        except Exception as exc:
            import_run.status = RawImportRun.Status.FAILED
            import_run.error_message = str(exc)
            import_run.finished_at = timezone.now()
            import_run.save(update_fields=["status", "error_message", "finished_at"])
            raise CommandError(str(exc)) from exc
        finally:
            if sock is not None:
                sock.close()

        import_run.created_count = saved_rows
        import_run.skipped_count = skipped_rows
        import_run.status = RawImportRun.Status.COMPLETED
        import_run.finished_at = timezone.now()
        import_run.save(update_fields=["created_count", "skipped_count", "status", "finished_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Import run #{import_run.pk}: visited {visited_pages} pages, "
                f"extracted {extracted_rows} rows, saved {saved_rows} raw, "
                f"skipped {skipped_rows}."
            )
        )
