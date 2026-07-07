"""Idempotent management command to seed product types and spec definitions.

Usage:
    python manage.py seed_product_types_and_specs
"""

from django.core.management.base import BaseCommand

from market.models import ProductType, SpecDefinition, SpecOption
from market.services.catalog import get_or_create_product_type


PRODUCT_TYPES = [
    {"slug": "phone", "name": "Phone"},
    {"slug": "laptop", "name": "Laptop"},
    {"slug": "tablet", "name": "Tablet"},
    {"slug": "console", "name": "Console"},
    {"slug": "vr_headset", "name": "VR Headset"},
    {"slug": "camera", "name": "Camera"},
]


def _specs_phone():
    return [
        {"key": "storage_gb", "label": "Storage", "value_type": "integer", "unit": "GB",
         "is_variant_identity": True, "is_filterable": True, "is_comparable": True, "sort_order": 10},
        {"key": "ram_gb", "label": "RAM", "value_type": "integer", "unit": "GB",
         "is_variant_identity": True, "is_filterable": True, "is_comparable": True, "sort_order": 20},
        {"key": "sim_config", "label": "SIM Config", "value_type": "option", "unit": "",
         "is_variant_identity": True, "is_filterable": True, "is_comparable": False, "sort_order": 30,
         "aliases": ["sim"]},
        {"key": "region", "label": "Region", "value_type": "text", "unit": "",
         "is_variant_identity": True, "is_filterable": False, "is_comparable": False, "sort_order": 40},
        {"key": "color", "label": "Color", "value_type": "option", "unit": "",
         "is_variant_identity": True, "is_filterable": True, "is_comparable": False, "sort_order": 50},
        {"key": "battery_health", "label": "Battery Health", "value_type": "integer", "unit": "%",
         "is_variant_identity": False, "is_listing_level": True, "is_filterable": False,
         "is_comparable": False, "sort_order": 60},
        {"key": "battery_cycles", "label": "Battery Cycles", "value_type": "integer", "unit": "",
         "is_variant_identity": False, "is_listing_level": True, "is_filterable": False,
         "is_comparable": False, "sort_order": 70},
        {"key": "box_status", "label": "Box Status", "value_type": "option", "unit": "",
         "is_variant_identity": False, "is_listing_level": True, "is_filterable": True,
         "is_comparable": False, "sort_order": 80,
         "aliases": ["box"]},
        {"key": "condition", "label": "Condition", "value_type": "option", "unit": "",
         "is_variant_identity": False, "is_listing_level": True, "is_filterable": True,
         "is_comparable": False, "sort_order": 90},
    ]


def _specs_laptop():
    return [
        {"key": "cpu_brand", "label": "CPU Brand", "value_type": "option", "unit": "",
         "is_variant_identity": True, "is_filterable": True, "is_comparable": False, "sort_order": 10,
         "aliases": ["processor_brand"]},
        {"key": "cpu_model", "label": "CPU Model", "value_type": "option", "unit": "",
         "is_variant_identity": True, "is_filterable": True, "is_comparable": True, "sort_order": 20,
         "aliases": ["processor"]},
        {"key": "gpu_brand", "label": "GPU Brand", "value_type": "option", "unit": "",
         "is_variant_identity": True, "is_filterable": True, "is_comparable": False, "sort_order": 30},
        {"key": "gpu_model", "label": "GPU Model", "value_type": "option", "unit": "",
         "is_variant_identity": True, "is_filterable": True, "is_comparable": True, "sort_order": 40,
         "aliases": ["graphics"]},
        {"key": "gpu_vram_gb", "label": "GPU VRAM", "value_type": "integer", "unit": "GB",
         "is_variant_identity": False, "is_filterable": False, "is_comparable": True, "sort_order": 50},
        {"key": "ram_gb", "label": "RAM", "value_type": "integer", "unit": "GB",
         "is_variant_identity": True, "is_filterable": True, "is_comparable": True, "sort_order": 60},
        {"key": "ram_type", "label": "RAM Type", "value_type": "option", "unit": "",
         "is_variant_identity": False, "is_filterable": True, "is_comparable": False, "sort_order": 70},
        {"key": "ssd_gb", "label": "SSD", "value_type": "integer", "unit": "GB",
         "is_variant_identity": True, "is_filterable": True, "is_comparable": True, "sort_order": 80},
        {"key": "screen_inches", "label": "Screen Size", "value_type": "decimal", "unit": "inch",
         "is_variant_identity": False, "is_filterable": True, "is_comparable": True, "sort_order": 90},
        {"key": "resolution", "label": "Resolution", "value_type": "option", "unit": "",
         "is_variant_identity": False, "is_filterable": True, "is_comparable": False, "sort_order": 100},
        {"key": "refresh_hz", "label": "Refresh Rate", "value_type": "integer", "unit": "Hz",
         "is_variant_identity": False, "is_filterable": True, "is_comparable": True, "sort_order": 110},
        {"key": "panel_type", "label": "Panel Type", "value_type": "option", "unit": "",
         "is_variant_identity": False, "is_filterable": True, "is_comparable": False, "sort_order": 120},
        {"key": "touchscreen", "label": "Touchscreen", "value_type": "boolean", "unit": "",
         "is_variant_identity": False, "is_filterable": True, "is_comparable": False, "sort_order": 130},
        {"key": "keyboard_layout", "label": "Keyboard Layout", "value_type": "option", "unit": "",
         "is_variant_identity": False, "is_filterable": True, "is_comparable": False, "sort_order": 140},
        {"key": "os", "label": "Operating System", "value_type": "option", "unit": "",
         "is_variant_identity": False, "is_filterable": False, "is_comparable": False, "sort_order": 150},
        {"key": "battery_health", "label": "Battery Health", "value_type": "integer", "unit": "%",
         "is_variant_identity": False, "is_listing_level": True, "is_filterable": False,
         "is_comparable": False, "sort_order": 160},
        {"key": "battery_cycles", "label": "Battery Cycles", "value_type": "integer", "unit": "",
         "is_variant_identity": False, "is_listing_level": True, "is_filterable": False,
         "is_comparable": False, "sort_order": 170},
        {"key": "warranty_months", "label": "Warranty", "value_type": "integer", "unit": "months",
         "is_variant_identity": False, "is_listing_level": True, "is_filterable": False,
         "is_comparable": False, "sort_order": 180},
        {"key": "box_status", "label": "Box Status", "value_type": "option", "unit": "",
         "is_variant_identity": False, "is_listing_level": True, "is_filterable": True,
         "is_comparable": False, "sort_order": 190},
        {"key": "condition", "label": "Condition", "value_type": "option", "unit": "",
         "is_variant_identity": False, "is_listing_level": True, "is_filterable": True,
         "is_comparable": False, "sort_order": 200},
    ]


SPECS_BY_SLUG = {
    "phone": _specs_phone,
    "laptop": _specs_laptop,
    "tablet": _specs_phone,
    "console": _specs_phone,
    "vr_headset": _specs_phone,
    "camera": _specs_phone,
}


class Command(BaseCommand):
    help = "Seed product types and spec definitions (idempotent)."

    def handle(self, *args, **options):
        created_types = 0
        created_specs = 0
        created_options = 0

        for pt_data in PRODUCT_TYPES:
            pt, created = ProductType.objects.get_or_create(
                slug=pt_data["slug"],
                defaults={"name": pt_data["name"]},
            )
            if created:
                created_types += 1
                self.stdout.write(f"  Created product type: {pt.name}")

            spec_factory = SPECS_BY_SLUG.get(pt.slug)
            if not spec_factory:
                continue

            for spec_data in spec_factory():
                spec, spec_created = SpecDefinition.objects.get_or_create(
                    product_type=pt,
                    key=spec_data["key"],
                    defaults={
                        "label": spec_data["label"],
                        "value_type": spec_data["value_type"],
                        "unit": spec_data.get("unit", ""),
                        "is_variant_identity": spec_data.get("is_variant_identity", False),
                        "is_listing_level": spec_data.get("is_listing_level", False),
                        "is_filterable": spec_data.get("is_filterable", True),
                        "is_comparable": spec_data.get("is_comparable", True),
                        "sort_order": spec_data.get("sort_order", 0),
                        "aliases": spec_data.get("aliases", []),
                    },
                )
                if spec_created:
                    created_specs += 1

            # Seed SIM config options for phone type
            if pt.slug == "phone":
                sim_spec = SpecDefinition.objects.filter(product_type=pt, key="sim_config").first()
                if sim_spec:
                    for val, norm in [("2SIM", "2sim"), ("Dual SIM", "2sim"), ("eSIM", "esim"), ("1SIM", "")]:
                        _, opt_created = SpecOption.objects.get_or_create(
                            spec=sim_spec,
                            normalized_value=norm,
                            defaults={"value": val, "aliases": []},
                        )
                        if opt_created:
                            created_options += 1

            # Seed box_status options
            box_spec = SpecDefinition.objects.filter(product_type=pt, key="box_status").first()
            if box_spec:
                for val in ["Boxed", "No Box", "Sealed"]:
                    _, opt_created = SpecOption.objects.get_or_create(
                        spec=box_spec,
                        normalized_value=val.lower(),
                        defaults={"value": val, "aliases": []},
                    )
                    if opt_created:
                        created_options += 1

            # Seed condition options
            cond_spec = SpecDefinition.objects.filter(product_type=pt, key="condition").first()
            if cond_spec:
                for val in ["Sealed", "Used A+", "Used A", "Used B", "Used C", "Used", "Unknown"]:
                    _, opt_created = SpecOption.objects.get_or_create(
                        spec=cond_spec,
                        normalized_value=val.lower(),
                        defaults={"value": val, "aliases": []},
                    )
                    if opt_created:
                        created_options += 1

            # Seed laptop-specific options
            if pt.slug == "laptop":
                _seed_laptop_options(pt, created_options)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created {created_types} product types, "
                f"{created_specs} spec definitions, {created_options} spec options."
            )
        )


def _seed_laptop_options(pt, counter):
    """Seed common laptop spec options."""
    created_options = 0

    # CPU brand
    cpu_brand_spec = SpecDefinition.objects.filter(product_type=pt, key="cpu_brand").first()
    if cpu_brand_spec:
        for val in ["Intel", "AMD", "Apple", "Qualcomm"]:
            _, c = SpecOption.objects.get_or_create(
                spec=cpu_brand_spec, normalized_value=val.lower(),
                defaults={"value": val, "aliases": []},
            )
            if c:
                created_options += 1

    # GPU brand
    gpu_brand_spec = SpecDefinition.objects.filter(product_type=pt, key="gpu_brand").first()
    if gpu_brand_spec:
        for val in ["NVIDIA", "AMD", "Intel"]:
            _, c = SpecOption.objects.get_or_create(
                spec=gpu_brand_spec, normalized_value=val.lower(),
                defaults={"value": val, "aliases": []},
            )
            if c:
                created_options += 1

    # Panel type
    panel_spec = SpecDefinition.objects.filter(product_type=pt, key="panel_type").first()
    if panel_spec:
        for val in ["IPS", "VA", "TN", "OLED", "Mini-LED", "AMOLED"]:
            _, c = SpecOption.objects.get_or_create(
                spec=panel_spec, normalized_value=val.lower(),
                defaults={"value": val, "aliases": []},
            )
            if c:
                created_options += 1

    # Resolution
    res_spec = SpecDefinition.objects.filter(product_type=pt, key="resolution").first()
    if res_spec:
        for val in ["1920x1080", "2560x1440", "3840x2160", "2560x1600", "2880x1800", "3200x2000"]:
            _, c = SpecOption.objects.get_or_create(
                spec=res_spec, normalized_value=val,
                defaults={"value": val, "aliases": []},
            )
            if c:
                created_options += 1

    # RAM type
    ram_type_spec = SpecDefinition.objects.filter(product_type=pt, key="ram_type").first()
    if ram_type_spec:
        for val in ["DDR4", "DDR5", "LPDDR4X", "LPDDR5", "LPDDR5X", "Unified"]:
            _, c = SpecOption.objects.get_or_create(
                spec=ram_type_spec, normalized_value=val.lower(),
                defaults={"value": val, "aliases": []},
            )
            if c:
                created_options += 1

    # Keyboard layout
    kb_spec = SpecDefinition.objects.filter(product_type=pt, key="keyboard_layout").first()
    if kb_spec:
        for val in ["QWERTY", "AZERTY", "QWERTZ", "ISO", "ANSI"]:
            _, c = SpecOption.objects.get_or_create(
                spec=kb_spec, normalized_value=val.lower(),
                defaults={"value": val, "aliases": []},
            )
            if c:
                created_options += 1

    # OS
    os_spec = SpecDefinition.objects.filter(product_type=pt, key="os").first()
    if os_spec:
        for val in ["Windows 11", "Windows 10", "macOS", "ChromeOS", "Linux", "FreeDOS"]:
            _, c = SpecOption.objects.get_or_create(
                spec=os_spec, normalized_value=val.lower(),
                defaults={"value": val, "aliases": []},
            )
            if c:
                created_options += 1

    return created_options
