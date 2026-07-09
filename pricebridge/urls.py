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
from market import views

urlpatterns = [
    path('', views.opportunities, name='opportunities'),
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
