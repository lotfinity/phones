from django.conf import settings
from django.urls import path
from django.views.static import serve as serve_static

from market.views_estore import estore_listing_detail, estore_listing_index


urlpatterns = [
    path("", estore_listing_index, name="estore_listing_index"),
    path(
        "listing/<slug:category>/<int:pk>/",
        estore_listing_detail,
        name="estore_listing_detail",
    ),
    path(
        "assets/<path:path>",
        serve_static,
        {"document_root": settings.BASE_DIR / "estoreui" / "assets"},
        name="estore_asset",
    ),
]
