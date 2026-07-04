#!/usr/bin/env python3
"""Download the first visible Instagram profile-grid images through Chrome CDP.

This started as an Imageye-extension helper. The extension is not required here:
Chrome CDP opens the profile page, extracts the first post/reel thumbnail URLs,
and Python downloads exactly the requested number of images.
"""

from __future__ import annotations

import argparse
import json
import time
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import urlparse

import requests

from chrome_extension_cdp import ChromeCdp, CdpSocket


def username_from_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    return parts[0] if parts else "instagram_profile"


def shortcode_from_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts):
        if part in {"p", "reel", "tv"} and len(parts) > index + 1:
            return parts[index + 1]
    return ""


def load_instagram_cookies(cookie_file: str) -> dict[str, str]:
    jar = MozillaCookieJar(cookie_file)
    jar.load(ignore_discard=True, ignore_expires=True)
    return {cookie.name: cookie.value for cookie in jar if "instagram" in cookie.domain}


def set_browser_cookies(sock: CdpSocket, cookies: dict[str, str]) -> None:
    if not cookies:
        return
    sock.call("Network.enable")
    sock.call(
        "Network.setCookies",
        {
            "cookies": [
                {
                    "name": name,
                    "value": value,
                    "domain": ".instagram.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": name == "sessionid",
                    "sameSite": "None",
                    "url": "https://www.instagram.com/",
                }
                for name, value in cookies.items()
            ]
        },
    )


def extract_image_urls(sock: CdpSocket, limit: int, offset: int = 0) -> list[dict[str, str]]:
    expression = f"""
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
  return JSON.stringify(rows.slice({int(offset)}, {int(offset)} + {int(limit)}));
}})()
"""
    raw = sock.eval(expression)
    return json.loads(raw or "[]")


def download_images(rows: list[dict[str, str]], cookies: dict[str, str], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:139.0) Gecko/20100101 Firefox/139.0",
            "Referer": "https://www.instagram.com/",
        }
    )
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".instagram.com", path="/")

    written = []
    for index, row in enumerate(rows, start=1):
        response = session.get(row["src"], timeout=30)
        response.raise_for_status()
        code = shortcode_from_url(row.get("href", ""))
        filename = f"{code}.jpg" if code else f"instagram_image_{index:02d}.jpg"
        path = output_dir / filename
        path.write_bytes(response.content)
        written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Download first Instagram profile-grid images via Chrome CDP.")
    parser.add_argument("profile_url")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--cookie-file", default="cookies.txt")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--wait", type=float, default=6)
    parser.add_argument("--scroll-steps", type=int, default=4)
    parser.add_argument("--output-dir")
    args = parser.parse_args()

    cookies = load_instagram_cookies(args.cookie_file) if args.cookie_file else {}
    username = username_from_url(args.profile_url)
    output_dir = Path(args.output_dir or f"media/instagram/{username}/manual_images")

    cdp = ChromeCdp(args.host, args.port)
    target = cdp.new_tab("about:blank")
    sock = CdpSocket(target)
    try:
        sock.call("Runtime.enable")
        sock.call("Page.enable")
        set_browser_cookies(sock, cookies)
        sock.call("Page.navigate", {"url": args.profile_url})
        time.sleep(args.wait)
        for step in range(max(args.scroll_steps, 0)):
            sock.eval(f"window.scrollTo(0, Math.min(document.body.scrollHeight, {(step + 1) * 1400}));")
            time.sleep(1.2)
        rows = extract_image_urls(sock, args.limit, args.offset)
    finally:
        sock.close()

    rows = rows[: args.limit]
    if not rows:
        raise SystemExit("No profile-grid image URLs found. Instagram may still be rate-limiting or blocking the page.")

    written = download_images(rows, cookies, output_dir)
    print(json.dumps({"downloaded": [str(path) for path in written], "posts": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
