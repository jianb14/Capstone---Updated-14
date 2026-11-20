from datetime import time, timedelta
from unittest.mock import patch

from django.core import mail
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .booking_lifecycle import process_booking, set_approval_deadlines
from .models import Booking, BookingStatusLog, GCashConfig, Notification, Payment, ServiceChargeConfig, SiteSettings, User
from .test_booking_design_step import _base_payload
from .views.common import log_booking_status


@override_settings(BOOKING_EMAIL_BASE_URL='https://balloorina.example')
class BookingStatusEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='email-customer', email='customer@example.com')
        self.booking = Booking.objects.create(user=self.user,
            event_date=timezone.localdate() + timedelta(days=5), event_time=time(15),
            event_location='Bacoor', event_type='Birthday', total_price=6000)

    def transition(self, old, new, notes=''):
        self.booking.status = new
        self.booking.save()
        return log_booking_status(self.booking, old, new, notes=notes)

    def test_submission_and_all_customer_statuses_send_to_customer(self):
        for old, new, label in [('', 'pending', 'Submitted'),
                ('pending', 'pending_payment', 'Pending Payment'),
                ('pending_payment', 'confirmed', 'Confirmed'),
                ('confirmed', 'cancelled', 'Cancelled'),
                ('pending', 'expired', 'Expired'),
                ('confirmed', 'completed', 'Completed')]:
            with self.subTest(status=new), self.captureOnCommitCallbacks(execute=True):
                self.transition(old, new)
            message = mail.outbox[-1]
            self.assertEqual(message.to, ['customer@example.com'])
            self.assertIn(label, message.subject)
            self.assertIn(f'Booking #{self.booking.pk}', message.body)
            self.assertIn(str(self.booking.event_date), message.body)
            self.assertIn('15:00', message.body)
            self.assertIn(f'https://balloorina.example/booking/{self.booking.pk}/', message.body)
        self.assertEqual(len(mail.outbox), 6)

    def test_approval_includes_actual_downpayment_and_local_deadline(self):
        GCashConfig.objects.create(downpayment_percent=30)
        set_approval_deadlines(self.booking)
        with self.captureOnCommitCallbacks(execute=True):
            self.transition('pending', 'pending_payment')
        self.assertIn('PHP 1,800.00', mail.outbox[0].body)
        deadline = timezone.localtime(self.booking.payment_due_at)
        self.assertIn(deadline.strftime('%Y-%m-%d %H:%M'), mail.outbox[0].body)

    def test_denial_includes_customer_facing_reason(self):
        self.booking.admin_denial_reason = 'The venue is outside our service area.'
        with self.captureOnCommitCallbacks(execute=True):
            self.transition('pending', 'cancelled', 'Denied by admin.')
        self.assertIn(self.booking.admin_denial_reason, mail.outbox[0].body)

    def test_expiration_worker_sends_reason_once(self):
        self.booking.event_date = timezone.localdate() - timedelta(days=1)
        self.booking.save()
        with self.captureOnCommitCallbacks(execute=True):
            process_booking(self.booking.pk)
            process_booking(self.booking.pk)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('event start time passed', mail.outbox[0].body)

    def test_history_only_entries_and_resaving_log_do_not_duplicate(self):
        with self.captureOnCommitCallbacks(execute=True):
            entry = self.transition('pending_payment', 'confirmed')
            entry.save()
            log_booking_status(self.booking, 'confirmed', 'confirmed', notes='Design sent.')
        self.assertEqual(len(mail.outbox), 1)

    def test_rollback_never_sends(self):
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError), transaction.atomic():
                self.transition('pending', 'cancelled')
                raise RuntimeError('rollback')
        self.assertEqual(len(mail.outbox), 0)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending')

    def test_each_email_keeps_its_status_snapshot_until_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.transition('pending', 'pending_payment')
            self.transition('pending_payment', 'confirmed')
            self.assertEqual(len(mail.outbox), 0)
        self.assertIn('Pending Payment', mail.outbox[0].subject)
        self.assertIn('Confirmed', mail.outbox[1].subject)

    def test_provider_failure_does_not_undo_status_or_history(self):
        with patch('django.core.mail.message.EmailMessage.send', side_effect=RuntimeError('offline')):
            with self.captureOnCommitCallbacks(execute=True):
                self.transition('pending', 'cancelled')
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'cancelled')
        self.assertTrue(BookingStatusLog.objects.filter(booking=self.booking, new_status='cancelled').exists())

    def test_missing_email_is_skipped(self):
        self.user.email = ''
        self.user.save()
        with self.captureOnCommitCallbacks(execute=True):
            self.transition('pending', 'cancelled')
        self.assertEqual(len(mail.outbox), 0)

    def test_real_submission_emails_customer_with_admin_alerts_disabled(self):
        site = SiteSettings.load()
        site.email_notifications_enabled = False
        site.save()
        ServiceChargeConfig.objects.create(pk=1, shop_lat='14.414', shop_lng='120.982')
        self.user.role = 'customer'
        self.user.email_verified = True
        self.user.save()
        self.client.force_login(self.user)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('create_booking'), _base_payload(),
                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'], response.content)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Submitted', mail.outbox[0].subject)

    def test_real_approval_repeated_request_only_sends_once(self):
        admin = User.objects.create_user(username='email-admin', role='admin', email_verified=True)
        self.client.force_login(admin)
        with self.captureOnCommitCallbacks(execute=True):
            for _ in range(2):
                self.client.get(reverse('admin_booking_action', args=[self.booking.pk, 'approve']))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Pending Payment', mail.outbox[0].subject)
        self.assertTrue(Notification.objects.filter(booking=self.booking, user=self.user).exists())

    def test_payment_verification_confirms_and_emails_once(self):
        admin = User.objects.create_user(username='payment-admin', role='admin', email_verified=True)
        self.booking.status = 'pending_payment'
        set_approval_deadlines(self.booking)
        self.booking.save()
        payment = Payment.objects.create(booking=self.booking, amount=1200,
            payment_method='gcash', payment_status='pending', transaction_ref='status-mail-payment')
        self.client.force_login(admin)
        with self.captureOnCommitCallbacks(execute=True):
            for _ in range(2):
                self.client.post(reverse('admin_payment_action', args=[payment.pk, 'verify']))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Confirmed', mail.outbox[0].subject)

    @override_settings(BOOKING_EMAIL_BASE_URL='', CSRF_TRUSTED_ORIGINS=['https://*.vercel.app'],
                       ALLOWED_HOSTS=['*', 'localhost', 'book.balloorina.example'])
    def test_worker_link_uses_concrete_public_host_when_origin_is_unset(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.transition('pending', 'cancelled')
        self.assertIn('https://book.balloorina.example/booking/', mail.outbox[0].body)

    @override_settings(BOOKING_EMAIL_BASE_URL='',
                       CSRF_TRUSTED_ORIGINS=['http://localhost:8000', 'https://public.example'])
    def test_worker_skips_localhost_trusted_origin(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.transition('pending', 'cancelled')
        self.assertIn('https://public.example/booking/', mail.outbox[0].body)

    @override_settings(BOOKING_EMAIL_BASE_URL='', CSRF_TRUSTED_ORIGINS=[],
                       ALLOWED_HOSTS=['localhost:8000', '127.0.0.1:8000', 'public.example'])
    def test_worker_skips_localhost_allowed_host_with_port(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.transition('pending', 'cancelled')
        self.assertIn('https://public.example/booking/', mail.outbox[0].body)

    @override_settings(BOOKING_EMAIL_BASE_URL='', CSRF_TRUSTED_ORIGINS=[], ALLOWED_HOSTS=['*', 'localhost'])
    def test_no_public_origin_skips_email_without_breaking_update(self):
        with self.captureOnCommitCallbacks(execute=True), self.assertLogs('app.booking_status_email', level='WARNING'):
            self.transition('pending', 'cancelled')
        self.assertEqual(len(mail.outbox), 0)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'cancelled')

    def test_provider_zero_result_is_logged_without_undoing_status(self):
        with patch('django.core.mail.message.EmailMessage.send', return_value=0):
            with self.assertLogs('app.booking_status_email', level='WARNING'), self.captureOnCommitCallbacks(execute=True):
                self.transition('pending', 'cancelled')
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'cancelled')
