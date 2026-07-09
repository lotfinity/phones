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
            models.Index(fields=["recommendation", "-gross_margin_eur"]),
            models.Index(fields=["brand", "model", "storage_gb"]),
            models.Index(fields=["-generated_at"]),
        ]
        verbose_name = "clean phone opportunity"
        verbose_name_plural = "clean phone opportunities"

    def __str__(self):
        storage = f" {self.storage_gb}GB" if self.storage_gb else ""
        return f"{self.brand} {self.model}{storage} margin={self.gross_margin_eur}"
