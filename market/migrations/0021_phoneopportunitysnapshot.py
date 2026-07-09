# Generated manually for clean PhoneListing opportunity dashboard

import django.db.models.deletion
import django.utils.timezone
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("market", "0020_raw_pipeline_and_phone_laptop_models"),
    ]

    operations = [
        migrations.CreateModel(
            name="PhoneOpportunitySnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("brand", models.CharField(db_index=True, max_length=120)),
                ("model", models.CharField(db_index=True, max_length=220)),
                ("storage_gb", models.PositiveSmallIntegerField(blank=True, db_index=True, null=True)),
                ("algeria_min_eur", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("algeria_avg_eur", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("turkiye_min_eur", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("turkiye_avg_eur", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("gross_margin_eur", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("margin_percent", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("algeria_count", models.PositiveIntegerField(default=0)),
                ("turkiye_count", models.PositiveIntegerField(default=0)),
                ("algeria_urls", models.JSONField(blank=True, default=list)),
                ("turkiye_urls", models.JSONField(blank=True, default=list)),
                ("recommendation", models.CharField(choices=[("buy", "Buy"), ("watch", "Watch"), ("ignore", "Ignore")], db_index=True, default="watch", max_length=20)),
                ("confidence_score", models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])),
                ("source_label", models.CharField(default="phone_v2", max_length=80)),
                ("generated_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("phone_model", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="clean_opportunity_snapshots", to="market.phonemodel")),
            ],
            options={
                "verbose_name": "clean phone opportunity",
                "verbose_name_plural": "clean phone opportunities",
                "ordering": ["-gross_margin_eur", "-margin_percent"],
                "indexes": [
                    models.Index(fields=["recommendation", "-gross_margin_eur"], name="market_phon_recomme_33af8d_idx"),
                    models.Index(fields=["brand", "model", "storage_gb"], name="market_phon_brand_45d0d0_idx"),
                    models.Index(fields=["-generated_at"], name="market_phon_generat_427938_idx"),
                ],
            },
        ),
    ]
