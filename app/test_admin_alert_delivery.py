"""Admin activity alerts and current policy editor use the configured mail transport."""
import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .booking_changes import notify, snapshot
from .booking_lifecycle import deadline_notice
from .models import AdminNotification, BookingChangeRequest, ChatSession, GuidelinePageContent, Payment
from . import test_email_delivery as delivery_tests


@override_settings(EMAIL_BACKEND='app.email_backend.BrevoEmailBackend', BREVO_API_KEY='test-brevo-key',
                   DEFAULT_FROM_EMAIL='Balloorina <sender@example.com>', REQUEST_RATE_LIMITING_ENABLED=False)
class AdminAlertDeliveryTests(TestCase):
    setUp = delivery_tests.BrevoEmailDeliveryTests.setUp
    booking = delivery_tests.BrevoEmailDeliveryTests.booking
    payload = delivery_tests.BrevoEmailDeliveryTests.payload

    def test_paid_webhook_and_customer_return_send_one_admin_email(self):
        booking = self.booking()
        payment = Payment.objects.create(booking=booking, amount=1000, payment_method='paymongo_gcash',
            payment_status='pending', transaction_ref='mail-paymongo', paymongo_checkout_session_id='cs_mail')
        payload = {'data': {'attributes': {'type':'checkout_session.payment.paid',
            'data': {'id':'cs_mail', 'attributes':{}}}}}
        with patch('app.views.payments.verify_paymongo_webhook_signature', return_value=True):
            with self.captureOnCommitCallbacks(execute=True):
                for _ in range(2):
                    response = self.client.post(reverse('paymongo_webhook'), json.dumps(payload), content_type='application/json')
                    self.assertEqual(response.status_code, 200)
        self.client.force_login(self.user)
        with patch('app.views.payments.retrieve_paymongo_checkout_session', return_value={'data':{'attributes':{'status':'paid'}}}):
            with self.captureOnCommitCallbacks(execute=True):
                self.client.get(reverse('paymongo_success', args=[booking.pk]))
        self.payload('New PayMongo Payment', ['admin@example.com', 'staff@example.com'])
        self.assertEqual(AdminNotification.objects.filter(booking=booking, message__contains='New PayMongo payment').count(), 1)
        payment.refresh_from_db()
        self.assertTrue(payment.admin_notified)
        self.assertEqual(payment.payment_status, 'pending')

    def test_unpaid_checkouts_do_not_send_received_payment_alerts(self):
        from .views.payments import _notify_received_paymongo
        booking = self.booking()
        payment = Payment.objects.create(booking=booking, amount=1000, payment_method='paymongo_gcash',
            payment_status='pending', transaction_ref='mail-unpaid', paymongo_checkout_session_id='cs_unpaid')
        with self.captureOnCommitCallbacks(execute=True):
            self.assertFalse(_notify_received_paymongo(payment))
        self.post.assert_not_called()
        self.assertFalse(AdminNotification.objects.filter(booking=booking).exists())

    def test_rolled_back_received_payment_does_not_send_or_consume_the_alert(self):
        from .views.payments import _notify_received_paymongo
        booking = self.booking()
        payment = Payment.objects.create(booking=booking, amount=1000, payment_method='paymongo_gcash',
            payment_status='pending', received_at=timezone.now(), transaction_ref='mail-rollback')
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    self.assertTrue(_notify_received_paymongo(payment))
                    raise RuntimeError('Save rolled back')
        self.post.assert_not_called()
        payment.refresh_from_db()
        self.assertFalse(payment.admin_notified)
        self.assertFalse(AdminNotification.objects.filter(booking=booking).exists())

    def test_change_request_alert_is_admin_only_and_honors_site_settings(self):
        booking = self.booking()
        change = BookingChangeRequest.objects.create(booking=booking, original=snapshot(booking), proposed=snapshot(booking),
            original_total=5000, quoted_total=5000, reason='Update the text')
        with self.captureOnCommitCallbacks(execute=True):
            notify(change, 'Please review these changes.', admin=True)
        self.payload('Booking Change Request', ['admin@example.com', 'staff@example.com'])
        self.post.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            notify(change, 'The customer can review the quote.')
        self.post.assert_not_called()
        self.site.email_notifications_enabled = False
        self.site.save()
        with self.captureOnCommitCallbacks(execute=True):
            notify(change, 'Another admin notice.', admin=True)
        self.post.assert_not_called()

    def test_new_review_emails_configured_admins(self):
        booking = self.booking()
        booking.status = 'completed'
        booking.save(update_fields=['status'])
        self.client.force_login(self.user)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('submit_review', args=[booking.pk]),
                {'rating':5, 'comment':'A lovely celebration.'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 201)
        self.payload('New Review', ['admin@example.com', 'staff@example.com'])

    def test_new_support_request_and_repeat_safe_deadline_email(self):
        from .views.chat import _notify_admins_new_chat_request
        session = ChatSession.objects.create(user=self.user, title='Please help with my booking', is_admin_support=True, status='pending_admin')
        with self.captureOnCommitCallbacks(execute=True):
            _notify_admins_new_chat_request(session, self.user)
        self.payload('New Admin Chat Request', ['admin@example.com', 'staff@example.com'])
        self.post.reset_mock()
        booking = self.booking()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(deadline_notice(booking, 'design-overdue', 'A design is overdue.'))
            self.assertFalse(deadline_notice(booking, 'design-overdue', 'A design is overdue.'))
        self.payload('deadline alert', ['admin@example.com', 'staff@example.com'])

    def test_current_policy_modal_emails_only_for_opted_in_changes(self):
        page, _ = GuidelinePageContent.objects.get_or_create(page_key='terms')
        self.client.force_login(self.admin)
        url = reverse('admin_content_action', args=['policies','page','section',page.pk])
        response = self.client.post(url, {'title':'Policy without notice'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.post.assert_not_called()
        response = self.client.post(url, {'title':'Updated payment terms','notify_clients':'on'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.payload('Updated Guidelines, Terms & Privacy', [self.user.email])
        self.post.reset_mock()
        self.client.post(url, {'title':'Updated payment terms','notify_clients':'on'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.post.assert_not_called()
