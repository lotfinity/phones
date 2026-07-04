from django.db.models import Avg, Count, Max, Q
from django.shortcuts import get_object_or_404, render

from market.models import (
    Country,
    DeviceVariant,
    InstagramPost,
    MarketListing,
    OCRResult,
    OpportunitySnapshot,
    ProductModel,
    Source,
    SourceType,
    SupplierPrice,
)


def pct(value):
    if value is None:
        return ""
    return f"{value:.1f}%"


def money(value, suffix="EUR"):
    if value is None:
        return ""
    return f"{value:,.2f} {suffix}"


def rec_class(value):
    return {
        "buy": "rec-buy",
        "watch": "rec-watch",
        "ignore": "rec-ignore",
        "insufficient_data": "rec-insufficient",
    }.get(value, "rec-insufficient")


def review_class(value):
    return {
        MarketListing.ReviewStatus.AUTO: "verified",
        MarketListing.ReviewStatus.APPROVED: "verified",
        MarketListing.ReviewStatus.NEEDS_REVIEW: "review",
        MarketListing.ReviewStatus.REJECTED: "excluded",
    }.get(value, "excluded")


def source_code(value):
    return {
        SourceType.INSTAGRAM: "IG",
        SourceType.OUEDKNISS: "OK",
        SourceType.SAHIBINDEN: "SH",
        SourceType.SUPPLIER: "SL",
        SourceType.MANUAL: "MN",
    }.get(value, value[:2].upper())


def source_badge(value):
    return {
        SourceType.INSTAGRAM: "ig",
        SourceType.OUEDKNISS: "ok",
        SourceType.SAHIBINDEN: "sh",
        SourceType.SUPPLIER: "sl",
    }.get(value, "")


def coverage_counts(product_model, storage_gb):
    listing_filter = {
        "product_model": product_model,
        "review_status__in": [MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED],
        "price_eur__isnull": False,
    }
    supplier_filter = {
        "product_model": product_model,
        "active": True,
        "supplier_price_eur__isnull": False,
    }
    if storage_gb:
        listing_filter["variant__storage_gb"] = storage_gb
        supplier_filter["variant__storage_gb"] = storage_gb
    else:
        listing_filter["variant__isnull"] = True
        supplier_filter["variant__isnull"] = True

    rows = (
        MarketListing.objects.filter(**listing_filter)
        .values("source_type")
        .annotate(count=Count("id"))
        .order_by("source_type")
    )
    coverage = [
        {
            "code": source_code(row["source_type"]),
            "class": source_badge(row["source_type"]),
            "count": row["count"],
        }
        for row in rows
    ]
    supplier_count = SupplierPrice.objects.filter(**supplier_filter).count()
    if supplier_count:
        coverage.append(
            {
                "code": source_code(SourceType.SUPPLIER),
                "class": source_badge(SourceType.SUPPLIER),
                "count": supplier_count,
            }
        )
    order = {"IG": 1, "OK": 2, "SH": 3, "SL": 4}
    return sorted(coverage, key=lambda item: order.get(item["code"], 99))


def base_context(active):
    return {"active": active}


def listing_display_rows(listings):
    rows = []
    for item in listings:
        rows.append(
            {
                "item": item,
                "source_code": source_code(item.source_type),
                "review_class": review_class(item.review_status),
                "price": f"{item.price_original or ''} {item.currency_original}".strip(),
                "eur": money(item.price_eur),
            }
        )
    return rows


def dashboard(request):
    opportunities = OpportunitySnapshot.objects.select_related(
        "product_model",
        "product_model__brand",
        "variant",
    ).order_by("-confidence_score", "-margin_percent", "product_model__canonical_name")

    total = opportunities.count()
    buy_count = opportunities.filter(recommendation=OpportunitySnapshot.Recommendation.BUY).count()
    watch_count = opportunities.filter(recommendation=OpportunitySnapshot.Recommendation.WATCH).count()
    avg_margin = opportunities.exclude(margin_percent__isnull=True).aggregate(value=Avg("margin_percent"))["value"]
    max_margin = opportunities.aggregate(value=Max("gross_margin_vs_sahibinden_eur"))["value"]
    usable_algeria = MarketListing.objects.filter(
        country=Country.ALGERIA,
        review_status__in=[MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED],
        price_eur__isnull=False,
    ).count()
    usable_turkiye = MarketListing.objects.filter(
        country=Country.TURKIYE,
        review_status__in=[MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED],
        price_eur__isnull=False,
    ).count()

    opportunity_rows = []
    for item in opportunities[:200]:
        storage = item.variant.storage_gb if item.variant else None
        opportunity_rows.append(
            {
                "item": item,
                "brand": item.product_model.brand.name if item.product_model.brand else "Unknown",
                "recommendation_class": rec_class(item.recommendation),
                "margin_class": "good" if item.margin_percent and item.margin_percent > 15 else "warn",
                "margin_percent": pct(item.margin_percent),
                "algeria_min": money(item.algeria_min_eur),
                "algeria_avg": money(item.algeria_avg_eur),
                "turkiye_avg": money(item.sahibinden_avg_eur),
                "gross_margin": money(item.gross_margin_vs_sahibinden_eur),
                "supplier": money(item.supplier_eur),
                "sources": coverage_counts(item.product_model, storage),
            }
        )

    return render(
        request,
        "market/dashboard.html",
        base_context("opportunities")
        | {
            "stats": [
                {"label": "Opportunities", "value": total, "delta": "latest batch"},
                {"label": "Buy", "value": buy_count, "delta": "actionable"},
                {"label": "Watch", "value": watch_count, "delta": "monitor"},
                {"label": "Avg margin", "value": pct(avg_margin), "delta": "EUR basis"},
                {"label": "Highest margin", "value": money(max_margin), "delta": "gross"},
                {"label": "Algeria usable", "value": usable_algeria, "delta": "buy side"},
                {"label": "Turkiye usable", "value": usable_turkiye, "delta": "sell side"},
                {"label": "Supplier rows", "value": SupplierPrice.objects.count(), "delta": "baseline"},
            ],
            "opportunity_rows": opportunity_rows,
        },
    )


def opportunities(request):
    return dashboard(request)


def opportunity_detail(request, pk):
    opportunity = get_object_or_404(
        OpportunitySnapshot.objects.select_related("product_model", "product_model__brand", "variant"),
        pk=pk,
    )
    storage = opportunity.variant.storage_gb if opportunity.variant else None
    listing_filter = {"product_model": opportunity.product_model}
    if storage:
        listing_filter["variant__storage_gb"] = storage
    else:
        listing_filter["variant__isnull"] = True

    algeria_listings = (
        MarketListing.objects.select_related("source", "product_model", "variant")
        .filter(country=Country.ALGERIA, **listing_filter)
        .order_by("price_eur", "-observed_at")
    )
    turkiye_listings = (
        MarketListing.objects.select_related("source", "product_model", "variant")
        .filter(country=Country.TURKIYE, **listing_filter)
        .order_by("price_eur", "-observed_at")
    )

    return render(
        request,
        "market/opportunity_detail.html",
        base_context("opportunities")
        | {
            "opportunity": opportunity,
            "brand": opportunity.product_model.brand.name if opportunity.product_model.brand else "Unknown",
            "storage": storage,
            "recommendation_class": rec_class(opportunity.recommendation),
            "margin_percent": pct(opportunity.margin_percent),
            "algeria_min": money(opportunity.algeria_min_eur),
            "algeria_avg": money(opportunity.algeria_avg_eur),
            "turkiye_avg": money(opportunity.sahibinden_avg_eur),
            "gross_margin": money(opportunity.gross_margin_vs_sahibinden_eur),
            "supplier": money(opportunity.supplier_eur),
            "coverage": coverage_counts(opportunity.product_model, storage),
            "algeria_rows": listing_display_rows(algeria_listings),
            "turkiye_rows": listing_display_rows(turkiye_listings),
        },
    )


def listings(request):
    listings_qs = MarketListing.objects.select_related("source", "product_model", "variant").order_by("-observed_at")
    search = request.GET.get("q", "").strip()
    source_type = request.GET.get("source_type", "")
    country = request.GET.get("country", "")
    review_status = request.GET.get("review_status", "")

    if search:
        listings_qs = listings_qs.filter(
            Q(title_raw__icontains=search)
            | Q(description_raw__icontains=search)
            | Q(product_model__canonical_name__icontains=search)
            | Q(variant__canonical_label__icontains=search)
        )
    if source_type:
        listings_qs = listings_qs.filter(source_type=source_type)
    if country:
        listings_qs = listings_qs.filter(country=country)
    if review_status:
        listings_qs = listings_qs.filter(review_status=review_status)

    listing_rows = listing_display_rows(listings_qs[:300])

    return render(
        request,
        "market/listings.html",
        base_context("listings")
        | {
            "listing_rows": listing_rows,
            "filters": {
                "q": search,
                "source_type": source_type,
                "country": country,
                "review_status": review_status,
            },
            "source_types": SourceType.choices,
            "countries": Country.choices,
            "review_statuses": MarketListing.ReviewStatus.choices,
        },
    )


def data_quality(request):
    approved = [MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED]
    source_quality = []
    for row in (
        MarketListing.objects.values("source_type", "country")
        .annotate(
            total=Count("id"),
            usable=Count("id", filter=Q(review_status__in=approved, price_eur__isnull=False)),
            review=Count("id", filter=Q(review_status=MarketListing.ReviewStatus.NEEDS_REVIEW)),
        )
        .order_by("source_type", "country")
    ):
        source_quality.append(row)

    duplicate_variant_groups = (
        DeviceVariant.objects.values("product_model_id", "identity_key").annotate(c=Count("id")).filter(c__gt=1).count()
    )
    unmatched = MarketListing.objects.filter(product_model__isnull=True).count()
    missing_variant = MarketListing.objects.filter(product_model__isnull=False, variant__isnull=True).count()

    return render(
        request,
        "market/data_quality.html",
        base_context("data_quality")
        | {
            "source_quality": source_quality,
            "metrics": {
                "instagram_posts": InstagramPost.objects.count(),
                "ocr_pending": OCRResult.objects.filter(status=OCRResult.Status.PENDING).count(),
                "ocr_failed": OCRResult.objects.filter(status=OCRResult.Status.FAILED).count(),
                "unmatched": unmatched,
                "missing_variant": missing_variant,
                "models_without_variants": ProductModel.objects.filter(devicevariant__isnull=True).count(),
                "duplicate_variant_groups": duplicate_variant_groups,
                "supplier_prices": SupplierPrice.objects.count(),
                "snapshots": OpportunitySnapshot.objects.count(),
            },
        },
    )


def sources(request):
    source_rows = []
    for source in Source.objects.order_by("source_type", "name"):
        listings = MarketListing.objects.filter(source=source)
        supplier_prices = SupplierPrice.objects.filter(source=source)
        source_rows.append(
            {
                "source": source,
                "code": source_code(source.source_type),
                "total": listings.count() or supplier_prices.count(),
                "usable": listings.filter(
                    review_status__in=[MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED],
                    price_eur__isnull=False,
                ).count()
                or supplier_prices.filter(active=True).count(),
                "review": listings.filter(review_status=MarketListing.ReviewStatus.NEEDS_REVIEW).count(),
                "last_seen": listings.aggregate(value=Max("observed_at"))["value"]
                or supplier_prices.aggregate(value=Max("created_at"))["value"],
            }
        )

    return render(
        request,
        "market/sources.html",
        base_context("sources") | {"source_rows": source_rows},
    )
