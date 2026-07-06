from django.conf import settings
from django.core.management.base import BaseCommand
from pathlib import Path

from market.models import Country, InstagramPost, MarketListing, OCRResult, SourceType
from market.parsers.ocr_backend import get_ocr_backend
from market.parsers.ocr_parser import parse_ocr_text
from market.services.currency import dzd_to_eur
from market.services.matching import find_existing_model, find_existing_variant


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


class Command(BaseCommand):
    help = "Process Instagram posts marked for OCR and create reviewable market listings."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--source-username", default="", help="Only process queued posts for one Instagram source.")

    def handle(self, *args, **options):
        backend = get_ocr_backend(settings.OCR_BACKEND)
        posts = InstagramPost.objects.filter(needs_ocr=True, ocr_processed=False)
        source_username = options["source_username"].strip().lstrip("@")
        if source_username:
            posts = posts.filter(source__source_type=SourceType.INSTAGRAM, source__username=source_username)
        posts = posts[: options["limit"]]
        processed = 0

        for post in posts:
            image_path = post.thumbnail_local_path or post.media_local_path
            try:
                raw_text, backend_confidence = backend.read_text(image_path) if image_path else ("", 0.0)
                combined_text = "\n".join(part for part in [post.caption, raw_text] if part)
                parsed = parse_ocr_text(combined_text)
                status = OCRResult.Status.PROCESSED if parsed.confidence >= 0.5 else OCRResult.Status.NEEDS_REVIEW
                ocr = OCRResult.objects.create(
                    instagram_post=post,
                    raw_text=raw_text,
                    confidence=max(parsed.confidence, backend_confidence or 0),
                    detected_price_dzd=parsed.price_dzd,
                    detected_model_text=parsed.model_text,
                    detected_storage_text=parsed.storage_text,
                    detected_battery_text=parsed.battery_text,
                    detected_condition_text=parsed.condition_text,
                    detected_sim_text=parsed.sim_text,
                    status=status,
                )
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
                    MarketListing.objects.update_or_create(
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
                post.ocr_processed = True
                post.needs_ocr = False
                post.save(update_fields=["ocr_processed", "needs_ocr"])
                processed += 1
            except Exception as exc:
                OCRResult.objects.create(instagram_post=post, raw_text="", status=OCRResult.Status.FAILED)
                self.stderr.write(f"Failed OCR for post {post.pk}: {exc}")

        self.stdout.write(self.style.SUCCESS(f"Processed {processed} OCR queue items."))
