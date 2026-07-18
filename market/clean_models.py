from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class PhoneOpportunitySnapshot(models.Model):
    """DB-backed snapshot for clean PhoneListing-based opportunities.

    This is intentionally separate from legacy OpportunitySnapshot because it is
    powered by the raw-first PhoneListing pipeline instead of old MarketListing.
    """

    class Recommendation(models.TextChoices):
        BUY = "buy", "Buy"
        WATCH = "watch", "Watch"
        IGNORE = "ignore", "Ignore"

    phone_model = models.ForeignKey(
        "PhoneModel",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clean_opportunity_snapshots",
    )
    algeria_listing = models.ForeignKey(
        "PhoneListing",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clean_opportunity_snapshots",
    )
    brand = models.CharField(max_length=120, db_index=True)
    model = models.CharField(max_length=220, db_index=True)
    storage_gb = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)

    algeria_min_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    algeria_avg_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    turkiye_min_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    turkiye_avg_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    gross_margin_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    margin_percent = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    algeria_count = models.PositiveIntegerField(default=0)
    turkiye_count = models.PositiveIntegerField(default=0)
    algeria_urls = models.JSONField(default=list, blank=True)
    turkiye_urls = models.JSONField(default=list, blank=True)

    recommendation = models.CharField(
        max_length=20,
        choices=Recommendation.choices,
        default=Recommendation.WATCH,
        db_index=True,
    )
    confidence_score = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    source_label = models.CharField(max_length=80, default="phone_v2")
    generated_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = "market"
        ordering = ["-gross_margin_eur", "-margin_percent"]
        indexes = [
            models.Index(fields=["recommendation", "-gross_margin_eur"], name="market_phon_recomme_33af8d_idx"),
            models.Index(fields=["brand", "model", "storage_gb"], name="market_phon_brand_45d0d0_idx"),
            models.Index(fields=["-generated_at"], name="market_phon_generat_427938_idx"),
        ]
        verbose_name = "clean phone opportunity"
        verbose_name_plural = "clean phone opportunities"

    def __str__(self):
        storage = f" {self.storage_gb}GB" if self.storage_gb else ""
        return f"{self.brand} {self.model}{storage} margin={self.gross_margin_eur}"


class LaptopOpportunitySnapshot(models.Model):
    """DB-backed snapshot for clean LaptopListing-based opportunities."""

    class Recommendation(models.TextChoices):
        BUY = "buy", "Buy"
        WATCH = "watch", "Watch"
        IGNORE = "ignore", "Ignore"
        LOW_CONFIDENCE = "low_confidence", "Low confidence"
        GOOD_OPPORTUNITY = "good_opportunity", "Good opportunity"
        MARGINAL = "marginal", "Marginal"
        NO_MARGIN = "no_margin", "No margin"

    laptop_model = models.ForeignKey(
        "LaptopModel",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clean_opportunity_snapshots",
    )
    algeria_listing = models.ForeignKey(
        "LaptopListing",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clean_opportunity_snapshots",
    )
    brand = models.CharField(max_length=120, db_index=True)
    model = models.CharField(max_length=240, db_index=True)
    cpu = models.CharField(max_length=160, blank=True)
    gpu = models.CharField(max_length=160, blank=True)
    ram_gb = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    storage_gb = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)

    algeria_min_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    algeria_avg_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    turkiye_min_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    turkiye_avg_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    gross_margin_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    margin_percent = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    algeria_count = models.PositiveIntegerField(default=0)
    turkiye_count = models.PositiveIntegerField(default=0)
    algeria_urls = models.JSONField(default=list, blank=True)
    turkiye_urls = models.JSONField(default=list, blank=True)

    recommendation = models.CharField(
        max_length=30,
        choices=Recommendation.choices,
        default=Recommendation.WATCH,
        db_index=True,
    )
    confidence_score = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    source_label = models.CharField(max_length=80, default="laptop_v2")
    generated_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = "market"
        ordering = ["-gross_margin_eur", "-margin_percent"]
        indexes = [
            models.Index(fields=["recommendation", "-gross_margin_eur"], name="market_lapt_recomme_2c0d2a_idx"),
            models.Index(fields=["brand", "model", "ram_gb", "storage_gb"], name="market_lapt_brand_8f4d3c_idx"),
            models.Index(fields=["-generated_at"], name="market_lapt_generat_c5b9e1_idx"),
        ]
        verbose_name = "clean laptop opportunity"
        verbose_name_plural = "clean laptop opportunities"

    def __str__(self):
        parts = [self.brand, self.model]
        if self.ram_gb:
            parts.append(f"{self.ram_gb}GB")
        if self.storage_gb:
            parts.append(f"{self.storage_gb}GB")
        return f"{' '.join(parts)} margin={self.gross_margin_eur}"


class ConsoleOpportunitySnapshot(models.Model):
    """DB-backed snapshot for clean portable gaming console opportunities."""

    class Recommendation(models.TextChoices):
        BUY = "buy", "Buy"
        WATCH = "watch", "Watch"
        IGNORE = "ignore", "Ignore"
        LOW_CONFIDENCE = "low_confidence", "Low confidence"
        GOOD_OPPORTUNITY = "good_opportunity", "Good opportunity"
        MARGINAL = "marginal", "Marginal"
        NO_MARGIN = "no_margin", "No margin"

    console_model = models.ForeignKey(
        "ConsoleModel",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clean_opportunity_snapshots",
    )
    algeria_listing = models.ForeignKey(
        "ConsoleListing",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clean_opportunity_snapshots",
    )
    brand = models.CharField(max_length=120, db_index=True)
    model = models.CharField(max_length=240, db_index=True)
    chipset = models.CharField(max_length=160, blank=True)
    ram_gb = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    storage_gb = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)

    algeria_min_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    algeria_avg_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    turkiye_min_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    turkiye_avg_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    gross_margin_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    margin_percent = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    algeria_count = models.PositiveIntegerField(default=0)
    turkiye_count = models.PositiveIntegerField(default=0)
    algeria_urls = models.JSONField(default=list, blank=True)
    turkiye_urls = models.JSONField(default=list, blank=True)

    recommendation = models.CharField(
        max_length=30,
        choices=Recommendation.choices,
        default=Recommendation.WATCH,
        db_index=True,
    )
    confidence_score = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    source_label = models.CharField(max_length=80, default="console_v1")
    generated_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = "market"
        ordering = ["-gross_margin_eur", "-margin_percent"]
        indexes = [
            models.Index(fields=["recommendation", "-gross_margin_eur"], name="market_cons_recomme_6dbd4c_idx"),
            models.Index(fields=["brand", "model", "storage_gb"], name="market_cons_brand_6d2b1e_idx"),
            models.Index(fields=["-generated_at"], name="market_cons_generat_935f20_idx"),
        ]
        verbose_name = "clean console opportunity"
        verbose_name_plural = "clean console opportunities"

    def __str__(self):
        storage = f" {self.storage_gb}GB" if self.storage_gb else ""
        return f"{self.brand} {self.model}{storage} margin={self.gross_margin_eur}"
