from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from pathlib import Path

from market.management.commands.export_candidates import Command as ExportCandidatesCommand
from market.models import (
    Country,
    InstagramPost,
    MarketListing,
    OCRResult,
    ParsedListingCandidate,
    RawListing,
    SourceType,
)
from market.parsers.ocr_backend import get_ocr_backend
from market.parsers.ocr_parser import parse_ocr_text
from market.services.currency import dzd_to_eur
from market.services.laptop_quality import candidate_has_laptop_export_identity
from market.services.matching import find_existing_model, find_existing_variant
from market.services.parsing.candidate_builder import build_candidate


CLEAN_EXPORT_CONFIDENCE_THRESHOLD = 0.65


def local_media_url(path):
    if not path:
        return ""
    media_root = Path(settings.MEDIA_ROOT).resolve()
    try:
        rel_path = Path(path).resolve().relative_to(media_root)
    except (OSError, ValueError):
        return ""
    media_url = "/" + settings.MEDIA_URL.lstrip("/")
    return f"{media_url.rstrip('/')}/{rel_path.as_posix()}"


def save_ocr_result(post, **fields):
    existing = OCRResult.objects.filter(instagram_post=post).order_by("-created_at", "-pk").first()
    if existing:
        for field, value in fields.items():
            setattr(existing, field, value)
        existing.save(update_fields=list(fields.keys()))
        return existing
    return OCRResult.objects.create(instagram_post=post, **fields)


def category_hint_from_nvidia_text(text):
    normalized = (text or "").lower()
    category = ""
    for line in normalized.splitlines():
        if line.startswith("category:"):
            category = line.split(":", 1)[1].strip()
            break

    if not category:
        category = normalized

    if "accessory" in category or any(
        token in category
        for token in ["charger", "case", "coque", "earbud", "airpods", "watch", "screen protector"]
    ):
        return RawListing.CategoryHint.ACCESSORIES
    if "console" in category or any(
        token in category
        for token in ["rog ally", "steam deck", "playstation portal", "xbox ally", "legion go"]
    ):
        return RawListing.CategoryHint.CONSOLES
    if "laptop" in category or any(
        token in category
        for token in ["macbook", "notebook", "thinkpad", "latitude", "elitebook", "vivobook", "ideapad"]
    ):
        return RawListing.CategoryHint.LAPTOPS
    if "phone" in category or any(
        token in category
        for token in ["iphone", "galaxy", "redmi", "poco", "honor", "oppo", "pixel"]
    ):
        return RawListing.CategoryHint.PHONES
    return RawListing.CategoryHint.UNKNOWN


def category_hint_from_nvidia_structured(data):
    if not isinstance(data, dict):
        return RawListing.CategoryHint.UNKNOWN
    category = str(data.get("category") or "").strip().lower()
    if category == "phone":
        return RawListing.CategoryHint.PHONES
    if category == "laptop":
        return RawListing.CategoryHint.LAPTOPS
    if category == "console":
        return RawListing.CategoryHint.CONSOLES
    if category == "accessory":
        return RawListing.CategoryHint.ACCESSORIES
    return RawListing.CategoryHint.UNKNOWN


def title_from_ocr(post, parsed, combined_text):
    if parsed.model_text:
        return parsed.model_text[:500]
    for line in (combined_text or "").splitlines():
        clean = line.strip()
        if clean and not clean.lower().startswith(("visible text:", "category:")):
            return clean[:500]
    return (post.shortcode or post.post_url or "")[:500]


def upsert_raw_listing_from_instagram(post, image_path, combined_text, raw_text, parsed, structured_data=None):
    structured_data = structured_data if isinstance(structured_data, dict) else {}
    listing_url = post.post_url
    if "manual_image=" in (post.post_url or ""):
        listing_url = local_media_url(image_path) or post.post_url
    image_url = local_media_url(image_path)
    price_text = f"{parsed.price_dzd} DZD" if parsed.price_dzd else ""
    raw, _created = RawListing.objects.update_or_create(
        source_type=SourceType.INSTAGRAM,
        listing_url=listing_url,
        defaults={
            "source": post.source,
            "country": post.source.country or Country.ALGERIA,
            "category_hint": (
                category_hint_from_nvidia_structured(structured_data)
                if structured_data
                else category_hint_from_nvidia_text("\n".join([raw_text or "", combined_text or ""]))
            ),
            "external_id": post.shortcode or str(post.pk),
            "title_raw": title_from_ocr(post, parsed, combined_text),
            "description_raw": combined_text,
            "raw_text": combined_text,
            "price_text_raw": price_text,
            "image_url": image_url,
            "raw_payload": {
                "collection_method": "instagram_nvidia_ocr",
                "instagram_post_id": post.pk,
                "shortcode": post.shortcode,
                "post_url": post.post_url,
                "media_local_path": post.media_local_path,
                "thumbnail_local_path": post.thumbnail_local_path,
                "nvidia_text": raw_text,
                "nvidia_structured": structured_data,
                "legacy_price_original": str(parsed.price_dzd) if parsed.price_dzd else "",
                "legacy_currency": MarketListing.Currency.DZD if parsed.price_dzd else "",
            },
            "content_hash": "",
            "observed_at": post.posted_at or post.collected_at,
            "parse_status": RawListing.ParseStatus.RAW,
        },
    )
    return raw


def export_candidate_if_ready(candidate):
    if candidate.status != ParsedListingCandidate.Status.PENDING:
        return False
    if candidate.confidence < CLEAN_EXPORT_CONFIDENCE_THRESHOLD:
        return False
    if not candidate.brand_text or not candidate.model_text or candidate.price_original is None:
        return False

    exporter = ExportCandidatesCommand()
    category = candidate.detected_category

    if category == ParsedListingCandidate.DetectedCategory.PHONE:
        export_method = exporter._export_phone
    elif category == ParsedListingCandidate.DetectedCategory.LAPTOP:
        if not candidate_has_laptop_export_identity(candidate):
            return False
        export_method = exporter._export_laptop
    elif category == ParsedListingCandidate.DetectedCategory.PORTABLE_CONSOLE:
        if not exporter._candidate_has_console_export_identity(candidate):
            return False
        export_method = exporter._export_console
    else:
        return False

    candidate.status = ParsedListingCandidate.Status.APPROVED
    candidate.save(update_fields=["status"])
    export_method(candidate)
    candidate.status = ParsedListingCandidate.Status.EXPORTED
    candidate.save(update_fields=["status"])
    if candidate.raw_listing:
        candidate.raw_listing.parse_status = RawListing.ParseStatus.EXPORTED
        candidate.raw_listing.save(update_fields=["parse_status"])
    return True


def process_instagram_post(post, backend=None, rebuild_clean=False):
    image_path = post.thumbnail_local_path or post.media_local_path
    structured_data = {}

    if rebuild_clean:
        existing_ocr = OCRResult.objects.filter(instagram_post=post).order_by("-created_at", "-pk").first()
        if not existing_ocr:
            return {"processed": False, "error": "No OCRResult row to rebuild from."}
        raw_text = existing_ocr.raw_text
        backend_confidence = existing_ocr.confidence or 0.0
        existing_raw = RawListing.objects.filter(
            source_type=SourceType.INSTAGRAM,
            listing_url=post.post_url,
        ).first()
        structured_data = (
            (existing_raw.raw_payload or {}).get("nvidia_structured", {})
            if existing_raw
            else {}
        )
    else:
        backend = backend or get_ocr_backend(settings.OCR_BACKEND)
        if image_path and hasattr(backend, "read_listing_data"):
            raw_text, backend_confidence, structured_data = backend.read_listing_data(image_path)
        else:
            raw_text, backend_confidence = backend.read_text(image_path) if image_path else ("", 0.0)

    combined_text = "\n".join(part for part in [post.caption, raw_text] if part)
    parsed = parse_ocr_text(combined_text)
    status = OCRResult.Status.PROCESSED if parsed.confidence >= 0.5 else OCRResult.Status.NEEDS_REVIEW
    if not rebuild_clean:
        save_ocr_result(
            post,
            raw_text=raw_text,
            confidence=max(parsed.confidence, backend_confidence or 0),
            detected_price_dzd=parsed.price_dzd,
            detected_model_text=parsed.model_text,
            detected_storage_text=parsed.storage_text,
            detected_battery_text=parsed.battery_text,
            detected_condition_text=parsed.condition_text,
            detected_sim_text=parsed.sim_text,
            status=status,
            created_at=timezone.now(),
        )

    raw_listing = upsert_raw_listing_from_instagram(
        post, image_path, combined_text, raw_text, parsed, structured_data
    )
    candidate, _candidate_created = build_candidate(raw_listing)
    exported = export_candidate_if_ready(candidate)

    product_model = find_existing_model(parsed.model_text) if parsed.model_text else None
    variant = (
        find_existing_variant(product_model, parsed.storage_gb, sim_config=parsed.sim_text)
        if product_model and parsed.storage_gb
        else None
    )
    if parsed.model_text and (parsed.price_dzd or parsed.storage_gb):
        listing_url = post.post_url
        if "manual_image=" in (post.post_url or ""):
            listing_url = local_media_url(image_path) or post.post_url
        listing, _ = MarketListing.objects.update_or_create(
            source=post.source,
            listing_url=listing_url,
            defaults={
                "source_type": SourceType.INSTAGRAM,
                "country": post.source.country or Country.ALGERIA,
                "product_model": product_model,
                "variant": variant,
                "storage_gb": parsed.storage_gb,
                "title_raw": parsed.model_text[:300],
                "description_raw": combined_text,
                "price_original": parsed.price_dzd,
                "currency_original": MarketListing.Currency.DZD,
                "price_eur": dzd_to_eur(parsed.price_dzd) if parsed.price_dzd else None,
                "condition": parsed.condition,
                "battery_health": parsed.battery_health,
                "battery_cycles": parsed.battery_cycles,
                "sim_config": parsed.sim_text,
                "listing_url": listing_url,
                "image_path": image_path,
                "observed_at": post.posted_at or post.collected_at,
                "parsed_confidence": parsed.confidence,
                "review_status": (
                    MarketListing.ReviewStatus.AUTO
                    if parsed.confidence >= 0.75
                    else MarketListing.ReviewStatus.NEEDS_REVIEW
                ),
            },
        )
        from market.services.spec_extraction import extract_specs_from_listing
        extracted = extract_specs_from_listing(
            None,
            parsed.model_text or "",
            description=combined_text,
        )
        if extracted.specs and product_model and product_model.product_type:
            from market.services.catalog import upsert_listing_specs_from_dict
            upsert_listing_specs_from_dict(listing, extracted.specs, confidence=extracted.confidence)

    if not rebuild_clean:
        post.ocr_processed = True
        post.needs_ocr = False
        post.save(update_fields=["ocr_processed", "needs_ocr"])

    return {
        "processed": True,
        "post": post,
        "raw_listing": raw_listing,
        "candidate": candidate,
        "exported": exported,
        "structured_category": structured_data.get("category") if isinstance(structured_data, dict) else "",
    }


class Command(BaseCommand):
    help = "Process Instagram posts marked for OCR and create reviewable market listings."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--source-username", default="", help="Only process queued posts for one Instagram source.")
        parser.add_argument(
            "--rebuild-clean-listings",
            action="store_true",
            help="Reuse existing OCRResult rows to rebuild RawListing/candidate/clean listing exports.",
        )
        parser.add_argument(
            "--reprocess-existing",
            action="store_true",
            help="Call NVIDIA again for already processed Instagram posts and rebuild clean exports.",
        )

    def handle(self, *args, **options):
        rebuild_clean = options["rebuild_clean_listings"]
        reprocess_existing = options["reprocess_existing"]
        backend = None if rebuild_clean else get_ocr_backend(settings.OCR_BACKEND)
        posts = InstagramPost.objects.all()
        if rebuild_clean:
            posts = posts.filter(ocr_processed=True, ocrresult__isnull=False).distinct()
        elif reprocess_existing:
            posts = posts.filter(ocr_processed=True)
        else:
            posts = posts.filter(needs_ocr=True, ocr_processed=False)
        source_username = options["source_username"].strip().lstrip("@")
        if source_username:
            posts = posts.filter(source__source_type=SourceType.INSTAGRAM, source__username=source_username)
        posts = posts[: options["limit"]]
        processed = 0
        raw_count = 0
        candidate_count = 0
        exported_count = 0

        for post in posts:
            try:
                result = process_instagram_post(post, backend=backend, rebuild_clean=rebuild_clean)
                if not result.get("processed"):
                    continue
                raw_count += 1
                candidate_count += 1
                if result.get("exported"):
                    exported_count += 1
                processed += 1
            except Exception as exc:
                if not rebuild_clean:
                    save_ocr_result(post, raw_text="", status=OCRResult.Status.FAILED, created_at=timezone.now())
                self.stderr.write(f"Failed OCR for post {post.pk}: {exc}")

        self.stdout.write(self.style.SUCCESS(f"Processed {processed} OCR queue items."))
        self.stdout.write(
            self.style.SUCCESS(
                f"Clean listing pipeline: raw={raw_count}, candidates={candidate_count}, exported={exported_count}."
            )
        )
