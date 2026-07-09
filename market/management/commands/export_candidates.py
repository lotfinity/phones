"""Export approved ParsedListingCandidates into PhoneListing or LaptopListing."""

from django.core.management.base import BaseCommand

from market.models import (
    Brand,
    LaptopListing,
    LaptopModel,
    LaptopVariant,
    ParsedListingCandidate,
    PhoneListing,
    PhoneModel,
    PhoneVariant,
    RawListing,
    build_laptop_variant_identity,
    build_phone_variant_identity,
    normalize_sim_config,
)
from market.services.currency import convert_to_eur
from market.services.laptop_model_canonicalization import normalize_laptop_model_name
from market.services.phone_model_canonicalization import canonical_phone_model_name


class Command(BaseCommand):
    help = "Export approved ParsedListingCandidates into PhoneListing or LaptopListing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--category", choices=["phones", "laptops"], required=True,
        )
        parser.add_argument(
            "--status", default="approved",
            help="Candidate status to export (default: approved).",
        )
        parser.add_argument("--candidate-id", type=int)
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args, **options):
        category = options["category"]
        status = options["status"]
        limit = options["limit"]

        qs = ParsedListingCandidate.objects.filter(status=status)
        if options["candidate_id"]:
            qs = qs.filter(pk=options["candidate_id"])

        if category == "phones":
            qs = qs.filter(detected_category=ParsedListingCandidate.DetectedCategory.PHONE)
        else:
            qs = qs.filter(detected_category=ParsedListingCandidate.DetectedCategory.LAPTOP)

        qs = qs.select_related(
            "raw_listing",
            "matched_brand",
            "matched_phone_model",
            "matched_phone_variant",
            "matched_laptop_model",
            "matched_laptop_variant",
        )[:limit]

        exported = 0
        for candidate in qs.iterator():
            if category == "phones":
                self._export_phone(candidate)
            else:
                self._export_laptop(candidate)
            candidate.status = ParsedListingCandidate.Status.EXPORTED
            candidate.save(update_fields=["status"])
            if candidate.raw_listing:
                candidate.raw_listing.parse_status = RawListing.ParseStatus.EXPORTED
                candidate.raw_listing.save(update_fields=["parse_status"])
            exported += 1

        self.stdout.write(self.style.SUCCESS(f"Exported {exported} {category} candidates."))

    def _candidate_price_eur(self, candidate):
        if candidate.price_eur is not None:
            return candidate.price_eur
        if candidate.price_original is not None and candidate.currency_original:
            return convert_to_eur(candidate.price_original, candidate.currency_original)
        return None

    def _review_status_for_export(self, candidate, listing_model):
        if candidate.status in {
            ParsedListingCandidate.Status.APPROVED,
            ParsedListingCandidate.Status.EXPORTED,
        }:
            return listing_model.ReviewStatus.APPROVED
        return listing_model.ReviewStatus.NEEDS_REVIEW

    def _get_or_create_brand(self, candidate):
        brand = candidate.matched_brand
        if brand or not candidate.brand_text:
            return brand
        existing = Brand.objects.filter(name__iexact=candidate.brand_text).first()
        if existing:
            return existing
        return Brand.objects.create(name=candidate.brand_text)

    def _export_phone(self, candidate):
        brand = self._get_or_create_brand(candidate)
        specs = candidate.phone_specs_json or {}
        storage_gb = specs.get("storage_gb")
        ram_gb = specs.get("ram_gb")
        sim_config = normalize_sim_config(specs.get("sim_config", ""))
        region = specs.get("region", "")
        color = specs.get("color", "")

        variant = candidate.matched_phone_variant
        phone_model = candidate.matched_phone_model or (variant.phone_model if variant else None)

        canonical_model_name = ""
        if brand and candidate.model_text:
            canonical_model_name = canonical_phone_model_name(brand.name, candidate.model_text)

        if not phone_model and brand and candidate.model_text:
            phone_model, _ = PhoneModel.objects.get_or_create(
                brand=brand,
                canonical_name=canonical_model_name or candidate.model_text,
                defaults={"canonical_name": canonical_model_name or candidate.model_text},
            )
            aliases = set(phone_model.aliases or [])
            if candidate.model_text and candidate.model_text != phone_model.canonical_name:
                aliases.add(candidate.model_text)
                phone_model.aliases = sorted(aliases)
                phone_model.save(update_fields=["aliases"])

        if phone_model and not variant:
            label_parts = [canonical_model_name or candidate.model_text or phone_model.canonical_name]
            if storage_gb:
                label_parts.append(f"{storage_gb}GB")
            if ram_gb:
                label_parts.append(f"{ram_gb}GB RAM")
            if sim_config:
                label_parts.append(sim_config)
            canonical_label = " ".join(part for part in label_parts if part)

            identity_key = build_phone_variant_identity(
                storage_gb, ram_gb, sim_config, region, color
            )

            variant, _ = PhoneVariant.objects.get_or_create(
                phone_model=phone_model,
                identity_key=identity_key,
                defaults={
                    "storage_gb": storage_gb,
                    "ram_gb": ram_gb,
                    "sim_config": sim_config,
                    "region": region,
                    "color": color,
                    "canonical_label": canonical_label,
                },
            )

        raw = candidate.raw_listing
        title = " ".join(part for part in [candidate.brand_text, candidate.model_text] if part).strip()
        if not title and raw:
            title = raw.title_raw
        listing, _ = PhoneListing.objects.update_or_create(
            raw_listing=raw,
            defaults={
                "source": raw.source if raw else None,
                "source_type": raw.source_type if raw else "",
                "country": raw.country if raw else "",
                "phone_model": phone_model,
                "variant": variant,
                "title": title,
                "price_original": candidate.price_original,
                "currency_original": candidate.currency_original,
                "price_eur": self._candidate_price_eur(candidate),
                "condition": candidate.condition,
                "storage_gb": storage_gb,
                "ram_gb": ram_gb,
                "sim_config": sim_config,
                "battery_health": specs.get("battery_health"),
                "battery_cycles": specs.get("battery_cycles"),
                "box_status": specs.get("box_status", ""),
                "region": region,
                "color": color,
                "listing_url": raw.listing_url if raw else "",
                "image_url": raw.image_url if raw else "",
                "parsed_confidence": candidate.confidence,
                "review_status": self._review_status_for_export(candidate, PhoneListing),
            },
        )
        return listing

    def _export_laptop(self, candidate):
        brand = self._get_or_create_brand(candidate)
        specs = candidate.laptop_specs_json or {}
        cpu = specs.get("cpu", "")
        gpu = specs.get("gpu", "")
        ram_gb = specs.get("ram_gb")
        storage_gb = specs.get("storage_gb")
        screen_size = specs.get("screen_size")
        resolution = specs.get("resolution", "")
        refresh_rate_hz = specs.get("refresh_rate_hz")
        panel_type = specs.get("panel_type", "")

        variant = candidate.matched_laptop_variant
        laptop_model = candidate.matched_laptop_model or (variant.laptop_model if variant else None)

        # Use canonicalization for readable model names
        canonical_model_name = ""
        series = ""
        if brand and candidate.model_text:
            canonical_model_name = normalize_laptop_model_name(brand.name, candidate.model_text)
            series = candidate.laptop_specs_json.get("series", "") if hasattr(candidate, "laptop_specs_json") else ""

        if not laptop_model and brand and candidate.model_text:
            laptop_model, _ = LaptopModel.objects.get_or_create(
                brand=brand,
                canonical_name=canonical_model_name or candidate.model_text,
                defaults={
                    "canonical_name": canonical_model_name or candidate.model_text,
                    "series": series,
                },
            )
            # Track aliases
            aliases = set(laptop_model.aliases or [])
            if candidate.model_text and candidate.model_text != laptop_model.canonical_name:
                aliases.add(candidate.model_text)
                laptop_model.aliases = sorted(aliases)
                laptop_model.save(update_fields=["aliases"])

        if laptop_model and not variant:
            label_parts = [canonical_model_name or candidate.model_text or laptop_model.canonical_name]
            if cpu:
                label_parts.append(cpu)
            if gpu:
                label_parts.append(gpu)
            if ram_gb:
                label_parts.append(f"{ram_gb}GB")
            if storage_gb:
                label_parts.append(f"{storage_gb}GB")
            canonical_label = " ".join(part for part in label_parts if part)

            identity_key = build_laptop_variant_identity(
                cpu, gpu, ram_gb, storage_gb,
                screen_size, resolution, refresh_rate_hz,
            )

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
                    "canonical_label": canonical_label,
                },
            )

        raw = candidate.raw_listing
        title = " ".join(part for part in [candidate.brand_text, candidate.model_text] if part).strip()
        if not title and raw:
            title = raw.title_raw
        listing, _ = LaptopListing.objects.update_or_create(
            raw_listing=raw,
            defaults={
                "source": raw.source if raw else None,
                "source_type": raw.source_type if raw else "",
                "country": raw.country if raw else "",
                "laptop_model": laptop_model,
                "variant": variant,
                "title": title,
                "price_original": candidate.price_original,
                "currency_original": candidate.currency_original,
                "price_eur": self._candidate_price_eur(candidate),
                "condition": candidate.condition,
                "cpu": cpu,
                "gpu": gpu,
                "ram_gb": ram_gb,
                "storage_gb": storage_gb,
                "screen_size": screen_size,
                "resolution": resolution,
                "refresh_rate_hz": refresh_rate_hz,
                "panel_type": panel_type,
                "listing_url": raw.listing_url if raw else "",
                "image_url": raw.image_url if raw else "",
                "parsed_confidence": candidate.confidence,
                "review_status": self._review_status_for_export(candidate, LaptopListing),
            },
        )
        return listing
