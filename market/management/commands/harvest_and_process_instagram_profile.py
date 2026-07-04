from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from market.collectors.instagram import normalize_instagram_username
from market.models import InstagramPost, Source, SourceType


class Command(BaseCommand):
    help = "Harvest Instagram profile-grid URLs via CDP, then OCR only newly queued posts."

    def add_arguments(self, parser):
        parser.add_argument("profile_url")
        parser.add_argument("--limit", type=int, default=10)
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--cookie-file", default=settings.INSTAGRAM_COOKIE_FILE)
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=9222)
        parser.add_argument("--wait", type=float, default=6)
        parser.add_argument("--scroll-steps", type=int, default=None)
        parser.add_argument("--ocr-limit", type=int, default=None)

    def handle(self, *args, **options):
        username = normalize_instagram_username(options["profile_url"])
        source = Source.objects.filter(source_type=SourceType.INSTAGRAM, username=username).first()
        before_urls = set()
        if source:
            before_urls = set(InstagramPost.objects.filter(source=source).values_list("post_url", flat=True))

        scroll_steps = options["scroll_steps"]
        if scroll_steps is None:
            scroll_steps = max(4, (options["offset"] + options["limit"]) // 9 + 2)

        call_command(
            "harvest_instagram_profile_page",
            options["profile_url"],
            limit=options["limit"],
            offset=options["offset"],
            cookie_file=options["cookie_file"],
            host=options["host"],
            port=options["port"],
            wait=options["wait"],
            scroll_steps=scroll_steps,
            download_images=True,
            verbosity=options["verbosity"],
        )

        source = Source.objects.get(source_type=SourceType.INSTAGRAM, username=username)
        after_posts = InstagramPost.objects.filter(source=source)
        after_urls = set(after_posts.values_list("post_url", flat=True))
        new_count = len(after_urls - before_urls)
        queued_count = after_posts.filter(needs_ocr=True, ocr_processed=False).count()
        process_limit = options["ocr_limit"] or queued_count or options["limit"]

        self.stdout.write(
            f"Harvest summary for @{username}: {new_count} new URLs, {queued_count} queued for OCR."
        )
        if queued_count:
            call_command("process_ocr_queue", limit=process_limit, verbosity=options["verbosity"])
        else:
            self.stdout.write("No new OCR work queued.")
