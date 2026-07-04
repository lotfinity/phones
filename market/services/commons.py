import os
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.utils.text import slugify

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "PriceBridge/0.1 internal market intelligence tool"

COMMONS_NAMESPACE_FILE = 6
DEFAULT_SEARCH_LIMIT = 10
SAFE_FILE_SIZE_LIMIT = 5 * 1024 * 1024  # 5 MB

VARIANT_TOKENS = frozenset({
    "ultra", "pro", "pro max", "plus", "fold", "flip", "air", "max",
    "mini", "se", "lite", "t", "r", "s", "z", "fe", "note", "a",
})

IGNORE_TOKENS = frozenset({
    "gb", "ram", "5g", "4g", "lte", "sim", "dual", "single",
    "the", "and", "for", "with", "new", "series",
})

STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "is", "it", "as", "be",
})


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def search_commons_files(query, limit=DEFAULT_SEARCH_LIMIT):
    """Search Wikimedia Commons file namespace for files matching query."""
    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srnamespace": str(COMMONS_NAMESPACE_FILE),
        "srlimit": str(min(limit, 50)),
        "srsearch": query,
    }
    try:
        resp = _session().get(COMMONS_API, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        return {"error": str(exc), "results": []}

    results = data.get("query", {}).get("search", [])
    normalized = data.get("query", {}).get("normalized", [])
    return {
        "results": results,
        "normalized": normalized,
        "query": query,
    }


def fetch_imageinfo(title):
    """Fetch imageinfo metadata for a Commons file title."""
    params = {
        "action": "query",
        "format": "json",
        "titles": title,
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
    }
    try:
        resp = _session().get(COMMONS_API, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        return {"error": str(exc), "pages": {}}

    pages = data.get("query", {}).get("pages", {})
    result = {}
    for page_id, page_data in pages.items():
        if page_id == "-1":
            result = {"missing": True, "title": title}
            break
        imageinfo = page_data.get("imageinfo", [{}])[0]
        extmetadata = imageinfo.get("extmetadata", {})
        result = {
            "title": page_data.get("title", title),
            "pageid": page_data.get("pageid"),
            "url": imageinfo.get("url", ""),
            "mime": imageinfo.get("mime", ""),
            "width": imageinfo.get("width"),
            "height": imageinfo.get("height"),
            "size": imageinfo.get("size"),
            "extmetadata": clean_extmetadata(extmetadata),
        }
    return result


def download_commons_file(url, local_path):
    """Download a Commons file to local_path. Returns local_path on success."""
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    try:
        resp = _session().get(url, timeout=60, stream=True)
        resp.raise_for_status()
        content_length = int(resp.headers.get("content-length", 0))
        if content_length > SAFE_FILE_SIZE_LIMIT:
            return None, f"File too large: {content_length} bytes"
        downloaded = 0
        with open(local_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                downloaded += len(chunk)
                if downloaded > SAFE_FILE_SIZE_LIMIT:
                    f.close()
                    os.remove(local_path)
                    return None, f"Download exceeded {SAFE_FILE_SIZE_LIMIT} bytes"
                f.write(chunk)
        return local_path, None
    except requests.RequestException as exc:
        return None, str(exc)


def clean_extmetadata(extmetadata):
    """Extract clean values from MediaWiki extmetadata dict."""
    cleaned = {}
    key_map = {
        "LicenseShortName": "license_short",
        "LicenseUrl": "license_url",
        "UsageTerms": "usage_terms",
        "Attribution": "attribution",
        "Artist": "artist",
        "Credit": "credit",
        "ImageDescription": "description",
        "Categories": "categories",
    }
    for raw_key, clean_key in key_map.items():
        entry = extmetadata.get(raw_key, {})
        if isinstance(entry, dict):
            value = entry.get("value", "")
        else:
            value = str(entry)
        cleaned[clean_key] = _strip_html(value)
    return cleaned


def _strip_html(text):
    """Remove HTML tags from text."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


def build_logo_search_queries(product_model):
    """Generate a list of Wikimedia Commons search queries for a product model."""
    brand_name = product_model.brand.name if product_model.brand else ""
    canonical = product_model.canonical_name
    queries = []

    name_lower = canonical.lower()
    brand_lower = brand_name.lower()

    base_name = canonical
    if brand_lower and name_lower.startswith(brand_lower):
        base_name = canonical[len(brand_name):].strip()
        if not base_name:
            base_name = canonical

    queries.append(f'intitle:"{canonical}" logo svg')
    queries.append(f'"{canonical} logo" svg')
    queries.append(f'"{base_name} logo" svg')

    variant_terms = []
    for vt in VARIANT_TOKENS:
        if vt in name_lower:
            variant_terms.append(vt)

    if variant_terms:
        queries.append(f'"{canonical}" "text logo"')

    if brand_lower:
        queries.append(f'"{brand_lower} {base_name} logo" svg')

    if "iphone" in name_lower or "ipad" in name_lower or "macbook" in name_lower or "airpods" in name_lower:
        alt_name = canonical.replace("i", "I", 1) if canonical.lower().startswith("i") else canonical
        if alt_name != canonical:
            queries.append(f'intitle:"{alt_name}" logo svg')
            queries.append(f'"{alt_name} logo" svg')

    series_fallbacks = _build_series_fallbacks(canonical, brand_name)
    for fb in series_fallbacks:
        queries.append(f'intitle:"{fb}" logo svg')
        queries.append(f'"{fb} logo" svg')

    seen = set()
    unique = []
    for q in queries:
        q_norm = q.lower().strip()
        if q_norm not in seen:
            seen.add(q_norm)
            unique.append(q)
    return unique


def _build_series_fallbacks(canonical, brand_name):
    """Build series fallback search terms."""
    fallbacks = []
    name_lower = canonical.lower()

    parts = canonical.rsplit(" ", 2)
    if len(parts) >= 2:
        fallbacks.append(parts[0] + " " + parts[1])

    words = canonical.split()
    if len(words) >= 2:
        fallbacks.append(" ".join(words[:2]))

    if brand_name and name_lower.startswith(brand_name.lower()):
        without_brand = canonical[len(brand_name):].strip()
        if without_brand:
            fallbacks.append(without_brand)

    if brand_name:
        fallbacks.append(brand_name)

    seen = set()
    unique = []
    for fb in fallbacks:
        fb_clean = fb.strip()
        if fb_clean and fb_clean.lower() not in seen and fb_clean.lower() != canonical.lower():
            seen.add(fb_clean.lower())
            unique.append(fb_clean)
    return unique


def _extract_model_tokens(product_model):
    """Extract meaningful tokens from a product model for scoring."""
    brand_name = product_model.brand.name if product_model.brand else ""
    canonical = product_model.canonical_name

    tokens = set()
    if brand_name:
        tokens.add(brand_name.lower())

    words = canonical.lower().split()
    for w in words:
        w_clean = re.sub(r"[^a-z0-9]", "", w)
        if w_clean and w_clean not in STOP_WORDS and w_clean not in IGNORE_TOKENS:
            tokens.add(w_clean)

    family_tokens = set()
    for w in words:
        w_clean = re.sub(r"[^a-z0-9]", "", w)
        if w_clean and w_clean not in STOP_WORDS and w_clean not in IGNORE_TOKENS:
            family_tokens.add(w_clean)

    variant_tokens = set()
    for vt in VARIANT_TOKENS:
        if vt in canonical.lower():
            variant_tokens.add(vt)

    return {
        "all": tokens,
        "family": family_tokens,
        "variant": variant_tokens,
        "brand": brand_name.lower(),
    }


def score_commons_candidate(product_model, candidate):
    """Score a Commons search result against a product model. Returns (score, reasons)."""
    score = 0
    reasons = []
    title = candidate.get("title", "").lower()
    title_clean = re.sub(r"[^a-z0-9\s]", " ", title)

    tokens = _extract_model_tokens(product_model)

    all_tokens_present = all(t in title_clean for t in tokens["all"] if len(t) > 2)
    if all_tokens_present:
        score += 40
        reasons.append("all_tokens_present")

    if "logo" in title_clean:
        score += 25
        reasons.append("has_logo")
    elif "typologo" in title_clean:
        score += 15
        reasons.append("has_typologo")

    if title.endswith(".svg") or ".svg" in title:
        score += 20
        reasons.append("is_svg")

    if tokens["brand"] and tokens["brand"] in title_clean:
        score += 10
        reasons.append("brand_match")

    family_match = any(ft in title_clean for ft in tokens["family"] if len(ft) > 2)
    if family_match:
        score += 10
        reasons.append("family_match")

    if "icon" in title_clean and "logo" not in title_clean:
        score -= 25
        reasons.append("icon_not_logo")

    if "screenshot" in title_clean:
        score -= 20
        reasons.append("screenshot")

    if any(w in title_clean for w in ("photo", "photograph", "picture", "wallpaper", "background")):
        if "logo" not in title_clean:
            score -= 20
            reasons.append("photo_not_logo")

    if any(brand in title_clean for brand in ("apple", "samsung", "xiaomi", "huawei", "google") if brand != tokens["brand"]):
        if tokens["brand"] and tokens["brand"] not in title_clean:
            score -= 50
            reasons.append("unrelated_brand")

    model_numbers = re.findall(r"\b([a-z]?\d{2,4}[a-z]?)\b", product_model.canonical_name.lower())
    title_numbers = re.findall(r"\b([a-z]?\d{2,4}[a-z]?)\b", title_clean)
    if model_numbers and title_numbers:
        if not any(mn in title_numbers for mn in model_numbers):
            score -= 30
            reasons.append("different_model_number")

    variant_missing = False
    if tokens["variant"]:
        for vt in tokens["variant"]:
            if vt not in title_clean:
                variant_missing = True
                break
        if variant_missing:
            score -= 40
            reasons.append("variant_missing")

    if score < -100:
        score = -100

    return score, reasons


def sync_asset_for_product_model(product_model, options=None):
    """Search, score, download, and save a ProductAsset for a product model.

    Returns a dict with status, asset (if saved), score, query, candidate, reasons.
    """
    from market.models import ProductAsset

    opts = options or {}
    dry_run = opts.get("dry_run", False)
    min_score = opts.get("min_score", 70)
    save_weak = opts.get("save_weak", False)
    asset_type = opts.get("asset_type", "model_logo")
    sleep_between = opts.get("sleep", 0.5)
    force = opts.get("force", False)
    verbose = opts.get("verbose", False)

    if not force and not dry_run:
        existing = ProductAsset.objects.filter(
            product_model=product_model,
            is_active=True,
            is_primary=True,
            asset_type__in=["model_logo", "series_logo"],
        ).first()
        if existing:
            return {
                "status": "skipped",
                "reason": "already_has_primary",
                "query": "",
                "candidate": None,
                "score": 0,
                "reasons": [],
            }

    queries = build_logo_search_queries(product_model)
    best_candidate = None
    best_score = -999
    best_query = ""
    best_reasons = []
    all_searched = []

    for query in queries:
        search_result = search_commons_files(query, limit=10)
        if search_result.get("error"):
            continue

        results = search_result.get("results", [])
        for r in results:
            candidate_title = r.get("title", "")
            score, reasons = score_commons_candidate(product_model, r)
            all_searched.append({
                "title": candidate_title,
                "score": score,
                "query": query,
                "reasons": reasons,
            })
            if score > best_score:
                best_score = score
                best_candidate = r
                best_query = query
                best_reasons = reasons

        time.sleep(sleep_between)

    if best_candidate is None:
        return {
            "status": "no_match",
            "reason": "no_candidates",
            "query": "",
            "candidate": None,
            "score": 0,
            "reasons": [],
        }

    candidate_title = best_candidate.get("title", "")
    imageinfo = fetch_imageinfo(candidate_title)
    time.sleep(sleep_between)

    if imageinfo.get("error") or imageinfo.get("missing"):
        return {
            "status": "failed",
            "reason": f"imageinfo_failed: {imageinfo.get('error', 'missing')}",
            "query": best_query,
            "candidate": best_candidate,
            "score": best_score,
            "reasons": best_reasons,
        }

    extmeta = imageinfo.get("extmetadata", {})
    mime = imageinfo.get("mime", "")
    if mime == "image/svg+xml":
        best_score += 5
        best_reasons.append("svg_mime")

    if best_score >= 70:
        final_type = asset_type
    elif best_score >= 50:
        final_type = "series_logo" if asset_type == "model_logo" else asset_type
    else:
        final_type = "series_logo"

    if best_score >= min_score:
        match_status = "matched"
    elif best_score >= 50 and save_weak:
        match_status = "manual_review"
    elif best_score >= 50:
        match_status = "weak_match"
    else:
        match_status = "no_match"

    if match_status == "no_match":
        return {
            "status": "no_match",
            "reason": f"low_score: {best_score}",
            "query": best_query,
            "candidate": best_candidate,
            "score": best_score,
            "reasons": best_reasons,
        }

    if dry_run:
        return {
            "status": "dry_run",
            "reason": "",
            "query": best_query,
            "candidate": best_candidate,
            "score": best_score,
            "reasons": best_reasons,
            "match_status": match_status,
            "asset_type": final_type,
            "imageinfo": imageinfo,
            "extmetadata": extmeta,
        }

    safe_brand = slugify(product_model.brand.name) if product_model.brand else "unknown"
    safe_model = slugify(product_model.canonical_name)
    filename = candidate_title.replace("File:", "").replace(" ", "_")
    local_dir = Path(settings.MEDIA_ROOT) / "product_assets" / "commons" / safe_brand / safe_model
    local_path = local_dir / filename

    downloaded_path = None
    download_error = None
    if local_path.exists() and not force:
        downloaded_path = str(local_path)
    else:
        file_url = imageinfo.get("url", "")
        if file_url:
            downloaded_path, download_error = download_commons_file(file_url, str(local_path))

    asset = ProductAsset.objects.create(
        product_model=product_model,
        brand=product_model.brand,
        asset_type=final_type,
        source="wikimedia_commons",
        commons_title=candidate_title,
        commons_file_url=imageinfo.get("url", ""),
        commons_page_url=f"https://commons.wikimedia.org/wiki/{candidate_title.replace(' ', '_')}",
        local_file=str(downloaded_path) if downloaded_path else "",
        mime_type=mime,
        width=imageinfo.get("width"),
        height=imageinfo.get("height"),
        file_size=imageinfo.get("size"),
        license_short=extmeta.get("license_short", ""),
        license_url=extmeta.get("license_url", ""),
        usage_terms=extmeta.get("usage_terms", ""),
        attribution=extmeta.get("attribution", ""),
        artist=extmeta.get("artist", ""),
        credit=extmeta.get("credit", ""),
        restrictions=extmeta.get("restrictions", ""),
        search_query=best_query,
        match_score=best_score,
        match_status=match_status,
        is_primary=True,
        is_active=True,
        raw_metadata={
            "imageinfo": {
                "url": imageinfo.get("url", ""),
                "mime": mime,
                "width": imageinfo.get("width"),
                "height": imageinfo.get("height"),
                "size": imageinfo.get("size"),
            },
            "extmetadata": extmeta,
            "all_searched": all_searched[:20],
            "download_error": download_error,
        },
    )

    return {
        "status": "saved",
        "reason": download_error if download_error else "",
        "query": best_query,
        "candidate": best_candidate,
        "score": best_score,
        "reasons": best_reasons,
        "asset": asset,
        "match_status": match_status,
        "asset_type": final_type,
    }
