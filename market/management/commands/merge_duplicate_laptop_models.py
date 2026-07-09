from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from market.models import (
    LaptopListing,
    LaptopModel,
    LaptopVariant,
    ParsedListingCandidate,
)
from market.services.laptop_model_canonicalization import (
    laptop_model_merge_key,
    normalize_laptop_model_name,
)


class Command(BaseCommand):
    help = "Merge duplicate LaptopModel rows caused by casing, Turkish-I, brand prefixes, and spec fragments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually merge rows. Default is dry-run only.",
        )
        parser.add_argument(
            "--brand",
            help="Limit to one brand name, e.g. Apple, Lenovo, ASUS.",
        )
        parser.add_argument("--limit", type=int, default=0, help="Limit number of duplicate groups processed.")

    def handle(self, *args, **options):
        apply = options["apply"]
        brand_filter = options.get("brand")
        limit = options["limit"]

        qs = LaptopModel.objects.select_related("brand").annotate(listing_count=Count("laptoplisting"))
        if brand_filter:
            qs = qs.filter(brand__name__iexact=brand_filter)

        groups = defaultdict(list)
        for model in qs:
            brand_name = model.brand.name if model.brand else ""
            key = laptop_model_merge_key(brand_name, model.canonical_name)
            groups[key].append(model)

        duplicate_groups = [models for models in groups.values() if len(models) > 1]
        duplicate_groups.sort(
            key=lambda models: sum(model.listing_count for model in models),
            reverse=True,
        )
        if limit:
            duplicate_groups = duplicate_groups[:limit]

        total_models_removed = 0
        total_listings_moved = 0
        total_variants_moved = 0
        total_variant_conflicts = 0
        total_candidates_moved = 0

        for models in duplicate_groups:
            target = self._choose_target(models)
            sources = [model for model in models if model.pk != target.pk]
            pretty_name = normalize_laptop_model_name(
                target.brand.name if target.brand else "",
                target.canonical_name,
            )
            listing_total = sum(model.listing_count for model in models)

            self.stdout.write("")
            self.stdout.write(
                f"GROUP {target.brand.name if target.brand else ''} / {pretty_name}: "
                f"{len(models)} model rows, {listing_total} listings"
            )
            self.stdout.write(f"  keep {target.pk}: {target.canonical_name} ({target.listing_count} listings)")
            for source in sources:
                self.stdout.write(f"  merge {source.pk}: {source.canonical_name} ({source.listing_count} listings)")

            if not apply:
                continue

            with transaction.atomic():
                moved = self._merge_group(target, sources, pretty_name)
                total_models_removed += moved["models_removed"]
                total_listings_moved += moved["listings_moved"]
                total_variants_moved += moved["variants_moved"]
                total_variant_conflicts += moved["variant_conflicts"]
                total_candidates_moved += moved["candidates_moved"]

        if not apply:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to merge."))
            self.stdout.write(self.style.WARNING(f"Duplicate groups found: {len(duplicate_groups)}"))
            return

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Laptop model merge complete."))
        self.stdout.write(f"models removed: {total_models_removed}")
        self.stdout.write(f"listings moved: {total_listings_moved}")
        self.stdout.write(f"variants moved: {total_variants_moved}")
        self.stdout.write(f"variant conflicts merged: {total_variant_conflicts}")
        self.stdout.write(f"candidates moved: {total_candidates_moved}")

    def _choose_target(self, models):
        """Choose the canonical survivor: most listings, then shortest name, then lowest id."""

        def score(model):
            name = model.canonical_name or ""
            brand_name = model.brand.name if model.brand else ""
            pretty = normalize_laptop_model_name(brand_name, name)
            pretty_score = 1 if name == pretty else 0
            not_all_caps = 1 if name != name.upper() else 0
            no_turkish_i = 1 if "İ" not in name else 0
            return (model.listing_count, pretty_score, not_all_caps, no_turkish_i, -model.pk)

        return sorted(models, key=score, reverse=True)[0]

    def _merge_group(self, target, sources, pretty_name):
        stats = {
            "models_removed": 0,
            "listings_moved": 0,
            "variants_moved": 0,
            "variant_conflicts": 0,
            "candidates_moved": 0,
        }

        aliases = set(target.aliases or [])
        aliases.add(target.canonical_name)
        aliases.add(pretty_name)

        for source in sources:
            aliases.add(source.canonical_name)
            aliases.update(source.aliases or [])

            for source_variant in LaptopVariant.objects.filter(laptop_model=source).iterator():
                target_variant = LaptopVariant.objects.filter(
                    laptop_model=target,
                    identity_key=source_variant.identity_key,
                ).first()
                if target_variant:
                    # Conflict: same identity on both sides — move listings and candidates to target variant
                    LaptopListing.objects.filter(variant=source_variant).update(variant=target_variant)
                    ParsedListingCandidate.objects.filter(matched_laptop_variant=source_variant).update(
                        matched_laptop_variant=target_variant,
                    )
                    source_variant.delete()
                    stats["variant_conflicts"] += 1
                else:
                    source_variant.laptop_model = target
                    source_variant.save(update_fields=["laptop_model"])
                    stats["variants_moved"] += 1

            stats["listings_moved"] += LaptopListing.objects.filter(laptop_model=source).update(laptop_model=target)
            stats["candidates_moved"] += ParsedListingCandidate.objects.filter(matched_laptop_model=source).update(
                matched_laptop_model=target,
            )
            source.delete()
            stats["models_removed"] += 1

        # Rename the target only after duplicates are gone to avoid the unique brand/name constraint.
        target.canonical_name = pretty_name
        target.aliases = sorted(alias for alias in aliases if alias and alias != pretty_name)
        target.save(update_fields=["canonical_name", "aliases"])
        return stats
