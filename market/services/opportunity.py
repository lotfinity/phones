from decimal import Decimal

from django.db import transaction
from django.db.models import Avg, Min

from market.models import Country, MarketListing, OpportunitySnapshot, ProductModel, SourceType, SupplierPrice
from market.services.matching import SUPPORTED_STORAGE_GB, get_or_create_variant


def confidence_for(algeria_count, sahibinden_count, supplier_count, exact_variant, sell_side_src="sahibinden"):
    score = min(algeria_count * 12, 36)
    score += min(sahibinden_count * 8, 32)
    score += min(supplier_count * 8, 12)
    score += 15 if exact_variant else 0
    if algeria_count and sahibinden_count:
        score += 5
    elif algeria_count and supplier_count and sell_side_src == "supplier":
        score += 3
    return min(score, 100)


def run_analysis():
    with transaction.atomic():
        OpportunitySnapshot.objects.all().delete()
        created = 0
        for product_model in ProductModel.objects.all():
            storage_values = list(
                product_model.devicevariant_set.filter(storage_gb__isnull=False)
                .filter(storage_gb__in=SUPPORTED_STORAGE_GB)
                .order_by("storage_gb")
                .values_list("storage_gb", flat=True)
                .distinct()
            )
            if not storage_values:
                storage_values = [None]

            for storage_gb in storage_values:
                listings = MarketListing.objects.filter(
                    country=Country.ALGERIA,
                    product_model=product_model,
                    price_eur__isnull=False,
                    review_status__in=[MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED],
                )
                sahibinden = MarketListing.objects.filter(
                    country=Country.TURKIYE,
                    source_type=SourceType.SAHIBINDEN,
                    product_model=product_model,
                    price_eur__isnull=False,
                    review_status__in=[MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED],
                )
                suppliers = SupplierPrice.objects.filter(
                    product_model=product_model,
                    active=True,
                    supplier_price_eur__isnull=False,
                )
                if storage_gb:
                    listings = listings.filter(variant__storage_gb=storage_gb)
                    sahibinden = sahibinden.filter(variant__storage_gb=storage_gb)
                    suppliers = suppliers.filter(variant__storage_gb=storage_gb)
                    variant = get_or_create_variant(product_model, storage_gb=storage_gb)
                else:
                    variant = None

                listing_stats = listings.aggregate(min_price=Min("price_eur"), avg_price=Avg("price_eur"))
                sahibinden_stats = sahibinden.aggregate(avg_price=Avg("price_eur"))
                supplier_stats = suppliers.aggregate(avg_price=Avg("supplier_price_eur"))
                algeria_min = listing_stats["min_price"]
                algeria_avg = listing_stats["avg_price"]
                sahibinden_avg = sahibinden_stats["avg_price"]
                supplier_eur = supplier_stats["avg_price"]
                listing_count = listings.count()
                sahibinden_count = sahibinden.count()
                supplier_count = suppliers.count()

                if not algeria_min or not sahibinden_avg:
                    recommendation = OpportunitySnapshot.Recommendation.INSUFFICIENT_DATA
                    margin = None
                    margin_percent = None
                else:
                    # PriceBridge direction: buy in Algeria, sell in Türkiye.
                    # Use Algeria minimum as the buy-side target and Sahibinden average as the sell-side baseline.
                    margin = Decimal(sahibinden_avg) - Decimal(algeria_min)
                    margin_percent = (margin / Decimal(algeria_min)) * Decimal("100")
                    if margin_percent > 15:
                        recommendation = OpportunitySnapshot.Recommendation.BUY
                    elif margin_percent > 5:
                        recommendation = OpportunitySnapshot.Recommendation.WATCH
                    else:
                        recommendation = OpportunitySnapshot.Recommendation.IGNORE

                confidence = confidence_for(listing_count, sahibinden_count, supplier_count, bool(storage_gb))
                explanation = (
                    f"{listing_count} Algeria listings, {sahibinden_count} Sahibinden rows, "
                    f"{supplier_count} supplier rows. Matched on product model and storage_gb={storage_gb}. "
                    "Margin is Türkiye average EUR minus Algeria minimum EUR. "
                    "Confidence is a simple count and storage-match heuristic."
                )
                OpportunitySnapshot.objects.create(
                    product_model=product_model,
                    variant=variant,
                    algeria_min_eur=algeria_min,
                    algeria_avg_eur=algeria_avg,
                    supplier_eur=supplier_eur,
                    sahibinden_avg_eur=sahibinden_avg,
                    gross_margin_vs_supplier_eur=None,
                    gross_margin_vs_sahibinden_eur=margin,
                    margin_percent=margin_percent,
                    confidence_score=confidence,
                    recommendation=recommendation,
                    explanation=explanation,
                )
                created += 1
        return created
