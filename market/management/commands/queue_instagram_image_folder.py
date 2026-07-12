import shutil
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from market.models import Country, InstagramPost, Source, SourceType


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
SHORTCODE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def image_size(path):
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except Exception:
        return 0, 0


def looks_like_shortcode(value):
    return 5 <= len(value) <= 32 and all(char in SHORTCODE_CHARS for char in value)


def existing_post_for_image(source, path):
    filename = path.name
    stem = path.stem
    qs = InstagramPost.objects.filter(source=source)
    existing = (
        qs.filter(
            Q(media_local_path__iendswith=f"/{filename}")
            | Q(media_local_path__iendswith=f"\\{filename}")
            | Q(media_local_path__iexact=filename)
            | Q(thumbnail_local_path__iendswith=f"/{filename}")
            | Q(thumbnail_local_path__iendswith=f"\\{filename}")
            | Q(thumbnail_local_path__iexact=filename)
        )
        .order_by("id")
        .first()
    )
    if existing:
        return existing
    if looks_like_shortcode(stem):
        return (
            qs.filter(shortcode=stem, media_local_path__contains="/manual_images/")
            .order_by("id")
            .first()
        )
    return None


def default_post_url(username, filename):
    stem = Path(filename).stem
    if looks_like_shortcode(stem):
        return f"https://www.instagram.com/p/{stem}/"
    quoted_name = quote(filename)
    return f"https://www.instagram.com/{username}/?manual_image={quoted_name}"


def output_directory_for(folder, username):
    profile_dir = (Path(settings.MEDIA_ROOT) / "instagram" / username).resolve()
    try:
        folder.resolve().relative_to(profile_dir)
        return folder
    except (OSError, ValueError):
        return profile_dir / "manual_folder_images"


class Command(BaseCommand):
    help = "Queue a local folder of manually downloaded Instagram images for OCR."

    def add_arguments(self, parser):
        parser.add_argument("folder")
        parser.add_argument("--username", required=True)
        parser.add_argument("--min-width", type=int, default=500)
        parser.add_argument("--min-height", type=int, default=500)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--reprocess-existing",
            action="store_true",
            help="Mark updated existing images for OCR again without creating duplicate posts.",
        )

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
                f"Would queue/update {len(candidates)} images for @{username}; skipped {skipped} files."
            )
            return

        output_dir = output_directory_for(folder, username)
        output_dir.mkdir(parents=True, exist_ok=True)

        queued = 0
        updated = 0
        requeued = 0
        now = timezone.now()
        for path, width, height in candidates:
            destination = output_dir / path.name
            if path.resolve() != destination.resolve():
                shutil.copy2(path, destination)

            existing = existing_post_for_image(source, path)
            needs_ocr = True
            ocr_processed = False
            if existing and not options["reprocess_existing"]:
                needs_ocr = existing.needs_ocr
                ocr_processed = existing.ocr_processed
            elif existing:
                requeued += 1

            post_url = existing.post_url if existing else default_post_url(username, path.name)
            defaults = {
                "source": source,
                "shortcode": (existing.shortcode if existing and existing.shortcode else path.stem[:80]),
                "caption": existing.caption if existing else "",
                "media_local_path": str(destination),
                "thumbnail_local_path": str(destination),
                "raw_metadata": {
                    **(existing.raw_metadata if existing and isinstance(existing.raw_metadata, dict) else {}),
                    "collection_method": "manual_download_folder",
                    "original_path": str(path),
                    "filename": path.name,
                    "width": width,
                    "height": height,
                    "note": "Manual image import/update; matched by existing media filename before creating a new post.",
                },
                "collected_at": now,
                "needs_ocr": needs_ocr,
                "ocr_processed": ocr_processed,
            }
            if existing:
                for field, value in defaults.items():
                    setattr(existing, field, value)
                existing.save(update_fields=list(defaults))
                created = False
            else:
                _, created = InstagramPost.objects.update_or_create(
                    post_url=post_url,
                    defaults=defaults,
                )
            if created:
                queued += 1
            else:
                updated += 1

        pending = InstagramPost.objects.filter(source=source, needs_ocr=True, ocr_processed=False).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Queued {queued} new, updated {updated}, and requeued {requeued} images for @{username}; "
                f"skipped {skipped}; source pending OCR: {pending}."
            )
        )
