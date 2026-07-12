from __future__ import annotations

from django.db.models import Model
from django.http import Http404
from django.shortcuts import get_object_or_404

from market.bagisto_source import render_bagisto_source
from market.views_clean import (
    _display_row,
    _evidence_rows,
    _snapshot_row,
    can_view_internal_gain,
    can_view_operational_meta,
)
from market.views_clean_detail import _restrict_detail_row
from market.views_estore import (
    OPPORTUNITY_CONFIG,
    _combined_specs,
    _filtered_items,
    _opportunity_card,
    _prepare_evidence,
    _primary_listing,
    _selected_currency,
)


INDEX_SOURCES = [
    "pages/smartphones-preview.html",
    "pages/smartphones.html",
]

DETAIL_SOURCES = [
    "pages/products/smartphone-earphone-bundle-preview.html",
    "pages/products/smartphone-earphone-bundle.html",
]


def _json_payload(value):
    """Remove Django model instances before embedding data as JSON in HTML."""
    if isinstance(value, Model):
        return None
    if isinstance(value, dict):
        return {
            key: _json_payload(item)
            for key, item in value.items()
            if not isinstance(item, Model)
        }
    if isinstance(value, (list, tuple, set)):
        return [
            _json_payload(item)
            for item in value
            if not isinstance(item, Model)
        ]
    return value


def _evidence_payload(rows):
    result = []
    for row in rows:
        item = row.get("item")
        result.append(
            {
                "title": row.get("title", ""),
                "listing_url": row.get("listing_url", ""),
                "image_url": row.get("image_url", ""),
                "source_code": row.get("source_code", ""),
                "source_name": row.get("source_name", ""),
                "country": row.get("country", ""),
                "country_label": row.get("country_label", ""),
                "condition": row.get("condition", ""),
                "observed_at": row.get("observed_at"),
                "price_original": row.get("price_original"),
                "currency_original": row.get("currency_original", ""),
                "price_eur": row.get("price_eur", ""),
                "spec": row.get("spec", ""),
                "parsed_confidence": row.get("parsed_confidence"),
                "has_image": row.get("has_image", False),
                "proxy_image_url": row.get("image_url", ""),
                "listing_id": item.pk if item is not None else None,
            }
        )
    return result


def estore_bagisto_opportunity_index(request):
    selected_currency = _selected_currency(request)
    show_internal_gain = can_view_internal_gain(request)
    items, active_category, query = _filtered_items(request)

    cards = [
        _opportunity_card(
            item,
            category,
            selected_currency,
            show_internal_gain=show_internal_gain,
        )
        for category, item in items
    ]

    counts = {
        category: config["model"].objects.count()
        for category, config in OPPORTUNITY_CONFIG.items()
    }

    payload = _json_payload(
        {
            "page": "opportunity-index",
            "frontend": "preserved-bagisto-port",
            "cards": cards,
            "total_count": len(cards),
            "counts": counts,
            "active_category": active_category,
            "query": query,
            "selected_currency": selected_currency,
            "can_view_internal_gain": show_internal_gain,
            "urls": {
                "index": "/estore/",
                "phone": "/estore/?category=phone",
                "laptop": "/estore/?category=laptop",
                "console": "/estore/?category=console",
            },
        }
    )

    return render_bagisto_source(
        request,
        candidates=INDEX_SOURCES,
        payload=payload,
        page_title="PriceBridge Fırsatlar",
    )


def estore_bagisto_opportunity_detail(request, category, pk):
    config = OPPORTUNITY_CONFIG.get(category)
    if config is None:
        raise Http404("Bilinmeyen fırsat kategorisi")

    item = get_object_or_404(config["model"], pk=pk)
    selected_currency = _selected_currency(request)
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

    primary = _primary_listing(item, category)
    card = _opportunity_card(
        item,
        category,
        selected_currency,
        show_internal_gain=show_internal_gain,
    )

    all_algeria_rows, all_turkiye_rows = _evidence_rows(item, category, selected_currency)
    algeria_rows = _prepare_evidence(all_algeria_rows, category) if show_internal_gain else []
    turkiye_rows = _prepare_evidence(all_turkiye_rows, category)

    opportunity = row | card | {
        "specs": _combined_specs(item, category, primary),
        "coverage": {
            "algeria": item.algeria_count,
            "turkiye": item.turkiye_count,
        },
        "generated_at": item.generated_at,
        "source_label": item.source_label if show_operational_meta else "",
    }

    payload = _json_payload(
        {
            "page": "opportunity-detail",
            "frontend": "preserved-bagisto-port",
            "opportunity": opportunity,
            "algeria_rows": _evidence_payload(algeria_rows),
            "turkiye_rows": _evidence_payload(turkiye_rows),
            "selected_currency": selected_currency,
            "can_view_internal_gain": show_internal_gain,
            "can_view_operational_meta": show_operational_meta,
            "urls": {
                "index": "/estore/",
                "category": f"/estore/?category={category}",
            },
        }
    )

    return render_bagisto_source(
        request,
        candidates=DETAIL_SOURCES,
        payload=payload,
        page_title=f"{opportunity['title']} · PriceBridge",
    )
