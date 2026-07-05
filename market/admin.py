from django.contrib import admin
from django.db.models import Count, Q
from django.utils.html import format_html

from market.models import (
    Brand,
    Category,
    CurrencyRate,
    DeviceVariant,
    InstagramPost,
    MarketListing,
    MarketListingReviewQueue,
    MarketListingSuggestion,
    OCRResult,
    OpportunitySnapshot,
    ProductAsset,
    ProductModel,
    Source,
    SupplierPrice,
)


def review_reason(obj):
    reasons = []
    if not obj.product_model_id:
        reasons.append("missing model")
    if obj.storage_gb is None:
        reasons.append("missing storage")
    if obj.price_original is None:
        reasons.append("missing price")
    if not (obj.listing_url or "").strip():
        reasons.append("missing URL")
    if not reasons and obj.review_status == MarketListing.ReviewStatus.NEEDS_REVIEW:
        reasons.append("manual review")
    return ", ".join(reasons) or "ok"


class ReviewStatusFilter(admin.SimpleListFilter):
    title = "review bucket"
    parameter_name = "review_bucket"

    def lookups(self, request, model_admin):
        return (
            ("needs_review", "Needs review"),
            ("auto_unusable", "AUTO but incomplete"),
            ("missing_variant", "Missing storage"),
            ("missing_price", "Missing price"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "needs_review":
            return queryset.filter(review_status=MarketListing.ReviewStatus.NEEDS_REVIEW)
        if value == "auto_unusable":
            return queryset.filter(review_status=MarketListing.ReviewStatus.AUTO).filter(
                Q(product_model__isnull=True)
                | Q(storage_gb__isnull=True)
                | Q(price_original__isnull=True)
            )
        if value == "missing_variant":
            return queryset.filter(storage_gb__isnull=True)
        if value == "missing_price":
            return queryset.filter(price_original__isnull=True)
        return queryset


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
    list_display = (
        "canonical_name",
        "brand",
        "category",
        "total_listings",
        "algeria_listings",
        "turkiye_listings",
        "storage_breakdown",
        "release_year",
    )
    search_fields = ("canonical_name", "aliases", "brand__name")
    list_filter = ("brand", "category", "release_year")
    list_select_related = ("brand", "category")

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                total_listing_count=Count("marketlisting", distinct=True),
                algeria_listing_count=Count("marketlisting", filter=Q(marketlisting__country="algeria"), distinct=True),
                turkiye_listing_count=Count("marketlisting", filter=Q(marketlisting__country="turkiye"), distinct=True),
                storage_64_count=Count("marketlisting", filter=Q(marketlisting__storage_gb=64), distinct=True),
                storage_128_count=Count("marketlisting", filter=Q(marketlisting__storage_gb=128), distinct=True),
                storage_256_count=Count("marketlisting", filter=Q(marketlisting__storage_gb=256), distinct=True),
                storage_512_count=Count("marketlisting", filter=Q(marketlisting__storage_gb=512), distinct=True),
                storage_1024_count=Count("marketlisting", filter=Q(marketlisting__storage_gb=1024), distinct=True),
                storage_2048_count=Count("marketlisting", filter=Q(marketlisting__storage_gb=2048), distinct=True),
            )
        )

    @admin.display(ordering="total_listing_count", description="Listings")
    def total_listings(self, obj):
        return obj.total_listing_count

    @admin.display(ordering="algeria_listing_count", description="DZ")
    def algeria_listings(self, obj):
        return obj.algeria_listing_count

    @admin.display(ordering="turkiye_listing_count", description="TR")
    def turkiye_listings(self, obj):
        return obj.turkiye_listing_count

    @admin.display(description="Storage")
    def storage_breakdown(self, obj):
        parts = []
        for storage in (64, 128, 256, 512, 1024, 2048):
            count = getattr(obj, f"storage_{storage}_count", 0)
            if count:
                parts.append(f"{storage}: {count}")
        return ", ".join(parts) or "-"


@admin.register(DeviceVariant)
class DeviceVariantAdmin(admin.ModelAdmin):
    list_display = (
        "canonical_label",
        "product_model",
        "storage_gb",
        "sim_config",
        "total_listings",
        "algeria_listings",
        "turkiye_listings",
        "region",
        "identity_key",
    )
    search_fields = ("canonical_label", "aliases", "identity_key", "product_model__canonical_name")
    list_filter = (
        ("product_model", admin.RelatedOnlyFieldListFilter),
        "storage_gb",
        "sim_config",
        "region",
    )
    readonly_fields = ("identity_key",)
    autocomplete_fields = ("product_model",)
    list_select_related = ("product_model",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                total_listing_count=Count("marketlisting", distinct=True),
                algeria_listing_count=Count("marketlisting", filter=Q(marketlisting__country="algeria"), distinct=True),
                turkiye_listing_count=Count("marketlisting", filter=Q(marketlisting__country="turkiye"), distinct=True),
            )
        )

    @admin.display(ordering="total_listing_count", description="Listings")
    def total_listings(self, obj):
        return obj.total_listing_count

    @admin.display(ordering="algeria_listing_count", description="DZ")
    def algeria_listings(self, obj):
        return obj.algeria_listing_count

    @admin.display(ordering="turkiye_listing_count", description="TR")
    def turkiye_listings(self, obj):
        return obj.turkiye_listing_count


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
        "storage_gb",
        "sim_config",
        "supplier_price_usd",
        "supplier_price_eur",
        "condition",
        "parsed_confidence",
        "active",
    )
    search_fields = ("raw_text", "product_model__canonical_name", "variant__canonical_label")
    list_filter = ("condition", "active", "storage_gb", "sim_config", "source")
    list_editable = ("active",)


@admin.register(MarketListing)
class MarketListingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "short_title",
        "source",
        "source_type",
        "country",
        "product_model",
        "variant",
        "storage_gb",
        "sim_config",
        "price_original",
        "currency_original",
        "condition",
        "review_status",
        "reason",
        "parsed_confidence",
        "open_listing",
    )
    list_display_links = ("id", "short_title")
    search_fields = (
        "title_raw",
        "description_raw",
        "listing_url",
        "product_model__canonical_name",
        "variant__canonical_label",
    )
    list_filter = (
        ReviewStatusFilter,
        "review_status",
        "source_type",
        "country",
        "condition",
        "storage_gb",
        "currency_original",
        ("product_model", admin.RelatedOnlyFieldListFilter),
        ("variant", admin.RelatedOnlyFieldListFilter),
        "source",
    )
    list_editable = ("review_status", "condition")
    list_select_related = ("source", "product_model", "variant")
    autocomplete_fields = ("source", "product_model", "variant")
    readonly_fields = ("observed_at", "parsed_confidence")
    list_per_page = 50
    actions = ("mark_auto", "mark_needs_review", "mark_approved")

    @admin.display(description="Title")
    def short_title(self, obj):
        return (obj.title_raw[:90] + "...") if len(obj.title_raw) > 90 else obj.title_raw

    @admin.display(description="Reason")
    def reason(self, obj):
        return review_reason(obj)

    @admin.display(description="URL")
    def open_listing(self, obj):
        if not obj.listing_url:
            return "-"
        return format_html('<a href="{}" target="_blank" rel="noopener">open</a>', obj.listing_url)

    @admin.action(description="Mark selected listings AUTO")
    def mark_auto(self, request, queryset):
        queryset.update(review_status=MarketListing.ReviewStatus.AUTO)

    @admin.action(description="Mark selected listings NEEDS_REVIEW")
    def mark_needs_review(self, request, queryset):
        queryset.update(review_status=MarketListing.ReviewStatus.NEEDS_REVIEW)

    @admin.action(description="Mark selected listings APPROVED")
    def mark_approved(self, request, queryset):
        queryset.update(review_status=MarketListing.ReviewStatus.APPROVED)


@admin.register(MarketListingReviewQueue)
class MarketListingReviewQueueAdmin(MarketListingAdmin):
    list_display = (
        "id",
        "short_title",
        "source_type",
        "country",
        "product_model",
        "variant",
        "storage_gb",
        "sim_config",
        "price_original",
        "currency_original",
        "condition",
        "review_status",
        "reason",
        "open_listing",
    )
    list_filter = (
        ReviewStatusFilter,
        "source_type",
        "country",
        "condition",
        "storage_gb",
        "currency_original",
        ("product_model", admin.RelatedOnlyFieldListFilter),
        ("variant", admin.RelatedOnlyFieldListFilter),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(review_status=MarketListing.ReviewStatus.NEEDS_REVIEW)
        )


@admin.register(MarketListingSuggestion)
class MarketListingSuggestionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "listing",
        "suggested_product_model",
        "suggested_storage_gb",
        "suggested_sim_config",
        "suggested_condition",
        "confidence",
        "status",
        "created_at",
    )
    search_fields = (
        "listing__title_raw",
        "listing__listing_url",
        "suggested_product_model__canonical_name",
        "reason",
    )
    list_filter = ("status", "suggested_storage_gb", "suggested_condition", "created_at")
    list_select_related = ("listing", "suggested_product_model")
    readonly_fields = ("raw_evidence", "created_at", "updated_at")
    list_per_page = 50


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
