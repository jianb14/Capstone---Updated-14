"""Payment settings validation, queue pagination and financial-action safeguards."""
from datetime import time, timedelta
from decimal import Decimal

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, Booking, GCashConfig, Notification, Payment, User


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminPaymentWorkspaceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='payment-admin', role='admin')
        self.customer = User.objects.create_user(username='payment-customer', role='customer')
        self.client.force_login(self.admin)
        self.config = GCashConfig.objects.create(downpayment_percent=20, gcash_number='09123456789',
            gcash_name='Existing account', instructions='Keep these instructions.')
        self.url = reverse('admin_gcash_config')
        self.headers = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        self.booking = Booking.objects.create(user=self.customer, event_date=timezone.localdate()+timedelta(days=45),
            event_time=time(10), event_type='Birthday', event_location='Venue', total_price=6000, status='confirmed')

    def test_settings_modal_load_and_valid_save_preserve_other_configuration(self):
        response = self.client.get(self.url, **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn('pmSettingsForm', response.json()['html'])
        result = self.client.post(self.url, {'downpayment_percent': '35'}, **self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()['ok'])
        self.config.refresh_from_db()
        self.assertEqual(self.config.downpayment_percent, Decimal('35'))
        self.assertEqual(self.config.gcash_number, '09123456789')
        self.assertEqual(self.config.gcash_name, 'Existing account')
        self.assertEqual(self.config.instructions, 'Keep these instructions.')
        self.assertEqual(Payment.objects.count(), 0)
        self.assertTrue(AuditLog.objects.filter(user=self.admin, action='Updated GCash configuration.').exists())

    def test_invalid_settings_are_not_saved_or_reported_as_success(self):
        for value in ('', '0', '-1', '101', '20.5', 'invalid'):
            with self.subTest(value=value):
                response = self.client.post(self.url, {'downpayment_percent': value}, **self.headers)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()['ok'])
                self.assertIn('aria-invalid="true"', response.json()['html'])
                self.config.refresh_from_db()
                self.assertEqual(self.config.downpayment_percent, Decimal('20'))
        self.assertFalse(AuditLog.objects.filter(action='Updated GCash configuration.').exists())
        response = self.client.post(self.url, {'downpayment_percent': '101'})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'pmPercentError', status_code=400)

    def test_settings_require_admin_and_csrf(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(self.url, **self.headers).status_code, 403)
        self.assertEqual(self.client.post(self.url, {'downpayment_percent': '40'}, **self.headers).status_code, 403)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(csrf_client.post(self.url, {'downpayment_percent': '40'}, **self.headers).status_code, 403)
        self.config.refresh_from_db()
        self.assertEqual(self.config.downpayment_percent, Decimal('20'))

    def test_queue_page_size_is_bounded_and_empty_search_has_no_table(self):
        Payment.objects.bulk_create([Payment(booking=self.booking, amount=100, payment_method='gcash',
            payment_type='downpayment', payment_status='pending', transaction_ref=f'proof-{i}') for i in range(11)])
        url = reverse('admin_payment_list')
        for requested, expected in (('', 8), ('4', 4), ('8', 8), ('100000', 8), ('bad', 8)):
            with self.subTest(size=requested):
                response = self.client.get(url, {'per_page': requested})
                self.assertEqual(len(response.context['pending_payments']), expected)
                self.assertEqual(response.context['pending_count'], 11)
        response = self.client.get(url, {'per_page': '4', 'pending_page': '2', 'search': 'not-found'})
        self.assertEqual(response.context['pending_payments'].number, 2)
        self.assertEqual(len(response.context['pending_payments']), 4)
        html = response.content.decode().split('id="pmSection-history"', 1)[1].split('</section>', 1)[0]
        self.assertIn('No matching payments', html)
        self.assertNotIn('<thead', html)
        self.assertNotIn('account-table-footer', html)

    def test_reject_validation_and_duplicate_approval_do_not_change_payment(self):
        payment = Payment.objects.create(booking=self.booking, amount=1000, payment_method='gcash',
            payment_type='downpayment', payment_status='pending')
        reject = reverse('admin_payment_action', args=[payment.pk, 'reject'])+'?next=payments'
        for reason in ('   ', 'x'*2001):
            self.client.post(reject, {'admin_notes': reason})
            payment.refresh_from_db()
            self.assertEqual(payment.payment_status, 'pending')
        self.client.post(reverse('admin_payment_action', args=[payment.pk, 'verify']), {})
        payment.refresh_from_db()
        verified_at = payment.paid_at
        notifications = Notification.objects.filter(booking=self.booking).count()
        self.client.post(reject, {'admin_notes': 'Stale action'})
        payment.refresh_from_db()
        self.assertEqual(payment.payment_status, 'verified')
        self.assertEqual(payment.paid_at, verified_at)
        self.assertEqual(Notification.objects.filter(booking=self.booking).count(), notifications)

    def test_progress_is_capped_for_overpayment_and_zero_total(self):
        payment = Payment.objects.create(booking=self.booking, amount=7000, payment_method='gcash',
            payment_type='full', payment_status='verified')
        url = reverse('admin_payment_detail', args=[payment.pk])
        self.assertEqual(self.client.get(url).context['paid_percentage'], 100)
        self.booking.total_price = 0
        self.booking.save(update_fields=['total_price'])
        self.assertEqual(self.client.get(url).context['paid_percentage'], 0)
