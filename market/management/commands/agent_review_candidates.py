"""Run AI review for raw-first ParsedListingCandidate rows.

The legacy agent_review_listings command reviews MarketListing rows. This
command keeps the same local OpenCode pattern but targets the raw-first staging
table so review work can happen before exporting into PhoneListing/LaptopListing.
"""

import json
import re
import shutil
import subprocess

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from market.models import (
    Brand,
    Condition,
    ConsoleModel,
    LaptopModel,
    ParsedListingCandidate,
    PhoneModel,
)
from market.services.laptop_quality import candidate_has_laptop_export_identity


JSON_START = "PRICEBRIDGE_CANDIDATE_AUDIT_JSON_START"
JSON_END = "PRICEBRIDGE_CANDIDATE_AUDIT_JSON_END"
DEFAULT_CATEGORIES = ("phone", "laptop")


def clean_text(value, limit=1200):
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[:limit]


def candidate_audit_bucket(candidate):
    if candidate.detected_category not in DEFAULT_CATEGORIES:
        return "non_phone_laptop"
    if not (candidate.model_text or "").strip():
        return "missing_model"
    if candidate.confidence < 0.7:
        return "weak_confidence"
    if (
        candidate.detected_category == ParsedListingCandidate.DetectedCategory.LAPTOP
        and not candidate_has_laptop_export_identity(candidate)
    ):
        return "not_export_eligible"
    return "review"


def candidate_queryset(options):
    qs = ParsedListingCandidate.objects.select_related(
        "raw_listing",
        "matched_brand",
        "matched_phone_model",
        "matched_phone_variant",
        "matched_laptop_model",
        "matched_laptop_variant",
    )
    if options.get("candidate_id"):
        return qs.filter(id=options["candidate_id"])

    if options.get("flagged_only"):
        qs = qs.filter(ai_notes__icontains="[ai-audit]")
    elif options.get("status"):
        qs = qs.filter(status=options["status"])

    categories = options.get("categories") or DEFAULT_CATEGORIES
    if categories != ("all",):
        qs = qs.filter(detected_category__in=categories)

    bucket = options.get("bucket") or ""
    if bucket == "missing_model":
        qs = qs.filter(Q(model_text="") | Q(model_text__isnull=True))
    elif bucket == "weak_confidence":
        qs = qs.filter(confidence__lt=0.7)
    elif bucket == "not_export_eligible":
        ids = [
            candidate.id
            for candidate in qs.filter(detected_category=ParsedListingCandidate.DetectedCategory.LAPTOP)
            if not candidate_has_laptop_export_identity(candidate)
        ]
        qs = qs.filter(id__in=ids)
    elif bucket == "non_phone_laptop":
        qs = qs.exclude(detected_category__in=DEFAULT_CATEGORIES)

    return qs.order_by("-updated_at", "-created_at")


def model_option_rows(candidate, limit=30):
    text = " ".join(
        part for part in [candidate.brand_text, candidate.model_text, candidate.variant_text] if part
    )
    tokens = [token for token in re.split(r"\W+", text) if len(token) >= 2][:5]
    query = Q()
    for token in tokens:
        query |= Q(canonical_name__icontains=token) | Q(brand__name__icontains=token)

    if candidate.detected_category == ParsedListingCandidate.DetectedCategory.PHONE:
        qs = PhoneModel.objects.select_related("brand")
    elif candidate.detected_category == ParsedListingCandidate.DetectedCategory.LAPTOP:
        qs = LaptopModel.objects.select_related("brand")
    elif candidate.detected_category == ParsedListingCandidate.DetectedCategory.PORTABLE_CONSOLE:
        qs = ConsoleModel.objects.select_related("brand")
    else:
        return []
    if query:
        qs = qs.filter(query)

    return [
        {
            "id": model.id,
            "brand": model.brand.name if model.brand else "",
            "name": model.canonical_name,
        }
        for model in qs.order_by("brand__name", "canonical_name")[:limit]
    ]


def build_prompt(candidate):
    raw = candidate.raw_listing
    specs = (
        candidate.phone_specs_json
        if candidate.detected_category == ParsedListingCandidate.DetectedCategory.PHONE
        else candidate.console_specs_json
        if candidate.detected_category == ParsedListingCandidate.DetectedCategory.PORTABLE_CONSOLE
        else candidate.laptop_specs_json
    )
    context = {
        "task": "Audit one PriceBridge raw-first parsed listing candidate and return safe candidate edits as JSON only.",
        "rules": [
            "PriceBridge is market intelligence, not ecommerce.",
            "Prefer raw title, raw text, and structured payload evidence. URL slug is fallback evidence only.",
            "Do not invent confidence. If identity is incomplete, keep status needs_review.",
            "Only approve phone/laptop candidates when the device identity and price are usable.",
            "Do not approve chargers, bags, cases, docks, screens, mice, keyboards, earbuds, or accessories.",
            "For laptops, approve only with model + RAM + storage, or model + CPU + GPU, or an exact high-confidence variant.",
            "Choose existing model_id from model_options only when clearly correct; otherwise return null.",
            "Return JSON between the marker lines and no other final data format.",
        ],
        "candidate": {
            "id": candidate.id,
            "detected_category": candidate.detected_category,
            "status": candidate.status,
            "brand_text": candidate.brand_text,
            "model_text": candidate.model_text,
            "variant_text": candidate.variant_text,
            "price": f"{candidate.price_original or ''} {candidate.currency_original or ''}".strip(),
            "price_eur": str(candidate.price_eur or ""),
            "condition": candidate.condition,
            "confidence": candidate.confidence,
            "specs": specs,
            "review_notes": clean_text(candidate.review_notes, 900),
            "ai_notes": clean_text(candidate.ai_notes, 900),
        },
        "raw_listing": {
            "id": raw.id if raw else None,
            "url": raw.listing_url if raw else "",
            "source_type": raw.source_type if raw else "",
            "country": raw.country if raw else "",
            "category_hint": raw.category_hint if raw else "",
            "title": raw.title_raw if raw else "",
            "raw_text": clean_text(raw.raw_text if raw else "", 3000),
            "price_text_raw": raw.price_text_raw if raw else "",
            "payload": raw.raw_payload if raw else {},
        },
        "model_options": model_option_rows(candidate),
        "required_json_schema": {
            "candidate_id": candidate.id,
            "detected_category": "phone|laptop|portable_console|accessory|unknown",
            "brand_text": "string",
            "model_text": "string",
            "model_id": "integer or null from model_options",
            "condition": "one Django Condition value",
            "status": "approved|needs_review|rejected",
            "confidence": "number from 0 to 1",
            "phone_specs": "object for phone candidates",
            "laptop_specs": "object for laptop candidates",
            "console_specs": "object for portable console candidates",
            "reason": "short explanation",
            "evidence": "short evidence summary",
        },
    }
    return (
        "You are an OpenCode agent running PriceBridge raw-first candidate audit mode.\n"
        "Investigate the provided evidence and return only the marked JSON.\n\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        f"{JSON_START}\n"
        '{"candidate_id":0,"detected_category":"unknown","brand_text":"","model_text":"","model_id":null,'
        '"condition":"unknown","status":"needs_review","confidence":0,'
        '"phone_specs":{},"laptop_specs":{},"console_specs":{},"reason":"","evidence":""}\n'
        f"{JSON_END}"
    )


def extract_agent_json(output):
    pattern = re.compile(rf"{JSON_START}\s*(\{{.*?\}})\s*{JSON_END}", re.DOTALL)
    matches = pattern.findall(output or "")
    if not matches:
        raise ValueError("OpenCode did not return a marked candidate JSON result.")
    return json.loads(matches[-1])


def validate_decision(candidate, decision):
    if int(decision.get("candidate_id") or 0) != candidate.id:
        raise ValueError("Agent returned a mismatched candidate_id.")

    detected_category = str(decision.get("detected_category") or candidate.detected_category).strip()
    if detected_category not in {choice[0] for choice in ParsedListingCandidate.DetectedCategory.choices}:
        raise ValueError(f"Unsupported detected_category {detected_category}.")

    status = str(decision.get("status") or ParsedListingCandidate.Status.NEEDS_REVIEW).strip()
    if status not in {
        ParsedListingCandidate.Status.APPROVED,
        ParsedListingCandidate.Status.NEEDS_REVIEW,
        ParsedListingCandidate.Status.REJECTED,
    }:
        raise ValueError("status must be approved, needs_review, or rejected.")

    condition = str(decision.get("condition") or candidate.condition or Condition.UNKNOWN).strip()
    if condition not in {choice[0] for choice in Condition.choices}:
        raise ValueError(f"Unsupported condition {condition}.")

    model_id = decision.get("model_id")
    matched_model = None
    matched_brand = None
    if model_id not in ("", None):
        model_id = int(model_id)
        if detected_category == ParsedListingCandidate.DetectedCategory.PHONE:
            matched_model = PhoneModel.objects.select_related("brand").filter(id=model_id).first()
        elif detected_category == ParsedListingCandidate.DetectedCategory.LAPTOP:
            matched_model = LaptopModel.objects.select_related("brand").filter(id=model_id).first()
        elif detected_category == ParsedListingCandidate.DetectedCategory.PORTABLE_CONSOLE:
            matched_model = ConsoleModel.objects.select_related("brand").filter(id=model_id).first()
        if not matched_model:
            raise ValueError(f"Model {model_id} does not exist for {detected_category}.")
        matched_brand = matched_model.brand

    confidence = max(0.0, min(float(decision.get("confidence") or 0), 1.0))
    phone_specs = decision.get("phone_specs") if isinstance(decision.get("phone_specs"), dict) else {}
    laptop_specs = decision.get("laptop_specs") if isinstance(decision.get("laptop_specs"), dict) else {}
    console_specs = decision.get("console_specs") if isinstance(decision.get("console_specs"), dict) else {}
    if detected_category != ParsedListingCandidate.DetectedCategory.PHONE:
        phone_specs = {}
    if detected_category != ParsedListingCandidate.DetectedCategory.LAPTOP:
        laptop_specs = {}
    if detected_category != ParsedListingCandidate.DetectedCategory.PORTABLE_CONSOLE:
        console_specs = {}

    validated = {
        "detected_category": detected_category,
        "brand_text": clean_text(str(decision.get("brand_text") or candidate.brand_text), 160),
        "model_text": clean_text(str(decision.get("model_text") or candidate.model_text), 240),
        "matched_model": matched_model,
        "matched_brand": matched_brand,
        "condition": condition,
        "status": status,
        "confidence": confidence,
        "phone_specs": phone_specs,
        "laptop_specs": laptop_specs,
        "console_specs": console_specs,
        "reason": clean_text(str(decision.get("reason") or ""), 600),
        "evidence": clean_text(str(decision.get("evidence") or ""), 1000),
        "raw_response": decision,
    }

    if detected_category == ParsedListingCandidate.DetectedCategory.LAPTOP:
        preview = ParsedListingCandidate(
            detected_category=detected_category,
            brand_text=validated["brand_text"],
            model_text=validated["model_text"],
            laptop_specs_json=laptop_specs,
            matched_laptop_model=matched_model if isinstance(matched_model, LaptopModel) else None,
        )
        if status == ParsedListingCandidate.Status.APPROVED and not candidate_has_laptop_export_identity(preview):
            validated["status"] = ParsedListingCandidate.Status.NEEDS_REVIEW
            validated["reason"] = (
                f"{validated['reason']} Export blocked: incomplete laptop identity."
            ).strip()

    return validated


def apply_decision(candidate, validated):
    candidate.detected_category = validated["detected_category"]
    candidate.brand_text = validated["brand_text"]
    candidate.model_text = validated["model_text"]
    candidate.condition = validated["condition"]
    candidate.confidence = max(candidate.confidence or 0, validated["confidence"])
    candidate.status = validated["status"]
    candidate.raw_ai_response = validated["raw_response"]

    if validated["detected_category"] == ParsedListingCandidate.DetectedCategory.PHONE:
        candidate.phone_specs_json = validated["phone_specs"]
        if validated["matched_model"]:
            candidate.matched_phone_model = validated["matched_model"]
            candidate.matched_brand = validated["matched_brand"]
    elif validated["detected_category"] == ParsedListingCandidate.DetectedCategory.LAPTOP:
        candidate.laptop_specs_json = validated["laptop_specs"]
        if validated["matched_model"]:
            candidate.matched_laptop_model = validated["matched_model"]
            candidate.matched_brand = validated["matched_brand"]
    elif validated["detected_category"] == ParsedListingCandidate.DetectedCategory.PORTABLE_CONSOLE:
        candidate.console_specs_json = validated["console_specs"]
        if validated["matched_model"]:
            candidate.matched_console_model = validated["matched_model"]
            candidate.matched_brand = validated["matched_brand"]

    note = {
        "candidate_ai_audit": {
            "confidence": validated["confidence"],
            "reason": validated["reason"],
            "evidence": validated["evidence"],
            "status": validated["status"],
        }
    }
    candidate.ai_notes = f"{candidate.ai_notes}\n{json.dumps(note, ensure_ascii=False)}".strip()
    candidate.save()


class Command(BaseCommand):
    help = "Run OpenCode AI audit for raw-first phone/laptop ParsedListingCandidate rows."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10)
        parser.add_argument("--candidate-id", type=int)
        parser.add_argument(
            "--categories",
            default="phone,laptop",
            help="Comma-separated categories. Default phone,laptop. Use all to include accessories/unknown.",
        )
        parser.add_argument("--status", default=ParsedListingCandidate.Status.NEEDS_REVIEW)
        parser.add_argument("--flagged-only", action="store_true")
        parser.add_argument(
            "--bucket",
            choices=["", "missing_model", "weak_confidence", "not_export_eligible", "non_phone_laptop"],
            default="",
        )
        parser.add_argument("--opencode-bin", default="opencode")
        parser.add_argument("--model", default="")
        parser.add_argument("--timeout", type=int, default=240)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        categories = tuple(
            item.strip()
            for item in str(options["categories"]).split(",")
            if item.strip()
        ) or DEFAULT_CATEGORIES
        if categories != ("all",):
            allowed = {choice[0] for choice in ParsedListingCandidate.DetectedCategory.choices}
            invalid = sorted(set(categories) - allowed)
            if invalid:
                raise CommandError(f"Invalid categories: {', '.join(invalid)}")
        options["categories"] = categories

        opencode_bin = shutil.which(options["opencode_bin"])
        if not opencode_bin:
            raise CommandError(f"OpenCode binary not found: {options['opencode_bin']}")

        qs = candidate_queryset(options)
        applied = dry_run = failed = skipped = 0
        for candidate in qs[: max(options["limit"], 0)]:
            if categories != ("all",) and candidate.detected_category not in categories:
                skipped += 1
                continue
            prompt = build_prompt(candidate)
            command = [
                opencode_bin,
                "run",
                "--format",
                "default",
                "--dir",
                ".",
                "--title",
                f"PriceBridge candidate {candidate.id}",
            ]
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
                    raise ValueError(
                        f"OpenCode failed with exit code {result.returncode}: {clean_text(output, 1200)}"
                    )
                decision = extract_agent_json(output)
                validated = validate_decision(candidate, decision)
                if options["dry_run"]:
                    dry_run += 1
                    self.stdout.write(f"DRY candidate {candidate.id}: {validated}")
                else:
                    apply_decision(candidate, validated)
                    applied += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Applied candidate {candidate.id}: "
                            f"{validated['detected_category']} {validated['brand_text']} "
                            f"{validated['model_text']} / {validated['status']} "
                            f"({validated['confidence']:.2f})"
                        )
                    )
            except Exception as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f"Failed candidate {candidate.id}: {exc}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"agent_review_candidates applied={applied} dry_run={dry_run} failed={failed} skipped={skipped}"
            )
        )
