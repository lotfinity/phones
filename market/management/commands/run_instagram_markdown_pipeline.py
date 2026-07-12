from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from market.management.commands.match_instagram_manual_links_from_markdown import (
    records_from_markdown,
    source_url_from_markdown,
    username_from_url,
)
from market.clean_models import ConsoleOpportunitySnapshot, LaptopOpportunitySnapshot, PhoneOpportunitySnapshot
from market.models import (
    CurrencyRate,
    DealSnapshot,
    InstagramPost,
    MarketListing,
    OCRResult,
    OpportunitySnapshot,
    Source,
    SourceType,
)


class Command(BaseCommand):
    help = (
        "Run the full Instagram Markdown intake pipeline: import/download, OCR, "
        "FX refresh, legacy opportunities, clean opportunities, and summary."
    )

    def add_arguments(self, parser):
        parser.add_argument("markdown_file")
        parser.add_argument("--username", default="", help="Instagram username override.")
        parser.add_argument("--dzd-per-eur-black", default="295")
        parser.add_argument("--ocr-limit", type=int, default=0, help="Max OCR rows; default processes all pending rows.")
        parser.add_argument(
            "--reprocess-existing",
            action="store_true",
            help="Requeue existing markdown posts for OCR after updating/downloading images.",
        )
        parser.add_argument(
            "--skip-fx",
            action="store_true",
            help="Skip fetch_exchange_rates and use existing CurrencyRate rows.",
        )
        parser.add_argument(
            "--skip-clean",
            action="store_true",
            help="Skip clean phone/laptop/console opportunity snapshot recomputes.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Show the import plan without writing rows.")

    def handle(self, *args, **options):
        markdown_file = Path(options["markdown_file"]).expanduser()
        if not markdown_file.exists():
            raise CommandError(f"Markdown file not found: {markdown_file}")

        records = records_from_markdown(markdown_file)
        if not records:
            raise CommandError(f"No Instagram post/reel image links found in {markdown_file}")

        username = options["username"].strip().lstrip("@") or username_from_url(source_url_from_markdown(markdown_file))
        if not username:
            username = username_from_url(records[0]["raw_post_url"])
        if not username:
            raise CommandError("--username is required when it cannot be inferred from the Markdown file.")

        source = Source.objects.filter(source_type=SourceType.INSTAGRAM, username=username).first()
        before = self.snapshot_counts(source, username)
        media_dir = Path(settings.MEDIA_ROOT) / "instagram" / username
        download_dir = media_dir / "manual_images"

        self.stdout.write(self.style.NOTICE("Instagram Markdown pipeline"))
        self.stdout.write(f"Markdown: {markdown_file}")
        self.stdout.write(f"Source: @{username}")
        self.stdout.write(f"Post/reel links found: {len(records)}")
        self.stdout.write(f"Media directory: {media_dir}")
        self.stdout.write(f"Download directory: {download_dir}")

        if options["dry_run"]:
            self.run_step(
                "Preview markdown import",
                "match_instagram_manual_links_from_markdown",
                str(markdown_file),
                "--username",
                username,
                "--queue-new",
                "--download-images",
                "--dry-run",
                passthrough=True,
            )
            self.stdout.write(self.style.WARNING("Dry run selected; stopping before writes."))
            return

        self.validate_ocr_backend()

        self.run_step(
            "Import markdown posts and download images",
            "match_instagram_manual_links_from_markdown",
            str(markdown_file),
            "--username",
            username,
            "--queue-new",
            "--download-images",
            *("--reprocess-existing",) if options["reprocess_existing"] else (),
            passthrough=True,
        )

        source = Source.objects.get(source_type=SourceType.INSTAGRAM, username=username)
        pending_ocr = InstagramPost.objects.filter(source=source, needs_ocr=True, ocr_processed=False).count()
        if pending_ocr:
            ocr_limit = options["ocr_limit"] or pending_ocr
            self.run_step(
                f"OCR and listing classification for {pending_ocr} pending posts",
                "process_ocr_queue",
                "--source-username",
                username,
                "--limit",
                str(ocr_limit),
                passthrough=True,
            )
        else:
            self.stdout.write(self.style.NOTICE("[skip] OCR: no pending posts for this source."))

        self.run_step(
            "Recompute phone listing matches",
            "recompute_listing_matches",
            "--product-type",
            "phone",
            "--only-missing",
            passthrough=True,
        )

        if options["skip_fx"]:
            self.stdout.write(self.style.NOTICE("[skip] FX refresh."))
        else:
            self.run_step(
                "Fetch exchange rates",
                "fetch_exchange_rates",
                "--dzd-per-eur-black",
                str(options["dzd_per_eur_black"]),
                passthrough=True,
            )

        self.run_step("Legacy opportunity and deal snapshots", "run_opportunity_analysis", passthrough=True)

        if options["skip_clean"]:
            self.stdout.write(self.style.NOTICE("[skip] Clean opportunity snapshots."))
        else:
            self.run_step(
                "Clean phone opportunity snapshots",
                "recompute_phone_opportunities_v2",
                "--write-snapshots",
                passthrough=True,
            )
            self.run_step(
                "Clean laptop opportunity snapshots",
                "recompute_laptop_opportunities_v2",
                "--write-snapshots",
                passthrough=True,
            )
            self.run_step(
                "Clean console opportunity snapshots",
                "recompute_console_opportunities_v1",
                "--write-snapshots",
                passthrough=True,
            )

        recent_data = self.run_step("Recent data summary", "inspect_recent_data", passthrough=False)
        after = self.snapshot_counts(source, username)
        self.write_summary(username, markdown_file, len(records), before, after, recent_data)

    def run_step(self, label, command_name, *args, passthrough):
        self.stdout.write("")
        self.stdout.write(self.style.NOTICE(f"==> {label}"))
        if passthrough:
            call_command(command_name, *args, stdout=self.stdout, stderr=self.stderr)
            return ""

        out = StringIO()
        call_command(command_name, *args, stdout=out, stderr=self.stderr)
        output = out.getvalue().strip()
        if output:
            self.stdout.write(output)
        return output

    def snapshot_counts(self, source, username):
        source_posts = InstagramPost.objects.filter(source=source) if source else InstagramPost.objects.none()
        source_post_ids = source_posts.values("id")
        source_listings = MarketListing.objects.filter(source=source) if source else MarketListing.objects.none()
        download_dir = Path(settings.MEDIA_ROOT) / "instagram" / username / "manual_images"
        downloaded_images = len([path for path in download_dir.glob("*") if path.is_file()]) if download_dir.exists() else 0
        return {
            "source_posts": source_posts.count(),
            "pending_ocr": source_posts.filter(needs_ocr=True, ocr_processed=False).count(),
            "ocr_results": OCRResult.objects.filter(instagram_post_id__in=source_post_ids).count(),
            "source_listings": source_listings.count(),
            "downloaded_images": downloaded_images,
            "currency_rates": CurrencyRate.objects.count(),
            "legacy_opportunities": OpportunitySnapshot.objects.count(),
            "legacy_deals": DealSnapshot.objects.count(),
            "phone_opportunities": PhoneOpportunitySnapshot.objects.count(),
            "laptop_opportunities": LaptopOpportunitySnapshot.objects.count(),
            "console_opportunities": ConsoleOpportunitySnapshot.objects.count(),
        }

    def write_summary(self, username, markdown_file, record_count, before, after, recent_data):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Pipeline summary"))
        self.stdout.write(f"Markdown: {markdown_file}")
        self.stdout.write(f"Source: @{username}")
        self.stdout.write(f"Markdown post/reel links: {record_count}")
        self.stdout.write(
            f"Source posts: {after['source_posts']} ({after['source_posts'] - before['source_posts']:+d})"
        )
        self.stdout.write(
            f"Downloaded source images: {after['downloaded_images']} "
            f"({after['downloaded_images'] - before['downloaded_images']:+d})"
        )
        self.stdout.write(f"Pending OCR: {after['pending_ocr']} ({after['pending_ocr'] - before['pending_ocr']:+d})")
        self.stdout.write(f"OCR results: {after['ocr_results']} ({after['ocr_results'] - before['ocr_results']:+d})")
        self.stdout.write(
            f"Source market listings: {after['source_listings']} "
            f"({after['source_listings'] - before['source_listings']:+d})"
        )
        self.stdout.write(f"FX rows: {after['currency_rates']} ({after['currency_rates'] - before['currency_rates']:+d})")
        self.stdout.write(
            f"Legacy opportunities/deals: {after['legacy_opportunities']} / {after['legacy_deals']}"
        )
        self.stdout.write(
            "Clean opportunities phone/laptop/console: "
            f"{after['phone_opportunities']} / {after['laptop_opportunities']} / {after['console_opportunities']}"
        )
        if recent_data:
            self.stdout.write("")
            self.stdout.write(recent_data)

    def validate_ocr_backend(self):
        backend = str(settings.OCR_BACKEND or "").strip().lower()
        if backend not in {"nvidia", "nvidia_vision", "nvidia-vlm", "nim"}:
            raise CommandError(
                f"OCR_BACKEND is set to '{settings.OCR_BACKEND}'. PriceBridge Instagram OCR is NVIDIA-only. "
                "Set NVIDIA_API_KEY or NVIDIA_NIM_API_KEY, then run with OCR_BACKEND=nvidia."
            )
