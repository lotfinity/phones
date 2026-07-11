"""Repair local filesystem image paths in clean listing image_url fields.

When listings were imported via CDP, some image_url values were stored as
local filesystem paths instead of HTTP URLs. This command identifies those
listings and clears the invalid local paths so the proxy falls back to the
raw_listing image or gracefully shows a brand logo fallback.

Usage:
    python manage.py repair_clean_listing_images --category phone --dry-run
    python manage.py repair_clean_listing_images --category phone --listing-id 316
    python manage.py repair_clean_listing_images --category phone --listing-id 316 --dry-run
"""

import os

from django.core.management.base import BaseCommand
from django.db import models

from market.models import ConsoleListing, LaptopListing, PhoneListing


CATEGORY_MODELS = {
    "phone": PhoneListing,
    "laptop": LaptopListing,
    "console": ConsoleListing,
}


class Command(BaseCommand):
    help = "Repair local filesystem paths in clean listing image_url fields."

    def add_arguments(self, parser):
        parser.add_argument(
            "--category",
            choices=list(CATEGORY_MODELS.keys()),
            default="phone",
            help="Listing category to repair (default: phone)",
        )
        parser.add_argument(
            "--listing-id",
            type=int,
            default=None,
            help="Repair a specific listing by ID (optional)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without making changes",
        )

    def handle(self, *args, **options):
        category = options["category"]
        listing_id = options["listing_id"]
        dry_run = options["dry_run"]

        model = CATEGORY_MODELS[category]

        # Find listings with local filesystem paths in image_url
        qs = model.objects.exclude(
            models.Q(image_url="") | models.Q(image_url__isnull=True)
        )

        if listing_id:
            qs = qs.filter(pk=listing_id)

        # A local path is one that starts with "/" or "media/" or contains
        # filesystem path separators but not http(s)://
        local_path_qs = qs.filter(
            models.Q(image_url__startswith="/")
            | models.Q(image_url__startswith="media/")
        )

        count = local_path_qs.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS(
                f"No {category} listings with local filesystem paths found."
            ))
            return

        self.stdout.write(self.style.WARNING(
            f"Found {count} {category} listing(s) with local filesystem paths in image_url."
        ))

        repaired = 0
        for listing in local_path_qs.iterator():
            old_url = listing.image_url
            raw_image = ""
            if listing.raw_listing_id:
                raw_image = listing.raw_listing.image_url if listing.raw_listing else ""

            action = "clear" if not raw_image else "replace_with_raw"

            self.stdout.write(
                f"  [{listing.pk}] {listing.title[:60]!r} "
                f"image_url={old_url!r} "
                f"raw_image_url={raw_image!r} "
                f"action={action}"
            )

            if not dry_run:
                if raw_image:
                    listing.image_url = raw_image
                    listing.save(update_fields=["image_url", "updated_at"])
                else:
                    listing.image_url = ""
                    listing.save(update_fields=["image_url", "updated_at"])
                repaired += 1

        verb = "Would repair" if dry_run else "Repaired"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {repaired} of {count} {category} listing(s)."
        ))
