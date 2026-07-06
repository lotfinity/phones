from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from market.collectors.ouedkniss_cdp import import_from_cdp
from market.models import Category


class Command(BaseCommand):
    help = "Import visible Ouedkniss listing cards from an already-open Chrome CDP tab."

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
            help="Open target URL when no matching tab exists. Use only for local controlled checks.",
        )
        parser.add_argument(
            "--no-open",
            dest="open_if_missing",
            action="store_false",
            help="Fail instead of opening target URL when no matching tab exists. This is the default.",
        )
        parser.add_argument(
            "--extractor",
            choices=["obsidian", "dom", "auto"],
            default="obsidian",
            help="Extraction backend. Default uses Obsidian Web Clipper content script; auto falls back to direct DOM.",
        )
        parser.add_argument(
            "--max-age-days",
            type=int,
            default=30,
            help="Skip Ouedkniss cards with visible relative dates older than this many days.",
        )
        parser.add_argument(
            "--pc",
            dest="pc_mode",
            action="store_true",
            default=False,
            help="Laptop/PC mode: parse laptop specs (CPU, GPU, RAM, screen) and save to Laptops category.",
        )

    def handle(self, *args, **options):
        category = None
        if options["pc_mode"]:
            category, _ = Category.objects.get_or_create(
                slug="laptops", defaults={"name": "Laptops"}
            )
            self.stdout.write(self.style.WARNING(f"PC mode: saving to Laptops category (id={category.id})"))

        try:
            result = import_from_cdp(
                options["cdp"],
                limit=options["limit"],
                scrolls=options["scrolls"],
                wait=options["wait"],
                target_url=options["target_url"],
                max_age_days=options["max_age_days"],
                open_if_missing=options["open_if_missing"],
                load_timeout=options["load_timeout"],
                extractor=options["extractor"],
                category=category,
            )
        except (RuntimeError, SystemExit) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Extracted {result.extracted_rows} Ouedkniss cards, "
                f"saved {result.saved_rows}, skipped {result.skipped_rows}, "
                f"skipped old {result.skipped_old_rows}, "
                f"skipped no price {result.skipped_no_price_rows}. "
                f"Created {result.created_rows}, updated {result.updated_rows}, "
                f"refreshed unchanged {result.unchanged_rows}. "
                f"Extractor {result.extractor}."
            )
        )
        for change in result.row_changes or []:
            if change.action == "created":
                self.stdout.write(f"NEW: {change.title} | {change.url}")
            elif change.action == "refreshed_unchanged":
                self.stdout.write(f"UNCHANGED: {change.title} | {change.url}")
            else:
                self.stdout.write(f"UPDATED: {change.title} | {change.url}")
                for field, values in change.changes.items():
                    self.stdout.write(f"  - {field}: {values['old']} -> {values['new']}")
        for skipped in result.skipped_no_price_details or []:
            self.stdout.write(f"DROP_NO_PRICE: {skipped['title']} | {skipped['url']}")

        # Recompute deal snapshots
        from django.db import transaction
        from market.models import DealSnapshot
        from market.management.commands.recompute_deal_snapshots import compute_deal_snapshots

        self.stdout.write("Recomputing deal snapshots...")
        snapshots = compute_deal_snapshots()
        with transaction.atomic():
            DealSnapshot.objects.all().delete()
            DealSnapshot.objects.bulk_create(snapshots, batch_size=500)
        self.stdout.write(self.style.SUCCESS(f"Created {len(snapshots)} deal snapshots."))
