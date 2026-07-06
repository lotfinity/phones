import re
from pathlib import Path
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError

from market.models import InstagramPost, MarketListing, SourceType


IMAGE_LINK_RE = re.compile(
    r"!\[[^\]]*\]\((https?://[^)]+)\)\]\((https://www\.instagram\.com/[^)]+)\)",
    flags=re.S,
)
SHORTCODE_RE = re.compile(r"/(?:p|reel)/([^/]+)/?")


def image_basename(url):
    return Path(urlparse(url).path).name


def manual_suffix(filename):
    return re.sub(r"^imgi_\d+_", "", Path(filename).name)


def shortcode_from_url(url):
    match = SHORTCODE_RE.search(url or "")
    return match.group(1) if match else ""


class Command(BaseCommand):
    help = "Match manually queued Instagram images to real post/reel URLs from a Markdown profile export."

    def add_arguments(self, parser):
        parser.add_argument("markdown_files", nargs="+")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        url_by_image = {}
        for raw_path in options["markdown_files"]:
            path = Path(raw_path)
            if not path.exists():
                raise CommandError(f"Markdown file not found: {path}")
            text = path.read_text(errors="ignore")
            for image_url, post_url in IMAGE_LINK_RE.findall(text):
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
