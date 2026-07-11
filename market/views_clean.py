from decimal import Decimal

from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from market.clean_models import ConsoleOpportunitySnapshot, LaptopOpportunitySnapshot, PhoneOpportunitySnapshot
from market.models import ConsoleListing, LaptopListing, ParsedListingCandidate, PhoneListing, RawListing
from market.services.gain_split import compute_gain_split
from market.views import base_context, money, money_amount, pct


CLEAN_SNAPSHOT_MODELS = {
    "phone": PhoneOpportunitySnapshot,
    "laptop": LaptopOpportunitySnapshot,
    "console": ConsoleOpportunitySnapshot,
}

CATEGORY_LABELS = {
    "phone": "Phone",
    "laptop": "Laptop",
    "console": "Portable console",
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
    row = _display_row(
        _snapshot_row(item, category),
        selected_currency,
        show_internal_gain=show_internal_gain,
    )
    return render(
        request,
        "market/clean_opportunity_detail.html",
        base_context(request, "opportunities")
        | {
            "row": row,
            "can_view_internal_gain": show_internal_gain,
            "can_view_operational_meta": can_view_operational_meta(request),
        },
    )
