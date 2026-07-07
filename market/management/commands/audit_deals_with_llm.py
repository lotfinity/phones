"""Audit DealSnapshots with NVIDIA Vision LLM to flag suspicious deals.

Usage:
    python manage.py audit_deals_with_llm --limit 10 --dry-run --no-image
    python manage.py audit_deals_with_llm --limit 20 --dry-run
    python manage.py audit_deals_with_llm --deal-id 483 --image-path /path/to/img.jpg --freeform-test
    python manage.py audit_deals_with_llm --deal-id 483 --image-path /path/to/img.jpg --vision-mode both --verbose
"""

import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from market.models import DealSnapshot
from market.services.deal_sanity import (
    _fetch_image_bytes,
    audit_deal,
    extract_red_flags,
    inspect_deal_image,
    inspect_deal_image_freeform,
)


class Command(BaseCommand):
    help = "Audit deal snapshots using LLM to flag suspicious pricing."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20, help="Max deals to audit (default: 20)")
        parser.add_argument("--deal-id", type=int, default=None, help="Audit a single deal by ID")
        parser.add_argument("--image-path", type=str, default=None, help="Override image path for the deal")
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
            help="Print full deal data, raw LLM responses, and image path used",
        )
        parser.add_argument(
            "--vision-only-test", action="store_true", default=False,
            help="Run only the structured vision inspection, skip final verdict",
        )
        parser.add_argument(
            "--freeform-test", action="store_true", default=False,
            help="Run only the free-form vision description, skip final verdict",
        )
        parser.add_argument(
            "--vision-mode", type=str, default="both",
            choices=["structured", "freeform", "both"],
            help="Which vision layers to use (default: both)",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        min_margin = options["min_margin_pct"]
        no_image = options["no_image"]
        verbose = options["verbose"]
        vision_only_test = options["vision_only_test"]
        freeform_test = options["freeform_test"]
        vision_mode = options["vision_mode"]
        deal_id = options["deal_id"]
        image_path_override = options["image_path"]

        has_nvidia_key = bool(settings.NVIDIA_API_KEY)
        if not no_image and not has_nvidia_key:
            self.stderr.write(
                self.style.WARNING(
                    "NVIDIA_API_KEY/NVIDIA_NIM_API_KEY is missing; "
                    "run with --no-image or set the key."
                )
            )
            no_image = True

        test_mode = vision_only_test or freeform_test

        # ── Single-deal mode (--deal-id) ──
        if deal_id is not None:
            try:
                deal = DealSnapshot.objects.select_related("listing").get(id=deal_id)
            except DealSnapshot.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"DealSnapshot {deal_id} not found."))
                return

            self.stdout.write(
                self.style.NOTICE(
                    f"Auditing deal {deal.id}: {deal.brand_name} {deal.model_name} "
                    f"{deal.storage_gb or '?'}GB — margin {deal.margin_pct:.1f}%\n"
                )
            )

            # Resolve image source
            if image_path_override:
                img_source = image_path_override
                p = Path(img_source)
                if not p.exists():
                    self.stderr.write(self.style.ERROR(f"Image not found: {img_source}"))
                    return
            else:
                img_source = deal.image_url or ""
                if not img_source and deal.listing:
                    img_source = deal.listing.image_path or ""

            image_bytes, mime_type = None, None
            if not no_image and img_source:
                image_bytes, mime_type = _fetch_image_bytes(img_source)

            if verbose:
                self.stdout.write(f"  Image source: {img_source}")
                if image_bytes:
                    self.stdout.write(f"  Image loaded: {len(image_bytes)} bytes ({mime_type})")
                else:
                    self.stdout.write("  No image loaded")

            if no_image or not image_bytes:
                if vision_only_test or freeform_test:
                    self.stdout.write(self.style.WARNING("  No image available for vision test."))
                    return

            # ── Vision-only test ──
            if vision_only_test:
                vision = inspect_deal_image(deal, image_bytes, mime_type)
                if verbose:
                    self.stdout.write("  [RAW STRUCTURED RESPONSE]")
                    self.stdout.write(f"    {vision}")
                self._print_structured_vision(vision)
                return

            # ── Freeform-only test ──
            if freeform_test:
                ff = inspect_deal_image_freeform(deal, image_bytes, mime_type)
                if verbose:
                    self.stdout.write("  [RAW FREEFORM RESPONSE]")
                    for line in ff.split("\n"):
                        self.stdout.write(f"    {line}")
                self._print_freeform(ff)
                return

            # ── Full audit ──
            structured = None
            freeform_text = None

            if image_bytes and vision_mode in ("structured", "both"):
                structured = inspect_deal_image(deal, image_bytes, mime_type)
                if verbose:
                    self.stdout.write("  [RAW STRUCTURED]")
                    self.stdout.write(f"    {structured}")

            if image_bytes and vision_mode in ("freeform", "both"):
                freeform_text = inspect_deal_image_freeform(deal, image_bytes, mime_type)
                if verbose:
                    self.stdout.write("  [RAW FREEFORM]")
                    for line in freeform_text.split("\n"):
                        self.stdout.write(f"    {line}")

            # Red-flag scan
            all_text = ""
            if structured:
                all_text += " " + structured.get("all_visible_text", "")
                all_text += " " + " ".join(structured.get("visible_notes", []))
            if freeform_text:
                all_text += " " + freeform_text
            red_flags = extract_red_flags(all_text)
            if verbose and red_flags:
                self.stdout.write(f"  [RED FLAGS] {red_flags}")

            result = audit_deal(deal, image_bytes, mime_type,
                                structured_vision=structured,
                                freeform_text=freeform_text)

            verdict_style = {
                "keep": self.style.SUCCESS,
                "watch": self.style.WARNING,
                "reject": self.style.ERROR,
            }.get(result["verdict"], self.style.NOTICE)

            self.stdout.write(verdict_style(
                f"  -> {result['verdict'].upper()} (conf {result['confidence']}%)"
            ))
            for reason in result["reasons"]:
                self.stdout.write(f"    - {reason}")
            self.stdout.write(f"    Action: {result['recommended_action']}")
            return

        # ── Bulk mode ──
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

        mode_label = "vision-only" if vision_only_test else (
            "freeform-only" if freeform_test else f"vision_mode={vision_mode}"
        )
        self.stdout.write(
            self.style.NOTICE(
                f"Auditing {len(deals)} deals (min_margin={min_margin}%, "
                f"no_image={no_image}, {mode_label})...\n"
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

            if no_image or not image_bytes:
                if vision_only_test or freeform_test:
                    self.stdout.write(self.style.WARNING(
                        "  Skipping: no image available for vision test"
                    ))
                    continue

            if vision_only_test:
                vision = inspect_deal_image(deal, image_bytes, mime_type)
                self._print_structured_vision(vision)
                results.append((deal, {"verdict": "watch", "confidence": 0,
                                       "reasons": ["vision-only test"],
                                       "recommended_action": "N/A"}, vision, ""))
                if i < len(deals):
                    time.sleep(1)
                continue

            if freeform_test:
                ff = inspect_deal_image_freeform(deal, image_bytes, mime_type)
                self._print_freeform(ff)
                results.append((deal, {"verdict": "watch", "confidence": 0,
                                       "reasons": ["freeform-only test"],
                                       "recommended_action": "N/A"}, None, ff))
                if i < len(deals):
                    time.sleep(1)
                continue

            structured = None
            freeform_text = None

            if image_bytes and vision_mode in ("structured", "both"):
                structured = inspect_deal_image(deal, image_bytes, mime_type)
                if verbose:
                    self._print_structured_vision(structured)

            if image_bytes and vision_mode in ("freeform", "both"):
                freeform_text = inspect_deal_image_freeform(deal, image_bytes, mime_type)
                if verbose:
                    self._print_freeform(freeform_text)

            result = audit_deal(deal, image_bytes, mime_type,
                                structured_vision=structured,
                                freeform_text=freeform_text)
            results.append((deal, result, structured, freeform_text or ""))

            verdict_style = {
                "keep": self.style.SUCCESS,
                "watch": self.style.WARNING,
                "reject": self.style.ERROR,
            }.get(result["verdict"], self.style.NOTICE)

            self.stdout.write(verdict_style(
                f"  -> {result['verdict'].upper()} (conf {result['confidence']}%)"
            ))
            for reason in result["reasons"][:5]:
                self.stdout.write(f"    - {reason}")
            self.stdout.write(f"    Action: {result['recommended_action']}")
            self.stdout.write("")

            if i < len(deals):
                time.sleep(1)

        if not test_mode:
            self._print_summary(results)

        self.stdout.write(self.style.SUCCESS("Done."))

    def _print_structured_vision(self, vision):
        """Print structured vision inspection."""
        cond = vision.get("condition_visible", "?")
        screen = vision.get("screen_damage", "?")
        body = vision.get("body_damage", "?")
        back = vision.get("back_damage", "?")
        cam = vision.get("camera_damage", "?")
        scratches = vision.get("scratches_or_scuffs", "?")
        visible = vision.get("visible_product", False)
        conf = vision.get("vision_confidence", 0)
        notes = vision.get("visible_notes", [])
        box_vis = vision.get("box_or_accessories_visible", "?")
        model_text = vision.get("model_text_visible", "")
        all_text = vision.get("all_visible_text", "")

        tag = "visible" if visible else "NOT_VISIBLE"
        self.stdout.write(
            f"  [STRUCTURED] product={tag} cond={cond} "
            f"screen={screen} body={body} back={back} cam={cam} "
            f"scratches={scratches} box={box_vis} conf={conf}%"
        )
        if model_text:
            self.stdout.write(f"    model_text: {model_text}")
        if all_text:
            self.stdout.write(f"    all_text: {all_text[:300]}")
        for n in notes[:5]:
            self.stdout.write(f"    note: {n}")

    def _print_freeform(self, text):
        """Print freeform vision description."""
        lines = text.split("\n") if text else []
        self.stdout.write("  [FREEFORM]")
        for line in lines[:10]:
            self.stdout.write(f"    {line}")
        if len(lines) > 10:
            self.stdout.write(f"    ... ({len(lines) - 10} more lines)")

    def _print_summary(self, results):
        """Print summary table."""
        self.stdout.write("\n" + "=" * 90)
        self.stdout.write("SUMMARY")
        self.stdout.write("=" * 90)
        self.stdout.write(
            f"{'ID':>4} {'Model':<30} {'Marg%':>6} {'EUR':>7} {'sah':>3} "
            f"{'Verdict':<8} {'Conf':>4}  Reasons"
        )
        self.stdout.write("-" * 90)
        for deal, res, _struct, _ff in results:
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

        keep = sum(1 for _, r, _, _ in results if r["verdict"] == "keep")
        watch = sum(1 for _, r, _, _ in results if r["verdict"] == "watch")
        reject = sum(1 for _, r, _, _ in results if r["verdict"] == "reject")
        self.stdout.write(f"\nKeep: {keep}  Watch: {watch}  Reject: {reject}")
