from pathlib import Path
from tempfile import TemporaryDirectory

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
from market.models import Country, InstagramPost, Source, SourceType


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
