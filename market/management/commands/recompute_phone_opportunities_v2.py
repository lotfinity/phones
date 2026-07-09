import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Avg, Count, Min
from django.utils import timezone

from market.clean_models import PhoneOpportunitySnapshot
from market.models import (
    Country,
    DealSnapshot,
    OpportunitySnapshot,
    PhoneListing,
    SourceType,
)

VALID_PHONE_STORAGE_GB = (64, 128, 256, 512, 1024, 2048)
VISIBLE_REVIEW_STATUSES = (
    PhoneListing.ReviewStatus.AUTO,
    PhoneListing.ReviewStatus.APPROVED,
    PhoneListing.ReviewStatus.NEEDS_REVIEW,
)
APPROVED_REVIEW_STATUSES = (
    PhoneListing.ReviewStatus.AUTO,
    PhoneListing.ReviewStatus.APPROVED,
)


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
    converted = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            converted[key] = float(value)
        else:
            converted[key] = value
    return converted


def _recommendation_for_row(row):
    margin = row.get("gross_margin_eur") or Decimal("0")
    percent = row.get("margin_percent") or Decimal("0")
    algeria_count = int(row.get("algeria_count") or 0)
    turkiye_count = int(row.get("turkiye_count") or 0)

    if margin >= Decimal("150") and percent >= Decimal("20") and algeria_count >= 1 and turkiye_count >= 2:
        return PhoneOpportunitySnapshot.Recommendation.BUY
    if margin >= Decimal("50") and percent >= Decimal("10"):
        return PhoneOpportunitySnapshot.Recommendation.WATCH
    return PhoneOpportunitySnapshot.Recommendation.IGNORE


def _confidence_for_row(row):
    algeria_count = int(row.get("algeria_count") or 0)
    turkiye_count = int(row.get("turkiye_count") or 0)
    margin = row.get("gross_margin_eur") or Decimal("0")
    percent = row.get("margin_percent") or Decimal("0")

    score = min(algeria_count * 10, 35) + min(turkiye_count * 3, 35)
    if margin >= Decimal("100"):
        score += 10
    if percent >= Decimal("20"):
        score += 10
    if row.get("storage_gb"):
        score += 10
    return max(0, min(score, 100))


def compute_phone_opportunity_rows(
    *,
    min_margin_eur=Decimal("0"),
    min_margin_percent=Decimal("0"),
    limit=100,
    only_approved=False,
):
    review_statuses = APPROVED_REVIEW_STATUSES if only_approved else VISIBLE_REVIEW_STATUSES
    base = (
        PhoneListing.objects.select_related("phone_model", "phone_model__brand")
        .filter(
            price_eur__isnull=False,
            phone_model__isnull=False,
            storage_gb__in=VALID_PHONE_STORAGE_GB,
            review_status__in=review_statuses,
        )
    )

    algeria_groups = (
        base.filter(country=Country.ALGERIA)
        .values("phone_model_id", "storage_gb")
        .annotate(
            algeria_min_eur=Min("price_eur"),
            algeria_avg_eur=Avg("price_eur"),
            algeria_count=Count("id"),
        )
    )

    rows = []
    for group in algeria_groups:
        tr_stats = base.filter(
            country=Country.TURKIYE,
            source_type=SourceType.SAHIBINDEN,
            phone_model_id=group["phone_model_id"],
            storage_gb=group["storage_gb"],
        ).aggregate(
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

        sample = (
            base.filter(
                phone_model_id=group["phone_model_id"],
                storage_gb=group["storage_gb"],
            )
            .select_related("phone_model", "phone_model__brand")
            .first()
        )
        if not sample or not sample.phone_model:
            continue

        algeria_urls = list(
            base.filter(
                country=Country.ALGERIA,
                phone_model_id=group["phone_model_id"],
                storage_gb=group["storage_gb"],
            )
            .order_by("price_eur")
            .values_list("listing_url", flat=True)[:5]
        )
        turkiye_urls = list(
            base.filter(
                country=Country.TURKIYE,
                source_type=SourceType.SAHIBINDEN,
                phone_model_id=group["phone_model_id"],
                storage_gb=group["storage_gb"],
            )
            .order_by("price_eur")
            .values_list("listing_url", flat=True)[:5]
        )

        row = {
            "brand": sample.phone_model.brand.name if sample.phone_model.brand else "",
            "model": sample.phone_model.canonical_name,
            "phone_model_id": group["phone_model_id"],
            "storage_gb": group["storage_gb"],
            "algeria_min_eur": _money(algeria_min),
            "algeria_avg_eur": _money(group["algeria_avg_eur"]),
            "turkiye_min_eur": _money(tr_stats["turkiye_min_eur"]),
            "turkiye_avg_eur": _money(turkiye_avg),
            "gross_margin_eur": _money(gross_margin),
            "margin_percent": _percent(margin_percent),
            "algeria_count": group["algeria_count"],
            "turkiye_count": tr_stats["turkiye_count"],
            "algeria_urls": [url for url in algeria_urls if url],
            "turkiye_urls": [url for url in turkiye_urls if url],
        }
        row["recommendation"] = _recommendation_for_row(row)
        row["confidence_score"] = _confidence_for_row(row)
        rows.append(row)

    rows.sort(key=lambda item: (item["gross_margin_eur"], item["margin_percent"] or Decimal("0")), reverse=True)
    return rows[:limit]


def write_phone_opportunity_snapshots(rows, *, source_label="phone_v2"):
    generated_at = timezone.now()
    snapshots = []
    for row in rows:
        snapshots.append(
            PhoneOpportunitySnapshot(
                phone_model_id=row.get("phone_model_id"),
                brand=row.get("brand") or "",
                model=row.get("model") or "",
                storage_gb=row.get("storage_gb"),
                algeria_min_eur=row.get("algeria_min_eur"),
                algeria_avg_eur=row.get("algeria_avg_eur"),
                turkiye_min_eur=row.get("turkiye_min_eur"),
                turkiye_avg_eur=row.get("turkiye_avg_eur"),
                gross_margin_eur=row.get("gross_margin_eur"),
                margin_percent=row.get("margin_percent"),
                algeria_count=row.get("algeria_count") or 0,
                turkiye_count=row.get("turkiye_count") or 0,
                algeria_urls=row.get("algeria_urls") or [],
                turkiye_urls=row.get("turkiye_urls") or [],
                recommendation=row.get("recommendation") or PhoneOpportunitySnapshot.Recommendation.WATCH,
                confidence_score=row.get("confidence_score") or 0,
                source_label=source_label,
                generated_at=generated_at,
            )
        )

    with transaction.atomic():
        deleted, _ = PhoneOpportunitySnapshot.objects.all().delete()
        PhoneOpportunitySnapshot.objects.bulk_create(snapshots, batch_size=500)
    return deleted, len(snapshots)


class Command(BaseCommand):
    help = "Compute clean phone opportunities using PhoneListing. Can preview, export JSON, or write DB snapshots."

    def add_arguments(self, parser):
        parser.add_argument("--min-margin-eur", default="0")
        parser.add_argument("--min-margin-percent", default="0")
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument(
            "--only-approved",
            action="store_true",
            help="Use only approved/auto PhoneListing rows; default includes needs_review too.",
        )
        parser.add_argument(
            "--clear-legacy-cache",
            action="store_true",
            help="Delete old OpportunitySnapshot and DealSnapshot rows before computing.",
        )
        parser.add_argument(
            "--write-snapshots",
            action="store_true",
            help="Replace clean PhoneOpportunitySnapshot rows with the computed results.",
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

    def handle(self, *args, **options):
        min_margin_eur = _decimal_option(options["min_margin_eur"])
        min_margin_percent = _decimal_option(options["min_margin_percent"])
        limit = options["limit"]
        if limit < 1:
            raise CommandError("--limit must be at least 1")

        if options["clear_legacy_cache"]:
            before_opps = OpportunitySnapshot.objects.count()
            before_deals = DealSnapshot.objects.count()
            OpportunitySnapshot.objects.all().delete()
            DealSnapshot.objects.all().delete()
            self.stdout.write(
                self.style.WARNING(
                    f"Cleared legacy cache: OpportunitySnapshot {before_opps}->0, DealSnapshot {before_deals}->0"
                )
            )

        rows = compute_phone_opportunity_rows(
            min_margin_eur=min_margin_eur,
            min_margin_percent=min_margin_percent,
            limit=limit,
            only_approved=options["only_approved"],
        )

        if options["write_snapshots"]:
            deleted, created = write_phone_opportunity_snapshots(rows)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Wrote {created} clean phone opportunity snapshots; replaced {deleted} old rows."
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

        self.stdout.write(self.style.SUCCESS(f"Clean phone opportunity rows: {len(rows)}"))
        self.stdout.write(
            "Brand | Model | Storage | DZ min € | TR avg € | Margin € | Margin % | Counts | Rec | Conf"
        )
        self.stdout.write("-" * 130)
        for row in rows:
            self.stdout.write(
                f"{row['brand']} | {row['model']} | {row['storage_gb']}GB | "
                f"{row['algeria_min_eur']} | {row['turkiye_avg_eur']} | "
                f"{row['gross_margin_eur']} | {row['margin_percent']}% | "
                f"{row['algeria_count']}/{row['turkiye_count']} | "
                f"{row['recommendation']} | {row['confidence_score']}"
            )

        if not options["write_snapshots"]:
            self.stdout.write(
                self.style.WARNING(
                    "Preview only: add --write-snapshots to update the clean dashboard table."
                )
            )
