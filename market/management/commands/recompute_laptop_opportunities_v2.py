import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Avg, Count, Min
from django.utils import timezone

from market.clean_models import LaptopOpportunitySnapshot
from market.models import Country, LaptopListing, LaptopModel, SourceType
from market.services.gain_split import attach_buyer_pricing, json_safe
from market.services.laptop_model_canonicalization import (
    normalize_cpu_family,
    normalize_gpu_family,
)
from market.services.laptop_quality import (
    is_implausible_laptop_price,
    is_garbage_laptop_model_name,
    is_generic_laptop_model_name,
    listing_has_laptop_opportunity_identity,
)

VISIBLE_REVIEW_STATUSES = (
    LaptopListing.ReviewStatus.AUTO,
    LaptopListing.ReviewStatus.APPROVED,
    LaptopListing.ReviewStatus.NEEDS_REVIEW,
)
APPROVED_REVIEW_STATUSES = (
    LaptopListing.ReviewStatus.AUTO,
    LaptopListing.ReviewStatus.APPROVED,
)
VALID_LAPTOP_STORAGE_GB = {128, 256, 512, 1024, 2048, 4096, 8192}


def _decimal_option(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise CommandError(f"Invalid decimal value: {value}") from exc


def _money(value):
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _percent(value):
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _row_to_json(row):
    return json_safe(row)


def _confidence_score(algeria_count, turkiye_count, has_cpu, has_gpu):
    """Compute a confidence score based on data availability."""
    score = 0.0
    # Both sides present
    if algeria_count > 0 and turkiye_count > 0:
        score += 0.5
    # Enough data points
    if algeria_count >= 3:
        score += 0.15
    elif algeria_count >= 1:
        score += 0.1
    if turkiye_count >= 3:
        score += 0.15
    elif turkiye_count >= 1:
        score += 0.1
    # Spec completeness
    if has_cpu:
        score += 0.1
    if has_gpu:
        score += 0.1
    return min(score, 1.0)


def _recommendation(margin_percent, confidence):
    """Generate a recommendation string."""
    if margin_percent is None:
        return "no_data"
    if confidence < 0.5:
        return "low_confidence"
    if margin_percent >= Decimal("30") and confidence >= 0.7:
        return "strong_buy"
    if margin_percent >= Decimal("15") and confidence >= 0.6:
        return "good_opportunity"
    if margin_percent >= Decimal("5"):
        return "marginal"
    return "no_margin"


def _snapshot_recommendation(value):
    mapping = {
        "strong_buy": LaptopOpportunitySnapshot.Recommendation.BUY,
        "good_opportunity": LaptopOpportunitySnapshot.Recommendation.GOOD_OPPORTUNITY,
        "marginal": LaptopOpportunitySnapshot.Recommendation.MARGINAL,
        "low_confidence": LaptopOpportunitySnapshot.Recommendation.LOW_CONFIDENCE,
        "no_margin": LaptopOpportunitySnapshot.Recommendation.NO_MARGIN,
        "no_data": LaptopOpportunitySnapshot.Recommendation.IGNORE,
    }
    return mapping.get(value, LaptopOpportunitySnapshot.Recommendation.WATCH)


def _eligible_laptop_queryset(qs):
    eligible_ids = []
    for listing in qs.select_related("laptop_model", "variant").iterator():
        if listing_has_laptop_opportunity_identity(listing) and not is_implausible_laptop_price(listing):
            eligible_ids.append(listing.pk)
    return qs.filter(pk__in=eligible_ids)


def compute_laptop_opportunity_rows(
    *,
    min_margin_eur=Decimal("0"),
    min_margin_percent=Decimal("0"),
    limit=100,
    only_approved=False,
    loose=False,
):
    review_statuses = APPROVED_REVIEW_STATUSES if only_approved else VISIBLE_REVIEW_STATUSES
    base = LaptopListing.objects.select_related("laptop_model", "laptop_model__brand").filter(
        price_eur__isnull=False,
        laptop_model__isnull=False,
        review_status__in=review_statuses,
    )
    base = _eligible_laptop_queryset(base)

    # Group Algeria listings by spec signature
    algeria_listings = base.filter(country=Country.ALGERIA)

    # Build groups: (model_id, cpu_family, gpu_family, ram_gb, storage_gb)
    algeria_groups_raw = (
        algeria_listings.values(
            "laptop_model_id",
            "cpu",
            "gpu",
            "ram_gb",
            "storage_gb",
        )
        .annotate(
            algeria_min_eur=Min("price_eur"),
            algeria_avg_eur=Avg("price_eur"),
            algeria_count=Count("id"),
        )
    )

    rows = []
    seen_signatures = set()

    for group in algeria_groups_raw:
        model_id = group["laptop_model_id"]
        cpu_raw = group["cpu"] or ""
        gpu_raw = group["gpu"] or ""
        ram_gb = group["ram_gb"]
        storage_gb = group["storage_gb"]
        sample_model = LaptopModel.objects.filter(pk=model_id).first()
        model_name = sample_model.canonical_name if sample_model else ""

        if is_garbage_laptop_model_name(model_name):
            continue

        cpu_key = normalize_cpu_family(cpu_raw)
        gpu_key = normalize_gpu_family(gpu_raw)
        has_ram_storage = bool(ram_gb and storage_gb)
        has_cpu_gpu = bool(cpu_key and gpu_key)

        if not has_ram_storage:
            continue
        if storage_gb and storage_gb not in VALID_LAPTOP_STORAGE_GB:
            continue
        if is_generic_laptop_model_name(model_name) and not (has_ram_storage or has_cpu_gpu):
            continue

        signature = (model_id, cpu_key, gpu_key, ram_gb, storage_gb)

        # Skip duplicates (different raw text but same normalized spec)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        # Match Turkiye listings
        tr_filter = {
            "country": Country.TURKIYE,
            "source_type": SourceType.SAHIBINDEN,
            "laptop_model_id": model_id,
        }

        if loose:
            # Loose matching: only match on model + RAM + storage (ignore CPU/GPU)
            tr_filter.pop("source_type", None)
            if not has_ram_storage:
                continue
        else:
            # Strict matching: model + RAM + storage is enough; CPU/GPU narrow when present.
            if cpu_key:
                tr_filter["cpu__icontains"] = cpu_raw.split("-")[0] if "-" in cpu_raw else cpu_raw
            if gpu_key:
                tr_filter["gpu__icontains"] = gpu_raw.split(" ")[-1] if " " in gpu_raw else gpu_raw

        # Always match on RAM and storage
        if ram_gb:
            tr_filter["ram_gb"] = ram_gb
        if storage_gb:
            tr_filter["storage_gb"] = storage_gb

        tr_stats = base.filter(**tr_filter).aggregate(
            turkiye_avg_eur=Avg("price_eur"),
            turkiye_min_eur=Min("price_eur"),
            turkiye_count=Count("id"),
        )

        if not tr_stats["turkiye_count"]:
            continue

        algeria_min = Decimal(str(group["algeria_min_eur"]))
        turkiye_avg = Decimal(str(tr_stats["turkiye_avg_eur"]))
        gross_margin = turkiye_avg - algeria_min
        margin_percent = (gross_margin / algeria_min * Decimal("100")) if algeria_min else None

        if gross_margin < min_margin_eur:
            continue
        if margin_percent is not None and margin_percent < min_margin_percent:
            continue

        # Get sample listing for brand/model name
        sample = (
            base.filter(
                laptop_model_id=model_id,
                ram_gb=ram_gb,
                storage_gb=storage_gb,
            )
            .select_related("laptop_model", "laptop_model__brand")
            .first()
        )
        if not sample or not sample.laptop_model:
            continue

        confidence = _confidence_score(
            group["algeria_count"],
            tr_stats["turkiye_count"],
            has_cpu=bool(cpu_key),
            has_gpu=bool(gpu_key),
        )

        # Collect example URLs
        algeria_urls = list(
            base.filter(
                country=Country.ALGERIA,
                laptop_model_id=model_id,
                ram_gb=ram_gb,
                storage_gb=storage_gb,
            )
            .order_by("price_eur")
            .values_list("listing_url", flat=True)[:5]
        )
        turkiye_urls = list(
            base.filter(
                country=Country.TURKIYE,
                source_type=SourceType.SAHIBINDEN,
                laptop_model_id=model_id,
                ram_gb=ram_gb,
                storage_gb=storage_gb,
            )
            .order_by("price_eur")
            .values_list("listing_url", flat=True)[:5]
        )

        rec = _recommendation(margin_percent, confidence)

        rows.append({
            "brand": sample.laptop_model.brand.name if sample.laptop_model.brand else "",
            "model": sample.laptop_model.canonical_name,
            "laptop_model_id": model_id,
            "cpu": cpu_raw,
            "gpu": gpu_raw,
            "ram_gb": ram_gb,
            "storage_gb": storage_gb,
            "algeria_min_eur": _money(algeria_min),
            "algeria_avg_eur": _money(group["algeria_avg_eur"]),
            "turkiye_min_eur": _money(tr_stats["turkiye_min_eur"]),
            "turkiye_avg_eur": _money(turkiye_avg),
            "margin_eur": _money(gross_margin),
            "margin_percent": _percent(margin_percent),
            "algeria_count": group["algeria_count"],
            "turkiye_count": tr_stats["turkiye_count"],
            "confidence": round(confidence, 2),
            "recommendation": rec,
            "algeria_urls": [url for url in algeria_urls if url],
            "turkiye_urls": [url for url in turkiye_urls if url],
        })
        attach_buyer_pricing(rows[-1], margin_key="margin_eur")

    rows.sort(key=lambda item: (item["margin_eur"] or Decimal("0"), item["margin_percent"] or Decimal("0")), reverse=True)
    return rows[:limit]


def write_laptop_opportunity_snapshots(rows, *, source_label="laptop_v2"):
    generated_at = timezone.now()
    snapshots = []
    for row in rows:
        snapshots.append(
            LaptopOpportunitySnapshot(
                laptop_model_id=row.get("laptop_model_id"),
                brand=row.get("brand") or "",
                model=row.get("model") or "",
                cpu=row.get("cpu") or "",
                gpu=row.get("gpu") or "",
                ram_gb=row.get("ram_gb"),
                storage_gb=row.get("storage_gb"),
                algeria_min_eur=row.get("algeria_min_eur"),
                algeria_avg_eur=row.get("algeria_avg_eur"),
                turkiye_min_eur=row.get("turkiye_min_eur"),
                turkiye_avg_eur=row.get("turkiye_avg_eur"),
                gross_margin_eur=row.get("margin_eur"),
                margin_percent=row.get("margin_percent"),
                algeria_count=row.get("algeria_count") or 0,
                turkiye_count=row.get("turkiye_count") or 0,
                algeria_urls=row.get("algeria_urls") or [],
                turkiye_urls=row.get("turkiye_urls") or [],
                recommendation=_snapshot_recommendation(row.get("recommendation")),
                confidence_score=int(round(float(row.get("confidence") or 0) * 100)),
                source_label=source_label,
                generated_at=generated_at,
            )
        )

    with transaction.atomic():
        deleted, _ = LaptopOpportunitySnapshot.objects.all().delete()
        LaptopOpportunitySnapshot.objects.bulk_create(snapshots, batch_size=500)
    return deleted, len(snapshots)


class Command(BaseCommand):
    help = "Preview clean laptop opportunities using LaptopListing only. Does not write opportunity snapshots."

    def add_arguments(self, parser):
        parser.add_argument("--min-margin-eur", default="0")
        parser.add_argument("--min-margin-percent", default="0")
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument(
            "--only-approved",
            action="store_true",
            help="Use only approved/auto LaptopListing rows; default includes needs_review too.",
        )
        parser.add_argument(
            "--loose",
            action="store_true",
            help="Allow looser matching for sparse data (skip CPU/GPU matching).",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print JSON instead of the terminal table.",
        )
        parser.add_argument(
            "--export-json",
            help="Optional path to save the computed rows as JSON.",
        )
        parser.add_argument(
            "--write-snapshots",
            action="store_true",
            help="Replace clean LaptopOpportunitySnapshot rows with the computed results.",
        )

    def handle(self, *args, **options):
        min_margin_eur = _decimal_option(options["min_margin_eur"])
        min_margin_percent = _decimal_option(options["min_margin_percent"])
        limit = options["limit"]
        if limit < 1:
            raise CommandError("--limit must be at least 1")

        rows = compute_laptop_opportunity_rows(
            min_margin_eur=min_margin_eur,
            min_margin_percent=min_margin_percent,
            limit=limit,
            only_approved=options["only_approved"],
            loose=options["loose"],
        )

        if options["write_snapshots"]:
            deleted, created = write_laptop_opportunity_snapshots(rows)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Wrote {created} clean laptop opportunity snapshots; replaced {deleted} old rows."
                )
            )

        json_rows = [_row_to_json(row) for row in rows]
        if options["export_json"]:
            path = Path(options["export_json"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(json_rows, ensure_ascii=False, indent=2), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Exported {len(rows)} rows to {path}"))

        if options["json"]:
            self.stdout.write(json.dumps(json_rows, ensure_ascii=False, indent=2))
            return

        self.stdout.write(self.style.SUCCESS(f"Clean laptop opportunity rows: {len(rows)}"))
        self.stdout.write(
            "Brand | Model | CPU | GPU | RAM | Storage | DZ min € | TR avg € | Margin € | Margin % | Counts"
        )
        self.stdout.write("-" * 140)
        for row in rows:
            cpu_short = (row["cpu"][:12] + "..") if len(row["cpu"]) > 14 else row["cpu"]
            gpu_short = (row["gpu"][:14] + "..") if len(row["gpu"]) > 16 else row["gpu"]
            self.stdout.write(
                f"{row['brand']} | {row['model'][:20]} | {cpu_short} | {gpu_short} | "
                f"{row['ram_gb'] or '?'}GB | {row['storage_gb'] or '?'}GB | "
                f"{row['algeria_min_eur']} | {row['turkiye_avg_eur']} | "
                f"{row['margin_eur']} | {row['margin_percent']}% | "
                f"{row['algeria_count']}/{row['turkiye_count']}"
            )

        if not options["write_snapshots"]:
            self.stdout.write(
                self.style.WARNING(
                    "Preview only: add --write-snapshots to update the clean laptop dashboard table."
                )
            )
