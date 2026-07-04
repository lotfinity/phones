from django.core.management.base import BaseCommand, CommandError

from market.collectors.instagram import crawl_profile


class Command(BaseCommand):
    help = "Collect recent public Instagram posts for a profile using Instaloader."

    def add_arguments(self, parser):
        parser.add_argument("username_or_url")
        parser.add_argument("--days", type=int, default=60)
        parser.add_argument("--limit", type=int, default=300)

    def handle(self, *args, **options):
        try:
            count = crawl_profile(
                options["username_or_url"],
                days=options["days"],
                limit=options["limit"],
                stdout=self.stdout,
            )
        except Exception as exc:
            raise CommandError(
                f"Instagram collection failed gracefully: {exc}. Public profiles only; do not bypass login challenges."
            ) from exc
        self.stdout.write(self.style.SUCCESS(f"Collected or updated {count} Instagram posts."))
