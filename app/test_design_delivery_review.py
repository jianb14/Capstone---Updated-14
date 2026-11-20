"""Missed event designs retain an accountable resolution and truthful delivery history."""
from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import booking_lifecycle
from .models import AdminNotification, Booking, BookingChangeRequest, BookingDeadlineNotice, BookingDesignDelivery, Notification, Payment, User
from .test_design_delivery import TempMediaMixin, _design_upload


AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class DesignDeliveryReviewTests(TempMediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.now = timezone.make_aware(datetime(2035, 12, 30, 19))
        timer = patch('django.utils.timezone.now', return_value=self.now)
        timer.start()
        self.addCleanup(timer.stop)
        self.admin = User.objects.create_user(username='design-review-admin', role='admin')
        self.customer = User.objects.create_user(username='design-review-customer', role='customer')
        self.booking = Booking.objects.create(user=self.customer, status='confirmed', event_date=self.now.date(),
            event_time=time(15), event_end_time=time(19), event_type='Birthday', event_location='Bacoor',
            package_type='Birthday Package', total_price=5000, design_due_at=self.now - timedelta(days=1, hours=4))
        Payment.objects.create(booking=self.booking, amount=1000, payment_status='verified', transaction_ref='review-paid')
        self.client.force_login(self.admin)

    def display(self, now=None):
        return booking_lifecycle.lifecycle_display(self.booking, now or self.now)

    def deliver(self, when):
        with patch('django.utils.timezone.now', return_value=when):
            return BookingDesignDelivery.objects.create(booking=self.booking, image=_design_upload())

    def action(self, action, data=None):
        return self.client.post(reverse('admin_booking_action', args=[self.booking.pk, action]), data or {}, **AJAX)

    def test_missing_design_changes_from_preparing_to_review_at_exact_event_end(self):
        before = self.display(self.now - timedelta(microseconds=1))
        self.assertFalse(before.get('design_review_required'))
        self.assertTrue(before['design_preparing'])
        ended = self.display()
        self.assertTrue(ended.get('design_review_required'))
        self.assertFalse(ended['design_preparing'])
        self.assertTrue(ended['event_ended'])

    def test_overnight_event_waits_for_its_actual_next_day_end(self):
        self.booking.event_time, self.booking.event_end_time = time(23), time(2)
        self.booking.event_end_date = self.now.date() + timedelta(days=1)
        before = timezone.make_aware(datetime(2035, 12, 31, 1, 59))
        self.assertFalse(self.display(before).get('design_review_required'))
        self.assertTrue(self.display(before.replace(hour=2, minute=0)).get('design_review_required'))

    def test_legacy_end_time_and_default_duration_match_existing_schedule(self):
        self.booking.event_end_time = None
        self.booking.special_requests = '(End Time: 20:30)'
        self.assertFalse(self.display(self.now.replace(hour=20)).get('design_review_required'))
        self.assertTrue(self.display(self.now.replace(hour=20, minute=30)).get('design_review_required'))
        self.booking.special_requests = ''
        self.assertTrue(self.display().get('design_review_required'))  # 15:00 + existing four-hour fallback

    def test_unknown_start_time_waits_through_event_date(self):
        self.booking.event_time = self.booking.event_end_time = None
        self.assertFalse(self.display(self.now.replace(hour=23, minute=59)).get('design_review_required'))
        self.assertTrue(self.display(timezone.make_aware(datetime(2035, 12, 31))).get('design_review_required'))

    def test_worker_persists_one_issue_and_one_customer_escalation_on_repeated_checks(self):
        for _ in range(2):
            booking_lifecycle.process_booking(self.booking.pk, self.now)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')
        self.assertTrue(self.display().get('design_review_required'))
        self.assertEqual(self.booking.design_reviews.count(), 1)
        self.assertEqual(Notification.objects.filter(booking=self.booking, message__contains='event has ended').count(), 1)
        self.assertEqual(AdminNotification.objects.filter(booking=self.booking, message__contains='event has ended').count(), 1)

    def test_late_upload_after_event_end_cannot_hide_issue_when_worker_was_offline(self):
        self.deliver(self.now + timedelta(minutes=1))
        display = self.display(self.now + timedelta(minutes=2))
        self.assertTrue(display['design_ready'])
        self.assertTrue(display.get('design_review_required'))
        booking_lifecycle.process_booking(self.booking.pk, self.now + timedelta(minutes=2))
        self.assertEqual(self.booking.design_reviews.count(), 1)

    def test_design_delivered_before_event_end_does_not_create_missed_delivery_issue(self):
        self.deliver(self.now - timedelta(hours=5))
        booking_lifecycle.process_booking(self.booking.pk, self.now)
        self.assertFalse(self.display().get('design_review_required'))
        self.assertEqual(self.booking.design_reviews.count(), 0)

    def test_previous_design_does_not_fulfill_an_applied_revision(self):
        self.deliver(self.now - timedelta(days=2))
        BookingChangeRequest.objects.create(booking=self.booking, status='applied', reason='New text',
            proposed={'_design_changed': True}, original={}, applied_at=self.now - timedelta(days=1),
            original_total=5000, quoted_total=5000)
        self.assertTrue(self.display().get('design_review_required'))

    def test_overdue_customer_notice_is_sent_once_before_event_ends(self):
        before = self.now - timedelta(hours=6)
        for _ in range(2):
            booking_lifecycle.process_booking(self.booking.pk, before)
        self.assertEqual(Notification.objects.filter(booking=self.booking, message__contains='design is delayed').count(), 1)

    def resolution(self, **overrides):
        booking_lifecycle.process_booking(self.booking.pk)
        review = self.display()['design_review']
        data = {'design_revision': '', 'outcome': 'external_delivery', 'notes': 'Shown to the customer at the venue; the styling service was fulfilled.',
            'delivered_at': '2035-12-30T14:00', 'service_fulfilled': 'on',
            'review_id': str(review.pk) if review else '', 'review_version': str(getattr(review, 'version', 1))}
        data.update(overrides)
        return self.action('resolve-design', data)

    def test_direct_completion_is_blocked_until_missed_design_is_resolved(self):
        response = self.action('complete')
        self.assertEqual(response.status_code, 400)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')
        self.assertFalse(self.booking.status_logs.filter(new_status='completed').exists())
        self.assertTrue(self.booking.design_reviews.exists())

    def test_future_event_cannot_be_completed_to_bypass_the_missing_design_check(self):
        self.booking.event_date += timedelta(days=1)
        self.booking.save()
        response = self.action('complete')
        self.assertEqual(response.status_code, 400)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')

    def test_external_delivery_resolution_records_actual_date_actor_and_customer_notice(self):
        response = self.resolution()
        self.assertEqual(response.status_code, 200, response.content)
        review = self.booking.design_reviews.get()
        self.assertEqual(review.resolved_by, self.admin)
        self.assertEqual(review.delivered_at, timezone.make_aware(datetime(2035, 12, 30, 14)))
        self.assertEqual(review.resolved_at, self.now)
        self.assertTrue(review.service_fulfilled)
        self.assertEqual(Notification.objects.filter(booking=self.booking).count(), 2)
        self.assertEqual(self.action('complete').status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'completed')

    def test_repeated_resolution_does_not_duplicate_notifications_or_history(self):
        self.assertEqual(self.resolution().status_code, 200)
        notices, logs = Notification.objects.count(), self.booking.status_logs.count()
        self.assertEqual(self.resolution().status_code, 200)
        self.assertEqual(Notification.objects.count(), notices)
        self.assertEqual(self.booking.status_logs.count(), logs)

    def test_resolution_requires_notes_and_valid_actual_delivery_time(self):
        for fields, field in [({'notes': '   '}, 'notes'), ({'notes': 'x'*2001}, 'notes'),
            ({'delivered_at': ''}, 'delivered_at'), ({'delivered_at': 'not-a-date'}, 'delivered_at'),
            ({'delivered_at': '2035-12-31T10:00'}, 'delivered_at'), ({'outcome': 'unknown'}, 'outcome')]:
            with self.subTest(field=field, fields=fields):
                response = self.resolution(**fields)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()['errors'])
        self.assertFalse(self.booking.design_reviews.filter(resolved_at__isnull=False).exists())

    def test_resolution_without_fulfilled_service_cannot_enable_completion(self):
        response = self.resolution(outcome='customer_resolution', delivered_at='', service_fulfilled='')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.action('complete').status_code, 400)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')

    def test_resolution_rejects_stale_design_requirements(self):
        BookingChangeRequest.objects.create(booking=self.booking, status='applied', reason='New design',
            proposed={'_design_changed': True}, original={}, applied_at=self.now - timedelta(hours=1),
            original_total=5000, quoted_total=5000)
        response = self.resolution()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.booking.design_reviews.filter(resolved_at__isnull=False).exists())

    def test_only_admin_can_resolve_and_get_cannot_mutate(self):
        url = reverse('admin_booking_action', args=[self.booking.pk, 'resolve-design'])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(self.customer)
        self.assertEqual(self.resolution().status_code, 403)
        self.assertFalse(self.booking.design_reviews.filter(resolved_at__isnull=False).exists())

    def test_pre_event_or_nonconfirmed_booking_cannot_be_resolved(self):
        self.booking.event_date += timedelta(days=1)
        self.booking.save()
        self.assertEqual(self.resolution().status_code, 400)
        self.booking.event_date -= timedelta(days=1)
        self.booking.status = 'cancelled'
        self.booking.save()
        self.assertEqual(self.resolution().status_code, 400)

    def test_upload_after_event_retains_issue_and_deadline_snapshot(self):
        url = reverse('admin_booking_design_upload', args=[self.booking.pk])
        response = self.client.post(url, {'design_image': _design_upload()}, **AJAX)
        self.assertEqual(response.status_code, 200, response.content)
        delivery = self.booking.design_deliveries.get()
        self.assertTrue(delivery.is_late)
        self.assertEqual(delivery.due_at, self.booking.design_due_at)
        self.assertTrue(self.display()['design_review_required'])
        self.assertEqual(self.action('complete').status_code, 400)
        self.assertEqual(self.resolution(outcome='late_delivery', delivered_at='').status_code, 200)
        self.assertEqual(self.action('complete').status_code, 200)

    def test_late_delivery_resolution_requires_a_current_image(self):
        response = self.resolution(outcome='late_delivery', delivered_at='')
        self.assertEqual(response.status_code, 400)
        self.assertIn('outcome', response.json()['errors'])

    def test_deleting_last_current_image_reopens_an_online_delivery_resolution(self):
        self.client.post(reverse('admin_booking_design_upload', args=[self.booking.pk]), {'design_image': _design_upload()}, **AJAX)
        self.assertEqual(self.resolution(outcome='late_delivery', delivered_at='').status_code, 200)
        delivery = self.booking.design_deliveries.get()
        response = self.client.post(reverse('admin_booking_design_delete', args=[self.booking.pk, delivery.pk]), **AJAX)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.display()['design_review_required'])
        self.assertEqual(self.action('complete').status_code, 400)

    def test_customer_sees_ended_event_issue_instead_of_preparation(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse('booking_modal_content', args=[self.booking.pk]))
        self.assertContains(response, 'Event passed')
        self.assertNotContains(response, 'Design in preparation')

    def test_admin_design_dialog_offers_resolution_without_nested_forms(self):
        response = self.client.get(reverse('admin_booking_detail', args=[self.booking.pk]), {'section': 'design'}, **AJAX)
        html = response.json()['html']
        self.assertIn('data-design-review-form', html)
        self.assertIn('Needs admin action', html)
        from html.parser import HTMLParser
        class Forms(HTMLParser):
            depth = 0
            nested = False
            def handle_starttag(parser, tag, attrs):
                if tag == 'form':
                    parser.nested |= bool(parser.depth)
                    parser.depth += 1
            def handle_endtag(parser, tag):
                if tag == 'form':
                    parser.depth -= 1
        parser = Forms(); parser.feed(html)
        self.assertFalse(parser.nested)
        self.assertEqual(parser.depth, 0)

    def test_customer_sees_escaped_resolution_and_actual_external_delivery(self):
        notes = '<script>alert(1)</script> Shared through Messenger and reviewed at the venue.'
        self.assertEqual(self.resolution(notes=notes).status_code, 200)
        self.client.force_login(self.customer)
        response = self.client.get(reverse('booking_modal_content', args=[self.booking.pk]))
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, 'Delivered outside the system')
        self.assertContains(response, 'Dec 30, 2035')

    def test_late_delivery_is_labeled_for_admin_and_customer(self):
        self.client.post(reverse('admin_booking_design_upload', args=[self.booking.pk]), {'design_image': _design_upload()}, **AJAX)
        html = self.client.get(reverse('admin_booking_detail', args=[self.booking.pk]), {'section': 'design'}, **AJAX).json()['html']
        self.assertIn('Late delivery', html)
        self.client.force_login(self.customer)
        response = self.client.get(reverse('booking_modal_content', args=[self.booking.pk]), {'section': 'design'})
        self.assertContains(response, 'Late delivery')

    def test_queue_exposes_review_and_hides_completion_until_resolved(self):
        response = self.client.get(reverse('admin_booking_list'), {'tab': 'designs', 'design_status': 'review'})
        self.assertEqual([row.pk for row in response.context['bookings']], [self.booking.pk])
        self.assertContains(response, 'Needs admin review')
        self.assertNotContains(response, 'data-action="complete"')
        self.assertEqual(self.resolution().status_code, 200)
        html = self.client.get(reverse('admin_booking_detail', args=[self.booking.pk]), **AJAX).json()['html']
        self.assertIn('data-action="complete"', html)

    def test_new_design_revision_cannot_inherit_a_previous_resolution(self):
        self.assertEqual(self.resolution().status_code, 200)
        BookingChangeRequest.objects.create(booking=self.booking, status='applied', reason='Revised backdrop',
            proposed={'_design_changed': True}, original={}, applied_at=self.now - timedelta(hours=1),
            original_total=5000, quoted_total=5000)
        booking_lifecycle.process_booking(self.booking.pk, self.now)
        self.assertTrue(self.display()['design_review_required'])
        self.assertEqual(self.booking.design_reviews.count(), 2)
        self.assertEqual(self.action('complete').status_code, 400)

    def test_completed_booking_retains_last_image_supporting_online_resolution(self):
        self.client.post(reverse('admin_booking_design_upload', args=[self.booking.pk]), {'design_image': _design_upload()}, **AJAX)
        self.assertEqual(self.resolution(outcome='late_delivery', delivered_at='').status_code, 200)
        self.assertEqual(self.action('complete').status_code, 200)
        delivery = self.booking.design_deliveries.get()
        response = self.client.post(reverse('admin_booking_design_delete', args=[self.booking.pk, delivery.pk]), **AJAX)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(self.booking.design_deliveries.filter(pk=delivery.pk).exists())
        self.assertIsNotNone(self.booking.design_reviews.get().resolved_at)

    def test_customer_tracker_after_event_does_not_promise_a_future_event(self):
        self.assertEqual(self.resolution().status_code, 200)
        self.client.force_login(self.customer)
        response = self.client.get(reverse('booking_modal_content', args=[self.booking.pk]))
        self.assertNotContains(response, 'everything is set for your event')
        self.assertContains(response, 'Your event has ended')

    def test_customer_can_download_design_supporting_a_completed_resolution(self):
        self.client.post(reverse('admin_booking_design_upload', args=[self.booking.pk]), {'design_image': _design_upload()}, **AJAX)
        self.assertEqual(self.resolution(outcome='late_delivery', delivered_at='').status_code, 200)
        self.assertEqual(self.action('complete').status_code, 200)
        self.client.force_login(self.customer)
        delivery = self.booking.design_deliveries.get()
        response = self.client.get(reverse('booking_design_download', args=[self.booking.pk, delivery.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b''.join(response.streaming_content).startswith(b'\x89PNG'))

    def test_ended_revision_details_do_not_promise_a_future_revision(self):
        self.deliver(self.now - timedelta(days=2))
        BookingChangeRequest.objects.create(booking=self.booking, status='applied', reason='Revised backdrop',
            proposed={'_design_changed': True}, original={}, applied_at=self.now - timedelta(days=1),
            original_total=5000, quoted_total=5000)
        self.client.force_login(self.customer)
        response = self.client.get(reverse('booking_modal_content', args=[self.booking.pk]))
        self.assertNotContains(response, 'our team prepares a revision')
        self.assertContains(response, 'Event passed')

    def test_unfulfilled_resolution_does_not_promise_a_future_event(self):
        self.assertEqual(self.resolution(outcome='customer_resolution', delivered_at='', service_fulfilled='').status_code, 200)
        self.client.force_login(self.customer)
        response = self.client.get(reverse('booking_modal_content', args=[self.booking.pk]))
        self.assertNotContains(response, 'everything is set for your event')
        self.assertContains(response, 'fulfillment was not confirmed')

    def test_customer_keeps_previous_resolution_when_deleted_image_reopens_review(self):
        self.client.post(reverse('admin_booking_design_upload', args=[self.booking.pk]), {'design_image': _design_upload()}, **AJAX)
        self.assertEqual(self.resolution(outcome='late_delivery', delivered_at='', notes='Customer approved the late design at the venue.').status_code, 200)
        delivery = self.booking.design_deliveries.get()
        self.client.post(reverse('admin_booking_design_delete', args=[self.booking.pk, delivery.pk]), **AJAX)
        self.client.force_login(self.customer)
        response = self.client.get(reverse('booking_modal_content', args=[self.booking.pk]))
        self.assertContains(response, 'Customer approved the late design at the venue.')
        self.assertContains(response, 'Review reopened')
        self.assertContains(response, 'Actual delivery')

    def test_design_lateness_uses_first_delivery_deadline_snapshot(self):
        first = self.deliver(self.now - timedelta(days=2))
        first.due_at = self.now - timedelta(days=1)
        first.save(update_fields=['due_at'])
        self.deliver(self.now)
        self.assertFalse(self.display()['design_late'])
        BookingDesignDelivery.objects.filter(pk=first.pk).update(due_at=self.now - timedelta(days=3))
        self.booking.design_due_at = self.now + timedelta(days=1)
        self.assertTrue(self.display()['design_late'])

    def test_legacy_admin_overdue_notice_does_not_suppress_first_customer_notice(self):
        BookingDeadlineNotice.objects.create(booking=self.booking, key='design-overdue')
        for _ in range(2):
            booking_lifecycle.process_booking(self.booking.pk, self.now - timedelta(hours=6))
        self.assertEqual(Notification.objects.filter(booking=self.booking, message__contains='design is delayed').count(), 1)
        self.assertEqual(AdminNotification.objects.filter(booking=self.booking).count(), 0)

    def test_legacy_confirmed_review_is_visible_without_upload_payment_permission(self):
        self.booking.payments.all().delete()
        response = self.client.get(reverse('admin_booking_list'), {'tab': 'designs', 'design_status': 'review'})
        self.assertEqual([row.pk for row in response.context['bookings']], [self.booking.pk])
        self.assertEqual(response.context['design_review_count'], 1)
        self.assertFalse(response.context['bookings'][0].can_send_design)

    def test_conflicting_second_resolution_is_rejected_instead_of_reporting_false_success(self):
        self.assertEqual(self.resolution().status_code, 200)
        response = self.resolution(notes='A different agreement that must not silently disappear.')
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(self.booking.design_reviews.get().notes, 'A different agreement that must not silently disappear.')

    def test_resolution_replay_after_reopening_cannot_reuse_old_fulfillment_declaration(self):
        upload = reverse('admin_booking_design_upload', args=[self.booking.pk])
        self.client.post(upload, {'design_image': _design_upload()}, **AJAX)
        self.assertEqual(self.resolution(outcome='late_delivery', delivered_at='').status_code, 200)
        review = self.booking.design_reviews.get()
        old_version = str(getattr(review, 'version', 1))
        delivery = self.booking.design_deliveries.get()
        self.client.post(reverse('admin_booking_design_delete', args=[self.booking.pk, delivery.pk]), **AJAX)
        self.client.post(upload, {'design_image': _design_upload()}, **AJAX)
        response = self.resolution(outcome='late_delivery', delivered_at='', review_version=old_version)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(self.display()['design_review_required'])
