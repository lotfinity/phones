import shutil
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from market.models import Country, InstagramPost, Source, SourceType


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def image_size(path):
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except Exception:
        return 0, 0


class Command(BaseCommand):
    help = "Queue a local folder of manually downloaded Instagram images for OCR."

    def add_arguments(self, parser):
        parser.add_argument("folder")
        parser.add_argument("--username", required=True)
        parser.add_argument("--min-width", type=int, default=500)
        parser.add_argument("--min-height", type=int, default=500)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        folder = Path(options["folder"]).expanduser()
        if not folder.is_dir():
            raise CommandError(f"Folder does not exist: {folder}")

        username = options["username"].strip().lstrip("@")
        if not username:
            raise CommandError("--username is required.")

        source, _ = Source.objects.get_or_create(
            source_type=SourceType.INSTAGRAM,
            username=username,
            defaults={
                "name": f"Instagram @{username}",
                "country": Country.ALGERIA,
                "profile_url": f"https://www.instagram.com/{username}/",
            },
        )

        candidates = []
        skipped = 0
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                skipped += 1
                continue
            width, height = image_size(path)
            if width < options["min_width"] or height < options["min_height"]:
                skipped += 1
                continue
            candidates.append((path, width, height))

        if options["limit"]:
            candidates = candidates[: options["limit"]]

        if options["dry_run"]:
            self.stdout.write(
                f"Would queue {len(candidates)} images for @{username}; skipped {skipped} files."
            )
            return

        output_dir = Path(settings.MEDIA_ROOT) / "instagram" / username / "manual_folder_images"
        output_dir.mkdir(parents=True, exist_ok=True)

        queued = 0
        updated = 0
        now = timezone.now()
        for path, width, height in candidates:
            destination = output_dir / path.name
            if path.resolve() != destination.resolve():
                shutil.copy2(path, destination)

            quoted_name = quote(path.name)
            post_url = f"https://www.instagram.com/{username}/?manual_image={quoted_name}"
            _, created = InstagramPost.objects.update_or_create(
                post_url=post_url,
                defaults={
                    "source": source,
                    "shortcode": path.stem[:80],
                    "caption": "",
                    "media_local_path": str(destination),
                    "thumbnail_local_path": str(destination),
                    "raw_metadata": {
                        "collection_method": "manual_download_folder",
                        "original_path": str(path),
                        "filename": path.name,
                        "width": width,
                        "height": height,
                        "note": "Manual image import; post URL is a profile-scoped local image identifier.",
                    },
                    "collected_at": now,
                    "needs_ocr": True,
                    "ocr_processed": False,
                },
            )
            if created:
                queued += 1
            else:
                updated += 1

        pending = InstagramPost.objects.filter(source=source, needs_ocr=True, ocr_processed=False).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Queued {queued} new and updated {updated} images for @{username}; "
                f"skipped {skipped}; source pending OCR: {pending}."
            )
        )
