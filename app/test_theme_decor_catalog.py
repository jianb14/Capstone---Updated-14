"""Admin catalog images and private uploads share the Theme Decor allowance."""
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from .canvas_builtins import THEME_DECOR
from .design_validation import asset_payload, eligible_assets, evaluate_design, offer_is_ready
from .models import CanvasAsset, CanvasCategory, DesignOffer, DesignRequirement, Package, User
from .test_canvas_uploads import TemporaryCanvasStorage, photo, placement


class ThemeDecorCatalogTests(TemporaryCanvasStorage, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = CanvasCategory.objects.get(builtin_key=THEME_DECOR)
        cls.admin = User.objects.create_user(username='theme-catalog-admin', role='admin')
        cls.customer = User.objects.create_user(username='theme-catalog-customer', role='customer')
        cls.offer = DesignOffer.objects.create(
            kind='package', package=Package.objects.create(name='Themed catalog package', price=1000), is_enabled=True)
        DesignRequirement.objects.create(
            offer=cls.offer, category=cls.category, required=True, minimum=2, maximum=2)

    def admin_url(self, action='create', pk=0):
        return reverse('admin_catalog_action', args=['canvas-asset', action, pk])

    def create_asset(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.admin_url(), {
            'label': 'Basketball prop', 'category': self.category.pk, 'image': photo(),
            'width': 150, 'height': 150, 'available_for': ['package'], 'is_active': 'on',
        })
        self.assertEqual(response.status_code, 200, response.content)
        return CanvasAsset.objects.get(label='Basketball prop')

    def catalog_placement(self, asset):
        payload = asset_payload(asset)
        return {'type': 'image', 'src': payload['src'], '_assetId': payload['id'],
                '_assetToken': payload['token'], '_categoryId': payload['category_id'], '_designSource': 'catalog'}

    def test_admin_can_choose_create_edit_hide_and_delete_theme_image(self):
        self.client.force_login(self.admin)
        form = self.client.get(self.admin_url()).json()['html']
        self.assertIn(f'value="{self.category.pk}"', form)
        asset = self.create_asset()
        self.assertIn(asset, eligible_assets(self.offer))
        original_image = asset.image.name
        response = self.client.post(self.admin_url('edit', asset.pk), {
            'label': 'Basketball decoration', 'category': self.category.pk,
            'width': 180, 'height': 140, 'available_for': ['package'],
        })
        self.assertEqual(response.status_code, 200, response.content)
        asset.refresh_from_db()
        self.assertEqual(asset.label, 'Basketball decoration')
        self.assertEqual(asset.image.name, original_image)
        self.assertFalse(asset.is_active)
        self.assertNotIn(asset, eligible_assets(self.offer))
        self.assertEqual(self.client.post(self.admin_url('delete', asset.pk)).status_code, 200)
        self.assertFalse(CanvasAsset.objects.filter(pk=asset.pk).exists())
        self.assertTrue(CanvasCategory.objects.filter(pk=self.category.pk, builtin_key=THEME_DECOR).exists())
        self.assertTrue(offer_is_ready(self.offer))

    def test_catalog_and_customer_upload_share_quota_and_survive_save_reopen(self):
        asset = self.create_asset()
        self.client.force_login(self.customer)
        response = self.client.post(reverse('canvas_upload_create'), {
            'image': photo(), 'category_id': self.category.pk, 'design_offer_id': self.offer.pk,
        })
        self.assertEqual(response.status_code, 201, response.content)
        upload = response.json()['upload']
        state = {'objects': [self.catalog_placement(asset), placement(upload)]}
        result = evaluate_design(state, self.offer, owner=self.customer)
        self.assertTrue(result['can_book'], result)
        self.assertEqual(result['counts'], {self.category.pk: 2})
        over_limit = evaluate_design({'objects': [*state['objects'], placement(upload)]}, self.offer, owner=self.customer)
        self.assertFalse(over_limit['can_book'])
        self.assertEqual(over_limit['counts'], {self.category.pk: 3})
        self.assertTrue(over_limit['rows'][0]['over_limit'])
        response = self.client.post(reverse('save_user_design'), {
            'canvas_json': state, 'design_offer_id': self.offer.pk, 'upload_ids': [upload['id']],
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['can_book'], response.content)
        reopened = self.client.get(reverse('design_canvas'), {'id': response.json()['id']})
        assets = reopened.context['canvas_assets_payload_obj']['theme decor']
        self.assertIn(asset.pk, [item['id'] for item in assets])
        self.assertIn(str(upload['id']), reopened.context['canvas_uploads_payload'])
        self.assertContains(reopened, f'data-asset-id="{asset.pk}"')
        self.assertContains(reopened, f'data-category-upload="{self.category.pk}"')
        restored = evaluate_design(reopened.context['saved_canvas_state'], self.offer, owner=self.customer)
        self.assertTrue(restored['can_book'], restored)
        DesignRequirement.objects.filter(offer=self.offer, category=self.category).delete()
        other = CanvasCategory.objects.create(name='Unrelated panel')
        CanvasAsset.objects.create(category=other, label='Panel', static_path='panel.svg')
        DesignRequirement.objects.create(offer=self.offer, category=other, required=True, minimum=1)
        for item in state['objects']:
            excluded = evaluate_design({'objects': [item]}, self.offer, owner=self.customer)
            self.assertTrue(any('not included' in message for message in excluded['invalid_items']), excluded)

    def test_catalog_eligibility_respects_design_type(self):
        asset = self.create_asset()
        for kind in ('package', 'entrance', 'stand'):
            with self.subTest(kind=kind):
                offer = DesignOffer(kind=kind)
                self.assertEqual(eligible_assets(offer).filter(pk=asset.pk).exists(), kind == 'package')
        asset.available_entrance = True
        asset.available_stand = True
        asset.save()
        for kind in ('package', 'entrance', 'stand'):
            self.assertTrue(eligible_assets(DesignOffer(kind=kind)).filter(pk=asset.pk).exists())

    def test_legacy_admin_asset_form_lists_theme_decor(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_canvas_asset_create'))
        self.assertContains(response, f'<option value="{self.category.pk}"')

    def test_legacy_admin_can_create_and_edit_theme_image(self):
        self.client.force_login(self.admin)
        data = {'label': 'Legacy theme image', 'category': self.category.pk, 'image': photo(),
                'width': 150, 'height': 150, 'available_for': ['package'],
                'availability_present': '1', 'is_active': 'on'}
        response = self.client.post(reverse('admin_canvas_asset_create'), data)
        self.assertEqual(response.status_code, 302, response.content)
        asset = CanvasAsset.objects.get(label='Legacy theme image')
        data.pop('image')
        data['label'] = 'Updated legacy theme image'
        response = self.client.post(reverse('admin_canvas_asset_edit', args=[asset.pk]), data)
        self.assertEqual(response.status_code, 302, response.content)
        asset.refresh_from_db()
        self.assertEqual(asset.label, 'Updated legacy theme image')
        self.assertIn(asset, eligible_assets(self.offer))

    def test_customer_cannot_administer_theme_images_and_category_stays_protected(self):
        asset = self.create_asset()
        self.client.force_login(self.customer)
        for action, pk in (('create', 0), ('edit', asset.pk), ('delete', asset.pk)):
            self.assertEqual(self.client.post(self.admin_url(action, pk), {}).status_code, 403)
        self.assertTrue(CanvasAsset.objects.filter(pk=asset.pk).exists())
        self.category.name = 'Renamed theme'
        with self.assertRaises(ValidationError):
            self.category.save()
        with self.assertRaises(ProtectedError):
            self.category.delete()
