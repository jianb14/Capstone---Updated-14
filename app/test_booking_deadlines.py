import io
import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .booking_lifecycle import event_start_at, lifecycle_display, process_booking, process_booking_deadlines, set_approval_deadlines
from .models import AdminNotification, Booking, BookingDeadlineNotice, BookingDesignDelivery, Notification, Package, Payment, ServiceChargeConfig, SiteSettings, User


class BookingDeadlineTests(TestCase):
    def setUp(self):
        self.now = timezone.make_aware(datetime(2035, 1, 21, 10))
        timer = patch('django.utils.timezone.now', return_value=self.now)
        timer.start()
        self.addCleanup(timer.stop)
        self.user = User.objects.create_user(username='deadline-customer', role='customer')
        self.admin = User.objects.create_user(username='deadline-admin', role='admin')
        self.site = SiteSettings.load()
        self.site.booking_payment_window_hours = 24
        self.site.booking_design_lead_hours = 24
        self.site.save()
        Package.objects.create(name='Birthday Package', price=5000)
        ServiceChargeConfig.objects.create(pk=1, amount=1000)
        self.booking = Booking.objects.create(user=self.user, event_date=self.now.date() + timedelta(days=2),
            event_time=time(15), event_type='Birthday', event_location='Bacoor', package_type='Birthday Package',
            total_price=6000, logistics_fee=1000)

    def payment(self, **extra):
        values = dict(booking=self.booking, amount=1200, payment_method='gcash', payment_status='pending',
            transaction_ref=f'deadline-payment-{Payment.objects.count()}')
        values.update(extra)
        return Payment.objects.create(**values)

    def approve(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_booking_action', args=[self.booking.pk, 'approve']))
        self.booking.refresh_from_db()
        return response

    def test_pending_expires_at_event_start_not_midnight_or_next_day(self):
        self.booking.event_date = self.now.date()
        self.booking.save()
        process_booking(self.booking.pk, self.now.replace(hour=0))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending')
        process_booking(self.booking.pk, self.now.replace(hour=14, minute=59, second=59))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending')
        for _ in range(2):
            process_booking(self.booking.pk, self.now.replace(hour=15))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'expired')
        self.assertEqual(Notification.objects.filter(booking=self.booking).count(), 1)
        self.assertEqual(self.booking.status_logs.filter(new_status='expired').count(), 1)

    def test_unknown_legacy_time_keeps_booking_through_that_date(self):
        self.booking.event_date, self.booking.event_time = self.now.date(), None
        self.booking.save()
        process_booking(self.booking.pk, self.now.replace(hour=23, minute=59))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending')
        process_booking(self.booking.pk, self.now + timedelta(days=1))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'expired')

    def test_approval_saves_exact_24_hour_deadline_and_notifies_customer(self):
        self.approve()
        self.assertEqual(self.booking.status, 'pending_payment')
        self.assertEqual(self.booking.approved_at, self.now)
        self.assertEqual(self.booking.payment_due_at, self.now + timedelta(hours=24))
        self.assertEqual(self.booking.design_due_at, event_start_at(self.booking) - timedelta(hours=24))
        self.assertTrue(Notification.objects.filter(booking=self.booking, message__contains='Jan 22, 2035 at 10:00 AM').exists())

    def test_approval_window_cannot_extend_beyond_event_start(self):
        self.booking.event_date = self.now.date()
        self.booking.save()
        self.approve()
        self.assertEqual(self.booking.payment_due_at, self.now.replace(hour=15))
        process_booking(self.booking.pk, self.now.replace(hour=0) + timedelta(days=0))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending_payment')

    def test_cannot_approve_event_that_already_started(self):
        self.booking.event_date, self.booking.event_time = self.now.date(), time(9)
        self.booking.save()
        self.approve()
        self.assertEqual(self.booking.status, 'expired')
        self.assertIsNone(self.booking.approved_at)

    def test_legacy_payment_record_cannot_bypass_past_event_approval_guard(self):
        self.booking.event_date, self.booking.event_time = self.now.date(), time(9)
        self.booking.save()
        self.payment(payment_status='verified')
        self.approve()
        self.assertEqual(self.booking.status, 'pending')
        self.assertIsNone(self.booking.approved_at)

    def test_no_payment_at_saved_deadline_expires_and_releases_slot(self):
        self.approve()
        process_booking(self.booking.pk, self.booking.payment_due_at - timedelta(seconds=1))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending_payment')
        process_booking(self.booking.pk, self.booking.payment_due_at)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'expired')

    def test_saved_deadline_does_not_move_when_admin_changes_settings(self):
        self.approve()
        original = self.booking.payment_due_at
        self.site.booking_payment_window_hours = 48
        self.site.save()
        process_booking(self.booking.pk, self.now)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.payment_due_at, original)

    def test_submitted_manual_proof_protects_booking_and_alerts_review_once(self):
        self.approve()
        self.payment(received_at=self.now)
        future = event_start_at(self.booking) + timedelta(days=1)
        for _ in range(2):
            process_booking(self.booking.pk, future)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending_payment')
        self.assertTrue(lifecycle_display(self.booking, future)['awaiting_verification'])
        self.assertEqual(AdminNotification.objects.filter(message__startswith='Urgent payment verification:').count(), 1)

    def test_rejected_proof_no_longer_blocks_expiration(self):
        self.approve()
        self.payment(payment_status='rejected')
        process_booking(self.booking.pk, self.booking.payment_due_at)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'expired')

    def test_unpaid_paymongo_checkout_does_not_count_as_payment(self):
        self.approve()
        self.payment(payment_method='paymongo_gcash', paymongo_checkout_session_id='cs_unpaid')
        process_booking(self.booking.pk, self.booking.payment_due_at)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'expired')

    def test_paid_provider_payment_waiting_verification_is_protected(self):
        self.approve()
        self.payment(payment_method='paymongo_gcash', paymongo_payment_id='pay_received', received_at=self.now)
        process_booking(self.booking.pk, self.booking.payment_due_at + timedelta(hours=1))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending_payment')

    def test_verified_booking_never_expires_for_a_missing_design(self):
        self.booking.status = 'confirmed'
        self.booking.save()
        self.payment(payment_status='verified')
        process_booking(self.booking.pk, event_start_at(self.booking) + timedelta(days=3))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')
        self.assertEqual(AdminNotification.objects.filter(message__startswith='Urgent: Booking').count(), 1)

    def test_missing_design_warning_starts_exactly_24_hours_before_event(self):
        self.booking.status = 'confirmed'
        self.booking.save()
        start = event_start_at(self.booking)
        process_booking(self.booking.pk, start - timedelta(hours=24, seconds=1))
        self.assertFalse(BookingDeadlineNotice.objects.exists())
        for _ in range(2):
            process_booking(self.booking.pk, start - timedelta(hours=24))
        self.assertEqual(BookingDeadlineNotice.objects.filter(key='design-overdue').count(), 1)

    def test_delivered_design_suppresses_missing_design_warning(self):
        self.booking.status = 'confirmed'
        self.booking.save()
        BookingDesignDelivery.objects.create(booking=self.booking, image='design.png')
        process_booking(self.booking.pk, event_start_at(self.booking))
        self.assertFalse(BookingDeadlineNotice.objects.filter(key='design-overdue').exists())
        self.assertTrue(lifecycle_display(self.booking)['design_ready'])

    def test_late_payment_verification_records_money_without_reopening_expired_booking(self):
        self.booking.status = 'expired'
        self.booking.save()
        payment = self.payment()
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_payment_action', args=[payment.pk, 'verify']))
        payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(payment.payment_status, 'verified')
        self.assertEqual(self.booking.status, 'expired')
        self.assertTrue(BookingDeadlineNotice.objects.filter(key=f'late-payment-{payment.pk}').exists())

    def test_rejection_does_not_reopen_cancelled_booking(self):
        self.booking.status = 'cancelled'
        self.booking.save()
        payment = self.payment()
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_payment_action', args=[payment.pk, 'reject']), {'admin_notes': 'Invalid proof'})
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'cancelled')

    def test_unpaid_manual_confirmation_is_blocked(self):
        self.approve()
        self.client.get(reverse('admin_booking_action', args=[self.booking.pk, 'confirm']))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending_payment')

    def test_direct_payment_submission_after_deadline_is_rejected(self):
        self.approve()
        self.booking.payment_due_at = self.now - timedelta(minutes=1)
        self.booking.save()
        self.client.force_login(self.user)
        self.client.post(reverse('submit_payment', args=[self.booking.pk]), {'gcash_ref_number': '1234567890123',
            'sender_name': 'Customer', 'amount': '6000', 'payment_option': 'full', 'refund_ack': 'on'})
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'expired')
        self.assertFalse(self.booking.payments.exists())

    def test_late_provider_webhook_records_receipt_and_raises_one_alert(self):
        self.booking.status = 'expired'
        self.booking.save()
        payment = self.payment(payment_method='paymongo_gcash', paymongo_checkout_session_id='cs_late')
        payload = {'data': {'attributes': {'type': 'checkout_session.payment.paid', 'data': {'id': 'cs_late', 'attributes': {}}}}}
        with patch('app.views.payments.verify_paymongo_webhook_signature', return_value=True):
            for _ in range(2):
                response = self.client.post(reverse('paymongo_webhook'), data=json.dumps(payload), content_type='application/json')
                self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(payment.received_at, self.now)
        self.assertEqual(self.booking.status, 'expired')
        self.assertEqual(BookingDeadlineNotice.objects.filter(key=f'late-receipt-{payment.pk}').count(), 1)

    def test_legacy_approved_booking_receives_visible_grace_window(self):
        self.booking.status = 'pending_payment'
        self.booking.save()
        process_booking(self.booking.pk, self.now)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.payment_due_at, self.now + timedelta(hours=24))

    def test_customer_and_admin_show_deadlines_and_design_status(self):
        self.approve()
        self.client.force_login(self.user)
        response = self.client.get(reverse('booking_modal_content', args=[self.booking.pk]))
        self.assertContains(response, 'Pay by Jan 22, 2035')
        self.payment()
        response = self.client.get(reverse('booking_modal_content', args=[self.booking.pk]))
        self.assertContains(response, 'awaiting admin verification')
        self.assertContains(response, 'Our team is verifying it.')
        self.booking.status, self.booking.design_due_at = 'confirmed', self.now
        self.booking.save()
        response = self.client.get(reverse('booking_modal_content', args=[self.booking.pk]))
        self.assertContains(response, 'Design in preparation')
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_booking_detail', args=[self.booking.pk]))
        self.assertContains(response, 'Urgent — event design is overdue')

    def test_management_command_processes_deadlines_without_a_page_visit(self):
        self.booking.event_date = self.now.date() - timedelta(days=1)
        self.booking.save()
        output = io.StringIO()
        call_command('process_booking_deadlines', stdout=output)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'expired')
        self.assertIn('1 booking(s) expired', output.getvalue())

    def test_deadline_settings_are_editable_without_rewriting_existing_deadlines(self):
        self.approve()
        original = self.booking.payment_due_at
        self.client.post(reverse('admin_site_settings'), {'site_name': 'Balloorina',
            'booking_payment_window_hours': '48', 'booking_design_lead_hours': '48'})
        self.site.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.site.booking_payment_window_hours, 48)
        self.assertEqual(self.site.booking_design_lead_hours, 48)
        self.assertEqual(self.booking.payment_due_at, original)


class BackgroundDeadlineTests(TransactionTestCase):
    def setUp(self):
        user = User.objects.create_user(username='deadline-background', role='customer')
        self.booking = Booking.objects.create(user=user, event_date=timezone.localdate() - timedelta(days=1),
            event_time=time(15), event_type='Birthday', event_location='Bacoor', total_price=6000)

    def test_real_worker_expires_booking_without_http_traffic(self):
        import time as clock
        from . import deadline_worker
        deadline_worker.start_deadline_worker()
        try:
            stop_at = clock.monotonic() + 5
            while clock.monotonic() < stop_at:
                self.booking.refresh_from_db()
                if self.booking.status == 'expired':
                    break
                clock.sleep(.05)
            self.assertEqual(self.booking.status, 'expired')
        finally:
            deadline_worker._stop.set()
            deadline_worker._thread.join(timeout=5)
        self.assertFalse(deadline_worker._thread.is_alive())

    def test_concurrent_checks_create_one_expiration_notification(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import connections
        def run():
            try:
                process_booking(self.booking.pk)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run) for _ in range(2)]
            for future in futures:
                future.result(timeout=10)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'expired')
        self.assertEqual(Notification.objects.filter(booking=self.booking).count(), 1)
