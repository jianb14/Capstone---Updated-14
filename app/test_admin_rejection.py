"""Selected reasons work without notes and are validated before any status change."""
from datetime import time, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .admin_rejection import REJECTION_CHOICES, rejection_reason
from .booking_changes import snapshot
from .models import Booking, BookingChangeRequest, Notification, Payment, User


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminRejectionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='reason-admin', role='admin')
        self.user = User.objects.create_user(username='reason-customer', role='customer')
        self.booking = Booking.objects.create(user=self.user, event_date=timezone.localdate()+timedelta(days=30),
            event_time=time(10), event_type='Birthday', event_location='Venue', status='pending', total_price=5000)
        self.payment = Payment.objects.create(booking=self.booking, amount=1000, payment_method='gcash', payment_status='pending')
        self.client.force_login(self.admin)

    def test_every_choice_saves_with_optional_details_and_invalid_choices_fail(self):
        for kind, choices in REJECTION_CHOICES.items():
            field, note = ('deny_reason_choice', 'deny_reason') if kind == 'booking' else ('reject_reason_choice', 'admin_notes')
            for value, label in choices:
                self.assertEqual(rejection_reason({field:value, note:'   '}, kind), label)
                self.assertEqual(rejection_reason({field:value, note:'Please contact us.'}, kind), f'{label}. Please contact us.')
            for value in ('', 'forged-choice'):
                with self.assertRaises(ValueError):
                    rejection_reason({field:value, note:'Details alone'}, kind)
            with self.assertRaises(ValueError):
                rejection_reason({field:choices[0][0], note:'x'*2000}, kind)

    def test_booking_selection_alone_is_saved_and_sent_to_the_customer(self):
        response = self.client.post(reverse('admin_booking_action', args=[self.booking.pk, 'deny']),
            {'deny_reason_choice':'schedule_unavailable', 'deny_reason':''}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'cancelled')
        self.assertEqual(self.booking.admin_denial_reason, 'Schedule is unavailable')
        self.assertTrue(Notification.objects.filter(booking=self.booking, message__contains='Schedule is unavailable').exists())

    def test_payment_selection_and_notes_are_saved_together(self):
        self.client.post(reverse('admin_payment_action', args=[self.payment.pk, 'reject'])+'?next=payments',
            {'reject_reason_choice':'invalid_receipt', 'admin_notes':'Please upload a clear photo.'})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payment_status, 'rejected')
        self.assertEqual(self.payment.notes, 'Receipt is invalid or unreadable. Please upload a clear photo.')

    def test_additional_change_payment_uses_the_selected_reason_without_notes(self):
        change = BookingChangeRequest.objects.create(booking=self.booking, status='manual_review',
            original=snapshot(self.booking), proposed=snapshot(self.booking), original_total=5000, quoted_total=5500, additional_due=500, reason='Backdrop change')
        self.payment.change_request = change
        self.payment.save(update_fields=['change_request'])
        self.client.post(reverse('admin_payment_action', args=[self.payment.pk, 'reject'])+'?next=payments',
            {'reject_reason_choice':'amount_mismatch', 'admin_notes':''})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payment_status, 'rejected')
        self.assertEqual(self.payment.notes, 'Payment amount does not match')

    def test_missing_and_forged_choices_leave_records_unchanged(self):
        for choice in ('', 'not-allowed'):
            response = self.client.post(reverse('admin_booking_action', args=[self.booking.pk, 'deny']),
                {'deny_reason_choice':choice, 'deny_reason':'Details'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 400)
            self.client.post(reverse('admin_payment_action', args=[self.payment.pk, 'reject'])+'?next=payments',
                {'reject_reason_choice':choice, 'admin_notes':'Details'})
            self.booking.refresh_from_db(); self.payment.refresh_from_db()
            self.assertEqual(self.booking.status, 'pending')
            self.assertEqual(self.payment.payment_status, 'pending')
