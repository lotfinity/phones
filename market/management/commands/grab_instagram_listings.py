import json
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from market.models import Country, InstagramPost, Source, SourceType

SCRIPTS_DIR = Path(settings.BASE_DIR) / "scripts"
import sys
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from imageye_download_images import ChromeCdp, CdpSocket  # noqa: E402


def username_from_url(url):
    parts = [p for p in urlparse(url).path.split("/") if p]
    return parts[0] if parts else ""


def shortcode_from_url(url):
    parts = [p for p in urlparse(url).path.split("/") if p]
    for i, part in enumerate(parts):
        if part in {"p", "reel", "tv"} and len(parts) > i + 1:
            return parts[i + 1]
    return ""


class Command(BaseCommand):
    help = "Grab Instagram listings from an open Chrome tab via CDP."

    def add_arguments(self, parser):
        parser.add_argument("--profile-url", default="", help="Instagram profile URL (auto-detected from open tabs if omitted)")
        parser.add_argument("--tab-id", default="", help="Specific Chrome tab ID to use")
        parser.add_argument("--limit", type=int, default=30)
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--scroll-steps", type=int, default=6)
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=9222)
        parser.add_argument("--download-images", action="store_true", default=True)

    def handle(self, *args, **options):
        import urllib.request

        profile_url = options["profile_url"]
        tab_id = options["tab_id"]
        limit = options["limit"]
        offset = options["offset"]

        if not tab_id:
            tabs_raw = urllib.request.urlopen(f"http://{options['host']}:{options['port']}/json/list").read()
            tabs = json.loads(tabs_raw)
            ig_tabs = [t for t in tabs if "instagram.com" in t.get("url", "") and t["type"] == "page"]
            if not ig_tabs:
                raise CommandError("No Instagram tab found in Chrome. Open an Instagram profile page first.")
            if not profile_url:
                profile_url = ig_tabs[0]["url"]
            tab_id = ig_tabs[0]["id"]
            self.stdout.write(f"Found Instagram tab: {profile_url[:80]}")

        username = username_from_url(profile_url)
        if not username:
            raise CommandError(f"Could not extract username from URL: {profile_url}")

        source, _ = Source.objects.get_or_create(
            source_type=SourceType.INSTAGRAM,
            username=username,
            defaults={
                "name": f"Instagram @{username}",
                "country": Country.ALGERIA,
                "profile_url": f"https://www.instagram.com/{username}/",
            },
        )

        cdp = ChromeCdp(options["host"], options["port"])
        target = cdp.new_tab("about:blank")
        sock = CdpSocket(target)
        try:
            sock.call("Runtime.enable")
            sock.call("Page.enable")

            sock.call("Page.navigate", {"url": profile_url})
            time.sleep(5)

            for step in range(options["scroll_steps"]):
                scroll_y = (step + 1) * 1400
                sock.eval(f"window.scrollTo(0, Math.min(document.body.scrollHeight, {scroll_y}));")
                time.sleep(1.5)

            extract_js = f"""
            (() => {{
                const seen = new Set();
                const rows = [];
                const anchors = Array.from(document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]'));
                for (const anchor of anchors) {{
                    const img = anchor.querySelector('img');
                    const src = img && (img.currentSrc || img.src);
                    if (!src || seen.has(src)) continue;
                    seen.add(src);
                    rows.push({{
                        href: new URL(anchor.getAttribute('href'), location.href).href,
                        src,
                        alt: img.alt || ''
                    }});
                }}
                return JSON.stringify(rows.slice({offset}, {offset} + {limit}));
            }})()
            """
            raw = sock.eval(extract_js)
            rows = json.loads(raw or "[]")
        finally:
            sock.close()

        if not rows:
            raise CommandError("No posts found on the profile page. Try scrolling more or check if the page loaded.")

        self.stdout.write(f"Found {len(rows)} posts on profile grid.")

        local_paths = {}
        if options["download_images"]:
            output_dir = Path(settings.MEDIA_ROOT) / "instagram" / username / "cdp_images"
            output_dir.mkdir(parents=True, exist_ok=True)
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                "Referer": "https://www.instagram.com/",
            })
            for row in rows:
                try:
                    resp = session.get(row["src"], timeout=30)
                    resp.raise_for_status()
                    code = shortcode_from_url(row.get("href", ""))
                    filename = f"{code}.jpg" if code else f"ig_{len(local_paths)+1:03d}.jpg"
                    path = output_dir / filename
                    path.write_bytes(resp.content)
                    local_paths[row["href"]] = str(path)
                    self.stdout.write(f"  Downloaded: {filename}")
                except Exception as exc:
                    self.stdout.write(f"  Failed to download {row.get('href', '?')}: {exc}")

        saved = 0
        for row in rows:
            post_url = row["href"]
            image_path = local_paths.get(post_url, "")
            existing = InstagramPost.objects.filter(post_url=post_url).first()
            if existing and not image_path:
                image_path = existing.thumbnail_local_path or existing.media_local_path
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
                        "collection_method": "chrome_cdp_grab",
                    },
                    "collected_at": timezone.now(),
                    "needs_ocr": bool(image_path),
                },
            )
            saved += 1

        total = InstagramPost.objects.filter(source=source).count()
        needs_ocr = InstagramPost.objects.filter(source=source, needs_ocr=True, ocr_processed=False).count()
        self.stdout.write(self.style.SUCCESS(
            f"Saved {saved} posts for @{username}. Total: {total} posts, {needs_ocr} pending OCR."
        ))
