# Generated manually for clean LaptopListing opportunity dashboard

import django.db.models.deletion
import django.utils.timezone
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("market", "0021_phoneopportunitysnapshot"),
    ]

    operations = [
        migrations.CreateModel(
            name="LaptopOpportunitySnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("brand", models.CharField(db_index=True, max_length=120)),
                ("model", models.CharField(db_index=True, max_length=240)),
                ("cpu", models.CharField(blank=True, max_length=160)),
                ("gpu", models.CharField(blank=True, max_length=160)),
                ("ram_gb", models.PositiveSmallIntegerField(blank=True, db_index=True, null=True)),
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
                ("recommendation", models.CharField(choices=[("buy", "Buy"), ("watch", "Watch"), ("ignore", "Ignore"), ("low_confidence", "Low confidence"), ("good_opportunity", "Good opportunity"), ("marginal", "Marginal"), ("no_margin", "No margin")], db_index=True, default="watch", max_length=30)),
                ("confidence_score", models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])),
                ("source_label", models.CharField(default="laptop_v2", max_length=80)),
                ("generated_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("laptop_model", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="clean_opportunity_snapshots", to="market.laptopmodel")),
            ],
            options={
                "verbose_name": "clean laptop opportunity",
                "verbose_name_plural": "clean laptop opportunities",
                "ordering": ["-gross_margin_eur", "-margin_percent"],
                "indexes": [
                    models.Index(fields=["recommendation", "-gross_margin_eur"], name="market_lapt_recomme_2c0d2a_idx"),
                    models.Index(fields=["brand", "model", "ram_gb", "storage_gb"], name="market_lapt_brand_8f4d3c_idx"),
                    models.Index(fields=["-generated_at"], name="market_lapt_generat_c5b9e1_idx"),
                ],
            },
        ),
    ]
