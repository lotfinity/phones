from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlsplit

from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from market.clean_models import (
    ConsoleOpportunitySnapshot,
    LaptopOpportunitySnapshot,
    PhoneOpportunitySnapshot,
)
from market.views_clean import (
    _display_row,
    _evidence_rows,
    _matching_listing_queryset,
    _snapshot_row,
    can_view_internal_gain,
    can_view_operational_meta,
)
from market.views_clean_detail import _restrict_detail_row


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
    primary = _primary_listing(item, category)
    specs = _combined_specs(item, category, primary)
    has_image = _has_image(primary)
    title = display["title"]

    return {
        "pk": item.pk,
        "category": category,
        "category_label": OPPORTUNITY_CONFIG[category]["label"],
        "brand": item.brand,
        "model": item.model,
        "title": title,
        "initials": "".join(part[0] for part in (item.brand or title).split()[:2]).upper() or "PB",
        "subtitle": display["spec"],
        "specs": specs,
        "condition": _condition_label(primary),
        "battery_health": getattr(primary, "battery_health", None) if primary else None,
        "recommendation": _recommendation_label(item.recommendation),
        "recommendation_value": item.recommendation,
        "confidence_score": item.confidence_score,
        "buyer_offer": display.get("buyer_offer", ""),
        "buyer_gain": display.get("buyer_gain", ""),
        "buyer_gain_percent": display.get("buyer_gain_percent", ""),
        "turkiye_avg": display.get("turkiye_avg", ""),
        "turkiye_count": item.turkiye_count,
        "algeria_count": item.algeria_count,
        "evidence_count": (item.algeria_count or 0) + (item.turkiye_count or 0),
        "margin_percent_label": display.get("margin_percent_label", ""),
        "has_image": has_image,
        "image_url": (
            reverse(
                "clean_listing_image",
                kwargs={"category": category, "pk": primary.pk},
            )
            if has_image
            else ""
        ),
        "detail_url": reverse(
            "estore_opportunity_detail",
            kwargs={"category": category, "pk": item.pk},
        ),
        "generated_at": item.generated_at,
        "my_gain": display.get("my_gain", "") if show_internal_gain else "",
    }


def _all_opportunity_items():
    items = []
    for category, config in OPPORTUNITY_CONFIG.items():
        for item in config["model"].objects.all():
            items.append((category, item))
    return items


def _filtered_items(request):
    active_category = request.GET.get("category", "").strip().lower()
    if active_category not in OPPORTUNITY_CONFIG:
        active_category = ""

    query = request.GET.get("q", "").strip().lower()
    items = _all_opportunity_items()

    if active_category:
        items = [entry for entry in items if entry[0] == active_category]

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
    return items, active_category, request.GET.get("q", "").strip()


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
    items, active_category, query = _filtered_items(request)
    cards = [
        _opportunity_card(
            item,
            category,
            selected_currency,
            show_internal_gain=show_internal_gain,
        )
        for category, item in items
    ]

    counts = {
        category: config["model"].objects.count()
        for category, config in OPPORTUNITY_CONFIG.items()
    }

    return render(
        request,
        "estore/listing_index.html",
        {
            "cards": cards,
            "total_count": len(cards),
            "counts": counts,
            "active_category": active_category,
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
            "opportunity": detail,
            "algeria_rows": algeria_rows,
            "turkiye_rows": turkiye_rows,
            "selected_currency": selected_currency,
            "can_view_internal_gain": show_internal_gain,
            "can_view_operational_meta": show_operational_meta,
        },
    )
