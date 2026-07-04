import json
import re
import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone

from market.models import Condition, Country, MarketListing, ProductAsset, Source, SourceType
from market.parsers.supplier_parser import CAPACITY_RE, STORAGE_RE
from market.services.currency import dzd_to_eur
from market.services.matching import SUPPORTED_STORAGE_GB, get_or_create_model, get_or_create_variant


SCRIPTS_DIR = Path(settings.BASE_DIR) / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from chrome_extension_cdp import ChromeCdp, CdpSocket  # noqa: E402

OBSIDIAN_WEB_CLIPPER_EXTENSION_ID = "cnjifjpddelmedmihgijeibhnjfabmlf"


@dataclass
class OuedknissRowChange:
    action: str
    title: str
    url: str
    changes: dict


@dataclass
class OuedknissImportResult:
    extracted_rows: int
    saved_rows: int
    skipped_rows: int
    skipped_old_rows: int = 0
    skipped_no_price_rows: int = 0
    created_rows: int = 0
    updated_rows: int = 0
    unchanged_rows: int = 0
    row_changes: list = None
    skipped_no_price_details: list = None
    extractor: str = "unknown"


def parse_cdp_endpoint(cdp_endpoint):
    parsed = urlparse(cdp_endpoint)
    return parsed.hostname or "127.0.0.1", parsed.port or 9222


def normalize_ouedkniss_url(value):
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("ouedkniss.com/") or value.startswith("www.ouedkniss.com/"):
        return f"https://{value}"
    return f"https://www.ouedkniss.com/{value.lstrip('/')}"


def comparable_url(value):
    parsed = urlparse(normalize_ouedkniss_url(value))
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.netloc.lower()}{path}?{parsed.query}" if parsed.query else f"{parsed.netloc.lower()}{path}"


def target_match_score(target, target_url):
    if not target_url:
        return 1 if "ouedkniss.com" in target.url else 0
    target_comp = comparable_url(target.url)
    wanted_comp = comparable_url(target_url)
    if target_comp == wanted_comp:
        return 100
    if target_url in target.url:
        return 50
    wanted_path = urlparse(normalize_ouedkniss_url(target_url)).path.rstrip("/")
    target_path = urlparse(target.url).path.rstrip("/")
    if wanted_path and wanted_path == target_path:
        return 40
    return 0


def parse_dzd_price(value):
    price_pattern = r"(?<![\d/])(?P<price>\d{1,3}(?:[\s.]\d{3})+|\d{4,7})\s*(?:da|dzd)\b"
    for match in re.finditer(price_pattern, value or "", re.IGNORECASE):
        digits = re.sub(r"\D", "", match.group("price"))
        if not digits:
            continue
        amount = Decimal(digits)
        if 1000 <= amount <= 1000000:
            return amount
    return None


def parse_relative_age_days(value):
    text = (value or "").lower()
    match = re.search(
        r"\b(?P<count>\d+)\s*(?P<unit>minute|minutes|heure|heures|jour|jours|semaine|semaines|mois|month|months|week|weeks|day|days|hour|hours)\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    count = int(match.group("count"))
    unit = match.group("unit").lower()
    if unit.startswith(("minute", "heure", "hour")):
        return 0
    if unit.startswith(("jour", "day")):
        return count
    if unit.startswith(("semaine", "week")):
        return count * 7
    if unit.startswith(("mois", "month")):
        return count * 31
    return None


def is_within_max_age(row, max_age_days):
    if max_age_days is None:
        return True
    age_days = parse_relative_age_days(row.get("text", ""))
    if age_days is None:
        return True
    return age_days <= max_age_days


RAM_GB_VALUES = {2, 3, 4, 6, 8, 12, 16, 18, 24, 32}


def normalize_storage_gb(value):
    token = str(value or "").lower().replace(" ", "")
    if token in {"1tb", "1000", "1000gb", "1000g", "1000go", "1024", "1024gb", "1024g", "1024go"}:
        return 1024
    if token.endswith(("gb", "go")):
        token = token[:-2]
    elif token.endswith("g"):
        token = token[:-1]
    if not token.isdigit():
        return None
    storage_gb = int(token)
    return storage_gb if storage_gb in SUPPORTED_STORAGE_GB else None


def parse_storage_ram(value):
    text = value or ""
    storage_gb = None
    ram_gb = None

    capacity_match = CAPACITY_RE.search(text)
    if capacity_match:
        first = int(capacity_match.group("a"))
        second = int(capacity_match.group("b"))
        first_storage = normalize_storage_gb(first)
        second_storage = normalize_storage_gb(second)
        if first in RAM_GB_VALUES and second_storage:
            ram_gb = first
            storage_gb = second_storage
        elif second in RAM_GB_VALUES and first_storage:
            storage_gb = first_storage
            ram_gb = second

    storage_match = STORAGE_RE.search(text)
    if storage_match:
        storage_gb = normalize_storage_gb(storage_match.group("storage")) or storage_gb

    ram_match = re.search(r"\b(?P<ram>2|3|4|6|8|12|16|18|24)\s*(?:ram|go ram|gb ram)\b", text, re.IGNORECASE)
    if ram_match:
        ram_gb = int(ram_match.group("ram"))
    inline_ram_match = re.search(
        r"\b(?P<ram>2|3|4|6|8|12|16|18|24)\s*gb\b(?=[^\n]{0,12}\b(?:32|64|128|256|512|1024)\s*gb\b)",
        text,
        re.IGNORECASE,
    )
    if inline_ram_match:
        ram_gb = int(inline_ram_match.group("ram"))

    if storage_gb is None:
        loose_storage = re.search(
            r"\b(?P<storage>64|128|256|512|1000|1024)\b(?=[^\n]{0,16}\b(?:gb|g|go|sim|duos|1sim|2sim|tb)\b)",
            text,
            re.IGNORECASE,
        )
        if loose_storage:
            storage_gb = normalize_storage_gb(loose_storage.group("storage"))

    return storage_gb, ram_gb


def parse_sim_config(value):
    text = (value or "").lower()
    if re.search(r"\b2\s*sim\b", text) or re.search(r"\bdual\s*sim\b", text) or re.search(r"\bdualsim\b", text) or re.search(r"\bduos\b", text) or re.search(r"\bdual\b", text):
        return "2sim"
    if re.search(r"\b1\s*sim\b", text):
        return ""
    return ""


def clean_model_text(value):
    text = value or ""
    text = re.sub(
        r"\b(?:2|3|4|6|8|12|16|18|24)\s*gb\b(?=\s+(?:32|64|128|256|512|1024)\s*gb\b)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b\d{2,4}\s*(?:gb|g|tb)\s*/\s*\d{1,2}\s*ram\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{1,2}\s*/\s*\d{2,4}\s*(?:gb|g|tb)?\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{2,4}\s*/\s*\d{1,2}\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:32|64|128|256|512|1024)\b(?=\s*[12]\s*sim\b)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[12]\s*tb\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{2,4}\s*(?:gb|g|tb)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{1,2}\s*(?:gb\s*)?ram\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[12]\s*sim\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bduos\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bdual\s*sim\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bdual\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[-/,]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def count_visible_cards(target):
    sock = CdpSocket(target)
    try:
        sock.call("Runtime.enable")
        count = int(sock.eval("document.querySelectorAll('div.v-col-sm-6.v-col-md-4.v-col-12').length") or 0)
        if not count:
            count = int(sock.eval("document.querySelectorAll('.o-announ-card').length") or 0)
        return count
    finally:
        sock.close()


def wait_for_ouedkniss_cards(target, timeout=20.0, interval=1.0):
    sock = CdpSocket(target)
    try:
        sock.call("Runtime.enable")
        end_at = time.time() + timeout
        while time.time() < end_at:
            count = count_cards_in_socket(sock)
            if count:
                return count
            time.sleep(interval)
        return count_cards_in_socket(sock)
    finally:
        sock.close()


def count_cards_in_socket(sock):
    count = int(sock.eval("document.querySelectorAll('div.v-col-sm-6.v-col-md-4.v-col-12').length") or 0)
    if not count:
        count = int(sock.eval("document.querySelectorAll('.o-announ-card').length") or 0)
    return count


def target_ouedkniss_page(cdp, target_url="", open_if_missing=True, load_timeout=20.0):
    targets = [
        target
        for target in cdp.targets()
        if target.type == "page" and target_match_score(target, target_url)
    ]
    if targets:
        return max(targets, key=lambda target: (target_match_score(target, target_url), count_visible_cards(target)))
    if target_url:
        if not open_if_missing:
            raise RuntimeError(f"No open Ouedkniss page target containing URL text: {target_url}")
        url = normalize_ouedkniss_url(target_url)
        target = cdp.new_tab(url)
        wait_for_ouedkniss_cards(target, timeout=load_timeout)
        refreshed_targets = [item for item in cdp.targets() if item.id == target.id]
        return refreshed_targets[0] if refreshed_targets else target
    raise RuntimeError("No open Ouedkniss page target found in Chrome CDP.")


def extract_rows(sock, scrolls=0, wait=1.0):
    sock.call("Runtime.enable")
    expression = r"""
(() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const listingHref = (card) => {
    const links = Array.from(card.querySelectorAll('a[href]')).map((a) => a.href);
    return links.find((href) => /(?:-d\d+|\/annonce\/\d+)/.test(href)) || '';
  };
  const titleFromText = (text) => {
    const lines = text.split('\n').map(clean).filter(Boolean);
    return lines.find((line) => !/^image$/i.test(line) && !/^\d[\d\s.]*$/.test(line) && !/^da$/i.test(line)) || '';
  };
  let cards = Array.from(document.querySelectorAll('div.v-col-sm-6.v-col-md-4.v-col-12'));
  if (!cards.length) {
    cards = Array.from(document.querySelectorAll('.o-announ-card'));
  }
  return JSON.stringify(cards.map((card) => {
    const rawText = card.innerText || '';
    const title = clean(card.querySelector('.o-announ-card-title')?.innerText || '');
    const text = clean(rawText);
    const href = listingHref(card);
    const image = card.querySelector('img')?.currentSrc || card.querySelector('img')?.src || '';
    const store = clean(card.querySelector('a[href*="/store/"]')?.innerText || '');
    const priceMatch = text.match(/(?:^|\D)(\d[\d\s.]{2,12})\s*(?:DA|DZD)\b/i);
    const priceText = priceMatch ? `${priceMatch[1]} DA` : '';
    return {title: title || titleFromText(rawText), text, href, image, store, priceText};
  }));
})()
"""
    rows_by_key = {}
    max_scrolls = max(scrolls or 1, 1)
    stable_passes = 0
    last_signature = None

    for index in range(max_scrolls + 1):
        page_height = int(sock.eval("document.body.scrollHeight") or 0)
        viewport_height = int(sock.eval("window.innerHeight") or 800)
        if index == 0:
            position = 0
        elif index >= max_scrolls:
            position = page_height
        else:
            position = min(index * max(int(viewport_height * 0.85), 600), page_height)

        sock.eval(f"window.scrollTo(0, {int(position)})")
        time.sleep(wait)
        rows = json.loads(sock.eval(expression) or "[]")
        for row_index, row in enumerate(rows):
            key = row.get("href") or f"no-url:{row_index}:{row.get('title', '')}:{row.get('priceText', '')}"
            rows_by_key[key] = row

        href_count = sum(1 for row in rows_by_key.values() if row.get("href"))
        priced_count = sum(
            1
            for row in rows_by_key.values()
            if parse_dzd_price(row.get("priceText")) or parse_dzd_price(row.get("text", ""))
        )
        current_height = int(sock.eval("document.body.scrollHeight") or 0)
        signature = (len(rows_by_key), href_count, priced_count, current_height)
        if signature == last_signature and position >= current_height - viewport_height - 10:
            stable_passes += 1
            if stable_passes >= 2:
                break
        else:
            stable_passes = 0
        last_signature = signature
    return list(rows_by_key.values())


def find_or_open_obsidian_target(cdp):
    extension_prefix = f"chrome-extension://{OBSIDIAN_WEB_CLIPPER_EXTENSION_ID}/"
    for target in cdp.targets():
        if target.type == "page" and target.url.startswith(extension_prefix):
            return target
    target = cdp.new_tab(f"{extension_prefix}popup.html")
    time.sleep(0.5)
    refreshed_targets = [item for item in cdp.targets() if item.id == target.id]
    return refreshed_targets[0] if refreshed_targets else target


def activate_target(cdp, target):
    try:
        cdp.activate(target.id)
    except json.JSONDecodeError:
        pass


def obsidian_get_page_content(cdp, target):
    activate_target(cdp, target)
    time.sleep(0.2)
    extension_target = find_or_open_obsidian_target(cdp)
    activate_target(cdp, target)
    time.sleep(0.2)
    sock = CdpSocket(extension_target)
    try:
        sock.call("Runtime.enable")
        expression = """
(async () => {
  const active = await chrome.runtime.sendMessage({action: "getActiveTab"});
  if (!active || active.error || !active.tabId) {
    return JSON.stringify({ok: false, error: active && active.error ? active.error : "No active tab"});
  }
  const response = await chrome.runtime.sendMessage({
    action: "sendMessageToTab",
    tabId: active.tabId,
    message: {action: "getPageContent"}
  });
  if (!response || response.error) {
    return JSON.stringify({ok: false, error: response && response.error ? response.error : "No page content"});
  }
  return JSON.stringify({
    ok: true,
    title: response.title || "",
    content: response.content || "",
    fullHtml: response.fullHtml || ""
  });
})()
"""
        payload = sock.eval(expression, await_promise=True)
        if isinstance(payload, str):
            return json.loads(payload)
        return payload or {}
    finally:
        sock.close()


def strip_html(value):
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def parse_obsidian_content_rows(content):
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - bs4 is in requirements, but keep optional.
        raise RuntimeError("BeautifulSoup is required for Obsidian Ouedkniss extraction.") from exc

    soup = BeautifulSoup(content or "", "html.parser")
    rows = []
    listing_anchors = []
    for anchor in soup.select('a[href*="/annonce/"], a[href*="-d"]'):
        href_value = anchor.get("href", "").strip()
        if "/store/" in href_value and "/annonce/" not in href_value:
            continue
        if "/annonce/" not in href_value and not re.search(r"-d\d+(?:[/?#]|$)", href_value):
            continue
        listing_anchors.append(anchor)

    for anchor in listing_anchors:
        href = normalize_ouedkniss_url(anchor.get("href", "").strip())
        if not href:
            continue
        title = strip_html(str(anchor.find(["h1", "h2", "h3"]) or ""))
        raw_text = anchor.get_text("\n", strip=True)
        text = re.sub(r"\s+", " ", raw_text).strip()
        if not title:
            lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
            title = next(
                (
                    line
                    for line in lines
                    if not re.fullmatch(r"image|da|prix da", line, flags=re.IGNORECASE)
                    and not re.fullmatch(r"\d[\d\s.]*", line)
                ),
                "",
            )
        image = ""
        image_tag = anchor.find("img")
        if image_tag:
            image = image_tag.get("src") or image_tag.get("data-src") or ""
        price_match = re.search(r"(?<![\d/])(?P<price>\d{1,3}(?:\s\d{3})+|\d{4,7})\s*DA\b", text, re.IGNORECASE)
        price_text = f"{price_match.group('price')} DA" if price_match else ""
        rows.append(
            {
                "title": title,
                "text": text,
                "href": href,
                "image": image,
                "store": "",
                "priceText": price_text,
            }
        )
    return rows


def extract_rows_with_obsidian(cdp, target, scrolls=0, wait=1.0):
    rows_by_key = {}
    sock = CdpSocket(target)
    try:
        sock.call("Runtime.enable")
        max_scrolls = max(scrolls or 1, 1)
        stable_passes = 0
        last_signature = None
        for index in range(max_scrolls + 1):
            page_height = int(sock.eval("document.body.scrollHeight") or 0)
            viewport_height = int(sock.eval("window.innerHeight") or 800)
            if index == 0:
                position = 0
            elif index >= max_scrolls:
                position = page_height
            else:
                position = min(index * max(int(viewport_height * 0.85), 600), page_height)
            sock.eval(f"window.scrollTo(0, {int(position)})")
            time.sleep(wait)
            payload = obsidian_get_page_content(cdp, target)
            if not payload.get("ok"):
                raise RuntimeError(f"Obsidian Web Clipper extraction failed: {payload.get('error') or 'unknown error'}")
            parsed_rows = parse_obsidian_content_rows(payload.get("content", ""))
            if not parsed_rows and payload.get("fullHtml"):
                parsed_rows = parse_obsidian_content_rows(payload.get("fullHtml", ""))
            for row_index, row in enumerate(parsed_rows):
                key = row.get("href") or f"no-url:{row_index}:{row.get('title', '')}:{row.get('priceText', '')}"
                rows_by_key[key] = row

            href_count = sum(1 for row in rows_by_key.values() if row.get("href"))
            priced_count = sum(
                1
                for row in rows_by_key.values()
                if parse_dzd_price(row.get("priceText")) or parse_dzd_price(row.get("text", ""))
            )
            current_height = int(sock.eval("document.body.scrollHeight") or 0)
            signature = (len(rows_by_key), href_count, priced_count, current_height)
            if signature == last_signature and position >= current_height - viewport_height - 10:
                stable_passes += 1
                if stable_passes >= 2:
                    break
            else:
                stable_passes = 0
            last_signature = signature
    finally:
        sock.close()
    return list(rows_by_key.values())


def format_value(value):
    if hasattr(value, "pk"):
        return str(value)
    return value


def save_row(row, source):
    raw_text = row.get("text", "")
    title = row.get("title", "")
    price_dzd = parse_dzd_price(row.get("priceText")) or parse_dzd_price(raw_text)
    storage_gb, ram_gb = parse_storage_ram(title)
    sim_config = parse_sim_config(title)
    model_text = clean_model_text(title)
    product_model = get_or_create_model(model_text) if model_text else None
    variant = (
        get_or_create_variant(product_model, storage_gb=storage_gb, sim_config=sim_config)
        if product_model
        else None
    )
    metadata = {
        "store": row.get("store", ""),
        "image_url": row.get("image", ""),
        "source": "ouedkniss_cdp",
    }
    review_status = (
        MarketListing.ReviewStatus.AUTO
        if price_dzd and product_model
        else MarketListing.ReviewStatus.NEEDS_REVIEW
    )
    url = row.get("href", "")
    defaults = {
        "source_type": SourceType.OUEDKNISS,
        "country": Country.ALGERIA,
        "product_model": product_model,
        "variant": variant,
        "title_raw": title[:300],
        "description_raw": f"{raw_text}\n{json.dumps(metadata, ensure_ascii=False)}",
        "price_original": price_dzd,
        "currency_original": MarketListing.Currency.DZD,
        "price_eur": dzd_to_eur(price_dzd) if price_dzd else None,
        "condition": Condition.UNKNOWN,
        "sim_config": sim_config,
        "listing_url": url,
        "image_path": row.get("image", ""),
        "observed_at": timezone.now(),
        "parsed_confidence": 0.9 if review_status == MarketListing.ReviewStatus.AUTO else 0.55,
        "review_status": review_status,
    }
    existing = MarketListing.objects.filter(source=source, listing_url=url).first()
    if not existing:
        listing = MarketListing.objects.create(source=source, **defaults)
        _save_card_image(product_model, variant, row, source)
        return OuedknissRowChange("created", listing.title_raw or "[blank title]", url, {})

    changed_fields = {}
    ignored_diff_fields = {"observed_at", "description_raw"}
    for field, new_value in defaults.items():
        if field in ignored_diff_fields:
            continue
        old_value = getattr(existing, field)
        if old_value != new_value:
            changed_fields[field] = {
                "old": format_value(old_value),
                "new": format_value(new_value),
            }

    for field, new_value in defaults.items():
        setattr(existing, field, new_value)
    existing.save(update_fields=list(defaults.keys()))

    action = "updated" if changed_fields else "refreshed_unchanged"
    return OuedknissRowChange(action, existing.title_raw or "[blank title]", url, changed_fields)


def _save_card_image(product_model, variant, row, source):
    image_url = row.get("image", "")
    if not image_url or not product_model:
        return
    has_primary = ProductAsset.objects.filter(
        product_model=product_model,
        asset_type=ProductAsset.AssetType.PRODUCT_IMAGE,
        source=ProductAsset.Source.MARKETPLACE,
        is_primary=True,
        is_active=True,
    ).exists()
    if has_primary:
        return
    ProductAsset.objects.create(
        product_model=product_model,
        variant=variant,
        asset_type=ProductAsset.Asstype.PRODUCT_IMAGE if hasattr(ProductAsset, 'Asstype') else ProductAsset.AssetType.PRODUCT_IMAGE,
        source=ProductAsset.Source.MARKETPLACE,
        commons_file_url=image_url,
        local_file=image_url,
        search_query=row.get("title", ""),
        match_score=50,
        match_status=ProductAsset.MatchStatus.WEAK_MATCH,
        is_primary=True,
        is_active=True,
        raw_metadata={"store": row.get("store", ""), "listing_url": row.get("href", "")},
    )


def import_from_cdp(
    cdp_endpoint,
    limit=200,
    scrolls=30,
    wait=1.0,
    target_url="",
    max_age_days=30,
    open_if_missing=True,
    load_timeout=45.0,
    extractor="obsidian",
):
    host, port = parse_cdp_endpoint(cdp_endpoint)
    cdp = ChromeCdp(host, port)
    target = target_ouedkniss_page(
        cdp,
        target_url=target_url,
        open_if_missing=open_if_missing,
        load_timeout=load_timeout,
    )
    source, _ = Source.objects.get_or_create(
        source_type=SourceType.OUEDKNISS,
        username="ouedkniss-cdp",
        defaults={
            "name": "Ouedkniss CDP",
            "country": Country.ALGERIA,
            "profile_url": target.url,
            "notes": "Imported from a user-opened Ouedkniss tab via Chrome CDP.",
        },
    )
    saved_rows = skipped_rows = skipped_old_rows = skipped_no_price_rows = created_rows = updated_rows = unchanged_rows = 0
    row_changes = []
    skipped_no_price_details = []
    wait_for_ouedkniss_cards(target, timeout=load_timeout)
    used_extractor = extractor
    if extractor in {"obsidian", "auto"}:
        try:
            rows = extract_rows_with_obsidian(cdp, target, scrolls=scrolls, wait=wait)
            used_extractor = "obsidian"
        except RuntimeError:
            if extractor == "obsidian":
                raise
            used_extractor = "dom"
            sock = CdpSocket(target)
            try:
                rows = extract_rows(sock, scrolls=scrolls, wait=wait)
            finally:
                sock.close()
    else:
        used_extractor = "dom"
        sock = CdpSocket(target)
        try:
            rows = extract_rows(sock, scrolls=scrolls, wait=wait)
            if not rows:
                time.sleep(wait)
                wait_for_ouedkniss_cards(target, timeout=load_timeout)
                rows = extract_rows(sock, scrolls=scrolls, wait=wait)
        finally:
            sock.close()

    seen_urls = set()
    for row in rows[:limit]:
        url = normalize_ouedkniss_url(row.get("href", ""))
        row["href"] = url
        if not parse_dzd_price(row.get("priceText")) and not parse_dzd_price(row.get("text", "")):
            skipped_no_price_rows += 1
            skipped_no_price_details.append(
                {
                    "title": row.get("title") or "[blank title]",
                    "url": url,
                }
            )
            continue
        if not url or url in seen_urls:
            skipped_rows += 1
            continue
        if not is_within_max_age(row, max_age_days):
            skipped_old_rows += 1
            continue
        seen_urls.add(url)
        change = save_row(row, source)
        row_changes.append(change)
        if change.action == "created":
            created_rows += 1
        elif change.action == "updated":
            updated_rows += 1
        else:
            unchanged_rows += 1
        saved_rows += 1
    return OuedknissImportResult(
        extracted_rows=len(rows),
        saved_rows=saved_rows,
        skipped_rows=skipped_rows,
        skipped_old_rows=skipped_old_rows,
        skipped_no_price_rows=skipped_no_price_rows,
        created_rows=created_rows,
        updated_rows=updated_rows,
        unchanged_rows=unchanged_rows,
        row_changes=row_changes,
        skipped_no_price_details=skipped_no_price_details,
        extractor=used_extractor,
    )
