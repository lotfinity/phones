from __future__ import annotations

from io import StringIO
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal
from urllib.parse import urlencode
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management import call_command
from django.db.models import Model
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from market.clean_models import (
    ConsoleOpportunitySnapshot,
    LaptopOpportunitySnapshot,
    PhoneOpportunitySnapshot,
)
from market.models import CurrencyRate
from market.services.currency import eur_rate_or_setting, eur_try_rate, eur_usd_rate, usd_try_rate
from market.views_clean import (
    VISIBLE_REVIEW_STATUSES,
    _display_row,
    _evidence_rows,
    _matching_listing_queryset,
    _snapshot_row,
    can_view_internal_gain,
    can_view_operational_meta,
)
from market.views_clean_detail import _restrict_detail_row
from market.views import money
from market.services.brand_logos import brand_logo_url as _brand_logo_url


OPPORTUNITY_CONFIG = {
    "phone": {
        "model": PhoneOpportunitySnapshot,
        "label": "Telefon",
        "plural": "Telefonlar",
    },
    "laptop": {
        "model": LaptopOpportunitySnapshot,
        "label": "Laptop",
        "plural": "Laptoplar",
    },
    "console": {
        "model": ConsoleOpportunitySnapshot,
        "label": "Konsol",
        "plural": "Konsollar",
    },
}

RECOMMENDATION_LABELS_TR = {
    "buy": "Alım fırsatı",
    "good_opportunity": "İyi fırsat",
    "watch": "Takip et",
    "marginal": "Sınırlı fırsat",
    "low_confidence": "Düşük veri güveni",
    "ignore": "Uygun değil",
    "no_margin": "Kazanç yok",
}

CONDITION_LABELS_TR = {
    "sealed": "Kapalı Kutu",
    "used_a_plus": "A+ Kalite",
    "used_a": "A Kalite",
    "used_b": "B Kalite",
    "used_c": "C Kalite",
    "used": "İkinci El",
    "unknown": "Durum Belirtilmemiş",
}

COUNTRY_LABELS_TR = {
    "algeria": "Cezayir",
    "turkiye": "Türkiye",
    "other": "Diğer",
}

AVAILABLE_REVIEW_STATUSES = {"auto", "approved"}


def _json_payload(value):
    """Remove Django model instances before embedding data as JSON in HTML."""
    if isinstance(value, Model):
        return None
    if isinstance(value, dict):
        return {
            key: _json_payload(item)
            for key, item in value.items()
            if not isinstance(item, Model)
        }
    if isinstance(value, (list, tuple, set)):
        return [
            _json_payload(item)
            for item in value
            if not isinstance(item, Model)
        ]
    return value


def _selected_currency(request):
    value = request.GET.get("currency") or request.COOKIES.get("pricebridge_currency") or "TRY"
    value = value.upper()
    return value if value in {"TRY", "EUR", "USD", "DZD"} else "TRY"


def _has_image(listing):
    if not listing:
        return False
    if (getattr(listing, "image_url", "") or "").strip():
        return True
    raw = getattr(listing, "raw_listing", None)
    return bool(raw and (getattr(raw, "image_url", "") or "").strip())


def _safe_external_url(value):
    value = (value or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return value


def _primary_listing(item, category):
    listings = list(_matching_listing_queryset(item, category)[:200])
    if not listings:
        return None

    for country in ("algeria", "turkiye"):
        for listing in listings:
            if listing.country == country and _has_image(listing):
                return listing

    for listing in listings:
        if _has_image(listing):
            return listing

    return listings[0]


def _listing_timestamp(listing):
    if not listing:
        return None
    for field in ("observed_at", "published_at", "listed_at", "created_at"):
        value = getattr(listing, field, None)
        if value:
            return value
    raw = getattr(listing, "raw_listing", None)
    if raw:
        for field in ("observed_at", "published_at", "created_at"):
            value = getattr(raw, field, None)
            if value:
                return value
    return None


def _listing_availability(listing):
    if not listing:
        return {
            "state": "verification_required",
            "label": "Güncellik doğrulanmalı",
            "is_actionable": False,
        }

    status = getattr(listing, "review_status", "")
    if status and status not in VISIBLE_REVIEW_STATUSES:
        return {
            "state": "unavailable",
            "label": "İlan artık mevcut değil",
            "is_actionable": False,
        }

    timestamp = _listing_timestamp(listing)
    if not timestamp:
        return {
            "state": "verification_required",
            "label": "Güncellik doğrulanmalı",
            "is_actionable": False,
        }

    if timezone.is_naive(timestamp):
        timestamp = timezone.make_aware(timestamp, timezone.get_current_timezone())
    age_days = (timezone.now() - timestamp).days
    if age_days <= 7 and status in AVAILABLE_REVIEW_STATUSES:
        return {
            "state": "available",
            "label": "İlan güncel",
            "is_actionable": True,
            "source_age_days": age_days,
        }
    return {
        "state": "stale",
        "label": "7 günden eski",
        "is_actionable": False,
        "source_age_days": age_days,
    }


def _listing_identity_url(listing):
    if not listing:
        return ""
    raw = getattr(listing, "raw_listing", None)
    return _safe_external_url(getattr(listing, "listing_url", "") or getattr(raw, "listing_url", ""))


def _supplier_pricing(item, selected_currency):
    supplier_eur = getattr(item, "supplier_eur", None)
    buyer_offer_eur = getattr(item, "buyer_offer_eur", None)
    if supplier_eur is None:
        return {
            "supplier_price": "",
            "supplier_discount_percent": None,
            "supplier_discount_label": "",
        }

    supplier = Decimal(str(supplier_eur))
    buyer = Decimal(str(buyer_offer_eur)) if buyer_offer_eur is not None else None
    discount_percent = None
    discount_label = ""
    if buyer is not None and supplier > 0 and buyer < supplier:
        discount_percent = int(((supplier - buyer) / supplier * Decimal("100")).quantize(Decimal("1")))
        if discount_percent > 0:
            discount_label = f"%{discount_percent} daha uygun"

    return {
        "supplier_price": money(supplier, selected_currency),
        "supplier_discount_percent": discount_percent,
        "supplier_discount_label": discount_label,
    }


def _acquisition_listing(item, category):
    listing = getattr(item, "algeria_listing", None)
    if listing is not None:
        return listing

    qs = _matching_listing_queryset(item, category).filter(country="algeria")
    listings = list(qs[:200])
    if not listings:
        return None

    def score(listing):
        timestamp = _listing_timestamp(listing)
        return (
            1 if getattr(listing, "review_status", "") in AVAILABLE_REVIEW_STATUSES else 0,
            1 if _spec_matches_snapshot(listing, item, category) else 0,
            timestamp or datetime.min.replace(tzinfo=datetime_timezone.utc),
            1 if _listing_identity_url(listing) else 0,
            1 if _has_image(listing) else 0,
        )

    return sorted(listings, key=score, reverse=True)[0]


def _spec_matches_snapshot(listing, item, category):
    if not listing:
        return False
    comparisons = []
    if category == "phone":
        comparisons.append((getattr(item, "storage_gb", None), getattr(listing, "storage_gb", None)))
    elif category == "laptop":
        comparisons.extend(
            [
                (getattr(item, "cpu", ""), getattr(listing, "cpu", "")),
                (getattr(item, "gpu", ""), getattr(listing, "gpu", "")),
                (getattr(item, "ram_gb", None), getattr(listing, "ram_gb", None)),
                (getattr(item, "storage_gb", None), getattr(listing, "storage_gb", None)),
            ]
        )
    elif category == "console":
        comparisons.extend(
            [
                (getattr(item, "chipset", ""), getattr(listing, "chipset", "")),
                (getattr(item, "ram_gb", None), getattr(listing, "ram_gb", None)),
                (getattr(item, "storage_gb", None), getattr(listing, "storage_gb", None)),
            ]
        )
    required = [(expected, actual) for expected, actual in comparisons if expected not in (None, "")]
    if not required:
        return True
    return all(str(expected).lower() == str(actual).lower() for expected, actual in required)


def _snapshot_specs(item, category):
    specs = []

    def add(label, value, suffix=""):
        if value in (None, ""):
            return
        specs.append({"label": label, "value": f"{value}{suffix}"})

    if category == "phone":
        add("Depolama", item.storage_gb, " GB")
    elif category == "laptop":
        add("İşlemci", item.cpu)
        add("Ekran kartı", item.gpu)
        add("RAM", item.ram_gb, " GB")
        add("Depolama", item.storage_gb, " GB")
    elif category == "console":
        add("Yonga seti", item.chipset)
        add("RAM", item.ram_gb, " GB")
        add("Depolama", item.storage_gb, " GB")

    return specs


def _listing_specs(listing, category):
    if not listing:
        return []

    specs = []

    def add(label, value, suffix=""):
        if value in (None, ""):
            return
        specs.append({"label": label, "value": f"{value}{suffix}"})

    if category == "phone":
        add("Batarya sağlığı", listing.battery_health, "%")
        add("Batarya döngüsü", listing.battery_cycles)
        add("SIM", listing.sim_config)
        add("Kutu", listing.box_status)
        add("Mağaza garantisi", listing.store_warranty)
        add("Bölge", listing.region)
        add("Renk", listing.color)
    elif category == "laptop":
        add("Ekran", listing.screen_size, '"')
        add("Çözünürlük", listing.resolution)
        add("Yenileme hızı", listing.refresh_rate_hz, " Hz")
        add("Panel", listing.panel_type)
    elif category == "console":
        add("Ekran", listing.screen_size, '"')
        add("Yenileme hızı", listing.refresh_rate_hz, " Hz")
        add("Bağlantı", listing.connectivity)
        add("Renk", listing.color)

    return specs


def _combined_specs(item, category, listing):
    result = []
    labels = set()
    for spec in _snapshot_specs(item, category) + _listing_specs(listing, category):
        if spec["label"] in labels:
            continue
        labels.add(spec["label"])
        result.append(spec)
    return result


def _formatted_original_price(listing):
    if not listing or listing.price_original in (None, ""):
        return ""
    currency = listing.currency_original or ""
    return f"{listing.price_original} {currency}".strip()


def _formatted_eur_price(listing):
    if not listing or listing.price_eur in (None, ""):
        return ""
    return f"€{listing.price_eur}"


def _detail_specs(item, category, listing):
    rows = []

    def add(label, value, suffix="", *, default="—"):
        if value in (None, ""):
            value = default
            suffix = ""
        rows.append({"label": label, "value": f"{value}{suffix}"})

    if category == "phone":
        add("Storage", getattr(listing, "storage_gb", None) or getattr(item, "storage_gb", None), " GB")
        add("RAM", getattr(listing, "ram_gb", None), " GB")
        add("SIM Configuration", getattr(listing, "sim_config", ""))
        add("Battery Health", getattr(listing, "battery_health", None), "%")
        add("Battery Cycles", getattr(listing, "battery_cycles", None))
        add("Box Status", getattr(listing, "box_status", ""))
        add("Store Warranty", getattr(listing, "store_warranty", ""))
        add("Region", getattr(listing, "region", ""))
        add("Color", getattr(listing, "color", ""))
        add("Condition", getattr(listing, "condition", ""), default="Unknown")
    elif category == "laptop":
        add("CPU", getattr(listing, "cpu", "") or getattr(item, "cpu", ""))
        add("GPU", getattr(listing, "gpu", "") or getattr(item, "gpu", ""))
        add("RAM", getattr(listing, "ram_gb", None) or getattr(item, "ram_gb", None), " GB")
        add("Storage", getattr(listing, "storage_gb", None) or getattr(item, "storage_gb", None), " GB")
        add("Screen Size", getattr(listing, "screen_size", None), '"')
        add("Resolution", getattr(listing, "resolution", ""))
        add("Refresh Rate", getattr(listing, "refresh_rate_hz", None), " Hz")
        add("Panel Type", getattr(listing, "panel_type", ""))
        add("Condition", getattr(listing, "condition", ""), default="Unknown")
    elif category == "console":
        add("Chipset", getattr(listing, "chipset", "") or getattr(item, "chipset", ""))
        add("RAM", getattr(listing, "ram_gb", None) or getattr(item, "ram_gb", None), " GB")
        add("Storage", getattr(listing, "storage_gb", None) or getattr(item, "storage_gb", None), " GB")
        add("Screen Size", getattr(listing, "screen_size", None), '"')
        add("Refresh Rate", getattr(listing, "refresh_rate_hz", None), " Hz")
        add("Connectivity", getattr(listing, "connectivity", ""))
        add("Color", getattr(listing, "color", ""))
        add("Condition", getattr(listing, "condition", ""), default="Unknown")

    add("Original Price", _formatted_original_price(listing))
    add("Price in EUR", _formatted_eur_price(listing))
    return rows


def _condition_label(listing):
    if not listing:
        return "Durum bilgisi yok"
    return CONDITION_LABELS_TR.get(listing.condition, listing.get_condition_display())


def _recommendation_label(value):
    return RECOMMENDATION_LABELS_TR.get(value, value.replace("_", " ").title())


def _opportunity_card(item, category, selected_currency, *, show_internal_gain=False):
    display = _display_row(
        _snapshot_row(item, category),
        selected_currency,
        show_internal_gain=show_internal_gain,
    )
    acquisition = _acquisition_listing(item, category)
    primary = acquisition or _primary_listing(item, category)
    specs = _combined_specs(item, category, acquisition)
    has_image = _has_image(acquisition)
    title = display["title"]
    availability = _listing_availability(acquisition)
    confidence_score = int(item.confidence_score or 0)
    supplier = _supplier_pricing(item, selected_currency)

    card = {
        "pk": item.pk,
        "plan_key": f"{category}:{item.pk}",
        "category": category,
        "category_label": OPPORTUNITY_CONFIG[category]["label"],
        "brand": item.brand,
        "brand_logo_url": _brand_logo_url(item.brand),
        "model": item.model,
        "title": title,
        "initials": "".join(part[0] for part in (item.brand or title).split()[:2]).upper() or "PB",
        "subtitle": display["spec"],
        "specs": specs,
        "condition": _condition_label(primary),
        "battery_health": getattr(acquisition, "battery_health", None) if acquisition else None,
        "recommendation": _recommendation_label(item.recommendation),
        "recommendation_value": item.recommendation,
        "confidence_score": confidence_score,
        "confidence_stars": round(confidence_score / 20),
        "confidence_aria_label": f"Veri güveni {confidence_score} / 100",
        "confidence_title": f"Veri güveni: %{confidence_score}",
        "buyer_offer": display.get("buyer_offer", ""),
        "buyer_gain": display.get("buyer_gain", ""),
        "buyer_gain_percent": display.get("buyer_gain_percent", ""),
        "turkiye_avg": display.get("turkiye_avg", ""),
        "supplier_price": supplier["supplier_price"],
        "supplier_discount_percent": supplier["supplier_discount_percent"],
        "supplier_discount_label": supplier["supplier_discount_label"],
        "turkiye_count": item.turkiye_count,
        "algeria_count": item.algeria_count,
        "evidence_count": (item.algeria_count or 0) + (item.turkiye_count or 0),
        "margin_percent_label": display.get("margin_percent_label", ""),
        "has_image": has_image,
        "image_url": (
            reverse(
                "clean_listing_image",
                kwargs={"category": category, "pk": acquisition.pk},
            )
            if has_image
            else ""
        ),
        "source_listing_id": acquisition.pk if acquisition else None,
        "source_listing_url": _listing_identity_url(acquisition),
        "source_observed_at": _listing_timestamp(acquisition),
        "availability_state": availability["state"],
        "availability_label": availability["label"],
        "availability_is_actionable": availability["is_actionable"],
        "source_age_days": availability.get("source_age_days"),
        "detail_url": reverse(
            "estore_opportunity_detail",
            kwargs={"category": category, "pk": item.pk},
        ),
        "generated_at": item.generated_at,
    }
    if show_internal_gain:
        card["my_gain"] = display.get("my_gain", "")
    return card


def _all_opportunity_items():
    items = []
    for category, config in OPPORTUNITY_CONFIG.items():
        for item in config["model"].objects.all():
            items.append((category, item))
    return items


def _brand_filter_options(items, *, active_category="", active_brand="", query=""):
    counts = {}
    for category, item in items:
        if active_category and category != active_category:
            continue
        if item.brand:
            counts[item.brand] = counts.get(item.brand, 0) + 1

    def url_for(brand):
        params = {}
        if active_category:
            params["category"] = active_category
        if query:
            params["q"] = query
        if brand:
            params["brand"] = brand
        query_string = urlencode(params)
        return f"/estore/?{query_string}" if query_string else "/estore/"

    options = [
        {
            "name": "Tümü",
            "value": "",
            "count": sum(counts.values()),
            "url": url_for(""),
            "active": not active_brand,
        }
    ]
    options.extend(
        {
            "name": brand,
            "value": brand,
            "count": count,
            "url": url_for(brand),
            "active": active_brand.lower() == brand.lower(),
            "logo": _brand_logo_url(brand) or "",
            "logo_white": (_brand_logo_url(brand) + "/ffffff") if _brand_logo_url(brand) else "",
        }
        for brand, count in sorted(counts.items(), key=lambda entry: (-entry[1], entry[0].lower()))
    )
    return options


def _filtered_items(request):
    active_category = request.GET.get("category", "").strip().lower()
    if active_category not in OPPORTUNITY_CONFIG:
        active_category = ""

    query = request.GET.get("q", "").strip().lower()
    active_brand = request.GET.get("brand", "").strip()
    items = _all_opportunity_items()
    brand_options = _brand_filter_options(
        items,
        active_category=active_category,
        active_brand=active_brand,
        query=request.GET.get("q", "").strip(),
    )

    if active_category:
        items = [entry for entry in items if entry[0] == active_category]

    if active_brand:
        items = [entry for entry in items if entry[1].brand.lower() == active_brand.lower()]

    if query:
        filtered = []
        for category, item in items:
            spec_text = " ".join(spec["value"] for spec in _snapshot_specs(item, category))
            haystack = f"{item.brand} {item.model} {spec_text}".lower()
            if query in haystack:
                filtered.append((category, item))
        items = filtered

    items.sort(
        key=lambda entry: (
            entry[1].gross_margin_eur or Decimal("0"),
            entry[1].margin_percent or Decimal("0"),
            entry[1].pk,
        ),
        reverse=True,
    )
    return items, active_category, request.GET.get("q", "").strip(), active_brand, brand_options


def _prepare_evidence(rows, category):
    prepared = []
    for row in rows:
        listing = row.get("item")
        has_image = _has_image(listing)
        prepared.append(
            row
            | {
                "country_label": COUNTRY_LABELS_TR.get(row.get("country"), row.get("country_label", "")),
                "condition": (
                    CONDITION_LABELS_TR.get(listing.condition, listing.get_condition_display())
                    if listing
                    else row.get("condition", "")
                ),
                "listing_url": _safe_external_url(row.get("listing_url")),
                "has_image": has_image,
                "image_url": (
                    reverse(
                        "clean_listing_image",
                        kwargs={"category": category, "pk": listing.pk},
                    )
                    if has_image
                    else ""
                ),
            }
        )
    return prepared


def _category_options(counts):
    return [
        {"value": key, "label": value["plural"], "count": counts[key]}
        for key, value in OPPORTUNITY_CONFIG.items()
    ]


def _api_card(card):
    return card | {
        "api_url": reverse(
            "estore_api_opportunity_detail",
            kwargs={"category": card["category"], "pk": card["pk"]},
        ),
        "frontend_detail_url": reverse(
            "estore_frontend_opportunity_detail",
            kwargs={"category": card["category"], "pk": card["pk"]},
        ),
    }


def _estore_index_payload(request):
    selected_currency = _selected_currency(request)
    show_internal_gain = can_view_internal_gain(request)
    items, active_category, query, active_brand, brand_options = _filtered_items(request)
    cards = [
        _opportunity_card(
            item,
            category,
            selected_currency,
            show_internal_gain=show_internal_gain,
        )
        for category, item in items
    ]
    cards.sort(
        key=lambda card: (
            Decimal(str(card.get("confidence_score") or 0)),
            Decimal(str(card.get("evidence_count") or 0)),
        ),
        reverse=True,
    )

    counts = {
        category: config["model"].objects.count()
        for category, config in OPPORTUNITY_CONFIG.items()
    }

    return {
        "selected_currency": selected_currency,
        "show_internal_gain": show_internal_gain,
        "cards": cards,
        "total_count": len(cards),
        "counts": counts,
        "active_category": active_category,
        "active_brand": active_brand,
        "brand_options": brand_options,
        "query": query,
        "category_options": _category_options(counts),
    }


def _pagination_params(request, total_count):
    try:
        offset = max(0, int(request.GET.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = int(request.GET.get("limit", 48))
    except (TypeError, ValueError):
        limit = 48
    limit = min(100, max(1, limit))
    return {
        "offset": offset,
        "limit": limit,
        "total": total_count,
        "has_more": offset + limit < total_count,
    }


def estore_opportunity_index(request):
    payload = _estore_index_payload(request)

    return render(
        request,
        "estore/listing_index.html",
        {
            "plan_payload": _json_payload({
                "page": "opportunity-index",
                "frontend": "server-rendered-estore",
                "cards": payload["cards"],
                "total_count": payload["total_count"],
                "active_category": payload["active_category"],
                "active_brand": payload["active_brand"],
                "brand_options": payload["brand_options"],
                "query": payload["query"],
                "selected_currency": payload["selected_currency"],
            }),
            "cards": payload["cards"],
            "total_count": payload["total_count"],
            "counts": payload["counts"],
            "active_category": payload["active_category"],
            "active_brand": payload["active_brand"],
            "brand_options": payload["brand_options"],
            "query": payload["query"],
            "selected_currency": payload["selected_currency"],
            "category_options": payload["category_options"],
            "can_view_internal_gain": payload["show_internal_gain"],
        },
    )


def _estore_detail_payload(request, category, pk):
    config = OPPORTUNITY_CONFIG.get(category)
    if config is None:
        raise Http404("Bilinmeyen fırsat kategorisi")

    item = get_object_or_404(config["model"], pk=pk)
    selected_currency = _selected_currency(request)
    show_internal_gain = can_view_internal_gain(request)
    show_operational_meta = can_view_operational_meta(request)

    full_row = _display_row(
        _snapshot_row(item, category),
        selected_currency,
        show_internal_gain=show_internal_gain,
    )
    row = _restrict_detail_row(
        full_row,
        show_internal_gain=show_internal_gain,
        show_operational_meta=show_operational_meta,
    )

    primary = _acquisition_listing(item, category) or _primary_listing(item, category)
    card = _opportunity_card(
        item,
        category,
        selected_currency,
        show_internal_gain=show_internal_gain,
    )

    all_algeria_rows, all_turkiye_rows = _evidence_rows(item, category, selected_currency)
    algeria_rows = _prepare_evidence(all_algeria_rows, category) if show_internal_gain else []
    turkiye_rows = _prepare_evidence(all_turkiye_rows, category)

    detail = row | card | {
        "specs": _combined_specs(item, category, primary),
        "detail_specs": _detail_specs(item, category, primary),
        "coverage": {
            "algeria": item.algeria_count,
            "turkiye": item.turkiye_count,
        },
        "generated_at": item.generated_at,
        "source_label": item.source_label if show_operational_meta else "",
    }

    return {
        "selected_currency": selected_currency,
        "show_internal_gain": show_internal_gain,
        "show_operational_meta": show_operational_meta,
        "detail": detail,
        "algeria_rows": algeria_rows,
        "turkiye_rows": turkiye_rows,
    }


def estore_opportunity_detail(request, category, pk):
    payload = _estore_detail_payload(request, category, pk)

    return render(
        request,
        "estore/listing_detail.html",
        {
            "plan_payload": _json_payload({
                "page": "opportunity-detail",
                "frontend": "server-rendered-estore",
                "opportunity": payload["detail"],
                "selected_currency": payload["selected_currency"],
            }),
            "opportunity": payload["detail"],
            "algeria_rows": payload["algeria_rows"],
            "turkiye_rows": payload["turkiye_rows"],
            "selected_currency": payload["selected_currency"],
            "can_view_internal_gain": payload["show_internal_gain"],
            "can_view_operational_meta": payload["show_operational_meta"],
        },
    )


@require_GET
def estore_api_opportunity_index(request):
    payload = _estore_index_payload(request)
    pagination = _pagination_params(request, payload["total_count"])
    offset = pagination["offset"]
    limit = pagination["limit"]
    cards = payload["cards"][offset:offset + limit]

    return JsonResponse(
        _json_payload(
            {
                "ok": True,
                "api_version": "estore-opportunities-v1",
                "page": "opportunity-index",
                "selected_currency": payload["selected_currency"],
                "filters": {
                    "category": payload["active_category"],
                    "brand": payload["active_brand"],
                    "q": payload["query"],
                },
                "pagination": pagination,
                "counts": payload["counts"],
                "category_options": payload["category_options"],
                "brand_options": payload["brand_options"],
                "cards": [_api_card(card) for card in cards],
            }
        )
    )


@require_GET
def estore_api_opportunity_detail(request, category, pk):
    payload = _estore_detail_payload(request, category, pk)
    return JsonResponse(
        _json_payload(
            {
                "ok": True,
                "api_version": "estore-opportunities-v1",
                "page": "opportunity-detail",
                "selected_currency": payload["selected_currency"],
                "opportunity": _api_card(payload["detail"]),
                "evidence": {
                    "algeria": payload["algeria_rows"],
                    "turkiye": payload["turkiye_rows"],
                },
            }
        )
    )


def _fmt_rate(value, places="0.000001"):
    return str(Decimal(str(value)).quantize(Decimal(places)))


def _latest_rate_row(base, quote):
    return (
        CurrencyRate.objects.filter(base_currency=base, quote_currency=quote)
        .order_by("-observed_at", "-id")
        .first()
    )


def _fx_pair(base, quote, rate, label):
    row = _latest_rate_row(base, quote)
    return {
        "base": base,
        "quote": quote,
        "pair": f"{base}/{quote}",
        "label": label,
        "rate": _fmt_rate(rate),
        "display": _fmt_rate(rate, "0.01"),
        "source": row.source if row else "settings:fallback",
        "observed_at": row.observed_at.isoformat() if row else "",
        "notes": row.notes if row else "",
    }


def _current_fx_payload():
    eur_try = eur_try_rate()
    usd_try = usd_try_rate()
    eur_usd = eur_usd_rate()
    eur_dzd = eur_rate_or_setting("DZD", "DZD_PER_EUR_BLACK")
    latest = CurrencyRate.objects.order_by("-observed_at", "-id").first()
    return {
        "ok": True,
        "api_version": "estore-fx-v1",
        "base": "EUR",
        "selected_currency": "TRY",
        "latest_observed": latest.observed_at.isoformat() if latest else "",
        "rates": {
            "EUR": "1.000000",
            "TRY": _fmt_rate(eur_try),
            "USD": _fmt_rate(eur_usd),
            "DZD": _fmt_rate(eur_dzd),
        },
        "pairs": [
            _fx_pair("EUR", "TRY", eur_try, "€1"),
            _fx_pair("USD", "TRY", usd_try, "$1"),
            _fx_pair("EUR", "DZD", eur_dzd, "€1"),
            _fx_pair("EUR", "USD", eur_usd, "€1"),
        ],
    }


@require_GET
def estore_api_fx_rates(request):
    return JsonResponse(_current_fx_payload())


@csrf_exempt
@require_POST
def estore_api_fx_refresh(request):
    dzd_rate = request.POST.get("dzd_per_eur_black") or "295"
    output = StringIO()
    call_command(
        "fetch_exchange_rates",
        "--dzd-per-eur-black",
        str(dzd_rate),
        stdout=output,
    )
    for command_name in (
        "recompute_phone_opportunities_v2",
        "recompute_laptop_opportunities_v2",
        "recompute_console_opportunities_v1",
    ):
        call_command(command_name, "--write-snapshots", stdout=output)

    payload = _current_fx_payload()
    payload["refreshed"] = True
    payload["command_output"] = output.getvalue()
    return JsonResponse(payload)
