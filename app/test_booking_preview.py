"""Tests for the booking Step 2 preview images (package/add-on/additional)."""
import io
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import AddOn, AdditionalOnly, Package, User

# Offline storage: para hindi humawak ng Cloudinary/network sa tests.
_OFFLINE_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


def _preview_upload(name="preview.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "#e63946").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class TempMediaMixin:
    """Lahat ng upload ay pumapasok sa pansamantalang MEDIA_ROOT (may cleanup)."""

    def setUp(self):
        super().setUp()
        media_temp = tempfile.TemporaryDirectory()
        self.addCleanup(media_temp.cleanup)
        settings_override = override_settings(
            STORAGES=_OFFLINE_STORAGES, MEDIA_ROOT=media_temp.name
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)


class BookingPreviewModelTests(TempMediaMixin, TestCase):
    def test_preview_images_attach_to_each_item(self):
        package = Package.objects.create(name="Grand", features="Balloons", price=1000)
        addon = AddOn.objects.create(
            name="Arch", features="Entrance arch", price=500, solo_price=700
        )
        additional = AdditionalOnly.objects.create(
            name="Stand", features="Welcome stand", price=100
        )

        package.preview_images.create(image=_preview_upload("pkg.png"))
        addon.preview_images.create(image=_preview_upload("addon.png"))
        additional.preview_images.create(image=_preview_upload("additional.png"))

        self.assertEqual(package.preview_images.count(), 1)
        self.assertEqual(addon.preview_images.count(), 1)
        self.assertEqual(additional.preview_images.count(), 1)

    def test_str_mentions_parent_item(self):
        package = Package.objects.create(name="Grand", features="Balloons", price=1000)
        preview = package.preview_images.create(image=_preview_upload("pkg.png"))
        self.assertIn("Grand", str(preview))


class BookingPreviewPageTests(TempMediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.customer = User.objects.create_user(
            username="cust", email="cust@test.com", password="pass12345", role="customer"
        )
        self.package = Package.objects.create(
            name="Grand Package", features="Balloons", price=1000, is_active=True
        )
        self.package.preview_images.create(image=_preview_upload("pkg1.png"))
        self.package.preview_images.create(image=_preview_upload("pkg2.png"))

    def test_step2_payload_and_four_step_markup_rendered(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("booking_page"))
        self.assertEqual(response.status_code, 200)

        for marker in (
            'id="booking-preview-data"',
            'id="step-5-indicator"',
            'id="step-2"',
            'id="btnNextToDetails"',
            'id="btnBackToPackages"',
            "function renderPackagePreview()",
            "preview-group-grid",
        ):
            self.assertContains(response, marker)

        payload = response.context["preview_data"]
        self.assertIn(str(self.package.id), payload["packages"])
        self.assertEqual(len(payload["packages"][str(self.package.id)]), 2)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("booking_page"))
        self.assertEqual(response.status_code, 302)


class BookingPreviewAdminTests(TempMediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username="admin1", email="admin1@test.com", password="pass12345", role="admin"
        )
        self.package = Package.objects.create(
            name="Grand", features="Balloons", price=1000
        )

    def test_create_caps_preview_images_at_two(self):
        self.client.force_login(self.admin_user)
        uploads = [_preview_upload(f"p{i}.png") for i in range(3)]
        response = self.client.post(
            reverse("admin_package_create"),
            {
                "name": "Capped Package",
                "price": "1500.00",
                "features": "Balloons\nTable setup",
                "preview_images": uploads,
            },
        )
        self.assertEqual(response.status_code, 302)
        package = Package.objects.get(name="Capped Package")
        self.assertEqual(package.preview_images.count(), 2)

    def test_edit_removes_and_adds_new(self):
        first = self.package.preview_images.create(image=_preview_upload("old1.png"))
        self.package.preview_images.create(image=_preview_upload("old2.png"))
        before_ids = set(self.package.preview_images.values_list("id", flat=True))

        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse("admin_package_edit", args=[self.package.id]),
            {
                "name": self.package.name,
                "price": "1000.00",
                "features": "Balloons",
                "remove_preview_ids": str(first.id),
                "preview_images": [_preview_upload("new1.png")],
            },
        )
        self.assertEqual(response.status_code, 302)

        after_ids = set(self.package.preview_images.values_list("id", flat=True))
        self.assertNotIn(first.id, after_ids)
        # 2 dati - 1 tinanggal + 1 bago = 2 pa ring natitira
        self.assertEqual(len(after_ids), 2)
        self.assertEqual(len(after_ids - before_ids), 1)

    def test_addon_and_additional_forms_save_previews(self):
        self.client.force_login(self.admin_user)

        self.client.post(
            reverse("admin_addon_create"),
            {
                "name": "Photo Booth",
                "price": "500.00",
                "solo_price": "700.00",
                "features": "Booth",
                "preview_images": [_preview_upload("a1.png")],
            },
        )
        addon = AddOn.objects.get(name="Photo Booth")
        self.assertEqual(addon.preview_images.count(), 1)

        self.client.post(
            reverse("admin_additional_create"),
            {
                "name": "Signage",
                "price": "100.00",
                "features": "Sign",
                "preview_images": [_preview_upload("b1.png")],
            },
        )
        additional = AdditionalOnly.objects.get(name="Signage")
        self.assertEqual(additional.preview_images.count(), 1)

    def test_forms_no_longer_expose_single_image_input(self):
        self.client.force_login(self.admin_user)
        for url_name in (
            "admin_package_create",
            "admin_addon_create",
            "admin_additional_create",
        ):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'name="image"')
            self.assertNotContains(response, 'type="checkbox" name="remove_preview"')
            self.assertContains(response, 'name="remove_preview_ids"')
            self.assertContains(response, "Booking Preview Images")
            self.assertContains(response, "(max 2)")

    def test_detail_page_shows_preview_images_grid(self):
        self.package.preview_images.create(image=_preview_upload("d1.png"))
        self.package.preview_images.create(image=_preview_upload("d2.png"))
        self.client.force_login(self.admin_user)

        response = self.client.get(
            reverse("admin_package_detail", args=[self.package.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "detail-preview-grid")
        self.assertContains(response, "d1.png")

        empty_package = Package.objects.create(
            name="No Preview", features="X", price=1
        )
        response = self.client.get(
            reverse("admin_package_detail", args=[empty_package.id])
        )
        self.assertContains(response, "No Image Available")