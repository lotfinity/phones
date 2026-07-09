"""Parse raw listings into ParsedListingCandidates."""

from django.core.management.base import BaseCommand, CommandError

from market.models import ParsedListingCandidate, RawListing
from market.services.parsing.candidate_builder import build_candidate


class Command(BaseCommand):
    help = "Parse RawListing rows into ParsedListingCandidates."

    def add_arguments(self, parser):
        parser.add_argument(
            "--category", choices=["phones", "laptops", "unknown"],
            help="Filter by category hint.",
        )
        parser.add_argument(
            "--source-type",
            help="Filter by source type (e.g. sahibinden, ouedkniss).",
        )
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--raw-id", type=int, help="Parse a single RawListing by ID.")
        parser.add_argument(
            "--reparse", action="store_true",
            help="Reparse already-parsed listings.",
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
            if options["category"]:
                qs = qs.filter(category_hint=options["category"])
            if options["source_type"]:
                qs = qs.filter(source_type=options["source_type"])

        qs = qs.order_by("-observed_at")[: options["limit"]]

        parsed_count = 0
        needs_review_count = 0
        high_conf_count = 0
        error_count = 0
        threshold = options["auto_approve_threshold"]

        for raw in qs.iterator():
            try:
                candidate, created = build_candidate(raw)
                parsed_count += 1
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
