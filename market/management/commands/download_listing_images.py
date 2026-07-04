from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from market.models import MarketListing
import os
import urllib.request
import urllib.error
from urllib.parse import urlparse
import mimetypes
import hashlib

class Command(BaseCommand):
    help = 'Download images for MarketListing records where image_path is a URL and store locally'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Limit the number of listings to process (0 for all)',
        )
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            help='Skip listings that already have a local file path (not starting with http)',
        )

    def handle(self, *args, **options):
        limit = options['limit']
        skip_existing = options['skip_existing']

        qs = MarketListing.objects.exclude(image_path='')
        if skip_existing:
            qs = qs.filter(image_path__startswith='http')
        else:
            # Only process those that look like URLs
            qs = qs.filter(image_path__startswith='http')

        if limit:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(f"Found {total} listings with image URLs to process.")

        # Prepare download directory
        download_dir = os.path.join(settings.MEDIA_ROOT, 'listing_images')
        os.makedirs(download_dir, exist_ok=True)

        downloaded = 0
        skipped = 0
        errors = 0

        for listing in qs.iterator():
            url = listing.image_path
            try:
                # Determine file extension from URL or content-type
                parsed = urlparse(url)
                filename = os.path.basename(parsed.path)
                if not filename or '.' not in filename:
                    # Try to guess extension from content-type
                    req = urllib.request.Request(url, method='HEAD')
                    try:
                        with urllib.request.urlopen(req, timeout=10) as response:
                            content_type = response.headers.get('Content-Type')
                            ext = mimetypes.guess_extension(content_type.split(';')[0].strip()) if content_type else '.bin'
                            if not ext:
                                ext = '.jpg'  # fallback
                    except Exception:
                        ext = '.jpg'
                    # Generate a filename based on hash of URL to avoid collisions
                    url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:10]
                    filename = f"{listing.id}_{url_hash}{ext}"
                else:
                    # Ensure filename is safe
                    # Prepend listing id to avoid overwrites
                    name, ext = os.path.splitext(filename)
                    filename = f"{listing.id}_{name}{ext}"

                # Ensure the filename is safe (no path traversal)
                filename = os.path.basename(filename)
                dest_path = os.path.join(download_dir, filename)

                # Skip if file already exists
                if os.path.exists(dest_path):
                    self.stdout.write(f"  Skipping existing file for listing {listing.id}: {filename}")
                    skipped += 1
                    # Update the image_path to the local path if it's still a URL
                    if listing.image_path.startswith('http'):
                        listing.image_path = dest_path
                        listing.save(update_fields=['image_path'])
                    continue

                # Download the image
                self.stdout.write(f"  Downloading image for listing {listing.id} from {url}")
                urllib.request.urlretrieve(url, dest_path)
                downloaded += 1

                # Update the model with the local path
                listing.image_path = dest_path
                listing.save(update_fields=['image_path'])

            except Exception as e:
                self.stderr.write(f"  Error processing listing {listing.id}: {e}")
                errors += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Finished. Downloaded: {downloaded}, Skipped (existing): {skipped}, Errors: {errors}"
            )
        )