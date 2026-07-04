from django.core.management.base import BaseCommand

from market.services.opportunity import run_analysis


class Command(BaseCommand):
    help = "Create opportunity snapshots from market listings and supplier prices."

    def handle(self, *args, **options):
        created = run_analysis()
        self.stdout.write(self.style.SUCCESS(f"Created {created} opportunity snapshots."))
