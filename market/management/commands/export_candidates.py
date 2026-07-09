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
    normalize_variant_text,
)


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

        qs = qs.select_related("raw_listing", "matched_brand")[:limit]

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

    def _export_phone(self, candidate):
        brand = candidate.matched_brand
        if not brand and candidate.brand_text:
            brand, _ = Brand.objects.get_or_create(
                name__iexact=candidate.brand_text,
                defaults={"name": candidate.brand_text},
            )

        phone_model = None
        if brand and candidate.model_text:
            phone_model, _ = PhoneModel.objects.get_or_create(
                brand=brand,
                canonical_name=candidate.model_text,
                defaults={"canonical_name": candidate.model_text},
            )

        specs = candidate.phone_specs_json or {}
        storage_gb = specs.get("storage_gb")
        ram_gb = specs.get("ram_gb")
        sim_config = normalize_sim_config(specs.get("sim_config", ""))
        region = specs.get("region", "")
        color = specs.get("color", "")

        variant = None
        if phone_model:
            label_parts = [candidate.model_text]
            if storage_gb:
                label_parts.append(f"{storage_gb}GB")
            if ram_gb:
                label_parts.append(f"{ram_gb}GB RAM")
            if sim_config:
                label_parts.append(sim_config)
            canonical_label = " ".join(label_parts)

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
        listing, _ = PhoneListing.objects.update_or_create(
            raw_listing=raw,
            defaults={
                "source": raw.source if raw else None,
                "source_type": raw.source_type if raw else "",
                "country": raw.country if raw else "",
                "phone_model": phone_model,
                "variant": variant,
                "title": candidate.brand_text + " " + candidate.model_text,
                "price_original": candidate.price_original,
                "currency_original": candidate.currency_original,
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
                "review_status": PhoneListing.ReviewStatus.NEEDS_REVIEW,
            },
        )
        return listing

    def _export_laptop(self, candidate):
        brand = candidate.matched_brand
        if not brand and candidate.brand_text:
            brand, _ = Brand.objects.get_or_create(
                name__iexact=candidate.brand_text,
                defaults={"name": candidate.brand_text},
            )

        laptop_model = None
        if brand and candidate.model_text:
            laptop_model, _ = LaptopModel.objects.get_or_create(
                brand=brand,
                canonical_name=candidate.model_text,
                defaults={"canonical_name": candidate.model_text},
            )

        specs = candidate.laptop_specs_json or {}
        cpu = specs.get("cpu", "")
        gpu = specs.get("gpu", "")
        ram_gb = specs.get("ram_gb")
        storage_gb = specs.get("storage_gb")
        screen_size = specs.get("screen_size")
        resolution = specs.get("resolution", "")
        refresh_rate_hz = specs.get("refresh_rate_hz")
        panel_type = specs.get("panel_type", "")

        variant = None
        if laptop_model:
            label_parts = [candidate.model_text]
            if cpu:
                label_parts.append(cpu)
            if gpu:
                label_parts.append(gpu)
            if ram_gb:
                label_parts.append(f"{ram_gb}GB")
            if storage_gb:
                label_parts.append(f"{storage_gb}GB")
            canonical_label = " ".join(label_parts)

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
        listing, _ = LaptopListing.objects.update_or_create(
            raw_listing=raw,
            defaults={
                "source": raw.source if raw else None,
                "source_type": raw.source_type if raw else "",
                "country": raw.country if raw else "",
                "laptop_model": laptop_model,
                "variant": variant,
                "title": candidate.brand_text + " " + candidate.model_text,
                "price_original": candidate.price_original,
                "currency_original": candidate.currency_original,
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
                "review_status": LaptopListing.ReviewStatus.NEEDS_REVIEW,
            },
        )
        return listing
