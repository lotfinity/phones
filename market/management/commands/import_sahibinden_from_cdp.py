from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from market.collectors.sahibinden_cdp import (
    extract_laptop_rows,
    extract_rows,
    parse_cdp_endpoint,
    target_sahibinden_page,
    with_paging_offset,
    absolute_sahibinden_url,
    save_raw_row,
)
from market.models import RawImportRun, RawListing, Source, SourceType, Country

import time

try:
    from market.collectors.sahibinden_cdp import ChromeCdp, CdpSocket
except ImportError:
    ChromeCdp = None
    CdpSocket = None


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
            status=RawImportRun.Status.RUNNING,
        )

        host, port = parse_cdp_endpoint(options["cdp"])
        cdp = ChromeCdp(host, port)

        target = target_sahibinden_page(cdp)
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
        visited_pages = extracted_rows = saved_rows = skipped_rows = 0
        seen_urls = set()
        try:
            sock.call("Runtime.enable")
            sock.call("Page.enable")
            for offset in range(0, options["max_rows"], options["paging_size"]):
                sock.call("Page.navigate", {"url": with_paging_offset(target.url, offset, options["paging_size"])})
                time.sleep(options["wait"])
                if is_laptop:
                    rows = extract_laptop_rows(sock)
                else:
                    rows = extract_rows(sock)
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
                    _, created = save_raw_row(row, source, import_run=import_run, category_hint=category_hint)
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
            raise
        finally:
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
