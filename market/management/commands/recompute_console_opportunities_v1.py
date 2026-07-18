import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Avg, Count, Min
from django.utils import timezone

from market.clean_models import ConsoleOpportunitySnapshot
from market.models import ConsoleListing, Country, SourceType
from market.services.gain_split import attach_buyer_pricing, json_safe


VISIBLE_REVIEW_STATUSES = (
    ConsoleListing.ReviewStatus.AUTO,
    ConsoleListing.ReviewStatus.APPROVED,
    ConsoleListing.ReviewStatus.NEEDS_REVIEW,
)
APPROVED_REVIEW_STATUSES = (
    ConsoleListing.ReviewStatus.AUTO,
    ConsoleListing.ReviewStatus.APPROVED,
)
MIN_CONSOLE_PRICE_EUR = Decimal("100")
MAX_CONSOLE_PRICE_EUR = Decimal("2500")


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


def _confidence_score(algeria_count, turkiye_count, has_storage, has_chipset):
    score = 0.5 if algeria_count and turkiye_count else 0.0
    score += 0.15 if algeria_count >= 2 else 0.1 if algeria_count else 0
    score += 0.15 if turkiye_count >= 2 else 0.1 if turkiye_count else 0
    if has_storage:
        score += 0.1
    if has_chipset:
        score += 0.1
    return min(score, 1.0)


def _recommendation(margin_percent, confidence):
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
        "strong_buy": ConsoleOpportunitySnapshot.Recommendation.BUY,
        "good_opportunity": ConsoleOpportunitySnapshot.Recommendation.GOOD_OPPORTUNITY,
        "marginal": ConsoleOpportunitySnapshot.Recommendation.MARGINAL,
        "low_confidence": ConsoleOpportunitySnapshot.Recommendation.LOW_CONFIDENCE,
        "no_margin": ConsoleOpportunitySnapshot.Recommendation.NO_MARGIN,
        "no_data": ConsoleOpportunitySnapshot.Recommendation.IGNORE,
    }
    return mapping.get(value, ConsoleOpportunitySnapshot.Recommendation.WATCH)


def _eligible_queryset(qs):
    return (
        qs.filter(
            console_model__isnull=False,
            price_eur__isnull=False,
            price_eur__gte=MIN_CONSOLE_PRICE_EUR,
            price_eur__lte=MAX_CONSOLE_PRICE_EUR,
        )
        .exclude(storage_gb__isnull=True)
    )


def compute_console_opportunity_rows(
    *,
    min_margin_eur=Decimal("0"),
    min_margin_percent=Decimal("0"),
    limit=100,
    only_approved=False,
):
    review_statuses = APPROVED_REVIEW_STATUSES if only_approved else VISIBLE_REVIEW_STATUSES
    base = ConsoleListing.objects.select_related("console_model", "console_model__brand").filter(
        review_status__in=review_statuses,
    )
    base = _eligible_queryset(base)
    algeria_groups = (
        base.filter(country=Country.ALGERIA)
        .values("console_model_id", "chipset", "ram_gb", "storage_gb")
        .annotate(
            algeria_min_eur=Min("price_eur"),
            algeria_avg_eur=Avg("price_eur"),
            algeria_count=Count("id"),
        )
    )

    rows = []
    for group in algeria_groups:
        tr_filter = {
            "country": Country.TURKIYE,
            "source_type": SourceType.SAHIBINDEN,
            "console_model_id": group["console_model_id"],
            "storage_gb": group["storage_gb"],
        }
        if group["chipset"]:
            tr_filter["chipset__icontains"] = group["chipset"].split(" ")[-1]
        if group["ram_gb"]:
            tr_filter["ram_gb"] = group["ram_gb"]
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

        algeria_listing = base.filter(
            country=Country.ALGERIA,
            console_model_id=group["console_model_id"],
            storage_gb=group["storage_gb"],
        ).order_by("price_eur", "-observed_at", "-id").first()

        sample = base.filter(
            console_model_id=group["console_model_id"],
            storage_gb=group["storage_gb"],
        ).first()
        if not sample or not sample.console_model:
            continue

        confidence = _confidence_score(
            group["algeria_count"],
            tr_stats["turkiye_count"],
            has_storage=bool(group["storage_gb"]),
            has_chipset=bool(group["chipset"]),
        )
        algeria_urls = list(
            base.filter(
                country=Country.ALGERIA,
                console_model_id=group["console_model_id"],
                storage_gb=group["storage_gb"],
            ).order_by("price_eur").values_list("listing_url", flat=True)[:5]
        )
        turkiye_urls = list(
            base.filter(
                country=Country.TURKIYE,
                source_type=SourceType.SAHIBINDEN,
                console_model_id=group["console_model_id"],
                storage_gb=group["storage_gb"],
            ).order_by("price_eur").values_list("listing_url", flat=True)[:5]
        )
        row = {
            "brand": sample.console_model.brand.name if sample.console_model.brand else "",
            "model": sample.console_model.canonical_name,
            "console_model_id": group["console_model_id"],
            "algeria_listing_id": algeria_listing.pk if algeria_listing else None,
            "chipset": group["chipset"] or "",
            "ram_gb": group["ram_gb"],
            "storage_gb": group["storage_gb"],
            "algeria_min_eur": _money(algeria_min),
            "algeria_avg_eur": _money(group["algeria_avg_eur"]),
            "turkiye_min_eur": _money(tr_stats["turkiye_min_eur"]),
            "turkiye_avg_eur": _money(turkiye_avg),
            "margin_eur": _money(gross_margin),
            "margin_percent": _percent(margin_percent),
            "algeria_count": group["algeria_count"],
            "turkiye_count": tr_stats["turkiye_count"],
            "confidence": round(confidence, 2),
            "recommendation": _recommendation(margin_percent, confidence),
            "algeria_urls": [url for url in algeria_urls if url],
            "turkiye_urls": [url for url in turkiye_urls if url],
        }
        attach_buyer_pricing(row, margin_key="margin_eur")
        rows.append(row)

    rows.sort(key=lambda item: (item["margin_eur"] or Decimal("0"), item["margin_percent"] or Decimal("0")), reverse=True)
    return rows[:limit]


def write_console_opportunity_snapshots(rows, *, source_label="console_v1"):
    generated_at = timezone.now()
    seen_keys = set()
    written = 0
    with transaction.atomic():
        for row in rows:
            key = (
                row.get("console_model_id"),
                row.get("chipset") or "",
                row.get("ram_gb"),
                row.get("storage_gb"),
            )
            seen_keys.add(key)
            defaults = {
                "algeria_listing_id": row.get("algeria_listing_id"),
                "brand": row.get("brand") or "",
                "model": row.get("model") or "",
                "algeria_min_eur": row.get("algeria_min_eur"),
                "algeria_avg_eur": row.get("algeria_avg_eur"),
                "turkiye_min_eur": row.get("turkiye_min_eur"),
                "turkiye_avg_eur": row.get("turkiye_avg_eur"),
                "gross_margin_eur": row.get("margin_eur"),
                "margin_percent": row.get("margin_percent"),
                "algeria_count": row.get("algeria_count") or 0,
                "turkiye_count": row.get("turkiye_count") or 0,
                "algeria_urls": row.get("algeria_urls") or [],
                "turkiye_urls": row.get("turkiye_urls") or [],
                "recommendation": _snapshot_recommendation(row.get("recommendation")),
                "confidence_score": int(round(float(row.get("confidence") or 0) * 100)),
                "source_label": source_label,
                "generated_at": generated_at,
            }
            ConsoleOpportunitySnapshot.objects.update_or_create(
                console_model_id=key[0],
                chipset=key[1],
                ram_gb=key[2],
                storage_gb=key[3],
                defaults=defaults,
            )
            written += 1

        stale = ConsoleOpportunitySnapshot.objects.all()
        if seen_keys:
            stale_ids = [
                snapshot.pk
                for snapshot in stale.only("pk", "console_model_id", "chipset", "ram_gb", "storage_gb")
                if (
                    snapshot.console_model_id,
                    snapshot.chipset or "",
                    snapshot.ram_gb,
                    snapshot.storage_gb,
                ) not in seen_keys
            ]
            deleted, _ = ConsoleOpportunitySnapshot.objects.filter(pk__in=stale_ids).delete()
        else:
            deleted, _ = stale.delete()
    return deleted, written


class Command(BaseCommand):
    help = "Compute clean portable console opportunities using ConsoleListing."

    def add_arguments(self, parser):
        parser.add_argument("--min-margin-eur", default="0")
        parser.add_argument("--min-margin-percent", default="0")
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--only-approved", action="store_true")
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--export-json")
        parser.add_argument("--write-snapshots", action="store_true")

    def handle(self, *args, **options):
        rows = compute_console_opportunity_rows(
            min_margin_eur=_decimal_option(options["min_margin_eur"]),
            min_margin_percent=_decimal_option(options["min_margin_percent"]),
            limit=options["limit"],
            only_approved=options["only_approved"],
        )
        if options["write_snapshots"]:
            deleted, created = write_console_opportunity_snapshots(rows)
            self.stdout.write(self.style.SUCCESS(
                f"Wrote {created} clean console opportunity snapshots; removed {deleted} stale rows."
            ))
        json_rows = [_row_to_json(row) for row in rows]
        if options["export_json"]:
            path = Path(options["export_json"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(json_rows, ensure_ascii=False, indent=2), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Exported {len(rows)} rows to {path}"))
        if options["json"]:
            self.stdout.write(json.dumps(json_rows, ensure_ascii=False, indent=2))
            return
        self.stdout.write(self.style.SUCCESS(f"Clean console opportunity rows: {len(rows)}"))
        self.stdout.write("Brand | Model | Chipset | RAM | Storage | DZ min € | TR avg € | Margin € | Margin % | Counts")
        self.stdout.write("-" * 120)
        for row in rows:
            self.stdout.write(
                f"{row['brand']} | {row['model'][:22]} | {row['chipset'][:16]} | "
                f"{row['ram_gb'] or '?'}GB | {row['storage_gb'] or '?'}GB | "
                f"{row['algeria_min_eur']} | {row['turkiye_avg_eur']} | "
                f"{row['margin_eur']} | {row['margin_percent']}% | "
                f"{row['algeria_count']}/{row['turkiye_count']}"
            )
