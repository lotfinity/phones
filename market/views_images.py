import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlsplit

import requests
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
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


@require_GET
def clean_listing_image(request, category, pk):
    model = CLEAN_LISTING_MODELS.get(category)
    if model is None:
        raise Http404("Unknown clean listing category")

    listing = get_object_or_404(model.objects.select_related("raw_listing"), pk=pk)
    raw_listing = listing.raw_listing
    image_url = (listing.image_url or (raw_listing.image_url if raw_listing else "") or "").strip()
    if not image_url:
        raise Http404("No image stored for this listing")

    listing_url = (listing.listing_url or (raw_listing.listing_url if raw_listing else "") or "").strip()
    referer = ""
    if listing_url:
        parsed_listing = urlsplit(listing_url)
        if parsed_listing.scheme in {"http", "https"} and parsed_listing.netloc:
            referer = f"{parsed_listing.scheme}://{parsed_listing.netloc}/"

    try:
        payload, content_type = _download_image(image_url, referer=referer)
    except (requests.RequestException, ValueError, OSError) as exc:
        logger.info("Clean listing image fetch failed category=%s pk=%s: %s", category, pk, exc)
        raise Http404("Listing image could not be loaded") from exc

    response = HttpResponse(payload, content_type=content_type)
    response["Cache-Control"] = "public, max-age=21600"
    response["X-Content-Type-Options"] = "nosniff"
    return response
