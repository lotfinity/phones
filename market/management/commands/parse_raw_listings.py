"""Parse raw listings into ParsedListingCandidates."""

from decimal import InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from market.models import ParsedListingCandidate, RawListing
from market.services.parsing.candidate_builder import build_candidate


class Command(BaseCommand):
    help = "Parse RawListing rows into ParsedListingCandidates."

    def add_arguments(self, parser):
        parser.add_argument(
            "--category", choices=["phones", "laptops", "consoles", "unknown"],
            help="Filter by category hint.",
        )
        parser.add_argument(
            "--country",
            help="Filter by country (e.g. algeria, turkiye).",
        )
        parser.add_argument(
            "--source-type",
            help="Filter by source type (e.g. sahibinden, ouedkniss).",
        )
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--raw-id", type=int, help="Parse a single RawListing by ID.")
        parser.add_argument(
            "--reparse", action="store_true",
            help="Reparse already-parsed listings. With --category, also processes "
                 "rows with other category hints (so laptop detection can override phone hints).",
        )
        parser.add_argument(
            "--auto-approve-threshold", type=float, default=0.95,
            help="Auto-approve candidates above this confidence.",
        )

    def handle(self, *args, **options):
        qs = RawListing.objects.all()

        if options["raw_id"]:
            qs = qs.filter(pk=options["raw_id"])
        else:
            if not options["reparse"]:
                qs = qs.filter(parse_status=RawListing.ParseStatus.RAW)

            if options["country"]:
                qs = qs.filter(country=options["country"])
            if options["source_type"]:
                qs = qs.filter(source_type=options["source_type"])

            # Category filtering:
            # Without --reparse: only rows matching the category hint.
            # With --reparse: broaden to include rows that might be reclassified
            # (e.g. --category laptops also processes phones/unknown/accessories
            # so URL/title signals can override the hint).
            category = options["category"]
            if category and not options["reparse"]:
                qs = qs.filter(category_hint=category)
            elif category and options["reparse"]:
                if category == "laptops":
                    # Include laptop hints plus rows that may have been imported
                    # with the wrong hint, so signal detection can reclassify.
                    qs = qs.filter(category_hint__in=[
                        RawListing.CategoryHint.LAPTOPS,
                        RawListing.CategoryHint.PHONES,
                        RawListing.CategoryHint.UNKNOWN,
                    ])
                elif category == "phones":
                    qs = qs.filter(category_hint__in=[
                        RawListing.CategoryHint.PHONES,
                        RawListing.CategoryHint.UNKNOWN,
                    ])
                elif category == "consoles":
                    qs = qs.filter(category_hint__in=[
                        RawListing.CategoryHint.CONSOLES,
                        RawListing.CategoryHint.LAPTOPS,
                        RawListing.CategoryHint.PHONES,
                        RawListing.CategoryHint.UNKNOWN,
                    ])
                # "unknown" already matches everything.

        qs = qs.order_by("-observed_at")[: options["limit"]]

        parsed_count = 0
        needs_review_count = 0
        high_conf_count = 0
        error_count = 0
        laptop_created = 0
        laptop_updated = 0
        phone_created = 0
        phone_updated = 0
        accessory_count = 0
        console_created = 0
        console_updated = 0
        converted_count = 0
        repaired_corrupt_count = 0
        threshold = options["auto_approve_threshold"]

        for raw in qs.iterator():
            try:
                # Track old category for conversion detection.
                old_category = None
                try:
                    old_candidate = ParsedListingCandidate.objects.get(raw_listing=raw)
                    old_category = old_candidate.detected_category
                except ParsedListingCandidate.DoesNotExist:
                    pass
                except InvalidOperation:
                    self._repair_corrupt_candidate_decimals(raw.pk)
                    repaired_corrupt_count += 1

                try:
                    candidate, created = build_candidate(raw)
                except InvalidOperation:
                    self._repair_corrupt_candidate_decimals(raw.pk)
                    repaired_corrupt_count += 1
                    candidate, created = build_candidate(raw)
                parsed_count += 1

                if candidate.detected_category == ParsedListingCandidate.DetectedCategory.LAPTOP:
                    if created:
                        laptop_created += 1
                    else:
                        laptop_updated += 1
                    if old_category == ParsedListingCandidate.DetectedCategory.PHONE:
                        converted_count += 1
                elif candidate.detected_category == ParsedListingCandidate.DetectedCategory.PHONE:
                    if created:
                        phone_created += 1
                    else:
                        phone_updated += 1
                elif candidate.detected_category == ParsedListingCandidate.DetectedCategory.PORTABLE_CONSOLE:
                    if created:
                        console_created += 1
                    else:
                        console_updated += 1
                else:
                    accessory_count += 1

                if candidate.status == ParsedListingCandidate.Status.NEEDS_REVIEW:
                    needs_review_count += 1
                if candidate.confidence >= threshold:
                    high_conf_count += 1
            except Exception as exc:
                error_count += 1
                self.stderr.write(f"Error parsing raw_listing {raw.pk}: {exc}")

        self.stdout.write(self.style.SUCCESS(
            f"Done. Parsed: {parsed_count}, Needs review: {needs_review_count}, "
            f"High confidence (>= {threshold:.0%}): {high_conf_count}, "
            f"Errors: {error_count}"
        ))
        self.stdout.write(
            f"  Laptop: +{laptop_created} created, {laptop_updated} updated | "
            f"Phone: +{phone_created} created, {phone_updated} updated | "
            f"Console: +{console_created} created, {console_updated} updated | "
            f"Accessory/unknown: {accessory_count} | "
            f"Converted phone->laptop: {converted_count} | "
            f"Repaired corrupt decimals: {repaired_corrupt_count}"
        )

    def _repair_corrupt_candidate_decimals(self, raw_listing_id):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE market_parsedlistingcandidate
                SET price_original = NULL, price_eur = NULL
                WHERE raw_listing_id = %s
                """,
                [raw_listing_id],
            )
