import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.conf import settings
from django.utils import timezone

from market.models import Condition, Country, MarketListing, Source, SourceType
from market.services.currency import try_to_eur
from market.services.matching import get_or_create_model, get_or_create_variant


SCRIPTS_DIR = Path(settings.BASE_DIR) / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from chrome_extension_cdp import ChromeCdp, CdpSocket  # noqa: E402


@dataclass
class SahibindenImportResult:
    visited_pages: int
    extracted_rows: int
    saved_rows: int
    skipped_rows: int


def parse_cdp_endpoint(cdp_endpoint):
    parsed = urlparse(cdp_endpoint)
    return parsed.hostname or "127.0.0.1", parsed.port or 9222


def with_paging_offset(url, offset, paging_size=50):
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["pagingOffset"] = str(offset)
    query["pagingSize"] = str(paging_size)
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def parse_try_price(value):
    text = (value or "").strip().lower()
    if not text:
        return None
    text = re.sub(r"\s*(tl|try|₺)\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s+", "", text)
    if "," in text:
        # Turkish prices use dot for thousands and comma for decimals: 47.499,99 TL.
        normalized = text.replace(".", "").replace(",", ".")
    else:
        normalized = text.replace(".", "")
    normalized = re.sub(r"[^\d.]", "", normalized)
    if not normalized:
        return None
    amount = Decimal(normalized)
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_storage_gb(value):
    text = value or ""
    capacity_pair = re.search(
        r"\b(?P<a>4|6|8|12|16|64|128|256|512|1024)\s*/\s*(?P<b>4|6|8|12|16|64|128|256|512|1024)\b",
        text,
    )
    if capacity_pair:
        first = int(capacity_pair.group("a"))
        second = int(capacity_pair.group("b"))
        return second if first <= 32 < second else first

    match = re.search(r"\b(64|128|256|512|1024|1\s?tb|2\s?tb)\s*(?:gb|g|tb)\b", text, re.IGNORECASE)
    if not match:
        match = re.search(
            r"\b(64|128|256|512|1024)\b(?=[^\n]{0,24}\b(?:gb|hafiza|hafıza)\b)",
            text,
            re.IGNORECASE,
        )
    if not match and re.search(r"\b(iphone|galaxy|samsung|s\d{2}|pro|max|ultra|plus)\b", text, re.IGNORECASE):
        match = re.search(r"\b(64|128|256|512|1024)\b", text, re.IGNORECASE)
    if not match:
        return None
    token = match.group(1).lower().replace(" ", "")
    return int(token[:-2]) * 1024 if token.endswith("tb") else int(token)


def parse_condition(value):
    text = unicodedata.normalize("NFKD", (value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    sealed_tokens = ["sıfır", "sifir", "kapalı kutu", "kapali kutu", "kapalı", "kapali", "açılmamış", "acilmamis"]
    used_tokens = ["2. el", "ikinci el", "temiz", "pil", "kullanım", "kullanim", "aktif", "hatasız", "hatasiz"]
    if any(token in text for token in sealed_tokens) and not any(token in text for token in ["pil", "2. el", "ikinci el"]):
        return Condition.SEALED
    if any(token in text for token in used_tokens):
        return Condition.USED
    return Condition.UNKNOWN


def parse_sim_config(value):
    text = (value or "").lower()
    if re.search(r"\b2\s*sim\b", text) or re.search(r"\bdual\s*sim\b", text) or re.search(r"\bdualsim\b", text) or re.search(r"\bduos\b", text):
        return "2sim"
    if re.search(r"\bçift\b", text) or re.search(r"\bcift\b", text):
        return "2sim"
    if re.search(r"\b1\s*sim\b", text):
        return ""
    return ""

def review_status_for(price_try, product_model, variant):
    if not price_try or not product_model or not variant:
        return MarketListing.ReviewStatus.NEEDS_REVIEW
    if price_try < Decimal("5000") or price_try > Decimal("100000"):
        return MarketListing.ReviewStatus.NEEDS_REVIEW
    return MarketListing.ReviewStatus.AUTO


def absolute_sahibinden_url(url):
    if not url:
        return ""
    return url if url.startswith("http") else f"https://www.sahibinden.com{url}"


def extract_rows(sock):
    expression = r"""
(() => {
  const rows = Array.from(document.querySelectorAll('tr.searchResultsItem'));
  return JSON.stringify(rows.map((tr) => {
    const titleLink = tr.querySelector('a.classifiedTitle');
    const thumbLink = tr.querySelector('.searchResultsLargeThumbnail a[href*="/ilan/"]');
    const img = tr.querySelector('.searchResultsLargeThumbnail img');
    const source = tr.querySelector('.searchResultsLargeThumbnail source');
    const model = tr.querySelector('.searchResultsTagAttributeValue')?.innerText.trim() || '';
    const title = tr.querySelector('.searchResultsTitleValue')?.innerText.trim().replace(/\s+/g, ' ') || titleLink?.innerText.trim() || '';
    const price = tr.querySelector('.searchResultsPriceValue')?.innerText.trim().replace(/\s+/g, ' ') || '';
    const date = tr.querySelector('.searchResultsDateValue')?.innerText.trim().replace(/\s+/g, ' ') || '';
    const place = tr.querySelector('.searchResultsLocationValue')?.innerText.trim().replace(/\s+/g, ' ') || '';
    const href = titleLink?.href || thumbLink?.href || '';
    const thumb = img?.currentSrc || img?.src || source?.srcset || '';
    const id = href.match(/-(\d+)\/detay/)?.[1] || tr.querySelector('[data-classified-id]')?.getAttribute('data-classified-id') || '';
    return {id, model, title, price, date, place, href, thumb};
  }).filter((row) => row.href && row.title));
})()
"""
    return json.loads(sock.eval(expression) or "[]")


def target_sahibinden_page(cdp):
    for target in cdp.targets():
        if target.type == "page" and "sahibinden.com" in target.url:
            return target
    raise RuntimeError("No open Sahibinden page target found in Chrome CDP.")


def target_sahibinden_detail_page(cdp):
    for target in cdp.targets():
        if target.type == "page" and "sahibinden.com/ilan/" in target.url and "/detay" in target.url:
            return target
    raise RuntimeError("No open Sahibinden detail page target found in Chrome CDP.")


def save_row(row, source):
    price_try = parse_try_price(row.get("price"))
    model_text = row.get("model") or row.get("title", "")
    product_model = get_or_create_model(model_text) if model_text else None
    combined = f"{row.get('model', '')} {row.get('title', '')}"
    storage_gb = parse_storage_gb(combined)
    sim_config = parse_sim_config(combined)
    variant = get_or_create_variant(product_model, storage_gb=storage_gb, sim_config=sim_config) if product_model else None
    condition = parse_condition(row.get("title", ""))
    listing_url = absolute_sahibinden_url(row.get("href", ""))
    metadata = {
        "sahibinden_id": row.get("id", ""),
        "model": row.get("model", ""),
        "price": row.get("price", ""),
        "date": row.get("date", ""),
        "place": row.get("place", ""),
        "thumbnail_url": row.get("thumb", ""),
    }
    review_status = review_status_for(price_try, product_model, variant)
    listing, _ = MarketListing.objects.update_or_create(
        source=source,
        listing_url=listing_url,
        defaults={
            "source_type": SourceType.SAHIBINDEN,
            "country": Country.TURKIYE,
            "product_model": product_model,
            "variant": variant,
            "title_raw": (row.get("title") or row.get("model", ""))[:300],
            "description_raw": f"{row.get('title', '')}\n{json.dumps(metadata, ensure_ascii=False)}",
            "price_original": price_try,
            "currency_original": MarketListing.Currency.TRY,
            "price_eur": try_to_eur(price_try) if price_try else None,
            "condition": condition,
            "sim_config": sim_config,
            "listing_url": listing_url,
            "image_path": row.get("thumb", ""),
            "observed_at": timezone.now(),
            "parsed_confidence": 0.9 if review_status == MarketListing.ReviewStatus.AUTO else 0.6,
            "review_status": review_status,
        },
    )
    return listing


def extract_detail(sock):
    expression = r"""
(() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const attrs = {};
  document.querySelectorAll('.classifiedInfoList li').forEach((li) => {
    const key = clean(li.querySelector('strong')?.innerText);
    const value = clean(li.querySelector('span')?.innerText);
    if (key && value) attrs[key] = value;
  });
  const h1 = clean(document.querySelector('h1')?.innerText);
  const price = clean(document.querySelector('.classifiedInfo .classified-price-wrapper, .classifiedInfo h3, .classified-price-wrapper')?.innerText);
  const description = clean(document.querySelector('#classifiedDescription')?.innerText);
  const locationText = clean(document.querySelector('.classifiedInfo h2, .classifiedInfo .classifiedInfoLocation')?.innerText);
  const image = document.querySelector('#classifiedDetail img, .classifiedDetailPhotos img')?.currentSrc || '';
  return JSON.stringify({url: window.location.href, h1, price, attrs, description, location: locationText, image});
})()
"""
    return json.loads(sock.eval(expression) or "{}")


def enrich_open_detail_from_cdp(cdp_endpoint):
    host, port = parse_cdp_endpoint(cdp_endpoint)
    cdp = ChromeCdp(host, port)
    target = target_sahibinden_detail_page(cdp)
    sock = CdpSocket(target)
    try:
        sock.call("Runtime.enable")
        detail = extract_detail(sock)
    finally:
        sock.close()

    listing_url = absolute_sahibinden_url(detail.get("url", ""))
    listing = MarketListing.objects.filter(source_type=SourceType.SAHIBINDEN, listing_url=listing_url).first()
    if not listing:
        raise RuntimeError(f"No Sahibinden MarketListing found for open detail URL: {listing_url}")

    attrs = detail.get("attrs") or {}
    model_text = attrs.get("Model") or (listing.product_model.canonical_name if listing.product_model else "")
    product_model = get_or_create_model(model_text) if model_text else listing.product_model
    storage_gb = parse_storage_gb(attrs.get("Depolama Kapasitesi") or detail.get("description") or detail.get("h1") or "")
    variant = get_or_create_variant(product_model, storage_gb=storage_gb) if product_model and storage_gb else listing.variant
    price_try = parse_try_price(detail.get("price")) or listing.price_original
    condition = parse_condition(" ".join([attrs.get("Durumu", ""), detail.get("description", ""), detail.get("h1", "")]))
    review_status = review_status_for(price_try, product_model, variant)

    metadata = {
        "detail_attrs": attrs,
        "detail_location": detail.get("location", ""),
        "detail_image": detail.get("image", ""),
    }
    listing.product_model = product_model
    listing.variant = variant
    listing.title_raw = (detail.get("h1") or listing.title_raw)[:300]
    existing_summary = listing.description_raw.splitlines()[0] if listing.description_raw else ""
    listing.description_raw = "\n".join(
        part for part in [detail.get("description") or existing_summary, json.dumps(metadata, ensure_ascii=False)] if part
    )
    listing.price_original = price_try
    listing.currency_original = MarketListing.Currency.TRY
    listing.price_eur = try_to_eur(price_try) if price_try else None
    listing.condition = condition
    listing.image_path = detail.get("image") or listing.image_path
    listing.parsed_confidence = 0.95 if review_status == MarketListing.ReviewStatus.AUTO else 0.7
    listing.review_status = review_status
    listing.save()
    return listing, detail


def import_from_cdp(cdp_endpoint, max_rows=300, paging_size=50, wait=2.0):
    host, port = parse_cdp_endpoint(cdp_endpoint)
    cdp = ChromeCdp(host, port)
    target = target_sahibinden_page(cdp)
    source, _ = Source.objects.get_or_create(
        source_type=SourceType.SAHIBINDEN,
        username="sahibinden-cdp",
        defaults={
            "name": "Sahibinden CDP",
            "country": Country.TURKIYE,
            "profile_url": target.url,
            "notes": "Imported from a user-opened Chrome tab via CDP.",
        },
    )

    sock = CdpSocket(target)
    visited_pages = extracted_rows = saved_rows = skipped_rows = 0
    seen_urls = set()
    try:
        sock.call("Runtime.enable")
        sock.call("Page.enable")
        for offset in range(0, max_rows, paging_size):
            sock.call("Page.navigate", {"url": with_paging_offset(target.url, offset, paging_size)})
            time.sleep(wait)
            rows = extract_rows(sock)
            visited_pages += 1
            if not rows:
                break
            for row in rows:
                listing_url = absolute_sahibinden_url(row.get("href", ""))
                if listing_url in seen_urls:
                    skipped_rows += 1
                    continue
                seen_urls.add(listing_url)
                if extracted_rows >= max_rows:
                    break
                extracted_rows += 1
                save_row(row, source)
                saved_rows += 1
            if len(rows) < paging_size or extracted_rows >= max_rows:
                break
    finally:
        sock.close()

    return SahibindenImportResult(visited_pages, extracted_rows, saved_rows, skipped_rows)
