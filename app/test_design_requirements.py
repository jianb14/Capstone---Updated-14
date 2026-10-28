import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from .design_validation import asset_payload, evaluate_design, offer_is_ready, restore_catalog_metadata
from .models import (AddOn, AdditionalOnly, Booking, CanvasAsset, CanvasCategory,
                     DesignOffer, DesignRequirement, Package, ServiceChargeConfig, User, UserDesign)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class DesignRequirementsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='designer', role='customer')
        cls.admin = User.objects.create_user(username='designer_admin', role='admin')
        cls.panels, _ = CanvasCategory.objects.get_or_create(name='Panels')
        cls.balloons = CanvasCategory.objects.create(name='Shared balloon decor', available_entrance=True, available_stand=True, is_balloon=True)
        cls.panel = CanvasAsset.objects.create(category=cls.panels, label='Official panel', static_path='images/test-panel.svg')
        cls.balloon = CanvasAsset.objects.create(category=cls.balloons, label='Shared balloon asset', static_path='images/test-balloon.svg', available_entrance=True, available_stand=True)
        cls.package = Package.objects.create(name='Test package', features='Description only', price='5000')
        cls.offer = DesignOffer.objects.create(kind='package', package=cls.package, is_enabled=True)
        DesignRequirement.objects.create(offer=cls.offer, category=cls.panels, required=True, minimum=2, maximum=2)
        DesignRequirement.objects.create(offer=cls.offer, category=cls.balloons, required=True, minimum=1)
        cls.entrance = AddOn.objects.create(name='Test entrance', features='Entrance description', price='1500', solo_price='2500')
        cls.entrance_offer = DesignOffer.objects.create(kind='entrance', entrance=cls.entrance, is_enabled=True)
        DesignRequirement.objects.create(offer=cls.entrance_offer, category=cls.balloons, required=True, minimum=1)
        cls.stand = AdditionalOnly.objects.create(name='Test stand', features='Stand description', price='1200')
        cls.stand_offer = DesignOffer.objects.create(kind='stand', stand=cls.stand, is_enabled=True)
        DesignRequirement.objects.create(offer=cls.stand_offer, category=cls.balloons, required=True, minimum=1)

    def setUp(self):
        self.client.force_login(self.user)

    def obj(self, asset, **overrides):
        p = asset_payload(asset)
        obj = {'type': 'image', 'src': p['src'], '_assetId': asset.pk, '_assetToken': p['token'],
               '_assetSource': p['src'], '_categoryId': asset.category_id, '_designSource': 'catalog'}
        obj.update(overrides)
        return obj

    def canvas(self, *objects):
        return json.dumps({'version': '5.3.1', 'objects': list(objects)})

    def complete(self):
        return self.canvas(self.obj(self.panel), self.obj(self.panel), self.obj(self.balloon))

    def design(self, canvas=None, offer=None, **kwargs):
        return UserDesign.objects.create(user=self.user, canvas_json=canvas or self.complete(), design_offer=offer or self.offer, **kwargs)

    def rule_payload(self, **overrides):
        data = {'name': self.package.name, 'price': '5000', 'features': 'Description only',
                'design_rules_present': '1', 'design_enabled': 'on',
                f'rule_{self.panels.pk}_included': 'on', f'rule_{self.panels.pk}_required': 'on',
                f'rule_{self.panels.pk}_minimum': '2', f'rule_{self.panels.pk}_maximum': '2'}
        data.update(overrides)
        return data

    def booking_payload(self, design):
        return {'user_design_id': design.pk, 'package_type': 'Tampered offer', 'total_price': '1',
                'event_type': 'Birthday', 'event_date': '2030-01-15', 'start_time': '09:00', 'end_time': '11:00',
                'event_location': 'Test Venue in Cavite', 'map_available': '0',
                'design_theme': 'Garden', 'color_palette': 'Green, White'}

    def test_panel_only_is_draft_and_complete_quantities_are_bookable(self):
        partial = evaluate_design(self.canvas(self.obj(self.panel)), self.offer)
        self.assertFalse(partial['can_book'])
        self.assertEqual([r['missing'] for r in partial['missing_requirements']], [1, 1])
        self.assertTrue(evaluate_design(self.complete(), self.offer)['can_book'])

    def test_reference_cannot_supply_required_elements_even_with_catalog_metadata(self):
        state = self.canvas(self.obj(self.panel), self.obj(self.panel), self.obj(self.balloon, _designSource='reference'))
        result = evaluate_design(state, self.offer)
        self.assertFalse(result['can_book'])
        self.assertEqual(result['missing_requirements'][0]['category_id'], self.balloons.pk)

    def test_category_label_and_id_cannot_reclassify_an_asset(self):
        result = evaluate_design(self.canvas(self.obj(self.balloon, _categoryId=self.panels.pk, _packageCategory='panels')), self.offer)
        self.assertEqual(result['counts'].get(self.panels.pk, 0), 0)
        self.assertEqual(result['counts'][self.balloons.pk], 1)

    def test_invalid_token_or_uploaded_pixels_cannot_be_catalog_assets(self):
        for changes in ({'_assetToken': 'fake'}, {'src': 'data:image/png;base64,abc'}):
            result = evaluate_design(self.canvas(self.obj(self.panel, **changes)), self.offer)
            self.assertEqual(result['counts'].get(self.panels.pk, 0), 0)
            self.assertTrue(result['invalid_items'])

    def test_maximum_is_checked_on_server(self):
        result = evaluate_design(self.canvas(*[self.obj(self.panel)] * 3, self.obj(self.balloon)), self.offer)
        self.assertFalse(result['can_book'])
        self.assertTrue(result['rows'][0]['over_limit'])

    def test_optional_categories_do_not_block_booking(self):
        rule = self.offer.requirements.get(category=self.balloons)
        rule.required, rule.minimum, rule.maximum = False, 0, 1
        rule.save()
        self.assertTrue(evaluate_design(self.canvas(self.obj(self.panel), self.obj(self.panel)), self.offer)['can_book'])

    def test_shared_asset_is_counted_for_all_three_types_without_copying(self):
        for offer in (self.entrance_offer, self.stand_offer):
            self.assertTrue(evaluate_design(self.canvas(self.obj(self.balloon)), offer)['can_book'])
        self.assertEqual(CanvasAsset.objects.filter(label='Shared balloon asset').count(), 1)

    def test_wrong_type_and_unconfigured_category_cannot_count(self):
        result = evaluate_design(self.canvas(self.obj(self.panel), self.obj(self.balloon)), self.entrance_offer)
        self.assertFalse(result['can_book'])
        self.assertTrue(result['invalid_items'])

    def test_svg_group_counts_once_not_per_path(self):
        obj = self.obj(self.panel, type='group', objects=[{'type': 'path'}] * 20, _isColorableSVG=True)
        result = evaluate_design(self.canvas(obj), self.offer)
        self.assertEqual(result['counts'][self.panels.pk], 1)

    def test_single_path_svg_is_one_catalog_placement(self):
        obj = self.obj(self.panel, type='path', _isColorableSVG=True)
        self.assertEqual(evaluate_design(self.canvas(obj), self.offer)['counts'][self.panels.pk], 1)

    def test_hidden_assets_and_empty_text_do_not_fulfill_requirements(self):
        result = evaluate_design(self.canvas(self.obj(self.panel, visible=False)), self.offer)
        self.assertEqual(result['counts'].get(self.panels.pk, 0), 0)
        category = CanvasCategory.objects.get(name='Styrofoam Name')
        text = CanvasAsset.objects.get(category=category, item_type='i-text')
        DesignRequirement.objects.create(offer=self.offer, category=category, required=True, minimum=1)
        state = self.canvas(self.obj(text, type='i-text', text=''))
        self.assertEqual(evaluate_design(state, self.offer)['counts'].get(category.pk, 0), 0)

    def test_legacy_unique_image_is_restored_but_category_alone_is_not(self):
        state = restore_catalog_metadata(self.canvas({'type': 'image', 'src': asset_payload(self.panel)['src']}), self.offer)
        self.assertEqual(state['objects'][0]['_assetId'], self.panel.pk)
        state = restore_catalog_metadata(self.canvas({'type': 'group', '_packageCategory': 'panels'}), self.offer)
        self.assertNotIn('_assetId', state['objects'][0])

    def test_save_keeps_incomplete_design_and_returns_evaluation(self):
        response = self.client.post(reverse('save_user_design'), {'canvas_json': self.canvas(self.obj(self.panel)), 'design_offer_id': self.offer.pk}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['can_book'])
        self.assertEqual(UserDesign.objects.get(pk=response.json()['id']).design_offer_id, self.offer.pk)

    def test_package_id_save_alias_is_preserved(self):
        response = self.client.post(reverse('save_user_design'), {'canvas_json': self.complete(), 'base_package_id': self.package.pk}, content_type='application/json')
        self.assertTrue(response.json()['can_book'])

    def test_customer_pages_render_typed_offers_and_canvas_identity(self):
        response = self.client.get(reverse('select_design_type'))
        for text in ('Package', 'Entrance Arch', 'Welcome Stand', self.entrance.name, 'Required before booking'):
            self.assertContains(response, text)
        response = self.client.get(reverse('design_canvas'), {'design_offer_id': self.entrance_offer.pk})
        self.assertContains(response, 'Reference photos do not count toward required items.')
        self.assertEqual(response.context['design_offer_payload']['price'], '2500.00')
        assets = response.context['canvas_assets_payload_obj']
        self.assertEqual(next(iter(assets.values()))[0]['id'], self.balloon.pk)

    def test_my_designs_shows_draft_without_booking_link(self):
        design = self.design(self.canvas(self.obj(self.panel)))
        response = self.client.get(reverse('my_designs'))
        self.assertContains(response, 'Draft')
        self.assertContains(response, 'Continue Editing')
        self.assertNotContains(response, f'?design_id={design.pk}"')

    def test_incomplete_direct_booking_url_returns_to_editor(self):
        design = self.design(self.canvas(self.obj(self.panel)))
        response = self.client.get(reverse('booking_page'), {'design_id': design.pk})
        self.assertRedirects(response, reverse('design_canvas') + f'?id={design.pk}', fetch_redirect_response=False)

    def test_incomplete_post_creates_no_booking(self):
        design = self.design(self.canvas(self.obj(self.panel)))
        response = self.client.post(reverse('create_booking'), self.booking_payload(design), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Booking.objects.exists())

    def test_foreign_design_url_and_post_are_rejected(self):
        design = self.design()
        other = User.objects.create_user(username='another_designer', role='customer')
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse('booking_page'), {'design_id': design.pk}).status_code, 404)
        self.assertEqual(self.client.post(reverse('create_booking'), self.booking_payload(design), HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 404)
        self.assertFalse(Booking.objects.exists())

    @patch('app.views.bookings.send_admin_alert_email')
    def test_entrance_booking_uses_solo_price_and_trusted_name(self, alert):
        ServiceChargeConfig.objects.update_or_create(pk=1, defaults={'amount': Decimal('100')})
        design = self.design(self.canvas(self.obj(self.balloon)), self.entrance_offer)
        response = self.client.post(reverse('create_booking'), self.booking_payload(design), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'], response.content)
        booking = Booking.objects.get()
        self.assertEqual(booking.package_type, 'Test entrance (Solo)')
        self.assertEqual(booking.total_price, Decimal('2600'))

    def test_revalidation_blocks_design_after_rules_change(self):
        design = self.design()
        self.offer.requirements.filter(category=self.balloons).update(minimum=2)
        response = self.client.post(reverse('create_booking'), self.booking_payload(design), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Booking.objects.exists())

    def test_missing_solo_price_or_missing_assets_disables_offer(self):
        self.entrance.solo_price = None
        self.entrance.save()
        self.assertFalse(offer_is_ready(self.entrance_offer))
        self.panel.is_active = False
        self.panel.save()
        self.assertFalse(offer_is_ready(self.offer))

    def test_admin_edit_forms_render_requirements_for_each_type(self):
        self.client.force_login(self.admin)
        for name, item in [('package', self.package), ('addon', self.entrance), ('additional', self.stand)]:
            self.assertContains(self.client.get(reverse('admin_' + name + '_edit', args=[item.pk])), 'Inclusions')

    def test_admin_can_save_rules_and_invalid_minimum_does_not_update_catalog(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin_package_edit', args=[self.package.pk]), self.rule_payload())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.offer.requirements.count(), 1)
        response = self.client.post(reverse('admin_package_edit', args=[self.package.pk]), self.rule_payload(**{'name': 'Should not save', f'rule_{self.panels.pk}_minimum': '3'}))
        self.assertContains(response, 'minimum cannot exceed maximum')
        self.package.refresh_from_db()
        self.assertEqual(self.package.name, 'Test package')

    def test_admin_cannot_enable_without_required_categories(self):
        self.client.force_login(self.admin)
        data = self.rule_payload()
        data.pop(f'rule_{self.panels.pk}_required')
        data[f'rule_{self.panels.pk}_minimum'] = '0'
        response = self.client.post(reverse('admin_package_edit', args=[self.package.pk]), data)
        self.assertContains(response, 'Select at least one required category')

    def test_admin_tabs_filter_both_categories_and_assets(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_canvas_assets'), {'kind': 'entrance'})
        self.assertContains(response, 'Shared balloon asset')
        self.assertNotContains(response, 'Official panel')
        self.assertNotIn(self.panels, response.context['categories'])
        self.assertContains(response, 'name="kind"')
        self.assertEqual(response.context['selected_kind'], 'entrance')

    def test_asset_cannot_be_shared_outside_category_types(self):
        self.client.force_login(self.admin)
        data = {'category': self.panels.pk, 'label': self.panel.label, 'width': 150, 'height': 150, 'is_active': 'on',
                'availability_present': '1', 'available_for': ['package', 'entrance'], 'kind': 'package'}
        response = self.client.post(reverse('admin_canvas_asset_edit', args=[self.panel.pk]), data)
        self.assertContains(response, 'Choose a category available in every selected design type')
        self.panel.refresh_from_db()
        self.assertFalse(self.panel.available_entrance)

    def test_category_can_be_shared_without_copying_assets(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin_canvas_category_edit', args=[self.panels.pk]), {
            'name': 'Panels', 'order': 1, 'is_active': 'on', 'availability_present': '1', 'available_for': ['package', 'entrance'], 'kind': 'entrance'})
        self.assertEqual(response.status_code, 302)
        self.panels.refresh_from_db()
        self.assertTrue(self.panels.available_entrance)
        self.assertEqual(CanvasAsset.objects.filter(label=self.panel.label).count(), 1)

    def test_new_catalog_offer_creates_configuration_in_same_submission(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin_package_create'), self.rule_payload(name='New configured offer'))
        self.assertEqual(response.status_code, 302)
        offer = DesignOffer.objects.get(package__name='New configured offer')
        self.assertTrue(offer_is_ready(offer))
        self.assertEqual(offer.requirements.get().minimum, 2)

    def test_unavailable_required_assets_prevent_admin_enabling_offer(self):
        self.client.force_login(self.admin)
        self.panel.is_active = False
        self.panel.save()
        response = self.client.post(reverse('admin_package_edit', args=[self.package.pk]), self.rule_payload())
        self.assertContains(response, 'add an active asset')

    def test_category_in_use_is_not_deleted(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_canvas_category_delete', args=[self.panels.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(CanvasCategory.objects.filter(pk=self.panels.pk).exists())

    def test_evaluation_endpoint_and_save_have_same_result(self):
        payload = {'canvas_json': self.complete(), 'design_offer_id': self.offer.pk}
        evaluation = self.client.post(reverse('evaluate_user_design'), payload, content_type='application/json').json()
        saved = self.client.post(reverse('save_user_design'), payload, content_type='application/json').json()
        self.assertEqual(evaluation, saved['evaluation'])

    def test_color_limit_is_an_explicit_server_rule(self):
        self.offer.max_balloon_colors = 1
        self.offer.save()
        state = self.canvas(self.obj(self.panel), self.obj(self.panel), self.obj(self.balloon, _currentColor='#ff0000'), self.obj(self.balloon, _currentColor='#0000ff'))
        result = evaluate_design(state, self.offer)
        self.assertFalse(result['can_book'])
        self.assertIn('no more than 1 balloon colors', result['invalid_items'][0])

    def test_invalid_canvas_structure_is_rejected_without_creating_design(self):
        response = self.client.post(reverse('save_user_design'), {'canvas_json': '{bad json'}, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserDesign.objects.exists())
