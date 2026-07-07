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
    MarketListingSpecValue,
    MarketListingSuggestion,
    OCRResult,
    OpportunitySnapshot,
    ProductAsset,
    ProductModel,
    ProductType,
    Source,
    SpecDefinition,
    SpecOption,
    SupplierPrice,
    ProductVariantSpecValue,
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


# ---------------------------------------------------------------------------
# Inline classes for spec system (must precede admin classes that reference them)
# ---------------------------------------------------------------------------

class SpecOptionInline(admin.TabularInline):
    model = SpecOption
    extra = 0
    fields = ("value", "normalized_value", "aliases")


class ProductVariantSpecValueInline(admin.TabularInline):
    model = ProductVariantSpecValue
    extra = 0
    fields = ("spec", "option", "value_text", "value_integer", "value_decimal", "value_boolean", "raw_value")
    autocomplete_fields = ("spec", "option")


class MarketListingSpecValueInline(admin.TabularInline):
    model = MarketListingSpecValue
    extra = 0
    fields = ("spec", "option", "value_text", "value_integer", "value_decimal", "value_boolean", "raw_value", "confidence")
    autocomplete_fields = ("spec", "option")


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
    inlines = [ProductVariantSpecValueInline]

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
        "source_type",
        "country",
        "detected_product_type",
        "product_model",
        "variant",
        "match_level_badge",
        "match_confidence",
        "condition",
        "review_status",
        "reason",
        "parsed_confidence",
        "eligible_badge",
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
        "match_level",
        "condition",
        "storage_gb",
        "currency_original",
        ("product_model__product_type", admin.RelatedOnlyFieldListFilter),
        ("product_model", admin.RelatedOnlyFieldListFilter),
        ("variant", admin.RelatedOnlyFieldListFilter),
        "source",
    )
    list_editable = ("review_status", "condition")
    list_select_related = ("source", "product_model", "variant", "product_model__product_type")
    autocomplete_fields = ("source", "product_model", "variant")
    readonly_fields = ("observed_at", "parsed_confidence", "match_level", "match_confidence", "match_reason")
    list_per_page = 50
    actions = ("mark_auto", "mark_needs_review", "mark_approved")
    inlines = [MarketListingSpecValueInline]

    @admin.display(description="Title")
    def short_title(self, obj):
        return (obj.title_raw[:90] + "...") if len(obj.title_raw) > 90 else obj.title_raw

    @admin.display(description="Type")
    def detected_product_type(self, obj):
        if obj.product_model and obj.product_model.product_type:
            return obj.product_model.product_type.slug
        return "-"

    @admin.display(description="Match")
    def match_level_badge(self, obj):
        level = obj.match_level or "unmatched"
        colors = {
            "exact_variant": "green",
            "strong_candidate": "blue",
            "model_only": "orange",
            "unmatched": "gray",
            "conflict": "red",
        }
        color = colors.get(level, "gray")
        return format_html('<span style="color:{};font-weight:bold">{}</span>', color, level)

    @admin.display(description="Eligible")
    def eligible_badge(self, obj):
        from market.models import (
            ALLOW_MODEL_ONLY_OPPORTUNITIES,
            MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY,
            OPPORTUNITY_ELIGIBLE_MATCH_LEVELS,
        )
        if not obj.product_model or not obj.product_model.product_type:
            return format_html('<span style="color:green">YES</span>')
        if obj.product_model.product_type.slug == "phone":
            return format_html('<span style="color:green">YES</span>')
        level = obj.match_level or "unmatched"
        if level in ("unmatched", "conflict"):
            return format_html('<span style="color:red">NO</span>')
        if level == "model_only" and not ALLOW_MODEL_ONLY_OPPORTUNITIES:
            return format_html('<span style="color:red">NO</span>')
        if level not in OPPORTUNITY_ELIGIBLE_MATCH_LEVELS:
            return format_html('<span style="color:red">NO</span>')
        if obj.match_confidence < MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY:
            return format_html('<span style="color:orange">LOW CONF</span>')
        return format_html('<span style="color:green">YES</span>')

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


@admin.register(ProductType)
class ProductTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "spec_count", "description")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_spec_count=Count("spec_definitions"))

    @admin.display(ordering="_spec_count", description="Specs")
    def spec_count(self, obj):
        return obj._spec_count


@admin.register(SpecDefinition)
class SpecDefinitionAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "key",
        "product_type",
        "value_type",
        "unit",
        "is_variant_identity",
        "is_listing_level",
        "is_filterable",
        "is_comparable",
        "sort_order",
    )
    list_filter = ("product_type", "value_type", "is_variant_identity", "is_listing_level")
    search_fields = ("key", "label", "product_type__name")
    list_editable = ("sort_order", "is_variant_identity", "is_listing_level", "is_filterable", "is_comparable")
    inlines = [SpecOptionInline]


@admin.register(SpecOption)
class SpecOptionAdmin(admin.ModelAdmin):
    list_display = ("value", "normalized_value", "spec", "aliases")
    list_filter = ("spec__product_type", "spec")
    search_fields = ("value", "normalized_value", "spec__key")


@admin.register(ProductVariantSpecValue)
class ProductVariantSpecValueAdmin(admin.ModelAdmin):
    list_display = ("variant", "spec", "effective_value", "raw_value")
    list_filter = ("spec__product_type", "spec")
    search_fields = ("variant__canonical_label", "spec__key", "raw_value")
    list_select_related = ("variant", "spec", "option")
    autocomplete_fields = ("variant", "spec", "option")


@admin.register(MarketListingSpecValue)
class MarketListingSpecValueAdmin(admin.ModelAdmin):
    list_display = ("listing", "spec", "effective_value", "confidence", "raw_value")
    list_filter = ("spec__product_type", "spec")
    search_fields = ("listing__title_raw", "spec__key", "raw_value")
    list_select_related = ("listing", "spec", "option")
    autocomplete_fields = ("listing", "spec", "option")
