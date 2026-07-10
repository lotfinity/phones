from decimal import Decimal

from django.db.models import Avg, Count, Sum
from django.shortcuts import render

from market.clean_models import ConsoleOpportunitySnapshot, LaptopOpportunitySnapshot, PhoneOpportunitySnapshot
from market.models import ConsoleListing, LaptopListing, ParsedListingCandidate, PhoneListing, RawListing
from market.views import base_context, money, pct


def _clean_snapshot_rows():
    rows = []
    for item in PhoneOpportunitySnapshot.objects.order_by("-gross_margin_eur", "-margin_percent")[:300]:
        rows.append({
            "device_type": "phone",
            "brand": item.brand,
            "model": item.model,
            "spec": f"{item.storage_gb}GB" if item.storage_gb else "-",
            "algeria_min_eur": item.algeria_min_eur,
            "turkiye_avg_eur": item.turkiye_avg_eur,
            "gross_margin_eur": item.gross_margin_eur,
            "margin_percent": item.margin_percent,
            "algeria_count": item.algeria_count,
            "turkiye_count": item.turkiye_count,
            "recommendation": item.get_recommendation_display(),
            "confidence_score": item.confidence_score,
            "algeria_urls": item.algeria_urls or [],
            "turkiye_urls": item.turkiye_urls or [],
            "generated_at": item.generated_at,
        })
    for item in LaptopOpportunitySnapshot.objects.order_by("-gross_margin_eur", "-margin_percent")[:300]:
        spec_parts = []
        if item.cpu:
            spec_parts.append(item.cpu)
        if item.gpu:
            spec_parts.append(item.gpu)
        if item.ram_gb:
            spec_parts.append(f"{item.ram_gb}GB RAM")
        if item.storage_gb:
            spec_parts.append(f"{item.storage_gb}GB")
        rows.append({
            "device_type": "laptop",
            "brand": item.brand,
            "model": item.model,
            "spec": " / ".join(spec_parts) or "-",
            "algeria_min_eur": item.algeria_min_eur,
            "turkiye_avg_eur": item.turkiye_avg_eur,
            "gross_margin_eur": item.gross_margin_eur,
            "margin_percent": item.margin_percent,
            "algeria_count": item.algeria_count,
            "turkiye_count": item.turkiye_count,
            "recommendation": item.get_recommendation_display(),
            "confidence_score": item.confidence_score,
            "algeria_urls": item.algeria_urls or [],
            "turkiye_urls": item.turkiye_urls or [],
            "generated_at": item.generated_at,
        })
    for item in ConsoleOpportunitySnapshot.objects.order_by("-gross_margin_eur", "-margin_percent")[:300]:
        spec_parts = []
        if item.chipset:
            spec_parts.append(item.chipset)
        if item.ram_gb:
            spec_parts.append(f"{item.ram_gb}GB RAM")
        if item.storage_gb:
            spec_parts.append(f"{item.storage_gb}GB")
        rows.append({
            "device_type": "console",
            "brand": item.brand,
            "model": item.model,
            "spec": " / ".join(spec_parts) or "-",
            "algeria_min_eur": item.algeria_min_eur,
            "turkiye_avg_eur": item.turkiye_avg_eur,
            "gross_margin_eur": item.gross_margin_eur,
            "margin_percent": item.margin_percent,
            "algeria_count": item.algeria_count,
            "turkiye_count": item.turkiye_count,
            "recommendation": item.get_recommendation_display(),
            "confidence_score": item.confidence_score,
            "algeria_urls": item.algeria_urls or [],
            "turkiye_urls": item.turkiye_urls or [],
            "generated_at": item.generated_at,
        })
    rows.sort(
        key=lambda row: (
            row["gross_margin_eur"] or Decimal("0"),
            row["margin_percent"] or Decimal("0"),
        ),
        reverse=True,
    )
    return rows


def clean_opportunities(request):
    selected_currency = request.GET.get("currency") or request.COOKIES.get("pricebridge_currency") or "EUR"
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
            row for row in rows
            if q_lower in row["model"].lower() or q_lower in row["brand"].lower() or q_lower in row["spec"].lower()
        ]

    visible_rows = rows[:300]
    total_gross = sum((row["gross_margin_eur"] or Decimal("0")) for row in visible_rows)
    margins = [row["margin_percent"] for row in visible_rows if row["margin_percent"] is not None]
    avg_margin = sum(margins) / len(margins) if margins else None
    latest_candidates = [
        PhoneOpportunitySnapshot.objects.order_by("-generated_at").values_list("generated_at", flat=True).first(),
        LaptopOpportunitySnapshot.objects.order_by("-generated_at").values_list("generated_at", flat=True).first(),
        ConsoleOpportunitySnapshot.objects.order_by("-generated_at").values_list("generated_at", flat=True).first(),
    ]
    latest_generated_at = max([item for item in latest_candidates if item], default=None)

    brands = sorted({row["brand"] for row in _clean_snapshot_rows() if row["brand"]})
    device_counts = {
        "phone": PhoneOpportunitySnapshot.objects.count(),
        "laptop": LaptopOpportunitySnapshot.objects.count(),
        "console": ConsoleOpportunitySnapshot.objects.count(),
    }
    source_counts = {
        "raw_total": RawListing.objects.count(),
        "phone_total": PhoneListing.objects.count(),
        "laptop_total": LaptopListing.objects.count(),
        "console_total": ConsoleListing.objects.count(),
        "needs_review": ParsedListingCandidate.objects.filter(status=ParsedListingCandidate.Status.NEEDS_REVIEW).count(),
    }

    display_rows = []
    for row in visible_rows:
        display_rows.append(row | {
            "algeria_min": money(row["algeria_min_eur"], selected_currency) if row["algeria_min_eur"] is not None else "-",
            "turkiye_avg": money(row["turkiye_avg_eur"], selected_currency) if row["turkiye_avg_eur"] is not None else "-",
            "gross_margin": money(row["gross_margin_eur"], selected_currency) if row["gross_margin_eur"] is not None else "-",
            "margin_percent_label": pct(row["margin_percent"]) if row["margin_percent"] is not None else "-",
            "counts_label": f"DZ {row['algeria_count']} / TR {row['turkiye_count']}",
        })

    return render(
        request,
        "market/clean_opportunities.html",
        base_context(request, "opportunities")
        | {
            "rows": display_rows,
            "snapshots_count": len(rows),
            "visible_count": len(display_rows),
            "total_gross": money(total_gross, selected_currency) if total_gross else "-",
            "avg_margin": pct(avg_margin) if avg_margin is not None else "-",
            "latest_generated_at": latest_generated_at,
            "brands": brands,
            "active_brand": brand,
            "active_type": device_type,
            "search_query": q,
            "device_counts": device_counts,
            "source_counts": source_counts,
        },
    )
