from __future__ import annotations

from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal
from urllib.parse import urlencode
from urllib.parse import urlsplit

from django.db.models import Model
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from market.clean_models import (
    ConsoleOpportunitySnapshot,
    LaptopOpportunitySnapshot,
    PhoneOpportunitySnapshot,
)
from market.models import DealSnapshot, SourceType
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


def _legacy_instagram_deal_card(item, selected_currency, *, show_internal_gain=False):
    confidence_score = 50
    margin_pct = Decimal(str(item.margin_pct or 0))
    if item.sah_count >= 3:
        confidence_score += 15
    if item.margin_pct and item.margin_pct >= 25:
        confidence_score += 10
    confidence_score = min(confidence_score, 85)
    title = f"{item.brand_name} {item.model_name}".strip()
    if item.storage_gb:
        title = f"{title} {item.storage_gb}GB"
    source_url = _safe_external_url(item.listing_url)
    card = {
        "pk": f"legacy-{item.pk}",
        "plan_key": f"legacy-phone:{item.pk}",
        "category": "phone",
        "category_label": "Telefon",
        "brand": item.brand_name,
        "brand_logo_url": _brand_logo_url(item.brand_name),
        "model": item.model_name,
        "title": title,
        "initials": "".join(part[0] for part in (item.brand_name or title).split()[:2]).upper() or "PB",
        "subtitle": f"{item.storage_gb} GB" if item.storage_gb else "",
        "specs": [{"label": "Depolama", "value": f"{item.storage_gb} GB"}] if item.storage_gb else [],
        "condition": CONDITION_LABELS_TR.get(item.condition, item.condition or "Durum bilgisi yok"),
        "battery_health": getattr(item.listing, "battery_health", None) if item.listing_id else None,
        "recommendation": "Instagram fırsatı",
        "recommendation_value": "buy" if margin_pct >= 25 else "watch",
        "confidence_score": confidence_score,
        "confidence_stars": round(confidence_score / 20),
        "confidence_aria_label": f"Veri güveni {confidence_score} / 100",
        "confidence_title": f"Veri güveni: %{confidence_score}",
        "buyer_offer": money(item.price_eur, selected_currency),
        "buyer_gain": money(item.margin_eur, selected_currency),
        "buyer_gain_percent": f"%{Decimal(str(item.margin_pct)).quantize(Decimal('0.1'))}" if item.margin_pct else "",
        "turkiye_avg": money(item.sah_median_eur, selected_currency),
        "supplier_price": money(item.supplier_eur, selected_currency) if item.supplier_eur else "",
        "supplier_discount_percent": None,
        "supplier_discount_label": "",
        "turkiye_count": item.sah_count,
        "algeria_count": 1,
        "evidence_count": (item.sah_count or 0) + 1,
        "margin_percent_label": f"%{Decimal(str(item.margin_pct)).quantize(Decimal('0.1'))}" if item.margin_pct else "",
        "has_image": bool(item.image_url),
        "image_url": item.image_url,
        "source_listing_id": item.listing_id,
        "source_listing_url": source_url,
        "source_observed_at": item.observed_at,
        "availability_state": "available" if source_url else "verification_required",
        "availability_label": "Instagram ilanı",
        "availability_is_actionable": bool(source_url),
        "source_age_days": None,
        "detail_url": source_url or reverse("deals_swiper"),
        "generated_at": item.created_at,
        "is_legacy_instagram": True,
    }
    if show_internal_gain:
        card["my_gain"] = ""
    return card


def _all_opportunity_items():
    items = []
    for category, config in OPPORTUNITY_CONFIG.items():
        for item in config["model"].objects.all():
            items.append((category, item))
    return items


def _legacy_instagram_deals():
    return list(
        DealSnapshot.objects.select_related("listing")
        .filter(listing__source_type=SourceType.INSTAGRAM)
        .order_by("-margin_pct", "-margin_eur", "-id")
    )


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


def estore_opportunity_index(request):
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
    legacy_deals = _legacy_instagram_deals()
    if active_category and active_category != "phone":
        legacy_deals = []
    if active_brand:
        legacy_deals = [item for item in legacy_deals if item.brand_name.lower() == active_brand.lower()]
    if query:
        lowered_query = query.lower()
        legacy_deals = [
            item
            for item in legacy_deals
            if lowered_query in f"{item.brand_name} {item.model_name} {item.storage_gb or ''} {item.title}".lower()
        ]
    cards.extend(
        _legacy_instagram_deal_card(item, selected_currency, show_internal_gain=show_internal_gain)
        for item in legacy_deals
    )
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
    counts["phone"] += DealSnapshot.objects.filter(listing__source_type=SourceType.INSTAGRAM).count()

    return render(
        request,
        "estore/listing_index.html",
        {
            "plan_payload": _json_payload({
                "page": "opportunity-index",
                "frontend": "server-rendered-estore",
                "cards": cards,
                "total_count": len(cards),
                "active_category": active_category,
                "active_brand": active_brand,
                "brand_options": brand_options,
                "query": query,
                "selected_currency": selected_currency,
            }),
            "cards": cards,
            "total_count": len(cards),
            "counts": counts,
            "active_category": active_category,
            "active_brand": active_brand,
            "brand_options": brand_options,
            "query": query,
            "selected_currency": selected_currency,
            "category_options": [
                {"value": key, "label": value["plural"], "count": counts[key]}
                for key, value in OPPORTUNITY_CONFIG.items()
            ],
            "can_view_internal_gain": show_internal_gain,
        },
    )


def estore_opportunity_detail(request, category, pk):
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

    primary = _primary_listing(item, category)
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
        "coverage": {
            "algeria": item.algeria_count,
            "turkiye": item.turkiye_count,
        },
        "generated_at": item.generated_at,
        "source_label": item.source_label if show_operational_meta else "",
    }

    return render(
        request,
        "estore/listing_detail.html",
        {
            "plan_payload": _json_payload({
                "page": "opportunity-detail",
                "frontend": "server-rendered-estore",
                "opportunity": detail,
                "selected_currency": selected_currency,
            }),
            "opportunity": detail,
            "algeria_rows": algeria_rows,
            "turkiye_rows": turkiye_rows,
            "selected_currency": selected_currency,
            "can_view_internal_gain": show_internal_gain,
            "can_view_operational_meta": show_operational_meta,
        },
    )
