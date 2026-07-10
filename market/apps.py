from django.apps import AppConfig


class MarketConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'market'

    def import_models(self):
        super().import_models()
        # Register clean v2 models that live outside the large legacy models.py file.
        from . import clean_models  # noqa: F401

    def ready(self):
        # Keep the clean v2 admin registration close to the clean model without
        # touching the already-large legacy admin.py file.
        try:
            from django.contrib import admin
            from django.contrib.admin.sites import AlreadyRegistered
            from .clean_models import ConsoleOpportunitySnapshot, LaptopOpportunitySnapshot, PhoneOpportunitySnapshot
        except Exception:
            return

        class PhoneOpportunitySnapshotAdmin(admin.ModelAdmin):
            list_display = (
                "brand", "model", "storage_gb", "algeria_min_eur",
                "turkiye_avg_eur", "gross_margin_eur", "margin_percent",
                "algeria_count", "turkiye_count", "recommendation",
                "confidence_score", "generated_at",
            )
            search_fields = ("brand", "model")
            list_filter = ("recommendation", "brand", "storage_gb", "generated_at")
            readonly_fields = ("generated_at", "created_at", "algeria_urls", "turkiye_urls")
            list_per_page = 50

        try:
            admin.site.register(PhoneOpportunitySnapshot, PhoneOpportunitySnapshotAdmin)
        except AlreadyRegistered:
            pass

        class LaptopOpportunitySnapshotAdmin(admin.ModelAdmin):
            list_display = (
                "brand", "model", "cpu", "gpu", "ram_gb", "storage_gb",
                "algeria_min_eur", "turkiye_avg_eur", "gross_margin_eur",
                "margin_percent", "algeria_count", "turkiye_count",
                "recommendation", "confidence_score", "generated_at",
            )
            search_fields = ("brand", "model", "cpu", "gpu")
            list_filter = ("recommendation", "brand", "ram_gb", "storage_gb", "generated_at")
            readonly_fields = ("generated_at", "created_at", "algeria_urls", "turkiye_urls")
            list_per_page = 50

        try:
            admin.site.register(LaptopOpportunitySnapshot, LaptopOpportunitySnapshotAdmin)
        except AlreadyRegistered:
            pass

        class ConsoleOpportunitySnapshotAdmin(admin.ModelAdmin):
            list_display = (
                "brand", "model", "chipset", "ram_gb", "storage_gb",
                "algeria_min_eur", "turkiye_avg_eur", "gross_margin_eur",
                "margin_percent", "algeria_count", "turkiye_count",
                "recommendation", "confidence_score", "generated_at",
            )
            search_fields = ("brand", "model", "chipset")
            list_filter = ("recommendation", "brand", "ram_gb", "storage_gb", "generated_at")
            readonly_fields = ("generated_at", "created_at", "algeria_urls", "turkiye_urls")
            list_per_page = 50

        try:
            admin.site.register(ConsoleOpportunitySnapshot, ConsoleOpportunitySnapshotAdmin)
        except AlreadyRegistered:
            pass
