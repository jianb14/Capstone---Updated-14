import json
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from . import test_design_requirements as fixtures
from .models import Booking, Design, ServiceChargeConfig, User, UserDesign


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', REQUEST_RATE_LIMITING_ENABLED=False)
class MultiDesignBookingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.DesignRequirementsTests.setUpTestData.__func__(cls)

    obj = fixtures.DesignRequirementsTests.obj
    canvas = fixtures.DesignRequirementsTests.canvas
    complete = fixtures.DesignRequirementsTests.complete
    design = fixtures.DesignRequirementsTests.design
    booking_payload = fixtures.DesignRequirementsTests.booking_payload

    def setUp(self):
        self.client.force_login(self.user)
        ServiceChargeConfig.objects.update_or_create(pk=1, defaults={'amount': 100})
        self.saved = {
            'package': self.design(),
            'entrance': self.design(self.canvas(self.obj(self.balloon)), self.entrance_offer),
            'stand': self.design(self.canvas(self.obj(self.balloon)), self.stand_offer),
        }
        self.alert = patch('app.views.bookings.send_admin_alert_email').start()
        self.addCleanup(patch.stopall)

    def submit(self, ids, **changes):
        payload = self.booking_payload(self.saved['package'])
        payload['user_design_id'] = [str(value) for value in ids]
        if 'design_selection_quote' not in changes:
            page = self.client.get(reverse('booking_page'), {'design_id': payload['user_design_id']})
            if page.status_code == 200:
                payload['design_selection_quote'] = page.context['design_selection_quote']
        payload.update(changes)
        return self.client.post(reverse('create_booking'), payload, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_six_combinations_have_correct_prices_and_all_snapshots(self):
        cases = [
            (('package',), 'Test package', 5000),
            (('entrance',), 'Test entrance (Solo)', 2500),
            (('package', 'entrance'), 'Test package + Test entrance', 6500),
            (('package', 'stand'), 'Test package + Test stand', 6200),
            (('entrance', 'stand'), 'Test entrance (Solo) + Test stand', 3700),
            (('package', 'entrance', 'stand'), 'Test package + Test entrance + Test stand', 7700),
        ]
        for kinds, label, subtotal in cases:
            with self.subTest(kinds=kinds):
                response = self.submit([self.saved[k].pk for k in kinds])
                self.assertTrue(response.json()['success'], response.content)
                booking = Booking.objects.latest('pk')
                self.assertEqual(booking.package_type, label)
                self.assertEqual(booking.total_price, Decimal(subtotal + 100))
                self.assertEqual(booking.designs.count(), len(kinds))
                self.assertEqual({d.reference_snapshot['kind'] for d in booking.designs.all()}, set(kinds))
                self.assertEqual(sum(d.price_estimate for d in booking.designs.all()), Decimal(subtotal))

    def test_stand_only_is_rejected_without_creating_booking(self):
        response = self.submit([self.saved['stand'].pk])
        self.assertEqual(response.status_code, 400)
        self.assertIn('package or entrance', response.json()['message'].lower())
        self.assertFalse(Booking.objects.exists())

    def test_duplicate_ids_categories_and_oversized_lists_are_rejected(self):
        second_package = self.design()
        for ids in ([self.saved['package'].pk] * 2,
                    [self.saved['package'].pk, second_package.pk],
                    [self.saved['package'].pk] * 4):
            with self.subTest(ids=ids):
                response = self.submit(ids)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(Booking.objects.exists())

    def test_malformed_and_foreign_ids_are_rejected(self):
        for ids in (['not-an-id'], ['0'], ['-2'], ['9' * 100]):
            with self.subTest(ids=ids):
                self.assertEqual(self.submit(ids).status_code, 400)
        other = User.objects.create_user(username='other_multi_owner', role='customer')
        self.saved['entrance'].user = other
        self.saved['entrance'].save()
        self.assertEqual(self.submit([self.saved['package'].pk, self.saved['entrance'].pk]).status_code, 404)
        self.assertFalse(Booking.objects.exists())

    def test_incomplete_component_rejects_entire_booking(self):
        self.saved['entrance'].canvas_json = '{"objects": []}'
        self.saved['entrance'].save()
        response = self.submit([d.pk for d in self.saved.values()])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Booking.objects.exists())
        self.assertFalse(Design.objects.exists())

    def test_get_handoff_resolves_every_design_in_canonical_order(self):
        response = self.client.get(reverse('booking_page'), {'design_id': [self.saved[k].pk for k in ('stand', 'entrance', 'package')]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([entry['kind'] for entry in response.context['prefilled_selection']], ['package', 'entrance', 'stand'])
        self.assertEqual(response.context['prefilled_selection'][1]['amount'], '1500.00')
        self.assertTrue(response.context['design_selection_quote'])

    def test_stand_only_handoff_returns_to_my_designs(self):
        response = self.client.get(reverse('booking_page'), {'design_id': self.saved['stand'].pk})
        self.assertRedirects(response, reverse('my_designs'), fetch_redirect_response=False)

    def test_price_change_requires_review_before_booking(self):
        ids = [self.saved['package'].pk, self.saved['entrance'].pk]
        page = self.client.get(reverse('booking_page'), {'design_id': ids})
        token = page.context.get('design_selection_quote', 'missing-current-token')
        self.entrance.price = Decimal('1700')
        self.entrance.save()
        response = self.submit(ids, design_selection_quote=token)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['design_selection'][1]['amount'], '1700.00')
        self.assertFalse(Booking.objects.exists())
        accepted = self.submit(ids, design_selection_quote=response.json()['design_selection_quote'])
        self.assertTrue(accepted.json()['success'])
        self.assertEqual(Booking.objects.get().total_price, Decimal('6800'))

    def test_snapshots_survive_source_deletion_and_submit_replay(self):
        ids = [d.pk for d in self.saved.values()]
        first = self.submit(ids)
        self.assertTrue(first.json()['success'])
        self.assertTrue(self.submit(ids).json()['success'])
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(Design.objects.count(), 3)
        UserDesign.objects.filter(pk__in=ids).delete()
        self.assertEqual(Design.objects.count(), 3)
        self.assertTrue(all(d.reference_snapshot['canvas']['objects'] for d in Design.objects.all()))

    def test_regular_booking_stand_only_and_duplicate_packages_are_rejected(self):
        for label in ('Test stand', 'Test package + Test package'):
            payload = self.booking_payload(self.saved['package'])
            payload.pop('user_design_id')
            payload.update(package_type=label, total_price='2000')
            response = self.client.post(reverse('create_booking'), payload, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 400)
            self.assertFalse(Booking.objects.exists())

    def test_component_failure_rolls_back_the_whole_booking(self):
        from pathlib import Path
        from django.conf import settings
        from .design_reference_snapshot import save_booking_design_reference
        from .test_booking_preview import _preview_upload
        for design in self.saved.values():
            design.thumbnail.save(f'multi-{design.pk}.png', _preview_upload())
        image_dir = Path(settings.MEDIA_ROOT) / 'designs'
        before = set(image_dir.glob('*'))
        calls = []
        def fail_second(*args, **kwargs):
            calls.append(True)
            if len(calls) == 2:
                raise OSError('Snapshot storage failure')
            return save_booking_design_reference(*args, **kwargs)
        with patch('app.design_reference_snapshot.save_booking_design_reference', side_effect=fail_second):
            with self.assertRaises(OSError):
                self.submit([d.pk for d in self.saved.values()])
        self.assertFalse(Booking.objects.exists())
        self.assertFalse(Design.objects.exists())
        self.assertEqual(set(image_dir.glob('*')), before)

    def test_composition_validator_preserves_legacy_and_rejects_invalid_known_items(self):
        from .design_booking import validate_catalog_selection
        self.assertIsNone(validate_catalog_selection('Legacy bespoke setup'))
        for label in ('Test stand', 'Test package + Test entrance (Solo)', 'Test package + missing item'):
            with self.subTest(label=label), self.assertRaises(ValidationError):
                validate_catalog_selection(label)

    def test_library_exposes_account_scoped_typed_catalog_and_selection_controls(self):
        other = User.objects.create_user(username='private_catalog_owner', role='customer')
        UserDesign.objects.create(user=other, name='Never exposed', design_offer=self.offer, canvas_json=self.complete())
        response = self.client.get(reverse('my_designs'))
        catalog = response.context.get('design_booking_catalog', [])
        self.assertEqual({row['id'] for row in catalog}, {d.pk for d in self.saved.values()})
        self.assertEqual({row['kind'] for row in catalog}, {'package', 'entrance', 'stand'})
        entrance = next(row for row in catalog if row['kind'] == 'entrance')
        self.assertEqual(entrance['price'], '1500.00')
        self.assertEqual(entrance['solo_price'], '2500.00')
        self.assertContains(response, 'Select for Booking')
        self.assertContains(response, 'Your booking')
        self.assertContains(response, 'Design complete')
        self.assertNotContains(response, 'Never exposed')

    def test_library_category_filter_keeps_complete_catalog_for_persistence(self):
        response = self.client.get(reverse('my_designs'), {'kind': 'entrance'})
        self.assertEqual({d.pk for d in response.context['designs']}, {self.saved['entrance'].pk})
        self.assertEqual(len(response.context.get('design_booking_catalog', [])), 3)

    def test_booking_template_exposes_all_designs_and_signed_quote(self):
        response = self.client.get(reverse('booking_page'), {'design_id': [d.pk for d in self.saved.values()]})
        self.assertContains(response, 'id="savedDesignSelection"')
        self.assertContains(response, 'applySavedDesignSelection')
        self.assertContains(response, 'Your selected designs')
        self.assertContains(response, 'design_selection_quote')

    def test_pending_edit_rejects_stand_only_without_changing_booking(self):
        self.assertTrue(self.submit([self.saved['package'].pk]).json()['success'])
        booking = Booking.objects.get()
        payload = self.booking_payload(self.saved['package'])
        payload.update(package_type='Test stand', total_price='1300')
        response = self.client.post(reverse('edit_booking', args=[booking.pk]), payload, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        booking.refresh_from_db()
        self.assertEqual(booking.package_type, 'Test package')

    def test_saved_selection_prices_use_ids_even_when_offer_names_contain_plus(self):
        self.package.name = 'Package + Celebration'
        self.package.save()
        response = self.submit([d.pk for d in self.saved.values()])
        self.assertTrue(response.json()['success'], response.content)
        self.assertEqual(Booking.objects.get().total_price, Decimal('7800'))

    def test_change_proposal_rejects_stand_only(self):
        from .booking_changes import prepare_proposal
        self.assertTrue(self.submit([self.saved['package'].pk]).json()['success'])
        booking = Booking.objects.get()
        payload = self.booking_payload(self.saved['package'])
        payload.update(package_type='Test stand', total_price='1300')
        with self.assertRaisesMessage(ValidationError, 'package or entrance'):
            prepare_proposal(booking, payload)

    def test_saved_name_with_plus_uses_actual_offer_theme_capability(self):
        self.package.name = 'Package + Celebration'
        self.package.save()
        response = self.submit([self.saved['package'].pk], design_theme='')
        self.assertTrue(response.json()['success'], response.content)

    def test_multi_id_submission_without_quote_requires_review(self):
        response = self.submit([d.pk for d in self.saved.values()], design_selection_quote='')
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Booking.objects.exists())

    def test_fee_policy_change_requires_review(self):
        ids = [self.saved['package'].pk]
        page = self.client.get(reverse('booking_page'), {'design_id': ids})
        ServiceChargeConfig.objects.filter(pk=1).update(amount=300)
        response = self.submit(ids, design_selection_quote=page.context['design_selection_quote'])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['fee_policy']['logistics']['base'], 300.0)
        self.assertFalse(Booking.objects.exists())

    def test_note_only_pending_edit_preserves_booked_items_and_fees(self):
        self.assertTrue(self.submit([d.pk for d in self.saved.values()]).json()['success'])
        booking = Booking.objects.get()
        self.package.price = 9000
        self.package.save()
        self.entrance.price = 2000
        self.entrance.save()
        ServiceChargeConfig.objects.filter(pk=1).update(amount=300)
        payload = self.booking_payload(self.saved['package'])
        payload.update(package_type=booking.package_type, total_price='99999', special_requests='Change the welcome text only.')
        response = self.client.post(reverse('edit_booking', args=[booking.pk]), payload, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'], response.content)
        booking.refresh_from_db()
        self.assertEqual(booking.total_price, Decimal('7800'))

    def test_amendment_preserves_retained_entrance_and_stand_prices(self):
        from .booking_changes import prepare_proposal
        from .models import Package
        self.assertTrue(self.submit([d.pk for d in self.saved.values()]).json()['success'])
        booking = Booking.objects.get()
        Package.objects.create(name='Replacement package', price=7000)
        self.entrance.price = 1900
        self.entrance.save()
        self.stand.price = 1600
        self.stand.save()
        payload = self.booking_payload(self.saved['package'])
        payload['package_type'] = 'Replacement package + Test entrance + Test stand'
        proposed = prepare_proposal(booking, payload)
        self.assertEqual(proposed.total_price, Decimal('9800'))

    def test_zero_price_extras_remain_bookable(self):
        self.entrance.price = 0
        self.entrance.save()
        self.stand.price = 0
        self.stand.save()
        response = self.submit([d.pk for d in self.saved.values()])
        self.assertTrue(response.json()['success'], response.content)
        self.assertEqual(Booking.objects.get().total_price, Decimal('5100'))

    def test_empty_regular_selection_is_rejected(self):
        from .design_booking import validate_catalog_selection
        for label in ('', '   ', None):
            with self.subTest(label=label), self.assertRaises(ValidationError):
                validate_catalog_selection(label)

    def test_normal_catalog_names_containing_plus_are_resolved(self):
        from .design_booking import validate_catalog_selection
        self.package.name = 'Package + Celebration'
        self.package.save()
        self.assertEqual(validate_catalog_selection('Package + Celebration + Test stand'), 'Package + Celebration + Test stand')

    def test_failure_after_snapshots_cleans_all_new_files(self):
        from pathlib import Path
        from django.conf import settings
        from .test_booking_preview import _preview_upload
        for design in self.saved.values():
            design.thumbnail.save(f'late-{design.pk}.png', _preview_upload())
        before = {p for p in Path(settings.MEDIA_ROOT).rglob('*') if p.is_file()}
        with patch('app.views.bookings.log_action', side_effect=OSError('Late audit failure')):
            with self.assertRaises(OSError):
                self.submit([d.pk for d in self.saved.values()], reference_image=_preview_upload('legacy.png'))
        self.assertFalse(Booking.objects.exists())
        self.assertEqual({p for p in Path(settings.MEDIA_ROOT).rglob('*') if p.is_file()}, before)

    def test_missing_thumbnail_still_has_customer_and_admin_component_labels(self):
        self.assertTrue(self.submit([d.pk for d in self.saved.values()]).json()['success'])
        booking = Booking.objects.get()
        response = self.client.get(reverse('booking_modal_content', args=[booking.pk]))
        self.assertContains(response, 'Preview unavailable', count=3)
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_booking_detail', args=[booking.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(response, 'Preview unavailable', count=3)

    def test_legacy_pending_amendment_is_validated_at_quote_issuance(self):
        from .booking_changes import issue_quote, snapshot
        from .models import BookingChangeRequest
        self.assertTrue(self.submit([self.saved['package'].pk]).json()['success'])
        booking = Booking.objects.get()
        booking.status = 'confirmed'
        booking.save()
        original = snapshot(booking)
        proposed = dict(original, package_type='Test stand', total_price='1300')
        change = BookingChangeRequest.objects.create(booking=booking, reason='Legacy draft', original=original,
            proposed=proposed, original_total=booking.total_price, quoted_total=1300)
        with self.assertRaisesMessage(ValidationError, 'package or entrance'):
            issue_quote(change, self.admin)

    def test_deleted_design_handoff_from_selector_is_actionable(self):
        pk = self.saved['package'].pk
        self.saved['package'].delete()
        response = self.client.get(reverse('booking_page'), {'design_id': pk, 'saved_selection': '1'})
        self.assertRedirects(response, reverse('my_designs'), fetch_redirect_response=False)

    def test_literal_mode_word_in_catalog_name_does_not_change_its_kind(self):
        self.stand.name = 'Welcome (Solo)'
        self.stand.save()
        payload = self.booking_payload(self.saved['package'])
        payload.pop('user_design_id')
        payload.update(package_type='Test package + Welcome (Solo)', total_price='6300')
        response = self.client.post(reverse('create_booking'), payload, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'], response.content)
        self.assertEqual(Booking.objects.get().total_price, Decimal('6300'))
