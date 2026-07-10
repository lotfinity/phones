"""Export a local HTML review report for raw/candidate/final listing data.

Usage examples:
    python manage.py export_data_review --category laptop --limit 300
    python manage.py export_data_review --q macbook --limit 200 --output exports/review_macbook.html
    python manage.py export_data_review --country algeria --source-type ouedkniss
"""

import html
import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Q

from market.models import ParsedListingCandidate, RawListing
from market.services.laptop_quality import (
    candidate_has_laptop_export_identity,
    is_garbage_laptop_model_name,
    is_generic_laptop_model_name,
    listing_has_laptop_export_identity,
)


STYLE = """
:root { color-scheme: dark light; }
body { font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; background: #0f172a; color: #e5e7eb; }
header { position: sticky; top: 0; z-index: 5; background: #020617; border-bottom: 1px solid #334155; padding: 14px 18px; }
h1 { margin: 0 0 6px; font-size: 20px; }
.meta { color: #94a3b8; font-size: 13px; }
main { padding: 16px; }
.grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.card { background: #111827; border: 1px solid #334155; border-radius: 12px; padding: 12px; }
.card b { display: block; font-size: 22px; color: #f8fafc; }
.card span { color: #94a3b8; font-size: 13px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { position: sticky; top: 62px; background: #111827; z-index: 4; text-align: left; color: #cbd5e1; border-bottom: 1px solid #475569; padding: 8px; }
td { vertical-align: top; border-bottom: 1px solid #1f2937; padding: 8px; }
tr:hover { background: #111827; }
.badge { display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 12px; margin: 1px 2px 1px 0; border: 1px solid #475569; color: #cbd5e1; }
.ok { border-color: #22c55e; color: #86efac; }
.warn { border-color: #f59e0b; color: #fcd34d; }
.bad { border-color: #ef4444; color: #fca5a5; }
.muted { color: #94a3b8; }
.small { font-size: 12px; color: #94a3b8; }
.raw { max-width: 360px; white-space: normal; overflow-wrap: anywhere; }
a { color: #93c5fd; text-decoration: none; }
a:hover { text-decoration: underline; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: #cbd5e1; }
@media (max-width: 1100px) { .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } table { font-size: 12px; } th:nth-child(8), td:nth-child(8) { display:none; } }
"""


def esc(value):
    if value is None:
        return ""
    return html.escape(str(value))


def money(value, currency=""):
    if value is None:
        return ""
    return f"{value} {currency}".strip()


def badge(text, kind=""):
    if not text:
        return ""
    cls = "badge"
    if kind:
        cls += f" {kind}"
    return f'<span class="{cls}">{esc(text)}</span>'


def confidence_badge(value):
    try:
        val = float(value or 0)
    except (TypeError, ValueError):
        val = 0
    kind = "ok" if val >= 0.9 else "warn" if val >= 0.65 else "bad"
    return badge(f"conf {val:.2f}", kind)


def json_block(value):
    if not value:
        return ""
    return f"<pre>{esc(json.dumps(value, ensure_ascii=False, indent=2))}</pre>"


class Command(BaseCommand):
    help = "Export an HTML file to visually review raw listings, candidates, and final normalized listings."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="exports/data_review.html")
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--category", choices=["phone", "laptop", "portable_console", "unknown", "accessory"])
        parser.add_argument("--country")
        parser.add_argument("--source-type")
        parser.add_argument("--status", help="Candidate status filter: pending/needs_review/approved/rejected/exported")
        parser.add_argument("--q", help="Search title, URL, brand, model, and raw text")
        parser.add_argument("--only-problems", action="store_true", help="Show rows with weak confidence, missing model, or needs_review")
        parser.add_argument(
            "--problem",
            action="append",
            choices=[
                "missing_model",
                "weak_confidence",
                "generic_model",
                "garbage_model",
                "candidate_final_mismatch",
                "not_export_eligible",
            ],
            help="Filter to a specific problem type. Can be passed multiple times.",
        )

    def handle(self, *args, **options):
        qs = ParsedListingCandidate.objects.select_related(
            "raw_listing",
            "matched_brand",
            "matched_phone_model",
            "matched_phone_variant",
            "matched_laptop_model",
            "matched_laptop_variant",
            "matched_console_model",
            "matched_console_variant",
            "raw_listing__phone_listing__phone_model",
            "raw_listing__phone_listing__variant",
            "raw_listing__laptop_listing__laptop_model",
            "raw_listing__laptop_listing__variant",
            "raw_listing__console_listing__console_model",
            "raw_listing__console_listing__variant",
        ).order_by("-created_at")

        if options["category"]:
            qs = qs.filter(detected_category=options["category"])
        if options["status"]:
            qs = qs.filter(status=options["status"])
        if options["country"]:
            qs = qs.filter(raw_listing__country=options["country"])
        if options["source_type"]:
            qs = qs.filter(raw_listing__source_type=options["source_type"])
        if options["q"]:
            q = options["q"]
            qs = qs.filter(
                Q(raw_listing__title_raw__icontains=q)
                | Q(raw_listing__listing_url__icontains=q)
                | Q(raw_listing__raw_text__icontains=q)
                | Q(brand_text__icontains=q)
                | Q(model_text__icontains=q)
                | Q(matched_laptop_model__canonical_name__icontains=q)
                | Q(matched_phone_model__canonical_name__icontains=q)
            )
        if options["only_problems"]:
            qs = qs.filter(Q(confidence__lt=0.65) | Q(model_text="") | Q(status=ParsedListingCandidate.Status.NEEDS_REVIEW))

        requested_problems = set(options.get("problem") or [])
        if requested_problems:
            filtered = []
            for candidate in qs[: max(options["limit"] * 5, options["limit"])]:
                problems = self._problem_keys(candidate)
                if requested_problems.intersection(problems):
                    filtered.append(candidate)
                if len(filtered) >= options["limit"]:
                    break
            rows = filtered
        else:
            rows = list(qs[: options["limit"]])

        counts = {
            "rows": len(rows),
            "needs_review": sum(1 for c in rows if c.status == ParsedListingCandidate.Status.NEEDS_REVIEW),
            "laptops": sum(1 for c in rows if c.detected_category == ParsedListingCandidate.DetectedCategory.LAPTOP),
            "phones": sum(1 for c in rows if c.detected_category == ParsedListingCandidate.DetectedCategory.PHONE),
            "consoles": sum(1 for c in rows if c.detected_category == ParsedListingCandidate.DetectedCategory.PORTABLE_CONSOLE),
            "missing_model": sum(1 for c in rows if not c.model_text),
        }

        body_rows = []
        for c in rows:
            raw = c.raw_listing
            phone = getattr(raw, "phone_listing", None)
            laptop = getattr(raw, "laptop_listing", None)
            console = getattr(raw, "console_listing", None)
            final_listing = laptop or phone or console
            final_model = ""
            final_specs = ""
            final_status = ""
            if laptop:
                final_model = laptop.laptop_model.canonical_name if laptop.laptop_model else ""
                final_specs = " / ".join(
                    part for part in [
                        laptop.cpu,
                        laptop.gpu,
                        f"{laptop.ram_gb}GB RAM" if laptop.ram_gb else "",
                        f"{laptop.storage_gb}GB" if laptop.storage_gb else "",
                    ]
                    if part
                )
                final_status = f"LaptopListing {laptop.review_status} conf={laptop.parsed_confidence:.2f}"
            elif phone:
                final_model = phone.phone_model.canonical_name if phone.phone_model else ""
                final_specs = " / ".join(
                    part for part in [
                        f"{phone.ram_gb}GB RAM" if phone.ram_gb else "",
                        f"{phone.storage_gb}GB" if phone.storage_gb else "",
                        phone.sim_config,
                    ]
                    if part
                )
                final_status = f"PhoneListing {phone.review_status} conf={phone.parsed_confidence:.2f}"
            elif console:
                final_model = console.console_model.canonical_name if console.console_model else ""
                final_specs = " / ".join(
                    part for part in [
                        console.chipset,
                        f"{console.ram_gb}GB RAM" if console.ram_gb else "",
                        f"{console.storage_gb}GB" if console.storage_gb else "",
                    ]
                    if part
                )
                final_status = f"ConsoleListing {console.review_status} conf={console.parsed_confidence:.2f}"

            problem_bits = []
            problem_keys = self._problem_keys(c)
            if c.status == ParsedListingCandidate.Status.NEEDS_REVIEW:
                problem_bits.append(badge("needs review", "warn"))
            if "missing_model" in problem_keys:
                problem_bits.append(badge("missing model", "bad"))
            if "weak_confidence" in problem_keys:
                problem_bits.append(badge("weak candidate", "bad"))
            if "generic_model" in problem_keys:
                problem_bits.append(badge("generic model", "warn"))
            if "garbage_model" in problem_keys:
                problem_bits.append(badge("garbage model", "bad"))
            if c.detected_category == ParsedListingCandidate.DetectedCategory.LAPTOP and laptop and not any([laptop.cpu, laptop.gpu, laptop.ram_gb, laptop.storage_gb]):
                problem_bits.append(badge("no laptop specs", "bad"))
            if "candidate_final_mismatch" in problem_keys:
                problem_bits.append(badge("candidate/final mismatch", "warn"))
            if "not_export_eligible" in problem_keys:
                problem_bits.append(badge("not export eligible", "bad"))

            url = raw.listing_url or ""
            link = f'<a href="{esc(url)}" target="_blank">open</a>' if url else ""
            body_rows.append(
                "<tr>"
                f"<td>{raw.pk}<br><span class='small'>{esc(raw.source_type)} / {esc(raw.country)}</span></td>"
                f"<td class='raw'><b>{esc(raw.title_raw)}</b><br>{link}<br><span class='small'>{esc(url)}</span></td>"
                f"<td>{badge(c.detected_category)} {badge(c.status)}<br>{confidence_badge(c.confidence)}<br>{''.join(problem_bits)}</td>"
                f"<td><b>{esc(c.brand_text)} {esc(c.model_text)}</b><br><span class='small'>{esc(c.variant_text)}</span></td>"
                f"<td>{json_block(c.laptop_specs_json or c.phone_specs_json or c.console_specs_json)}</td>"
                f"<td><b>{esc(final_model)}</b><br><span class='small'>{esc(final_specs)}</span><br>{badge(final_status, 'ok' if final_listing and final_listing.review_status == 'auto' else 'warn' if final_listing else 'bad')}</td>"
                f"<td>{money(c.price_original, c.currency_original)}<br><span class='small'>€ {esc(c.price_eur)}</span></td>"
                f"<td class='raw'><pre>{esc((raw.raw_text or '')[:900])}</pre></td>"
                "</tr>"
            )

        html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PriceBridge Data Review</title>
<style>{STYLE}</style>
</head>
<body>
<header>
  <h1>PriceBridge Data Review</h1>
  <div class="meta">Filters: category={esc(options.get('category') or 'all')} country={esc(options.get('country') or 'all')} source={esc(options.get('source_type') or 'all')} q={esc(options.get('q') or '')}</div>
</header>
<main>
  <section class="grid">
    <div class="card"><b>{counts['rows']}</b><span>Rows shown</span></div>
    <div class="card"><b>{counts['needs_review']}</b><span>Needs review</span></div>
    <div class="card"><b>{counts['laptops']} / {counts['phones']} / {counts['consoles']}</b><span>Laptops / Phones / Consoles</span></div>
    <div class="card"><b>{counts['missing_model']}</b><span>Missing model</span></div>
  </section>
  <table>
    <thead>
      <tr>
        <th>ID</th><th>Raw Listing</th><th>Candidate State</th><th>Candidate Model</th><th>Extracted Specs</th><th>Final Listing</th><th>Price</th><th>Raw Text</th>
      </tr>
    </thead>
    <tbody>{''.join(body_rows)}</tbody>
  </table>
</main>
</body>
</html>"""

        output = Path(options["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(html_doc, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Exported {len(rows)} rows to {output}"))

    def _problem_keys(self, candidate):
        raw = candidate.raw_listing
        laptop = getattr(raw, "laptop_listing", None)
        model_text = candidate.model_text or ""
        final_model = laptop.laptop_model.canonical_name if laptop and laptop.laptop_model else ""
        problems = set()

        if not model_text:
            problems.add("missing_model")
        if candidate.confidence < 0.65:
            problems.add("weak_confidence")
        if candidate.detected_category == ParsedListingCandidate.DetectedCategory.LAPTOP:
            if is_generic_laptop_model_name(model_text) or is_generic_laptop_model_name(final_model):
                problems.add("generic_model")
            if is_garbage_laptop_model_name(model_text) or is_garbage_laptop_model_name(final_model):
                problems.add("garbage_model")
            if laptop and final_model.lower() != model_text.lower():
                problems.add("candidate_final_mismatch")
            candidate_ok = candidate_has_laptop_export_identity(candidate)
            listing_ok = listing_has_laptop_export_identity(laptop) if laptop else False
            if not (candidate_ok or listing_ok):
                problems.add("not_export_eligible")
        return problems
