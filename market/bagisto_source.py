from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.http import Http404, HttpResponse
from django.urls import reverse


BAGISTO_ROOT = Path(settings.BASE_DIR) / "estoreui"
BAGISTO_HOSTS = {
    "bagisto-headless-electronic.vercel.app",
    "nextjs.bagisto.com",
    "www.nextjs.bagisto.com",
}


def _asset_root() -> str:
    marker = "__pricebridge_asset__"
    return reverse("estore_asset", kwargs={"path": marker}).replace(marker, "")


def _read_source(candidates: list[str]) -> tuple[str, str]:
    for relative_path in candidates:
        candidate = (BAGISTO_ROOT / relative_path).resolve()
        try:
            candidate.relative_to(BAGISTO_ROOT.resolve())
        except ValueError as exc:
            raise Http404("Invalid Bagisto source path") from exc

        if candidate.is_file():
            return relative_path, candidate.read_text(encoding="utf-8")

    raise Http404("Preserved Bagisto source page was not found")


def _safe_json(payload: dict) -> str:
    text = json.dumps(payload, cls=DjangoJSONEncoder, ensure_ascii=False, separators=(",", ":"))
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _html_escape(value) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#039;")
    )


def _absolutize_assets(html: str) -> str:
    root = _asset_root()

    # The preserved pages live below estoreui/pages/, while Django exposes the
    # exact same assets below /estore/assets/. Only path resolution changes.
    html = re.sub(
        r'(?P<quote>["\'])((?:\.\./)+)assets/',
        lambda match: f"{match.group('quote')}{root}",
        html,
    )
    html = re.sub(
        r'(?P<quote>["\'])\./assets/',
        lambda match: f"{match.group('quote')}{root}",
        html,
    )
    return html


def _captured_destination(value: str, *, for_form: bool = False, urls: dict | None = None) -> str | None:
    """Map captured Bagisto navigation to the isolated PriceBridge storefront."""
    urls = urls or {}
    index_url = urls.get("index") or "/estore/"
    phone_url = urls.get("phone") or "/estore/?category=phone"
    laptop_url = urls.get("laptop") or "/estore/?category=laptop"
    console_url = urls.get("console") or "/estore/?category=console"

    raw = (value or "").strip()
    if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None

    parsed = urlsplit(raw)
    host = parsed.netloc.lower()
    path = (parsed.path or "/").lower().rstrip("/") or "/"

    # Leave unrelated external links and static resources alone.
    if host and host not in BAGISTO_HOSTS:
        return None
    if not host and not raw.startswith("/"):
        return None
    if path.startswith(("/estore/assets", "/assets", "/_next", "/media")):
        return None
    if path.endswith((".css", ".js", ".woff", ".woff2", ".png", ".jpg", ".jpeg", ".webp", ".svg")):
        return None

    query = parsed.query.lower()
    combined = f"{path}?{query}"

    if for_form:
        return index_url

    if path == "/":
        return index_url
    if any(token in combined for token in ("smartphone", "phone", "mobile")) and "/product" not in path:
        return phone_url
    if any(token in combined for token in ("laptop", "computer", "notebook")) and "/product" not in path:
        return laptop_url
    if any(token in combined for token in ("console", "gaming")) and "/product" not in path:
        return console_url

    # Product anchors are retained as structural markers. The opportunity
    # adapter replaces each one with its real Django detail URL.
    if path.startswith(("/product/", "/products/")):
        return "#pb-product"

    if any(
        token in path
        for token in (
            "/customer",
            "/account",
            "/login",
            "/register",
            "/cart",
            "/checkout",
            "/wishlist",
            "/compare",
            "/contact",
        )
    ):
        return index_url

    # No captured Bagisto/Vercel link is allowed to escape the isolated store.
    if host in BAGISTO_HOSTS:
        return index_url
    return None


def _rewrite_captured_navigation(html: str, *, urls: dict | None = None) -> str:
    attribute_pattern = re.compile(
        r'(?P<prefix>\b(?P<attribute>href|action)\s*=\s*)(?P<quote>["\'])(?P<value>.*?)(?P=quote)',
        flags=re.IGNORECASE | re.DOTALL,
    )

    def replace(match: re.Match) -> str:
        attribute = match.group("attribute").lower()
        value = match.group("value")
        destination = _captured_destination(value, for_form=attribute == "action", urls=urls)
        if destination is None:
            return match.group(0)
        return f'{match.group("prefix")}{match.group("quote")}{destination}{match.group("quote")}'

    return attribute_pattern.sub(replace, html)


def _spec_table_html(rows: list[dict]) -> str:
    body = "\n".join(
        f'<tr><td class="px-4 py-3 text-sm text-neutral-700 dark:text-neutral-300">{_html_escape(row.get("label"))}</td>'
        f'<td class="px-4 py-3 text-sm text-neutral-700 dark:text-neutral-300">{_html_escape(row.get("value"))}</td></tr>'
        for row in rows
    )
    return f"""
<table class="min-w-full divide-y divide-neutral-200 dark:divide-neutral-700" data-pb-detail-spec-table>
  <thead class="bg-neutral-50 dark:bg-neutral-800/50">
    <tr>
      <th class="px-6 py-3 text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">Attribute</th>
      <th class="px-6 py-3 text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">Value</th>
    </tr>
  </thead>
  <tbody class="divide-y divide-neutral-200 bg-white dark:divide-neutral-800 dark:bg-neutral-900">
    {body}
  </tbody>
</table>""".strip()


def _rewrite_detail_specs_table(html: str, rows: list[dict] | None) -> str:
    if not rows:
        return html

    table = _spec_table_html(rows)
    pattern = re.compile(
        r"<table\b[^>]*>[^<]*(?:(?!</table>).)*?\bAttribute\b(?:(?!</table>).)*?</table>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    html, count = pattern.subn(table, html, count=1)
    return html


def _comparables_panel_html(rows: list[dict] | None) -> str:
    rows = rows or []
    if not rows:
        body = '<p class="text-sm text-neutral-500 dark:text-neutral-400">Türkiye karşılaştırma ilanı bulunamadı.</p>'
    else:
        cards = []
        for row in rows[:12]:
            title = row.get("title") or "Türkiye karşılaştırması"
            href = row.get("listing_url") or "#"
            image = ""
            if row.get("image_url"):
                image = (
                    f'<img src="{_html_escape(row.get("image_url"))}" alt="{_html_escape(title)}" '
                    'loading="lazy" class="h-16 w-16 rounded-lg object-cover bg-neutral-100 dark:bg-neutral-800">'
                )
            meta = " · ".join(
                str(value)
                for value in (
                    row.get("source_name"),
                    row.get("price_eur"),
                    row.get("condition"),
                )
                if value
            )
            cards.append(
                '<a class="flex gap-3 rounded-xl border border-neutral-200 dark:border-neutral-800 '
                'bg-white dark:bg-neutral-900 p-3 text-sm transition-colors hover:border-neutral-300 '
                'dark:hover:border-neutral-700" target="_blank" rel="noopener noreferrer" '
                f'href="{_html_escape(href)}">'
                f"{image}"
                '<span class="min-w-0">'
                f'<strong class="block truncate text-neutral-900 dark:text-white">{_html_escape(title)}</strong>'
                f'<small class="block text-neutral-500 dark:text-neutral-400">{_html_escape(meta)}</small>'
                "</span></a>"
            )
        body = '<div class="grid gap-3 md:grid-cols-2">' + "\n".join(cards) + "</div>"

    return f"""
<section data-pb-comparables-panel hidden class="mt-6">
  <div class="mb-4">
    <h3 class="text-base font-semibold text-neutral-900 dark:text-white">Türkiye Comparables ({len(rows)})</h3>
    <p class="text-sm text-neutral-500 dark:text-neutral-400">Sahibinden ortalamasını oluşturan benzer ilanlar.</p>
  </div>
  {body}
</section>
""".strip()


def _rewrite_comparables_tab(html: str, rows: list[dict] | None) -> str:
    count = len(rows or [])
    html = re.sub(
        r">Reviews\s*\(\d+\)<",
        f">Türkiye Comparables ({count})<",
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    if "data-pb-comparables-panel" in html:
        return html
    if "data-pb-detail-spec-table" not in html:
        return html
    pattern = re.compile(
        r"(?P<table><table\b(?=[^>]*\bdata-pb-detail-spec-table\b)[^>]*>.*?</table>)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    html, _count = pattern.subn(
        lambda match: match.group("table") + "\n" + _comparables_panel_html(rows),
        html,
        count=1,
    )
    return html


def _description_text(rows: list[dict]) -> str:
    return ",\n".join(
        f"{row.get('label')}: {row.get('value')}"
        for row in rows
        if row.get("label") and row.get("value") not in (None, "")
    )


def _rewrite_detail_description(html: str, rows: list[dict] | None) -> str:
    if not rows:
        return html
    description = (
        _description_text(rows)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    pattern = re.compile(
        r"(?P<open><p\b(?=[^>]*\bline-clamp-4\b)[^>]*>)(?P<body>.*?)(?P<close></p>)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    html, _count = pattern.subn(
        lambda match: f"{match.group('open')}{description}{match.group('close')}",
        html,
        count=1,
    )
    return html


def render_bagisto_source(
    request,
    *,
    candidates: list[str],
    payload: dict,
    page_title: str,
) -> HttpResponse:
    source_path, html = _read_source(candidates)
    html = _absolutize_assets(html)
    html = _rewrite_captured_navigation(html, urls=payload.get("urls") or {})
    html = _rewrite_detail_specs_table(html, payload.get("detail_specs"))
    html = _rewrite_comparables_tab(html, payload.get("turkiye_rows"))
    html = _rewrite_detail_description(html, payload.get("detail_description_rows"))

    html = re.sub(
        r"<title>.*?</title>",
        f"<title>{page_title}</title>",
        html,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )

    bridge_css = reverse("estore_asset", kwargs={"path": "css/bagisto-django-bridge.css"})
    plan_css = reverse("estore_asset", kwargs={"path": "css/pricebridge-plan.css"})
    shell_js = reverse("estore_asset", kwargs={"path": "js/site-shell.js"})
    detail_js = reverse("estore_asset", kwargs={"path": "js/pricebridge-detail.js"})
    plan_js = reverse("estore_asset", kwargs={"path": "js/pricebridge-plan.js"})

    head_injection = f"""
<meta name="pricebridge-bagisto-source" content="{source_path}">
<meta name="pricebridge-frontend" content="api-driven-bagisto-port">
<link rel="stylesheet" href="{bridge_css}">
<link rel="stylesheet" href="{plan_css}">
""".strip()

    if "</head>" in html.lower():
        html = re.sub(
            r"</head>",
            lambda _match: head_injection + "\n</head>",
            html,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        html = head_injection + html

    runtime_parts = []
    if payload.get("page") == "opportunity-detail":
        runtime_parts.extend(
            [
                "<script>",
                "window.PriceBridgePage = " + _safe_json(
                    {
                        "page": "opportunity-detail",
                        "api_url": payload.get("api_url", ""),
                    }
                ) + ";",
                "</script>",
            ]
        )
    if "site-shell.js" not in html:
        runtime_parts.append(f'<script src="{shell_js}" defer></script>')
    if payload.get("page") == "opportunity-detail":
        runtime_parts.append(f'<script src="{detail_js}" defer></script>')
    runtime_parts.append(f'<script src="{plan_js}" defer></script>')
    runtime = "\n".join(runtime_parts)

    if "</body>" in html.lower():
        html = re.sub(
            r"</body>",
            lambda _match: runtime + "\n</body>",
            html,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        html += runtime

    response = HttpResponse(html, content_type="text/html; charset=utf-8")
    response["X-PriceBridge-Frontend"] = "api-driven-bagisto-port"
    response["X-PriceBridge-Bagisto-Source"] = source_path
    return response
