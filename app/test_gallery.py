"""Gallery previews stay small and cached without replacing uploaded originals."""
import io
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from .models import GalleryCategory, GalleryImage, User


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


class GalleryCaptionAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='gallery-caption-admin', role='admin', email_verified=True)
        self.client.force_login(self.admin)
        self.category = GalleryCategory.objects.create(name='Birthday')
        self.other_category = GalleryCategory.objects.create(name='Corporate')
        self.image = GalleryImage.objects.create(category=self.category,
            image='gallery/original-caption.png', caption='Original caption', is_active=True)
        self.edit_url = reverse('admin_gallery_image_edit', args=[self.image.pk])
        self.create_url = reverse('admin_gallery_image_create')

    def upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        output = io.BytesIO()
        Image.new('RGB', (4, 4), '#999999').save(output, 'PNG')
        return SimpleUploadedFile('new-caption-image.png', output.getvalue(), content_type='image/png')

    def test_overlong_edit_preserves_input_without_changing_any_saved_fields(self):
        caption = 'x' * 256
        response = self.client.post(self.edit_url, {
            'category': self.other_category.pk, 'caption': caption,
            'image': self.upload(), 'next': '/staff/gallery/', 'scroll_target': 'gallery-images-section',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Use 255 characters or fewer for the caption.')
        self.assertEqual(response.context['caption_value'], caption)
        self.assertEqual(response.context['selected_category_id'], str(self.other_category.pk))
        self.assertFalse(response.context['form_is_active'])
        self.assertTrue(response.context['upload_needs_reselect'])
        self.assertEqual(response.context['next_url'], '/staff/gallery/')
        self.image.refresh_from_db()
        self.assertEqual(self.image.caption, 'Original caption')
        self.assertEqual(self.image.category_id, self.category.pk)
        self.assertTrue(self.image.is_active)
        self.assertEqual(self.image.image.name, 'gallery/original-caption.png')

    def test_overlong_create_does_not_insert_an_image(self):
        response = self.client.post(self.create_url, {
            'category': self.category.pk, 'caption': 'long ' * 100, 'image': self.upload(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('caption', response.context['errors'])
        self.assertEqual(GalleryImage.objects.count(), 1)
        self.assertContains(response, 'long ' * 99)

    def test_exact_limit_saves_for_both_create_and_edit(self):
        caption = 'é' * 255
        response = self.client.post(self.create_url, {
            'category': self.category.pk, 'caption': caption, 'image': self.upload(),
        })
        self.assertRedirects(response, reverse('admin_gallery'))
        created = GalleryImage.objects.exclude(pk=self.image.pk).get()
        self.assertEqual(created.caption, caption)
        self.assertTrue(created.is_active)
        response = self.client.post(self.edit_url, {
            'category': self.other_category.pk, 'caption': caption, 'is_active': 'on',
        })
        self.assertRedirects(response, reverse('admin_gallery'))
        self.image.refresh_from_db()
        self.assertEqual(self.image.caption, caption)
        self.assertEqual(self.image.category_id, self.other_category.pk)

    def test_caption_remains_optional_and_edit_does_not_require_new_upload(self):
        response = self.client.post(self.edit_url, {'category': self.category.pk, 'caption': ''})
        self.assertRedirects(response, reverse('admin_gallery'))
        self.image.refresh_from_db()
        self.assertEqual(self.image.caption, '')
        self.assertFalse(self.image.is_active)
        self.assertEqual(self.image.image.name, 'gallery/original-caption.png')

    def test_required_field_errors_preserve_caption_and_category(self):
        response = self.client.post(self.create_url, {'category': self.other_category.pk, 'caption': 'Keep this text'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['errors'], {'image': 'Image is required.'})
        self.assertEqual(response.context['caption_value'], 'Keep this text')
        self.assertEqual(response.context['selected_category_id'], str(self.other_category.pk))
        response = self.client.post(self.edit_url, {'caption': 'y' * 256})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.context['errors']), {'category', 'caption'})

    def test_caption_field_exposes_its_limit_and_existing_value(self):
        response = self.client.get(self.edit_url)
        self.assertContains(response, 'maxlength="255"')
        self.assertContains(response, 'Up to 255 characters.')
        self.assertContains(response, 'Original caption</textarea>')
        self.assertContains(response, '<span id="captionCount">16</span>', html=True)
