import re
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from market.models import Country, InstagramPost, MarketListing, Source, SourceType


IMAGE_LINK_RE = re.compile(
    r"!\[(.*?)\]\((https?://[^)]+)\)\]\((https://www\.instagram\.com/[^)]+)\)",
    flags=re.S,
)
SHORTCODE_RE = re.compile(r"/(?P<kind>p|reel)/(?P<shortcode>[^/]+)/?")
SOURCE_RE = re.compile(r'^source:\s*"?(https://www\.instagram\.com/[^"\n]+)"?', flags=re.M)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
USER_AGENT = "Mozilla/5.0 (compatible; PriceBridge Instagram markdown importer)"


def image_basename(url):
    return Path(urlparse(url).path).name


def manual_suffix(filename):
    return re.sub(r"^imgi_\d+_", "", Path(filename).name)


def shortcode_from_url(url):
    match = SHORTCODE_RE.search(url or "")
    return match.group("shortcode") if match else ""


def media_kind_from_url(url):
    match = SHORTCODE_RE.search(url or "")
    return match.group("kind") if match else "p"


def canonical_post_url(url):
    shortcode = shortcode_from_url(url)
    if not shortcode:
        return url
    return f"https://www.instagram.com/{media_kind_from_url(url)}/{shortcode}/"


def username_from_url(url):
    parts = [part for part in urlparse(url or "").path.split("/") if part]
    if parts and parts[0] not in {"p", "reel", "stories"}:
        return parts[0]
    return ""


def records_from_markdown(path):
    text = path.read_text(errors="ignore")
    records = []
    seen = set()
    for alt_text, image_url, post_url in IMAGE_LINK_RE.findall(text):
        shortcode = shortcode_from_url(post_url)
        if not shortcode:
            continue
        canonical_url = canonical_post_url(post_url)
        if canonical_url in seen:
            continue
        seen.add(canonical_url)
        records.append(
            {
                "alt_text": " ".join(alt_text.split()),
                "image_url": image_url,
                "image_basename": image_basename(image_url),
                "post_url": canonical_url,
                "raw_post_url": post_url,
                "shortcode": shortcode,
                "media_kind": media_kind_from_url(post_url),
            }
        )
    return records


def source_url_from_markdown(path):
    match = SOURCE_RE.search(path.read_text(errors="ignore"))
    return match.group(1) if match else ""


def image_extension(url):
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in IMAGE_EXTENSIONS else ".jpg"


def download_image(url, destination):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        destination.write_bytes(response.read())


class Command(BaseCommand):
    help = "Match manually queued Instagram images to real post/reel URLs from a Markdown profile export."

    def add_arguments(self, parser):
        parser.add_argument("markdown_files", nargs="+")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--username", default="")
        parser.add_argument(
            "--queue-new",
            action="store_true",
            help="Create or update InstagramPost rows from real post links in the Markdown export.",
        )
        parser.add_argument(
            "--download-images",
            action="store_true",
            help="Download linked images into MEDIA_ROOT/instagram/<username>/manual_images.",
        )
        parser.add_argument(
            "--reprocess-existing",
            action="store_true",
            help="Mark updated existing posts for OCR again when they have a local image.",
        )

    def handle(self, *args, **options):
        if options["queue_new"]:
            self.queue_from_markdown(options)
            return

        url_by_image = {}
        for raw_path in options["markdown_files"]:
            path = Path(raw_path)
            if not path.exists():
                raise CommandError(f"Markdown file not found: {path}")
            text = path.read_text(errors="ignore")
            for _, image_url, post_url in IMAGE_LINK_RE.findall(text):
                basename = image_basename(image_url)
                if basename:
                    url_by_image[basename] = post_url

        if not url_by_image:
            self.stdout.write("No Instagram image/post pairs found.")
            return

        posts = InstagramPost.objects.filter(
            source__source_type=SourceType.INSTAGRAM,
            post_url__contains="manual_image=",
        ).exclude(media_local_path="")

        dry_run = options["dry_run"]
        matched_posts = 0
        updated_posts = 0
        updated_listings = 0

        for post in posts.iterator():
            suffix = manual_suffix(post.media_local_path or post.thumbnail_local_path)
            real_url = url_by_image.get(suffix)
            if not real_url:
                continue

            matched_posts += 1
            shortcode = shortcode_from_url(real_url) or post.shortcode
            self.stdout.write(f"{Path(post.media_local_path).name} -> {real_url}")

            if not dry_run:
                post.post_url = real_url
                post.shortcode = shortcode
                post.save(update_fields=["post_url", "shortcode"])
                updated_posts += 1

                listing_qs = MarketListing.objects.filter(
                    source_type=SourceType.INSTAGRAM,
                    image_path__iendswith=Path(post.media_local_path).name,
                )
                updated_listings += listing_qs.update(listing_url=real_url)

        action = "Would update" if dry_run else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {updated_posts if not dry_run else matched_posts} Instagram posts "
                f"and {updated_listings} listings from {len(url_by_image)} Markdown image links."
            )
        )

    def queue_from_markdown(self, options):
        dry_run = options["dry_run"]
        markdown_paths = [Path(raw_path) for raw_path in options["markdown_files"]]
        for path in markdown_paths:
            if not path.exists():
                raise CommandError(f"Markdown file not found: {path}")

        records = []
        inferred_username = ""
        for path in markdown_paths:
            records_for_path = records_from_markdown(path)
            for record in records_for_path:
                record["markdown_file"] = str(path)
            records.extend(records_for_path)
            inferred_username = inferred_username or username_from_url(source_url_from_markdown(path))
            if not inferred_username and records_for_path:
                inferred_username = username_from_url(records_for_path[0]["raw_post_url"])

        if not records:
            self.stdout.write("No Instagram image/post pairs found.")
            return

        username = options["username"].strip().lstrip("@") or inferred_username
        if not username:
            raise CommandError("--username is required when it cannot be inferred from Markdown.")

        if dry_run:
            existing = InstagramPost.objects.filter(
                source__source_type=SourceType.INSTAGRAM,
                source__username=username,
                shortcode__in=[record["shortcode"] for record in records],
            ).count()
            self.stdout.write(
                f"Would import/update {len(records)} Markdown posts for @{username}; "
                f"{existing} already match by shortcode."
            )
            return

        source, _ = Source.objects.get_or_create(
            source_type=SourceType.INSTAGRAM,
            username=username,
            defaults={
                "name": f"Instagram @{username}",
                "country": Country.ALGERIA,
                "profile_url": f"https://www.instagram.com/{username}/",
            },
        )

        output_dir = Path(settings.MEDIA_ROOT) / "instagram" / username / "manual_images"
        if options["download_images"]:
            output_dir.mkdir(parents=True, exist_ok=True)

        queued = 0
        updated = 0
        requeued = 0
        downloaded = 0
        failed_downloads = 0
        now = timezone.now()

        for record in records:
            destination = output_dir / f"{record['shortcode']}{image_extension(record['image_url'])}"
            image_path = ""
            if options["download_images"]:
                if not destination.exists():
                    try:
                        download_image(record["image_url"], destination)
                        downloaded += 1
                    except (OSError, URLError) as exc:
                        failed_downloads += 1
                        self.stderr.write(f"Failed image download for {record['post_url']}: {exc}")
                if destination.exists():
                    image_path = str(destination)

            existing = (
                InstagramPost.objects.filter(source=source, shortcode=record["shortcode"]).order_by("id").first()
                or InstagramPost.objects.filter(post_url=record["post_url"]).order_by("id").first()
                or InstagramPost.objects.filter(post_url=record["raw_post_url"]).order_by("id").first()
            )

            media_local_path = image_path or (existing.media_local_path if existing else "")
            thumbnail_local_path = image_path or (existing.thumbnail_local_path if existing else "")
            should_reprocess = bool(media_local_path) and (not existing or options["reprocess_existing"])
            if existing and should_reprocess:
                requeued += 1

            metadata = existing.raw_metadata if existing and isinstance(existing.raw_metadata, dict) else {}
            defaults = {
                "source": source,
                "shortcode": record["shortcode"],
                "caption": existing.caption if existing else "",
                "media_local_path": media_local_path,
                "thumbnail_local_path": thumbnail_local_path,
                "raw_metadata": {
                    **metadata,
                    "collection_method": "markdown_profile_export",
                    "markdown_file": record["markdown_file"],
                    "image_url": record["image_url"],
                    "image_basename": record["image_basename"],
                    "raw_post_url": record["raw_post_url"],
                    "media_kind": record["media_kind"],
                    "alt_text": record["alt_text"],
                },
                "collected_at": now,
                "needs_ocr": should_reprocess if should_reprocess else (existing.needs_ocr if existing else False),
                "ocr_processed": False if should_reprocess else (existing.ocr_processed if existing else False),
            }

            if existing:
                defaults["post_url"] = record["post_url"]
                for field, value in defaults.items():
                    setattr(existing, field, value)
                existing.save(update_fields=list(defaults))
                updated += 1
            else:
                InstagramPost.objects.create(post_url=record["post_url"], **defaults)
                queued += 1

        pending = InstagramPost.objects.filter(source=source, needs_ocr=True, ocr_processed=False).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Queued {queued} new, updated {updated}, and requeued {requeued} posts for @{username}; "
                f"downloaded {downloaded}, failed downloads {failed_downloads}; source pending OCR: {pending}."
            )
        )
