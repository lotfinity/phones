from decimal import Decimal

from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from market.clean_models import ConsoleOpportunitySnapshot, LaptopOpportunitySnapshot, PhoneOpportunitySnapshot
from market.models import (
    ConsoleListing,
    Country,
    LaptopListing,
    ParsedListingCandidate,
    PhoneListing,
    RawListing,
)
from market.services.gain_split import compute_gain_split
from market.views import base_context, money, money_amount, pct


CLEAN_SNAPSHOT_MODELS = {
    "phone": PhoneOpportunitySnapshot,
    "laptop": LaptopOpportunitySnapshot,
    "console": ConsoleOpportunitySnapshot,
}

CLEAN_LISTING_MODELS = {
    "phone": PhoneListing,
    "laptop": LaptopListing,
    "console": ConsoleListing,
}

CATEGORY_LABELS = {
    "phone": "Phone",
    "laptop": "Laptop",
    "console": "Portable console",
}

SOURCE_META = {
    "instagram": ("IG", "ig"),
    "ouedkniss": ("OK", "ok"),
    "sahibinden": ("SH", "sh"),
    "supplier": ("SL", "sl"),
    "manual": ("MN", "mn"),
}

VISIBLE_REVIEW_STATUSES = {
    PhoneListing.ReviewStatus.AUTO,
    PhoneListing.ReviewStatus.APPROVED,
    PhoneListing.ReviewStatus.NEEDS_REVIEW,
}


def can_view_internal_gain(request):
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_superuser)


def can_view_operational_meta(request):
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_staff)


def _snapshot_spec(item, device_type):
    parts = []
    if device_type == "phone":
        if item.storage_gb:
            parts.append(f"{item.storage_gb}GB")
    elif device_type == "laptop":
        if item.cpu:
            parts.append(item.cpu)
        if item.gpu:
            parts.append(item.gpu)
        if item.ram_gb:
            parts.append(f"{item.ram_gb}GB RAM")
        if item.storage_gb:
            parts.append(f"{item.storage_gb}GB")
    elif device_type == "console":
        if item.chipset:
            parts.append(item.chipset)
        if item.ram_gb:
            parts.append(f"{item.ram_gb}GB RAM")
        if item.storage_gb:
            parts.append(f"{item.storage_gb}GB")
    return " / ".join(parts) or "-"


def _recommendation_class(value):
    if value in {"buy", "good_opportunity"}:
        return "rec-buy"
    if value in {"watch", "marginal", "low_confidence"}:
        return "rec-watch"
    return "rec-ignore"


def _snapshot_row(item, device_type):
    return {
        "item": item,
        "snapshot_id": item.pk,
        "device_type": device_type,
        "category_label": CATEGORY_LABELS[device_type],
        "brand": item.brand,
        "model": item.model,
        "title": f"{item.brand} {item.model}".strip(),
        "spec": _snapshot_spec(item, device_type),
        "algeria_min_eur": item.algeria_min_eur,
        "algeria_avg_eur": item.algeria_avg_eur,
        "turkiye_min_eur": item.turkiye_min_eur,
        "turkiye_avg_eur": item.turkiye_avg_eur,
        "gross_margin_eur": item.gross_margin_eur,
        "margin_percent": item.margin_percent,
        "algeria_count": item.algeria_count,
        "turkiye_count": item.turkiye_count,
        "recommendation": item.get_recommendation_display(),
        "recommendation_value": item.recommendation,
        "recommendation_class": _recommendation_class(item.recommendation),
        "confidence_score": item.confidence_score,
        "algeria_urls": item.algeria_urls or [],
        "turkiye_urls": item.turkiye_urls or [],
        "generated_at": item.generated_at,
        "source_label": item.source_label,
        "detail_url": reverse(
            "clean_opportunity_detail",
            kwargs={"category": device_type, "pk": item.pk},
        ),
    }


def _clean_snapshot_rows():
    rows = []
    for device_type, model in CLEAN_SNAPSHOT_MODELS.items():
        for item in model.objects.order_by("-gross_margin_eur", "-margin_percent")[:300]:
            rows.append(_snapshot_row(item, device_type))
    rows.sort(
        key=lambda row: (
            row["gross_margin_eur"] or Decimal("0"),
            row["margin_percent"] or Decimal("0"),
        ),
        reverse=True,
    )
    return rows


def _filtered_clean_rows(request):
    device_type = request.GET.get("type", "").strip()
    brand = request.GET.get("brand", "").strip()
    q = request.GET.get("q", "").strip()

    rows = _clean_snapshot_rows()
    if device_type:
        rows = [row for row in rows if row["device_type"] == device_type]
    if brand:
        rows = [row for row in rows if row["brand"].lower() == brand.lower()]
    if q:
        q_lower = q.lower()
        rows = [
            row
            for row in rows
            if q_lower in row["model"].lower()
            or q_lower in row["brand"].lower()
            or q_lower in row["spec"].lower()
        ]
    return rows, device_type, brand, q


def _display_row(row, selected_currency, *, show_internal_gain=False):
    display = row | {
        "algeria_min": money(row["algeria_min_eur"], selected_currency)
        if row["algeria_min_eur"] is not None
        else "-",
        "algeria_avg": money(row["algeria_avg_eur"], selected_currency)
        if row["algeria_avg_eur"] is not None
        else "-",
        "turkiye_min": money(row["turkiye_min_eur"], selected_currency)
        if row["turkiye_min_eur"] is not None
        else "-",
        "turkiye_avg": money(row["turkiye_avg_eur"], selected_currency)
        if row["turkiye_avg_eur"] is not None
        else "-",
        "gross_margin": money(row["gross_margin_eur"], selected_currency)
        if row["gross_margin_eur"] is not None
        else "-",
        "margin_percent_label": pct(row["margin_percent"])
        if row["margin_percent"] is not None
        else "-",
        "margin_class": "good"
        if row["margin_percent"] is not None and row["margin_percent"] >= Decimal("20")
        else "warn",
        "counts_label": f"DZ {row['algeria_count']} / TR {row['turkiye_count']}",
    }

    gain_split = compute_gain_split(
        algeria_min_eur=row.get("algeria_min_eur"),
        turkiye_avg_eur=row.get("turkiye_avg_eur"),
        gross_margin_eur=row.get("gross_margin_eur"),
    )
    if not gain_split:
        return display

    display.update(
        {
            "buyer_offer": money(gain_split["offer_price_to_buyer_eur"], selected_currency),
            "buyer_offer_dzd": money_amount(gain_split["offer_price_to_buyer_dzd"], "DZD"),
            "buyer_gain": money(gain_split["buyer_gain_eur"], selected_currency),
            "buyer_gain_percent": pct(gain_split["buyer_gain_percent"]),
            "deal_quality": gain_split["deal_quality"],
        }
    )

    if show_internal_gain:
        display.update(
            {
                "my_gain": money(gain_split["my_gain_eur"], selected_currency),
                "my_gain_dzd": money_amount(gain_split["my_gain_dzd"], "DZD"),
                "my_gain_percent": pct(gain_split["my_gain_percent_of_gross"]),
                "pricing_basis": gain_split["pricing_basis"],
                "pricing_notes": gain_split["notes"],
            }
        )
    return display


def _shared_clean_context(request, rows, device_type, brand, q):
    selected_currency = request.GET.get("currency") or request.COOKIES.get("pricebridge_currency") or "EUR"
    show_internal_gain = can_view_internal_gain(request)
    show_operational_meta = can_view_operational_meta(request)
    visible_rows = rows[:300]
    display_rows = [
        _display_row(row, selected_currency, show_internal_gain=show_internal_gain)
        for row in visible_rows
    ]
    total_gross = sum((row["gross_margin_eur"] or Decimal("0")) for row in visible_rows)
    margins = [row["margin_percent"] for row in visible_rows if row["margin_percent"] is not None]
    avg_margin = sum(margins) / len(margins) if margins else None
    latest_candidates = [
        PhoneOpportunitySnapshot.objects.order_by("-generated_at").values_list("generated_at", flat=True).first(),
        LaptopOpportunitySnapshot.objects.order_by("-generated_at").values_list("generated_at", flat=True).first(),
        ConsoleOpportunitySnapshot.objects.order_by("-generated_at").values_list("generated_at", flat=True).first(),
    ]
    latest_generated_at = max([item for item in latest_candidates if item], default=None)
    all_rows = _clean_snapshot_rows()
    brand_values = sorted({row["brand"] for row in all_rows if row["brand"]})

    return {
        "rows": display_rows,
        "snapshots_count": len(rows),
        "visible_count": len(display_rows),
        "total_gross": money(total_gross, selected_currency) if total_gross else "-",
        "avg_margin": pct(avg_margin) if avg_margin is not None else "-",
        "latest_generated_at": latest_generated_at,
        "brands": brand_values,
        "brand_list": [{"name": value} for value in brand_values],
        "active_brand": brand,
        "active_type": device_type,
        "search_query": q,
        "device_counts": {
            "phone": PhoneOpportunitySnapshot.objects.count(),
            "laptop": LaptopOpportunitySnapshot.objects.count(),
            "console": ConsoleOpportunitySnapshot.objects.count(),
        },
        "source_counts": {
            "raw_total": RawListing.objects.count(),
            "phone_total": PhoneListing.objects.count(),
            "laptop_total": LaptopListing.objects.count(),
            "console_total": ConsoleListing.objects.count(),
            "needs_review": ParsedListingCandidate.objects.filter(
                status=ParsedListingCandidate.Status.NEEDS_REVIEW
            ).count(),
        },
        "best_opportunity": display_rows[0] if display_rows else None,
        "can_view_internal_gain": show_internal_gain,
        "can_view_operational_meta": show_operational_meta,
    }


def _matching_listing_queryset(item, category):
    model = CLEAN_LISTING_MODELS[category]
    related_model_field = {
        "phone": "phone_model",
        "laptop": "laptop_model",
        "console": "console_model",
    }[category]
    snapshot_model_id = getattr(item, f"{related_model_field}_id")

    qs = model.objects.select_related("source", "raw_listing", related_model_field, "variant").filter(
        price_eur__isnull=False,
        review_status__in=VISIBLE_REVIEW_STATUSES,
    )

    if snapshot_model_id:
        qs = qs.filter(**{f"{related_model_field}_id": snapshot_model_id})
    else:
        qs = qs.filter(
            **{
                f"{related_model_field}__canonical_name__iexact": item.model,
                f"{related_model_field}__brand__name__iexact": item.brand,
            }
        )

    if category == "phone":
        if item.storage_gb:
            qs = qs.filter(storage_gb=item.storage_gb)
    elif category == "laptop":
        if item.cpu:
            qs = qs.filter(cpu__iexact=item.cpu)
        if item.gpu:
            qs = qs.filter(gpu__iexact=item.gpu)
        if item.ram_gb:
            qs = qs.filter(ram_gb=item.ram_gb)
        if item.storage_gb:
            qs = qs.filter(storage_gb=item.storage_gb)
    elif category == "console":
        if item.chipset:
            qs = qs.filter(chipset__iexact=item.chipset)
        if item.ram_gb:
            qs = qs.filter(ram_gb=item.ram_gb)
        if item.storage_gb:
            qs = qs.filter(storage_gb=item.storage_gb)

    return qs.order_by("price_eur", "-observed_at")


def _listing_spec(listing, category):
    parts = []
    if category == "phone":
        if listing.storage_gb:
            parts.append(f"{listing.storage_gb}GB")
        if listing.ram_gb:
            parts.append(f"{listing.ram_gb}GB RAM")
        if listing.sim_config:
            parts.append(listing.sim_config)
        if listing.battery_health:
            parts.append(f"battery {listing.battery_health}%")
        if listing.box_status:
            parts.append(listing.box_status)
        if listing.region:
            parts.append(listing.region)
    elif category == "laptop":
        if listing.cpu:
            parts.append(listing.cpu)
        if listing.gpu:
            parts.append(listing.gpu)
        if listing.ram_gb:
            parts.append(f"{listing.ram_gb}GB RAM")
        if listing.storage_gb:
            parts.append(f"{listing.storage_gb}GB")
        if listing.screen_size:
            parts.append(f'{listing.screen_size}"')
        if listing.resolution:
            parts.append(listing.resolution)
        if listing.refresh_rate_hz:
            parts.append(f"{listing.refresh_rate_hz}Hz")
    else:
        if listing.chipset:
            parts.append(listing.chipset)
        if listing.ram_gb:
            parts.append(f"{listing.ram_gb}GB RAM")
        if listing.storage_gb:
            parts.append(f"{listing.storage_gb}GB")
        if listing.screen_size:
            parts.append(f'{listing.screen_size}"')
        if listing.refresh_rate_hz:
            parts.append(f"{listing.refresh_rate_hz}Hz")
        if listing.connectivity:
            parts.append(listing.connectivity)
    return " / ".join(parts) or "-"


def _review_class(status):
    return {
        "auto": "review-auto",
        "approved": "review-approved",
        "needs_review": "review-needs",
        "rejected": "review-rejected",
    }.get(status, "")


def _prepare_listing(listing, category, selected_currency):
    source_code, source_class = SOURCE_META.get(listing.source_type, (listing.source_type[:2].upper(), "mn"))
    raw_listing = listing.raw_listing
    image_url = listing.image_url or (raw_listing.image_url if raw_listing else "")
    title = listing.title or (raw_listing.title_raw if raw_listing else "") or str(listing)
    return {
        "item": listing,
        "title": title,
        "listing_url": listing.listing_url or (raw_listing.listing_url if raw_listing else ""),
        "image_url": image_url,
        "source_code": source_code,
        "source_class": source_class,
        "source_name": listing.source.name if listing.source else listing.get_source_type_display(),
        "country": listing.country,
        "country_label": listing.get_country_display(),
        "condition": listing.get_condition_display(),
        "review_status": listing.get_review_status_display(),
        "review_class": _review_class(listing.review_status),
        "observed_at": listing.observed_at,
        "price_original": listing.price_original,
        "currency_original": listing.currency_original,
        "price_eur": money(listing.price_eur, selected_currency) if listing.price_eur is not None else "-",
        "spec": _listing_spec(listing, category),
        "parsed_confidence": int(round((listing.parsed_confidence or 0) * 100)),
        "admin_url": reverse(f"admin:market_{listing._meta.model_name}_change", args=[listing.pk]),
        "is_fallback": False,
    }


def _fallback_evidence(url, country):
    is_algeria = country == Country.ALGERIA
    return {
        "item": None,
        "title": "Stored Algeria evidence" if is_algeria else "Stored Türkiye evidence",
        "listing_url": url,
        "image_url": "",
        "source_code": "DZ" if is_algeria else "SH",
        "source_class": "ok" if is_algeria else "sh",
        "source_name": "Snapshot URL",
        "country": country,
        "country_label": "Algeria" if is_algeria else "Türkiye",
        "condition": "",
        "review_status": "",
        "review_class": "",
        "observed_at": None,
        "price_original": None,
        "currency_original": "",
        "price_eur": "-",
        "spec": "Stored on the clean opportunity snapshot",
        "parsed_confidence": None,
        "admin_url": "",
        "is_fallback": True,
    }


def _evidence_rows(item, category, selected_currency):
    listings = list(_matching_listing_queryset(item, category)[:200])
    prepared = [_prepare_listing(listing, category, selected_currency) for listing in listings]

    algeria_rows = [row for row in prepared if row["country"] == Country.ALGERIA]
    turkiye_rows = [row for row in prepared if row["country"] == Country.TURKIYE]

    known_urls = {row["listing_url"] for row in prepared if row["listing_url"]}
    for url in item.algeria_urls or []:
        if url and url not in known_urls:
            algeria_rows.append(_fallback_evidence(url, Country.ALGERIA))
            known_urls.add(url)
    for url in item.turkiye_urls or []:
        if url and url not in known_urls:
            turkiye_rows.append(_fallback_evidence(url, Country.TURKIYE))
            known_urls.add(url)

    return algeria_rows, turkiye_rows


def clean_opportunities(request):
    rows, device_type, brand, q = _filtered_clean_rows(request)
    return render(
        request,
        "market/clean_opportunities.html",
        base_context(request, "opportunities")
        | _shared_clean_context(request, rows, device_type, brand, q),
    )


def clean_card_opportunities(request):
    """Card-based UI backed only by the clean snapshot tables."""
    rows, device_type, brand, q = _filtered_clean_rows(request)
    return render(
        request,
        "market/clean_card_opportunities.html",
        base_context(request, "opportunities")
        | _shared_clean_context(request, rows, device_type, brand, q),
    )


def clean_opportunity_detail(request, category, pk):
    model = CLEAN_SNAPSHOT_MODELS.get(category)
    if model is None:
        raise Http404("Unknown clean opportunity category")

    item = get_object_or_404(model, pk=pk)
    selected_currency = request.GET.get("currency") or request.COOKIES.get("pricebridge_currency") or "EUR"
    show_internal_gain = can_view_internal_gain(request)
    show_operational_meta = can_view_operational_meta(request)
    row = _display_row(
        _snapshot_row(item, category),
        selected_currency,
        show_internal_gain=show_internal_gain,
    )
    algeria_rows, turkiye_rows = _evidence_rows(item, category, selected_currency)
    all_evidence = algeria_rows + turkiye_rows
    hero_image_url = next((entry["image_url"] for entry in all_evidence if entry["image_url"]), "")

    admin_url = reverse(f"admin:market_{item._meta.model_name}_change", args=[item.pk])
    coverage = [
        {"code": "DZ", "count": len(algeria_rows), "class": "ok"},
        {"code": "TR", "count": len(turkiye_rows), "class": "sh"},
    ]

    return render(
        request,
        "market/clean_opportunity_detail.html",
        base_context(request, "opportunities")
        | {
            "row": row,
            "hero_image_url": hero_image_url,
            "coverage": coverage,
            "algeria_rows": algeria_rows,
            "turkiye_rows": turkiye_rows,
            "admin_url": admin_url,
            "can_view_internal_gain": show_internal_gain,
            "can_view_operational_meta": show_operational_meta,
        },
    )
