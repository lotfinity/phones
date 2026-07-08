"""Audit listing condition via vision model.

Deal mode (phones, from DealSnapshot):
    python manage.py audit_deals_with_llm --limit 10 --dry-run --no-image
    python manage.py audit_deals_with_llm --deal-id 483 --image-path /path/to/img.jpg --write --verbose
    python manage.py audit_deals_with_llm --limit 28 --write

Listing mode (any MarketListing, e.g. laptops):
    python manage.py audit_deals_with_llm --product-type laptop --model MacBook --write
    python manage.py audit_deals_with_llm --source-type ouedkniss --product-type laptop --only-unaudited --limit 50 --write
    python manage.py audit_deals_with_llm --listing-ids 3389,3379 --product-type laptop --write --verbose
"""

import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from market.models import DealSnapshot, MarketListing
from market.services.deal_sanity import (
    _fetch_image_bytes,
    inspect_listing_metadata_and_condition,
    save_condition_audit,
)


class _ListingAuditTarget:
    """Adapt a MarketListing to the deal-like interface expected by
    inspect_listing_metadata_and_condition / save_condition_audit.

    Those helpers read deal.brand_name / model_name / storage_gb / title /
    condition / source_name / source_code / image_url and write the audit via
    deal.listing (the MarketListing the audit is attached to).
    """

    def __init__(self, listing):
        self.listing = listing
        self._l = listing

    @property
    def brand_name(self):
        pm = self._l.product_model
        if pm and pm.brand:
            return pm.brand.name
        if self._l.brand:
            return self._l.brand.name
        return "Unknown"

    @property
    def model_name(self):
        pm = self._l.product_model
        return pm.canonical_name if pm else "Unknown"

    @property
    def storage_gb(self):
        return self._l.storage_gb

    @property
    def title(self):
        return self._l.title_raw

    @property
    def condition(self):
        return self._l.condition or self._l.box_status or "unknown"

    @property
    def source_name(self):
        return self._l.source.name if self._l.source else ""

    @property
    def source_code(self):
        return self._l.source_type

    @property
    def image_url(self):
        return self._l.image_path


CONDITION_LABELS = {
    "brand_new_closed_box": "Kapalı Kutu",
    "used_clean": "Temiz İkinci El",
    "used_repaired_or_needs_repair": "Tamirli / Sorunlu",
    "unknown": "Belirsiz",
}


class Command(BaseCommand):
    help = "Inspect listing images and classify device condition."

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
            help="Print raw LLM JSON and full detail",
        )
        parser.add_argument(
            "--write", action="store_true", default=False,
            help="Save ListingConditionAudit to DB for each audited deal",
        )
        parser.add_argument(
            "--listing-ids", type=str, default=None,
            help="Comma-separated MarketListing IDs to audit (listing mode).",
        )
        parser.add_argument(
            "--source-type", type=str, default=None,
            help="Filter listings by source_type (ouedkniss/sahibinden/instagram).",
        )
        parser.add_argument(
            "--product-type", type=str, default=None,
            help="Filter listings by product_type slug (e.g. laptop, phone, tablet). "
                 "Also sets the vision prompt cues (laptop vs phone).",
        )
        parser.add_argument(
            "--model", type=str, default=None,
            help="Filter listings by ProductModel canonical_name substring.",
        )
        parser.add_argument(
            "--only-unaudited", action="store_true", default=False,
            help="Skip listings that already have a ListingConditionAudit.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        min_margin = options["min_margin_pct"]
        no_image = options["no_image"]
        verbose = options["verbose"]
        write = options["write"]
        deal_id = options["deal_id"]
        image_path_override = options["image_path"]
        listing_ids = options["listing_ids"]
        source_type = options["source_type"]
        product_type = options["product_type"]
        model_filter = options["model"]
        only_unaudited = options["only_unaudited"]

        has_nvidia_key = bool(settings.NVIDIA_API_KEY)
        if not no_image and not has_nvidia_key:
            self.stderr.write(
                self.style.WARNING(
                    "NVIDIA_API_KEY is missing; run with --no-image or set the key."
                )
            )
            no_image = True

        # ── Listing mode (audit MarketListing rows directly) ──
        if listing_ids or source_type or product_type or model_filter:
            self._run_listing_mode(
                listing_ids=listing_ids,
                source_type=source_type,
                product_type=product_type,
                model_filter=model_filter,
                only_unaudited=only_unaudited,
                limit=limit,
                no_image=no_image,
                verbose=verbose,
                write=write,
                has_nvidia_key=has_nvidia_key,
            )
            return

        # ── Single-deal mode ──
        if deal_id is not None:
            try:
                deal = DealSnapshot.objects.select_related("listing").get(id=deal_id)
            except DealSnapshot.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"DealSnapshot {deal_id} not found."))
                return

            self.stdout.write(
                self.style.NOTICE(
                    f"Inspecting deal {deal.id}: {deal.brand_name} {deal.model_name} "
                    f"{deal.storage_gb or '?'}GB\n"
                )
            )

            # Resolve image
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
                # Fall back to listing.image_path if image_url failed
                if not image_bytes and deal.listing and deal.listing.image_path:
                    image_bytes, mime_type = _fetch_image_bytes(deal.listing.image_path)

            if verbose:
                self.stdout.write(f"  Image: {img_source}")
                if image_bytes:
                    self.stdout.write(f"  Loaded: {len(image_bytes)} bytes ({mime_type})")
                else:
                    self.stdout.write("  No image loaded")

            # Run inspection
            result, error = inspect_listing_metadata_and_condition(
                deal, image_bytes, mime_type
            )
            if error:
                self.stderr.write(self.style.ERROR(f"  Error: {error}"))
                return

            self._print_result(result, verbose=verbose)

            if write and deal.listing:
                model_used = settings.NVIDIA_VISION_MODEL if has_nvidia_key else "text-only"
                audit, created = save_condition_audit(
                    deal, result, image_source=img_source, model_used=model_used,
                )
                status = "CREATED" if created else "UPDATED"
                label = CONDITION_LABELS.get(audit.condition_class, audit.condition_class)
                self.stdout.write(f"  [{status}] condition_class={audit.condition_class} label_tr={label}")
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

        self.stdout.write(
            self.style.NOTICE(
                f"Inspecting {len(deals)} deals (min_margin={min_margin}%, "
                f"no_image={no_image}, write={write})...\n"
            )
        )

        counts = {"brand_new_closed_box": 0, "used_clean": 0, "used_repaired_or_needs_repair": 0, "unknown": 0}

        for i, deal in enumerate(deals, 1):
            self.stdout.write(f"[{i}/{len(deals)}] {deal.brand_name} {deal.model_name} "
                              f"{deal.storage_gb or '?'}GB...")

            img_source = deal.image_url or ""
            if not img_source and deal.listing:
                img_source = deal.listing.image_path or ""

            image_bytes, mime_type = None, None
            if not no_image and img_source:
                image_bytes, mime_type = _fetch_image_bytes(img_source)
                # Fall back to listing.image_path if image_url failed
                if not image_bytes and deal.listing and deal.listing.image_path:
                    image_bytes, mime_type = _fetch_image_bytes(deal.listing.image_path)
                if verbose and image_bytes:
                    self.stdout.write(f"  Image: {len(image_bytes)} bytes ({mime_type})")
                elif verbose:
                    self.stdout.write("  No image available")

            result, error = inspect_listing_metadata_and_condition(
                deal, image_bytes, mime_type
            )
            if error:
                self.stdout.write(self.style.ERROR(f"  Error: {error}"))
                if i < len(deals):
                    time.sleep(1)
                continue

            self._print_result(result, verbose=verbose)

            cc = result.get("condition_class", "unknown")
            counts[cc] = counts.get(cc, 0) + 1

            if write and deal.listing:
                model_used = settings.NVIDIA_VISION_MODEL if has_nvidia_key else "text-only"
                audit, created = save_condition_audit(
                    deal, result, image_source=img_source, model_used=model_used,
                )
                status = "CREATED" if created else "UPDATED"
                label = CONDITION_LABELS.get(audit.condition_class, audit.condition_class)
                self.stdout.write(f"  [{status}] {audit.condition_class} = {label}")

            if i < len(deals):
                time.sleep(1)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Condition class summary:"))
        for cc, n in sorted(counts.items()):
            label = CONDITION_LABELS.get(cc, cc)
            self.stdout.write(f"  {label} ({cc}): {n}")
        self.stdout.write(self.style.SUCCESS("Done."))

    def _inspect_and_save(self, target, *, no_image, verbose, write, has_nvidia_key,
                          product_type="phone", image_override=None):
        """Resolve image, run vision inspection, optionally save the audit.

        Returns (audit, created, result, error).
        """
        img_source = image_override or target.image_url or ""
        if not img_source and target.listing:
            img_source = target.listing.image_path or ""

        image_bytes, mime_type = None, None
        if not no_image and img_source:
            image_bytes, mime_type = _fetch_image_bytes(img_source)
            # Fall back to listing.image_path if image_url failed
            if not image_bytes and target.listing and target.listing.image_path:
                image_bytes, mime_type = _fetch_image_bytes(target.listing.image_path)
        if verbose:
            if image_bytes:
                self.stdout.write(f"  Image: {len(image_bytes)} bytes ({mime_type})")
            else:
                self.stdout.write("  No image loaded")

        result, error = inspect_listing_metadata_and_condition(
            target, image_bytes, mime_type, product_type=product_type
        )
        if error:
            return None, False, None, error

        self._print_result(result, verbose=verbose)

        if write and target.listing:
            model_used = settings.NVIDIA_VISION_MODEL if has_nvidia_key else "text-only"
            audit, created = save_condition_audit(
                target, result, image_source=img_source, model_used=model_used,
            )
            return audit, created, result, None
        return None, False, result, None

    def _run_listing_mode(self, *, listing_ids, source_type, product_type, model_filter,
                          only_unaudited, limit, no_image, verbose, write, has_nvidia_key):
        from django.db.models import Q

        qs = MarketListing.objects.select_related(
            "product_model__brand", "source", "condition_audit"
        )
        if listing_ids:
            ids = [int(x.strip()) for x in listing_ids.split(",") if x.strip()]
            qs = qs.filter(id__in=ids)
        if source_type:
            qs = qs.filter(source_type=source_type)
        if product_type:
            qs = qs.filter(product_model__product_type__slug=product_type)
        if model_filter:
            qs = qs.filter(product_model__canonical_name__icontains=model_filter)
        if only_unaudited:
            qs = qs.filter(condition_audit__isnull=True)
        qs = qs.order_by("id")[:limit]

        listings = list(qs)
        if not listings:
            self.stdout.write(self.style.WARNING("No listings matched the filter criteria."))
            return

        self.stdout.write(
            self.style.NOTICE(
                f"Inspecting {len(listings)} listings (source={source_type or 'any'}, "
                f"product_type={product_type or 'any'}, model~{model_filter or 'any'}, "
                f"no_image={no_image}, write={write})...\n"
            )
        )

        counts = {"brand_new_closed_box": 0, "used_clean": 0,
                  "used_repaired_or_needs_repair": 0, "unknown": 0}
        pt = product_type or "phone"

        for i, listing in enumerate(listings, 1):
            target = _ListingAuditTarget(listing)
            self.stdout.write(
                f"[{i}/{len(listings)}] {target.brand_name} {target.model_name} "
                f"{target.storage_gb or '?'}GB (listing {listing.id})..."
            )

            audit, created, result, error = self._inspect_and_save(
                target, no_image=no_image, verbose=verbose, write=write,
                has_nvidia_key=has_nvidia_key, product_type=pt,
            )
            if error:
                self.stdout.write(self.style.ERROR(f"  Error: {error}"))
                if i < len(listings):
                    time.sleep(1)
                continue

            cc = (result or {}).get("condition_class", "unknown")
            counts[cc] = counts.get(cc, 0) + 1

            if write and audit:
                status = "CREATED" if created else "UPDATED"
                label = CONDITION_LABELS.get(audit.condition_class, audit.condition_class)
                self.stdout.write(f"  [{status}] {audit.condition_class} = {label}")

            if i < len(listings):
                time.sleep(1)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Condition class summary:"))
        for cc, n in sorted(counts.items()):
            label = CONDITION_LABELS.get(cc, cc)
            self.stdout.write(f"  {label} ({cc}): {n}")
        self.stdout.write(self.style.SUCCESS("Done."))

    def _print_result(self, result, verbose=False):
        cc = result.get("condition_class", "unknown")
        conf = result.get("confidence", 0)
        note = result.get("condition_note", "")
        label = CONDITION_LABELS.get(cc, cc)

        style = {
            "brand_new_closed_box": self.style.SUCCESS,
            "used_clean": self.style.SUCCESS,
            "used_repaired_or_needs_repair": self.style.ERROR,
            "unknown": self.style.WARNING,
        }.get(cc, self.style.NOTICE)

        self.stdout.write(style(f"  -> {label} ({cc}) conf={conf}%"))
        if note:
            self.stdout.write(f"    Note: {note}")

        if verbose:
            mc = result.get("metadata_check", {})
            corr = mc.get("corrections", {})
            if corr:
                self.stdout.write(f"    Corrections: {corr}")
            missing = mc.get("missing_visible_info", [])
            if missing:
                self.stdout.write(f"    Missing info: {missing}")
            vt = result.get("visible_text", {})
            all_text = vt.get("all_text", "")
            if all_text:
                self.stdout.write(f"    Visible text: {all_text[:200]}")
