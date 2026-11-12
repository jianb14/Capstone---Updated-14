from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from . import test_booking_changes as fixtures
from .models import Payment


@override_settings(PAYMONGO_SECRET_KEY='sk_test_checkout')
class SharedChangeCheckoutTests(TestCase):
    setUp = fixtures.BookingChangeTests.setUp
    data = fixtures.BookingChangeTests.data
    submit = fixtures.BookingChangeTests.submit
    quote = fixtures.BookingChangeTests.quote
    accept = fixtures.BookingChangeTests.accept
    proof = fixtures.BookingChangeTests.proof

    def upgrade(self):
        change = self.submit(package_type='Package B')
        self.quote(change)
        self.accept(change)
        return change

    def page(self, change):
        return self.client.get(reverse('booking_change_payment', args=[self.booking.pk, change.pk]))

    def test_additional_payment_uses_existing_checkout_template_and_steps(self):
        change = self.upgrade()
        response = self.page(change)
        self.assertTemplateUsed(response, 'client/payment_upload.html')
        self.assertContains(response, 'Select Payment Option')
        self.assertContains(response, 'Review Your Payment')
        self.assertContains(response, 'Submit Payment Proof')
        self.assertContains(response, 'Submit GCash payment proof')
        self.assertContains(response, 'GCash QR')
        self.assertContains(response, 'Additional payment only')
        self.assertContains(response, 'Requested Booking Details')
        self.assertContains(response, 'Package B')
        self.assertContains(response, '7:00 AM')
        self.assertContains(response, 'Revised Booking Total')
        self.assertContains(response, 'Previous Verified Payments')
        self.assertContains(response, 'id="js-refund-ack"')
        self.assertContains(response, 'id="js-checkout-btn" type="submit" disabled')
        self.assertContains(response, f'action="{reverse("booking_change_payment", args=[self.booking.pk, change.pk])}"')
        self.assertNotContains(response, 'Pay Downpayment')
        self.assertContains(response, 'name="receipt_image"')
        self.assertContains(response, 'gcash_sender_name')

    @patch('app.views.changes.create_paymongo_checkout_session')
    def test_shared_form_charges_saved_difference_and_never_starts_provider(self, checkout):
        change = self.upgrade()
        self.proof(change, amount='1', payment_option='downpayment')
        payment = change.payments.get()
        self.assertEqual(payment.amount, Decimal('2000'))
        self.assertFalse(payment.applied_to_booking)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.total_price, 6000)
        checkout.assert_not_called()

    @patch('app.views.changes.create_paymongo_checkout_session')
    def test_terms_required_even_for_forged_form_submission(self, checkout):
        change = self.upgrade()
        response = self.proof(change, refund_ack='')
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Acknowledge the payment terms', status_code=400)
        self.assertContains(response, 'Submit GCash payment proof', status_code=400)
        checkout.assert_not_called()

    def test_pending_payment_uses_shared_status_screen_without_checkout(self):
        change = self.upgrade()
        self.proof(change)
        response = self.page(change)
        self.assertTemplateUsed(response, 'client/payment_upload.html')
        self.assertContains(response, 'Awaiting Verification')
        self.assertContains(response, 'Booking changes finalized')
        self.assertContains(response, 'Additional Payment Submitted')
        self.assertNotContains(response, 'Submit GCash payment proof')
        self.assertNotContains(response, 'This booking is fully paid')

    def test_original_balance_is_separate_from_change_checkout_and_history(self):
        self.original_payment.amount = 1200
        self.original_payment.save()
        change = self.upgrade()
        response = self.page(change)
        self.assertEqual(response.context['remaining_balance'], 2000)
        self.assertContains(response, 'original unpaid balance')
        self.assertContains(response, '4,800.00')
        self.assertEqual(len(response.context['payment_history']), 0)
        self.proof(change)
        response = self.client.get(reverse('payment_page', args=[self.booking.pk]))
        self.assertIsNone(response.context['pending_payment'])
        self.assertEqual(response.context['remaining_balance'], 4800)
        self.assertEqual(list(response.context['payment_history']), [self.original_payment])
        response = self.client.get(reverse('payment_success', args=[self.booking.pk]))
        self.assertIsNone(response.context['pending_payment'])
        self.assertEqual(list(response.context['payment_history']), [self.original_payment])

    @patch('app.views.changes.create_paymongo_checkout_session')
    def test_existing_checkout_needs_review_without_new_payment_record(self, checkout):
        change = self.upgrade()
        Payment.objects.create(booking=self.booking, change_request=change, applied_to_booking=False,
            amount=2000, payment_type='change_balance', payment_status='pending', payment_method='paymongo_gcash',
            transaction_ref='continue', paymongo_checkout_session_id='cs_continue', paymongo_checkout_url='https://checkout.paymongo.com/continue')
        response = self.page(change)
        self.assertContains(response, 'previous checkout')
        self.assertNotContains(response, 'name="receipt_image"')
        response = self.client.post(reverse('booking_change_payment', args=[self.booking.pk, change.pk]), {'method':'paymongo', 'refund_ack':'1'})
        self.assertEqual(response.status_code, 400)
        checkout.assert_not_called()
        self.assertEqual(change.payments.count(), 1)

    @override_settings(PAYMONGO_SECRET_KEY='')
    def test_configured_qr_works_without_provider_credentials(self):
        change = self.upgrade()
        response = self.page(change)
        self.assertNotContains(response, 'Payment Unavailable')
        self.assertContains(response, 'Submit GCash payment proof')

    def test_expired_and_unaccepted_quotes_cannot_show_checkout(self):
        change = self.submit(package_type='Package B')
        self.quote(change)
        self.client.force_login(self.user)
        response = self.page(change)
        self.assertContains(response, 'Payment Unavailable')
        self.assertNotContains(response, 'Submit GCash payment proof')
        self.accept(change)
        change.expires_at = self.now - timedelta(minutes=1)
        change.save()
        response = self.page(change)
        self.assertContains(response, 'Payment Unavailable')
        self.assertNotContains(response, 'Submit GCash payment proof')

    def test_original_checkout_keeps_initial_options_and_balance_mode(self):
        self.original_payment.delete()
        self.booking.status = 'pending_payment'
        self.booking.payment_due_at = self.now + timedelta(hours=24)
        self.booking.save()
        response = self.client.get(reverse('payment_page', args=[self.booking.pk]))
        self.assertContains(response, 'Pay Full Amount')
        self.assertContains(response, 'Pay Downpayment')
        self.assertContains(response, reverse('submit_payment', args=[self.booking.pk]))
        Payment.objects.create(booking=self.booking, amount=1200, payment_method='gcash', payment_status='verified', transaction_ref='deposit')
        response = self.client.get(reverse('payment_page', args=[self.booking.pk]))
        self.assertContains(response, 'Balance payment only')
        self.assertNotContains(response, 'Pay Downpayment')

    @patch('app.views.payments.retrieve_paymongo_checkout_session', return_value=None)
    def test_processing_provider_return_stays_in_the_change_checkout(self, retrieve):
        change = self.upgrade()
        Payment.objects.create(booking=self.booking, change_request=change, applied_to_booking=False,
            amount=2000, payment_type='change_balance', payment_status='pending', payment_method='paymongo_gcash',
            transaction_ref='provider-processing', paymongo_checkout_session_id='cs_processing')
        response = self.client.get(reverse('paymongo_success', args=[self.booking.pk]), {'change_request':change.pk})
        self.assertEqual(response.url, reverse('booking_change_payment', args=[self.booking.pk, change.pk]))
