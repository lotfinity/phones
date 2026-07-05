import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q

from market.models import MarketListing, MarketListingSuggestion
from market.services.listing_suggestions import build_listing_suggestion


SCRIPTS_DIR = Path(settings.BASE_DIR) / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def parse_cdp_endpoint(cdp_endpoint):
    parsed = urlparse(cdp_endpoint)
    return parsed.hostname or "127.0.0.1", parsed.port or 9222


def comparable_url(value):
    parsed = urlparse(value or "")
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.netloc.lower()}{path}"


def extract_open_cdp_text(cdp_endpoint, listing_url):
    if not listing_url:
        return ""
    try:
        from chrome_extension_cdp import ChromeCdp, CdpSocket
    except ImportError:
        return ""

    wanted = comparable_url(listing_url)
    if not wanted:
        return ""

    host, port = parse_cdp_endpoint(cdp_endpoint)
    cdp = ChromeCdp(host, port)
    target = None
    for item in cdp.targets():
        if item.type != "page":
            continue
        current = comparable_url(item.url)
        if current == wanted or wanted in current or current in wanted:
            target = item
            break
    if not target:
        return ""

    sock = CdpSocket(target)
    try:
        sock.call("Runtime.enable")
        expression = r"""
(() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const attrs = {};
  document.querySelectorAll('li, .classifiedInfoList li, [class*="attribute"], [class*="Attribute"]').forEach((el) => {
    const text = clean(el.innerText);
    if (text && text.length < 240) attrs[text] = true;
  });
  const title = clean(document.querySelector('h1')?.innerText || document.title || '');
  const description = clean(
    document.querySelector('#classifiedDescription, [class*="description"], [class*="Description"]')?.innerText || ''
  );
  const body = clean(document.body?.innerText || '').slice(0, 4000);
  return JSON.stringify({url: window.location.href, title, description, attrs: Object.keys(attrs).slice(0, 80), body});
})()
"""
        payload = json.loads(sock.eval(expression) or "{}")
        return "\n".join(
            part
            for part in [
                payload.get("title", ""),
                payload.get("description", ""),
                "\n".join(payload.get("attrs", [])),
                payload.get("body", ""),
            ]
            if part
        )
    finally:
        sock.close()


class Command(BaseCommand):
    help = "Create reviewable suggestions for listings that need model/storage/condition cleanup."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--min-confidence", type=float, default=0.35)
        parser.add_argument("--status", default=MarketListing.ReviewStatus.NEEDS_REVIEW)
        parser.add_argument(
            "--issue",
            choices=["", "missing_model", "missing_storage", "missing_price", "no_image"],
            default="",
        )
        parser.add_argument("--source-type", default="")
        parser.add_argument("--country", default="")
        parser.add_argument(
            "--use-cdp",
            nargs="?",
            const="http://127.0.0.1:9222",
            default="",
            help="Also inspect a matching page already open in user Chrome CDP. Does not navigate or bypass challenges.",
        )

    def handle(self, *args, **options):
        qs = MarketListing.objects.select_related("source", "product_model").order_by("-observed_at")
        status = options["status"].strip()
        if status:
            qs = qs.filter(review_status=status)
        if options["source_type"]:
            qs = qs.filter(source_type=options["source_type"])
        if options["country"]:
            qs = qs.filter(country=options["country"])

        issue = options["issue"]
        if issue == "missing_model":
            qs = qs.filter(product_model__isnull=True)
        elif issue == "missing_storage":
            qs = qs.filter(product_model__isnull=False, storage_gb__isnull=True)
        elif issue == "missing_price":
            qs = qs.filter(Q(price_original__isnull=True) | Q(price_eur__isnull=True))
        elif issue == "no_image":
            qs = qs.filter(image_path="")

        created = updated = skipped = 0
        for listing in qs[: max(options["limit"], 0)]:
            extra_text = extract_open_cdp_text(options["use_cdp"], listing.listing_url) if options["use_cdp"] else ""
            suggestion = build_listing_suggestion(listing, extra_text=extra_text)
            if suggestion.confidence < options["min_confidence"]:
                skipped += 1
                continue

            existing = (
                MarketListingSuggestion.objects.filter(
                    listing=listing,
                    status=MarketListingSuggestion.Status.PENDING,
                )
                .order_by("-created_at")
                .first()
            )
            values = {
                "suggested_product_model": suggestion.product_model,
                "suggested_storage_gb": suggestion.storage_gb,
                "suggested_sim_config": suggestion.sim_config,
                "suggested_condition": suggestion.condition,
                "confidence": suggestion.confidence,
                "reason": suggestion.reason,
                "raw_evidence": suggestion.evidence,
            }
            if existing:
                for field, value in values.items():
                    setattr(existing, field, value)
                existing.save()
                updated += 1
            else:
                MarketListingSuggestion.objects.create(listing=listing, **values)
                created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Suggestions created={created}, updated={updated}, skipped_low_confidence={skipped}"
            )
        )
