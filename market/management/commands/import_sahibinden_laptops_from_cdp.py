import json
import re
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from market.collectors.sahibinden_cdp import (
    ChromeCdp,
    CdpSocket,
    parse_cdp_endpoint,
    parse_try_price,
    parse_condition as sahibinden_parse_condition,
)
from market.models import (
    Category,
    Condition,
    Country,
    MarketListing,
    ProductModel,
    Source,
    SourceType,
)
from market.services.currency import try_to_eur
from market.services.listing_parser import extract_model_text, ascii_fold
from market.services.laptop_parser import parse_laptop_title, laptop_review_status
from market.services.matching import find_existing_model, get_or_create_model, find_existing_variant, get_or_create_variant


SAHIBINDEN_LAPTOP_TABLE_JS = """
(function() {
    const table = document.querySelector('#searchResultsTable, table.laptop-category');
    if (!table) return JSON.stringify({rows: [], error: 'no table found'});
    const rows = [];
    const trs = table.querySelectorAll('tr');
    for (const tr of trs) {
        const tds = tr.querySelectorAll('td');
        if (tds.length < 7) continue;
        const titleCell = tds[2];
        const link = titleCell.querySelector('a');
        if (!link) continue;
        const title = (link.textContent || '').trim();
        const href = link.href || '';
        const processorCell = tds[3];
        const ramCell = tds[4];
        const screenSizeCell = tds[5];
        const priceCell = tds[6];
        const dateCell = tds[7];
        const locationCell = tds[8];
        const priceText = (priceCell.textContent || '').trim();
        const dateText = dateCell ? (dateCell.textContent || '').trim() : '';
        const locationText = locationCell ? (locationCell.textContent || '').trim() : '';
        const processor = (processorCell.textContent || '').trim();
        const ram = (ramCell.textContent || '').trim();
        const screenSize = (screenSizeCell.textContent || '').trim();
        const imageImg = tr.querySelector('img');
        const imageUrl = imageImg ? imageImg.src : '';
        if (title && href) {
            rows.push({
                title: title,
                href: href,
                priceText: priceText,
                dateText: dateText,
                locationText: locationText,
                processor: processor,
                ram: ram,
                screenSize: screenSize,
                imageUrl: imageUrl,
            });
        }
    }
    return JSON.stringify({rows: rows});
})()
"""

SAHIBINDEN_SCROLL_JS = """
(function() {
    window.scrollTo(0, document.body.scrollHeight);
    return document.body.scrollHeight;
})()
"""


def extract_laptop_rows(cdp, target, scrolls=15, wait=1.0):
    """Extract laptop listing rows from Sahibinden via CDP."""
    sock = CdpSocket(target)
    try:
        seen_hrefs = set()
        rows_by_key = {}
        current_height = 0
        stable_passes = 0
        last_signature = None

        for _ in range(scrolls):
            sock.send_json({"id": 1, "method": "Runtime.evaluate", "params": {"expression": SAHIBINDEN_SCROLL_JS, "returnByValue": True}})
            scroll_result = sock.recv_json()
            try:
                current_height = int(scroll_result.get("result", {}).get("result", {}).get("value", 0))
            except (TypeError, ValueError):
                current_height = 0

            sock.send_json({"id": 2, "method": "Runtime.evaluate", "params": {"expression": SAHIBINDEN_LAPTOP_TABLE_JS, "returnByValue": True}})
            result = sock.recv_json()
            value = result.get("result", {}).get("result", {}).get("value", "")
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    parsed = {"rows": []}
            else:
                parsed = value or {"rows": []}

            for row in parsed.get("rows", []):
                href = row.get("href", "")
                if not href or href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                key = href
                rows_by_key[key] = row

            priced_count = len([r for r in rows_by_key.values() if r.get("priceText")])
            href_count = len(rows_by_key)
            signature = (len(rows_by_key), href_count, priced_count, current_height)
            if signature == last_signature:
                stable_passes += 1
                if stable_passes >= 2:
                    break
            else:
                stable_passes = 0
            last_signature = signature
            time.sleep(wait)
    finally:
        sock.close()
    return list(rows_by_key.values())


def normalize_sahibinden_url(url):
    if not url:
        return url
    return re.sub(r"\?.*$", "", url)


class SahibindenLaptopImportResult:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def save_laptop_row(row, source, category):
    title = row.get("title", "")
    price_try = parse_try_price(row.get("priceText", ""))
    specs = parse_laptop_title(title)
    ram_gb = specs.get("ram_gb")
    storage_gb = specs.get("storage_gb")

    # Try to get model from title
    model_text = extract_model_text(title)
    product_model = find_existing_model(model_text) if model_text else None
    if not product_model and model_text:
        product_model = get_or_create_model(model_text, category_name="Laptops")

    variant = None
    if product_model and ram_gb:
        variant = find_existing_variant(product_model, storage_gb=ram_gb, sim_config="")

    condition = sahibinden_parse_condition(title)
    price_eur = try_to_eur(price_try, "TRY") if price_try else None

    metadata = {
        "source": "sahibinden_cdp",
        "category": "laptops",
        "cpu": specs.get("cpu", ""),
        "gpu": specs.get("gpu", ""),
        "ram_gb": ram_gb,
        "storage_gb": storage_gb,
        "screen_size": specs.get("screen_size"),
        "resolution": specs.get("resolution", ""),
        "processor_cell": row.get("processor", ""),
        "ram_cell": row.get("ram", ""),
        "screen_size_cell": row.get("screenSize", ""),
        "location": row.get("locationText", ""),
        "date_text": row.get("dateText", ""),
    }

    review_status = laptop_review_status(price_try, product_model, ram_gb)
    url = normalize_sahibinden_url(row.get("href", ""))

    defaults = {
        "source_type": SourceType.SAHIBINDEN,
        "country": Country.TURKIYE,
        "product_model": product_model,
        "variant": variant,
        "storage_gb": ram_gb,
        "title_raw": title[:300],
        "description_raw": json.dumps(metadata, ensure_ascii=False),
        "price_original": price_try,
        "currency_original": MarketListing.Currency.TRY,
        "price_eur": price_eur,
        "condition": condition,
        "sim_config": "",
        "listing_url": url,
        "image_path": row.get("imageUrl", ""),
        "observed_at": timezone.now(),
        "parsed_confidence": 0.85 if review_status == MarketListing.ReviewStatus.AUTO else 0.5,
        "review_status": review_status,
    }

    existing = MarketListing.objects.filter(source=source, listing_url=url).first()
    if not existing:
        listing = MarketListing.objects.create(source=source, **defaults)
        return "created", listing
    else:
        for field, new_value in defaults.items():
            setattr(existing, field, new_value)
        existing.save(update_fields=list(defaults.keys()))
        return "updated", existing


class Command(BaseCommand):
    help = "Import laptop listings from an already-open Sahibinden CDP tab."

    def add_arguments(self, parser):
        parser.add_argument("--cdp", default=settings.CHROME_CDP_ENDPOINT)
        parser.add_argument("--limit", type=int, default=200)
        parser.add_argument("--scrolls", type=int, default=15)
        parser.add_argument("--wait", type=float, default=1.0)
        parser.add_argument("--target-url", default="")
        parser.add_argument("--load-timeout", type=float, default=45.0)
        parser.add_argument(
            "--open",
            dest="open_if_missing",
            action="store_true",
            default=False,
        )
        parser.add_argument(
            "--no-open",
            dest="open_if_missing",
            action="store_false",
        )

    def handle(self, *args, **options):
        host, port = parse_cdp_endpoint(options["cdp"])
        cdp = ChromeCdp(host, port)

        # Find target tab
        target = None
        for t in cdp.get_targets():
            url = t.get("url", "")
            if "sahibinden.com" in url and ("laptop" in url or "bilgisayar" in url or options["target_url"] in url):
                target = t
                break
        if not target and options.get("target_url"):
            for t in cdp.get_targets():
                if options["target_url"] in t.get("url", ""):
                    target = t
                    break
        if not target:
            raise CommandError("No Sahibinden laptop tab found. Open a Sahibinden laptop search page first.")

        category, _ = Category.objects.get_or_create(slug="laptops", defaults={"name": "Laptops"})
        source, _ = Source.objects.get_or_create(
            source_type=SourceType.SAHIBINDEN,
            username="sahibinden-laptops-cdp",
            defaults={
                "name": "Sahibinden Laptops CDP",
                "country": Country.TURKIYE,
                "profile_url": target.get("url", ""),
                "notes": "Imported from a user-opened Sahibinden laptop tab via Chrome CDP.",
            },
        )

        self.stdout.write(self.style.WARNING(f"Extracting from: {target.get('url', '')}"))
        rows = extract_laptop_rows(cdp, target, scrolls=options["scrolls"], wait=options["wait"])
        self.stdout.write(f"Extracted {len(rows)} rows")

        created_count = updated_count = 0
        for row in rows[:options["limit"]]:
            action, listing = save_laptop_row(row, source, category)
            if action == "created":
                created_count += 1
                self.stdout.write(f"  NEW: {listing.title_raw[:70]} | {listing.price_original} TRY")
            else:
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created {created_count}, updated {updated_count} laptop listings."
        ))
