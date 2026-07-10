"""Audit and repair unsafe LaptopListing rows from the raw-first migration."""

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from market.models import (
    Brand,
    LaptopListing,
    LaptopModel,
    LaptopVariant,
    ParsedListingCandidate,
    build_laptop_variant_identity,
)
from market.services.laptop_model_canonicalization import normalize_laptop_model_name
from market.services.laptop_quality import (
    candidate_has_laptop_export_identity,
    is_garbage_laptop_model_name,
    is_generic_laptop_model_name,
    listing_has_laptop_export_identity,
)


class Command(BaseCommand):
    help = (
        "Find unsafe LaptopListing rows, repair obvious raw-candidate mismatches, "
        "and keep uncertain rows in needs_review. Dry-run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write changes. Default is dry-run.")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--no-backup", action="store_true", help="Skip sqlite backup before --apply.")
        parser.add_argument(
            "--only-garbage",
            action="store_true",
            help="Only inspect rows with garbage/spec-fragment final model names.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        limit = options["limit"]

        qs = LaptopListing.objects.select_related(
            "laptop_model",
            "laptop_model__brand",
            "variant",
            "raw_listing",
            "raw_listing__candidate",
        ).order_by("id")

        suspect = []
        for listing in qs.iterator():
            if self._is_suspect(listing, only_garbage=options["only_garbage"]):
                suspect.append(listing)
                if limit and len(suspect) >= limit:
                    break

        repaired = flagged = unchanged = 0

        if apply and not options["no_backup"]:
            backup_path = self._backup_sqlite()
            if backup_path:
                self.stdout.write(self.style.SUCCESS(f"Backup created: {backup_path}"))

        for listing in suspect:
            action = self._plan_action(listing)
            self._print_action(listing, action)
            if not apply:
                continue

            with transaction.atomic():
                if action["action"] == "repair_from_candidate":
                    self._repair_from_candidate(listing, action["candidate"])
                    repaired += 1
                elif action["action"] == "flag_review":
                    fields = []
                    if listing.review_status != LaptopListing.ReviewStatus.NEEDS_REVIEW:
                        listing.review_status = LaptopListing.ReviewStatus.NEEDS_REVIEW
                        fields.append("review_status")
                    if fields:
                        listing.save(update_fields=fields)
                        flagged += 1
                    else:
                        unchanged += 1
                else:
                    unchanged += 1

        if not apply:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to write repairs/flags."))
        self.stdout.write(
            self.style.SUCCESS(
                f"suspect={len(suspect)} repaired={repaired} flagged={flagged} unchanged={unchanged}"
            )
        )

    def _is_suspect(self, listing, *, only_garbage=False):
        model_name = listing.laptop_model.canonical_name if listing.laptop_model else ""
        if is_garbage_laptop_model_name(model_name):
            return True
        if only_garbage:
            return False
        if is_generic_laptop_model_name(model_name) and not listing_has_laptop_export_identity(listing):
            return True
        return not listing_has_laptop_export_identity(listing)

    def _plan_action(self, listing):
        candidate = getattr(listing.raw_listing, "candidate", None) if listing.raw_listing_id else None
        if (
            candidate
            and candidate.detected_category == ParsedListingCandidate.DetectedCategory.LAPTOP
            and candidate.model_text
            and not is_garbage_laptop_model_name(candidate.model_text)
            and candidate_has_laptop_export_identity(candidate)
        ):
            return {"action": "repair_from_candidate", "candidate": candidate}
        return {"action": "flag_review", "candidate": candidate}

    def _repair_from_candidate(self, listing, candidate):
        brand = candidate.matched_brand
        if not brand and candidate.brand_text:
            brand = Brand.objects.filter(name__iexact=candidate.brand_text).first()
            if not brand:
                brand = Brand.objects.create(name=candidate.brand_text)

        specs = candidate.laptop_specs_json or {}
        model_name = normalize_laptop_model_name(brand.name if brand else "", candidate.model_text)
        laptop_model, _ = LaptopModel.objects.get_or_create(
            brand=brand,
            canonical_name=model_name,
            defaults={"series": specs.get("series", "")},
        )
        aliases = set(laptop_model.aliases or [])
        if candidate.model_text and candidate.model_text != model_name:
            aliases.add(candidate.model_text)
        if aliases != set(laptop_model.aliases or []):
            laptop_model.aliases = sorted(aliases)
            laptop_model.save(update_fields=["aliases"])

        cpu = specs.get("cpu", "")
        gpu = specs.get("gpu", "")
        ram_gb = specs.get("ram_gb")
        storage_gb = specs.get("storage_gb")
        screen_size = specs.get("screen_size")
        resolution = specs.get("resolution", "")
        refresh_rate_hz = specs.get("refresh_rate_hz")
        panel_type = specs.get("panel_type", "")

        variant = None
        identity_key = build_laptop_variant_identity(
            cpu, gpu, ram_gb, storage_gb, screen_size, resolution, refresh_rate_hz
        )
        if identity_key:
            label_parts = [model_name, cpu, gpu]
            if ram_gb:
                label_parts.append(f"{ram_gb}GB")
            if storage_gb:
                label_parts.append(f"{storage_gb}GB")
            variant, _ = LaptopVariant.objects.get_or_create(
                laptop_model=laptop_model,
                identity_key=identity_key,
                defaults={
                    "cpu": cpu,
                    "gpu": gpu,
                    "ram_gb": ram_gb,
                    "storage_gb": storage_gb,
                    "screen_size": screen_size,
                    "resolution": resolution,
                    "refresh_rate_hz": refresh_rate_hz,
                    "panel_type": panel_type,
                    "canonical_label": " ".join(part for part in label_parts if part),
                },
            )

        listing.laptop_model = laptop_model
        listing.variant = variant
        listing.title = " ".join(part for part in [candidate.brand_text, model_name] if part).strip()
        listing.cpu = cpu
        listing.gpu = gpu
        listing.ram_gb = ram_gb
        listing.storage_gb = storage_gb
        listing.screen_size = screen_size
        listing.resolution = resolution
        listing.refresh_rate_hz = refresh_rate_hz
        listing.panel_type = panel_type
        listing.parsed_confidence = candidate.confidence
        listing.review_status = LaptopListing.ReviewStatus.NEEDS_REVIEW
        listing.save()

    def _print_action(self, listing, action):
        model_name = listing.laptop_model.canonical_name if listing.laptop_model else ""
        candidate = action.get("candidate")
        cand_text = f"{candidate.brand_text} {candidate.model_text}".strip() if candidate else "-"
        self.stdout.write(
            f"{action['action']}: listing={listing.pk} model={model_name!r} "
            f"candidate={cand_text!r} status={listing.review_status} raw={listing.raw_listing_id}"
        )

    def _backup_sqlite(self):
        db_name = settings.DATABASES["default"].get("NAME")
        if not db_name or db_name == ":memory:":
            return None
        source = Path(db_name)
        if not source.exists():
            return None
        timestamp = timezone.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = Path(settings.BASE_DIR) / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"db.before-laptop-listing-cleanup-{timestamp}.sqlite3"
        shutil.copy2(source, target)
        return target
