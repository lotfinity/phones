import json
import re
from decimal import Decimal
from statistics import median

from django.core.management.base import BaseCommand

from market.models import MarketListing
from market.services.currency import convert_to_eur
from market.services.listing_parser import (
    is_accessory_title,
    is_dirty_model_name,
    parse_condition,
    parse_sim_config,
    parse_storage_ram,
)
from market.services.listing_suggestions import build_listing_suggestion
from market.services.matching import SUPPORTED_STORAGE_GB, find_existing_variant


def clean_model(model):
    return (
        model
        and model.brand
        and model.brand.name != "Unknown"
        and not is_dirty_model_name(model.canonical_name)
        and not is_accessory_title(model.canonical_name)
    )


def parse_storage_extended(text):
    text = text or ""
    storage_gb, _ram = parse_storage_ram(text)
    if storage_gb in SUPPORTED_STORAGE_GB:
        return storage_gb, "explicit"
    if re.search(r"\b(?:1\s*tb|1000\s*(?:gb|g|go)?|1024\s*(?:gb|g|go)?)\b", text, re.IGNORECASE):
        return 1024, "explicit_1tb"
    if re.search(r"\b(?:2\s*tb|2000\s*(?:gb|g|go)?|2048\s*(?:gb|g|go)?)\b", text, re.IGNORECASE):
        return 2048, "explicit_2tb"
    return None, ""


def median_price_by_storage(product_model, listing):
    qs = (
        MarketListing.objects.filter(
            product_model=product_model,
            storage_gb__isnull=False,
            price_eur__isnull=False,
        )
        .exclude(id=listing.id)
        .exclude(review_status=MarketListing.ReviewStatus.REJECTED)
    )
    preferred = qs.filter(country=listing.country, source_type=listing.source_type)
    if preferred.count() >= 3:
        qs = preferred
    elif qs.filter(country=listing.country).count() >= 3:
        qs = qs.filter(country=listing.country)

    grouped = {}
    for row in qs.values_list("storage_gb", "price_eur"):
        storage, price = row
        if storage in SUPPORTED_STORAGE_GB and price and price > 0:
            grouped.setdefault(storage, []).append(Decimal(price))
    return {storage: median(values) for storage, values in grouped.items() if values}


def infer_storage_from_price(product_model, listing):
    if not listing.price_eur:
        return None, ""
    medians = median_price_by_storage(product_model, listing)
    if not medians:
        return None, ""
    price = Decimal(listing.price_eur)
    storage = min(medians, key=lambda item: abs(price - medians[item]))
    return storage, f"price_nearest:{storage}GB@{medians[storage]}"


def process_listing(listing):
    original = {
        "product_model_id": listing.product_model_id,
        "storage_gb": listing.storage_gb,
        "sim_config": listing.sim_config,
        "condition": listing.condition,
        "review_status": listing.review_status,
    }
    text = "\n".join([listing.title_raw or "", listing.description_raw or ""])
    evidence = []

    if listing.price_original and listing.currency_original and not listing.price_eur:
        listing.price_eur = convert_to_eur(listing.price_original, listing.currency_original)
        evidence.append("price_eur_recalculated")

    if not clean_model(listing.product_model):
        suggestion = build_listing_suggestion(listing)
        if clean_model(suggestion.product_model):
            listing.product_model = suggestion.product_model
            evidence.append(f"model:{suggestion.product_model_id if hasattr(suggestion, 'product_model_id') else suggestion.product_model.id}")

    if not listing.storage_gb:
        storage_gb, source = parse_storage_extended(text)
        if storage_gb:
            listing.storage_gb = storage_gb
            evidence.append(f"storage_{source}:{storage_gb}")

    if not listing.storage_gb and clean_model(listing.product_model):
        storage_gb, source = infer_storage_from_price(listing.product_model, listing)
        if storage_gb:
            listing.storage_gb = storage_gb
            evidence.append(f"storage_{source}")

    parsed_sim = parse_sim_config(text)
    if parsed_sim and parsed_sim != listing.sim_config:
        listing.sim_config = parsed_sim
        evidence.append(f"sim:{parsed_sim}")

    parsed_condition = parse_condition(text)
    if parsed_condition and parsed_condition != listing.condition:
        listing.condition = parsed_condition
        evidence.append(f"condition:{parsed_condition}")

    if clean_model(listing.product_model):
        listing.variant = find_existing_variant(
            listing.product_model,
            storage_gb=listing.storage_gb,
            sim_config=listing.sim_config,
        )

    complete = bool(clean_model(listing.product_model) and listing.storage_gb and listing.price_eur)
    listing.review_status = MarketListing.ReviewStatus.APPROVED if complete else MarketListing.ReviewStatus.NEEDS_REVIEW
    if complete:
        listing.parsed_confidence = max(listing.parsed_confidence or 0, 0.72)

    changed = any(getattr(listing, key) != value for key, value in original.items())
    if changed or evidence:
        if evidence and "finalize_review_queue" not in (listing.description_raw or ""):
            note = {"finalize_review_queue": evidence}
            listing.description_raw = f"{listing.description_raw or ''}\n{json.dumps(note, ensure_ascii=False)}".strip()
        listing.save()
    return changed or bool(evidence), complete, evidence


class Command(BaseCommand):
    help = "Finalize the review queue with explicit parsing and same-model price-band storage inference."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--close-rest", action="store_true")

    def handle(self, *args, **options):
        qs = MarketListing.objects.select_related("product_model", "product_model__brand").filter(
            review_status=MarketListing.ReviewStatus.NEEDS_REVIEW
        )
        if options["limit"]:
            qs = qs[: options["limit"]]

        total = changed = completed = 0
        for listing in qs:
            total += 1
            row_changed, row_complete, _evidence = process_listing(listing)
            changed += 1 if row_changed else 0
            completed += 1 if row_complete else 0

        remaining = MarketListing.objects.filter(review_status=MarketListing.ReviewStatus.NEEDS_REVIEW)
        closed = 0
        if options["close_rest"]:
            for listing in remaining.select_related("product_model", "product_model__brand"):
                text = f"{listing.title_raw or ''} {listing.description_raw or ''}".lower()
                model_name = (listing.product_model.canonical_name if listing.product_model else "").lower()
                reject_tokens = [
                    "watch",
                    "buds",
                    "airpods",
                    "case",
                    "coque",
                    "kılıf",
                    "kilif",
                    "playstation",
                    "imprimante",
                    "printer",
                    "ecotank",
                    "tab ",
                    "tablette",
                    "tablet",
                    "tuşlu",
                    "tuslu",
                    "b310",
                ]
                if not listing.price_eur or any(token in text or token in model_name for token in reject_tokens):
                    listing.review_status = MarketListing.ReviewStatus.REJECTED
                    listing.save(update_fields=["review_status"])
                    closed += 1
                    continue

                if not clean_model(listing.product_model):
                    suggestion = build_listing_suggestion(listing)
                    if clean_model(suggestion.product_model):
                        listing.product_model = suggestion.product_model

                if clean_model(listing.product_model) and not listing.storage_gb:
                    if re.search(r"\b266\b", text):
                        listing.storage_gb = 256
                    elif re.search(r"\b(?:fold|flip|pro max|ultra|x7 pro|k13 turbo)\b", text):
                        listing.storage_gb = 256
                    else:
                        listing.storage_gb = 128

                parsed_sim = parse_sim_config(text)
                if parsed_sim:
                    listing.sim_config = parsed_sim
                parsed_condition = parse_condition(text)
                if parsed_condition:
                    listing.condition = parsed_condition
                if clean_model(listing.product_model) and listing.storage_gb and listing.price_eur:
                    listing.variant = find_existing_variant(
                        listing.product_model,
                        storage_gb=listing.storage_gb,
                        sim_config=listing.sim_config,
                    )
                    listing.review_status = MarketListing.ReviewStatus.APPROVED
                    listing.parsed_confidence = max(listing.parsed_confidence or 0, 0.6)
                    listing.save()
                    closed += 1

            remaining = MarketListing.objects.filter(review_status=MarketListing.ReviewStatus.NEEDS_REVIEW)
        self.stdout.write(
            self.style.SUCCESS(
                f"processed={total} changed={changed} completed={completed} closed_rest={closed} remaining={remaining.count()}"
            )
        )
        self.stdout.write(
            "remaining_missing "
            f"model={remaining.filter(product_model__isnull=True).count()} "
            f"storage={remaining.filter(storage_gb__isnull=True).count()} "
            f"price={remaining.filter(price_eur__isnull=True).count()}"
        )
