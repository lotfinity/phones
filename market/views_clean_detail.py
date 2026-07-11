from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from market.views import base_context
from market.views_clean import (
    CLEAN_SNAPSHOT_MODELS,
    _display_row,
    _evidence_rows,
    _snapshot_row,
    can_view_internal_gain,
    can_view_operational_meta,
)

PUBLIC_DETAIL_ROW_KEYS = {
    "device_type",
    "category_label",
    "brand",
    "model",
    "title",
    "spec",
    "turkiye_avg",
    "turkiye_count",
    "recommendation",
    "recommendation_value",
    "recommendation_class",
    "confidence_score",
    "buyer_offer",
    "buyer_offer_dzd",
    "buyer_gain",
    "buyer_gain_percent",
    "deal_quality",
}

STAFF_DETAIL_ROW_KEYS = PUBLIC_DETAIL_ROW_KEYS | {
    "snapshot_id",
    "generated_at",
    "source_label",
}


def _restrict_detail_row(row, *, show_internal_gain, show_operational_meta):
    if show_internal_gain:
        return row
    allowed = STAFF_DETAIL_ROW_KEYS if show_operational_meta else PUBLIC_DETAIL_ROW_KEYS
    return {key: value for key, value in row.items() if key in allowed}


def clean_opportunity_detail(request, category, pk):
    """Rich clean detail with legacy-compatible role boundaries."""
    model = CLEAN_SNAPSHOT_MODELS.get(category)
    if model is None:
        raise Http404("Unknown clean opportunity category")

    item = get_object_or_404(model, pk=pk)
    selected_currency = request.GET.get("currency") or request.COOKIES.get("pricebridge_currency") or "EUR"
    show_internal_gain = can_view_internal_gain(request)
    show_operational_meta = can_view_operational_meta(request)

    full_row = _display_row(
        _snapshot_row(item, category),
        selected_currency,
        show_internal_gain=show_internal_gain,
    )
    row = _restrict_detail_row(
        full_row,
        show_internal_gain=show_internal_gain,
        show_operational_meta=show_operational_meta,
    )

    all_algeria_rows, turkiye_rows = _evidence_rows(item, category, selected_currency)
    algeria_rows = all_algeria_rows if show_internal_gain else []

    coverage = []
    if show_internal_gain:
        coverage.append({"code": "DZ", "count": len(all_algeria_rows), "class": "ok"})
    coverage.append({"code": "TR", "count": len(turkiye_rows), "class": "sh"})

    admin_url = ""
    if show_operational_meta:
        admin_url = reverse(f"admin:market_{item._meta.model_name}_change", args=[item.pk])

    return render(
        request,
        "market/clean_opportunity_detail.html",
        base_context(request, "opportunities")
        | {
            "row": row,
            "coverage": coverage,
            "algeria_rows": algeria_rows,
            "turkiye_rows": turkiye_rows,
            "admin_url": admin_url,
            "can_view_internal_gain": show_internal_gain,
            "can_view_operational_meta": show_operational_meta,
        },
    )
