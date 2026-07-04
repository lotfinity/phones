from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from market.collectors.sahibinden_cdp import import_from_cdp


class Command(BaseCommand):
    help = "Import Sahibinden search-result table rows from an already-open Chrome CDP session."

    def add_arguments(self, parser):
        parser.add_argument("--cdp", default=settings.CHROME_CDP_ENDPOINT)
        parser.add_argument("--max-rows", type=int, default=300)
        parser.add_argument("--paging-size", type=int, default=50)
        parser.add_argument("--wait", type=float, default=2.0)

    def handle(self, *args, **options):
        try:
            result = import_from_cdp(
                options["cdp"],
                max_rows=options["max_rows"],
                paging_size=options["paging_size"],
                wait=options["wait"],
            )
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Visited {result.visited_pages} pages, extracted {result.extracted_rows} rows, "
                f"saved {result.saved_rows}, skipped {result.skipped_rows}."
            )
        )
