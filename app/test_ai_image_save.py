"""Regression tests for AI-generated chat image persistence.

``_save_generated_image`` must derive its URL from Django's storage layer:
on production MediaCloudinaryStorage uploads the file to Cloudinary and the
returned URL renders there, while the old implementation hardcoded
``/media/ai_generated/...`` -- which 404s on the deployed site because no
``/media/`` route is mounted when Cloudinary is configured. The rewrite
command covers messages that still embed those legacy paths.
"""

import io
from unittest.mock import patch
from urllib.parse import urlparse

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.test import TestCase
from PIL import Image

from .models import ChatMessage, User
from .services import _save_generated_image


def _tiny_png_bytes(color="red"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


class AiImageSaveTests(TestCase):
    """_save_generated_image must go through default_storage, always."""

    FAKE_URL = (
        "https://res.cloudinary.com/demo/image/upload/v1/media/ai_generated/probe.png"
    )

    def test_bytes_input_uses_storage_save_and_url(self):
        with patch("app.services.default_storage") as storage:
            storage.save.return_value = "media/ai_generated/probe.png"
            storage.url.return_value = self.FAKE_URL
            url = _save_generated_image(_tiny_png_bytes())

        self.assertEqual(url, self.FAKE_URL)
        storage.save.assert_called_once()
        name, content = storage.save.call_args[0]
        self.assertTrue(name.startswith("ai_generated/"))
        self.assertTrue(name.endswith(".png"))
        self.assertIsInstance(content, ContentFile)

    def test_pil_image_input_uses_storage_save_and_url(self):
        with patch("app.services.default_storage") as storage:
            storage.save.return_value = "media/ai_generated/probe.png"
            storage.url.return_value = self.FAKE_URL
            url = _save_generated_image(Image.new("RGB", (8, 8), "blue"))

        self.assertEqual(url, self.FAKE_URL)
        storage.save.assert_called_once()
        self.assertIsInstance(storage.save.call_args[0][1], ContentFile)

    def test_real_storage_roundtrip(self):
        url = _save_generated_image(_tiny_png_bytes())
        self.assertTrue(url)
        # Resolve the name back through default_storage so the assertion
        # holds for FileSystemStorage (local) and Cloudinary (production).
        last_segment = urlparse(url).path.rsplit("/", 1)[-1]
        name = f"ai_generated/{last_segment}"
        try:
            self.assertTrue(default_storage.exists(name))
            self.assertEqual(default_storage.url(name), url)
        finally:
            default_storage.delete(name)


class RewriteAiImageUrlsTests(TestCase):
    """Legacy /media/ai_generated srcs in chat messages -> storage URLs."""

    OLD_PROBE = '<img src="/media/ai_generated/design_probe.png" alt="Balloorina Design Concept">'
    OLD_MISSING = '<img src="/media/ai_generated/design_missing.png" alt="Balloorina Design Concept">'

    def setUp(self):
        self.user = User.objects.create(username="rewrite_test_user", role="customer")

    def _create_message(self, text):
        return ChatMessage.objects.create(
            sender=self.user, receiver=self.user, message=text
        )

    @staticmethod
    def _fake_storage():
        storage = patch("app.management.commands.rewrite_ai_image_urls.default_storage")
        mocked = storage.start()
        mocked.exists.side_effect = lambda name: name.endswith("design_probe.png")
        mocked.url.side_effect = (
            lambda name: f"https://res.cloudinary.com/demo/image/upload/v1/media/{name}"
        )
        return storage, mocked

    def test_dry_run_does_not_write(self):
        message = self._create_message(self.OLD_PROBE)
        storage_patch, _ = self._fake_storage()
        try:
            call_command("rewrite_ai_image_urls", stdout=io.StringIO())
        finally:
            storage_patch.stop()

        message.refresh_from_db()
        self.assertEqual(message.message, self.OLD_PROBE)

    def test_apply_rewrites_resolvable_and_keeps_missing(self):
        message = self._create_message(f"{self.OLD_PROBE} {self.OLD_MISSING}")
        storage_patch, _ = self._fake_storage()
        try:
            call_command("rewrite_ai_image_urls", "--apply", stdout=io.StringIO())
        finally:
            storage_patch.stop()

        message.refresh_from_db()
        self.assertIn(
            "https://res.cloudinary.com/demo/image/upload/v1/media/"
            "ai_generated/design_probe.png",
            message.message,
        )
        self.assertNotIn(self.OLD_PROBE, message.message)
        # The missing file stays untouched so nothing is rewritten blindly.
        self.assertIn("/media/ai_generated/design_missing.png", message.message)
