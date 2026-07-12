from django.conf import settings
from django.urls import path
from django.views.static import serve as serve_static

from market.cache_control import private_no_store
from market.views_estore import estore_opportunity_detail, estore_opportunity_index


urlpatterns = [
    path(
        "",
        private_no_store(estore_opportunity_index),
        name="estore_opportunity_index",
    ),
    path(
        "opportunity/<slug:category>/<int:pk>/",
        private_no_store(estore_opportunity_detail),
        name="estore_opportunity_detail",
    ),
    path(
        "assets/<path:path>",
        serve_static,
        {"document_root": settings.BASE_DIR / "estoreui" / "assets"},
        name="estore_asset",
    ),
]
