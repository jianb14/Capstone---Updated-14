"""Entry checks must agree with submission rules without changing the booking."""
from datetime import date, time
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Booking, BookingChangeRequest, Package, Payment, ServiceChargeConfig, SiteSettings, User


def feedback_booking():
    user = User.objects.create_user(username='feedback-customer', role='customer', email_verified=True)
    SiteSettings.load()
    ServiceChargeConfig.objects.create(pk=1, amount=1000, shop_lat=14.414, shop_lng=120.982, per_km_rate=30)
    Package.objects.create(name='Package 1-A', price=7000)
    Package.objects.create(name='Package 2', price=9000)
    booking = Booking.objects.create(user=user, event_date=date(2099, 7, 15), event_time=time(7),
        event_end_time=time(10), event_end_date=date(2099, 7, 15), duration_minutes=180,
        event_type='Birthday', event_location='Molino Bacoor Cavite venue', event_lat='14.414000',
        event_lng='120.982000', package_type='Package 2', total_price=10000, logistics_fee=1000,
        design_theme='Princess', color_palette='Pink, Gold', motto_text='Happy Birthday', status='confirmed')
    from .views.common import capture_booking_fee_policy
    capture_booking_fee_policy(booking)
    booking.save()
    payment = Payment.objects.create(booking=booking, amount=10000, payment_method='gcash',
        payment_status='verified', received_at=timezone.now(), transaction_ref='feedback-payment')
    return user, booking, payment


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class BookingChangeFeedbackTests(TestCase):
    def setUp(self):
        self.user, self.booking, self.payment = feedback_booking()
        self.client.force_login(self.user)
        self.url = reverse('request_booking_change', args=[self.booking.pk])

    def preflight(self):
        response = self.client.get(self.url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        return response.json()

    def test_verified_full_payment_can_open_changes_with_fresh_totals(self):
        state = self.preflight()
        self.assertTrue(state['can_request_changes'])
        self.assertEqual(Decimal(state['verified_paid']), Decimal('10000'))
        self.assertEqual(Decimal(state['original_total']), Decimal('10000'))
        self.assertFalse(BookingChangeRequest.objects.exists())
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.package_type, 'Package 2')

    def test_verified_partial_payment_remains_eligible(self):
        self.payment.amount = 5000
        self.payment.save()
        state = self.preflight()
        self.assertTrue(state['can_request_changes'])
        self.assertEqual(Decimal(state['verified_paid']), Decimal('5000'))

    def test_pending_received_payment_blocks_entry_and_updates_after_verification(self):
        self.payment.payment_status = 'pending'
        self.payment.save()
        state = self.preflight()
        self.assertFalse(state['can_request_changes'])
        self.assertEqual(state['message'], 'Your payment is still being verified. You can request booking changes once verification is complete.')
        self.payment.payment_status = 'verified'
        self.payment.save()
        self.assertTrue(self.preflight()['can_request_changes'])

    def test_unpaid_provider_checkout_does_not_block_changes(self):
        self.payment.delete()
        Payment.objects.create(booking=self.booking, amount=10000, payment_method='paymongo',
            payment_status='pending', transaction_ref='unpaid-checkout')
        self.assertTrue(self.preflight()['can_request_changes'])

    def test_received_provider_payment_blocks_changes(self):
        self.payment.payment_method = 'paymongo'
        self.payment.payment_status = 'pending'
        self.payment.save()
        self.assertFalse(self.preflight()['can_request_changes'])

    def test_pending_proof_is_checked_even_after_verified_payment(self):
        Payment.objects.create(booking=self.booking, amount=100, payment_method='gcash', payment_status='pending')
        self.assertFalse(self.preflight()['can_request_changes'])

    def test_cutoff_and_active_request_still_block_entry(self):
        self.booking.event_date = timezone.localdate()
        self.booking.save()
        self.assertFalse(self.preflight()['can_request_changes'])
        self.booking.event_date = date(2099, 7, 15)
        self.booking.save()
        BookingChangeRequest.objects.create(booking=self.booking, reason='Existing request',
            original={}, proposed={}, original_total=10000, quoted_total=8000)
        self.assertFalse(self.preflight()['can_request_changes'])

    def test_other_customer_cannot_read_payment_state(self):
        other = User.objects.create_user(username='feedback-other', role='customer')
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url, HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 404)

    def test_payment_submitted_after_entry_is_still_blocked_at_submission(self):
        self.assertTrue(self.preflight()['can_request_changes'])
        self.payment.payment_status = 'pending'
        self.payment.save()
        response = self.client.post(self.url, {'change_reason': 'We need a different package.'},
                                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertIn('verification is complete', response.json()['message'])
        self.assertFalse(BookingChangeRequest.objects.exists())

    def test_regular_get_redirects_without_opening_blocked_wizard(self):
        self.payment.payment_status = 'pending'
        self.payment.save()
        self.assertRedirects(self.client.get(self.url), reverse('customer_profile'))
