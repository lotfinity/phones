import ipaddress
import os
import socket
import struct
import tempfile
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from market.clean_models import PhoneOpportunitySnapshot
from market.models import (
    Brand,
    Condition,
    Country,
    PhoneListing,
    PhoneModel,
    RawListing,
    Source,
    SourceType,
)
from market.views_images import (
    _collect_image_candidates,
    _is_local_filesystem_path,
    _normalize_image_url,
    _resolve_local_image_path,
    _sniff_image_type,
)


def _make_jpeg_bytes():
    """Return minimal valid JPEG bytes."""
    return b"\xff\xd8\xff\xe0" + b"\x00" * 100


def _make_webp_bytes():
    """Return minimal valid WebP bytes."""
    # RIFF header + WEBP signature
    return b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100


def _make_png_bytes():
    """Return minimal valid PNG bytes."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


class SniffImageTypeTests(TestCase):
    def test_jpeg(self):
        self.assertEqual(_sniff_image_type(_make_jpeg_bytes()), "image/jpeg")

    def test_png(self):
        self.assertEqual(_sniff_image_type(_make_png_bytes()), "image/png")

    def test_webp(self):
        self.assertEqual(_sniff_image_type(_make_webp_bytes()), "image/webp")

    def test_empty(self):
        self.assertEqual(_sniff_image_type(b""), "")

    def test_unknown(self):
        self.assertEqual(_sniff_image_type(b"random data here"), "")


class NormalizeImageUrlTests(TestCase):
    def test_empty_string(self):
        self.assertEqual(_normalize_image_url(""), "")

    def test_none_like(self):
        self.assertEqual(_normalize_image_url(None), "")

    def test_whitespace_only(self):
        self.assertEqual(_normalize_image_url("   "), "")

    def test_protocol_relative(self):
        result = _normalize_image_url("//example.com/img.jpg")
        self.assertEqual(result, "https://example.com/img.jpg")

    def test_http_url_preserved(self):
        url = "http://example.com/img.jpg"
        self.assertEqual(_normalize_image_url(url), url)

    def test_https_url_preserved(self):
        url = "https://example.com/img.jpg"
        self.assertEqual(_normalize_image_url(url), url)

    def test_data_url_rejected(self):
        self.assertEqual(_normalize_image_url("data:image/png;base64,abc"), "")

    def test_javascript_url_rejected(self):
        self.assertEqual(_normalize_image_url("javascript:alert(1)"), "")

    def test_ftp_url_rejected(self):
        self.assertEqual(_normalize_image_url("ftp://example.com/img.jpg"), "")

    def test_url_with_credentials_rejected(self):
        self.assertEqual(
            _normalize_image_url("https://user:pass@example.com/img.jpg"), ""
        )

    def test_whitespace_trimmed(self):
        url = "  https://example.com/img.jpg  "
        self.assertEqual(_normalize_image_url(url), "https://example.com/img.jpg")


class IsLocalFilesystemPathTests(TestCase):
    def test_absolute_path(self):
        self.assertTrue(_is_local_filesystem_path("/home/user/media/img.jpg"))

    def test_relative_media_path(self):
        self.assertTrue(_is_local_filesystem_path("media/instagram/img.jpg"))

    def test_http_url(self):
        self.assertFalse(_is_local_filesystem_path("https://example.com/img.jpg"))

    def test_empty(self):
        self.assertFalse(_is_local_filesystem_path(""))

    def test_ftp_url(self):
        self.assertFalse(_is_local_filesystem_path("ftp://example.com/img.jpg"))


class ResolveLocalImagePathTests(TestCase):
    def test_absolute_path_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.jpg")
            with open(test_file, "wb") as f:
                f.write(_make_jpeg_bytes())
            with override_settings(MEDIA_ROOT=tmpdir):
                abs_path, rel_path = _resolve_local_image_path(test_file)
                self.assertEqual(abs_path, os.path.normpath(test_file))
                self.assertTrue(rel_path.endswith(".jpg"))

    def test_relative_path_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rel = "test_images/photo.jpg"
            abs_path_target = os.path.join(tmpdir, rel)
            os.makedirs(os.path.dirname(abs_path_target))
            with open(abs_path_target, "wb") as f:
                f.write(_make_jpeg_bytes())

            with override_settings(MEDIA_ROOT=tmpdir):
                abs_path, rel_path = _resolve_local_image_path(rel)
                self.assertEqual(abs_path, os.path.normpath(abs_path_target))

    def test_path_not_found(self):
        with self.assertRaises(ValueError):
            _resolve_local_image_path("/nonexistent/path/img.jpg")

    def test_empty_path(self):
        with self.assertRaises(ValueError):
            _resolve_local_image_path("")

    def test_path_escapes_media_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(MEDIA_ROOT=tmpdir):
                with self.assertRaises(ValueError):
                    _resolve_local_image_path("../../../etc/passwd")


class CollectImageCandidatesTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name="TestBrand")
        self.model = PhoneModel.objects.create(
            brand=self.brand, canonical_name="TestModel"
        )
        self.raw = RawListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            listing_url="https://example.com/listing",
            image_url="https://cdn.example.com/raw.jpg",
            content_hash="abc123",
        )

    def test_listing_with_http_image_url(self):
        listing = PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=self.model,
            title="Test",
            listing_url="https://example.com/listing",
            image_url="https://cdn.example.com/listing.jpg",
        )
        candidates = _collect_image_candidates(listing)
        urls = [c[0] for c in candidates]
        self.assertEqual(urls, ["https://cdn.example.com/listing.jpg"])

    def test_listing_with_local_path_and_raw_http(self):
        listing = PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=self.model,
            title="Test",
            listing_url="https://example.com/listing",
            image_url="/home/user/media/img.jpg",
            raw_listing=self.raw,
        )
        candidates = _collect_image_candidates(listing)
        urls = [c[0] for c in candidates]
        self.assertIn("/home/user/media/img.jpg", urls)
        self.assertIn("https://cdn.example.com/raw.jpg", urls)

    def test_deduplication(self):
        self.raw.image_url = "https://cdn.example.com/same.jpg"
        self.raw.save()
        listing = PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=self.model,
            title="Test",
            listing_url="https://example.com/listing",
            image_url="https://cdn.example.com/same.jpg",
            raw_listing=self.raw,
        )
        candidates = _collect_image_candidates(listing)
        urls = [c[0] for c in candidates]
        self.assertEqual(len(urls), 1)

    def test_empty_image_urls(self):
        listing = PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=self.model,
            title="Test",
            listing_url="https://example.com/listing",
            image_url="",
            raw_listing=self.raw,
        )
        self.raw.image_url = ""
        self.raw.save()
        candidates = _collect_image_candidates(listing)
        self.assertEqual(candidates, [])


class CleanListingImageProxyTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name="Apple")
        self.model = PhoneModel.objects.create(
            brand=self.brand, canonical_name="Image Test Phone"
        )
        self.listing = PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=self.model,
            title="Image proxy listing",
            price_original=Decimal("40000.00"),
            currency_original="TRY",
            price_eur=Decimal("750.00"),
            condition=Condition.SEALED,
            storage_gb=256,
            listing_url="https://example.com/listing",
            image_url="https://images.example.com/photo.webp",
            review_status=PhoneListing.ReviewStatus.APPROVED,
        )
        self.url = reverse(
            "clean_listing_image",
            kwargs={"category": "phone", "pk": self.listing.pk},
        )

    def test_proxy_returns_same_origin_cacheable_raster_image(self):
        with patch("market.views_images._download_image") as mock:
            mock.return_value = (b"fake-webp-bytes", "image/webp")
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "image/webp")
        self.assertEqual(response.content, b"fake-webp-bytes")
        self.assertIn("max-age=21600", response.headers["Cache-Control"])
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_proxy_rejects_unknown_category(self):
        response = self.client.get(
            reverse(
                "clean_listing_image",
                kwargs={"category": "legacy", "pk": self.listing.pk},
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_proxy_returns_404_for_no_image(self):
        listing = PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=self.model,
            title="No image listing",
            image_url="",
        )
        response = self.client.get(
            reverse(
                "clean_listing_image",
                kwargs={"category": "phone", "pk": listing.pk},
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_valid_jpeg_response(self):
        with patch("market.views_images._download_image") as mock:
            mock.return_value = (_make_jpeg_bytes(), "image/jpeg")
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "image/jpeg")
        self.assertTrue(response.content.startswith(b"\xff\xd8\xff"))

    def test_valid_webp_response(self):
        with patch("market.views_images._download_image") as mock:
            mock.return_value = (_make_webp_bytes(), "image/webp")
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "image/webp")

    def test_generic_octet_stream_with_valid_image_bytes(self):
        with patch("market.views_images._download_image") as mock:
            mock.return_value = (_make_jpeg_bytes(), "image/jpeg")
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "image/jpeg")

    def test_redirect_to_valid_public_image(self):
        with patch("market.views_images._download_image") as mock:
            mock.return_value = (b"redirect-result-bytes", "image/png")
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"redirect-result-bytes")

    def test_redirect_to_private_ip_rejected(self):
        with patch("market.views_images._download_image") as mock:
            mock.side_effect = ValueError("Image host is not public")
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_direct_private_ip_rejected(self):
        self.listing.image_url = "http://192.168.1.1/photo.jpg"
        self.listing.save(update_fields=["image_url"])
        with patch("market.views_images._download_image") as mock:
            mock.side_effect = ValueError("Image host is not public")
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_oversized_response_rejected(self):
        with patch("market.views_images._download_image") as mock:
            mock.side_effect = ValueError("Remote image exceeded the size limit")
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_timeout_handled(self):
        import requests as req_lib

        with patch("market.views_images._download_image") as mock:
            mock.side_effect = req_lib.Timeout("Connection timed out")
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_first_403_then_referer_retry_succeeds(self):
        with patch("market.views_images._download_image") as mock:
            # First call (with referer) returns 403, second (without) succeeds
            mock.side_effect = [
                ValueError("403 Forbidden"),
                (b"retry-ok-bytes", "image/png"),
            ]
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"retry-ok-bytes")
        self.assertEqual(mock.call_count, 2)

    def test_first_candidate_fails_second_succeeds(self):
        raw = RawListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            listing_url="https://example.com/listing",
            image_url="https://cdn.example.com/raw-image.jpg",
            content_hash="raw123",
        )
        self.listing.raw_listing = raw
        self.listing.save(update_fields=["raw_listing"])

        with patch("market.views_images._download_image") as mock:
            # First candidate fails, second succeeds
            mock.side_effect = [
                ValueError("Connection refused"),
                (b"second-candidate-ok", "image/jpeg"),
            ]
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"second-candidate-ok")
        self.assertEqual(mock.call_count, 2)

    def test_all_candidates_fail_returns_404(self):
        with patch("market.views_images._download_image") as mock:
            mock.side_effect = ValueError("Connection refused")
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)
        self.assertIn(b"", response.content)

    def test_no_image_candidate_returns_404(self):
        listing = PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=self.model,
            title="Empty image listing",
            image_url="",
            listing_url="https://example.com/no-image-listing",
        )
        response = self.client.get(
            reverse(
                "clean_listing_image",
                kwargs={"category": "phone", "pk": listing.pk},
            )
        )
        self.assertEqual(response.status_code, 404)


class LocalFilesystemImageTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name="Samsung")
        self.model = PhoneModel.objects.create(
            brand=self.brand, canonical_name="Galaxy Z Fold 7"
        )
        self.media_dir = tempfile.mkdtemp()
        # Create a test image file
        self.test_image_path = os.path.join(self.media_dir, "test_image.jpg")
        with open(self.test_image_path, "wb") as f:
            f.write(_make_jpeg_bytes())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.media_dir, ignore_errors=True)

    def test_local_absolute_path_served(self):
        listing = PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=self.model,
            title="Local image test",
            image_url=self.test_image_path,
        )
        url = reverse(
            "clean_listing_image",
            kwargs={"category": "phone", "pk": listing.pk},
        )
        with override_settings(MEDIA_ROOT=self.media_dir):
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "image/jpeg")
        self.assertTrue(response.content.startswith(b"\xff\xd8\xff"))
        self.assertIn("max-age=21600", response.headers["Cache-Control"])

    def test_local_relative_path_served(self):
        rel = "media/instagram/test_profile/photo.jpg"
        abs_path = os.path.join(self.media_dir, rel)
        os.makedirs(os.path.dirname(abs_path))
        with open(abs_path, "wb") as f:
            f.write(_make_png_bytes())

        listing = PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=self.model,
            title="Relative local image test",
            image_url=rel,
        )
        url = reverse(
            "clean_listing_image",
            kwargs={"category": "phone", "pk": listing.pk},
        )
        with override_settings(MEDIA_ROOT=self.media_dir):
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "image/png")

    def test_local_file_not_found_returns_404(self):
        listing = PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=self.model,
            title="Missing local image test",
            image_url="/nonexistent/path/img.jpg",
        )
        url = reverse(
            "clean_listing_image",
            kwargs={"category": "phone", "pk": listing.pk},
        )
        with override_settings(MEDIA_ROOT=self.media_dir):
            response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_local_path_outside_media_root_rejected(self):
        listing = PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=self.model,
            title="Escaping path test",
            image_url="../../../etc/passwd",
        )
        url = reverse(
            "clean_listing_image",
            kwargs={"category": "phone", "pk": listing.pk},
        )
        with override_settings(MEDIA_ROOT=self.media_dir):
            response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_local_file_webp_served(self):
        webp_path = os.path.join(self.media_dir, "photo.webp")
        with open(webp_path, "wb") as f:
            f.write(_make_webp_bytes())

        listing = PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=self.model,
            title="WebP local image test",
            image_url=webp_path,
        )
        url = reverse(
            "clean_listing_image",
            kwargs={"category": "phone", "pk": listing.pk},
        )
        with override_settings(MEDIA_ROOT=self.media_dir):
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "image/webp")


class PermissionBoundaryTests(TestCase):
    """Permission boundary tests for clean listing images."""

    def setUp(self):
        self.brand = Brand.objects.create(name="Samsung")
        self.model = PhoneModel.objects.create(
            brand=self.brand, canonical_name="Permission Test Phone"
        )
        self.snapshot = PhoneOpportunitySnapshot.objects.create(
            brand="Samsung",
            model="Permission Test Phone",
            storage_gb=256,
            algeria_min_eur=Decimal("500.00"),
            algeria_avg_eur=Decimal("520.00"),
            turkiye_min_eur=Decimal("700.00"),
            turkiye_avg_eur=Decimal("750.00"),
            gross_margin_eur=Decimal("250.00"),
            margin_percent=Decimal("50.00"),
            recommendation=PhoneOpportunitySnapshot.Recommendation.BUY,
            confidence_score=90,
        )
        self.listing = PhoneListing.objects.create(
            source_type=SourceType.SAHIBINDEN,
            country=Country.TURKIYE,
            phone_model=self.model,
            title="Permission test listing",
            price_original=Decimal("40000.00"),
            currency_original="TRY",
            price_eur=Decimal("750.00"),
            condition=Condition.SEALED,
            storage_gb=256,
            listing_url="https://example.com/listing",
            image_url="https://example.com/photo.jpg",
            review_status=PhoneListing.ReviewStatus.APPROVED,
        )
        User = get_user_model()
        self.public_user = None
        self.staff_user = User.objects.create_user(
            username="perm-staff",
            password="test-pass",
            is_staff=True,
        )
        self.superuser = User.objects.create_superuser(
            username="perm-superuser",
            email="perm@example.com",
            password="test-pass",
        )

    def test_public_user_cannot_see_superuser_pricing(self):
        response = self.client.get(
            reverse("ui_preview_card_opportunities")
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "superuser pricing")

    def test_staff_user_cannot_see_superuser_pricing(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(
            reverse("ui_preview_card_opportunities")
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "superuser pricing")

    def test_superuser_sees_full_internal_detail(self):
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("ui_preview_card_opportunities")
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "superuser pricing")

    def test_public_detail_response_is_private_no_store(self):
        response = self.client.get(
            reverse(
                "clean_opportunity_detail",
                kwargs={"category": "phone", "pk": self.snapshot.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        cache_control = response.headers.get("Cache-Control", "")
        self.assertIn("private", cache_control)
        self.assertIn("no-store", cache_control)
        self.assertIn("Cookie", response.headers.get("Vary", ""))

    def test_superuser_detail_response_is_private_no_store(self):
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse(
                "clean_opportunity_detail",
                kwargs={"category": "phone", "pk": self.snapshot.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        cache_control = response.headers.get("Cache-Control", "")
        self.assertIn("private", cache_control)
        self.assertIn("no-store", cache_control)
        self.assertIn("Cookie", response.headers.get("Vary", ""))
