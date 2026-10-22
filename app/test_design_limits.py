"""Admin allowance, ownership, and authoritative saved-design quota checks."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.db import connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from .design_limits import create_saved_design, DesignLimitReached, saved_design_usage
from .design_validation import asset_payload
from .models import CanvasAsset, CanvasCategory, DesignOffer, DesignRequirement, Package, SiteSettings, User, UserDesign


class DesignLimitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = User.objects.create_user(username='quota_customer', role='customer')
        cls.other = User.objects.create_user(username='quota_other', role='customer')
        cls.admin = User.objects.create_user(username='quota_admin', role='admin')
        cls.site = SiteSettings.load()
        cls.site.max_saved_designs = 2
        cls.site.save()
        category = CanvasCategory.objects.create(name='Quota panels')
        asset = CanvasAsset.objects.create(category=category, label='Quota panel', static_path='images/quota-panel.svg')
        package = Package.objects.create(name='Quota package', price=1000)
        cls.offer = DesignOffer.objects.create(kind='package', package=package, is_enabled=True)
        DesignRequirement.objects.create(offer=cls.offer, category=category, required=True, minimum=1, maximum=1)
        payload = asset_payload(asset)
        cls.complete = json.dumps({'objects': [{
            'type': 'image', 'src': payload['src'], '_assetId': asset.pk, '_assetToken': payload['token'], '_designSource': 'catalog',
        }]})

    def setUp(self):
        self.client.force_login(self.customer)

    def save_new(self, **overrides):
        data = {'name': 'Quota test', 'design_offer_id': self.offer.pk, 'canvas_json': '{"objects": []}'}
        data.update(overrides)
        return self.client.post(reverse('save_user_design'), data, content_type='application/json')

    def design(self, user=None, **overrides):
        fields = {'user': user or self.customer, 'name': 'Saved draft', 'canvas_json': '{"objects": []}', 'design_offer': self.offer}
        fields.update(overrides)
        return UserDesign.objects.create(**fields)

    def test_default_is_twenty_and_admin_can_change_only_design_settings(self):
        self.assertEqual(SiteSettings().max_saved_designs, 20)
        self.client.force_login(self.admin)
        before = SiteSettings.load()
        response = self.client.post(reverse('admin_site_settings'), {'settings_section': 'design', 'max_saved_designs': '30'})
        self.assertRedirects(response, reverse('admin_site_settings') + '#design-settings', fetch_redirect_response=False)
        after = SiteSettings.load()
        self.assertEqual(after.max_saved_designs, 30)
        self.assertEqual(after.updated_by, self.admin)
        for field in ('site_name', 'contact_email', 'address', 'booking_change_cutoff_hours', 'email_notifications_enabled'):
            self.assertEqual(getattr(after, field), getattr(before, field))
        self.client.post(reverse('admin_site_settings'), {'site_name': before.site_name})
        self.assertEqual(SiteSettings.load().max_saved_designs, 30)

    def test_invalid_admin_limit_is_inline_and_does_not_save(self):
        self.client.force_login(self.admin)
        for raw in ('', '0', '-1', '2.5', 'abc', '2147483648'):
            response = self.client.post(reverse('admin_site_settings'), {'settings_section': 'design', 'max_saved_designs': raw})
            self.assertEqual(response.status_code, 400, raw)
            self.assertTrue(response.context['design_settings_form'].errors.get('max_saved_designs'), raw)
            self.assertContains(response, 'ss-field has-error', status_code=400)
            self.assertEqual(SiteSettings.load().max_saved_designs, 2)

    def test_customer_cannot_change_allowance(self):
        self.assertEqual(self.client.get(reverse('admin_site_settings')).status_code, 403)
        self.assertEqual(self.client.post(reverse('admin_site_settings'), {'settings_section': 'design', 'max_saved_designs': '999'}).status_code, 403)
        self.assertEqual(SiteSettings.load().max_saved_designs, 2)

    def test_drafts_and_ready_designs_count_and_direct_save_is_blocked_at_limit(self):
        first = self.save_new()
        second = self.save_new(name='Ready', canvas_json=self.complete)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(first.json()['can_book'])
        self.assertTrue(second.json()['can_book'])
        with patch('app.models.UserDesign.save') as save_model, patch('app.views.designs.log_action') as log:
            blocked = self.save_new(max_saved_designs=999, used=0)
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()['code'], 'design_limit_reached')
        self.assertEqual(blocked.json()['design_usage'], {'used': 2, 'limit': 2, 'at_limit': True, 'remaining': 0})
        self.assertEqual(UserDesign.objects.filter(user=self.customer).count(), 2)
        save_model.assert_not_called()
        log.assert_not_called()

    def test_existing_design_can_be_saved_at_or_above_limit_and_other_owners_cannot(self):
        design = self.design()
        self.design()
        self.design()
        response = self.save_new(id=design.pk, name='Edited', canvas_json=self.complete)
        self.assertEqual(response.status_code, 200)
        design.refresh_from_db()
        self.assertEqual(design.name, 'Edited')
        self.assertEqual(UserDesign.objects.filter(user=self.customer).count(), 3)
        other_design = self.design(user=self.other)
        self.assertEqual(self.save_new(id=other_design.pk, name='Not mine').status_code, 404)

    def test_delete_frees_a_slot_and_other_accounts_have_their_own_quota(self):
        first, second = self.design(), self.design()
        self.assertEqual(self.save_new().status_code, 409)
        response = self.client.post(reverse('delete_user_design', args=[first.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.save_new().status_code, 200)
        self.client.force_login(self.other)
        self.assertEqual(self.save_new().status_code, 200)
        self.assertEqual(UserDesign.objects.filter(user=self.customer).count(), 2)

    def test_usage_counts_all_pages_despite_search_and_disables_only_create(self):
        design = self.design(name='Visible design')
        self.design(name='Hidden by search')
        response = self.client.get(reverse('my_designs'), {'q': 'Visible'})
        self.assertEqual(response.context['design_usage']['used'], 2)
        self.assertContains(response, '<strong>2/2</strong> designs saved')
        self.assertContains(response, 'disabled aria-describedby="designLimitNote"')
        self.assertContains(response, 'You can still edit and save your existing designs.')
        self.assertContains(response, reverse('design_canvas') + f'?id={design.pk}')
        self.assertEqual(len(response.context['designs']), 1)

    def test_lowering_limit_preserves_existing_designs_and_raising_reopens_creation(self):
        self.design()
        self.design()
        SiteSettings.objects.filter(pk=self.site.pk).update(max_saved_designs=1)
        self.assertEqual(saved_design_usage(self.customer)['used'], 2)
        self.assertEqual(self.save_new().status_code, 409)
        SiteSettings.objects.filter(pk=self.site.pk).update(max_saved_designs=3)
        self.assertEqual(self.save_new().status_code, 200)

    def test_direct_new_canvas_and_picker_links_are_blocked_but_existing_can_open(self):
        design = self.design()
        self.design()
        for endpoint in ('design_canvas', 'select_design_type'):
            response = self.client.get(reverse(endpoint), {'design_offer_id': self.offer.pk, 'fresh': 1})
            self.assertRedirects(response, reverse('my_designs'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('design_canvas'), {'id': design.pk}).status_code, 200)
        self.assertEqual(self.client.get(reverse('select_design_type'), {'design_id': design.pk}).status_code, 200)
        foreign = self.design(user=self.other)
        self.assertEqual(self.client.get(reverse('select_design_type'), {'design_id': foreign.pk}).status_code, 404)


class ConcurrentDesignLimitTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_two_simultaneous_creates_cannot_take_the_last_slot(self):
        customer = User.objects.create_user(username='concurrent_quota_customer', role='customer')
        site = SiteSettings.load()
        site.max_saved_designs = 1
        site.save()
        barrier = Barrier(2)

        def create():
            try:
                user = User.objects.get(pk=customer.pk)
                barrier.wait(timeout=10)
                create_saved_design(user=user, name='Last slot', canvas_json='{"objects": []}')
                return 'created'
            except DesignLimitReached:
                return 'blocked'
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: create(), range(2)))
        self.assertCountEqual(results, ['created', 'blocked'])
        self.assertEqual(UserDesign.objects.filter(user=customer).count(), 1)
