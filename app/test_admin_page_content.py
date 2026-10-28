"""Content CRUD, filtering and notification regressions on the shared workspace."""
import io
from unittest.mock import patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import (AboutContent, AboutJourneyItem, AboutValueItem, GuidelineItem,
    GuidelinePageContent, HomeContent, HomeFaqItem, HomeFeatureItem, HomeHowItWorksStep,
    Service, ServiceContent, User)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AdminPageContentTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='page-editor', role='admin', email_verified=True)
        self.customer = User.objects.create_user(username='page-customer', role='customer', email='customer@example.com')
        self.client.force_login(self.admin)
        self.home = HomeContent.objects.first() or HomeContent.objects.create(hero_title='Welcome')
        self.about = AboutContent.objects.first() or AboutContent.objects.create(hero_title='About')
        self.service = ServiceContent.objects.first() or ServiceContent.objects.create(hero_title='Services')
        self.policy, _ = GuidelinePageContent.objects.get_or_create(page_key='terms', defaults={'title': 'Terms'})
        self.feature = HomeFeatureItem.objects.create(home_content=self.home, title='Feature fixture', display_order=1)

    def url(self, workspace, resource, action, pk=0):
        return reverse('admin_content_action', args=(workspace, resource, action, pk))

    def ajax(self, url, data=None):
        kwargs = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        return self.client.get(url, **kwargs) if data is None else self.client.post(url, data, **kwargs)

    def test_all_pages_and_modal_sections_render_with_shared_controls(self):
        from .content_admin import SECTIONS
        for workspace, name, instance in (
            ('home', 'admin_home_content', self.home), ('about', 'admin_about_content', self.about),
            ('services', 'admin_service_content', self.service), ('policies', 'admin_guidelines_content', self.policy)):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'admin_page_content.css')
            self.assertContains(response, 'data-catalog-dialog')
            for section in SECTIONS[workspace]:
                modal = self.ajax(self.url(workspace, section, 'section', instance.pk))
                self.assertEqual(modal.status_code, 200, modal.content)
                self.assertIn('data-catalog-form', modal.json()['html'])
                self.assertIn('form="catalogEditorForm"', modal.json()['footer_html'])

    def test_section_save_preserves_other_sections_and_automatic_statistics(self):
        before_hours = self.home.support_hours
        response = self.ajax(self.url('home', 'hero', 'section', self.home.pk), {
            'hero_title': 'Changed welcome', 'hero_label': 'Hello', 'stat_rating': '999', 'support_hours': '2'})
        self.assertEqual(response.status_code, 200)
        self.home.refresh_from_db()
        self.assertEqual(self.home.hero_title, 'Changed welcome')
        self.assertEqual(self.home.support_hours, before_hours)
        self.assertNotEqual(self.home.stat_rating, '999')

    def test_invalid_section_and_bounds_do_not_write(self):
        url = self.url('home', 'support', 'section', self.home.pk)
        for value in ('', '0', '25', '-1', 'abc', '11.5'):
            response = self.ajax(url, {'support_hours': value})
            self.assertEqual(response.status_code, 400)
            self.assertIn('support_hours', response.json()['errors'])
        self.assertEqual(self.ajax(url, {'support_hours': 9}).status_code, 200)
        self.home.refresh_from_db()
        self.assertEqual(self.home.support_hours, 9)
        response = self.ajax(self.url('home', 'hero', 'section', self.home.pk), {'hero_title': 'x' * 256})
        self.assertEqual(response.status_code, 400)
        self.assertIn('hero_title', response.json()['errors'])

    def test_every_collection_create_detail_edit_delete_and_no_reseed(self):
        from .content_admin import COLLECTIONS
        for workspace, resources in COLLECTIONS.items():
            for resource, (model, _, _, fields, _) in resources.items():
                data = {'title': 'Test item', 'question': 'Test question?', 'heading': 'Test heading',
                    'description': 'A description', 'answer': 'An answer', 'body': 'Policy details',
                    'icon_class': 'fas fa-star', 'display_order': 2, 'is_active': 'on'}
                response = self.ajax(self.url(workspace, resource, 'create'), data)
                self.assertEqual(response.status_code, 200, response.content)
                item = model.objects.latest('pk')
                self.assertEqual(self.ajax(self.url(workspace, resource, 'detail', item.pk)).status_code, 200)
                data['display_order'] = 3
                self.assertEqual(self.ajax(self.url(workspace, resource, 'edit', item.pk), data).status_code, 200)
                item.refresh_from_db()
                self.assertEqual(item.display_order, 3)
                self.assertEqual(self.ajax(self.url(workspace, resource, 'delete', item.pk)).status_code, 405)
                self.assertTrue(model.objects.filter(pk=item.pk).exists())
                self.assertEqual(self.ajax(self.url(workspace, resource, 'delete', item.pk), {}).status_code, 200)
                self.assertFalse(model.objects.filter(pk=item.pk).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_search_visibility_pagination_and_stable_display_order(self):
        HomeFeatureItem.objects.filter(home_content=self.home).delete()
        for index in range(11):
            HomeFeatureItem.objects.create(home_content=self.home, title=f'Searchable {index:02}', display_order=index, is_active=index != 10)
        url = reverse('admin_home_content')
        response = self.ajax(url)
        self.assertEqual(len(response.context['rows']) if response.context else response.json()['html'].count('data-catalog-row='), 8)
        self.assertEqual(self.ajax(url + '?page=2').json()['html'].count('data-catalog-row='), 3)
        self.assertEqual(self.ajax(url + '?per_page=4').json()['html'].count('data-catalog-row='), 4)
        html = self.ajax(url + '?q=not-found').json()['html']
        self.assertIn('No matching features', html)
        self.assertNotIn('<thead>', html)
        self.assertEqual(self.ajax(url + '?status=hidden').json()['html'].count('data-catalog-row='), 1)
        ids = list(HomeFeatureItem.objects.filter(home_content=self.home).values_list('pk', flat=True))
        response = self.ajax(self.url('home', 'features', 'bulk-delete'), {'ids': ids})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.ajax(url).json()['html'].count('data-catalog-row='), 0)
        self.client.get(url)
        self.assertFalse(HomeFeatureItem.objects.filter(home_content=self.home).exists())

    def test_bulk_delete_rejects_stale_and_cross_policy_selection_atomically(self):
        url = self.url('home', 'features', 'bulk-delete')
        for ids in ([self.feature.pk, 999999], [self.feature.pk, self.feature.pk], ['invalid'], []):
            self.assertIn(self.ajax(url, {'ids': ids}).status_code, (400, 409))
            self.assertTrue(HomeFeatureItem.objects.filter(pk=self.feature.pk).exists())
        privacy, _ = GuidelinePageContent.objects.get_or_create(page_key='privacy')
        item = GuidelineItem.objects.create(page_content=privacy, heading='Private', body='Details')
        response = self.ajax(self.url('policies', 'terms', 'bulk-delete'), {'ids': [item.pk]})
        self.assertEqual(response.status_code, 409)
        self.assertTrue(GuidelineItem.objects.filter(pk=item.pk).exists())

    def test_invalid_items_and_uploads_keep_existing_content(self):
        url = self.url('home', 'features', 'edit', self.feature.pk)
        for data in ({'title': ''}, {'title': 'Valid', 'display_order': -1}, {'title': 'Valid', 'display_order': 2147483648}, {'title': 'Valid', 'display_order': 1, 'icon_class': 'bad-icon'}):
            self.assertEqual(self.ajax(url, data).status_code, 400)
        self.feature.refresh_from_db()
        self.assertEqual(self.feature.title, 'Feature fixture')
        response = self.ajax(self.url('services', 'services', 'create'), {'title': 'Invalid image', 'description': 'Details', 'display_order': 0,
            'image': SimpleUploadedFile('bad.png', b'not an image', content_type='image/png')})
        self.assertEqual(response.status_code, 400)
        self.assertIn('image', response.json()['errors'])
        self.assertFalse(Service.objects.filter(title='Invalid image').exists())

    def test_story_upload_and_remove_photo(self):
        stream = io.BytesIO()
        Image.new('RGB', (4, 4), '#aaa').save(stream, 'PNG')
        url = self.url('about', 'story', 'section', self.about.pk)
        response = self.ajax(url, {'story_title': 'Story', 'story_image': SimpleUploadedFile('story.png', stream.getvalue(), content_type='image/png')})
        self.assertEqual(response.status_code, 200, response.content)
        self.about.refresh_from_db()
        self.assertTrue(self.about.story_image)
        response = self.ajax(url, {'story_title': 'Story', 'remove_story_image': 'on'})
        self.assertEqual(response.status_code, 200, response.content)
        self.about.refresh_from_db()
        self.assertFalse(self.about.story_image)

    def test_policy_notices_require_opt_in_and_actual_changes(self):
        url = self.url('policies', 'page', 'section', self.policy.pk)
        self.assertEqual(self.ajax(url, {'title': 'Updated terms'}).status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.ajax(url, {'title': 'Updated terms', 'notify_clients': 'on'}).status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        response = self.ajax(url, {'title': 'New terms', 'notify_clients': 'on'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['customer@example.com'])
        self.assertIn(reverse('terms_conditions'), mail.outbox[0].body)
        with patch('app.views.admin.send_mail', side_effect=RuntimeError('Mail unavailable')):
            response = self.ajax(url, {'title': 'Saved despite mail failure', 'notify_clients': 'on'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('could not be sent', response.json()['message'])
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.title, 'Saved despite mail failure')

    def test_policy_url_validation_and_explicit_delete_notice(self):
        response = self.ajax(self.url('policies', 'page', 'section', self.policy.pk), {'title': 'Terms', 'attachment_url': 'javascript:alert(1)'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('attachment_url', response.json()['errors'])
        item = GuidelineItem.objects.create(page_content=self.policy, body='Terms details')
        response = self.ajax(self.url('policies', 'terms', 'delete', item.pk), {'notify_clients': 'on'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_customer_access_csrf_and_unknown_resources(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse('admin_home_content')).status_code, 403)
        self.assertEqual(self.ajax(self.url('home', 'features', 'create'), {}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.ajax(self.url('home', 'features', 'bogus')).status_code, 404)
        from django.test import Client
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(csrf_client.post(self.url('home', 'features', 'delete', self.feature.pk)).status_code, 403)

    def test_legacy_delete_routes_cannot_delete_on_get(self):
        url = reverse('admin_home_feature_delete', args=(self.feature.pk,))
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(HomeFeatureItem.objects.filter(pk=self.feature.pk).exists())

    def test_legacy_content_items_remain_manageable(self):
        older = HomeContent.objects.create(hero_title='Another saved page')
        item = HomeFeatureItem.objects.create(home_content=older, title='Legacy feature', display_order=0)
        response = self.ajax(reverse('admin_home_content') + '?q=Legacy')
        self.assertIn('Legacy feature', response.json()['html'])
        self.assertEqual(self.ajax(self.url('home', 'features', 'edit', item.pk)).status_code, 200)

    def test_public_visits_do_not_restore_deleted_collections(self):
        AboutValueItem.objects.all().delete()
        Service.objects.all().delete()
        self.assertEqual(self.client.get(reverse('about')).status_code, 200)
        self.assertEqual(self.client.get(reverse('services')).status_code, 200)
        self.assertFalse(AboutValueItem.objects.exists())
        self.assertFalse(Service.objects.exists())
