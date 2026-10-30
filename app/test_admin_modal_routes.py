"""Old admin detail links resolve to the modal workspaces, including notifications."""
from datetime import time, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .booking_changes import snapshot
from .models import AdminNotification, Booking, BookingChangeRequest, Payment, Review, User


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminModalRouteTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='modal-admin', role='admin')
        self.customer = User.objects.create_user(username='modal-customer', role='customer')
        self.booking = Booking.objects.create(user=self.customer,
            event_date=timezone.localdate() + timedelta(days=30), event_time=time(10),
            event_type='Birthday', event_location='Venue', total_price=5000, status='confirmed')
        self.payment = Payment.objects.create(booking=self.booking, amount=1000,
            payment_method='gcash', payment_status='pending')
        self.client.force_login(self.admin)

    def test_old_detail_urls_open_workspace_modals_and_preserve_design_section(self):
        for name, key, record in (('admin_booking_detail', 'open_booking', self.booking),
                                  ('admin_payment_detail', 'open_payment', self.payment)):
            workspace = reverse('admin_booking_list' if key == 'open_booking' else 'admin_payment_list')
            self.assertRedirects(self.client.get(reverse(name, args=[record.pk])),
                                 f'{workspace}?{key}={record.pk}')
        self.assertRedirects(self.client.get(reverse('admin_booking_detail', args=[self.booking.pk]),
                                            {'section': 'design'}),
                             f"{reverse('admin_booking_list')}?open_booking={self.booking.pk}&section=design")

    def test_ajax_details_still_load_in_dialogs(self):
        headers = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        response = self.client.get(reverse('admin_booking_detail', args=[self.booking.pk]), **headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn('abModalTitle', response.json()['html'])
        response = self.client.get(reverse('admin_payment_detail', args=[self.payment.pk]), **headers)
        self.assertContains(response, 'id="pmPaymentDetail"')
        self.assertNotContains(response, '<html')
        self.assertNotContains(response, 'id="pmDetailDialog"')

    def test_notification_feed_targets_modal_workspaces(self):
        from .admin_notifications import notification_rows
        AdminNotification.objects.create(booking=self.booking, user=self.customer,
            message=f'New GCash payment submitted for Booking #{self.booking.pk}')
        rows, _ = notification_rows()
        self.assertIn(f"{reverse('admin_booking_list')}?open_booking={self.booking.pk}",
                      [row['target_url'] for row in rows])
        self.assertIn(f"{reverse('admin_payment_list')}?open_payment={self.payment.pk}",
                      [row['target_url'] for row in rows])

    def test_customer_and_missing_record_links_do_not_bypass_access_checks(self):
        for name, record in (('admin_booking_detail', self.booking), ('admin_payment_detail', self.payment)):
            self.assertEqual(self.client.get(reverse(name, args=[999999999])).status_code, 404)
            self.client.force_login(self.customer)
            self.assertEqual(self.client.get(reverse(name, args=[record.pk])).status_code, 403)
            self.client.force_login(self.admin)

    def test_change_request_notifications_and_old_links_open_the_exact_modal(self):
        from .context_processors import _admin_notif_target_url
        for status in ('pending_review', 'withdrawn'):
            change = BookingChangeRequest.objects.create(booking=self.booking, status=status,
                original=snapshot(self.booking), proposed=snapshot(self.booking), original_total=5000, quoted_total=5000, reason='Update backdrop')
            url = f"{reverse('admin_booking_list')}?tab=requests&open_change={change.pk}"
            self.assertEqual(_admin_notif_target_url('event',
                f'Booking change request #{change.pk} for Booking #{self.booking.pk}', self.booking), url)
            self.assertEqual(_admin_notif_target_url('event', 'A booking change request needs review', self.booking), url)
            scope = 'active' if status == 'pending_review' else 'history'
            self.assertRedirects(self.client.get(reverse('admin_booking_change_detail', args=[change.pk])),
                f"{reverse('admin_booking_list')}?tab=requests&scope={scope}&open_change={change.pk}")
            response = self.client.get(reverse('admin_booking_change_detail', args=[change.pk]),
                                       HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 200)
            self.assertIn(f'Request #{change.pk}', response.json()['html'])

    def test_review_notifications_use_the_review_modal(self):
        from .context_processors import _admin_notif_target_url
        review = Review.objects.create(user=self.customer, booking=self.booking, rating=5, comment='Thank you')
        self.assertEqual(_admin_notif_target_url('event', 'submitted a new review.', self.booking),
                         f"{reverse('admin_reviews')}?review_id={review.pk}")
