from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlsplit

from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from market.models import ConsoleListing, LaptopListing, PhoneListing
from market.services.currency import eur_to_try


LISTING_CONFIG = {
    "phone": {
        "model": PhoneListing,
        "model_field": "phone_model",
        "label": "Telefon",
        "plural": "Telefonlar",
    },
    "laptop": {
        "model": LaptopListing,
        "model_field": "laptop_model",
        "label": "Laptop",
        "plural": "Laptoplar",
    },
    "console": {
        "model": ConsoleListing,
        "model_field": "console_model",
        "label": "Konsol",
        "plural": "Konsollar",
    },
}

VISIBLE_REVIEW_STATUSES = {"auto", "approved", "needs_review"}

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


def _format_number(value, digits=0):
    if value is None:
        return ""
    amount = Decimal(str(value))
    text = f"{amount:,.{digits}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _format_money(value, currency):
    if value is None:
        return "Fiyat belirtilmemiş"
    currency = (currency or "").upper()
    symbol = {
        "TRY": "TL",
        "EUR": "€",
        "USD": "$",
        "DZD": "DZD",
    }.get(currency, currency)
    return f"{_format_number(value, 0)} {symbol}".strip()


def _try_price(listing):
    if listing.price_eur is None:
        return None
    return eur_to_try(listing.price_eur)


def _brand_and_model(listing, config):
    model_obj = getattr(listing, config["model_field"], None)
    if not model_obj:
        return "", ""
    brand_obj = getattr(model_obj, "brand", None)
    brand = getattr(brand_obj, "name", "") if brand_obj else ""
    model = getattr(model_obj, "canonical_name", "") or str(model_obj)
    return brand, model


def _listing_title(listing, brand, model):
    return (listing.title or f"{brand} {model}".strip() or f"İlan #{listing.pk}").strip()


def _has_image(listing):
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


def _source_url(listing):
    direct = _safe_external_url(getattr(listing, "listing_url", ""))
    if direct:
        return direct
    raw = getattr(listing, "raw_listing", None)
    return _safe_external_url(getattr(raw, "listing_url", "")) if raw else ""


def _specs_for(listing, category):
    specs = []

    def add(label, value, suffix=""):
        if value in (None, ""):
            return
        specs.append({"label": label, "value": f"{value}{suffix}"})

    if category == "phone":
        add("Depolama", listing.storage_gb, " GB")
        add("RAM", listing.ram_gb, " GB")
        add("Batarya", listing.battery_health, "%")
        add("Batarya döngüsü", listing.battery_cycles)
        add("SIM", listing.sim_config)
        add("Kutu", listing.box_status)
        add("Bölge", listing.region)
        add("Renk", listing.color)
    elif category == "laptop":
        add("İşlemci", listing.cpu)
        add("Ekran kartı", listing.gpu)
        add("RAM", listing.ram_gb, " GB")
        add("Depolama", listing.storage_gb, " GB")
        add("Ekran", listing.screen_size, '"')
        add("Çözünürlük", listing.resolution)
        add("Yenileme hızı", listing.refresh_rate_hz, " Hz")
        add("Panel", listing.panel_type)
    elif category == "console":
        add("Yonga seti", listing.chipset)
        add("RAM", listing.ram_gb, " GB")
        add("Depolama", listing.storage_gb, " GB")
        add("Ekran", listing.screen_size, '"')
        add("Yenileme hızı", listing.refresh_rate_hz, " Hz")
        add("Bağlantı", listing.connectivity)
        add("Renk", listing.color)

    return specs


def _card_subtitle(specs):
    values = [item["value"] for item in specs[:3]]
    return " · ".join(values)


def _listing_card(listing, category):
    config = LISTING_CONFIG[category]
    brand, model = _brand_and_model(listing, config)
    specs = _specs_for(listing, category)
    image_url = (
        reverse("clean_listing_image", kwargs={"category": category, "pk": listing.pk})
        if _has_image(listing)
        else ""
    )
    price_try = _try_price(listing)
    title = _listing_title(listing, brand, model)

    return {
        "pk": listing.pk,
        "category": category,
        "category_label": config["label"],
        "brand": brand,
        "model": model,
        "title": title,
        "initials": "".join(part[0] for part in (brand or title).split()[:2]).upper() or "PB",
        "subtitle": _card_subtitle(specs),
        "specs": specs,
        "condition": CONDITION_LABELS_TR.get(listing.condition, listing.get_condition_display()),
        "country": COUNTRY_LABELS_TR.get(listing.country, listing.get_country_display()),
        "source": listing.source.name if listing.source_id else listing.get_source_type_display(),
        "source_type": listing.source_type,
        "price_original": (
            _format_money(listing.price_original, listing.currency_original)
            if listing.price_original is not None
            else _format_money(listing.price_eur, "EUR")
        ),
        "price_try": _format_money(price_try, "TRY") if price_try is not None else "",
        "has_image": bool(image_url),
        "image_url": image_url,
        "detail_url": reverse(
            "estore_listing_detail",
            kwargs={"category": category, "pk": listing.pk},
        ),
        "observed_at": listing.observed_at,
        "review_status": listing.review_status,
    }


def _queryset_for(category):
    config = LISTING_CONFIG[category]
    return (
        config["model"].objects.select_related(
            "raw_listing",
            "source",
            config["model_field"],
            f"{config['model_field']}__brand",
            "variant",
        )
        .filter(review_status__in=VISIBLE_REVIEW_STATUSES)
        .order_by("-observed_at", "-pk")
    )


def estore_listing_index(request):
    active_category = request.GET.get("category", "").strip().lower()
    if active_category not in LISTING_CONFIG:
        active_category = ""

    query = request.GET.get("q", "").strip()
    countries = request.GET.getlist("country")
    countries = [value for value in countries if value in COUNTRY_LABELS_TR]

    categories = [active_category] if active_category else list(LISTING_CONFIG)
    cards = []

    for category in categories:
        queryset = _queryset_for(category)
        if countries:
            queryset = queryset.filter(country__in=countries)

        for listing in queryset:
            card = _listing_card(listing, category)
            if query:
                haystack = " ".join(
                    [
                        card["title"],
                        card["brand"],
                        card["model"],
                        card["subtitle"],
                        card["source"],
                    ]
                ).lower()
                if query.lower() not in haystack:
                    continue
            cards.append(card)

    cards.sort(
        key=lambda card: (
            card["observed_at"],
            card["pk"],
        ),
        reverse=True,
    )

    counts = {
        category: _queryset_for(category).count()
        for category in LISTING_CONFIG
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
            "selected_countries": countries,
            "category_options": [
                {"value": key, "label": value["plural"], "count": counts[key]}
                for key, value in LISTING_CONFIG.items()
            ],
        },
    )


def estore_listing_detail(request, category, pk):
    config = LISTING_CONFIG.get(category)
    if config is None:
        raise Http404("Bilinmeyen ilan kategorisi")

    listing = get_object_or_404(_queryset_for(category), pk=pk)
    card = _listing_card(listing, category)
    raw = listing.raw_listing

    detail = card | {
        "listing_url": _source_url(listing),
        "description": (
            (raw.description_raw or raw.raw_text or "").strip()
            if raw
            else ""
        ),
        "location": (raw.location_raw or "").strip() if raw else "",
        "date_text": (raw.date_text_raw or "").strip() if raw else "",
        "parsed_confidence": round((listing.parsed_confidence or 0) * 100)
        if (listing.parsed_confidence or 0) <= 1
        else round(listing.parsed_confidence or 0),
    }

    return render(
        request,
        "estore/listing_detail.html",
        {
            "listing": detail,
        },
    )
