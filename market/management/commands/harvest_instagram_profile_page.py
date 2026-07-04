from pathlib import Path
import sys
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from market.models import Country, InstagramPost, Source, SourceType


SCRIPTS_DIR = Path(settings.BASE_DIR) / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from imageye_download_images import (  # noqa: E402
    ChromeCdp,
    CdpSocket,
    download_images,
    extract_image_urls,
    load_instagram_cookies,
    set_browser_cookies,
    username_from_url,
)


def shortcode_from_url(url):
    parts = [part for part in urlparse(url).path.split("/") if part]
    for index, part in enumerate(parts):
        if part in {"p", "reel", "tv"} and len(parts) > index + 1:
            return parts[index + 1]
    return ""


class Command(BaseCommand):
    help = "Harvest visible Instagram profile page post/reel URLs via Chrome CDP."

    def add_arguments(self, parser):
        parser.add_argument("profile_url")
        parser.add_argument("--limit", type=int, default=5)
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--cookie-file", default=settings.INSTAGRAM_COOKIE_FILE)
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=9222)
        parser.add_argument("--wait", type=float, default=6)
        parser.add_argument("--scroll-steps", type=int, default=4)
        parser.add_argument("--download-images", action="store_true")

    def handle(self, *args, **options):
        profile_url = options["profile_url"]
        username = username_from_url(profile_url)
        cookies = load_instagram_cookies(options["cookie_file"]) if options["cookie_file"] else {}

        source, _ = Source.objects.get_or_create(
            source_type=SourceType.INSTAGRAM,
            username=username,
            defaults={
                "name": f"Instagram @{username}",
                "country": Country.ALGERIA,
                "profile_url": profile_url,
            },
        )

        try:
            cdp = ChromeCdp(options["host"], options["port"])
            target = cdp.new_tab("about:blank")
            sock = CdpSocket(target)
        except SystemExit as exc:
            raise CommandError(str(exc)) from exc

        try:
            sock.call("Runtime.enable")
            sock.call("Page.enable")
            set_browser_cookies(sock, cookies)
            sock.call("Page.navigate", {"url": profile_url})
            import time

            time.sleep(options["wait"])
            for step in range(max(options["scroll_steps"], 0)):
                sock.eval(f"window.scrollTo(0, Math.min(document.body.scrollHeight, {(step + 1) * 1400}));")
                time.sleep(1.2)
            rows = extract_image_urls(sock, options["limit"], options["offset"])
        finally:
            sock.close()

        rows = rows[: options["limit"]]
        if not rows:
            raise CommandError("No profile-grid post or reel URLs found.")

        local_paths = {}
        if options["download_images"]:
            output_dir = Path(settings.MEDIA_ROOT) / "instagram" / username / "manual_images"
            for row, path in zip(rows, download_images(rows, cookies, output_dir), strict=False):
                local_paths[row["href"]] = str(path)

        saved = 0
        for row in rows:
            post_url = row["href"]
            image_path = local_paths.get(post_url, "")
            existing = InstagramPost.objects.filter(post_url=post_url).first()
            if existing and not image_path:
                image_path = existing.thumbnail_local_path or existing.media_local_path
            ocr_processed = existing.ocr_processed if existing else False
            needs_ocr = existing.needs_ocr if existing else True
            if image_path and not ocr_processed:
                needs_ocr = True
            InstagramPost.objects.update_or_create(
                post_url=post_url,
                defaults={
                    "source": source,
                    "shortcode": shortcode_from_url(post_url),
                    "caption": row.get("alt", ""),
                    "media_local_path": image_path,
                    "thumbnail_local_path": image_path,
                    "raw_metadata": {
                        "profile_url": profile_url,
                        "thumbnail_url": row.get("src", ""),
                        "alt": row.get("alt", ""),
                        "collection_method": "chrome_cdp_profile_page",
                    },
                    "collected_at": timezone.now(),
                    "needs_ocr": needs_ocr,
                    "ocr_processed": ocr_processed,
                },
            )
            saved += 1

        self.stdout.write(self.style.SUCCESS(f"Saved {saved} Instagram profile-page URLs for @{username}."))
