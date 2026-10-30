"""Gallery package assignments, public visibility, and admin validation."""
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse

from .catalog_forms import GalleryImageForm
from .models import GalleryCategory, GalleryImage, Package, User
from .test_admin_catalog import upload


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class GalleryPackageTests(TestCase):
    def setUp(self):
        media = tempfile.TemporaryDirectory(prefix='gallery-package-tests-')
        self.addCleanup(media.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=media.name))
        self.admin = User.objects.create_user(username='gallery-package-admin', role='admin', email_verified=True)
        self.customer = User.objects.create_user(username='gallery-package-customer', role='customer')
        self.birthday = GalleryCategory.objects.create(name='Birthday')
        self.baptism = GalleryCategory.objects.create(name='Baptism')
        self.one = Package.objects.create(name='Package 1', price=4000)
        self.two = Package.objects.create(name='Package 2', price=6000)
        self.unused = Package.objects.create(name='Package 3', price=8000)
        self.inactive = Package.objects.create(name='Private inactive package', price=8000, is_active=False)
        self.photo = GalleryImage.objects.create(category=self.birthday, package=self.one, image=upload('birthday-one.png'), caption='Birthday one')
        GalleryImage.objects.create(category=self.birthday, package=self.two, image=upload('birthday-two.png'), caption='Birthday two')
        GalleryImage.objects.create(category=self.baptism, package=self.one, image=upload('baptism-one.png'), caption='Baptism one')
        self.legacy = GalleryImage.objects.create(category=self.birthday, image=upload('legacy.png'), caption='Legacy photo')
        GalleryImage.objects.create(category=self.birthday, package=self.unused, image=upload('hidden.png'), caption='Hidden photo', is_active=False)
        self.client.force_login(self.admin)

    def action(self, action='create', pk=0):
        return reverse('admin_catalog_action', args=['gallery-image', action, pk])

    def test_public_gallery_shows_used_active_packages_and_preserves_unassigned_photos(self):
        GalleryImage.objects.create(category=self.birthday, package=self.inactive, image=upload('inactive.png'), caption='Past setup')
        response = self.client.get(reverse('gallery'))
        self.assertEqual([package.pk for package in response.context['gallery_packages']], [self.one.pk, self.two.pk])
        self.assertEqual(len(response.context['gallery_images']), 5)
        self.assertContains(response, 'Legacy photo')
        self.assertContains(response, 'Past setup')
        self.assertNotContains(response, 'Private inactive package')
        self.assertNotContains(response, 'Hidden photo')
        self.assertNotContains(response, '>Package 3</button>')
        self.assertContains(response, 'id="lightboxPackage"')

    def test_batch_upload_assigns_category_and_package_to_every_photo(self):
        response = self.client.post(self.action(), {'category':self.birthday.pk, 'package':self.one.pk,
            'caption':'New birthday batch', 'is_active':'on', 'images':[upload('first.png'),upload('second.png')]})
        self.assertEqual(response.status_code, 200, response.content)
        photos = GalleryImage.objects.filter(caption='New birthday batch')
        self.assertEqual(photos.count(), 2)
        self.assertEqual(set(photos.values_list('category_id','package_id')), {(self.birthday.pk,self.one.pk)})

    def test_invalid_or_inactive_package_cannot_create_photos(self):
        original = GalleryImage.objects.count()
        for value in ('invalid', '9'*150, '99999999', str(self.inactive.pk)):
            response = self.client.post(self.action(), {'category':self.birthday.pk, 'package':value,
                'caption':'Must not save', 'is_active':'on', 'images':[upload()]})
            self.assertEqual(response.status_code, 400)
            self.assertIn('package', response.json()['errors'])
        self.assertEqual(GalleryImage.objects.count(), original)

    def test_edit_can_assign_change_or_clear_package_without_reuploading(self):
        image_name = self.legacy.image.name
        for package in (str(self.one.pk), str(self.two.pk), ''):
            response = self.client.post(self.action('edit', self.legacy.pk), {'category':self.birthday.pk,
                'package':package, 'caption':'Updated legacy', 'is_active':'on'})
            self.assertEqual(response.status_code, 200, response.content)
            self.legacy.refresh_from_db()
            self.assertEqual(self.legacy.package_id, int(package) if package else None)
            self.assertEqual(self.legacy.image.name, image_name)

    def test_admin_package_filters_combine_with_category_and_search(self):
        url = reverse('admin_gallery')
        response = self.client.get(url, {'category':self.birthday.pk,'package':self.one.pk})
        self.assertEqual([row['pk'] for row in response.context['rows']], [self.photo.pk])
        self.assertIn(('Package', self.one.name), response.context['rows'][0]['values'])
        response = self.client.get(url, {'package':'unassigned'})
        self.assertEqual([row['pk'] for row in response.context['rows']], [self.legacy.pk])
        response = self.client.get(url, {'q':'Package 2'})
        self.assertEqual(len(response.context['rows']), 1)
        self.assertEqual(response.context['rows'][0]['name'], 'Birthday two')
        for value in ('invalid','9'*150):
            self.assertEqual(self.client.get(url, {'package':value}).status_code, 200)

    def test_deleting_or_deactivating_package_preserves_gallery_photos(self):
        self.one.is_active = False
        self.one.save(update_fields=['is_active'])
        form = GalleryImageForm(instance=self.photo)
        self.assertIn(self.one, list(form.fields['package'].queryset))
        self.assertNotIn(self.one, list(GalleryImageForm().fields['package'].queryset))
        self.assertEqual(form.fields['package'].label_from_instance(self.one), 'Package 1 (inactive)')
        self.one.delete()
        self.photo.refresh_from_db()
        self.assertIsNone(self.photo.package_id)
        self.assertTrue(self.photo.image)
        self.assertEqual(GalleryImage.objects.count(), 5)

    def test_legacy_forms_share_package_validation_and_preserve_missing_assignment(self):
        url = reverse('admin_gallery_image_edit', args=[self.photo.pk])
        response = self.client.post(url, {'category':self.birthday.pk,'caption':'Kept assignment','is_active':'on'})
        self.assertEqual(response.status_code, 302)
        self.photo.refresh_from_db()
        self.assertEqual(self.photo.package_id, self.one.pk)
        response = self.client.post(url, {'category':self.birthday.pk,'package':self.two.pk,'caption':'Changed assignment','is_active':'on'})
        self.assertEqual(response.status_code, 302)
        self.photo.refresh_from_db()
        self.assertEqual(self.photo.package_id, self.two.pk)
        response = self.client.post(url, {'category':self.birthday.pk,'package':'bad','caption':'Must not overwrite'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('package', response.context['errors'])
        self.photo.refresh_from_db()
        self.assertEqual(self.photo.caption, 'Changed assignment')

    def test_gallery_package_writes_still_require_admin_and_csrf(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.action('edit',self.photo.pk), {'package':self.two.pk}).status_code,403)
        self.client.force_login(self.customer)
        self.assertEqual(self.client.post(self.action('edit',self.photo.pk), {'package':self.two.pk}).status_code,403)
