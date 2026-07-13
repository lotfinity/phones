from pathlib import Path
from io import StringIO
from tempfile import TemporaryDirectory

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from market.management.commands.queue_instagram_image_folder import (
    default_post_url,
    existing_post_for_image,
    output_directory_for,
)
from market.management.commands.match_instagram_manual_links_from_markdown import (
    canonical_post_url,
    records_from_markdown,
    shortcode_from_url,
)
from market.management.commands.process_ocr_queue import category_hint_from_nvidia_text
from market.models import Country, InstagramPost, RawListing, Source, SourceType
from market.services.parsing.phone_parser_v2 import parse_phone


class InstagramImageQueueHelpersTests(TestCase):
    def test_existing_post_for_image_matches_media_filename(self):
        source = Source.objects.create(
            name="Instagram @brothers_phone___official_",
            source_type=SourceType.INSTAGRAM,
            country=Country.ALGERIA,
            username="brothers_phone___official_",
        )
        post = InstagramPost.objects.create(
            source=source,
            post_url="https://www.instagram.com/p/DaVfcEYsWkH/",
            shortcode="DaVfcEYsWkH",
            media_local_path="media/instagram/brothers_phone___official_/manual_images/DaVfcEYsWkH.jpg",
            thumbnail_local_path="media/instagram/brothers_phone___official_/manual_images/DaVfcEYsWkH.jpg",
            needs_ocr=False,
            ocr_processed=True,
        )

        self.assertEqual(existing_post_for_image(source, Path("DaVfcEYsWkH.jpg")), post)

    def test_default_post_url_uses_shortcode_when_filename_is_shortcode(self):
        self.assertEqual(
            default_post_url("brothers_phone___official_", "DaVfcEYsWkH.jpg"),
            "https://www.instagram.com/p/DaVfcEYsWkH/",
        )


class InstagramImageQueuePathTests(SimpleTestCase):
    def test_output_directory_preserves_profile_media_folder(self):
        with TemporaryDirectory() as tmp:
            media_root = Path(tmp)
            folder = media_root / "instagram" / "brothers_phone___official_" / "manual_images"
            folder.mkdir(parents=True)
            with override_settings(MEDIA_ROOT=media_root):
                self.assertEqual(
                    output_directory_for(folder, "brothers_phone___official_"),
                    folder,
                )

    def test_output_directory_uses_manual_folder_for_external_folder(self):
        with TemporaryDirectory() as tmp:
            media_root = Path(tmp) / "media"
            external = Path(tmp) / "downloads"
            external.mkdir(parents=True)
            with override_settings(MEDIA_ROOT=media_root):
                self.assertEqual(
                    output_directory_for(external, "brothers_phone___official_"),
                    media_root / "instagram" / "brothers_phone___official_" / "manual_folder_images",
                )


class InstagramMarkdownImportHelpersTests(SimpleTestCase):
    def test_shortcode_from_profile_scoped_post_url(self):
        self.assertEqual(
            shortcode_from_url("https://www.instagram.com/brothers_phone___official_/p/Das1mKGMtzO/"),
            "Das1mKGMtzO",
        )

    def test_canonical_post_url_preserves_reel_kind(self):
        self.assertEqual(
            canonical_post_url("https://www.instagram.com/brothers_phone___official_/reel/DatDNOQs3GO/"),
            "https://www.instagram.com/reel/DatDNOQs3GO/",
        )

    def test_records_from_markdown_deduplicates_by_canonical_url(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.md"
            path.write_text(
                "\n".join(
                    [
                        "[![Photo by Brothers](https://cdn.example/one.jpg)]"
                        "(https://www.instagram.com/brothers_phone___official_/p/Das1mKGMtzO/)",
                        "[![Duplicate](https://cdn.example/two.jpg)]"
                        "(https://www.instagram.com/p/Das1mKGMtzO/)",
                    ]
                )
            )

            records = records_from_markdown(path)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["post_url"], "https://www.instagram.com/p/Das1mKGMtzO/")
        self.assertEqual(records[0]["image_basename"], "one.jpg")


class InstagramNvidiaCategoryHintTests(SimpleTestCase):
    def test_category_label_maps_to_raw_listing_hint(self):
        self.assertEqual(
            category_hint_from_nvidia_text("Category: laptop\nModel: MacBook Air M2"),
            RawListing.CategoryHint.LAPTOPS,
        )
        self.assertEqual(
            category_hint_from_nvidia_text("Category: console\nModel: ROG Ally X"),
            RawListing.CategoryHint.CONSOLES,
        )
        self.assertEqual(
            category_hint_from_nvidia_text("Category: phone\nModel: iPhone 15 Pro"),
            RawListing.CategoryHint.PHONES,
        )


class InstagramNvidiaStructuredPhoneParserTests(SimpleTestCase):
    def test_structured_storage_does_not_become_fake_ram(self):
        parsed = parse_phone(
            "Model: iPhone 15\nStorage: 128GB\nBattery: 98%\nPrice: 77000 DZD",
            "iPhone 15",
            {
                "nvidia_structured": {
                    "category": "phone",
                    "brand": "Apple",
                    "model": "iPhone 15",
                    "storage_gb": 128,
                    "ram_gb": None,
                    "battery_health": "98%",
                    "store_warranty": "Garantie 6 Mois",
                    "price": {"amount": 77000, "currency": "DZD", "raw": "77000"},
                }
            },
        )

        self.assertEqual(parsed["storage_gb"], 128)
        self.assertIsNone(parsed["ram_gb"])
        self.assertEqual(parsed["price_original"], 77000)
        self.assertEqual(parsed["store_warranty"], "Garantie 6 Mois")


class InstagramMarkdownPipelineCommandTests(TestCase):
    def test_dry_run_infers_username_and_previews_import(self):
        with TemporaryDirectory() as tmp:
            media_root = Path(tmp) / "media"
            markdown = Path(tmp) / "RDphone35.md"
            markdown.write_text(
                "\n".join(
                    [
                        'source: "https://www.instagram.com/rd.phone35?igsh=test"',
                        "[![iPhone 17 256 GB](https://cdn.example/phone.jpg)]"
                        "(https://www.instagram.com/rd.phone35/reel/DaXyZ123abc/)",
                    ]
                )
            )

            out = StringIO()
            with override_settings(MEDIA_ROOT=media_root):
                call_command("run_instagram_markdown_pipeline", str(markdown), "--dry-run", stdout=out)

        output = out.getvalue()
        self.assertIn("Source: @rd.phone35", output)
        self.assertIn("Post/reel links found: 1", output)
        self.assertIn("Would import/update 1 Markdown posts", output)

    def test_refuses_non_nvidia_ocr_backend_before_writes(self):
        with TemporaryDirectory() as tmp:
            media_root = Path(tmp) / "media"
            markdown = Path(tmp) / "RDphone35.md"
            markdown.write_text(
                "\n".join(
                    [
                        'source: "https://www.instagram.com/rd.phone35"',
                        "[![iPhone 17 256 GB](https://cdn.example/phone.jpg)]"
                        "(https://www.instagram.com/rd.phone35/reel/DaXyZ123abc/)",
                    ]
                )
            )

            with override_settings(MEDIA_ROOT=media_root, OCR_BACKEND="tesseract"):
                with self.assertRaisesMessage(CommandError, "NVIDIA-only"):
                    call_command("run_instagram_markdown_pipeline", str(markdown), stdout=StringIO())

        self.assertEqual(InstagramPost.objects.count(), 0)
