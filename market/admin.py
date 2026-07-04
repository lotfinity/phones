from django.contrib import admin

from market.models import (
    Brand,
    Category,
    CurrencyRate,
    DeviceVariant,
    InstagramPost,
    MarketListing,
    OCRResult,
    OpportunitySnapshot,
    ProductAsset,
    ProductModel,
    Source,
    SupplierPrice,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "parent")
    search_fields = ("name", "slug")
    list_filter = ("parent",)


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "aliases")
    search_fields = ("name", "aliases")


@admin.register(ProductModel)
class ProductModelAdmin(admin.ModelAdmin):
    list_display = ("canonical_name", "brand", "category", "release_year")
    search_fields = ("canonical_name", "aliases", "brand__name")
    list_filter = ("brand", "category", "release_year")


@admin.register(DeviceVariant)
class DeviceVariantAdmin(admin.ModelAdmin):
    list_display = ("canonical_label", "product_model", "storage_gb", "sim_config", "region", "identity_key")
    search_fields = ("canonical_label", "aliases", "identity_key", "product_model__canonical_name")
    list_filter = ("storage_gb", "sim_config", "region")
    readonly_fields = ("identity_key",)


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "source_type", "country", "username", "active")
    search_fields = ("name", "username", "profile_url", "notes")
    list_filter = ("source_type", "country", "active")


@admin.register(InstagramPost)
class InstagramPostAdmin(admin.ModelAdmin):
    list_display = ("shortcode", "source", "posted_at", "needs_ocr", "ocr_processed", "collected_at")
    search_fields = ("shortcode", "post_url", "caption")
    list_filter = ("source", "needs_ocr", "ocr_processed", "posted_at")
    readonly_fields = ("raw_metadata", "collected_at")


@admin.register(OCRResult)
class OCRResultAdmin(admin.ModelAdmin):
    list_display = (
        "instagram_post",
        "status",
        "reviewed",
        "detected_model_text",
        "detected_price_dzd",
        "confidence",
    )
    search_fields = ("raw_text", "detected_model_text", "detected_condition_text")
    list_filter = ("status", "reviewed")
    list_editable = ("status", "reviewed")


@admin.register(SupplierPrice)
class SupplierPriceAdmin(admin.ModelAdmin):
    list_display = (
        "source",
        "product_model",
        "variant",
        "supplier_price_usd",
        "supplier_price_eur",
        "condition",
        "parsed_confidence",
        "active",
    )
    search_fields = ("raw_text", "product_model__canonical_name", "variant__canonical_label")
    list_filter = ("condition", "active", "source")
    list_editable = ("active",)


@admin.register(MarketListing)
class MarketListingAdmin(admin.ModelAdmin):
    list_display = (
        "source",
        "country",
        "product_model",
        "variant",
        "price_original",
        "currency_original",
        "price_eur",
        "condition",
        "review_status",
        "parsed_confidence",
    )
    search_fields = ("title_raw", "description_raw", "listing_url", "product_model__canonical_name")
    list_filter = ("source_type", "country", "condition", "review_status", "source")
    list_editable = ("review_status",)


@admin.register(CurrencyRate)
class CurrencyRateAdmin(admin.ModelAdmin):
    list_display = ("base_currency", "quote_currency", "rate", "source", "observed_at")
    search_fields = ("base_currency", "quote_currency", "source", "notes")
    list_filter = ("base_currency", "quote_currency", "source")


@admin.register(OpportunitySnapshot)
class OpportunitySnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "product_model",
        "variant",
        "algeria_avg_eur",
        "supplier_eur",
        "margin_percent",
        "confidence_score",
        "recommendation",
        "created_at",
    )
    search_fields = ("product_model__canonical_name", "variant__canonical_label", "explanation")
    list_filter = ("recommendation", "confidence_score", "created_at")


@admin.register(ProductAsset)
class ProductAssetAdmin(admin.ModelAdmin):
    list_display = (
        "product_model",
        "brand",
        "asset_type",
        "source",
        "commons_title",
        "match_score",
        "match_status",
        "is_primary",
        "is_active",
    )
    search_fields = (
        "product_model__canonical_name",
        "brand__name",
        "commons_title",
        "search_query",
    )
    list_filter = ("asset_type", "source", "match_status", "is_primary", "is_active")
    readonly_fields = ("created_at", "updated_at")
