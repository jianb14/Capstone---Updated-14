from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from . import test_booking_changes as fixtures
from .models import BookingChangeRequest, Payment


class ChangePaymentOverviewTests(TestCase):
    setUp = fixtures.BookingChangeTests.setUp
    data = fixtures.BookingChangeTests.data
    submit = fixtures.BookingChangeTests.submit
    quote = fixtures.BookingChangeTests.quote
    accept = fixtures.BookingChangeTests.accept
    proof = fixtures.BookingChangeTests.proof

    def accepted_upgrade(self):
        change = self.submit(package_type='Package B')
        self.quote(change)
        self.accept(change)
        return change

    def overview(self, **params):
        self.client.force_login(self.user)
        return self.client.get(reverse('my_payments'), params)

    def test_fully_paid_original_still_shows_accepted_additional_due(self):
        change = self.accepted_upgrade()
        response = self.overview()
        self.assertEqual(response.context['action_required_total_count'], 1)
        self.assertContains(response, 'Pay Additional &#8369;2,000.00')
        self.assertContains(response, 'from <strong>Package A</strong> to <strong>Package B</strong>', html=False)
        self.assertContains(response, reverse('booking_change_payment', args=[self.booking.pk, change.pk]))
        self.assertContains(response, 'Payment deadline')
        self.assertContains(response, 'Your previous verified payments remain credited.')
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.total_price, 6000)
        self.assertEqual(Payment.objects.count(), 1)

    def test_unaccepted_quote_is_not_a_payment_due(self):
        change = self.submit(package_type='Package B')
        self.quote(change)
        response = self.overview()
        self.assertEqual(response.context['action_required_total_count'], 0)
        self.assertNotContains(response, 'Pay Additional')

    def test_proof_shows_under_review_without_pay_button(self):
        change = self.accepted_upgrade()
        self.proof(change)
        response = self.overview()
        self.assertContains(response, 'Payment under review')
        self.assertContains(response, 'Please wait for verification before paying again.')
        self.assertNotContains(response, 'Pay Additional')
        self.assertEqual(response.context['action_required_total_count'], 1)
        payment = next(p for p in response.context['payments_page_obj'] if p.change_request_id)
        self.assertEqual(payment.pending_info_url, reverse('booking_change_payment', args=[self.booking.pk, change.pk]))

    def test_unpaid_checkout_keeps_payment_action_available(self):
        change = self.accepted_upgrade()
        Payment.objects.create(booking=self.booking, change_request=change, applied_to_booking=False,
            amount=2000, payment_method='paymongo_gcash', payment_status='pending',
            transaction_ref='unpaid-checkout', paymongo_checkout_session_id='cs_unpaid',
            paymongo_checkout_url='https://checkout.example/session')
        response = self.overview()
        self.assertContains(response, 'Pay Additional &#8369;2,000.00')
        row = response.context['action_required_page_obj'][0]
        self.assertFalse(row.waiting_for_review)

    def test_original_balance_stays_separate_while_change_payment_reviewed(self):
        self.original_payment.amount = Decimal('1200')
        self.original_payment.save()
        change = self.accepted_upgrade()
        self.proof(change)
        response = self.overview()
        self.assertEqual(response.context['partial_total_count'], 1)
        balance = response.context['partial_page_obj'][0]
        self.assertEqual(balance.booking_remaining, Decimal('4800'))
        self.assertTrue(balance.payment_action_disabled)
        self.assertContains(response, 'original booking balance of <strong>&#8369;4,800.00</strong>')
        self.assertContains(response, 'Change payment under review')

    def test_verification_removes_action_and_credits_payment_once(self):
        change = self.accepted_upgrade()
        self.proof(change)
        payment = change.payments.get()
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_payment_action', args=[payment.pk, 'verify']))
        response = self.overview()
        self.assertEqual(response.context['action_required_total_count'], 0)
        self.assertEqual(response.context['partial_total_count'], 0)
        self.assertNotContains(response, 'Pay Additional')
        payment = next(p for p in response.context['payments_page_obj'] if p.change_request_id)
        self.assertTrue(payment.applied_to_booking)
        self.assertEqual(payment.booking.total_verified_paid, Decimal('8000'))
        self.assertEqual(payment.booking.booking_remaining, 0)

    def test_rejected_proof_allows_retry_and_history_links_to_change_payment(self):
        change = self.accepted_upgrade()
        self.proof(change)
        payment = change.payments.get()
        payment.payment_status = 'rejected'
        payment.save()
        response = self.overview()
        self.assertContains(response, 'Pay Additional &#8369;2,000.00')
        pay = next(p for p in response.context['payments_page_obj'] if p.change_request_id)
        self.assertEqual(pay.pending_info_url, reverse('booking_change_payment', args=[self.booking.pk, change.pk]))

    def test_withdrawn_and_expired_requests_do_not_remain_payable(self):
        change = self.accepted_upgrade()
        self.client.post(reverse('customer_booking_change_action', args=[self.booking.pk, change.pk, 'withdraw']))
        response = self.overview()
        self.assertEqual(response.context['action_required_total_count'], 0)
        change = self.accepted_upgrade()
        change.expires_at = self.now - timedelta(minutes=1)
        change.save()
        response = self.overview()
        change.refresh_from_db()
        self.assertEqual(change.status, 'expired')
        self.assertEqual(response.context['action_required_total_count'], 0)

    def test_manual_review_never_offers_another_payment(self):
        change = self.accepted_upgrade()
        change.status = 'manual_review'
        change.save()
        response = self.overview()
        self.assertContains(response, 'Needs team review')
        self.assertContains(response, 'Please do not submit another payment.')
        self.assertNotContains(response, 'Pay Additional')

    def test_timely_proof_keeps_review_state_after_quote_deadline(self):
        change = self.accepted_upgrade()
        self.proof(change)
        change.expires_at = self.now - timedelta(minutes=1)
        change.save()
        payment = change.payments.get()
        payment.received_at = self.now - timedelta(minutes=2)
        payment.save()
        response = self.overview()
        self.assertContains(response, 'Payment under review')
        self.assertNotContains(response, 'Pay Additional')
        change.refresh_from_db()
        self.assertEqual(change.status, 'awaiting_payment')

    def test_search_filters_both_original_and_change_actions(self):
        change = self.accepted_upgrade()
        response = self.overview(ar_search=str(self.booking.pk))
        self.assertEqual(response.context['action_required_total_count'], 1)
        self.assertEqual(response.context['action_required_page_obj'][0].pk, change.pk)
        response = self.overview(ar_search='No such event')
        self.assertEqual(response.context['action_required_total_count'], 0)

    def test_other_customer_cannot_see_request_or_payments(self):
        change = self.accepted_upgrade()
        self.client.force_login(self.other)
        response = self.client.get(reverse('my_payments'))
        self.assertEqual(response.context['action_required_total_count'], 0)
        self.assertEqual(response.context['total_records'], 0)
        response = self.client.get(reverse('booking_change_payment', args=[self.booking.pk, change.pk]))
        self.assertEqual(response.status_code, 403)

    def test_pagination_counts_change_actions_and_finds_off_page_booking(self):
        for index in range(7):
            booking = fixtures.Booking.objects.get(pk=self.booking.pk)
            booking.pk = None
            booking.save()
            Payment.objects.create(booking=booking, amount=6000, payment_method='gcash',
                payment_status='verified', transaction_ref=f'original-{index}')
            BookingChangeRequest.objects.create(booking=booking, reason='Upgrade',
                status='awaiting_payment', accepted_at=self.now, expires_at=self.now + timedelta(hours=8),
                original_total=6000, quoted_total=8000, additional_due=2000,
                original=fixtures.snapshot(booking), proposed={**fixtures.snapshot(booking), 'package_type':'Package B'})
        response = self.overview(ar_page=2)
        self.assertEqual(response.context['action_required_total_count'], 7)
        self.assertEqual(len(response.context['action_required_page_obj']), 1)
        self.assertEqual(response.context['action_required_page_obj'].number, 2)

    def test_failed_closed_change_checkout_does_not_retry_original_payment(self):
        change = self.accepted_upgrade()
        Payment.objects.create(booking=self.booking, change_request=change, applied_to_booking=False,
            amount=2000, payment_method='paymongo_gcash', payment_status='pending',
            transaction_ref='failed-closed', paymongo_checkout_session_id='cs_closed',
            notes='PayMongo checkout expired')
        change.status = 'expired'
        change.save()
        response = self.overview()
        pay = next(p for p in response.context['payments_page_obj'] if p.change_request_id)
        self.assertFalse(pay.can_retry)
        self.assertNotIn(reverse('payment_page', args=[self.booking.pk]), pay.pending_info_url)
