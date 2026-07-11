import ipaddress
import logging
import os
import socket
from urllib.parse import urljoin, urlsplit

import requests
from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.http import http_date
from django.views.decorators.http import require_GET

from market.models import ConsoleListing, LaptopListing, PhoneListing

logger = logging.getLogger(__name__)

CLEAN_LISTING_MODELS = {
    "phone": PhoneListing,
    "laptop": LaptopListing,
    "console": ConsoleListing,
}

ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/avif",
}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 3
SUCCESS_CACHE_SECONDS = 21600  # 6 hours
FAILURE_CACHE_SECONDS = 60  # 1 minute


def _sniff_image_type(payload):
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp"
    if len(payload) >= 16 and payload[4:8] == b"ftyp" and payload[8:12] in {b"avif", b"avis"}:
        return "image/avif"
    return ""


def _normalize_image_url(url):
    """Normalize a raw image URL string safely.

    Returns a cleaned URL string, or empty string if the input is unusable.
    Does NOT validate reachability -- that is done elsewhere.
    """
    if not url:
        return ""
    url = url.strip()
    if not url:
        return ""
    # Protocol-relative URLs: //example.com/img.jpg -> https://example.com/img.jpg
    if url.startswith("//"):
        url = "https:" + url
    # Reject data: and javascript: schemes
    parsed = urlsplit(url)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return ""
    # Reject URLs with embedded credentials
    if parsed.username or parsed.password:
        return ""
    return url


def _is_local_filesystem_path(url):
    """Return True if the URL looks like a local filesystem path."""
    if not url:
        return False
    # Absolute paths
    if url.startswith("/"):
        return True
    # Relative paths that resolve to MEDIA_ROOT
    # Check if it starts with a known media prefix
    if url.startswith("media/"):
        return True
    return False


def _resolve_local_image_path(url):
    """Resolve a local filesystem path to an absolute path and verify existence.

    Returns (absolute_path, media_relative_path) or raises ValueError.
    media_relative_path is used for cache-key generation.
    """
    if not url:
        raise ValueError("Empty image path")

    media_root = settings.MEDIA_ROOT

    if os.path.isabs(url):
        abs_path = os.path.normpath(url)
    else:
        # Relative path -- resolve against MEDIA_ROOT
        abs_path = os.path.normpath(os.path.join(media_root, url))

    # Security: the resolved path must stay within MEDIA_ROOT
    if not abs_path.startswith(os.path.normpath(media_root)):
        raise ValueError("Image path escapes media root")

    if not os.path.isfile(abs_path):
        raise ValueError("Local image file not found")

    # Compute a media-relative path for cache keys
    try:
        rel_path = os.path.relpath(abs_path, media_root)
    except ValueError:
        rel_path = os.path.basename(abs_path)

    return abs_path, rel_path


def _serve_local_image(abs_path, rel_path, updated_at=None):
    """Serve a local image file directly from disk."""
    with open(abs_path, "rb") as fh:
        payload = fh.read()

    if len(payload) > MAX_IMAGE_BYTES:
        raise ValueError("Local image exceeds size limit")

    content_type = _sniff_image_type(payload)
    if not content_type:
        # Fall back to extension-based detection
        ext = os.path.splitext(abs_path)[1].lower()
        ext_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".avif": "image/avif",
        }
        content_type = ext_map.get(ext, "application/octet-stream")
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise ValueError("Local file is not a supported raster image")

    response = HttpResponse(payload, content_type=content_type)
    response["Cache-Control"] = f"public, max-age={SUCCESS_CACHE_SECONDS}"
    response["X-Content-Type-Options"] = "nosniff"
    if updated_at:
        response["Last-Modified"] = http_date(updated_at.timestamp())
    return response


def _validate_public_http_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Unsupported image URL")

    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ValueError("Image host could not be resolved") from exc

    for entry in addresses:
        address = ipaddress.ip_address(entry[4][0])
        if not address.is_global:
            raise ValueError("Image host is not public")
    return parsed


def _download_image(url, *, referer=""):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/png,image/jpeg,image/gif,*/*;q=0.7",
    }
    if referer:
        headers["Referer"] = referer

    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        _validate_public_http_url(current_url)
        response = requests.get(
            current_url,
            headers=headers,
            stream=True,
            allow_redirects=False,
            timeout=(4, 10),
        )

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise ValueError("Image redirect had no destination")
            current_url = urljoin(current_url, location)
            continue

        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()

        declared_size = response.headers.get("Content-Length")
        if declared_size and int(declared_size) > MAX_IMAGE_BYTES:
            response.close()
            raise ValueError("Remote image is too large")

        chunks = []
        size = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_IMAGE_BYTES:
                response.close()
                raise ValueError("Remote image exceeded the size limit")
            chunks.append(chunk)
        response.close()
        payload = b"".join(chunks)
        if content_type == "image/jpg":
            content_type = "image/jpeg"
        if content_type not in ALLOWED_IMAGE_TYPES:
            content_type = _sniff_image_type(payload)
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise ValueError("Remote resource is not a supported raster image")
        return payload, content_type

    raise ValueError("Too many image redirects")


def _collect_image_candidates(listing):
    """Gather image URL candidates from listing and its raw_listing.

    Returns a list of (candidate_url, candidate_label) tuples in priority order.
    Deduplicates equivalent URLs.
    """
    candidates = []
    seen = set()

    def _add(url, label):
        url = _normalize_image_url(url)
        if not url or url in seen:
            return
        seen.add(url)
        candidates.append((url, label))

    # 1. listing.image_url (highest priority)
    _add(getattr(listing, "image_url", ""), "listing.image_url")

    # 2. raw_listing.image_url
    raw = getattr(listing, "raw_listing", None)
    if raw:
        _add(getattr(raw, "image_url", ""), "raw_listing.image_url")

    return candidates


def _build_referer(listing):
    """Extract a safe referer origin from the listing URL."""
    listing_url = (
        getattr(listing, "listing_url", "")
        or (getattr(listing.raw_listing, "listing_url", "") if getattr(listing, "raw_listing", None) else "")
        or ""
    ).strip()
    if listing_url:
        parsed_listing = urlsplit(listing_url)
        if parsed_listing.scheme in {"http", "https"} and parsed_listing.netloc:
            return f"{parsed_listing.scheme}://{parsed_listing.netloc}/"
    return ""


def _log_image_fetch(category, pk, *, event, candidate_num=0, hostname="", upstream_status=0,
                     content_type="", exception_type="", url=""):
    """Structured logging for image fetch operations."""
    safe_url = url
    # Never log query-string secrets or full signed tokens
    if "?" in safe_url:
        safe_url = safe_url.split("?")[0] + "?[redacted]"
    logger.info(
        "clean_listing_image event=%s category=%s pk=%s candidate=%d "
        "host=%s status=%d content_type=%s exception=%s url=%s",
        event, category, pk, candidate_num,
        hostname, upstream_status, content_type, exception_type, safe_url,
    )


def _try_fetch_image(candidates, referer, category, pk):
    """Try to fetch an image from a list of candidates.

    Returns (payload, content_type) or raises ValueError.
    """
    last_error = None

    for idx, (candidate_url, label) in enumerate(candidates, 1):
        parsed = urlsplit(candidate_url)
        hostname = parsed.hostname or ""

        # Try with referer first
        try:
            payload, content_type = _download_image(candidate_url, referer=referer)
            _log_image_fetch(
                category, pk, event="fetch_ok",
                candidate_num=idx, hostname=hostname,
                content_type=content_type, url=candidate_url,
            )
            return payload, content_type
        except (requests.RequestException, ValueError, OSError) as exc:
            last_error = exc
            _log_image_fetch(
                category, pk, event="fetch_fail",
                candidate_num=idx, hostname=hostname,
                exception_type=type(exc).__name__, url=candidate_url,
            )

            # If 403 and we have a referer, retry without it
            if "403" in str(exc) or "Forbidden" in str(exc):
                if referer:
                    try:
                        payload, content_type = _download_image(candidate_url, referer="")
                        _log_image_fetch(
                            category, pk, event="fetch_ok_no_referer",
                            candidate_num=idx, hostname=hostname,
                            content_type=content_type, url=candidate_url,
                        )
                        return payload, content_type
                    except (requests.RequestException, ValueError, OSError) as exc2:
                        last_error = exc2
                        _log_image_fetch(
                            category, pk, event="fetch_fail_no_referer",
                            candidate_num=idx, hostname=hostname,
                            exception_type=type(exc2).__name__, url=candidate_url,
                        )

    raise ValueError(f"All image candidates failed: {last_error}")


@require_GET
def clean_listing_image(request, category, pk):
    model = CLEAN_LISTING_MODELS.get(category)
    if model is None:
        raise Http404("Unknown clean listing category")

    listing = get_object_or_404(model.objects.select_related("raw_listing"), pk=pk)

    # Collect all image candidates
    candidates = _collect_image_candidates(listing)
    if not candidates:
        _log_image_fetch(category, pk, event="no_candidates")
        raise Http404("No image stored for this listing")

    referer = _build_referer(listing)
    updated_at = getattr(listing, "updated_at", None) or getattr(listing, "observed_at", None)

    # Try each candidate
    for idx, (candidate_url, label) in enumerate(candidates, 1):
        # Local filesystem path
        if _is_local_filesystem_path(candidate_url):
            try:
                abs_path, rel_path = _resolve_local_image_path(candidate_url)
                response = _serve_local_image(abs_path, rel_path, updated_at=updated_at)
                _log_image_fetch(
                    category, pk, event="local_ok",
                    candidate_num=idx, url=candidate_url,
                )
                return response
            except (ValueError, OSError) as exc:
                _log_image_fetch(
                    category, pk, event="local_fail",
                    candidate_num=idx,
                    exception_type=type(exc).__name__, url=candidate_url,
                )
                continue

        # HTTP/HTTPS URL
        parsed = urlsplit(candidate_url)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            try:
                payload, content_type = _try_fetch_image(
                    [(candidate_url, label)], referer, category, pk
                )
                response = HttpResponse(payload, content_type=content_type)
                response["Cache-Control"] = f"public, max-age={SUCCESS_CACHE_SECONDS}"
                response["X-Content-Type-Options"] = "nosniff"
                if updated_at:
                    response["Last-Modified"] = http_date(updated_at.timestamp())
                return response
            except (requests.RequestException, ValueError, OSError) as exc:
                _log_image_fetch(
                    category, pk, event="candidate_failed",
                    candidate_num=idx,
                    exception_type=type(exc).__name__, url=candidate_url,
                )
                continue

    # All candidates failed
    _log_image_fetch(category, pk, event="all_candidates_failed", url=candidates[0][0] if candidates else "")
    response = HttpResponse(b"", content_type="image/svg+xml", status=404)
    response["Cache-Control"] = f"public, max-age={FAILURE_CACHE_SECONDS}"
    response["X-Content-Type-Options"] = "nosniff"
    return response
