import statistics
from decimal import Decimal

from django.db import transaction
from django.db.models import Avg, Min, Q

from market.models import (
    ALLOW_MODEL_ONLY_OPPORTUNITIES,
    OPPORTUNITY_ELIGIBLE_MATCH_LEVELS,
    MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY,
    Country,
    ListingConditionAudit,
    MarketListing,
    OpportunitySnapshot,
    ProductModel,
    SourceType,
    SupplierPrice,
)
from market.services.matching import SUPPORTED_STORAGE_GB


def median_value(queryset, field):
    """Return the median of a numeric field from a queryset. Robust to outliers."""
    values = list(queryset.values_list(field, flat=True))
    if not values:
        return None
    return Decimal(str(statistics.median(values)))


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


def _listing_eligible_for_opportunity(listing: MarketListing) -> bool:
    """Check if a listing is eligible for automatic opportunity analysis.

    Opportunity analysis should use variant-quality matches. Phones are no longer
    exempt from match-level gates: model_only rows are too vague for arbitrage.
    """
    if not listing.product_model:
        return False

    level = listing.match_level or MarketListing.MatchLevel.UNMATCHED
    if level in (MarketListing.MatchLevel.UNMATCHED, MarketListing.MatchLevel.CONFLICT):
        return False
    if level == MarketListing.MatchLevel.MODEL_ONLY and not ALLOW_MODEL_ONLY_OPPORTUNITIES:
        return False
    if level not in OPPORTUNITY_ELIGIBLE_MATCH_LEVELS:
        return False
    if listing.match_confidence < MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY:
        return False
    return True


def _opportunity_listing_gate(prefix="") -> Q:
    """Return DB-level gate matching _listing_eligible_for_opportunity."""
    return Q(**{f"{prefix}product_model__isnull": False}) & Q(
        **{f"{prefix}match_level__in": list(OPPORTUNITY_ELIGIBLE_MATCH_LEVELS)}
    ) & Q(**{f"{prefix}match_confidence__gte": MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY})


def _eligible_review_gate(prefix="") -> Q:
    """Return DB-level review/price gate for MarketListing paths."""
    return Q(
        **{f"{prefix}review_status__in": [
            MarketListing.ReviewStatus.AUTO,
            MarketListing.ReviewStatus.APPROVED,
        ]},
        **{f"{prefix}price_eur__isnull": False},
    )


def _clean_condition_gate(prefix="") -> Q:
    """Gate Algeria listings to sealed_new or clean_used condition audits."""
    return Q(**{
        f"{prefix}condition_audit__condition_class__in": [
            ListingConditionAudit.ConditionClass.SEALED_NEW,
            ListingConditionAudit.ConditionClass.CLEAN_USED,
        ]
    })


def run_analysis(include_insufficient=False, include_cross_storage=False,
                 require_clean_condition=False):
    with transaction.atomic():
        OpportunitySnapshot.objects.all().delete()
        created = 0

        eligible_review = _eligible_review_gate()
        match_gate = _opportunity_listing_gate()
        base_filter = eligible_review & match_gate

        pm_eligible_review = _eligible_review_gate(prefix="marketlisting__")
        pm_match_gate = _opportunity_listing_gate(prefix="marketlisting__")
        pm_base_filter = pm_eligible_review & pm_match_gate

        variant_listing_filter = _eligible_review_gate(prefix="marketlisting__") & _opportunity_listing_gate(prefix="marketlisting__")

        product_models = (
            ProductModel.objects.filter(pm_base_filter)
            .distinct()
            .order_by("canonical_name")
        )
        for product_model in product_models:
            spec_values = list(
                MarketListing.objects.filter(
                    product_model=product_model,
                    storage_gb__isnull=False,
                    storage_gb__in=SUPPORTED_STORAGE_GB,
                )
                .filter(base_filter)
                .filter(Q(country=Country.ALGERIA) | Q(country=Country.TURKIYE, source_type=SourceType.SAHIBINDEN))
                .order_by("storage_gb")
                .values_list("storage_gb", flat=True)
                .distinct()
            )
            if not spec_values:
                continue

            for storage_gb in spec_values:
                algeria_q = MarketListing.objects.filter(
                    country=Country.ALGERIA,
                    product_model=product_model,
                ).filter(base_filter)
                if require_clean_condition:
                    algeria_q = algeria_q.filter(_clean_condition_gate())
                listings = algeria_q
                sahibinden = MarketListing.objects.filter(
                    country=Country.TURKIYE,
                    source_type=SourceType.SAHIBINDEN,
                    product_model=product_model,
                ).filter(base_filter)
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
                                filter=variant_listing_filter,
                            )
                        )
                        .order_by("id")
                        .first()
                    )
                else:
                    variant = None

                algeria_min = listings.aggregate(min_price=Min("price_eur"))["min_price"]
                algeria_median = median_value(listings, "price_eur")
                sahibinden_median = median_value(sahibinden, "price_eur")
                supplier_median = median_value(suppliers, "supplier_price_eur")
                listing_count = listings.count()
                sahibinden_count = sahibinden.count()
                supplier_count = suppliers.count()

                if not include_insufficient and (not algeria_min or not sahibinden_median):
                    continue
                if include_insufficient and not (listing_count or sahibinden_count or supplier_count):
                    continue

                if not algeria_min or not sahibinden_median:
                    recommendation = OpportunitySnapshot.Recommendation.INSUFFICIENT_DATA
                    margin = None
                    margin_percent = None
                else:
                    margin = Decimal(sahibinden_median) - Decimal(algeria_min)
                    margin_percent = (margin / Decimal(algeria_min)) * Decimal("100")
                    if margin_percent > 15:
                        recommendation = OpportunitySnapshot.Recommendation.BUY
                    elif margin_percent > 5:
                        recommendation = OpportunitySnapshot.Recommendation.WATCH
                    else:
                        recommendation = OpportunitySnapshot.Recommendation.IGNORE

                supplier_margin = None
                supplier_margin_pct = None
                if algeria_min and supplier_median:
                    supplier_margin = Decimal(supplier_median) - Decimal(algeria_min)
                    supplier_margin_pct = (supplier_margin / Decimal(algeria_min)) * Decimal("100")

                confidence = confidence_for(listing_count, sahibinden_count, supplier_count, bool(storage_gb))
                explanation = (
                    f"{listing_count} Algeria listings, {sahibinden_count} Sahibinden rows, "
                    f"{supplier_count} supplier rows. Matched on product model, storage_gb={storage_gb}. "
                    "Margin is Türkiye median EUR minus Algeria minimum EUR. "
                    "Confidence is a simple count and storage-match heuristic."
                )
                OpportunitySnapshot.objects.create(
                    product_model=product_model,
                    variant=variant,
                    storage_gb=storage_gb,
                    sim_config="",
                    algeria_min_eur=algeria_min,
                    algeria_avg_eur=algeria_median,
                    supplier_eur=supplier_median,
                    sahibinden_avg_eur=sahibinden_median,
                    gross_margin_vs_supplier_eur=supplier_margin,
                    gross_margin_vs_sahibinden_eur=margin,
                    supplier_margin_percent=supplier_margin_pct,
                    margin_percent=margin_percent,
                    confidence_score=confidence,
                    recommendation=recommendation,
                    explanation=explanation,
                )
                created += 1

        if not include_cross_storage:
            return created

        algeria_models = set(
            MarketListing.objects.filter(country=Country.ALGERIA)
            .filter(base_filter)
            .values_list("product_model_id", flat=True)
        )
        turkiye_models = set(
            MarketListing.objects.filter(
                country=Country.TURKIYE,
                source_type=SourceType.SAHIBINDEN,
            )
            .filter(base_filter)
            .values_list("product_model_id", flat=True)
        )
        already_done = set(
            OpportunitySnapshot.objects.values_list("product_model_id", flat=True)
        )
        cross_storage_candidates = (algeria_models & turkiye_models) - already_done

        for pm_id in cross_storage_candidates:
            if not pm_id:
                continue
            product_model = ProductModel.objects.get(id=pm_id)
            algeria_q = MarketListing.objects.filter(
                country=Country.ALGERIA,
                product_model=product_model,
            ).filter(base_filter)
            if require_clean_condition:
                algeria_q = algeria_q.filter(_clean_condition_gate())
            listings = algeria_q
            sahibinden = MarketListing.objects.filter(
                country=Country.TURKIYE,
                source_type=SourceType.SAHIBINDEN,
                product_model=product_model,
            ).filter(base_filter)
            suppliers = SupplierPrice.objects.filter(
                product_model=product_model,
                active=True,
                supplier_price_eur__isnull=False,
            )

            algeria_min = listings.aggregate(min_price=Min("price_eur"))["min_price"]
            algeria_median = median_value(listings, "price_eur")
            sahibinden_median = median_value(sahibinden, "price_eur")
            supplier_median = median_value(suppliers, "supplier_price_eur")
            listing_count = listings.count()
            sahibinden_count = sahibinden.count()
            supplier_count = suppliers.count()

            if not include_insufficient and (not algeria_min or not sahibinden_median):
                continue

            if not algeria_min or not sahibinden_median:
                recommendation = OpportunitySnapshot.Recommendation.INSUFFICIENT_DATA
                margin = None
                margin_percent = None
            else:
                margin = Decimal(sahibinden_median) - Decimal(algeria_min)
                margin_percent = (margin / Decimal(algeria_min)) * Decimal("100")
                if margin_percent > 15:
                    recommendation = OpportunitySnapshot.Recommendation.BUY
                elif margin_percent > 5:
                    recommendation = OpportunitySnapshot.Recommendation.WATCH
                else:
                    recommendation = OpportunitySnapshot.Recommendation.IGNORE

            supplier_margin = None
            supplier_margin_pct = None
            if algeria_min and supplier_median:
                supplier_margin = Decimal(supplier_median) - Decimal(algeria_min)
                supplier_margin_pct = (supplier_margin / Decimal(algeria_min)) * Decimal("100")

            confidence = confidence_for(listing_count, sahibinden_count, supplier_count, False)
            confidence = int(confidence * 0.85)

            a_storages = sorted(s for s in listings.values_list("storage_gb", flat=True).distinct() if s is not None)
            t_storages = sorted(s for s in sahibinden.values_list("storage_gb", flat=True).distinct() if s is not None)
            explanation = (
                f"CROSS-STORAGE comparison. Algeria storages: {a_storages}, Turkiye storages: {t_storages}. "
                f"{listing_count} Algeria listings, {sahibinden_count} Sahibinden rows, "
                f"{supplier_count} supplier rows. "
                "Margin is Türkiye median EUR minus Algeria minimum EUR."
            )
            OpportunitySnapshot.objects.create(
                product_model=product_model,
                variant=None,
                storage_gb=None,
                sim_config="",
                algeria_min_eur=algeria_min,
                algeria_avg_eur=algeria_median,
                supplier_eur=supplier_median,
                sahibinden_avg_eur=sahibinden_median,
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
