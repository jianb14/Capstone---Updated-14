"""Gallery previews stay small and cached without replacing uploaded originals."""
import io
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from .models import GalleryCategory, GalleryImage


class GalleryPreviewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.category = GalleryCategory.objects.create(name='Birthday')
        self.image = GalleryImage.objects.create(category=self.category, caption='Birthday setup')
        output = io.BytesIO()
        Image.new('RGB', (2048, 1536), '#c8a77c').save(output, 'PNG')
        self.original = output.getvalue()
        self.image.image.save('gallery-large.png', ContentFile(self.original))
        self.url = reverse('gallery_image_preview', args=[self.image.pk])

    def test_guest_preview_is_smaller_cached_and_keeps_original(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/webp')
        self.assertEqual(response['Cache-Control'], 'public, max-age=86400')
        self.assertLess(len(response.content), len(self.original))
        with Image.open(io.BytesIO(response.content)) as image:
            self.assertEqual(image.size, (640, 480))
        with self.image.image.open('rb') as original:
            self.assertEqual(original.read(), self.original)
        with patch.object(self.image.image.storage, 'open', side_effect=AssertionError('Cached preview reopened upload')):
            self.assertEqual(self.client.get(self.url).content, response.content)
            cached = self.client.get(self.url, HTTP_IF_NONE_MATCH=response['ETag'])
            self.assertEqual(cached.status_code, 304)
            self.assertEqual(cached.content, b'')

    def test_replacing_image_changes_version_and_preview(self):
        before = self.client.get(self.url)
        output = io.BytesIO()
        Image.new('RGB', (300, 600), '#324a5f').save(output, 'PNG')
        self.image.image.save('gallery-replacement.png', ContentFile(output.getvalue()))
        after = self.client.get(self.url, HTTP_IF_NONE_MATCH=before['ETag'])
        self.assertEqual(after.status_code, 200)
        self.assertNotEqual(before['ETag'], after['ETag'])
        self.assertNotEqual(before.content, after.content)
        with Image.open(io.BytesIO(after.content)) as image:
            self.assertEqual(image.size, (300, 600))

    def test_hidden_deleted_and_invalid_images_do_not_produce_previews(self):
        cached = self.client.get(self.url)
        self.image.is_active = False
        self.image.save(update_fields=['is_active'])
        self.assertEqual(self.client.get(self.url, HTTP_IF_NONE_MATCH=cached['ETag']).status_code, 404)
        self.image.is_active = True
        self.image.save(update_fields=['is_active'])
        self.image.image.save('invalid-gallery.png', ContentFile(b'not an image'))
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.image.delete()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_gallery_uses_previews_and_retains_original_for_lightbox(self):
        GalleryImage.objects.create(category=self.category, image='gallery/hidden.png', is_active=False)
        response = self.client.get(reverse('gallery'))
        self.assertContains(response, f'src="{self.url}?v=')
        self.assertContains(response, f'data-full-image="{self.image.image.url}"')
        self.assertNotContains(response, 'gallery/hidden.png')
        self.assertEqual(len(response.context['gallery_images']), 1)

    def test_preview_endpoint_is_read_only(self):
        self.assertEqual(self.client.post(self.url).status_code, 405)
