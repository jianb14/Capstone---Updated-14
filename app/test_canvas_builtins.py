import importlib
import json
from types import SimpleNamespace

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from .canvas_builtins import STYRO_NAME
from .design_validation import asset_payload, evaluate_design
from .models import AddOn, AdditionalOnly, CanvasAsset, CanvasCategory, DesignOffer, DesignRequirement, Package, User, UserDesign


class BuiltinStyroTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.asset = CanvasAsset.objects.get(builtin_key=STYRO_NAME)
        cls.category = cls.asset.category
        cls.user = User.objects.create_user(username='builtin_customer', role='customer')
        cls.admin = User.objects.create_user(username='builtin_admin', role='admin')
        cls.offers = []
        for kind, owner in (
            ('package', Package.objects.create(name='Builtin package', price=1000)),
            ('entrance', AddOn.objects.create(name='Builtin entrance', price=500, solo_price=1500)),
            ('stand', AdditionalOnly.objects.create(name='Builtin stand', price=800)),
        ):
            offer = DesignOffer.objects.create(kind=kind, **{kind: owner}, is_enabled=True)
            DesignRequirement.objects.create(offer=offer, category=cls.category, required=True, minimum=1, maximum=1)
            cls.offers.append(offer)

    def test_seed_is_idempotent_and_preserves_catalog_identity(self):
        migration = importlib.import_module('app.migrations.0103_builtin_styro_name')
        migration.register_styro_name(apps, SimpleNamespace(connection=connection))
        self.assertEqual(CanvasAsset.objects.get(builtin_key=STYRO_NAME).pk, self.asset.pk)
        self.assertEqual(CanvasCategory.objects.get(builtin_key=STYRO_NAME).pk, self.category.pk)

    def test_builtin_and_category_cannot_be_deleted_even_through_bulk_delete(self):
        for model, pk in ((CanvasAsset, self.asset.pk), (CanvasCategory, self.category.pk)):
            for bulk in (True, False):
                with self.assertRaises(ProtectedError), transaction.atomic():
                    queryset = model.objects.filter(pk=pk)
                    queryset.delete() if bulk else queryset.get().delete()
                self.assertTrue(model.objects.filter(pk=pk).exists())

    def test_preset_cannot_be_hidden_or_reclassified(self):
        for model, pk, field, value in (
            (CanvasAsset, self.asset.pk, 'is_active', False),
            (CanvasAsset, self.asset.pk, 'available_entrance', False),
            (CanvasAsset, self.asset.pk, 'item_type', 'image'),
            (CanvasAsset, self.asset.pk, 'builtin_key', None),
            (CanvasCategory, self.category.pk, 'is_active', False),
            (CanvasCategory, self.category.pk, 'is_balloon', True),
        ):
            instance = model.objects.get(pk=pk)
            setattr(instance, field, value)
            with self.assertRaises(ValidationError):
                instance.save()

    def test_admin_cannot_delete_or_edit_via_direct_urls(self):
        self.client.force_login(self.admin)
        for kind, pk in (('asset', self.asset.pk), ('category', self.category.pk)):
            for method in (self.client.get, self.client.post):
                response = method(reverse('admin_canvas_' + kind + '_edit', args=[pk]), {'name': 'Tampered', 'is_active': ''})
                self.assertRedirects(response, reverse('admin_canvas_assets'), fetch_redirect_response=False)
                response = method(reverse('admin_canvas_' + kind + '_delete', args=[pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                self.assertEqual(response.status_code, 400)
        self.assertTrue(CanvasAsset.objects.get(pk=self.asset.pk).is_active)
        response = self.client.get(reverse('admin_canvas_assets'), {'asset_category': self.category.pk})
        self.assertContains(response, 'Built-in')
        self.assertNotContains(response, reverse('admin_canvas_asset_delete', args=[self.asset.pk]))
        self.assertNotContains(response, reverse('admin_canvas_category_delete', args=[self.category.pk]))

    def test_stable_text_counts_for_all_offer_types_and_references_do_not(self):
        payload = asset_payload(self.asset)
        obj = {'type': 'i-text', 'text': 'Alex', '_assetId': self.asset.pk, '_assetToken': payload['token'], '_designSource': 'catalog'}
        for offer in self.offers:
            self.assertTrue(evaluate_design({'objects': [obj]}, offer)['can_book'])
            self.assertFalse(evaluate_design({'objects': [{**obj, 'text': ''}]}, offer)['can_book'])
            self.assertFalse(evaluate_design({'objects': [{**obj, '_designSource': 'reference'}]}, offer)['can_book'])
            self.assertFalse(evaluate_design({'objects': [obj, obj]}, offer)['can_book'])

    def test_another_session_gets_same_builtin_and_existing_design_can_reopen(self):
        self.client.force_login(self.user)
        for offer in self.offers:
            url = reverse('design_canvas') + f'?design_offer_id={offer.pk}'
            first = self.client.get(url)
            self.assertEqual(first.context['styro_asset'].pk, self.asset.pk)
            self.assertNotIn(self.category.pk, [category.pk for category in first.context['canvas_categories']])
            self.client.logout()
            self.client.force_login(self.user)
            self.assertEqual(self.client.get(url).context['styro_asset'].pk, self.asset.pk)
        payload = asset_payload(self.asset)
        state = json.dumps({'objects': [{'type': 'i-text', 'text': 'Alex', '_assetId': self.asset.pk, '_assetToken': payload['token'], '_designSource': 'catalog'}]})
        design = UserDesign.objects.create(user=self.user, design_offer=self.offers[0], canvas_json=state)
        self.assertEqual(self.client.get(reverse('design_canvas'), {'id': design.pk}).status_code, 200)
