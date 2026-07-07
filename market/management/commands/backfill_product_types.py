"""Backfill product_type on existing ProductModel rows.

Idempotent: only sets product_type when it's NULL and the model is obviously
a phone or laptop based on its canonical_name or category.

Usage:
    python manage.py backfill_product_types
"""

from django.core.management.base import BaseCommand

from market.models import Category, ProductModel, ProductType
from market.services.catalog import get_or_create_product_type
from market.services.spec_extraction import detect_product_type


class Command(BaseCommand):
    help = "Backfill product_type on ProductModel rows that don't have one yet."

    def handle(self, *args, **options):
        phone_type = get_or_create_product_type("phone", name="Phone")
        laptop_type = get_or_create_product_type("laptop", name="Laptop")

        # Count before
        unset_before = ProductModel.objects.filter(product_type__isnull=True).count()

        updated = 0
        skipped = 0

        for pm in ProductModel.objects.filter(product_type__isnull=True).select_related("category", "brand"):
            # Try to detect from category first
            if pm.category:
                cat_slug = pm.category.slug.lower()
                if cat_slug in ("laptops", "laptop", "ordinateurs"):
                    pm.product_type = laptop_type
                    pm.save(update_fields=["product_type"])
                    updated += 1
                    continue
                if cat_slug in ("phones", "phone", "smartphones", "mobiles"):
                    pm.product_type = phone_type
                    pm.save(update_fields=["product_type"])
                    updated += 1
                    continue

            # Try to detect from model name
            detected = detect_product_type(pm.canonical_name, "")
            if detected == "laptop":
                pm.product_type = laptop_type
                pm.save(update_fields=["product_type"])
                updated += 1
            elif detected == "phone":
                pm.product_type = phone_type
                pm.save(update_fields=["product_type"])
                updated += 1
            else:
                skipped += 1

        unset_after = ProductModel.objects.filter(product_type__isnull=True).count()

        self.stdout.write(
            self.style.SUCCESS(
                f"Backfill complete. Updated: {updated}, Skipped: {skipped}, "
                f"Unset before: {unset_before}, Unset after: {unset_after}"
            )
        )
