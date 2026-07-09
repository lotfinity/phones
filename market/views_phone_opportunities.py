from decimal import Decimal

from django.db.models import Avg, Count, Sum
from django.shortcuts import render

from market.clean_models import PhoneOpportunitySnapshot
from market.models import ParsedListingCandidate, PhoneListing, RawListing, SourceType
from market.views import base_context, money, pct


def _money_or_dash(value, currency="EUR"):
    return money(value, currency) if value is not None else "-"


def _pct_or_dash(value):
    return pct(value) if value is not None else "-"


def _row(snapshot, selected_currency="EUR"):
    return {
        "item": snapshot,
        "brand": snapshot.brand,
        "model": snapshot.model,
        "storage": f"{snapshot.storage_gb}GB" if snapshot.storage_gb else "-",
        "algeria_min": _money_or_dash(snapshot.algeria_min_eur, selected_currency),
        "algeria_avg": _money_or_dash(snapshot.algeria_avg_eur, selected_currency),
        "turkiye_min": _money_or_dash(snapshot.turkiye_min_eur, selected_currency),
        "turkiye_avg": _money_or_dash(snapshot.turkiye_avg_eur, selected_currency),
        "gross_margin": _money_or_dash(snapshot.gross_margin_eur, selected_currency),
        "margin_percent": _pct_or_dash(snapshot.margin_percent),
        "margin_class": "good" if snapshot.margin_percent and snapshot.margin_percent >= Decimal("20") else "warn",
        "recommendation_class": {
            PhoneOpportunitySnapshot.Recommendation.BUY: "rec-buy",
            PhoneOpportunitySnapshot.Recommendation.WATCH: "rec-watch",
            PhoneOpportunitySnapshot.Recommendation.IGNORE: "rec-ignore",
        }.get(snapshot.recommendation, "rec-watch"),
        "recommendation_label": snapshot.get_recommendation_display(),
        "counts_label": f"DZ {snapshot.algeria_count} / TR {snapshot.turkiye_count}",
        "algeria_urls": snapshot.algeria_urls or [],
        "turkiye_urls": snapshot.turkiye_urls or [],
    }


def phone_opportunities_v2(request):
    selected_currency = request.GET.get("currency") or request.COOKIES.get("pricebridge_currency") or "EUR"
    brand = request.GET.get("brand", "").strip()
    q = request.GET.get("q", "").strip()
    rec = request.GET.get("rec", "").strip()

    qs = PhoneOpportunitySnapshot.objects.select_related("phone_model").order_by(
        "-gross_margin_eur", "-margin_percent"
    )
    if brand:
        qs = qs.filter(brand__iexact=brand)
    if q:
        qs = qs.filter(model__icontains=q)
    if rec:
        qs = qs.filter(recommendation=rec)

    snapshots = list(qs[:300])
    rows = [_row(item, selected_currency) for item in snapshots]

    all_qs = PhoneOpportunitySnapshot.objects.all()
    totals = all_qs.aggregate(
        count=Count("id"),
        gross=Sum("gross_margin_eur"),
        avg_margin=Avg("margin_percent"),
    )
    visible_gross = sum((item.gross_margin_eur or Decimal("0")) for item in snapshots)
    best = snapshots[0] if snapshots else None
    latest = all_qs.order_by("-generated_at").first()

    source_counts = {
        "raw_total": RawListing.objects.count(),
        "phone_total": PhoneListing.objects.count(),
        "instagram_raw": RawListing.objects.filter(source_type=SourceType.INSTAGRAM).count(),
        "instagram_phone": PhoneListing.objects.filter(source_type=SourceType.INSTAGRAM).count(),
        "needs_review": ParsedListingCandidate.objects.filter(status=ParsedListingCandidate.Status.NEEDS_REVIEW).count(),
    }

    brands = list(
        all_qs.values_list("brand", flat=True)
        .exclude(brand="")
        .distinct()
        .order_by("brand")
    )

    return render(
        request,
        "market/phone_opportunities_v2.html",
        base_context(request, "opportunities")
        | {
            "rows": rows,
            "snapshots_count": totals["count"] or 0,
            "visible_count": len(rows),
            "total_gross": money(totals["gross"], selected_currency) if totals["gross"] else "-",
            "visible_gross": money(visible_gross, selected_currency),
            "avg_margin": pct(totals["avg_margin"]) if totals["avg_margin"] is not None else "-",
            "best_snapshot": _row(best, selected_currency) if best else None,
            "latest_generated_at": latest.generated_at if latest else None,
            "source_counts": source_counts,
            "brands": brands,
            "active_brand": brand,
            "active_rec": rec,
            "search_query": q,
            "recommendations": PhoneOpportunitySnapshot.Recommendation.choices,
        },
    )
