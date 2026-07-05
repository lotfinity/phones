from collections import Counter
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Q

from market.models import MarketListing, ProductModel, SourceType
from market.services.currency import dzd_to_eur, try_to_eur
from market.services.listing_parser import (
    extract_model_text,
    is_accessory_title,
    is_dirty_model_name,
    listing_review_status,
    parse_condition,
    parse_sim_config,
    parse_storage_ram,
)
from market.services.matching import find_existing_model, find_existing_variant


def sahibinden_status(price, product_model, storage_gb):
    status = listing_review_status(price, product_model, storage_gb)
    if status != MarketListing.ReviewStatus.AUTO:
        return status
    if price < Decimal("5000") or price > Decimal("100000"):
        return MarketListing.ReviewStatus.NEEDS_REVIEW
    return status


class Command(BaseCommand):
    help = "Clean imported marketplace parsing links without scraping new data."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--prune-dirty-orphans",
            action="store_true",
            help="Delete dirty ProductModel rows that have no references from listings, variants, assets, suppliers, or snapshots.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        prune_dirty_orphans = options["prune_dirty_orphans"]
        counters = Counter()
        examples = []

        with transaction.atomic():
            listings = MarketListing.objects.select_related("product_model", "variant", "source").order_by("id")
            for listing in listings:
                before = {
                    "product_model_id": listing.product_model_id,
                    "variant_id": listing.variant_id,
                    "storage_gb": listing.storage_gb,
                    "condition": listing.condition,
                    "sim_config": listing.sim_config,
                    "price_eur": listing.price_eur,
                    "review_status": listing.review_status,
                    "parsed_confidence": listing.parsed_confidence,
                }

                text = f"{listing.title_raw} {listing.description_raw}"
                if is_accessory_title(listing.title_raw):
                    product_model = None
                    variant = None
                    storage_gb = None
                    sim_config = parse_sim_config(text)
                    counters["accessory_marked_review"] += 1
                else:
                    model_text = extract_model_text(listing.title_raw, listing.description_raw)
                    product_model = find_existing_model(model_text) if model_text else listing.product_model
                    storage_gb, _ram_gb = parse_storage_ram(text)
                    sim_config = parse_sim_config(text)
                    variant = (
                        find_existing_variant(product_model, storage_gb=storage_gb, sim_config=sim_config)
                        if product_model and storage_gb
                        else None
                    )

                if listing.source_type == SourceType.SAHIBINDEN:
                    review_status = sahibinden_status(listing.price_original, product_model, storage_gb)
                    price_eur = try_to_eur(listing.price_original) if listing.price_original else None
                elif listing.source_type == SourceType.OUEDKNISS:
                    review_status = listing_review_status(listing.price_original, product_model, storage_gb)
                    price_eur = dzd_to_eur(listing.price_original) if listing.price_original else None
                else:
                    review_status = listing_review_status(listing.price_original, product_model, storage_gb)
                    price_eur = listing.price_eur

                condition = parse_condition(text)
                if condition == "unknown":
                    condition = listing.condition

                listing.product_model = product_model
                listing.variant = variant
                listing.storage_gb = storage_gb
                listing.condition = condition
                listing.sim_config = sim_config
                listing.price_eur = price_eur
                listing.review_status = review_status
                listing.parsed_confidence = 0.9 if review_status == MarketListing.ReviewStatus.AUTO else 0.55

                changed_fields = [
                    field
                    for field, old_value in before.items()
                    if getattr(listing, field) != old_value
                ]
                if changed_fields:
                    counters["listings_changed"] += 1
                    for field in changed_fields:
                        counters[f"changed_{field}"] += 1
                    if len(examples) < 20:
                        examples.append(
                            {
                                "id": listing.id,
                                "title": listing.title_raw,
                                "model": product_model.canonical_name if product_model else None,
                                "variant": variant.canonical_label if variant else None,
                                "status": review_status,
                                "fields": ", ".join(changed_fields),
                            }
                        )
                    if not dry_run:
                        listing.save(
                            update_fields=[
                                "product_model",
                                "variant",
                                "storage_gb",
                                "condition",
                                "sim_config",
                                "price_eur",
                                "review_status",
                                "parsed_confidence",
                            ]
                        )

            deleted_dirty_orphans = 0
            if prune_dirty_orphans:
                candidates = (
                    ProductModel.objects.annotate(
                        listing_count=Count("marketlisting", distinct=True),
                        variant_count=Count("devicevariant", distinct=True),
                        supplier_count=Count("supplierprice", distinct=True),
                        asset_count=Count("productasset", distinct=True),
                        snapshot_count=Count("opportunitysnapshot", distinct=True),
                    )
                    .filter(
                        listing_count=0,
                        variant_count=0,
                        supplier_count=0,
                        asset_count=0,
                        snapshot_count=0,
                    )
                    .filter(Q(canonical_name__isnull=False))
                )
                delete_ids = [item.id for item in candidates if is_dirty_model_name(item.canonical_name)]
                deleted_dirty_orphans = len(delete_ids)
                if delete_ids and not dry_run:
                    ProductModel.objects.filter(id__in=delete_ids).delete()
            counters["dirty_orphans_deleted"] = deleted_dirty_orphans

            if dry_run:
                transaction.set_rollback(True)

        for key, value in counters.most_common():
            self.stdout.write(f"{key}: {value}")
        if examples:
            self.stdout.write("examples:")
            for example in examples:
                self.stdout.write(
                    f"  #{example['id']} {example['fields']} -> "
                    f"{example['model']} | {example['variant']} | {example['status']} | {example['title']}"
                )
