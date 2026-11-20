from decimal import Decimal

from django.test import TestCase, override_settings
from django.conf import settings
from django.urls import reverse

from . import test_booking_changes as fixtures
from .models import BookingChangeRequest, BookingImage, Payment, SubmissionReceipt


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class BookingChangeReviewTests(TestCase):
    setUp = fixtures.BookingChangeTests.setUp
    data = fixtures.BookingChangeTests.data

    def endpoint(self):
        return reverse('request_booking_change', args=[self.booking.pk])

    def test_pending_edit_baseline_is_owner_checked_and_read_only(self):
        self.booking.status = 'pending'
        self.booking.save()
        url = reverse('edit_booking', args=[self.booking.pk])
        response = self.client.get(url, {'review_original': '1'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['review_original']['fields']['package_type'], 'Package A')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertFalse(BookingChangeRequest.objects.exists())
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url, {'review_original': '1'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 403)

    def original(self):
        return self.client.get(self.endpoint(), HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()['review_original']

    def review(self, **updates):
        return self.client.post(self.endpoint(), self.data(review_only='1', **updates),
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_payment_matrix_matches_existing_quote_policy(self):
        for paid, package, revised, remaining, extra, later, excess in [
            (0, 'Package B', 8000, 8000, 0, 8000, 0),
            (3000, 'Package B', 8000, 5000, 2000, 3000, 0),
            (6000, 'Package B', 8000, 2000, 2000, 0, 0),
            (3000, 'Package A', 6000, 3000, 0, 3000, 0),
            (6000, 'Package A', 6000, 0, 0, 0, 0),
            (3000, 'Package C', 5000, 2000, 0, 2000, 0),
            (6000, 'Package C', 5000, 0, 0, 0, 1000),
        ]:
            with self.subTest(paid=paid, revised=revised):
                self.original_payment.amount = paid
                self.original_payment.save()
                response = self.review(package_type=package)
                self.assertEqual(response.status_code, 200, response.content)
                result = response.json()
                self.assertEqual(Decimal(result['proposed']['total_price']), revised)
                payment = result['payment']
                for key, expected in [('verified_paid', paid), ('remaining', remaining),
                                      ('additional', extra), ('balance_after_additional', later), ('excess', excess)]:
                    self.assertEqual(Decimal(payment[key]), expected, key)

    def test_preview_is_read_only_and_detects_reverted_details(self):
        before = self.original()
        self.assertFalse(self.review().json()['has_changes'])
        self.assertTrue(self.review(motto_text='New message').json()['has_changes'])
        self.assertFalse(self.review(color_palette='Gold, Pink').json()['has_changes'])
        self.assertEqual(self.original(), before)
        self.assertFalse(BookingChangeRequest.objects.exists())
        self.assertFalse(SubmissionReceipt.objects.exists())

    def test_prices_are_saved_and_retained_when_catalog_changes(self):
        self.package.price = 9000
        self.package.save()
        original = self.original()
        self.assertEqual(original['items'][0]['amount'], '5000.00')
        result = self.review(motto_text='New message').json()
        self.assertEqual(Decimal(result['proposed']['total_price']), 6000)
        self.assertEqual(Decimal(result['items'][0]['amount']), 5000)

    def test_missing_saved_prices_does_not_invent_original_unit_prices(self):
        self.booking.fee_policy_snapshot = {}
        self.booking.save()
        original = self.original()
        self.assertFalse(original['item_prices_available'])
        self.assertEqual(original['items'][0]['label'], 'Package A')
        self.assertIsNone(original['items'][0]['amount'])
        self.assertEqual(Decimal(original['fields']['total_price']), 6000)
        result = self.review(motto_text='New message').json()
        self.assertEqual(result['items'], original['items'])

    def test_missing_saved_prices_and_catalog_drift_keeps_same_item_identity(self):
        self.booking.fee_policy_snapshot = {}
        self.booking.save()
        self.package.price = 9999
        self.package.save()
        result = self.review(motto_text='New message').json()
        self.assertEqual(result['items'], self.original()['items'])
        self.assertEqual(Decimal(result['proposed']['total_price']), 6000)

    def test_credit_excludes_unapplied_and_rejected_payments_and_unpaid_checkout(self):
        Payment.objects.create(booking=self.booking, amount=100, payment_method='gcash',
                               payment_status='verified', applied_to_booking=True, transaction_ref='second')
        Payment.objects.create(booking=self.booking, amount=200, payment_method='gcash',
                               payment_status='verified', applied_to_booking=False, transaction_ref='unapplied')
        Payment.objects.create(booking=self.booking, amount=300, payment_method='gcash',
                               payment_status='rejected', transaction_ref='rejected')
        Payment.objects.create(booking=self.booking, amount=400, payment_method='paymongo',
                               payment_status='pending', transaction_ref='unpaid-checkout')
        self.assertEqual(Decimal(self.review(package_type='Package B').json()['payment']['verified_paid']), 6100)

    def test_pending_verification_and_other_customer_cannot_preview(self):
        self.original_payment.payment_status = 'pending'
        self.original_payment.save()
        self.assertEqual(self.review(package_type='Package B').status_code, 400)
        self.client.force_login(self.other)
        self.assertEqual(self.review(package_type='Package B').status_code, 404)
        self.assertEqual(self.client.get(self.endpoint(), HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 404)

    def test_stale_baseline_is_rejected_on_preview_and_submission(self):
        version = self.original()['version']
        self.booking.motto_text = 'Changed by the team'
        self.booking.save()
        for preview in ('1', '0'):
            response = self.client.post(self.endpoint(), self.data(review_only=preview,
                original_version=version, package_type='Package B'), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 400)
            self.assertIn('reopen', response.json()['message'].lower())
        self.assertFalse(BookingChangeRequest.objects.exists())

    def test_image_removals_count_and_change_baseline_version(self):
        version = self.original()['version']
        image = BookingImage.objects.create(booking=self.booking, image='reference.png')
        self.assertNotEqual(self.original()['version'], version)
        result = self.review(**{'remove_images[]': [str(image.pk)]}).json()
        self.assertTrue(result['has_changes'])
        self.assertEqual(self.booking.images.count(), 1)

    def test_preview_keeps_saved_custom_design_images(self):
        from .models import Design
        Design.objects.create(booking=self.booking, image='custom-design.png', style='Custom', color_palette='Pink', price_estimate=5000)
        self.assertEqual(len(self.original()['design_images']), 1)
        self.assertIn('custom-design.png', self.original()['design_images'][0]['url'])

    def test_design_image_changes_reject_a_stale_preview(self):
        from .models import Design
        design = Design.objects.create(booking=self.booking, image='custom-design.png', style='Custom', color_palette='Pink', price_estimate=5000)
        version = self.original()['version']
        design.delete()
        response = self.review(original_version=version, motto_text='New message')
        self.assertEqual(response.status_code, 400)
        self.assertIn('reopen', response.json()['message'].lower())

    def test_overpaid_upgrade_requires_team_explanation(self):
        self.original_payment.amount = 7000
        self.original_payment.save()
        result = self.review(package_type='Package B').json()
        self.assertEqual(Decimal(result['payment']['remaining']), 1000)
        self.assertEqual(Decimal(result['payment']['additional']), 2000)
        self.assertTrue(result['payment_review_required'])

    @override_settings(REQUEST_RATE_LIMITING_ENABLED=True, REQUEST_RATE_LIMITS={
        **settings.REQUEST_RATE_LIMITS, 'booking_change': (1, 600), 'booking_review': (10, 60)})
    def test_review_refresh_does_not_consume_submission_quota(self):
        for _ in range(2):
            response = self.review(package_type='Package B')
            self.assertEqual(response.status_code, 200, response.content)
        response = self.client.post(self.endpoint(), self.data(package_type='Package B'),
                                   HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(BookingChangeRequest.objects.count(), 1)
