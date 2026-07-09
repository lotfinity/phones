from django.apps import AppConfig


class MarketConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'market'

    def import_models(self):
        super().import_models()
        # Register clean v2 models that live outside the large legacy models.py file.
        from . import clean_models  # noqa: F401
