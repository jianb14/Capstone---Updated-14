"""Request budgets, route integration and repeat-safe customer submissions."""
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta
from threading import Barrier
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import OperationalError, close_old_connections
from django.http import JsonResponse
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import resolve, reverse
from django.utils import timezone

from .models import Booking, Payment, RequestRateBucket, ServiceChargeConfig, SubmissionReceipt, User
from .request_limits import GET_POLICIES, POST_POLICIES, RequestLimitsMiddleware
from .request_protection import (
    RateLimited, bucket_key, client_ip, consume_rules, deduplicate_submission,
)
from .test_booking_design_step import _base_payload


class BudgetTests(TestCase):
    def test_shared_budget_survives_local_cache_clear_and_expires(self):
        now = timezone.now()
        rule = ('example', 'user:1', 2, 60, 1)
        with patch('app.request_protection.timezone.now', return_value=now):
            consume_rules([rule])
            cache.clear()
            consume_rules([rule])
            with self.assertRaises(RateLimited) as error:
                consume_rules([rule])
            self.assertEqual(error.exception.retry_after, 60)
        with patch('app.request_protection.timezone.now', return_value=now + timedelta(seconds=60)):
            consume_rules([rule])
        self.assertEqual(RequestRateBucket.objects.get().count, 1)

    def test_group_rejection_rolls_back_other_budgets(self):
        first = ('first', 'actor', 3, 60, 1)
        second = ('second', 'actor', 1, 60, 1)
        consume_rules([second])
        with self.assertRaises(RateLimited):
            consume_rules([first, second])
        self.assertFalse(RequestRateBucket.objects.filter(pk=bucket_key('first', 'actor')).exists())
        self.assertEqual(RequestRateBucket.objects.get().count, 1)

    def test_upload_bytes_are_weighted_and_rejection_does_not_increase_count(self):
        consume_rules([('bytes', 'user:1', 10, 60, 7)])
        with self.assertRaises(RateLimited):
            consume_rules([('bytes', 'user:1', 10, 60, 4)])
        self.assertEqual(RequestRateBucket.objects.get().count, 7)
        consume_rules([('bytes', 'user:1', 10, 60, 3)])
        self.assertEqual(RequestRateBucket.objects.get().count, 10)

    def test_zero_limit_disables_rule_and_keys_do_not_store_identity(self):
        consume_rules([('disabled', 'private@gmail.com', 0, 60, 1)])
        self.assertFalse(RequestRateBucket.objects.exists())
        consume_rules([('email', 'private@gmail.com', 1, 60, 1)])
        self.assertRegex(RequestRateBucket.objects.get().key, r'^[a-f0-9]{64}$')

    def test_pruning_preserves_active_rows(self):
        past, future = timezone.now() - timedelta(seconds=1), timezone.now() + timedelta(minutes=1)
        for model in (RequestRateBucket, SubmissionReceipt):
            model.objects.create(key='expired', expires_at=past)
            model.objects.create(key='active', expires_at=future)
        call_command('prune_request_protection', stdout=io.StringIO())
        for model in (RequestRateBucket, SubmissionReceipt):
            self.assertEqual(list(model.objects.values_list('key', flat=True)), ['active'])


class RequestLimitsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = RequestLimitsMiddleware(lambda request: JsonResponse({'success': True}))
        self.user = User.objects.create_user(username='limited', email='limited@gmail.com',
                                             password='Pass123!', role='customer', email_verified=True)

    def request(self, name, method='post', args=None, user=None, data=None, **extra):
        request = getattr(self.factory, method)(reverse(name, args=args), data or {}, **extra)
        request.user = user or self.user
        request.resolver_match = resolve(request.path)
        return request

    def reserve(self, request):
        return self.middleware.process_view(request, request.resolver_match.func,
                                            request.resolver_match.args, request.resolver_match.kwargs)

    @override_settings(RATE_LIMIT_TRUSTED_PROXY_CIDRS=[])
    def test_untrusted_forwarding_header_cannot_change_ip_budget(self):
        request = self.factory.get('/', REMOTE_ADDR='198.51.100.7', HTTP_X_FORWARDED_FOR='203.0.113.8')
        self.assertEqual(client_ip(request), '198.51.100.7')

    @override_settings(RATE_LIMIT_TRUSTED_PROXY_CIDRS=['10.0.0.0/8'])
    def test_trusted_proxy_walks_chain_from_right_and_ignores_spoofed_left_entry(self):
        request = self.factory.get('/', REMOTE_ADDR='10.0.0.2',
                                   HTTP_X_FORWARDED_FOR='192.0.2.99, 203.0.113.8, 10.0.0.3')
        self.assertEqual(client_ip(request), '203.0.113.8')

    def test_all_configured_write_and_export_routes_return_429_before_view(self):
        route_args = {
            'password_reset_confirm': ['uid', 'token'], 'edit_booking': [1], 'request_booking_change': [1],
            'submit_payment': [1], 'create_paymongo_checkout': [1], 'booking_change_payment': [1, 1],
            'admin_chat_thread': [1], 'submit_review': [1], 'edit_review': [1], 'like_review': [1],
            'download_payment_receipt_pdf': [1],
        }
        limits = {name: (1, 60) for name in settings.REQUEST_RATE_LIMITS}
        with override_settings(REQUEST_RATE_LIMITS=limits):
            for method, policies in (('post', POST_POLICIES), ('get', GET_POLICIES)):
                for name in policies:
                    with self.subTest(route=name):
                        RequestRateBucket.objects.all().delete()
                        first = self.request(name, method, route_args.get(name), HTTP_ACCEPT='application/json')
                        self.assertIsNone(self.reserve(first))
                        blocked = self.reserve(self.request(name, method, route_args.get(name), HTTP_ACCEPT='application/json'))
                        self.assertEqual(blocked.status_code, 429)
                        self.assertIn('Retry-After', blocked)
                        self.assertEqual(blocked['Cache-Control'], 'no-store')

    def test_limits_are_per_account_and_payment_routes_share_a_budget(self):
        limits = {**settings.REQUEST_RATE_LIMITS, 'payment_submit': (1, 60)}
        other = User.objects.create_user(username='other-limited', role='customer')
        with override_settings(REQUEST_RATE_LIMITS=limits):
            self.assertIsNone(self.reserve(self.request('submit_payment', args=[1])))
            response = self.reserve(self.request('create_paymongo_checkout', args=[1]))
            self.assertEqual(response.status_code, 429)
            self.assertIsNone(self.reserve(self.request('create_paymongo_checkout', args=[2], user=other)))

    def test_polling_webhooks_and_anonymous_auth_redirects_are_not_budgeted(self):
        for name in ('chat_history', 'chat_typing', 'chat_presence', 'admin_chat_poll'):
            self.assertIsNone(self.reserve(self.request(name, 'get')))
        self.assertIsNone(self.reserve(self.request('paymongo_webhook', user=AnonymousUser())))
        self.assertIsNone(self.reserve(self.request('submit_payment', args=[1], user=AnonymousUser())))
        self.assertFalse(RequestRateBucket.objects.exists())

    @override_settings(UPLOAD_MAX_REQUEST_BYTES=100)
    def test_oversized_upload_rejected_before_post_is_parsed(self):
        request = self.request('submit_payment', args=[1], data={'receipt_image': SimpleUploadedFile('proof.png', b'x' * 101)})
        response = self.middleware.process_request(request)
        self.assertEqual(response.status_code, 413)
        self.assertNotIn('_post', request.__dict__)
        self.assertFalse(RequestRateBucket.objects.exists())

    def test_upload_bytes_and_request_limits_cover_other_upload_routes(self):
        limits = {**settings.REQUEST_RATE_LIMITS, 'upload_bytes': (10, 60)}
        with override_settings(REQUEST_RATE_LIMITS=limits):
            first = self.request('submit_payment', args=[1], data={'receipt_image': SimpleUploadedFile('proof.png', b'1234567')})
            self.assertIsNone(self.reserve(first))
            second = self.request('report_concern', data={'images': SimpleUploadedFile('photo.png', b'1234')})
            self.assertEqual(self.reserve(second).status_code, 429)
            self.assertEqual(RequestRateBucket.objects.get(pk=bucket_key('upload_bytes', f'user:{self.user.pk}')).count, 7)

    def test_customer_login_cannot_evade_account_limit_with_ip_or_email_case(self):
        limits = {**settings.REQUEST_RATE_LIMITS, 'login_account': (2, 60)}
        with override_settings(REQUEST_RATE_LIMITS=limits):
            for address in ('198.51.100.1', '198.51.100.2'):
                response = self.client.post(reverse('login'), {'email': ' LIMITED@GMAIL.COM ', 'password': 'wrong'}, REMOTE_ADDR=address)
                self.assertEqual(response.status_code, 200)
            response = self.client.post(reverse('login'), {'email': self.user.email, 'password': 'Pass123!'}, REMOTE_ADDR='198.51.100.3')
            self.assertEqual(response.status_code, 429)
            self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_ip_limit_applies_across_accounts_and_admin_login(self):
        limits = {**settings.REQUEST_RATE_LIMITS, 'login_ip': (1, 60)}
        with override_settings(REQUEST_RATE_LIMITS=limits):
            self.client.post(reverse('login'), {'email': 'first@gmail.com', 'password': 'wrong'})
            response = self.client.post(reverse('admin:login'), {'username': 'someone-else', 'password': 'wrong'})
            self.assertEqual(response.status_code, 429)

    def test_successful_login_resets_account_counter_but_keeps_ip_budget(self):
        self.client.post(reverse('login'), {'email': self.user.email, 'password': 'wrong'})
        response = self.client.post(reverse('login'), {'email': self.user.email, 'password': 'Pass123!'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(RequestRateBucket.objects.filter(pk=bucket_key('login_account', self.user.email)).exists())
        self.assertEqual(RequestRateBucket.objects.get(pk=bucket_key('login_ip', '127.0.0.1')).count, 2)

    def test_store_failure_fails_closed_with_503(self):
        self.client.force_login(self.user)
        with patch('app.request_limits.consume_rules', side_effect=OperationalError('offline')):
            response = self.client.post(reverse('create_booking'), _base_payload(), HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(Booking.objects.exists())
        self.assertEqual(response.json()['retry_after'], 5)

    @override_settings(FORGOT_PASSWORD_COOLDOWN_SECONDS=0, FORGOT_PASSWORD_RATE_LIMIT_PER_EMAIL=1)
    def test_password_reset_email_limit_is_shared_across_ips_and_has_retry_header(self):
        self.client.post(reverse('forgot_password'), {'email': 'nobody@gmail.com'}, REMOTE_ADDR='198.51.100.1')
        blocked = self.client.post(reverse('forgot_password'), {'email': ' NOBODY@GMAIL.COM '}, REMOTE_ADDR='198.51.100.2')
        self.assertEqual(blocked.status_code, 429)
        self.assertIn('Retry-After', blocked)

    def test_email_store_failure_returns_503_without_sending_email(self):
        with patch('app.request_protection.consume_rules', side_effect=OperationalError('offline')):
            response = self.client.post(reverse('resend_verification'), {'email': self.user.email})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response['Retry-After'], '5')


class SubmissionTests(TestCase):
    def setUp(self):
        ServiceChargeConfig.objects.create(pk=1, shop_lat='14.414', shop_lng='120.982')
        self.user = User.objects.create_user(username='repeat-customer', role='customer')
        self.client.force_login(self.user)

    def test_repeated_booking_creates_one_booking_and_replays_success(self):
        url = reverse('create_booking')
        first = self.client.post(url, _base_payload(), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(first.json()['success'])
        second = self.client.post(url, _base_payload(), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(second.json(), first.json())
        self.assertEqual(second['Idempotent-Replayed'], 'true')
        self.assertEqual(Booking.objects.count(), 1)
        third = self.client.post(url, _base_payload())
        self.assertRedirects(third, reverse('booking_page'), fetch_redirect_response=False)
        self.assertEqual(Booking.objects.count(), 1)

    def test_validation_error_is_not_replayed_and_corrected_form_can_succeed(self):
        response = self.client.post(reverse('create_booking'), _base_payload(design_theme=''), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertFalse(response.json()['success'])
        self.assertFalse(SubmissionReceipt.objects.exists())
        response = self.client.post(reverse('create_booking'), _base_payload(), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'])
        self.assertEqual(Booking.objects.count(), 1)

    def booking(self):
        return Booking.objects.create(user=self.user, event_date=timezone.localdate() + timedelta(days=10),
            event_time=time(10), event_type='Birthday', event_location='Test venue', package_type='Package A',
            total_price=5000, status='pending_payment', payment_due_at=timezone.now() + timedelta(hours=24))

    def test_repeated_manual_payment_replays_redirect_and_creates_one_payment(self):
        booking = self.booking()
        payload = {'gcash_ref_number': '1234567890123', 'sender_name': 'Customer', 'amount': '5000',
                   'payment_option': 'full', 'refund_ack': '1'}
        url = reverse('submit_payment', args=[booking.pk])
        first, second = self.client.post(url, payload), self.client.post(url, payload)
        self.assertEqual(first.url, reverse('my_payments') + '?tab=payment_history')
        self.assertEqual(second.url, first.url)
        self.assertEqual(second['Idempotent-Replayed'], 'true')
        self.assertEqual(Payment.objects.count(), 1)

    @override_settings(PAYMONGO_SECRET_KEY='sk_test_limit')
    @patch('app.views.payments.create_paymongo_checkout_session')
    def test_repeated_checkout_creates_one_provider_session(self, checkout):
        booking = self.booking()
        checkout.return_value = {'data': {'id': 'cs_repeat', 'attributes': {'checkout_url': 'https://checkout.paymongo.com/repeat'}}}
        payload = {'payment_method': 'gcash', 'amount': '5000', 'payment_option': 'full', 'refund_ack': '1'}
        url = reverse('create_paymongo_checkout', args=[booking.pk])
        first, second = self.client.post(url, payload), self.client.post(url, payload)
        self.assertEqual(first.url, 'https://checkout.paymongo.com/repeat')
        self.assertEqual(second.url, first.url)
        self.assertEqual(second['Idempotent-Replayed'], 'true')
        self.assertEqual(Payment.objects.count(), 1)
        checkout.assert_called_once()

    def test_receipt_expires_and_files_are_rewound_for_the_view(self):
        calls = []

        @deduplicate_submission
        def action(request):
            calls.append(request.FILES['image'].read())
            request._submission_succeeded = True
            return JsonResponse({'success': True})

        def send():
            request = RequestFactory().post('/test-operation/', {'image': SimpleUploadedFile('image.png', b'example')})
            request.user = self.user
            return action(request)

        send()
        self.assertEqual(send()['Idempotent-Replayed'], 'true')
        SubmissionReceipt.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        send()
        self.assertEqual(calls, [b'example', b'example'])


class ConcurrentBudgetTests(TransactionTestCase):
    def test_parallel_workers_cannot_exceed_shared_limit(self):
        workers, limit = 6, 2
        gate = Barrier(workers)
        # An existing row also exercises competing updates rather than only unique insertion.
        RequestRateBucket.objects.create(key=bucket_key('parallel', 'shared'),
                                         expires_at=timezone.now() + timedelta(minutes=1))

        def attempt(_):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                consume_rules([('parallel', 'shared', limit, 60, 1)])
                return True
            except (RateLimited, OperationalError):
                # SQLite can reject simultaneous writers; production PostgreSQL waits on row locks.
                return False
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=workers) as executor:
            accepted = sum(executor.map(attempt, range(workers)))
        self.assertLessEqual(accepted, limit)
        self.assertEqual(RequestRateBucket.objects.get().count, accepted)
        for _ in range(limit - accepted):
            consume_rules([('parallel', 'shared', limit, 60, 1)])
        with self.assertRaises(RateLimited):
            consume_rules([('parallel', 'shared', limit, 60, 1)])

    @skipUnlessDBFeature('has_select_for_update')
    def test_identical_concurrent_submissions_commit_once_and_all_replay_success(self):
        user = User.objects.create_user(username='parallel-customer', role='customer')
        booking = Booking.objects.create(user=user, event_date=timezone.localdate() + timedelta(days=10),
                                         event_type='Birthday', event_location='Test venue', total_price=5000)
        workers, gate = 4, Barrier(4)

        @deduplicate_submission
        def payment(request):
            Payment.objects.create(booking=booking, amount=5000, payment_method='gcash',
                                   transaction_ref='concurrent-receipt')
            request._submission_succeeded = True
            return JsonResponse({'success': True})

        def submit(_):
            close_old_connections()
            try:
                request = RequestFactory().post('/test-repeat/', {'amount': '5000'})
                request.user = user
                gate.wait(timeout=10)
                response = payment(request)
                return response.status_code, response.get('Idempotent-Replayed')
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=workers) as executor:
            responses = list(executor.map(submit, range(workers)))
        self.assertEqual([status for status, _ in responses], [200] * workers)
        self.assertEqual(sum(replayed == 'true' for _, replayed in responses), workers - 1)
        self.assertEqual(Payment.objects.count(), 1)

    @skipUnlessDBFeature('has_select_for_update')
    @override_settings(PAYMONGO_SECRET_KEY='sk_test_parallel')
    @patch('app.views.payments.create_paymongo_checkout_session')
    def test_different_checkout_payloads_share_booking_lock_and_reuse_one_session(self, checkout):
        from .views.payments import create_paymongo_checkout

        user = User.objects.create_user(username='parallel-checkout', role='customer')
        booking = Booking.objects.create(user=user, event_date=timezone.localdate() + timedelta(days=10),
            event_time=time(10), event_type='Birthday', event_location='Test venue', total_price=5000,
            status='pending_payment', payment_due_at=timezone.now() + timedelta(hours=24))
        checkout.return_value = {'data': {'id': 'cs_parallel', 'attributes': {'checkout_url': 'https://checkout.paymongo.com/parallel'}}}
        gate = Barrier(2)

        def submit(index):
            close_old_connections()
            try:
                request = RequestFactory().post(reverse('create_paymongo_checkout', args=[booking.pk]), {
                    'payment_method': 'gcash', 'amount': '5000', 'payment_option': 'full',
                    'refund_ack': '1', 'attempt': str(index),
                })
                request.user, request.session = user, {}
                request._messages = FallbackStorage(request)
                gate.wait(timeout=10)
                return create_paymongo_checkout(request, booking.pk).url
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(submit, range(2)))
        self.assertEqual(responses, ['https://checkout.paymongo.com/parallel'] * 2)
        self.assertEqual(Payment.objects.count(), 1)
        checkout.assert_called_once()
