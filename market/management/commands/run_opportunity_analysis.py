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

    def handle(self, *args, **options):
        created = run_analysis(include_insufficient=options["include_insufficient"])
        self.stdout.write(self.style.SUCCESS(f"Created {created} opportunity snapshots."))

        # Also recompute deal snapshots (cached deals for fast page loads)
        from django.db import transaction
        from market.models import DealSnapshot
        from market.management.commands.recompute_deal_snapshots import compute_deal_snapshots

        self.stdout.write("Recomputing deal snapshots...")
        snapshots = compute_deal_snapshots()
        with transaction.atomic():
            DealSnapshot.objects.all().delete()
            DealSnapshot.objects.bulk_create(snapshots, batch_size=500)
        self.stdout.write(self.style.SUCCESS(f"Created {len(snapshots)} deal snapshots."))
