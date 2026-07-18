from __future__ import annotations

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse

from market.bagisto_source import render_bagisto_source
from market.views_estore import (
    OPPORTUNITY_CONFIG,
    _estore_detail_payload,
)


INDEX_SOURCES = [
    "pages/smartphones-preview.html",
    "pages/smartphones.html",
]

DETAIL_SOURCES = [
    "pages/products/speakers-preview.html",
    "pages/products/speakers.html",
    "pages/products/computer-monitor-preview.html",
    "pages/products/computer-monitor.html",
]


def _frontend_detail_url(category, pk):
    return reverse(
        "estore_frontend_opportunity_detail",
        kwargs={"category": category, "pk": pk},
    )


def estore_bagisto_opportunity_index(request):
    return render_bagisto_source(
        request,
        candidates=INDEX_SOURCES,
        payload={
            "page": "opportunity-index",
            "frontend": "api-driven-bagisto-port",
            "urls": {
                "index": "/",
                "phone": "/?category=phone",
                "laptop": "/?category=laptop",
                "console": "/?category=console",
            },
        },
        page_title="PriceBridge Fırsatlar",
    )


def estore_bagisto_opportunity_detail(request, category, pk):
    config = OPPORTUNITY_CONFIG.get(category)
    if config is None:
        raise Http404("Bilinmeyen fırsat kategorisi")

    item = get_object_or_404(config["model"], pk=pk)
    detail_payload = _estore_detail_payload(request, category, item.pk)
    detail = detail_payload["detail"]
    description_rows = [
        {"label": "Brand", "value": detail.get("brand")},
        {"label": "Model", "value": detail.get("model")},
        {"label": "Category", "value": detail.get("category_label")},
        {"label": "Recommendation", "value": detail.get("recommendation")},
        {"label": "PriceBridge Offer", "value": detail.get("buyer_offer")},
        {"label": "Türkiye Average", "value": detail.get("turkiye_avg")},
    ] + detail.get("detail_specs", [])

    return render_bagisto_source(
        request,
        candidates=DETAIL_SOURCES,
        payload={
            "page": "opportunity-detail",
            "frontend": "api-driven-bagisto-port",
            "api_url": reverse(
                "estore_api_opportunity_detail",
                kwargs={"category": category, "pk": item.pk},
            ),
            "detail_specs": detail.get("detail_specs", []),
            "detail_description_rows": description_rows,
            "turkiye_rows": detail_payload.get("turkiye_rows", []),
            "urls": {
                "index": "/",
                "category": f"/?category={category}",
                "phone": "/?category=phone",
                "laptop": "/?category=laptop",
                "console": "/?category=console",
            },
        },
        page_title="PriceBridge Fırsat Detayı",
    )
