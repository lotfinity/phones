import re

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
    algeria_min_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    algeria_avg_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    supplier_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    sahibinden_avg_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    gross_margin_vs_supplier_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    gross_margin_vs_sahibinden_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
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
