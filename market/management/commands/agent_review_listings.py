import json
import re
import shutil
import subprocess
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from market.models import Condition, DeviceVariant, MarketListing, ProductModel
from market.services.currency import convert_to_eur
from market.services.listing_parser import extract_model_text
from market.services.listing_suggestions import build_listing_suggestion
from market.services.matching import SUPPORTED_STORAGE_GB, find_existing_variant


JSON_START = "PRICEBRIDGE_AGENT_JSON_START"
JSON_END = "PRICEBRIDGE_AGENT_JSON_END"


def clean_text(value, limit=900):
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[:limit]


def model_option_rows(listing, limit=30):
    detected = extract_model_text(f"{listing.title_raw}\n{listing.description_raw}")
    qs = ProductModel.objects.select_related("brand").exclude(brand__name="Unknown")
    if detected:
        tokens = [token for token in re.split(r"\W+", detected) if len(token) >= 2]
        query = Q()
        for token in tokens[:4]:
            query |= Q(canonical_name__icontains=token)
        if query:
            qs = qs.filter(query)
    rows = []
    for model in qs.order_by("brand__name", "canonical_name")[:limit]:
        rows.append(
            {
                "id": model.id,
                "name": model.canonical_name,
                "brand": model.brand.name if model.brand else "",
            }
        )
    return rows


def similar_listing_rows(listing, limit=24):
    qs = (
        MarketListing.objects.select_related("product_model", "source")
        .exclude(id=listing.id)
        .exclude(price_eur__isnull=True)
        .exclude(product_model__isnull=True)
        .order_by("-observed_at")
    )
    if listing.price_eur:
        low = Decimal(str(listing.price_eur)) * Decimal("0.75")
        high = Decimal(str(listing.price_eur)) * Decimal("1.25")
        qs = qs.filter(price_eur__gte=low, price_eur__lte=high)
    if listing.source_type:
        qs = qs.filter(source_type=listing.source_type)
    rows = []
    for item in qs[:limit]:
        rows.append(
            {
                "id": item.id,
                "title": clean_text(item.title_raw, 180),
                "model_id": item.product_model_id,
                "model": item.product_model.canonical_name if item.product_model else "",
                "storage_gb": item.storage_gb,
                "sim_config": item.sim_config,
                "price": f"{item.price_original} {item.currency_original}",
                "price_eur": str(item.price_eur or ""),
                "condition": item.condition,
                "status": item.review_status,
            }
        )
    return rows


def build_prompt(listing, deterministic_hint):
    context = {
        "task": "Review one PriceBridge marketplace listing and return final DB edits as JSON only.",
        "rules": [
            "You are allowed to inspect the listing_url if your environment can access it.",
            "For Sahibinden or Ouedkniss, only use a user-opened browser/CDP session if available; do not bypass challenges.",
            "If the URL cannot be inspected or does not provide enough data, make a safe assumption from title, description, deterministic_hint, model_options, and similar_priced_listings.",
            "Choose only an existing model_id from model_options or similar_priced_listings. Do not create product models or variants.",
            "Choose storage_gb only from [64, 128, 256, 512, 1024, 2048] or null.",
            "Choose sim_config as '', '2sim', or 'esim' unless the listing clearly says something else.",
            "Choose condition from Django choices: sealed, used_a_plus, used_a, used_b, used_c, used, unknown.",
            "Set review_status to approved only when model_id, storage_gb, and price are usable; otherwise needs_review.",
            "Return JSON between the marker lines and no other final data format.",
        ],
        "listing": {
            "id": listing.id,
            "url": listing.listing_url,
            "source_type": listing.source_type,
            "country": listing.country,
            "title": listing.title_raw,
            "description": clean_text(listing.description_raw, 3000),
            "current_model_id": listing.product_model_id,
            "current_model": listing.product_model.canonical_name if listing.product_model else "",
            "current_storage_gb": listing.storage_gb,
            "current_sim_config": listing.sim_config,
            "price": f"{listing.price_original} {listing.currency_original}",
            "price_eur": str(listing.price_eur or ""),
            "condition": listing.condition,
            "review_status": listing.review_status,
        },
        "deterministic_hint": deterministic_hint,
        "model_options": model_option_rows(listing),
        "similar_priced_listings": similar_listing_rows(listing),
        "required_json_schema": {
            "listing_id": listing.id,
            "model_id": "integer or null",
            "storage_gb": "integer or null",
            "sim_config": "string",
            "condition": "string",
            "review_status": "approved or needs_review",
            "confidence": "number from 0 to 1",
            "reason": "short explanation",
            "evidence": "short text describing URL/description/similar-price evidence used",
        },
    }
    return (
        "You are an OpenCode agent running PriceBridge listing review mode.\n"
        "Investigate, finalize, and return the DB edits. Do not edit files.\n\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        f"{JSON_START}\n"
        '{"listing_id":0,"model_id":null,"storage_gb":null,"sim_config":"","condition":"unknown",'
        '"review_status":"needs_review","confidence":0,"reason":"","evidence":""}\n'
        f"{JSON_END}"
    )


def extract_agent_json(output):
    pattern = re.compile(rf"{JSON_START}\s*(\{{.*?\}})\s*{JSON_END}", re.DOTALL)
    matches = pattern.findall(output or "")
    if not matches:
        raise ValueError("OpenCode did not return a marked JSON result.")
    return json.loads(matches[-1])


def validate_decision(listing, decision):
    if int(decision.get("listing_id") or 0) != listing.id:
        raise ValueError("Agent returned a mismatched listing_id.")

    model = None
    model_id = decision.get("model_id")
    if model_id not in ("", None):
        model = ProductModel.objects.select_related("brand").filter(id=int(model_id)).first()
        if not model:
            raise ValueError(f"ProductModel {model_id} does not exist.")
        if not model.brand or model.brand.name == "Unknown":
            raise ValueError("Agent selected an Unknown-brand model, which is not allowed.")

    storage_gb = decision.get("storage_gb")
    if storage_gb in ("", None):
        storage_gb = None
    else:
        storage_gb = int(storage_gb)
        if storage_gb not in SUPPORTED_STORAGE_GB:
            raise ValueError(f"Unsupported storage_gb {storage_gb}.")

    sim_config = str(decision.get("sim_config") or "").strip().lower()
    condition = str(decision.get("condition") or Condition.UNKNOWN).strip()
    if condition not in {choice[0] for choice in Condition.choices}:
        raise ValueError(f"Unsupported condition {condition}.")

    review_status = str(decision.get("review_status") or MarketListing.ReviewStatus.NEEDS_REVIEW).strip()
    if review_status not in {MarketListing.ReviewStatus.APPROVED, MarketListing.ReviewStatus.NEEDS_REVIEW}:
        raise ValueError("review_status must be approved or needs_review.")

    confidence = float(decision.get("confidence") or 0)
    confidence = max(0, min(confidence, 1))
    return {
        "model": model,
        "storage_gb": storage_gb,
        "sim_config": sim_config,
        "condition": condition,
        "review_status": review_status,
        "confidence": confidence,
        "reason": clean_text(str(decision.get("reason") or ""), 500),
        "evidence": clean_text(str(decision.get("evidence") or ""), 800),
    }


def apply_decision(listing, validated):
    if validated["model"]:
        listing.product_model = validated["model"]
    if validated["storage_gb"]:
        listing.storage_gb = validated["storage_gb"]
    listing.sim_config = validated["sim_config"]
    listing.condition = validated["condition"]
    if listing.price_original and listing.currency_original:
        listing.price_eur = convert_to_eur(listing.price_original, listing.currency_original)
    listing.variant = find_existing_variant(
        listing.product_model,
        storage_gb=listing.storage_gb,
        sim_config=listing.sim_config,
    )
    listing.review_status = validated["review_status"]
    listing.parsed_confidence = max(listing.parsed_confidence or 0, validated["confidence"])
    note = {
        "agent_review": {
            "confidence": validated["confidence"],
            "reason": validated["reason"],
            "evidence": validated["evidence"],
        }
    }
    existing = listing.description_raw or ""
    if "agent_review" not in existing:
        listing.description_raw = f"{existing}\n{json.dumps(note, ensure_ascii=False)}".strip()
    listing.save()


class Command(BaseCommand):
    help = "Launch OpenCode to inspect review listings and apply finalized DB edits directly."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10)
        parser.add_argument("--listing-id", type=int)
        parser.add_argument("--source-type", default="")
        parser.add_argument("--country", default="")
        parser.add_argument("--issue", choices=["", "missing_model", "missing_storage", "missing_price"], default="")
        parser.add_argument("--status", default=MarketListing.ReviewStatus.NEEDS_REVIEW)
        parser.add_argument("--opencode-bin", default="opencode")
        parser.add_argument("--model", default="")
        parser.add_argument("--timeout", type=int, default=240)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        opencode_bin = shutil.which(options["opencode_bin"])
        if not opencode_bin:
            raise CommandError(f"OpenCode binary not found: {options['opencode_bin']}")

        qs = MarketListing.objects.select_related("source", "product_model", "product_model__brand")
        if options["listing_id"]:
            qs = qs.filter(id=options["listing_id"])
        elif options["status"]:
            qs = qs.filter(review_status=options["status"])
        if options["source_type"]:
            qs = qs.filter(source_type=options["source_type"])
        if options["country"]:
            qs = qs.filter(country=options["country"])
        if options["issue"] == "missing_model":
            qs = qs.filter(product_model__isnull=True)
        elif options["issue"] == "missing_storage":
            qs = qs.filter(product_model__isnull=False, storage_gb__isnull=True)
        elif options["issue"] == "missing_price":
            qs = qs.filter(Q(price_original__isnull=True) | Q(price_eur__isnull=True))

        applied = dry_run = failed = 0
        for listing in qs.order_by("-observed_at")[: max(options["limit"], 0)]:
            hint = build_listing_suggestion(listing)
            deterministic_hint = {
                "model_id": hint.product_model.id if hint.product_model else None,
                "model": hint.product_model.canonical_name if hint.product_model else "",
                "storage_gb": hint.storage_gb,
                "sim_config": hint.sim_config,
                "condition": hint.condition,
                "confidence": hint.confidence,
                "reason": hint.reason,
            }
            prompt = build_prompt(listing, deterministic_hint)
            command = [opencode_bin, "run", "--format", "default", "--dir", ".", "--title", f"PriceBridge listing {listing.id}"]
            if options["model"]:
                command.extend(["--model", options["model"]])
            command.append(prompt)
            try:
                result = subprocess.run(
                    command,
                    cwd=".",
                    text=True,
                    capture_output=True,
                    timeout=options["timeout"],
                    check=False,
                )
                output = "\n".join([result.stdout or "", result.stderr or ""])
                if result.returncode != 0:
                    raise ValueError(f"OpenCode failed with exit code {result.returncode}: {clean_text(output, 1200)}")
                decision = extract_agent_json(output)
                validated = validate_decision(listing, decision)
                if options["dry_run"]:
                    dry_run += 1
                    self.stdout.write(f"DRY listing {listing.id}: {validated}")
                else:
                    apply_decision(listing, validated)
                    applied += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Applied listing {listing.id}: "
                            f"{validated['model'] or listing.product_model} / {validated['storage_gb']}GB / "
                            f"{validated['review_status']} ({validated['confidence']:.2f})"
                        )
                    )
            except Exception as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f"Failed listing {listing.id}: {exc}"))

        self.stdout.write(self.style.SUCCESS(f"agent_review_listings applied={applied} dry_run={dry_run} failed={failed}"))
