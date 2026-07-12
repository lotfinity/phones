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


def _captured_destination(value: str, *, for_form: bool = False) -> str | None:
    """Map captured Bagisto navigation to the isolated PriceBridge storefront."""
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
        return "/estore/"

    if path == "/":
        return "/estore/"
    if any(token in combined for token in ("smartphone", "phone", "mobile")) and "/product" not in path:
        return "/estore/?category=phone"
    if any(token in combined for token in ("laptop", "computer", "notebook")) and "/product" not in path:
        return "/estore/?category=laptop"
    if any(token in combined for token in ("console", "gaming")) and "/product" not in path:
        return "/estore/?category=console"

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
        return "/estore/"

    # No captured Bagisto/Vercel link is allowed to escape the isolated store.
    if host in BAGISTO_HOSTS:
        return "/estore/"
    return None


def _rewrite_captured_navigation(html: str) -> str:
    attribute_pattern = re.compile(
        r'(?P<prefix>\b(?P<attribute>href|action)\s*=\s*)(?P<quote>["\'])(?P<value>.*?)(?P=quote)',
        flags=re.IGNORECASE | re.DOTALL,
    )

    def replace(match: re.Match) -> str:
        attribute = match.group("attribute").lower()
        value = match.group("value")
        destination = _captured_destination(value, for_form=attribute == "action")
        if destination is None:
            return match.group(0)
        return f'{match.group("prefix")}{match.group("quote")}{destination}{match.group("quote")}'

    return attribute_pattern.sub(replace, html)


def render_bagisto_source(
    request,
    *,
    candidates: list[str],
    payload: dict,
    page_title: str,
) -> HttpResponse:
    source_path, html = _read_source(candidates)
    html = _absolutize_assets(html)
    html = _rewrite_captured_navigation(html)

    html = re.sub(
        r"<title>.*?</title>",
        f"<title>{page_title}</title>",
        html,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )

    bridge_css = reverse("estore_asset", kwargs={"path": "css/bagisto-django-bridge.css"})
    shell_js = reverse("estore_asset", kwargs={"path": "js/site-shell.js"})
    adapter_js = reverse(
        "estore_asset",
        kwargs={"path": "js/bagisto-opportunity-adapter.js"},
    )

    head_injection = f"""
<meta name="pricebridge-bagisto-source" content="{source_path}">
<meta name="pricebridge-frontend" content="preserved-bagisto-port">
<link rel="stylesheet" href="{bridge_css}">
<style>html.pb-bagisto-hydrating body{{visibility:hidden}}</style>
<script>
  document.documentElement.classList.add("pb-bagisto-hydrating");
  window.setTimeout(function () {{
    document.documentElement.classList.remove("pb-bagisto-hydrating");
  }}, 2200);
</script>
""".strip()

    if "</head>" in html.lower():
        html = re.sub(
            r"</head>",
            head_injection + "\n</head>",
            html,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        html = head_injection + html

    runtime_parts = [
        '<script id="pricebridge-opportunity-data" type="application/json">',
        _safe_json(payload),
        "</script>",
    ]
    if "site-shell.js" not in html:
        runtime_parts.append(f'<script src="{shell_js}" defer></script>')
    runtime_parts.append(f'<script src="{adapter_js}" defer></script>')
    runtime = "\n".join(runtime_parts)

    if "</body>" in html.lower():
        html = re.sub(
            r"</body>",
            runtime + "\n</body>",
            html,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        html += runtime

    response = HttpResponse(html, content_type="text/html; charset=utf-8")
    response["X-PriceBridge-Frontend"] = "preserved-bagisto-port"
    response["X-PriceBridge-Bagisto-Source"] = source_path
    return response
