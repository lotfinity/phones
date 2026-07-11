from django.shortcuts import render

from market.views import base_context
from market.views_clean import (
    _filtered_clean_rows,
    _shared_clean_context,
    can_view_internal_gain,
    can_view_operational_meta,
)

PRIVATE_CARD_KEYS = {
    "item",
    "algeria_avg_eur",
    "turkiye_min_eur",
    "gross_margin",
    "gross_margin_eur",
    "algeria_urls",
    "turkiye_urls",
    "my_gain",
    "my_gain_dzd",
    "my_gain_percent",
    "pricing_basis",
    "pricing_notes",
}

PUBLIC_ONLY_HIDDEN_KEYS = {
    "snapshot_id",
    "generated_at",
    "source_label",
}


def _sanitize_card_context(context, *, show_internal_gain, show_operational_meta):
    if show_internal_gain:
        return context

    hidden_keys = set(PRIVATE_CARD_KEYS)
    if not show_operational_meta:
        hidden_keys.update(PUBLIC_ONLY_HIDDEN_KEYS)

    sanitized_rows = []
    for row in context.get("rows", []):
        sanitized = {key: value for key, value in row.items() if key not in hidden_keys}
        sanitized["gross_margin"] = "-"
        sanitized_rows.append(sanitized)

    context["rows"] = sanitized_rows
    context["best_opportunity"] = sanitized_rows[0] if sanitized_rows else None
    context["total_gross"] = "-"
    context["avg_margin"] = "-"
    if not show_operational_meta:
        context["source_counts"] = context.get("source_counts", {}) | {"needs_review": "-"}
    return context


def clean_card_opportunities(request):
    """Card UI with legacy-compatible public/staff/superuser data boundaries."""
    rows, device_type, brand, q = _filtered_clean_rows(request)
    show_internal_gain = can_view_internal_gain(request)
    show_operational_meta = can_view_operational_meta(request)
    context = base_context(request, "opportunities") | _shared_clean_context(
        request,
        rows,
        device_type,
        brand,
        q,
    )
    context = _sanitize_card_context(
        context,
        show_internal_gain=show_internal_gain,
        show_operational_meta=show_operational_meta,
    )
    return render(request, "market/clean_card_opportunities.html", context)
