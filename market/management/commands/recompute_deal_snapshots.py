import json
import statistics
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from market.models import (
    Country,
    DealSnapshot,
    MarketListing,
    MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY,
    OPPORTUNITY_ELIGIBLE_MATCH_LEVELS,
    SourceType,
    SupplierPrice,
)
from market.services import currency as fx


def _source_code(value):
    mapping = {
        "instagram": "IG",
        "ouedkniss": "OK",
        "sahibinden": "SH",
        "supplier_list": "SL",
        "manual": "MN",
    }
    return mapping.get(str(value), str(value)[:4].upper())


def _listing_image_url(listing):
    path = (getattr(listing, "image_path", "") or "").strip()
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if hasattr(listing, "image_file") and listing.image_file:
        return listing.image_file.url
    media_root = Path(settings.MEDIA_ROOT).resolve()
    try:
        rel_path = Path(path).resolve().relative_to(media_root)
        return f"{settings.MEDIA_URL}{rel_path.as_posix()}"
    except (OSError, ValueError):
        if path.startswith(str(settings.MEDIA_URL)):
            return path
        return ""


def _eligible_listing_filter():
    return {
        "review_status__in": [MarketListing.ReviewStatus.AUTO, MarketListing.ReviewStatus.APPROVED],
        "price_eur__isnull": False,
        "product_model__isnull": False,
        "variant__isnull": False,
        "match_level__in": list(OPPORTUNITY_ELIGIBLE_MATCH_LEVELS),
        "match_confidence__gte": MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY,
    }


def compute_deal_snapshots():
    """Compute all deals and return a list of DealSnapshot instances (not yet saved).

    Deal snapshots power the public/mobile deals UI, so they must use the same
    match-quality gate as OpportunitySnapshot. Do not include model_only,
    unmatched, conflict, or storage-less rows in the cached buyer-facing deck.
    """
    eligible_filter = _eligible_listing_filter()
    algeria_listings = (
        MarketListing.objects.select_related("source", "product_model", "product_model__brand", "variant")
        .filter(
            country=Country.ALGERIA,
            storage_gb__isnull=False,
            **eligible_filter,
        )
        .order_by("product_model__brand__name", "product_model__canonical_name", "storage_gb", "price_eur")
    )

    snapshots = []
    for listing in algeria_listings:
        pm = listing.product_model
        brand = pm.brand.name if pm.brand else "Unknown"
        storage = listing.storage_gb

        sah_query = MarketListing.objects.filter(
            source_type=SourceType.SAHIBINDEN,
            product_model=pm,
            storage_gb=storage,
            **eligible_filter,
        )

        sah_prices_eur = list(sah_query.values_list("price_eur", flat=True))
        sah_prices_try = list(sah_query.values_list("price_original", flat=True))
        sah_count = len(sah_prices_eur)

        if not sah_count:
            continue

        sah_median_eur = statistics.median(sah_prices_eur)
        sah_median_try = statistics.median(sah_prices_try)
        sah_min_try = min(sah_prices_try)
        sah_max_try = max(sah_prices_try)
        sah_urls = [u for u in sah_query.values_list("listing_url", flat=True)[:10] if u]

        margin_eur = (sah_median_eur - listing.price_eur) if listing.price_eur else None
        margin_pct = (margin_eur / listing.price_eur * 100) if (margin_eur is not None and listing.price_eur) else None

        supplier = SupplierPrice.objects.filter(
            product_model=pm, active=True, supplier_price_usd__isnull=False,
        )
        if storage:
            supplier = supplier.filter(storage_gb=storage)
        supplier_first = supplier.first()

        price_try = price_usd = price_dzd = None
        if listing.price_eur is not None:
            try:
                price_try = float(fx.eur_to_try(listing.price_eur))
            except Exception:
                pass
            try:
                price_usd = float(fx.eur_to_usd(listing.price_eur))
            except Exception:
                pass
            try:
                price_dzd = float(fx.eur_to_dzd(listing.price_eur))
            except Exception:
                pass

        sah_median_eur_conv = sah_median_usd = sah_median_dzd = None
        if sah_median_try is not None:
            try:
                sah_median_eur_conv = float(fx.try_to_eur(sah_median_try))
                sah_median_usd = float(fx.eur_to_usd(sah_median_eur_conv))
                sah_median_dzd = float(fx.eur_to_dzd(sah_median_eur_conv))
            except Exception:
                pass

        supplier_usd = supplier_eur = supplier_try = supplier_dzd = None
        if supplier_first:
            if supplier_first.supplier_price_usd is not None:
                supplier_usd = float(supplier_first.supplier_price_usd)
            if supplier_first.supplier_price_eur is not None:
                supplier_eur = float(supplier_first.supplier_price_eur)
                try:
                    supplier_try = float(fx.eur_to_try(supplier_first.supplier_price_eur))
                    supplier_dzd = float(fx.eur_to_dzd(supplier_first.supplier_price_eur))
                except Exception:
                    pass
            elif supplier_first.supplier_price_usd is not None:
                try:
                    sup_eur = float(fx.usd_to_eur(supplier_first.supplier_price_usd))
                    supplier_try = float(fx.eur_to_try(sup_eur))
                    supplier_dzd = float(fx.eur_to_dzd(sup_eur))
                except Exception:
                    pass

        snapshots.append(DealSnapshot(
            listing=listing,
            brand_name=brand,
            model_name=pm.canonical_name,
            storage_gb=storage,
            title=listing.title_raw or f"{pm.canonical_name} {storage or ''}GB".strip(),
            price_original=listing.price_original,
            currency_original=listing.currency_original or "",
            price_eur=listing.price_eur,
            price_try=price_try,
            price_usd=price_usd,
            price_dzd=price_dzd,
            condition=listing.get_condition_display() if hasattr(listing, "get_condition_display") else "",
            source_code=_source_code(listing.source_type),
            source_name=listing.source.name if listing.source else "",
            image_url=_listing_image_url(listing),
            listing_url=listing.listing_url or "",
            observed_at=listing.observed_at,
            sah_median=sah_median_try,
            sah_median_eur=sah_median_eur_conv,
            sah_median_usd=sah_median_usd,
            sah_median_dzd=sah_median_dzd,
            sah_min=sah_min_try,
            sah_max=sah_max_try,
            sah_count=sah_count,
            sah_urls=sah_urls,
            supplier_usd=supplier_usd,
            supplier_eur=supplier_eur,
            supplier_try=supplier_try,
            supplier_dzd=supplier_dzd,
            margin_eur=margin_eur,
            margin_pct=margin_pct,
        ))

    return snapshots


class Command(BaseCommand):
    help = "Recompute deal snapshots (cached deals for fast page loads)."

    def handle(self, *args, **options):
        self.stdout.write("Computing deal snapshots...")
        snapshots = compute_deal_snapshots()

        with transaction.atomic():
            DealSnapshot.objects.all().delete()
            DealSnapshot.objects.bulk_create(snapshots, batch_size=500)

        self.stdout.write(self.style.SUCCESS(f"Created {len(snapshots)} deal snapshots."))
