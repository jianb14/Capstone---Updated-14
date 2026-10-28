"""Concern retries, customer cancellation and staff updates share durable database state."""
import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from PIL import Image
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, ConcernImage, ConcernTicket, SubmissionReceipt, User
from .views.admin import admin_concern_update
from .views.profiles import cancel_concern, report_concern


def photo():
    stream = io.BytesIO()
    Image.new('RGB', (12, 12), '#dddddd').save(stream, format='PNG')
    return SimpleUploadedFile('concern.png', stream.getvalue(), content_type='image/png')


def payload(**changes):
    return {'category': 'bug', 'subject': 'The page stopped loading',
            'message': 'The connection dropped while I was submitting.', **changes}


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class ConcernTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='concern-owner', role='customer', email_verified=True)
        self.other = User.objects.create_user(username='concern-other', role='customer', email_verified=True)
        self.admin = User.objects.create_user(username='concern-admin', role='admin', email_verified=True)
        self.client.force_login(self.user)
        self.alert = self.enterContext(patch('app.views.profiles.send_admin_alert_email', return_value=True))

    def ticket(self, **changes):
        return ConcernTicket.objects.create(user=self.user, category='bug', subject='Help', message='Details', **changes)

    def cancel(self, ticket, client=None):
        return (client or self.client).post(reverse('cancel_concern', args=[ticket.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_retries_create_one_ticket_one_attachment_one_alert_and_one_audit(self):
        key = str(uuid.uuid4())
        for _ in range(4):
            response = self.client.post(reverse('report_concern'), payload(submission_key=key, concern_images=photo()),
                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['success'])
        self.assertEqual(ConcernTicket.objects.count(), 1)
        self.assertEqual(ConcernImage.objects.count(), 1)
        self.alert.assert_called_once()
        self.assertEqual(AuditLog.objects.filter(action__startswith='Submitted concern').count(), 1)

    def test_durable_form_key_survives_expired_receipt_and_changed_retry_fields(self):
        key = str(uuid.uuid4())
        self.client.post(reverse('report_concern'), payload(submission_key=key))
        SubmissionReceipt.objects.update(expires_at=timezone.now() - timedelta(days=1))
        response = self.client.post(reverse('report_concern'), payload(submission_key=key, subject='Edited after lost response'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'])
        self.assertEqual(ConcernTicket.objects.count(), 1)
        self.assertEqual(ConcernTicket.objects.get().subject, payload()['subject'])
        self.alert.assert_called_once()

    def test_legacy_forms_without_key_and_html_ajax_retries_are_compatible(self):
        url = reverse('report_concern')
        self.assertEqual(self.client.post(url, payload()).status_code, 302)
        replay = self.client.post(url, payload(), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(replay.json()['success'])
        self.assertEqual(replay['Idempotent-Replayed'], 'true')
        self.assertEqual(self.client.post(url, payload()).status_code, 302)
        self.assertEqual(ConcernTicket.objects.count(), 1)
        self.alert.assert_called_once()

    def test_ajax_success_can_be_replayed_as_html_without_exposing_json_page(self):
        self.client.post(reverse('report_concern'), payload(), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        response = self.client.post(reverse('report_concern'), payload())
        self.assertRedirects(response, reverse('report_concern'), fetch_redirect_response=False)
        self.assertEqual(ConcernTicket.objects.count(), 1)

    def test_different_forms_and_different_customers_have_independent_keys(self):
        key = str(uuid.uuid4())
        self.client.post(reverse('report_concern'), payload(submission_key=key))
        self.client.post(reverse('report_concern'), payload(submission_key=str(uuid.uuid4()), subject='Another issue'))
        self.client.force_login(self.other)
        self.client.post(reverse('report_concern'), payload(submission_key=key))
        self.assertEqual(ConcernTicket.objects.count(), 3)

    def test_validation_does_not_consume_form_key_or_create_ticket(self):
        key = str(uuid.uuid4())
        for invalid in ({'category': ''}, {'subject': ''}, {'message': ''}, {'submission_key': 'not-a-uuid'},
                        {'category': 'other', 'other_category': ''}, {'subject': 'x' * 151}):
            data = payload(submission_key=key)
            data.update(invalid)
            response = self.client.post(reverse('report_concern'), data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 400)
        self.assertFalse(ConcernTicket.objects.exists())
        self.assertFalse(SubmissionReceipt.objects.exists())
        self.client.post(reverse('report_concern'), payload(submission_key=key))
        self.assertEqual(ConcernTicket.objects.count(), 1)

    def test_invalid_or_excess_images_create_no_ticket_or_files(self):
        for images in ([photo() for _ in range(5)], [SimpleUploadedFile('fake.png', b'not an image')]):
            response = self.client.post(reverse('report_concern'), payload(concern_images=images),
                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 400)
        self.assertFalse(ConcernTicket.objects.exists())
        self.assertFalse(ConcernImage.objects.exists())
        self.alert.assert_not_called()

    def test_oversized_and_unsupported_images_are_rejected_by_server(self):
        stream = io.BytesIO()
        Image.new('RGB', (12, 12)).save(stream, format='GIF')
        for upload in (SimpleUploadedFile('too-large.png', b'x' * (5 * 1024 * 1024 + 1), content_type='image/png'),
                       SimpleUploadedFile('animation.gif', stream.getvalue(), content_type='image/gif')):
            response = self.client.post(reverse('report_concern'), payload(concern_images=upload),
                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 400)
        self.assertFalse(ConcernTicket.objects.exists())
        self.alert.assert_not_called()

    def test_alert_failure_does_not_duplicate_or_lose_a_saved_concern(self):
        self.alert.return_value = False
        self.client.post(reverse('report_concern'), payload())
        self.client.post(reverse('report_concern'), payload())
        self.assertEqual(ConcernTicket.objects.count(), 1)
        self.alert.assert_called_once()

    def test_cancel_new_keeps_details_and_attachments_and_repeated_click_is_harmless(self):
        ticket = self.ticket()
        ConcernImage.objects.create(concern=ticket, image=photo())
        for _ in range(2):
            response = self.cancel(ticket)
            self.assertTrue(response.json()['success'])
            self.assertFalse(response.json()['ticket']['can_cancel'])
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'cancelled')
        self.assertEqual(ticket.message, 'Details')
        self.assertEqual(ticket.images.count(), 1)
        self.assertEqual(AuditLog.objects.filter(action__startswith='Cancelled concern').count(), 1)

    def test_processing_resolved_notes_and_prior_processing_cannot_be_cancelled(self):
        for changes in ({'status': 'in_progress'}, {'status': 'resolved'}, {'admin_notes': 'We are reviewing this.'},
                        {'processing_started_at': timezone.now()}):
            ticket = self.ticket(**changes)
            self.assertEqual(self.cancel(ticket).status_code, 409)
            ticket.refresh_from_db()
            self.assertNotEqual(ticket.status, 'cancelled')

    def test_ownership_roles_method_and_csrf_are_enforced(self):
        ticket = self.ticket()
        stranger = Client()
        stranger.force_login(self.other)
        self.assertEqual(self.cancel(ticket, stranger).status_code, 404)
        stranger.force_login(self.admin)
        self.assertEqual(self.cancel(ticket, stranger).status_code, 403)
        self.assertEqual(self.client.get(reverse('cancel_concern', args=[ticket.pk])).status_code, 405)
        self.assertEqual(Client().post(reverse('cancel_concern', args=[ticket.pk])).status_code, 302)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(self.cancel(ticket, strict).status_code, 403)
        self.assertEqual(strict.post(reverse('report_concern'), payload()).status_code, 403)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'new')

    def test_customer_only_receives_own_history_and_safe_json_data(self):
        own = self.ticket()
        ConcernTicket.objects.create(user=self.other, subject='Private other concern', message='Private message')
        response = self.client.get(reverse('report_concern'))
        self.assertEqual([item['id'] for item in response.context['ticket_data']], [own.pk])
        self.assertNotContains(response, 'Private message')
        self.assertTrue(response.context['ticket_data'][0]['can_cancel'])

    def test_staff_processing_is_durable_even_if_status_is_reset_to_new(self):
        ticket = self.ticket()
        self.client.force_login(self.admin)
        url = reverse('admin_concern_update', args=[ticket.pk])
        self.client.post(url, {'status': 'in_progress', 'admin_notes': 'Investigating'})
        self.client.post(url, {'status': 'new', 'admin_notes': ''})
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.processing_started_at)
        self.client.force_login(self.user)
        self.assertEqual(self.cancel(ticket).status_code, 409)

    def test_new_ticket_with_admin_response_is_not_cancellable(self):
        ticket = self.ticket()
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_concern_update', args=[ticket.pk]), {'status': 'new', 'admin_notes': 'Please send a screenshot.'})
        ticket.refresh_from_db()
        self.assertFalse(ticket.can_cancel)
        self.assertIsNotNone(ticket.processing_started_at)

    def test_cancelled_ticket_cannot_be_reopened_by_stale_admin_form(self):
        ticket = self.ticket()
        self.cancel(ticket)
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_concern_update', args=[ticket.pk]), {'status': 'resolved', 'admin_notes': 'Stale update'})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'cancelled')
        self.assertFalse(ticket.admin_notes)

    def test_admin_can_filter_cancelled_and_cannot_set_customer_cancel_status(self):
        ticket = self.ticket(status='cancelled')
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_concern_update', args=[self.ticket().pk]), {'status': 'cancelled'})
        self.assertEqual(ConcernTicket.objects.filter(status='cancelled').count(), 1)
        response = self.client.get(reverse('admin_concerns'), {'concern_status': 'cancelled',
            'start_date': timezone.localdate().isoformat(), 'end_date': timezone.localdate().isoformat()})
        self.assertEqual([item.pk for item in response.context['concern_rows']], [ticket.pk])


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class ConcernConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_parallel_submissions_commit_one_ticket_attachment_and_alert(self):
        user = User.objects.create_user(username='parallel-concern', role='customer')
        gate = Barrier(4)
        key = str(uuid.uuid4())
        def send(_):
            close_old_connections()
            try:
                request = RequestFactory().post(reverse('report_concern'), payload(submission_key=key, concern_images=photo()),
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                request.user = user
                gate.wait(timeout=10)
                return report_concern(request).status_code
            finally:
                close_old_connections()
        with patch('app.views.profiles.send_admin_alert_email', return_value=True) as alert:
            with ThreadPoolExecutor(max_workers=4) as pool:
                self.assertEqual(list(pool.map(send, range(4))), [200] * 4)
        self.assertEqual(ConcernTicket.objects.count(), 1)
        self.assertEqual(ConcernImage.objects.count(), 1)
        alert.assert_called_once()

    @skipUnlessDBFeature('has_select_for_update')
    def test_cancellation_and_admin_processing_cannot_overwrite_each_other(self):
        user = User.objects.create_user(username='race-concern', role='customer')
        admin = User.objects.create_user(username='race-admin', role='admin')
        for _ in range(4):
            ticket = ConcernTicket.objects.create(user=user, subject='Race', message='Details')
            gate = Barrier(2)
            def act(is_admin):
                close_old_connections()
                try:
                    route = 'admin_concern_update' if is_admin else 'cancel_concern'
                    request = RequestFactory().post(reverse(route, args=[ticket.pk]),
                        {'status': 'in_progress', 'admin_notes': 'Working on it'} if is_admin else {},
                        HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                    request.user = admin if is_admin else user
                    request.session = {}
                    request._messages = FallbackStorage(request)
                    gate.wait(timeout=10)
                    return (admin_concern_update if is_admin else cancel_concern)(request, ticket.pk).status_code
                finally:
                    close_old_connections()
            with ThreadPoolExecutor(max_workers=2) as pool:
                admin_status, cancel_status = list(pool.map(act, [True, False]))
            ticket.refresh_from_db()
            if ticket.status == 'cancelled':
                self.assertEqual(admin_status, 409)
                self.assertEqual(cancel_status, 200)
                self.assertFalse(ticket.admin_notes)
                self.assertIsNone(ticket.processing_started_at)
            else:
                self.assertEqual(admin_status, 200)
                self.assertEqual(ticket.status, 'in_progress')
                self.assertEqual(cancel_status, 409)
                self.assertEqual(ticket.admin_notes, 'Working on it')
