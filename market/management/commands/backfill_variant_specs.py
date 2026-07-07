from django.core.management.base import BaseCommand, CommandError

from market.models import DeviceVariant, ProductVariantSpecValue
from market.services.catalog import upsert_variant_specs_from_dict
from market.services.spec_extraction import extract_specs_from_text, has_useful_specs

# Identity spec keys per product type for --require-identity-spec.
IDENTITY_SPECS_BY_TYPE = {
    "phone": {"storage_gb", "sim_config"},
    "laptop": {"cpu_model", "gpu_model", "ram_gb", "ssd_gb", "screen_inches", "refresh_hz"},
}


class Command(BaseCommand):
    help = "Backfill ProductVariantSpecValue rows from existing variant fields/labels."

    def add_arguments(self, parser):
        parser.add_argument(
            "--product-type",
            type=str,
            default="",
            help="Optional product type slug filter, e.g. phone or laptop.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=1000,
            help="Maximum variants to process (default 1000).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print changes without writing spec rows.",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Delete existing variant spec rows before backfilling each variant.",
        )
        parser.add_argument(
            "--min-spec-count",
            type=int,
            default=1,
            help="Minimum number of useful spec values required to write (default 1).",
        )
        parser.add_argument(
            "--require-identity-spec",
            action="store_true",
            default=False,
            help="Require at least one identity spec (storage_gb/sim_config for phones, "
                 "cpu/gpu/ram/ssd/screen/refresh for laptops) before writing.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1:
            raise CommandError("--limit must be >= 1")
        limit = min(limit, 10000)

        product_type_slug = options["product_type"].strip().lower()
        dry_run = options["dry_run"]
        replace = options["replace"]
        min_spec_count = max(0, options["min_spec_count"])
        require_identity = options["require_identity_spec"]

        qs = DeviceVariant.objects.select_related(
            "product_model", "product_model__product_type"
        ).order_by("id")
        if product_type_slug:
            qs = qs.filter(product_model__product_type__slug=product_type_slug)

        variants = list(qs[:limit])
        processed = 0
        would_write = 0
        skipped = 0

        for variant in variants:
            product_model = variant.product_model
            product_type = product_model.product_type if product_model else None
            if not product_type:
                skipped += 1
                continue

            specs = self._specs_for_variant(variant, product_type.slug)
            if not specs or not has_useful_specs(specs, product_type.slug):
                skipped += 1
                continue

            # Count actual useful spec keys after cleaning
            useful_count = len(specs)
            if useful_count < min_spec_count:
                skipped += 1
                continue

            if require_identity:
                identity_keys = IDENTITY_SPECS_BY_TYPE.get(product_type.slug, set())
                if not identity_keys.intersection(specs.keys()):
                    skipped += 1
                    continue

            processed += 1
            if dry_run:
                would_write += len(specs)
                self.stdout.write(
                    f"  #{variant.pk} WOULD WRITE {product_type.slug} ({len(specs)} specs): {specs}"
                )
                continue

            if replace:
                ProductVariantSpecValue.objects.filter(variant=variant).delete()
            saved = upsert_variant_specs_from_dict(variant, specs)
            would_write += len(saved)
            self.stdout.write(
                f"  #{variant.pk} wrote {len(saved)} spec values: {variant.canonical_label}"
            )

        verb = "Would write" if dry_run else "Wrote"
        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Processed {processed}, skipped {skipped}. {verb} {would_write} spec rows."
        ))

    def _specs_for_variant(self, variant: DeviceVariant, product_type_slug: str) -> dict:
        if product_type_slug == "phone":
            specs = {}
            if variant.storage_gb:
                specs["storage_gb"] = variant.storage_gb
            if variant.sim_config:
                specs["sim_config"] = variant.sim_config
            if variant.region:
                specs["region"] = variant.region
            if variant.color:
                specs["color"] = variant.color
            return specs

        text = " ".join(
            part for part in [
                variant.product_model.canonical_name if variant.product_model else "",
                variant.canonical_label,
                " ".join(variant.aliases or []),
            ] if part
        )
        return extract_specs_from_text(product_type_slug, text) if text else {}
