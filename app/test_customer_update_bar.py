"""Owner-scoped, incremental customer alerts; two updates must group."""
import json

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Notification, User
from .test_customer_notifications import notification_fixture


class CustomerUpdateBarTests(TestCase):
    def test_offline_approval_is_delivered_at_login_without_reading_it(self):
        self.user.set_password('CustomerUpdates!123'); self.user.save()
        self.client.logout()
        notice = self.notice()
        self.client.post(reverse('login'), {'email':self.user.email,'password':'CustomerUpdates!123'})
        page = self.client.get(reverse('my_profile'))
        data = self.updates(page.context['customer_updates_cursor']).json()
        self.assertEqual(data['update_count'], 1)
        self.assertEqual(data['updates'][0]['id'], notice.pk)
        notice.refresh_from_db()
        self.assertFalse(notice.is_read)
        self.assertIsNone(notice.bar_shown_at)
        self.assertEqual(self.ack(data).status_code, 200)
        notice.refresh_from_db()
        self.assertIsNotNone(notice.bar_shown_at)
        self.assertFalse(notice.is_read)
        self.client.logout()
        self.client.post(reverse('login'), {'email':self.user.email,'password':'CustomerUpdates!123'})
        self.assertEqual(self.updates().json()['update_count'], 0)

    def setUp(self):
        self.user, self.booking = notification_fixture()
        self.client.force_login(self.user)
        self.url = reverse('customer_notification_feed')

    def notice(self, message=None, **kwargs):
        return Notification.objects.create(user=self.user, booking=self.booking,
            message=message or f'Great news! Your booking #{self.booking.pk} has been approved! Please proceed to payment.', **kwargs)

    def updates(self, cursor=None):
        response = self.client.get(self.url, {'updates': '1', **({'after': cursor} if cursor else {})})
        if response.status_code == 200:
            self.assertIn('updates_cursor', response.json())
        return response

    def ack(self, data, client=None):
        return (client or self.client).post(reverse('ack_customer_update_bar'),
            data=json.dumps({'delivery_token': data['delivery_token']}), content_type='application/json')

    def test_bootstrap_ignores_already_shown_history_and_threshold_is_exactly_two(self):
        self.notice(bar_shown_at=timezone.now())
        boot = self.updates().json()
        self.assertEqual(boot['update_count'], 0)
        cursor = boot['updates_cursor']
        for count in (1, 2, 3):
            self.notice()
            response = self.updates(cursor)
            self.assertEqual(response.json()['update_count'], count)
            self.assertEqual(len(response.json()['updates']), count)
            self.assertEqual(response['Cache-Control'], 'private, no-store')
        latest = response.json()['updates_cursor']
        self.assertEqual(self.ack(response.json()).status_code, 200)
        self.assertEqual(self.updates(latest).json()['update_count'], 0)
        self.assertEqual(Notification.objects.filter(is_read=False).count(), 4)

    def test_all_agreed_event_classes_and_links(self):
        cursor = self.updates().json()['updates_cursor']
        key = self.booking.pk
        messages = [
            (f'Great news! Your booking #{key} has been approved! Please proceed to payment.', 'booking_approved', 'View booking'),
            (f'Hooray! Your booking #{key} is now CONFIRMED! See you soon!', 'booking_confirmed', 'View booking'),
            (f"We're sorry, but your booking #{key} was NOT approved. Reason: unavailable", 'booking_declined', 'View booking'),
            (f'Your booking #{key} has been cancelled.', 'booking_cancelled', 'View booking'),
            (f'Booking #{key} expired. The initial payment deadline passed.', 'booking_expired', 'View booking'),
            (f'Your payment of PHP 1,500.00 for Booking #{key} has been verified. Thank you!', 'payment_verified', 'View payment'),
            (f'Your payment of PHP 1,500.00 for Booking #{key} was rejected. Reason: unclear', 'payment_rejected', 'View payment'),
            (f'Booking change request #1 for Booking #{key}: Your quote is ready. Open Booking Details to review and accept it before the deadline.', 'change_quote', 'Review quote'),
            (f'Booking change request #1 for Booking #{key}: Your changes are now final. Open Booking Details to see your updated reservation.', 'change_approved', 'View booking'),
            (f'Booking change request #1 for Booking #{key}: The requested change was declined: unavailable. Your original booking is unchanged.', 'change_declined', 'View booking'),
            (f'Booking change request #1 for Booking #{key}: The quote expired without acceptance/payment. Your original booking was not changed.', 'change_expired', 'View booking'),
            (f'Your backdrop design for booking #{key} is ready! Open your booking details to view and download it.', 'design_ready', 'View design'),
        ]
        for message, event, action in messages:
            notice = self.notice(message)
            with self.subTest(event=event):
                data = self.updates(cursor).json()
                row = next(row for row in data['updates'] if row['id'] == notice.pk)
                self.assertEqual(row['event'], event)
                self.assertEqual(row['action'], action)
                self.assertIn(f'booking_id={key}', row['target_url'])
                if event == 'design_ready': self.assertIn('modal=design', row['target_url'])
                if event == 'change_quote': self.assertIn('modal=details', row['target_url'])

    def test_excludes_receipts_promos_unrelated_and_read_events(self):
        cursor = self.updates().json()['updates_cursor']
        for message in ('General announcement: approved payments are safe.',
                        f'Your payment of PHP 100.00 for Booking #{self.booking.pk} was received and is now pending admin verification.',
                        f'Thank you! Your booking #{self.booking.pk} is now COMPLETED. Please leave a review.',
                        'Payment Reminder: please settle your balance.'):
            self.notice(message)
        self.notice(is_read=True)
        self.assertEqual(self.updates(cursor).json()['update_count'], 0)

    def test_cursor_and_booking_ownership_are_enforced(self):
        cursor = self.updates().json()['updates_cursor']
        self.assertEqual(self.client.get(self.url, {'updates': '1', 'after': 'bad'}).status_code, 400)
        other = User.objects.create_user(username='foreign-update', role='customer')
        Notification.objects.create(user=other, booking=self.booking, message='Your booking #1 has been cancelled.')
        self.assertEqual(self.updates(cursor).json()['update_count'], 0)
        self.client.force_login(other)
        self.assertEqual(self.updates(cursor).status_code, 400)
        foreign_cursor = self.updates().json()['updates_cursor']
        Notification.objects.create(user=other, booking=self.booking,
            message=f'Booking #{self.booking.pk} expired. No payment.')
        self.assertEqual(self.updates(foreign_cursor).json()['update_count'], 0)
        self.user.role = 'admin'; self.user.save(update_fields=['role'])
        self.client.force_login(self.user)
        self.assertEqual(self.updates(cursor).status_code, 403)

    def test_does_not_lose_batches_larger_than_normal_feed_or_count_delta(self):
        old = self.notice()
        cursor = self.updates().json()['updates_cursor']
        old.is_read = True; old.save(update_fields=['is_read'])
        self.notice()
        data = self.updates(cursor).json()
        self.assertEqual(data['update_count'], 1)
        for _ in range(30): self.notice()
        data = self.updates(cursor).json()
        self.assertEqual(data['update_count'], 31)
        self.assertLessEqual(len(data['updates']), 20)
        later = self.notice()
        self.assertEqual(self.ack(data).status_code, 200)
        self.assertEqual(Notification.objects.filter(bar_shown_at__isnull=False).count(), 31)
        pending = self.updates(data['updates_cursor']).json()
        self.assertEqual(pending['update_count'], 1)
        self.assertEqual(pending['updates'][0]['id'], later.pk)
        self.assertEqual(self.ack(data).status_code, 200)
        self.assertEqual(self.updates().json()['update_count'], 1)

    def test_delivery_receipts_are_post_only_csrf_protected_and_owner_scoped(self):
        notice = self.notice()
        data = self.updates().json()
        url = reverse('ack_customer_update_bar')
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf = Client(enforce_csrf_checks=True); csrf.force_login(self.user)
        self.assertEqual(self.ack(data, csrf).status_code, 403)
        self.assertEqual(self.client.post(url, data='{}', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(url, data='[]', content_type='application/json').status_code, 400)
        self.assertEqual(self.ack({'delivery_token': 'bad'}).status_code, 400)
        other = User.objects.create_user(username='foreign-receipt', role='customer')
        self.client.force_login(other)
        self.assertEqual(self.ack(data).status_code, 400)
        self.client.logout()
        self.assertEqual(self.ack(data).status_code, 302)
        self.user.role='admin'; self.user.save(update_fields=['role'])
        self.client.force_login(self.user)
        self.assertEqual(self.ack(data).status_code, 403)
        notice.refresh_from_db()
        self.assertIsNone(notice.bar_shown_at)
        self.assertFalse(notice.is_read)

    def test_fresh_login_has_a_fresh_bar_session_and_delivers_logged_out_history(self):
        self.user.set_password('CustomerUpdates!123'); self.user.save()
        self.client.force_login(self.user)
        self.notice(bar_shown_at=timezone.now())
        old = self.client.get(reverse('my_profile')).context.get('customer_updates_session', '')
        self.client.logout()
        self.notice()
        self.client.post(reverse('login'), {'email': self.user.email, 'password': 'CustomerUpdates!123'})
        page = self.client.get(reverse('my_profile'))
        marker = page.context.get('customer_updates_session', '')
        self.assertTrue(marker)
        self.assertNotEqual(marker, old)
        self.assertTrue(self.client.session.get('customer_updates_login'))
        stale = self.client.get(self.url, {'updates': '1', 'session': old,
            'after': page.context['customer_updates_cursor']})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()['code'], 'session_changed')
        self.assertEqual(self.client.get(self.url, {'updates': '1', 'session': marker,
            'after': page.context['customer_updates_cursor']}).json()['update_count'], 1)
        data = self.updates(page.context['customer_updates_cursor']).json()
        self.assertEqual(data['update_count'], 1)
        self.assertEqual(self.ack(data).status_code, 200)
        self.assertEqual(self.updates().json()['update_count'], 0)
