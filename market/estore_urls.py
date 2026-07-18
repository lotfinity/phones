from django.conf import settings
from django.urls import path
from django.views.static import serve as serve_static

from market.cache_control import private_no_store
from market.views_estore import (
    estore_api_fx_rates,
    estore_api_fx_refresh,
    estore_api_opportunity_detail,
    estore_api_opportunity_index,
    estore_opportunity_detail,
    estore_opportunity_index,
)
from market.views_estore_bagisto import (
    estore_bagisto_opportunity_detail,
    estore_bagisto_opportunity_index,
)


urlpatterns = [
    path(
        "",
        private_no_store(estore_opportunity_index),
        name="estore_opportunity_index",
    ),
    path(
        "api/opportunities/",
        private_no_store(estore_api_opportunity_index),
        name="estore_api_opportunity_index",
    ),
    path(
        "api/opportunities/<slug:category>/<int:pk>/",
        private_no_store(estore_api_opportunity_detail),
        name="estore_api_opportunity_detail",
    ),
    path(
        "api/fx/",
        private_no_store(estore_api_fx_rates),
        name="estore_api_fx_rates",
    ),
    path(
        "api/fx/refresh/",
        private_no_store(estore_api_fx_refresh),
        name="estore_api_fx_refresh",
    ),
    path(
        "opportunity/<slug:category>/<int:pk>/",
        private_no_store(estore_opportunity_detail),
        name="estore_opportunity_detail",
    ),
    path(
        "bagisto/",
        private_no_store(estore_bagisto_opportunity_index),
        name="estore_bagisto_opportunity_index",
    ),
    path(
        "bagisto/opportunity/<slug:category>/<int:pk>/",
        private_no_store(estore_bagisto_opportunity_detail),
        name="estore_bagisto_opportunity_detail",
    ),
    path(
        "assets/<path:path>",
        serve_static,
        {"document_root": settings.BASE_DIR / "estoreui" / "assets"},
        name="estore_asset",
    ),
]
