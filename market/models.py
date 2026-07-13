import json
import re
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Country(models.TextChoices):
    ALGERIA = "algeria", "Algeria"
    TURKIYE = "turkiye", "Türkiye"
    OTHER = "other", "Other"


class SourceType(models.TextChoices):
    INSTAGRAM = "instagram", "Instagram"
    SUPPLIER = "supplier", "Supplier"
    SAHIBINDEN = "sahibinden", "Sahibinden"
    OUEDKNISS = "ouedkniss", "Ouedkniss"
    MANUAL = "manual", "Manual"


class Condition(models.TextChoices):
    SEALED = "sealed", "Sealed"
    USED_A_PLUS = "used_a_plus", "Used A+"
    USED_A = "used_a", "Used A"
    USED_B = "used_b", "Used B"
    USED_C = "used_c", "Used C"
    USED = "used", "Used"
    UNKNOWN = "unknown", "Unknown"


# ── Confidence gates for opportunity analysis ────────────────────────────────
# Match levels eligible for automatic opportunity analysis.
OPPORTUNITY_ELIGIBLE_MATCH_LEVELS = frozenset({
    "exact_variant",
    "strong_candidate",
})
# Minimum match_confidence for opportunity analysis (0.0–1.0).
MIN_MATCH_CONFIDENCE_FOR_OPPORTUNITY = 0.70
# Allow model_only matches in opportunity analysis (without variant).
ALLOW_MODEL_ONLY_OPPORTUNITIES = False


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=120, unique=True)
    aliases = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ProductModel(models.Model):
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL)
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.SET_NULL)
    product_type = models.ForeignKey("ProductType", null=True, blank=True, on_delete=models.SET_NULL)
    canonical_name = models.CharField(max_length=180)
    aliases = models.JSONField(default=list, blank=True)
    release_year = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["canonical_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "canonical_name"],
                name="unique_product_model_per_brand",
            )
        ]

    def __str__(self):
        return self.canonical_name


def normalize_variant_text(value):
    return re.sub(r"\s+", " ", (value or "").strip())


def normalize_sim_config(value):
    text = normalize_variant_text(value).lower()
    compact = re.sub(r"[\s_-]+", "", text)
    if not compact or compact in {"1sim", "singlesim"}:
        return ""
    if compact in {"2sim", "dualsim", "duos", "çiftsim", "ciftsim"}:
        return "2sim"
    if compact in {"esim", "e-sim"}:
        return "esim"
    return compact


def build_device_variant_identity(storage_gb=None, sim_config="", region="", color=""):
    return "|".join(
        [
            f"storage={storage_gb or ''}",
            f"sim={normalize_sim_config(sim_config)}",
            f"region={normalize_variant_text(region).lower()}",
            f"color={normalize_variant_text(color).lower()}",
        ]
    )


class DeviceVariant(models.Model):
    class Storage(models.IntegerChoices):
        GB_64 = 64, "64 GB"
        GB_128 = 128, "128 GB"
        GB_256 = 256, "256 GB"
        GB_512 = 512, "512 GB"
        GB_1024 = 1024, "1024 GB"
        GB_2048 = 2048, "2048 GB"

    product_model = models.ForeignKey(ProductModel, on_delete=models.CASCADE)
    storage_gb = models.PositiveSmallIntegerField(choices=Storage.choices, null=True, blank=True)
    color = models.CharField(max_length=80, blank=True)
    sim_config = models.CharField(max_length=80, blank=True)
    region = models.CharField(max_length=80, blank=True)
    canonical_label = models.CharField(max_length=220)
    identity_key = models.CharField(max_length=160, blank=True, editable=False, db_index=True)
    aliases = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["product_model__canonical_name", "storage_gb", "canonical_label"]
        constraints = [
            models.UniqueConstraint(
                fields=["product_model", "identity_key"],
                name="unique_device_variant_identity_per_model",
            )
        ]

    def __str__(self):
        return self.canonical_label

    def save(self, *args, **kwargs):
        self.sim_config = normalize_sim_config(self.sim_config)
        self.region = normalize_variant_text(self.region)
        self.color = normalize_variant_text(self.color)
        self.identity_key = build_device_variant_identity(
            self.storage_gb,
            self.sim_config,
            self.region,
            self.color,
        )
        super().save(*args, **kwargs)


class Source(models.Model):
    name = models.CharField(max_length=160)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    country = models.CharField(max_length=20, choices=Country.choices, default=Country.OTHER)
    profile_url = models.URLField(blank=True)
    username = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["source_type", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "username"],
                name="unique_source_type_username",
            )
        ]

    def __str__(self):
        return self.name


class InstagramPost(models.Model):
    source = models.ForeignKey(Source, on_delete=models.CASCADE)
    post_url = models.URLField(unique=True)
    shortcode = models.CharField(max_length=80, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    caption = models.TextField(blank=True)
    media_local_path = models.CharField(max_length=500, blank=True)
    thumbnail_local_path = models.CharField(max_length=500, blank=True)
    raw_metadata = models.JSONField(default=dict, blank=True)
    collected_at = models.DateTimeField(default=timezone.now)
    needs_ocr = models.BooleanField(default=False)
    ocr_processed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-posted_at", "-collected_at"]

    def __str__(self):
        return self.shortcode or self.post_url


class OCRResult(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"
        NEEDS_REVIEW = "needs_review", "Needs review"

    instagram_post = models.ForeignKey(InstagramPost, on_delete=models.CASCADE)
    raw_text = models.TextField(blank=True)
    confidence = models.FloatField(null=True, blank=True)
    detected_price_dzd = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    detected_model_text = models.CharField(max_length=220, blank=True)
    detected_storage_text = models.CharField(max_length=80, blank=True)
    detected_battery_text = models.CharField(max_length=80, blank=True)
    detected_condition_text = models.CharField(max_length=120, blank=True)
    detected_sim_text = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    reviewed = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"OCR {self.instagram_post_id} {self.status}"


class SupplierPrice(models.Model):
    class SupplierCondition(models.TextChoices):
        SEALED = "sealed", "Sealed"
        USED = "used", "Used"
        UNKNOWN = "unknown", "Unknown"

    raw_text = models.TextField()
    source = models.ForeignKey(Source, on_delete=models.CASCADE)
    product_model = models.ForeignKey(ProductModel, null=True, blank=True, on_delete=models.SET_NULL)
    variant = models.ForeignKey(DeviceVariant, null=True, blank=True, on_delete=models.SET_NULL)
    storage_gb = models.PositiveSmallIntegerField(choices=DeviceVariant.Storage.choices, null=True, blank=True)
    sim_config = models.CharField(max_length=80, blank=True)
    supplier_price_usd = models.DecimalField(max_digits=12, decimal_places=2)
    supplier_price_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    condition = models.CharField(max_length=20, choices=SupplierCondition.choices, default=SupplierCondition.UNKNOWN)
    parsed_confidence = models.FloatField(default=0)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.raw_text[:60]} ({self.supplier_price_usd} USD)"

    def save(self, *args, **kwargs):
        self.sim_config = normalize_sim_config(self.sim_config)
        super().save(*args, **kwargs)


class MarketListing(models.Model):
    class Currency(models.TextChoices):
        DZD = "DZD", "DZD"
        USD = "USD", "USD"
        EUR = "EUR", "EUR"
        TRY = "TRY", "TRY"

    class ReviewStatus(models.TextChoices):
        AUTO = "auto", "Auto"
        NEEDS_REVIEW = "needs_review", "Needs review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    source = models.ForeignKey(Source, on_delete=models.CASCADE)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    country = models.CharField(max_length=20, choices=Country.choices)
    product_model = models.ForeignKey(ProductModel, null=True, blank=True, on_delete=models.SET_NULL)
    variant = models.ForeignKey(DeviceVariant, null=True, blank=True, on_delete=models.SET_NULL)
    storage_gb = models.PositiveSmallIntegerField(choices=DeviceVariant.Storage.choices, null=True, blank=True)
    title_raw = models.CharField(max_length=300, blank=True)
    description_raw = models.TextField(blank=True)
    price_original = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency_original = models.CharField(max_length=3, choices=Currency.choices, default=Currency.DZD)
    price_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    condition = models.CharField(max_length=20, choices=Condition.choices, default=Condition.UNKNOWN)
    battery_health = models.PositiveSmallIntegerField(null=True, blank=True)
    battery_cycles = models.PositiveIntegerField(null=True, blank=True)
    sim_config = models.CharField(max_length=80, blank=True)
    box_status = models.CharField(max_length=120, blank=True)
    listing_url = models.URLField(blank=True)
    image_path = models.CharField(max_length=500, blank=True)
    observed_at = models.DateTimeField(default=timezone.now)
    parsed_confidence = models.FloatField(default=0)
    review_status = models.CharField(max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.NEEDS_REVIEW)

    # Phase 3: match quality tracking
    class MatchLevel(models.TextChoices):
        EXACT_VARIANT = "exact_variant", "Exact variant"
        STRONG_CANDIDATE = "strong_candidate", "Strong candidate"
        MODEL_ONLY = "model_only", "Model only"
        UNMATCHED = "unmatched", "Unmatched"
        CONFLICT = "conflict", "Conflict"

    match_level = models.CharField(
        max_length=20,
        choices=MatchLevel.choices,
        default=MatchLevel.UNMATCHED,
        blank=True,
        db_index=True,
    )
    match_confidence = models.FloatField(default=0)
    match_reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-observed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "listing_url"],
                name="unique_market_listing_source_url",
            )
        ]

    def __str__(self):
        return self.title_raw or self.listing_url or f"Listing {self.pk}"

    def save(self, *args, **kwargs):
        self.sim_config = normalize_sim_config(self.sim_config)
        super().save(*args, **kwargs)


class MarketListingReviewQueue(MarketListing):
    class Meta:
        proxy = True
        verbose_name = "listing needing review"
        verbose_name_plural = "listings needing review"


class MarketListingSuggestion(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPLIED = "applied", "Applied"
        REJECTED = "rejected", "Rejected"

    listing = models.ForeignKey(MarketListing, related_name="suggestions", on_delete=models.CASCADE)
    suggested_product_model = models.ForeignKey(ProductModel, null=True, blank=True, on_delete=models.SET_NULL)
    suggested_storage_gb = models.PositiveSmallIntegerField(
        choices=DeviceVariant.Storage.choices,
        null=True,
        blank=True,
    )
    suggested_sim_config = models.CharField(max_length=80, blank=True)
    suggested_condition = models.CharField(max_length=20, choices=Condition.choices, blank=True)
    confidence = models.FloatField(default=0)
    reason = models.TextField(blank=True)
    raw_evidence = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["listing", "status"]),
        ]

    def __str__(self):
        return f"Suggestion for listing {self.listing_id} ({self.status})"

    def save(self, *args, **kwargs):
        self.suggested_sim_config = normalize_sim_config(self.suggested_sim_config)
        super().save(*args, **kwargs)


class CurrencyRate(models.Model):
    base_currency = models.CharField(max_length=3)
    quote_currency = models.CharField(max_length=3)
    rate = models.DecimalField(max_digits=14, decimal_places=6)
    source = models.CharField(max_length=120, blank=True)
    observed_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-observed_at"]

    def __str__(self):
        return f"{self.base_currency}/{self.quote_currency} {self.rate}"


class OpportunitySnapshot(models.Model):
    class Recommendation(models.TextChoices):
        BUY = "buy", "Buy"
        WATCH = "watch", "Watch"
        IGNORE = "ignore", "Ignore"
        INSUFFICIENT_DATA = "insufficient_data", "Insufficient data"

    product_model = models.ForeignKey(ProductModel, on_delete=models.CASCADE)
    variant = models.ForeignKey(DeviceVariant, null=True, blank=True, on_delete=models.SET_NULL)
    storage_gb = models.PositiveSmallIntegerField(choices=DeviceVariant.Storage.choices, null=True, blank=True)
    sim_config = models.CharField(max_length=80, blank=True)
    algeria_min_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    algeria_avg_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    supplier_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    sahibinden_avg_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    gross_margin_vs_supplier_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    gross_margin_vs_sahibinden_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    supplier_margin_percent = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    margin_percent = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    confidence_score = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    recommendation = models.CharField(
        max_length=30,
        choices=Recommendation.choices,
        default=Recommendation.INSUFFICIENT_DATA,
    )
    explanation = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.product_model} {self.variant or ''} {self.recommendation}".strip()

    def save(self, *args, **kwargs):
        self.sim_config = normalize_sim_config(self.sim_config)
        super().save(*args, **kwargs)

    # ---- Gain-split tiers (edit these to adjust commission behaviour) ----
    # Each tuple: (upper_margin_threshold, my_gain_percent, buyer_min_gain_eur)
    # Tiers are evaluated top-to-bottom; first match wins.
    GAIN_SPLIT_TIERS = [
        (Decimal("50"), Decimal("0"), Decimal("0")),
        (Decimal("100"), Decimal("0.20"), Decimal("35")),
        (Decimal("250"), Decimal("0.25"), Decimal("60")),
        (Decimal("500"), Decimal("0.35"), Decimal("100")),
        (None, Decimal("0.50"), Decimal("150")),
    ]
    GOOD_DEAL_GROSS_FLOOR_EUR = Decimal("150")
    SUPPLIER_BUYER_DISCOUNT_USD = Decimal("100")

    def gain_split(self):
        from market.services.gain_split import compute_gain_split

        return compute_gain_split(
            algeria_min_eur=self.algeria_min_eur,
            turkiye_avg_eur=self.sahibinden_avg_eur,
            gross_margin_eur=self.gross_margin_vs_sahibinden_eur,
            supplier_eur=self.supplier_eur,
        )


class DealSnapshot(models.Model):
    listing = models.ForeignKey("MarketListing", on_delete=models.CASCADE, related_name="deal_snapshots")
    brand_name = models.CharField(max_length=120, db_index=True)
    model_name = models.CharField(max_length=200)
    storage_gb = models.PositiveSmallIntegerField(null=True, blank=True)
    title = models.CharField(max_length=500)

    price_original = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    currency_original = models.CharField(max_length=8, blank=True)
    price_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    price_try = models.FloatField(null=True, blank=True)
    price_usd = models.FloatField(null=True, blank=True)
    price_dzd = models.FloatField(null=True, blank=True)

    condition = models.CharField(max_length=40, blank=True)
    source_code = models.CharField(max_length=10, blank=True)
    source_name = models.CharField(max_length=200, blank=True)
    image_url = models.URLField(max_length=1000, blank=True)
    listing_url = models.URLField(max_length=1000, blank=True)
    observed_at = models.DateTimeField(null=True, blank=True)

    sah_median = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    sah_median_eur = models.FloatField(null=True, blank=True)
    sah_median_usd = models.FloatField(null=True, blank=True)
    sah_median_dzd = models.FloatField(null=True, blank=True)
    sah_min = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    sah_max = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    sah_count = models.PositiveIntegerField(default=0)
    sah_urls = models.JSONField(default=list, blank=True)

    supplier_usd = models.FloatField(null=True, blank=True)
    supplier_eur = models.FloatField(null=True, blank=True)
    supplier_try = models.FloatField(null=True, blank=True)
    supplier_dzd = models.FloatField(null=True, blank=True)

    margin_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    margin_pct = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["brand_name", "-margin_pct"]),
            models.Index(fields=["-margin_pct"]),
            models.Index(fields=["listing"]),
        ]
        ordering = ["-margin_pct"]

    def __str__(self):
        return f"{self.brand_name} {self.model_name} margin={self.margin_pct}"

    @property
    def model(self):
        return self.model_name

    @property
    def sah_urls_json(self):
        return json.dumps(self.sah_urls)


class ProductAsset(models.Model):
    class AssetType(models.TextChoices):
        MODEL_LOGO = "model_logo", "Model logo"
        SERIES_LOGO = "series_logo", "Series logo"
        BRAND_LOGO = "brand_logo", "Brand logo"
        PRODUCT_IMAGE = "product_image", "Product image"
        PLACEHOLDER = "placeholder", "Placeholder"

    class Source(models.TextChoices):
        WIKIMEDIA_COMMONS = "wikimedia_commons", "Wikimedia Commons"
        MANUAL = "manual", "Manual"
        INSTAGRAM = "instagram", "Instagram"
        MARKETPLACE = "marketplace", "Marketplace"
        PLACEHOLDER = "placeholder", "Placeholder"

    class MatchStatus(models.TextChoices):
        MATCHED = "matched", "Matched"
        WEAK_MATCH = "weak_match", "Weak match"
        NO_MATCH = "no_match", "No match"
        FAILED = "failed", "Failed"
        MANUAL_REVIEW = "manual_review", "Manual review"

    product_model = models.ForeignKey(ProductModel, null=True, blank=True, on_delete=models.SET_NULL)
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.SET_NULL)
    variant = models.ForeignKey(DeviceVariant, null=True, blank=True, on_delete=models.SET_NULL)

    asset_type = models.CharField(max_length=20, choices=AssetType.choices, default=AssetType.MODEL_LOGO)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.WIKIMEDIA_COMMONS)

    commons_title = models.CharField(max_length=300, blank=True)
    commons_file_url = models.URLField(blank=True)
    commons_page_url = models.URLField(blank=True)
    local_file = models.CharField(max_length=500, blank=True)

    mime_type = models.CharField(max_length=80, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    file_size = models.PositiveIntegerField(null=True, blank=True)

    license_short = models.CharField(max_length=120, blank=True)
    license_url = models.URLField(blank=True)
    usage_terms = models.CharField(max_length=200, blank=True)
    attribution = models.TextField(blank=True)
    artist = models.CharField(max_length=300, blank=True)
    credit = models.TextField(blank=True)
    restrictions = models.CharField(max_length=300, blank=True)

    search_query = models.CharField(max_length=300, blank=True)
    match_score = models.IntegerField(default=0)
    match_status = models.CharField(max_length=20, choices=MatchStatus.choices, default=MatchStatus.NO_MATCH)

    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    raw_metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-match_score", "-is_primary", "-created_at"]

    def __str__(self):
        label = self.commons_title or self.local_file or f"Asset {self.pk}"
        return f"{self.asset_type}: {label}"

    def get_effective_logo(self):
        if self.is_active and self.is_primary and self.match_status in (
            self.MatchStatus.MATCHED,
            self.MatchStatus.WEAK_MATCH,
        ):
            return self
        return None


# ---------------------------------------------------------------------------
# Generic typed spec system
# ---------------------------------------------------------------------------


class ProductType(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SpecDefinition(models.Model):
    class ValueType(models.TextChoices):
        TEXT = "text", "Text"
        INTEGER = "integer", "Integer"
        DECIMAL = "decimal", "Decimal"
        BOOLEAN = "boolean", "Boolean"
        OPTION = "option", "Option"
        MULTI_OPTION = "multi_option", "Multi option"

    product_type = models.ForeignKey(
        ProductType, related_name="spec_definitions", on_delete=models.CASCADE
    )
    key = models.SlugField(max_length=120)
    label = models.CharField(max_length=160)
    value_type = models.CharField(max_length=20, choices=ValueType.choices)
    unit = models.CharField(max_length=40, blank=True)
    is_variant_identity = models.BooleanField(default=False)
    is_listing_level = models.BooleanField(default=False)
    is_filterable = models.BooleanField(default=True)
    is_comparable = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    aliases = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["product_type", "sort_order", "key"]
        constraints = [
            models.UniqueConstraint(
                fields=["product_type", "key"],
                name="unique_spec_key_per_product_type",
            )
        ]

    def __str__(self):
        return f"{self.product_type}: {self.label} ({self.key})"


class SpecOption(models.Model):
    spec = models.ForeignKey(
        SpecDefinition, related_name="options", on_delete=models.CASCADE
    )
    value = models.CharField(max_length=160)
    normalized_value = models.CharField(max_length=160, db_index=True)
    aliases = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["spec", "normalized_value"]
        constraints = [
            models.UniqueConstraint(
                fields=["spec", "normalized_value"],
                name="unique_spec_option_per_spec",
            )
        ]

    def __str__(self):
        return f"{self.spec.key}: {self.value}"


class ProductVariantSpecValue(models.Model):
    variant = models.ForeignKey(
        "DeviceVariant", related_name="spec_values", on_delete=models.CASCADE
    )
    spec = models.ForeignKey(SpecDefinition, on_delete=models.CASCADE)
    option = models.ForeignKey(
        SpecOption, null=True, blank=True, on_delete=models.SET_NULL
    )
    value_text = models.TextField(blank=True)
    value_integer = models.IntegerField(null=True, blank=True)
    value_decimal = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True
    )
    value_boolean = models.BooleanField(null=True, blank=True)
    raw_value = models.CharField(max_length=240, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["variant", "spec"],
                name="unique_variant_spec_value",
            )
        ]

    def __str__(self):
        return f"Variant {self.variant_id} {self.spec.key}={self.effective_value}"

    @property
    def effective_value(self):
        if self.option:
            return self.option.value
        if self.value_boolean is not None:
            return self.value_boolean
        if self.value_integer is not None:
            return self.value_integer
        if self.value_decimal is not None:
            return self.value_decimal
        return self.value_text


class ListingConditionAudit(models.Model):
    class ConditionClass(models.TextChoices):
        SEALED_NEW = "sealed_new", "Sealed / New"
        CLEAN_USED = "clean_used", "Clean Used"
        ISSUE_USED = "issue_used", "Issue Used"
        UNKNOWN = "unknown", "Unknown / Unaudited"

    class Verdict(models.TextChoices):
        KEEP = "keep", "Keep"
        WATCH = "watch", "Watch"
        REJECT = "reject", "Reject"

    TR_LABELS = {
        ConditionClass.SEALED_NEW: "Kapalı Kutu",
        ConditionClass.CLEAN_USED: "Temiz İkinci El",
        ConditionClass.ISSUE_USED: "Riskli İkinci El",
        ConditionClass.UNKNOWN: "İncelenmemiş",
    }

    listing = models.OneToOneField(
        "MarketListing",
        related_name="condition_audit",
        on_delete=models.CASCADE,
    )
    condition_class = models.CharField(
        max_length=20,
        choices=ConditionClass.choices,
        default=ConditionClass.UNKNOWN,
        db_index=True,
    )
    verdict = models.CharField(max_length=10, choices=Verdict.choices, default=Verdict.WATCH)
    confidence = models.PositiveSmallIntegerField(default=0)
    red_flags = models.JSONField(default=list, blank=True)
    reasons = models.JSONField(default=list, blank=True)
    structured_vision = models.JSONField(null=True, blank=True)
    freeform_vision_text = models.TextField(blank=True)
    image_source = models.TextField(blank=True)
    model_used = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Listing {self.listing_id}: {self.condition_class} ({self.verdict})"

    @property
    def condition_label_tr(self):
        return self.TR_LABELS.get(self.condition_class, "Bilinmeyen")

    @property
    def is_clean_for_comparison(self):
        return self.condition_class in {
            self.ConditionClass.SEALED_NEW,
            self.ConditionClass.CLEAN_USED,
        }


class MarketListingSpecValue(models.Model):
    listing = models.ForeignKey(
        "MarketListing", related_name="spec_values", on_delete=models.CASCADE
    )
    spec = models.ForeignKey(SpecDefinition, on_delete=models.CASCADE)
    option = models.ForeignKey(
        SpecOption, null=True, blank=True, on_delete=models.SET_NULL
    )
    value_text = models.TextField(blank=True)
    value_integer = models.IntegerField(null=True, blank=True)
    value_decimal = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True
    )
    value_boolean = models.BooleanField(null=True, blank=True)
    raw_value = models.CharField(max_length=240, blank=True)
    confidence = models.FloatField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["listing", "spec"],
                name="unique_listing_spec_value",
            )
        ]

    def __str__(self):
        return f"Listing {self.listing_id} {self.spec.key}={self.effective_value}"

    @property
    def effective_value(self):
        if self.option:
            return self.option.value
        if self.value_boolean is not None:
            return self.value_boolean
        if self.value_integer is not None:
            return self.value_integer
        if self.value_decimal is not None:
            return self.value_decimal
        return self.value_text


# ===========================================================================
# Raw-first import pipeline
# ===========================================================================


class RawImportRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        PARTIAL = "partial", "Partial"

    class CategoryHint(models.TextChoices):
        PHONES = "phones", "Phones"
        LAPTOPS = "laptops", "Laptops"
        CONSOLES = "consoles", "Portable gaming consoles"
        UNKNOWN = "unknown", "Unknown"

    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    country = models.CharField(max_length=20, choices=Country.choices)
    category_hint = models.CharField(
        max_length=20, choices=CategoryHint.choices, default=CategoryHint.UNKNOWN
    )

    source = models.ForeignKey(Source, null=True, blank=True, on_delete=models.SET_NULL)

    query_text = models.CharField(max_length=300, blank=True)
    target_url = models.URLField(max_length=1000, blank=True)
    cdp_endpoint = models.CharField(max_length=300, blank=True)

    params_json = models.JSONField(default=dict, blank=True)

    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.RUNNING
    )
    error_message = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return (
            f"ImportRun {self.pk}: {self.source_type}/{self.country} "
            f"[{self.status}] {self.query_text or self.target_url or ''}"
        )


class RawListing(models.Model):
    class ParseStatus(models.TextChoices):
        RAW = "raw", "Raw"
        PARSED = "parsed", "Parsed"
        NEEDS_REVIEW = "needs_review", "Needs review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        EXPORTED = "exported", "Exported"

    class CategoryHint(models.TextChoices):
        PHONES = "phones", "Phones"
        LAPTOPS = "laptops", "Laptops"
        CONSOLES = "consoles", "Portable gaming consoles"
        ACCESSORIES = "accessories", "Accessories"
        UNKNOWN = "unknown", "Unknown"

    import_run = models.ForeignKey(
        RawImportRun, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="raw_listings",
    )
    source = models.ForeignKey(Source, null=True, blank=True, on_delete=models.SET_NULL)

    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    country = models.CharField(max_length=20, choices=Country.choices)
    category_hint = models.CharField(
        max_length=20, choices=CategoryHint.choices, default=CategoryHint.UNKNOWN
    )

    external_id = models.CharField(max_length=160, blank=True)
    listing_url = models.URLField(max_length=1000, blank=True)

    title_raw = models.CharField(max_length=500, blank=True)
    description_raw = models.TextField(blank=True)
    raw_text = models.TextField(blank=True)

    price_text_raw = models.CharField(max_length=160, blank=True)
    location_raw = models.CharField(max_length=300, blank=True)
    date_text_raw = models.CharField(max_length=160, blank=True)

    image_url = models.URLField(max_length=1000, blank=True)

    raw_payload = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=64, db_index=True)

    observed_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    parse_status = models.CharField(
        max_length=20, choices=ParseStatus.choices, default=ParseStatus.RAW
    )

    class Meta:
        ordering = ["-observed_at"]
        indexes = [
            models.Index(fields=["source_type", "country", "category_hint"]),
            models.Index(fields=["parse_status", "-observed_at"]),
            models.Index(fields=["content_hash"]),
            models.Index(fields=["listing_url"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "listing_url"],
                name="unique_raw_listing_source_url",
                condition=~models.Q(listing_url=""),
            )
        ]

    def __str__(self):
        return self.title_raw or self.listing_url or f"RawListing {self.pk}"

    def save(self, *args, **kwargs):
        if not self.content_hash:
            self.content_hash = self._compute_content_hash()
        super().save(*args, **kwargs)

    def _compute_content_hash(self):
        import hashlib

        stable = f"{self.source_type}|{self.listing_url}|{self.title_raw}|{self.price_text_raw}"
        if self.listing_url:
            stable = f"{self.source_type}|{self.listing_url}"
        return hashlib.sha256(stable.encode()).hexdigest()[:64]


class ParsedListingCandidate(models.Model):
    class DetectedCategory(models.TextChoices):
        PHONE = "phone", "Phone"
        LAPTOP = "laptop", "Laptop"
        PORTABLE_CONSOLE = "portable_console", "Portable gaming console"
        ACCESSORY = "accessory", "Accessory"
        UNKNOWN = "unknown", "Unknown"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        NEEDS_REVIEW = "needs_review", "Needs review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        EXPORTED = "exported", "Exported"

    raw_listing = models.OneToOneField(
        RawListing, on_delete=models.CASCADE, related_name="candidate"
    )

    detected_category = models.CharField(
        max_length=20, choices=DetectedCategory.choices,
        default=DetectedCategory.UNKNOWN,
    )

    brand_text = models.CharField(max_length=160, blank=True)
    model_text = models.CharField(max_length=240, blank=True)
    variant_text = models.CharField(max_length=240, blank=True)

    price_original = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    currency_original = models.CharField(max_length=8, blank=True)
    price_eur = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    condition = models.CharField(
        max_length=20, choices=Condition.choices, default=Condition.UNKNOWN
    )

    phone_specs_json = models.JSONField(default=dict, blank=True)
    laptop_specs_json = models.JSONField(default=dict, blank=True)
    console_specs_json = models.JSONField(default=dict, blank=True)

    detected_segments_json = models.JSONField(default=list, blank=True)

    confidence = models.FloatField(default=0)
    parser_version = models.CharField(max_length=80, blank=True)

    matched_brand = models.ForeignKey(
        Brand, null=True, blank=True, on_delete=models.SET_NULL
    )

    matched_phone_model = models.ForeignKey(
        "PhoneModel", null=True, blank=True, on_delete=models.SET_NULL
    )
    matched_phone_variant = models.ForeignKey(
        "PhoneVariant", null=True, blank=True, on_delete=models.SET_NULL
    )

    matched_laptop_model = models.ForeignKey(
        "LaptopModel", null=True, blank=True, on_delete=models.SET_NULL
    )
    matched_laptop_variant = models.ForeignKey(
        "LaptopVariant", null=True, blank=True, on_delete=models.SET_NULL
    )

    matched_console_model = models.ForeignKey(
        "ConsoleModel", null=True, blank=True, on_delete=models.SET_NULL
    )
    matched_console_variant = models.ForeignKey(
        "ConsoleVariant", null=True, blank=True, on_delete=models.SET_NULL
    )

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )

    review_notes = models.TextField(blank=True)
    ai_notes = models.TextField(blank=True)
    raw_ai_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "detected_category"]),
            models.Index(fields=["confidence"]),
            models.Index(fields=["matched_brand"]),
        ]

    def __str__(self):
        return (
            f"Candidate {self.pk}: {self.brand_text} {self.model_text} "
            f"[{self.detected_category}] conf={self.confidence:.2f}"
        )


# ===========================================================================
# Phone models
# ===========================================================================


class PhoneModel(models.Model):
    brand = models.ForeignKey(
        Brand, null=True, blank=True, on_delete=models.SET_NULL
    )
    canonical_name = models.CharField(max_length=200)
    aliases = models.JSONField(default=list, blank=True)
    release_year = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["brand__name", "canonical_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "canonical_name"],
                name="unique_phone_model_per_brand",
            )
        ]

    def __str__(self):
        return self.canonical_name


def build_phone_variant_identity(storage_gb=None, ram_gb=None, sim_config="", region="", color=""):
    return "|".join([
        f"storage={storage_gb or ''}",
        f"ram={ram_gb or ''}",
        f"sim={normalize_sim_config(sim_config)}",
        f"region={normalize_variant_text(region).lower()}",
        f"color={normalize_variant_text(color).lower()}",
    ])


class PhoneVariant(models.Model):
    phone_model = models.ForeignKey(
        PhoneModel, on_delete=models.CASCADE, related_name="variants"
    )

    storage_gb = models.PositiveSmallIntegerField(null=True, blank=True)
    ram_gb = models.PositiveSmallIntegerField(null=True, blank=True)

    sim_config = models.CharField(max_length=80, blank=True)
    region = models.CharField(max_length=80, blank=True)
    color = models.CharField(max_length=80, blank=True)

    canonical_label = models.CharField(max_length=240)
    identity_key = models.CharField(max_length=200, db_index=True, editable=False)

    aliases = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["phone_model__canonical_name", "storage_gb", "ram_gb", "sim_config"]
        constraints = [
            models.UniqueConstraint(
                fields=["phone_model", "identity_key"],
                name="unique_phone_variant_identity",
            )
        ]

    def __str__(self):
        return self.canonical_label

    def save(self, *args, **kwargs):
        self.identity_key = build_phone_variant_identity(
            self.storage_gb, self.ram_gb, self.sim_config, self.region, self.color
        )
        super().save(*args, **kwargs)


class PhoneListing(models.Model):
    class ReviewStatus(models.TextChoices):
        AUTO = "auto", "Auto"
        NEEDS_REVIEW = "needs_review", "Needs review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    raw_listing = models.OneToOneField(
        RawListing, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="phone_listing",
    )

    source = models.ForeignKey(Source, null=True, blank=True, on_delete=models.SET_NULL)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    country = models.CharField(max_length=20, choices=Country.choices)

    phone_model = models.ForeignKey(
        PhoneModel, null=True, blank=True, on_delete=models.SET_NULL
    )
    variant = models.ForeignKey(
        PhoneVariant, null=True, blank=True, on_delete=models.SET_NULL
    )

    title = models.CharField(max_length=500, blank=True)

    price_original = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    currency_original = models.CharField(max_length=8, blank=True)
    price_eur = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    condition = models.CharField(
        max_length=20, choices=Condition.choices, default=Condition.UNKNOWN
    )

    storage_gb = models.PositiveSmallIntegerField(null=True, blank=True)
    ram_gb = models.PositiveSmallIntegerField(null=True, blank=True)
    sim_config = models.CharField(max_length=80, blank=True)

    battery_health = models.PositiveSmallIntegerField(null=True, blank=True)
    battery_cycles = models.PositiveIntegerField(null=True, blank=True)

    box_status = models.CharField(max_length=120, blank=True)
    store_warranty = models.CharField(max_length=240, blank=True)
    region = models.CharField(max_length=80, blank=True)
    color = models.CharField(max_length=80, blank=True)

    listing_url = models.URLField(max_length=1000, blank=True)
    image_url = models.URLField(max_length=1000, blank=True)

    observed_at = models.DateTimeField(default=timezone.now)

    parsed_confidence = models.FloatField(default=0)
    review_status = models.CharField(
        max_length=20, choices=ReviewStatus.choices,
        default=ReviewStatus.NEEDS_REVIEW,
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-observed_at"]
        indexes = [
            models.Index(fields=["country", "source_type"]),
            models.Index(fields=["phone_model", "storage_gb"]),
            models.Index(fields=["price_eur"]),
            models.Index(fields=["review_status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "listing_url"],
                name="unique_phone_listing_source_url",
                condition=~models.Q(listing_url=""),
            )
        ]

    def __str__(self):
        return self.title or f"PhoneListing {self.pk}"

    def save(self, *args, **kwargs):
        self.sim_config = normalize_sim_config(self.sim_config)
        super().save(*args, **kwargs)


# ===========================================================================
# Laptop models
# ===========================================================================


class LaptopModel(models.Model):
    brand = models.ForeignKey(
        Brand, null=True, blank=True, on_delete=models.SET_NULL
    )
    canonical_name = models.CharField(max_length=240)
    series = models.CharField(max_length=160, blank=True)
    aliases = models.JSONField(default=list, blank=True)
    release_year = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["brand__name", "canonical_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "canonical_name"],
                name="unique_laptop_model_per_brand",
            )
        ]

    def __str__(self):
        return self.canonical_name


def build_laptop_variant_identity(
    cpu="", gpu="", ram_gb=None, storage_gb=None,
    screen_size=None, resolution="", refresh_rate_hz=None,
):
    def _norm(val):
        return normalize_variant_text(str(val)).lower() if val else ""

    parts = [
        f"cpu={_norm(cpu)}",
        f"gpu={_norm(gpu)}",
        f"ram={ram_gb or ''}",
        f"storage={storage_gb or ''}",
        f"screen={screen_size or ''}",
        f"resolution={_norm(resolution)}",
        f"hz={refresh_rate_hz or ''}",
    ]
    return "|".join(parts)


class LaptopVariant(models.Model):
    laptop_model = models.ForeignKey(
        LaptopModel, on_delete=models.CASCADE, related_name="variants"
    )

    cpu = models.CharField(max_length=160, blank=True)
    gpu = models.CharField(max_length=160, blank=True)

    ram_gb = models.PositiveSmallIntegerField(null=True, blank=True)
    storage_gb = models.PositiveSmallIntegerField(null=True, blank=True)

    screen_size = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    resolution = models.CharField(max_length=80, blank=True)
    refresh_rate_hz = models.PositiveSmallIntegerField(null=True, blank=True)
    panel_type = models.CharField(max_length=80, blank=True)

    canonical_label = models.CharField(max_length=300)
    identity_key = models.CharField(max_length=300, db_index=True, editable=False)

    aliases = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = [
            "laptop_model__canonical_name", "gpu", "cpu", "ram_gb", "storage_gb"
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["laptop_model", "identity_key"],
                name="unique_laptop_variant_identity",
            )
        ]

    def __str__(self):
        return self.canonical_label

    def save(self, *args, **kwargs):
        self.identity_key = build_laptop_variant_identity(
            self.cpu, self.gpu, self.ram_gb, self.storage_gb,
            self.screen_size, self.resolution, self.refresh_rate_hz,
        )
        super().save(*args, **kwargs)


class LaptopListing(models.Model):
    class ReviewStatus(models.TextChoices):
        AUTO = "auto", "Auto"
        NEEDS_REVIEW = "needs_review", "Needs review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    raw_listing = models.OneToOneField(
        RawListing, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="laptop_listing",
    )

    source = models.ForeignKey(Source, null=True, blank=True, on_delete=models.SET_NULL)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    country = models.CharField(max_length=20, choices=Country.choices)

    laptop_model = models.ForeignKey(
        LaptopModel, null=True, blank=True, on_delete=models.SET_NULL
    )
    variant = models.ForeignKey(
        LaptopVariant, null=True, blank=True, on_delete=models.SET_NULL
    )

    title = models.CharField(max_length=500, blank=True)

    price_original = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    currency_original = models.CharField(max_length=8, blank=True)
    price_eur = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    condition = models.CharField(
        max_length=20, choices=Condition.choices, default=Condition.UNKNOWN
    )

    cpu = models.CharField(max_length=160, blank=True)
    gpu = models.CharField(max_length=160, blank=True)
    ram_gb = models.PositiveSmallIntegerField(null=True, blank=True)
    storage_gb = models.PositiveSmallIntegerField(null=True, blank=True)
    screen_size = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    resolution = models.CharField(max_length=80, blank=True)
    refresh_rate_hz = models.PositiveSmallIntegerField(null=True, blank=True)
    panel_type = models.CharField(max_length=80, blank=True)

    listing_url = models.URLField(max_length=1000, blank=True)
    image_url = models.URLField(max_length=1000, blank=True)

    observed_at = models.DateTimeField(default=timezone.now)

    parsed_confidence = models.FloatField(default=0)
    review_status = models.CharField(
        max_length=20, choices=ReviewStatus.choices,
        default=ReviewStatus.NEEDS_REVIEW,
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-observed_at"]
        indexes = [
            models.Index(fields=["country", "source_type"]),
            models.Index(fields=["laptop_model", "gpu", "cpu"]),
            models.Index(fields=["price_eur"]),
            models.Index(fields=["review_status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "listing_url"],
                name="unique_laptop_listing_source_url",
                condition=~models.Q(listing_url=""),
            )
        ]

    def __str__(self):
        return self.title or f"LaptopListing {self.pk}"


# ===========================================================================
# Portable gaming console models
# ===========================================================================


class ConsoleModel(models.Model):
    brand = models.ForeignKey(
        Brand, null=True, blank=True, on_delete=models.SET_NULL
    )
    canonical_name = models.CharField(max_length=240)
    aliases = models.JSONField(default=list, blank=True)
    release_year = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["brand__name", "canonical_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "canonical_name"],
                name="unique_console_model_per_brand",
            )
        ]

    def __str__(self):
        return self.canonical_name


def build_console_variant_identity(chipset="", ram_gb=None, storage_gb=None, connectivity="", color=""):
    def _norm(val):
        return normalize_variant_text(str(val)).lower() if val else ""

    return "|".join([
        f"chipset={_norm(chipset)}",
        f"ram={ram_gb or ''}",
        f"storage={storage_gb or ''}",
        f"connectivity={_norm(connectivity)}",
        f"color={_norm(color)}",
    ])


class ConsoleVariant(models.Model):
    console_model = models.ForeignKey(
        ConsoleModel, on_delete=models.CASCADE, related_name="variants"
    )
    chipset = models.CharField(max_length=160, blank=True)
    ram_gb = models.PositiveSmallIntegerField(null=True, blank=True)
    storage_gb = models.PositiveSmallIntegerField(null=True, blank=True)
    screen_size = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    refresh_rate_hz = models.PositiveSmallIntegerField(null=True, blank=True)
    connectivity = models.CharField(max_length=80, blank=True)
    color = models.CharField(max_length=80, blank=True)

    canonical_label = models.CharField(max_length=300)
    identity_key = models.CharField(max_length=300, db_index=True, editable=False)
    aliases = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["console_model__canonical_name", "storage_gb", "ram_gb", "chipset"]
        constraints = [
            models.UniqueConstraint(
                fields=["console_model", "identity_key"],
                name="unique_console_variant_identity",
            )
        ]

    def __str__(self):
        return self.canonical_label

    def save(self, *args, **kwargs):
        self.identity_key = build_console_variant_identity(
            self.chipset, self.ram_gb, self.storage_gb, self.connectivity, self.color
        )
        super().save(*args, **kwargs)


class ConsoleListing(models.Model):
    class ReviewStatus(models.TextChoices):
        AUTO = "auto", "Auto"
        NEEDS_REVIEW = "needs_review", "Needs review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    raw_listing = models.OneToOneField(
        RawListing, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="console_listing",
    )

    source = models.ForeignKey(Source, null=True, blank=True, on_delete=models.SET_NULL)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    country = models.CharField(max_length=20, choices=Country.choices)

    console_model = models.ForeignKey(
        ConsoleModel, null=True, blank=True, on_delete=models.SET_NULL
    )
    variant = models.ForeignKey(
        ConsoleVariant, null=True, blank=True, on_delete=models.SET_NULL
    )

    title = models.CharField(max_length=500, blank=True)
    price_original = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    currency_original = models.CharField(max_length=8, blank=True)
    price_eur = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    condition = models.CharField(
        max_length=20, choices=Condition.choices, default=Condition.UNKNOWN
    )

    chipset = models.CharField(max_length=160, blank=True)
    ram_gb = models.PositiveSmallIntegerField(null=True, blank=True)
    storage_gb = models.PositiveSmallIntegerField(null=True, blank=True)
    screen_size = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    refresh_rate_hz = models.PositiveSmallIntegerField(null=True, blank=True)
    connectivity = models.CharField(max_length=80, blank=True)
    color = models.CharField(max_length=80, blank=True)

    listing_url = models.URLField(max_length=1000, blank=True)
    image_url = models.URLField(max_length=1000, blank=True)
    observed_at = models.DateTimeField(default=timezone.now)
    parsed_confidence = models.FloatField(default=0)
    review_status = models.CharField(
        max_length=20, choices=ReviewStatus.choices,
        default=ReviewStatus.NEEDS_REVIEW,
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-observed_at"]
        indexes = [
            models.Index(fields=["country", "source_type"]),
            models.Index(fields=["console_model", "storage_gb"]),
            models.Index(fields=["price_eur"]),
            models.Index(fields=["review_status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "listing_url"],
                name="unique_console_listing_source_url",
                condition=~models.Q(listing_url=""),
            )
        ]

    def __str__(self):
        return self.title or f"ConsoleListing {self.pk}"
