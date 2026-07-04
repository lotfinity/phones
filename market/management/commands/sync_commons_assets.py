import time

from django.core.management.base import BaseCommand

from market.models import Brand, ProductModel
from market.services.commons import sync_asset_for_product_model


class Command(BaseCommand):
    help = "Sync model/series logos from Wikimedia Commons for ProductModel rows."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0, help="Process at most N product models.")
        parser.add_argument("--model-id", type=int, default=0, help="Process a single ProductModel by ID.")
        parser.add_argument("--brand", type=str, default="", help="Only process models for this brand name.")
        parser.add_argument("--dry-run", action="store_true", help="Search and rank but do not save/download.")
        parser.add_argument("--force", action="store_true", help="Re-check models even if they already have an active primary asset.")
        parser.add_argument("--min-score", type=int, default=70, help="Minimum score to auto-save. Default: 70.")
        parser.add_argument("--save-weak", action="store_true", help="Save weak matches as manual_review.")
        parser.add_argument("--asset-type", type=str, default="model_logo", help="Asset type to assign. Default: model_logo.")
        parser.add_argument("--sleep", type=float, default=0.5, help="Delay between API calls in seconds.")
        parser.add_argument("--verbose", action="store_true", help="Print detailed per-model output.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]
        min_score = options["min_score"]
        save_weak = options["save_weak"]
        asset_type = options["asset_type"]
        sleep_between = options["sleep"]
        verbose = options["verbose"]
        limit = options["limit"]
        model_id = options["model_id"]
        brand_filter = options["brand"].strip()

        self.stdout.write(self.style.NOTICE("PriceBridge Commons Asset Sync"))
        self.stdout.write(f"  dry_run={dry_run}, force={force}, min_score={min_score}, save_weak={save_weak}")
        self.stdout.write(f"  asset_type={asset_type}, sleep={sleep_between}")
        self.stdout.write("")

        qs = ProductModel.objects.select_related("brand").order_by("canonical_name")
        if model_id:
            qs = qs.filter(pk=model_id)
        elif brand_filter:
            qs = qs.filter(brand__name__icontains=brand_filter)
        if limit:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(f"Processing {total} product model(s)...")
        self.stdout.write("")

        stats = {
            "matched": 0,
            "weak": 0,
            "no_match": 0,
            "failed": 0,
            "saved": 0,
            "skipped": 0,
            "dry_run_saved": 0,
        }
        failures = []
        processed = 0

        for pm in qs:
            processed += 1
            brand_label = pm.brand.name if pm.brand else "no-brand"
            self.stdout.write(f"[{processed}/{total}] {pm.canonical_name} ({brand_label})")

            result = sync_asset_for_product_model(pm, options={
                "dry_run": dry_run,
                "min_score": min_score,
                "save_weak": save_weak,
                "asset_type": asset_type,
                "sleep": sleep_between,
                "force": force,
                "verbose": verbose,
            })

            status = result.get("status", "")
            score = result.get("score", 0)
            query = result.get("query", "")
            candidate = result.get("candidate", {})
            reasons = result.get("reasons", [])
            match_status = result.get("match_status", "")

            if verbose:
                self.stdout.write(f"  query: {query}")
                if candidate:
                    self.stdout.write(f"  candidate: {candidate.get('title', '?')} score={score} reasons={reasons}")
                self.stdout.write(f"  status: {status} match_status={match_status}")

            if status == "skipped":
                stats["skipped"] += 1
                self.stdout.write(self.style.WARNING(f"  -> skipped ({result.get('reason', '')})"))
            elif status == "saved":
                stats["saved"] += 1
                if match_status == "matched":
                    stats["matched"] += 1
                elif match_status in ("weak_match", "manual_review"):
                    stats["weak"] += 1
                asset = result.get("asset")
                local = asset.local_file if asset else "n/a"
                self.stdout.write(self.style.SUCCESS(f"  -> saved ({match_status}, score={score}, local={local})"))
            elif status == "dry_run":
                stats["dry_run_saved"] += 1
                if match_status == "matched":
                    stats["matched"] += 1
                elif match_status in ("weak_match", "manual_review"):
                    stats["weak"] += 1
                ii = result.get("imageinfo", {})
                self.stdout.write(self.style.NOTICE(
                    f"  -> dry_run ({match_status}, score={score}, mime={ii.get('mime', '?')}, "
                    f"url={ii.get('url', '?')[:80]})"
                ))
            elif status == "no_match":
                stats["no_match"] += 1
                self.stdout.write(self.style.WARNING(f"  -> no_match (score={score})"))
                failures.append({"model": pm.canonical_name, "reason": result.get("reason", ""), "score": score})
            elif status == "failed":
                stats["failed"] += 1
                self.stdout.write(self.style.ERROR(f"  -> failed ({result.get('reason', '')})"))
                failures.append({"model": pm.canonical_name, "reason": result.get("reason", ""), "score": score})
            else:
                stats["failed"] += 1
                failures.append({"model": pm.canonical_name, "reason": f"unknown_status: {status}", "score": score})

            self.stdout.write("")

        self.stdout.write("=" * 60)
        self.stdout.write(self.style.NOTICE("REPORT"))
        self.stdout.write(f"  Models processed:       {total}")
        self.stdout.write(f"  Matched:                {stats['matched']}")
        self.stdout.write(f"  Weak/manual review:     {stats['weak']}")
        self.stdout.write(f"  No match:               {stats['no_match']}")
        self.stdout.write(f"  Failed:                 {stats['failed']}")
        self.stdout.write(f"  Saved (downloaded):     {stats['saved']}")
        self.stdout.write(f"  Skipped (existing):     {stats['skipped']}")
        self.stdout.write(f"  Dry-run candidates:     {stats['dry_run_saved']}")
        self.stdout.write("")

        if failures:
            self.stdout.write(self.style.WARNING("TOP FAILED EXAMPLES:"))
            for f in failures[:10]:
                self.stdout.write(f"  - {f['model']}: {f['reason']} (score={f['score']})")
            self.stdout.write("")

        self.stdout.write(self.style.NOTICE("Done."))
