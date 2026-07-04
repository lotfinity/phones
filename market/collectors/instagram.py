import datetime as dt
import json
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone

from market.models import Country, InstagramPost, Source, SourceType


def normalize_instagram_username(username_or_url):
    value = username_or_url.strip().rstrip("/")
    if "instagram.com" not in value:
        return value.lstrip("@")
    parsed = urlparse(value if value.startswith("http") else f"https://{value}")
    parts = [part for part in parsed.path.split("/") if part]
    return parts[0].lstrip("@") if parts else ""


def load_instagram_cookies(loader, cookie_file):
    jar = MozillaCookieJar(cookie_file)
    jar.load(ignore_discard=True, ignore_expires=True)
    cookies = {cookie.name: cookie.value for cookie in jar if "instagram" in cookie.domain}
    if not cookies:
        raise RuntimeError(f"No Instagram cookies found in {cookie_file}.")
    loader.context.update_cookies(cookies)
    csrf = cookies.get("csrftoken")
    if csrf:
        loader.context._session.headers.update({"X-CSRFToken": csrf})
    login_username = loader.test_login()
    if not login_username:
        raise RuntimeError("Instagram cookies loaded, but Instaloader does not consider the session logged in.")
    loader.context.username = login_username
    return sorted(cookies)


def crawl_profile(username_or_url, days=60, limit=300, stdout=None):
    try:
        import instaloader
    except ImportError as exc:
        raise RuntimeError("Instaloader is not installed. Install requirements.txt first.") from exc

    username = normalize_instagram_username(username_or_url)
    if not username:
        raise ValueError("Instagram username or profile URL is required.")

    loader = instaloader.Instaloader(
        download_pictures=True,
        download_videos=False,
        download_video_thumbnails=True,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        dirname_pattern=str(Path(settings.MEDIA_ROOT) / "instagram" / "{profile}"),
    )
    if settings.INSTAGRAM_SESSION_PATH:
        loader.load_session_from_file(username, settings.INSTAGRAM_SESSION_PATH)
    elif settings.INSTAGRAM_COOKIE_FILE:
        cookie_names = load_instagram_cookies(loader, settings.INSTAGRAM_COOKIE_FILE)
        if stdout:
            stdout.write(f"Loaded Instagram cookies: {', '.join(cookie_names)}")

    source, _ = Source.objects.get_or_create(
        source_type=SourceType.INSTAGRAM,
        username=username,
        defaults={
            "name": f"Instagram @{username}",
            "country": Country.ALGERIA,
            "profile_url": f"https://www.instagram.com/{username}/",
        },
    )

    cutoff = timezone.now() - dt.timedelta(days=days)
    profile = instaloader.Profile.from_username(loader.context, username)
    created_or_updated = 0

    for index, post in enumerate(profile.get_posts(), start=1):
        posted_at = timezone.make_aware(post.date_utc, dt.timezone.utc)
        if posted_at < cutoff or index > limit:
            break

        target = Path(settings.MEDIA_ROOT) / "instagram" / username
        try:
            loader.download_post(post, target=username)
        except Exception as exc:
            if stdout:
                stdout.write(f"Could not download media for {post.shortcode}: {exc}")

        media_path = ""
        thumb_path = ""
        for candidate in sorted(target.glob(f"*{post.shortcode}*")):
            if candidate.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".mp4"}:
                media_path = str(candidate)
                if candidate.suffix.lower() != ".mp4":
                    thumb_path = str(candidate)
                break

        metadata = {
            "shortcode": post.shortcode,
            "typename": post.typename,
            "is_video": post.is_video,
            "likes": post.likes,
            "comments": post.comments,
            "url": post.url,
        }
        InstagramPost.objects.update_or_create(
            post_url=f"https://www.instagram.com/p/{post.shortcode}/",
            defaults={
                "source": source,
                "shortcode": post.shortcode,
                "posted_at": posted_at,
                "caption": post.caption or "",
                "media_local_path": media_path,
                "thumbnail_local_path": thumb_path,
                "raw_metadata": json.loads(json.dumps(metadata, default=str)),
                "needs_ocr": bool(media_path or thumb_path),
            },
        )
        created_or_updated += 1

    return created_or_updated
