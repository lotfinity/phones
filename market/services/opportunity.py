from decimal import Decimal

from django.db import transaction
from django.db.models import Avg, Min, Q

from market.models import Country, MarketListing, OpportunitySnapshot, ProductModel, SourceType, SupplierPrice
from market.services.matching import SUPPORTED_STORAGE_GB


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


def run_analysis(include_insufficient=False):
    with transaction.atomic():
        OpportunitySnapshot.objects.all().delete()
        created = 0
        product_models = (
            ProductModel.objects.filter(
                marketlisting__review_status__in=[
                    MarketListing.ReviewStatus.AUTO,
                    MarketListing.ReviewStatus.APPROVED,
                ],
                marketlisting__price_eur__isnull=False,
            )
            .distinct()
            .order_by("canonical_name")
        )
        for product_model in product_models:
            spec_values = list(
                MarketListing.objects.filter(
                    product_model=product_model,
                    price_eur__isnull=False,
                    review_status__in=[
                        MarketListing.ReviewStatus.AUTO,
                        MarketListing.ReviewStatus.APPROVED,
                    ],
                    storage_gb__isnull=False,
                    storage_gb__in=SUPPORTED_STORAGE_GB,
                )
                .filter(Q(country=Country.ALGERIA) | Q(country=Country.TURKIYE, source_type=SourceType.SAHIBINDEN))
                .order_by("storage_gb")
                .values_list("storage_gb", flat=True)
                .distinct()
            )
            if not spec_values:
                continue

            for storage_gb in spec_values:
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
                    listings = listings.filter(storage_gb=storage_gb)
                    sahibinden = sahibinden.filter(storage_gb=storage_gb)
                    suppliers = suppliers.filter(storage_gb=storage_gb)
                    variant = (
                        product_model.devicevariant_set.filter(storage_gb=storage_gb)
                        .annotate(
                            listing_count=Avg(
                                "marketlisting__price_eur",
                                filter=Q(
                                    marketlisting__review_status__in=[
                                        MarketListing.ReviewStatus.AUTO,
                                        MarketListing.ReviewStatus.APPROVED,
                                    ],
                                    marketlisting__price_eur__isnull=False,
                                ),
                            )
                        )
                        .order_by("id")
                        .first()
                    )
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

                if not include_insufficient and (not algeria_min or not sahibinden_avg):
                    continue
                if include_insufficient and not (listing_count or sahibinden_count or supplier_count):
                    continue

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

                # Supplier margin: Algeria min vs supplier average
                supplier_margin = None
                supplier_margin_pct = None
                if algeria_min and supplier_eur:
                    supplier_margin = Decimal(supplier_eur) - Decimal(algeria_min)
                    supplier_margin_pct = (supplier_margin / Decimal(algeria_min)) * Decimal("100")

                confidence = confidence_for(listing_count, sahibinden_count, supplier_count, bool(storage_gb))
                explanation = (
                    f"{listing_count} Algeria listings, {sahibinden_count} Sahibinden rows, "
                    f"{supplier_count} supplier rows. Matched on product model, storage_gb={storage_gb}. "
                    "Margin is Türkiye average EUR minus Algeria minimum EUR. "
                    "Confidence is a simple count and storage-match heuristic."
                )
                OpportunitySnapshot.objects.create(
                    product_model=product_model,
                    variant=variant,
                    storage_gb=storage_gb,
                    sim_config="",
                    algeria_min_eur=algeria_min,
                    algeria_avg_eur=algeria_avg,
                    supplier_eur=supplier_eur,
                    sahibinden_avg_eur=sahibinden_avg,
                    gross_margin_vs_supplier_eur=supplier_margin,
                    gross_margin_vs_sahibinden_eur=margin,
                    supplier_margin_percent=supplier_margin_pct,
                    margin_percent=margin_percent,
                    confidence_score=confidence,
                    recommendation=recommendation,
                    explanation=explanation,
                )
                created += 1

        # Second pass: models in both countries with no matching storage
        algeria_models = set(
            MarketListing.objects.filter(
                country=Country.ALGERIA,
                review_status__in=[MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED],
                price_eur__isnull=False,
            ).values_list("product_model_id", flat=True)
        )
        turkiye_models = set(
            MarketListing.objects.filter(
                country=Country.TURKIYE,
                source_type=SourceType.SAHIBINDEN,
                review_status__in=[MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED],
                price_eur__isnull=False,
            ).values_list("product_model_id", flat=True)
        )
        already_done = set(
            OpportunitySnapshot.objects.values_list("product_model_id", flat=True)
        )
        cross_storage_candidates = (algeria_models & turkiye_models) - already_done

        for pm_id in cross_storage_candidates:
            product_model = ProductModel.objects.get(id=pm_id)
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

            if not include_insufficient and (not algeria_min or not sahibinden_avg):
                continue

            if not algeria_min or not sahibinden_avg:
                recommendation = OpportunitySnapshot.Recommendation.INSUFFICIENT_DATA
                margin = None
                margin_percent = None
            else:
                margin = Decimal(sahibinden_avg) - Decimal(algeria_min)
                margin_percent = (margin / Decimal(algeria_min)) * Decimal("100")
                if margin_percent > 15:
                    recommendation = OpportunitySnapshot.Recommendation.BUY
                elif margin_percent > 5:
                    recommendation = OpportunitySnapshot.Recommendation.WATCH
                else:
                    recommendation = OpportunitySnapshot.Recommendation.IGNORE

            supplier_margin = None
            supplier_margin_pct = None
            if algeria_min and supplier_eur:
                supplier_margin = Decimal(supplier_eur) - Decimal(algeria_min)
                supplier_margin_pct = (supplier_margin / Decimal(algeria_min)) * Decimal("100")

            confidence = confidence_for(listing_count, sahibinden_count, supplier_count, False)
            confidence = int(confidence * 0.85)  # lower confidence for cross-storage

            a_storages = sorted(s for s in listings.values_list("storage_gb", flat=True).distinct() if s is not None)
            t_storages = sorted(s for s in sahibinden.values_list("storage_gb", flat=True).distinct() if s is not None)
            explanation = (
                f"CROSS-STORAGE comparison. Algeria storages: {a_storages}, Turkiye storages: {t_storages}. "
                f"{listing_count} Algeria listings, {sahibinden_count} Sahibinden rows, "
                f"{supplier_count} supplier rows. "
                "Margin is Türkiye average EUR minus Algeria minimum EUR."
            )
            OpportunitySnapshot.objects.create(
                product_model=product_model,
                variant=None,
                storage_gb=None,
                sim_config="",
                algeria_min_eur=algeria_min,
                algeria_avg_eur=algeria_avg,
                supplier_eur=supplier_eur,
                sahibinden_avg_eur=sahibinden_avg,
                gross_margin_vs_supplier_eur=supplier_margin,
                gross_margin_vs_sahibinden_eur=margin,
                supplier_margin_percent=supplier_margin_pct,
                margin_percent=margin_percent,
                confidence_score=confidence,
                recommendation=recommendation,
                explanation=explanation,
            )
            created += 1

        return created
