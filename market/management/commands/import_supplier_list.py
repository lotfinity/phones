from django.core.management.base import BaseCommand, CommandError

from market.models import Country, Source, SourceType, SupplierPrice
from market.parsers.supplier_parser import parse_supplier_line
from market.services.currency import usd_to_eur
from market.services.matching import get_or_create_model, get_or_create_variant


class Command(BaseCommand):
    help = "Import rough WhatsApp-style supplier price lists."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument("--source-name", default="Supplier list")
        parser.add_argument("--country", choices=Country.values, default=Country.OTHER)

    def handle(self, *args, **options):
        path = options["file"]
        try:
            lines = open(path, encoding="utf-8").read().splitlines()
        except OSError as exc:
            raise CommandError(str(exc)) from exc

        source, _ = Source.objects.get_or_create(
            source_type=SourceType.SUPPLIER,
            username="supplier-list",
            defaults={"name": options["source_name"], "country": options["country"]},
        )
        updates = {}
        if source.name != options["source_name"]:
            updates["name"] = options["source_name"]
        if source.country != options["country"]:
            updates["country"] = options["country"]
        if updates:
            for field, value in updates.items():
                setattr(source, field, value)
            source.save(update_fields=list(updates))

        imported = 0
        skipped = 0
        unchanged = 0
        for line in lines:
            parsed = parse_supplier_line(line)
            if not parsed.raw_text or not parsed.price_usd:
                skipped += 1
                continue
            product_model = get_or_create_model(parsed.model_text) if parsed.model_text else None
            variant = (
                get_or_create_variant(product_model, parsed.storage_gb)
                if product_model and parsed.storage_gb
                else None
            )
            _, created = SupplierPrice.objects.get_or_create(
                raw_text=parsed.raw_text,
                source=source,
                supplier_price_usd=parsed.price_usd,
                defaults={
                    "product_model": product_model,
                    "variant": variant,
                    "supplier_price_eur": usd_to_eur(parsed.price_usd),
                    "parsed_confidence": parsed.confidence,
                    "active": True,
                },
            )
            if created:
                imported += 1
            else:
                unchanged += 1

        self.stdout.write(
            self.style.SUCCESS(f"Imported {imported} supplier rows. Skipped {skipped}. Unchanged {unchanged}.")
        )
