import importlib
import io
import json
from decimal import Decimal

from PIL import Image
from django.apps import apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .design_validation import asset_payload, evaluate_design, offer_is_ready
from .models import (User, Package, AddOn, AdditionalOnly, CanvasCategory, CanvasAsset,
                     DesignOffer, DesignRequirement, OfferInclusion)
from .offer_inclusions import import_rows


def image_upload(name='preview.png'):
    content = io.BytesIO()
    Image.new('RGB', (20, 20), 'gray').save(content, 'PNG')
    return SimpleUploadedFile(name, content.getvalue(), content_type='image/png')


class OfferEditorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username='offer_editor_admin', role='admin')
        cls.category = CanvasCategory.objects.create(name='Offer panels', available_entrance=True, available_stand=True)
        cls.balloon_category = CanvasCategory.objects.create(name='Offer balloon decor', is_balloon=True, available_entrance=True, available_stand=True)
        cls.asset = CanvasAsset.objects.create(category=cls.category, label='Panel', static_path='images/panel.svg', available_entrance=True, available_stand=True)
        CanvasAsset.objects.create(category=cls.balloon_category, label='Balloon', static_path='images/balloon.svg', available_entrance=True, available_stand=True)

    def setUp(self):
        self.client.force_login(self.admin)

    def rows(self):
        return [
            {'row_type': 'item', 'name': 'Panels', 'quantity': 2, 'category_id': self.category.pk, 'required_minimum': 2},
            {'row_type': 'item', 'name': 'Balloon decor', 'quantity': None, 'category_id': self.balloon_category.pk, 'required_minimum': 1},
            {'row_type': 'service', 'name': 'Setup and delivery', 'quantity': None, 'category_id': None, 'required_minimum': 0},
        ]

    def payload(self, rows=None, **overrides):
        data = {'name': 'Complete offer', 'price': '5000', 'solo_price': '7500', 'description': 'A celebration setup',
                'notes': 'Delivery details', 'design_enabled': 'on', 'design_max_colors': '3', 'inclusions': json.dumps(self.rows() if rows is None else rows)}
        data.update(overrides)
        return data

    def create(self, kind='package', **overrides):
        endpoint = {'package': 'package', 'entrance': 'addon', 'stand': 'additional'}[kind]
        response = self.client.post(reverse('admin_' + endpoint + '_create'), self.payload(**overrides), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['success'])
        return DesignOffer.objects.filter(kind=kind).latest('pk')

    def test_all_types_create_with_one_authoritative_inclusion_list(self):
        for kind in ('package', 'entrance', 'stand'):
            offer = self.create(kind)
            self.assertEqual(offer.inclusions.count(), 3)
            self.assertEqual(offer.requirements.count(), 2)
            self.assertEqual(offer.item.feature_list(), ['2 Panels', 'Balloon decor (max 3 colors)', 'Setup and delivery'])
            self.assertTrue(offer_is_ready(offer))
            self.assertEqual(offer.price, Decimal('7500') if kind == 'entrance' else Decimal('5000'))

    def test_all_create_and_edit_forms_use_shared_editor(self):
        for kind, endpoint in [('package', 'package'), ('entrance', 'addon'), ('stand', 'additional')]:
            response = self.client.get(reverse('admin_' + endpoint + '_create'))
            self.assertContains(response, 'CUSTOMER PREVIEW')
            self.assertNotContains(response, 'name="features"')
            self.assertNotContains(response, 'Design Requirements')
            offer = self.create(kind)
            self.assertContains(self.client.get(reverse('admin_' + endpoint + '_edit', args=[offer.item.pk])), 'Preview images')

    def test_single_edit_updates_both_customer_text_and_machine_rules(self):
        offer = self.create()
        rows = self.rows()
        rows[0].update(quantity=3, required_minimum=1, name='Custom panels')
        response = self.client.post(reverse('admin_package_edit', args=[offer.item.pk]), self.payload(rows), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'])
        offer.refresh_from_db()
        self.assertEqual(offer.package.features.splitlines()[0], '3 Custom panels')
        rule = offer.requirements.get(category=self.category)
        self.assertEqual((rule.minimum, rule.maximum, rule.display_name), (1, 3, 'Custom panels'))

    def test_optional_and_service_rows_cannot_become_canvas_requirements(self):
        rows = self.rows()
        rows[0]['required_minimum'] = 0
        rows[2]['required_minimum'] = 99
        offer = self.create(rows=rows)
        self.assertEqual(offer.inclusions.get(row_type='service').required_minimum, 0)
        self.assertFalse(offer.requirements.get(category=self.category).required)
        self.assertFalse(offer.requirements.filter(category__isnull=True).exists())

    def test_service_only_offer_saves_when_designer_is_disabled(self):
        offer = self.create(rows=[self.rows()[2]], design_enabled='')
        self.assertFalse(offer.is_enabled)
        self.assertEqual(offer.requirements.count(), 0)
        self.assertEqual(offer.package.features, 'Setup and delivery')

    def test_service_only_offer_cannot_enable_designer(self):
        response = self.client.post(reverse('admin_package_create'), self.payload([self.rows()[2]]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertIn('design_enabled', response.json()['errors'])
        self.assertFalse(Package.objects.exists())

    def test_fixed_quantity_minimum_and_duplicate_category_errors_are_atomic(self):
        offer = self.create()
        for mutate in ('minimum', 'duplicate', 'quantity', 'category', 'blank_required_minimum'):
            rows = self.rows()
            if mutate == 'minimum': rows[0]['required_minimum'] = 3
            if mutate == 'duplicate': rows.append(dict(rows[0]))
            if mutate == 'quantity': rows[0]['quantity'] = 0
            if mutate == 'category': rows[0]['category_id'] = 999999
            if mutate == 'blank_required_minimum': rows[0].update(required=True, required_minimum='')
            response = self.client.post(reverse('admin_package_edit', args=[offer.item.pk]), self.payload(rows, name='Must not save'), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 400)
            self.assertTrue(response.json()['row_errors'])
            self.assertEqual(Package.objects.get(pk=offer.package_id).name, 'Complete offer')
            self.assertEqual(offer.inclusions.count(), 3)

    def test_invalid_details_preserve_bound_values_and_report_fields(self):
        response = self.client.post(reverse('admin_package_create'), self.payload(price='-1', name='Keep this name'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Keep this name"')
        self.assertTrue(response.context['offer_form'].errors.get('price'))
        self.assertEqual(response.context['editor_data']['rows'][0]['quantity'], 2)
        self.assertFalse(Package.objects.exists())

    def test_unresolved_import_requires_mapping_or_service_conversion(self):
        rows = [{'row_type': 'item', 'name': 'Metal Arch 7ft height', 'quantity': None, 'category_id': None, 'required_minimum': 0}]
        response = self.client.post(reverse('admin_package_create'), self.payload(rows, design_enabled=''), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertIn('category_id', response.json()['row_errors']['0'])
        rows[0]['row_type'] = 'service'
        self.assertEqual(self.create(rows=rows, design_enabled='').inclusions.get().name, 'Metal Arch 7ft height')

    def test_category_applicability_is_validated_on_server(self):
        self.category.available_entrance = False
        self.category.save()
        response = self.client.post(reverse('admin_addon_create'), self.payload(), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertIn('category_id', response.json()['row_errors']['0'])

    def test_balloon_flag_survives_category_rename_and_controls_color_validation(self):
        offer = self.create()
        self.balloon_category.name = 'Renamed decoration category'
        self.balloon_category.save()
        asset = CanvasAsset.objects.get(category=self.balloon_category)
        def obj(color):
            p = asset_payload(asset)
            return {'type': 'image', 'src': p['src'], '_assetId': asset.pk, '_assetToken': p['token'], '_designSource': 'catalog', '_currentColor': color}
        result = evaluate_design({'objects': [obj(color) for color in ('#000', '#111', '#222', '#333')]}, offer)
        self.assertIn('Use no more than 3 balloon colors.', result['invalid_items'])

    def test_removing_balloon_rows_clears_stale_color_limit(self):
        rows = [self.rows()[0], self.rows()[2]]
        offer = self.create(rows=rows, design_max_colors='5')
        self.assertIsNone(offer.max_balloon_colors)
        self.assertNotIn('colors', offer.package.features)

    def test_uploaded_images_are_validated_before_catalog_is_created(self):
        invalid = SimpleUploadedFile('fake.png', b'not an image', content_type='image/png')
        response = self.client.post(reverse('admin_package_create'), self.payload(preview_images=[invalid]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()['image_errors'])
        self.assertFalse(Package.objects.exists())

    def test_image_limit_includes_existing_images_and_pending_removals(self):
        offer = self.create(preview_images=[image_upload('one.png'), image_upload('two.png')])
        item = offer.package
        first = item.preview_images.first()
        response = self.client.post(reverse('admin_package_edit', args=[item.pk]), self.payload(name='Must not save', preview_images=[image_upload('three.png')]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(item.preview_images.count(), 2)
        self.assertEqual(Package.objects.get(pk=item.pk).name, 'Complete offer')
        response = self.client.post(reverse('admin_package_edit', args=[item.pk]), self.payload(remove_preview_ids=str(first.pk), preview_images=[image_upload('replacement.png')]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'])
        self.assertEqual(item.preview_images.count(), 2)
        self.assertFalse(item.preview_images.filter(pk=first.pk).exists())

    def test_foreign_image_removal_is_rejected(self):
        offer = self.create(preview_images=[image_upload()])
        response = self.client.post(reverse('admin_package_edit', args=[offer.package_id]), self.payload(remove_preview_ids='99999'), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(offer.package.preview_images.count(), 1)

    def test_customer_role_cannot_open_or_submit_admin_editor(self):
        user = User.objects.create_user(username='offer_customer', role='customer')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('admin_package_create')).status_code, 403)
        self.assertEqual(self.client.post(reverse('admin_package_create'), self.payload()).status_code, 403)

    def test_legacy_import_preserves_dimensions_and_only_links_unambiguous_names(self):
        rows = import_rows('2 Offer panels\nMetal Arch 7ft height (rounded)\nSetup and delivery', [self.category])
        self.assertEqual((rows[0]['quantity'], rows[0]['category_id']), (2, self.category.pk))
        self.assertIsNone(rows[1]['quantity'])
        self.assertEqual(rows[1]['name'], 'Metal Arch 7ft height (rounded)')
        self.assertIsNone(rows[1]['category_id'])

    def test_migration_preserves_rules_limits_and_enablement_without_duplicates(self):
        package = Package.objects.create(name='Imported package', price=1000, features='1 Offer panels\nOffer balloon decor (max 2 colors)\nMetal Arch 7ft height')
        offer = DesignOffer.objects.create(kind='package', package=package, is_enabled=False, max_balloon_colors=4)
        DesignRequirement.objects.create(offer=offer, category=self.category, minimum=2, maximum=3, required=True)
        migrate = importlib.import_module('app.migrations.0101_import_offer_inclusions').import_inclusions
        migrate(apps, None)
        migrate(apps, None)
        self.assertEqual(offer.inclusions.count(), 3)
        panel = offer.inclusions.get(category=self.category)
        self.assertEqual((panel.quantity, panel.required_minimum), (3, 2))
        balloon_rule = offer.requirements.get(category=self.balloon_category)
        self.assertEqual((balloon_rule.minimum, balloon_rule.maximum, balloon_rule.required), (0, None, False))
        offer.refresh_from_db()
        self.assertFalse(offer.is_enabled)
        self.assertEqual(offer.max_balloon_colors, 4)
        self.assertEqual(offer.package.features.splitlines(), ['3 Offer panels', 'Offer balloon decor (max 4 colors)', 'Metal Arch 7ft height'])
