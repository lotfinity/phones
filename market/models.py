import json
import re
from decimal import Decimal, ROUND_HALF_UP

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
        from decimal import Decimal as D
        from market.services.currency import eur_to_dzd, money, usd_to_eur

        gross = self.gross_margin_vs_sahibinden_eur
        algeria_min = self.algeria_min_eur
        sahibinden_avg = self.sahibinden_avg_eur
        supplier = self.supplier_eur

        if algeria_min is None:
            return None

        algeria_min = D(str(algeria_min))

        if supplier is not None:
            supplier = D(str(supplier))
            buyer_floor = usd_to_eur(self.SUPPLIER_BUYER_DISCOUNT_USD)
            gross = supplier - algeria_min
            split_pool = gross - buyer_floor

            if split_pool <= 0:
                my_gain = D("0")
                buyer_gain = gross
                offer_price = algeria_min
                deal_quality = "weak" if buyer_gain > 0 else "ignore"
                notes = (
                    f"Supplier-list rule: target buyer discount USD {self.SUPPLIER_BUYER_DISCOUNT_USD:.0f}; "
                    "spread is too thin to split after the target discount."
                )
            else:
                my_gain = split_pool / D("2")
                buyer_gain = buyer_floor + (split_pool / D("2"))
                offer_price = algeria_min + my_gain
                buyer_gain_pct = (buyer_gain / offer_price * D("100")) if offer_price else D("0")
                if buyer_gain_pct >= 30:
                    deal_quality = "strong"
                elif buyer_gain_pct >= 15 or split_pool >= self.GOOD_DEAL_GROSS_FLOOR_EUR:
                    deal_quality = "medium"
                else:
                    deal_quality = "weak"
                notes = (
                    f"Supplier-list rule: buyer gets USD {self.SUPPLIER_BUYER_DISCOUNT_USD:.0f} below supplier, "
                    "then remaining spread is split 50/50."
                )

            buyer_gain_pct = (buyer_gain / offer_price * D("100")) if offer_price else D("0")
            my_gain_pct_of_gross = (my_gain / gross * D("100")) if gross else D("0")
            return {
                "pricing_basis": "supplier",
                "gross_margin_eur": money(gross),
                "my_gain_eur": money(my_gain),
                "buyer_gain_eur": money(buyer_gain),
                "offer_price_to_buyer_eur": money(offer_price),
                "buyer_gain_percent": buyer_gain_pct.quantize(D("0.01"), rounding=ROUND_HALF_UP),
                "my_gain_percent_of_gross": my_gain_pct_of_gross.quantize(D("0.01"), rounding=ROUND_HALF_UP),
                "my_gain_dzd": money(eur_to_dzd(my_gain)),
                "offer_price_to_buyer_dzd": money(eur_to_dzd(offer_price)),
                "deal_quality": deal_quality,
                "notes": notes,
            }

        if gross is None or sahibinden_avg is None:
            return None

        gross = D(str(gross))

        if gross <= 0:
            return {
                "pricing_basis": "turkiye_market",
                "gross_margin_eur": money(gross),
                "my_gain_eur": money(D("0")),
                "buyer_gain_eur": money(gross),
                "offer_price_to_buyer_eur": money(algeria_min),
                "buyer_gain_percent": D("0.00"),
                "my_gain_percent_of_gross": D("0.00"),
                "my_gain_dzd": money(D("0")),
                "offer_price_to_buyer_dzd": money(eur_to_dzd(algeria_min)),
                "deal_quality": "ignore",
                "notes": "No spread available to split.",
            }

        # Find the right tier
        my_gain_pct = D("0")
        buyer_min = D("0")
        for threshold, gain_pct, min_gain in self.GAIN_SPLIT_TIERS:
            if threshold is None or gross < threshold:
                my_gain_pct = gain_pct
                buyer_min = min_gain
                break

        my_gain = gross * my_gain_pct

        # Cap: buyer must keep at least buyer_min.
        capped = False
        max_my_gain = gross - buyer_min
        if my_gain > max_my_gain:
            my_gain = max(D("0"), max_my_gain)
            capped = True

        buyer_gain = gross - my_gain
        offer_price = algeria_min + my_gain

        # Percentages
        my_gain_pct_of_gross = (my_gain / gross * D("100")) if gross else D("0")
        buyer_gain_pct = (buyer_gain / offer_price * D("100")) if offer_price else D("0")

        # Deal quality
        if gross < D("50"):
            deal_quality = "weak"
        elif buyer_gain_pct >= 30:
            deal_quality = "strong"
        elif buyer_gain_pct >= 15:
            deal_quality = "medium"
        elif gross >= self.GOOD_DEAL_GROSS_FLOOR_EUR and buyer_gain > 0:
            deal_quality = "medium"
        elif buyer_gain_pct > 0:
            deal_quality = "weak"
        else:
            deal_quality = "ignore"

        # Notes
        notes_parts = []
        if my_gain_pct > 0:
            notes_parts.append(f"My cut: {my_gain_pct * 100:.0f}% of spread")
        if capped and buyer_gain >= buyer_min and buyer_min > 0:
            notes_parts.append(f"Capped to leave buyer at least EUR {buyer_min:.0f}")
        elif buyer_gain < buyer_min and buyer_min > 0:
            notes_parts.append(f"Buyer minimum target EUR {buyer_min:.0f} is not met")
        if gross >= self.GOOD_DEAL_GROSS_FLOOR_EUR and deal_quality == "medium" and buyer_gain_pct < 15:
            notes_parts.append(f"Absolute spread above EUR {self.GOOD_DEAL_GROSS_FLOOR_EUR:.0f}; kept as medium")
        if deal_quality == "weak":
            notes_parts.append("Thin margin for buyer; may not close")
        if deal_quality == "strong":
            notes_parts.append("Healthy buyer profit; attractive deal")

        return {
            "pricing_basis": "turkiye_market",
            "gross_margin_eur": money(gross),
            "my_gain_eur": money(my_gain),
            "buyer_gain_eur": money(buyer_gain),
            "offer_price_to_buyer_eur": money(offer_price),
            "buyer_gain_percent": buyer_gain_pct.quantize(D("0.01"), rounding=ROUND_HALF_UP),
            "my_gain_percent_of_gross": my_gain_pct_of_gross.quantize(D("0.01"), rounding=ROUND_HALF_UP),
            "my_gain_dzd": money(eur_to_dzd(my_gain)),
            "offer_price_to_buyer_dzd": money(eur_to_dzd(offer_price)),
            "deal_quality": deal_quality,
            "notes": "; ".join(notes_parts),
        }


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
