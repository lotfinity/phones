from django.core.management.base import BaseCommand

from market.models import InstagramPost, MarketListing, OCRResult, OpportunitySnapshot, SupplierPrice


class Command(BaseCommand):
    help = "Print quick counts for recent market data."

    def handle(self, *args, **options):
        self.stdout.write(f"Instagram posts: {InstagramPost.objects.count()}")
        self.stdout.write(f"OCR results: {OCRResult.objects.count()}")
        self.stdout.write(f"Market listings: {MarketListing.objects.count()}")
        self.stdout.write(f"Supplier prices: {SupplierPrice.objects.count()}")
        self.stdout.write(f"Opportunity snapshots: {OpportunitySnapshot.objects.count()}")
