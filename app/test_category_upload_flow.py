import json
import importlib
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.apps import apps
from django.db import connection
from django.urls import reverse

from .models import CanvasAsset, CanvasCategory, DesignOffer, DesignRequirement, OfferInclusion, Package, User, UserDesign
from .test_canvas_uploads import TemporaryCanvasStorage, photo, placement


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class CategoryUploadFlowTests(TemporaryCanvasStorage, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username='upload-flow', role='customer')
        cls.category = CanvasCategory.objects.create(name='Flow Panels')
        CanvasAsset.objects.create(category=cls.category, label='Flow panel', static_path='images/canvas/premium/frames/panel_wall.svg')
        cls.package = Package.objects.create(name='Upload flow package', price=1000)
        cls.offer = DesignOffer.objects.create(kind='package', package=cls.package, is_enabled=True)
        DesignRequirement.objects.create(offer=cls.offer, category=cls.category, required=True, minimum=1, maximum=2)

    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    def upload(self):
        response = self.client.post(reverse('canvas_upload_create'), {'image': photo(), 'category_id': self.category.pk, 'design_offer_id': self.offer.pk})
        self.assertEqual(response.status_code, 201)
        return response.json()['upload']

    def test_save_evaluate_and_reopen_restore_upload_category_library(self):
        upload = self.upload()
        state = {'objects': [placement(upload)], 'upload_library_ids': [upload['id']]}
        payload = {'canvas_json': state, 'design_offer_id': self.offer.pk, 'upload_ids': [upload['id']]}
        evaluated = self.client.post(reverse('evaluate_user_design'), payload, content_type='application/json')
        self.assertTrue(evaluated.json()['can_book'], evaluated.content)
        response = self.client.post(reverse('save_user_design'), payload, content_type='application/json')
        self.assertTrue(response.json()['can_book'], response.content)
        design = UserDesign.objects.get(pk=response.json()['id'])
        self.assertEqual(list(design.uploads.values_list('pk', flat=True)), [upload['id']])
        reopened = self.client.get(reverse('design_canvas'), {'id': design.pk})
        self.assertEqual(reopened.context['canvas_uploads_payload'][str(upload['id'])]['category_id'], self.category.pk)
        self.assertContains(reopened, 'data-category-upload=')
        self.assertContains(reopened, 'data-builtin-key="theme_decor"')
        self.assertNotContains(reopened, 'id="referenceUploadDropzone"')
        self.assertContains(reopened, 'id="bgImageUpload"')

    def test_library_removal_keeps_an_image_still_used_on_canvas(self):
        upload = self.upload()
        response = self.client.post(reverse('save_user_design'), {'canvas_json': {'objects': [placement(upload)]}, 'design_offer_id': self.offer.pk, 'upload_ids': []}, content_type='application/json')
        design = UserDesign.objects.get(pk=response.json()['id'])
        self.assertTrue(design.uploads.filter(pk=upload['id']).exists())

    def test_approved_mapping_preserves_quantity_and_does_not_add_inclusions(self):
        targeted = DesignOffer.objects.create(kind='package', package=Package.objects.create(name='Package 1-B', price=1500))
        row = OfferInclusion.objects.create(offer=targeted, row_type='service', name='Theme Decor', quantity=None)
        unrelated = OfferInclusion.objects.create(offer=self.offer, row_type='service', name='Theme Decor', quantity=2)
        migration = importlib.import_module('app.migrations.0123_map_theme_decor_inclusions')
        for _ in range(2):
            migration.map_theme_decor(apps, SimpleNamespace(connection=connection))
        row.refresh_from_db()
        self.assertEqual(row.row_type, 'item')
        self.assertIsNone(row.quantity)
        self.assertEqual(row.category.builtin_key, 'theme_decor')
        self.assertEqual(targeted.requirements.get().minimum, 0)
        self.assertIsNone(targeted.requirements.get().maximum)
        self.assertEqual(targeted.requirements.count(), 1)
        unrelated.refresh_from_db()
        self.assertEqual(unrelated.row_type, 'service')
        self.assertIsNone(unrelated.category_id)

    def test_library_binding_failure_rolls_back_saved_canvas(self):
        upload = self.upload()
        original = json.dumps({'objects': []})
        design = UserDesign.objects.create(user=self.owner, design_offer=self.offer, canvas_json=original)
        with patch.object(type(design.uploads), 'set', side_effect=RuntimeError('Storage relationship failed')):
            response = self.client.post(reverse('save_user_design'), {'id': design.pk, 'canvas_json': {'objects': [placement(upload)]},
                'design_offer_id': self.offer.pk, 'upload_ids': [upload['id']]}, content_type='application/json')
        self.assertEqual(response.status_code, 500)
        design.refresh_from_db()
        self.assertEqual(design.canvas_json, original)

    def test_snapshot_keeps_hidden_image_and_flags_a_changed_catalog_only_package(self):
        from django.template.loader import render_to_string
        from .design_reference_snapshot import save_booking_design_reference
        from .models import Booking
        upload = self.upload()
        design = UserDesign.objects.create(user=self.owner, design_offer=self.offer,
            canvas_json=json.dumps({'objects': [placement(upload, visible=False)]}))
        booking = Booking.objects.create(user=self.owner, event_date='2030-01-15', event_time='09:00',
            event_type='Birthday', event_location='Test Venue', package_type=self.package.name, total_price=1000)
        submitted = save_booking_design_reference(booking, design)
        self.assertEqual(submitted.reference_snapshot['custom_items'], [])
        self.assertTrue(submitted.uploads.filter(pk=upload['id']).exists())
        booking.package_type = 'Changed package'
        html = render_to_string('admin/booking/workspace/_references.html', {'booking': booking})
        self.assertIn('package has changed', html)

    def test_catalog_only_snapshot_also_shows_changed_package_notice(self):
        from django.template.loader import render_to_string
        from .models import Booking, Design
        booking = Booking.objects.create(user=self.owner, event_date='2030-01-15', event_time='09:00',
            event_type='Birthday', event_location='Test Venue', package_type='Changed package', total_price=1000)
        Design.objects.create(booking=booking, style='Catalog setup', color_palette='White', image='', price_estimate=1000,
            reference_snapshot={'booking_package': 'Original package', 'custom_items': []})
        html = render_to_string('admin/booking/workspace/_references.html', {'booking': booking})
        self.assertIn('package has changed', html)

    def test_mapping_rejects_a_conflicting_existing_theme_allowance(self):
        targeted = DesignOffer.objects.create(kind='package', package=Package.objects.create(name='Package 2', price=1500))
        category = CanvasCategory.objects.get(builtin_key='theme_decor')
        row = OfferInclusion.objects.create(offer=targeted, row_type='service', name='Theme Decor')
        rule = DesignRequirement.objects.create(offer=targeted, category=category, required=True, minimum=1, maximum=3)
        migration = importlib.import_module('app.migrations.0123_map_theme_decor_inclusions')
        with self.assertRaisesRegex(RuntimeError, 'different allowance'):
            migration.map_theme_decor(apps, SimpleNamespace(connection=connection))
        row.refresh_from_db()
        rule.refresh_from_db()
        self.assertEqual((rule.minimum, rule.maximum), (1, 3))
        self.assertEqual(row.row_type, 'service')

    @patch('app.views.bookings.send_admin_alert_email')
    def test_booking_retains_submitted_breakdown_after_source_design_deletion(self, alert):
        upload = self.upload()
        design = UserDesign.objects.create(user=self.owner, design_offer=self.offer,
                                          canvas_json=json.dumps({'objects': [placement(upload), placement(upload)]}))
        payload = {'user_design_id': design.pk, 'event_type': 'Birthday', 'event_date': '2030-01-15',
                   'start_time': '09:00', 'end_time': '11:00', 'event_location': 'Test Venue in Cavite',
                   'map_available': '0', 'design_theme': 'Garden', 'color_palette': 'Green, White'}
        response = self.client.post(reverse('create_booking'), payload, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'], response.content)
        from .models import Design
        submitted = Design.objects.get()
        self.assertEqual(submitted.reference_snapshot['custom_items'][0]['quantity'], 2)
        self.assertEqual(submitted.reference_snapshot['custom_items'][0]['category'], self.category.name)
        design.delete()
        self.assertTrue(submitted.uploads.filter(pk=upload['id']).exists())
        admin = User.objects.create_user(username='flow-admin', role='admin')
        self.client.force_login(admin)
        response = self.client.get(upload['src'])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b''.join(response.streaming_content))
