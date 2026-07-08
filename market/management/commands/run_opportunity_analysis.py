from django.core.management.base import BaseCommand

from market.services.opportunity import run_analysis


class Command(BaseCommand):
    help = "Create opportunity snapshots from market listings and supplier prices."

    def add_arguments(self, parser):
        parser.add_argument(
            "--include-insufficient",
            action="store_true",
            help="Also create one-sided insufficient-data snapshots for coverage/debugging.",
        )
        parser.add_argument(
            "--include-cross-storage",
            action="store_true",
            help="Also create lower-confidence model-level cross-storage snapshots for debugging.",
        )
        parser.add_argument(
            "--require-clean-condition",
            action="store_true",
            help="Only use Algeria listings with condition_audit in sealed_new/clean_used.",
        )

    def handle(self, *args, **options):
        require_clean = options["require_clean_condition"]

        if require_clean:
            from market.models import ListingConditionAudit
            clean_count = ListingConditionAudit.objects.filter(
                condition_class__in=[
                    ListingConditionAudit.ConditionClass.SEALED_NEW,
                    ListingConditionAudit.ConditionClass.CLEAN_USED,
                ]
            ).count()
            total_audits = ListingConditionAudit.objects.count()
            self.stdout.write(
                f"Clean-condition filter active: {clean_count} clean audits "
                f"out of {total_audits} total audits."
            )

        created = run_analysis(
            include_insufficient=options["include_insufficient"],
            include_cross_storage=options["include_cross_storage"],
            require_clean_condition=require_clean,
        )
        self.stdout.write(self.style.SUCCESS(f"Created {created} opportunity snapshots."))

        # Also recompute deal snapshots (cached deals for fast page loads)
        from django.db import transaction
        from market.models import DealSnapshot
        from market.management.commands.recompute_deal_snapshots import compute_deal_snapshots

        self.stdout.write("Recomputing deal snapshots...")
        snapshots = compute_deal_snapshots(require_clean_condition=require_clean)
        with transaction.atomic():
            DealSnapshot.objects.all().delete()
            DealSnapshot.objects.bulk_create(snapshots, batch_size=500)
        self.stdout.write(self.style.SUCCESS(f"Created {len(snapshots)} deal snapshots."))
