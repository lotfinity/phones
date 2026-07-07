"""Test spec extraction from listing text.

Usage:
    python manage.py parse_listing_text "Lenovo Legion 5 RTX 4060 16GB 512GB SSD 165Hz"
    python manage.py parse_listing_text --type laptop "ASUS ROG Strix i7-13650HX RTX 4060 16GB 1TB SSD"
    python manage.py parse_listing_text "iPhone 15 Pro Max 256GB 2sim"
"""

from django.core.management.base import BaseCommand

from market.services.spec_extraction import (
    ParsedListing,
    detect_product_type,
    extract_specs_from_listing,
    extract_specs_from_text,
)


class Command(BaseCommand):
    help = "Test spec extraction from listing text."

    def add_arguments(self, parser):
        parser.add_argument("text", help="Listing title or text to parse")
        parser.add_argument(
            "--type",
            dest="product_type",
            default=None,
            help="Force product type (laptop, phone, tablet, console, vr_headset, camera)",
        )
        parser.add_argument(
            "--description",
            default="",
            help="Additional description text",
        )

    def handle(self, *args, **options):
        text = options["text"]
        product_type = options["product_type"]
        description = options["description"]

        # Detect product type if not forced
        if not product_type:
            detected = detect_product_type(text, description)
            self.stdout.write(f"Detected product type: {detected or 'unknown'}")
            product_type = detected
        else:
            self.stdout.write(f"Forced product type: {product_type}")

        # Extract specs
        parsed = extract_specs_from_listing(
            product_type,
            text,
            description=description,
        )

        # Display results
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Product type: {parsed.product_type or 'unknown'}"))
        self.stdout.write(f"Brand: {parsed.brand or 'unknown'}")
        self.stdout.write(f"Model: {parsed.model_text or 'unknown'}")
        self.stdout.write(f"Confidence: {parsed.confidence:.3f}")
        self.stdout.write("")

        if parsed.specs:
            self.stdout.write(self.style.WARNING("Specs:"))
            for key, value in sorted(parsed.specs.items()):
                if value is not None and value != "" and value is not False:
                    self.stdout.write(f"  {key}: {value}")
        else:
            self.stdout.write("No specs extracted.")

        self.stdout.write("")
        if parsed.reasons:
            self.stdout.write("Reasons:")
            for reason in parsed.reasons:
                self.stdout.write(f"  - {reason}")
