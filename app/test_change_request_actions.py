from django.test import TestCase
from django.urls import reverse

from . import test_booking_changes as fixtures
from .models import Payment


class ChangeRequestActionTests(TestCase):
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

    def details(self):
        return self.client.get(reverse('booking_modal_content', args=[self.booking.pk]))

    def test_received_online_payment_hides_pay_and_withdraw_actions(self):
        change = self.upgrade()
        Payment.objects.create(booking=self.booking, change_request=change, applied_to_booking=False,
            amount=2000, payment_type='change_balance', payment_method='paymongo_gcash',
            payment_status='pending', transaction_ref='online-received', received_at=self.now)
        response = self.details()
        self.assertContains(response, 'Payment under review')
        self.assertContains(response, 'Please do not pay again.')
        self.assertContains(response, 'View Payment Status')
        self.assertContains(response, 'Additional payment recorded')
        self.assertNotContains(response, 'Pay Additional')
        self.assertNotContains(response, 'Withdraw request / keep original booking')
        self.assertFalse(response.context['change_can_pay'])
        self.assertFalse(response.context['change_can_withdraw'])

    def test_pending_manual_proof_uses_same_guard(self):
        change = self.upgrade()
        self.proof(change)
        response = self.details()
        self.assertContains(response, 'Payment under review')
        self.assertNotContains(response, 'Pay Additional')
        self.assertNotContains(response, 'Withdraw request / keep original booking')
        self.client.post(reverse('customer_booking_change_action', args=[self.booking.pk, change.pk, 'withdraw']))
        change.refresh_from_db()
        self.assertEqual(change.status, 'awaiting_payment')

    def test_manual_resolution_does_not_promise_automatic_application(self):
        change = self.upgrade()
        self.proof(change)
        change.status = 'manual_review'
        change.save()
        response = self.details()
        self.assertContains(response, 'Our team must resolve this request directly with you.')
        self.assertNotContains(response, 'Your accepted changes will be finalized after verification.')
        self.assertNotContains(response, 'Pay Additional')
        self.assertNotContains(response, 'Withdraw request / keep original booking')

    def test_unpaid_checkout_does_not_falsely_claim_payment_received(self):
        change = self.upgrade()
        Payment.objects.create(booking=self.booking, change_request=change, applied_to_booking=False,
            amount=2000, payment_type='change_balance', payment_method='paymongo_gcash',
            payment_status='pending', transaction_ref='online-unpaid', paymongo_checkout_session_id='cs_unpaid')
        response = self.details()
        self.assertContains(response, 'Pay Additional')
        self.assertContains(response, 'Withdraw request / keep original booking')
        self.assertNotContains(response, 'Please do not pay again.')

    def test_recorded_verified_funds_without_application_never_allow_another_payment(self):
        change = self.upgrade()
        Payment.objects.create(booking=self.booking, change_request=change, applied_to_booking=False,
            amount=2000, payment_type='change_balance', payment_method='gcash',
            payment_status='verified', transaction_ref='recorded-manual')
        response = self.details()
        self.assertNotContains(response, 'Pay Additional')
        self.assertNotContains(response, 'Withdraw request / keep original booking')
        self.assertContains(response, 'Your additional payment is recorded.')
        response = self.client.get(reverse('my_payments'))
        self.assertNotContains(response, 'Pay Additional')

    def test_verified_applied_change_has_no_payment_or_withdraw_actions(self):
        change = self.upgrade()
        self.proof(change)
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_payment_action', args=[change.payments.get().pk, 'verify']))
        self.client.force_login(self.user)
        response = self.details()
        self.assertNotContains(response, 'Pay Additional')
        self.assertNotContains(response, 'Withdraw request / keep original booking')
        self.assertNotContains(response, 'Please do not pay again.')

    def test_rejected_proof_restores_payment_and_withdraw_options(self):
        change = self.upgrade()
        self.proof(change)
        payment = change.payments.get()
        payment.payment_status = 'rejected'
        payment.save()
        response = self.details()
        self.assertContains(response, 'Pay Additional')
        self.assertContains(response, 'Withdraw request / keep original booking')

    def test_reason_is_hidden_payload_instead_of_a_step_five_textarea(self):
        response = self.client.get(reverse('customer_profile'))
        self.assertContains(response, 'type="hidden" id="change_reason" name="change_reason" disabled')
        self.assertNotContains(response, 'id="changeReasonGroup"')
        self.assertNotContains(response, '<textarea id="change_reason"')
        self.assertContains(response, 'id="changeRequestReasonText"')

    def test_reason_validation_still_runs_on_server(self):
        for reason in ('', 'short', 'x' * 2001):
            response = self.client.post(reverse('request_booking_change', args=[self.booking.pk]),
                self.data(package_type='Package B', change_reason=reason), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 400)
        self.assertFalse(self.booking.change_requests.exists())
