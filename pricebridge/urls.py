"""
URL configuration for pricebridge project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from django.views.generic import TemplateView

from market import views
from market.cache_control import private_no_store
from market.views_clean import clean_card_opportunities, clean_opportunities, clean_opportunity_detail
from market.views_images import clean_listing_image
from market.views_phone_opportunities import phone_opportunities_v2

urlpatterns = [
    path('', clean_opportunities, name='opportunities'),

    # Side-by-side frontend review routes. These aliases intentionally leave
    # the public routes unchanged while each UI variant is evaluated.
    path(
        'ui-preview/',
        TemplateView.as_view(
            template_name='market/ui_preview.html',
            extra_context={'active': 'opportunities'},
        ),
        name='ui_preview',
    ),
    path(
        'ui-preview/clean-opportunities/',
        clean_opportunities,
        name='ui_preview_clean_opportunities',
    ),
    path(
        'ui-preview/card-opportunities/',
        private_no_store(clean_card_opportunities),
        name='ui_preview_card_opportunities',
    ),
    path(
        'ui-preview/card-opportunities/<slug:category>/<int:pk>/',
        private_no_store(clean_opportunity_detail),
        name='clean_opportunity_detail',
    ),
    path(
        'image-proxy/clean-listing/<slug:category>/<int:pk>/',
        clean_listing_image,
        name='clean_listing_image',
    ),
    path(
        'ui-preview/phone-opportunities/',
        phone_opportunities_v2,
        name='ui_preview_phone_opportunities',
    ),
    path(
        'ui-preview/deals/',
        views.deals_swiper,
        name='ui_preview_deals',
    ),

    path('phone-opportunities/', phone_opportunities_v2, name='phone_opportunities_v2'),
    path('opportunities/<int:pk>/', views.opportunity_detail, name='opportunity_detail'),
    path('listings/', views.listings, name='listings'),
    path('deals/', views.deals_swiper, name='deals_swiper'),
    path('deals/more/', views.deals_more, name='deals_more'),
    path('api/deals/', views.deals_api, name='deals_api'),
    path('data-quality/', views.data_quality, name='data_quality'),
    path('import-lab/', views.import_lab, name='import_lab'),
    path('import-lab/candidate/<int:pk>/', views.candidate_detail, name='candidate_detail'),
    path('sources/', views.sources, name='sources'),
    path('api/inline-edit/<slug:model_key>/', views.inline_edit_api, name='inline_edit_api'),
    path('api/listing-bulk/', views.listing_bulk_api, name='listing_bulk_api'),
    path('i18n/set-language/', views.set_language, name='set_language'),
    path('i18n/set-currency/', views.set_currency, name='set_currency'),
    path('admin/', admin.site.urls),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG and settings.STATICFILES_DIRS:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])

if settings.DEBUG and getattr(settings, "DEBUG_TOOLBAR_AVAILABLE", False):
    urlpatterns.append(path("__debug__/", include("debug_toolbar.urls")))
