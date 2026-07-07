"""Audit DealSnapshots with NVIDIA Vision LLM to flag suspicious deals.

Usage:
    python manage.py audit_deals_with_llm --limit 10 --dry-run --no-image
    python manage.py audit_deals_with_llm --limit 20 --dry-run
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from market.models import DealSnapshot
from market.services.deal_sanity import _fetch_image_bytes, audit_deal


class Command(BaseCommand):
    help = "Audit deal snapshots using LLM to flag suspicious pricing."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20, help="Max deals to audit (default: 20)")
        parser.add_argument(
            "--min-margin-pct", type=float, default=30.0,
            help="Minimum margin%% to include (default: 30)",
        )
        parser.add_argument(
            "--dry-run", action="store_true", default=True,
            help="Dry-run: no DB writes (default behavior)",
        )
        parser.add_argument(
            "--no-image", action="store_true", default=False,
            help="Skip image fetching; audit from text/data only",
        )
        parser.add_argument(
            "--verbose", action="store_true", default=False,
            help="Print full deal data and raw LLM response",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        min_margin = options["min_margin_pct"]
        no_image = options["no_image"]
        verbose = options["verbose"]

        has_nvidia_key = bool(settings.NVIDIA_API_KEY)
        if not no_image and not has_nvidia_key:
            self.stderr.write(
                self.style.WARNING(
                    "NVIDIA_API_KEY not set. Falling back to --no-image mode."
                )
            )
            no_image = True

        # Select deals: high margin OR low sahibinden evidence
        from django.db.models import Q
        qs = DealSnapshot.objects.select_related("listing").order_by("-margin_pct")
        qs = qs.exclude(margin_pct__isnull=True)
        qs = qs.filter(Q(margin_pct__gte=min_margin) | Q(sah_count__lte=2))

        deals = []
        for d in qs:
            if len(deals) >= limit:
                break
            margin = d.margin_pct or 0
            sah = d.sah_count or 0
            if margin >= min_margin or sah <= 2:
                deals.append(d)

        if not deals:
            self.stdout.write(self.style.WARNING("No deals matched the filter criteria."))
            return

        self.stdout.write(
            self.style.NOTICE(
                f"Auditing {len(deals)} deals (min_margin={min_margin}%, "
                f"no_image={no_image})...\n"
            )
        )

        results = []
        for i, deal in enumerate(deals, 1):
            self.stdout.write(f"[{i}/{len(deals)}] {deal.brand_name} {deal.model_name} "
                              f"{deal.storage_gb or '?'}GB — margin {deal.margin_pct:.1f}%...")

            image_bytes, mime_type = None, None
            if not no_image:
                img_source = deal.image_url or ""
                if not img_source and deal.listing:
                    img_source = deal.listing.image_path or ""
                if img_source:
                    image_bytes, mime_type = _fetch_image_bytes(img_source)
                    if verbose and image_bytes:
                        self.stdout.write(f"  Image loaded: {len(image_bytes)} bytes ({mime_type})")
                    elif verbose:
                        self.stdout.write("  No image available")

            result = audit_deal(deal, image_bytes, mime_type)
            results.append((deal, result))

            verdict_style = {
                "keep": self.style.SUCCESS,
                "watch": self.style.WARNING,
                "reject": self.style.ERROR,
            }.get(result["verdict"], self.style.NOTICE)

            self.stdout.write(verdict_style(
                f"  → {result['verdict'].upper()} (conf {result['confidence']}%)"
            ))
            for reason in result["reasons"]:
                self.stdout.write(f"    - {reason}")
            self.stdout.write(f"    Action: {result['recommended_action']}")
            self.stdout.write("")

            # Polite rate limiting
            if i < len(deals):
                time.sleep(1)

        # Summary table
        self.stdout.write("\n" + "=" * 90)
        self.stdout.write("SUMMARY")
        self.stdout.write("=" * 90)
        self.stdout.write(
            f"{'ID':>4} {'Model':<30} {'Marg%':>6} {'EUR':>7} {'sah':>3} "
            f"{'Verdict':<8} {'Conf':>4}  Reasons"
        )
        self.stdout.write("-" * 90)
        for deal, res in results:
            model_str = f"{deal.brand_name} {deal.model_name} {deal.storage_gb or '?'}GB"
            if len(model_str) > 30:
                model_str = model_str[:27] + "..."
            reasons_str = "; ".join(res["reasons"][:2])
            if len(reasons_str) > 50:
                reasons_str = reasons_str[:47] + "..."
            self.stdout.write(
                f"{deal.id:>4} {model_str:<30} {deal.margin_pct:>5.1f}% "
                f"{deal.margin_eur:>6} {deal.sah_count:>3} "
                f"{res['verdict']:<8} {res['confidence']:>3}%  {reasons_str}"
            )

        # Counts
        keep = sum(1 for _, r in results if r["verdict"] == "keep")
        watch = sum(1 for _, r in results if r["verdict"] == "watch")
        reject = sum(1 for _, r in results if r["verdict"] == "reject")
        self.stdout.write(f"\nKeep: {keep}  Watch: {watch}  Reject: {reject}")
        self.stdout.write(self.style.SUCCESS("Done."))
