"""Email OTP security, lifecycle, compatibility and PostgreSQL concurrency."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.db import OperationalError, close_old_connections
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from . import email_otp
from .models import EmailOTPChallenge, RequestRateBucket, User
from .request_protection import RateLimited, bucket_key
from .views.auth import email_verification_token_generator


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailOTPTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='otp-customer', email='customer@gmail.com', password='Passw0rd!',
            role='customer', email_verified=False,
        )

    def start(self, purpose=EmailOTPChallenge.RESET, client=None, email=None):
        client = client or self.client
        route = 'resend_verification' if purpose == EmailOTPChallenge.SIGNUP else 'forgot_password'
        response = client.post(reverse(route), {'email': email or self.user.email})
        self.assertEqual(response.status_code, 302)
        context = client.session[email_otp.session_key(purpose)]
        code = re.search(r'(?m)^[0-9]{6}$', mail.outbox[-1].body).group() if mail.outbox else None
        return context, code

    def verify(self, code, purpose=EmailOTPChallenge.RESET, client=None, **extra):
        route = 'verify_account_otp' if purpose == EmailOTPChallenge.SIGNUP else 'verify_password_otp'
        return (client or self.client).post(reverse(route), {'code': code}, **extra)

    def authorize(self):
        context, code = self.start()
        self.assertRedirects(self.verify(code), reverse('reset_password_otp'), fetch_redirect_response=False)
        return context

    def password_post(self, client=None, password='UpdatedPassw0rd!'):
        return (client or self.client).post(reverse('reset_password_otp'), {
            'password': password, 'confirm_password': password,
        })

    def test_signup_code_preserves_leading_zeros_and_never_logs_in_automatically(self):
        with patch('app.email_otp.secrets.randbelow', return_value=42):
            context, code = self.start(EmailOTPChallenge.SIGNUP)
        self.assertEqual(code, '000042')
        challenge = EmailOTPChallenge.objects.get(pk=context['id'])
        self.assertEqual(len(challenge.code_digest), 64)
        self.assertNotEqual(challenge.code_digest, code)
        self.assertEqual(set(context), {'id', 'binding', 'email', 'issued_at'})
        self.assertRedirects(self.verify(code, EmailOTPChallenge.SIGNUP), reverse('login'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        challenge.refresh_from_db()
        self.assertTrue(self.user.email_verified)
        self.assertIsNotNone(challenge.consumed_at)
        self.assertEqual(challenge.code_digest, '')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_complete_recovery_consumes_grant_and_requires_explicit_login(self):
        context = self.authorize()
        challenge = EmailOTPChallenge.objects.get(pk=context['id'])
        self.assertEqual(challenge.code_digest, '')
        self.assertIsNotNone(challenge.verified_at)
        self.assertIsNone(challenge.consumed_at)
        self.assertRedirects(self.password_post(), reverse('login'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('UpdatedPassw0rd!'))
        self.assertFalse(self.user.email_verified)  # Recovery never verifies an account.
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertNotIn(email_otp.session_key(EmailOTPChallenge.RESET), self.client.session)
        challenge.refresh_from_db()
        self.assertIsNotNone(challenge.consumed_at)

    def test_reset_form_cannot_be_used_directly_or_with_unverified_challenge(self):
        self.assertRedirects(self.password_post(), reverse('forgot_password'), fetch_redirect_response=False)
        self.start()
        self.assertRedirects(self.password_post(), reverse('forgot_password'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Passw0rd!'))

    def test_code_and_grant_expire_independently(self):
        context, code = self.start()
        challenge = EmailOTPChallenge.objects.get(pk=context['id'])
        with patch('app.email_otp.timezone.now', return_value=challenge.expires_at):
            self.assertContains(self.verify(code), 'invalid, expired, or already used')
        self.verify(code)
        challenge.refresh_from_db()
        with patch('app.email_otp.timezone.now', return_value=challenge.grant_expires_at):
            self.assertRedirects(self.password_post(), reverse('forgot_password'), fetch_redirect_response=False)

    def test_wrong_code_or_malformed_code_does_not_authorize_reset(self):
        self.start()
        for code in ('12345', '1234567', '１２３４５６', 'abcdef'):
            self.assertContains(self.verify(code), 'invalid, expired, or already used')
        self.assertFalse(EmailOTPChallenge.objects.filter(verified_at__isnull=False).exists())

    def test_wrong_attempt_limit_survives_new_session_ip_and_resend(self):
        context, code = self.start()
        wrong = '999999' if code != '999999' else '888888'
        for _ in range(4):
            self.assertEqual(self.verify(wrong).status_code, 200)
        with override_settings(FORGOT_PASSWORD_COOLDOWN_SECONDS=0):
            other = Client()
            _context, new_code = self.start(client=other)
        self.assertEqual(self.verify(wrong, client=other, REMOTE_ADDR='198.51.100.4').status_code, 429)
        blocked = self.verify(new_code, client=other, REMOTE_ADDR='198.51.100.5')
        self.assertEqual(blocked.status_code, 429)
        self.assertIn('Retry-After', blocked)
        self.assertFalse(EmailOTPChallenge.objects.filter(verified_at__isnull=False).exists())
        counter = RequestRateBucket.objects.get(pk=bucket_key('email-otp:wrong:reset', self.user.email))
        self.assertEqual(counter.count, 5)
        # Wait-window expiry does not erase or bypass an expired OTP.
        with patch('app.email_otp.timezone.now', return_value=counter.expires_at + timedelta(seconds=1)):
            self.assertEqual(self.verify(new_code, client=other).status_code, 200)

    @override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
    def test_otp_guesses_remain_limited_if_general_request_limits_are_disabled(self):
        self.start()
        for _ in range(5):
            response = self.verify('invalid')
        self.assertEqual(response.status_code, 429)

    @override_settings(EMAIL_OTP_VERIFY_PER_IP=2)
    def test_ip_limit_applies_across_purposes_and_accounts(self):
        self.start()
        self.verify('invalid')
        self.verify('invalid')
        response = self.verify('invalid')
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response)

    def test_cross_browser_binding_is_required_even_when_challenge_id_is_known(self):
        context, code = self.start()
        other = Client()
        session = other.session
        session[email_otp.session_key(EmailOTPChallenge.RESET)] = {**context, 'binding': 'different-browser'}
        session.save()
        self.assertContains(self.verify(code, client=other), 'invalid, expired, or already used')
        self.assertRedirects(self.password_post(client=other), reverse('forgot_password'), fetch_redirect_response=False)
        self.assertEqual(self.verify(code).status_code, 302)

    def test_codes_cannot_cross_purposes_or_accounts(self):
        context, code = self.start(EmailOTPChallenge.SIGNUP)
        session = self.client.session
        session[email_otp.session_key(EmailOTPChallenge.RESET)] = context
        session.save()
        self.assertContains(self.verify(code), 'invalid, expired, or already used')
        other = User.objects.create_user(username='other-otp', email='other@gmail.com', role='customer')
        EmailOTPChallenge.objects.filter(pk=context['id']).update(user=other)
        self.assertContains(self.verify(code, EmailOTPChallenge.SIGNUP), 'invalid, expired, or already used')

    def test_code_cannot_be_replayed_after_verification(self):
        context, code = self.start()
        self.verify(code)
        request = RequestFactory().post('/forgot-password/verify/')
        self.assertEqual(email_otp.verify_code(request, EmailOTPChallenge.RESET, context, code), (False, 0))

    @override_settings(FORGOT_PASSWORD_COOLDOWN_SECONDS=0)
    def test_successful_resend_invalidates_previous_code_and_reset_grant(self):
        context, old_code = self.start()
        self.verify(old_code)
        with patch('app.email_otp.secrets.randbelow', return_value=731280):
            response = self.client.post(reverse('verify_password_otp'), {'action': 'resend'})
        self.assertEqual(response.status_code, 302)
        old = EmailOTPChallenge.objects.get(pk=context['id'])
        self.assertIsNotNone(old.consumed_at)
        self.assertRedirects(self.password_post(), reverse('forgot_password'), fetch_redirect_response=False)
        self.assertContains(self.verify(old_code), 'invalid, expired, or already used')
        self.assertEqual(self.verify('731280').status_code, 302)

    def test_resend_cooldown_is_shared_by_email_across_ip_and_session(self):
        self.start()
        other = Client()
        response = other.post(reverse('forgot_password'), {'email': ' CUSTOMER@GMAIL.COM '}, REMOTE_ADDR='198.51.100.9')
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response)
        self.assertEqual(len(mail.outbox), 1)

    def test_known_and_unknown_forgot_password_responses_have_the_same_flow(self):
        self.start()
        known = self.client.get(reverse('verify_password_otp'))
        with override_settings(FORGOT_PASSWORD_COOLDOWN_SECONDS=0):
            response = self.client.post(reverse('forgot_password'), {'email': 'unknown@gmail.com'})
        self.assertRedirects(response, reverse('verify_password_otp'), fetch_redirect_response=False)
        unknown = self.client.get(reverse('verify_password_otp'))
        for page in (known, unknown):
            self.assertContains(page, 'If the email exists and is eligible')
            self.assertContains(page, 'name="code"')
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(self.verify('123456'), 'invalid, expired, or already used')
        self.assertEqual(EmailOTPChallenge.objects.count(), 1)

    def test_initial_send_failure_creates_no_usable_challenge_or_grant(self):
        with patch('app.email_otp.send_mail', side_effect=RuntimeError('Provider down')), self.assertLogs(level='ERROR'):
            context, _code = self.start()
        self.assertFalse(EmailOTPChallenge.objects.filter(consumed_at__isnull=True).exists())
        self.assertRedirects(self.password_post(), reverse('forgot_password'), fetch_redirect_response=False)

    @override_settings(FORGOT_PASSWORD_COOLDOWN_SECONDS=0)
    def test_failed_resend_keeps_last_accepted_code_usable(self):
        context, code = self.start()
        with patch('app.email_otp.send_mail', return_value=0), self.assertLogs(level='ERROR'):
            self.client.post(reverse('verify_password_otp'), {'action': 'resend'})
        self.assertEqual(self.client.session[email_otp.session_key(EmailOTPChallenge.RESET)]['id'], context['id'])
        self.assertEqual(self.verify(code).status_code, 302)

    def test_password_and_email_changes_revoke_existing_codes_and_grants(self):
        context = self.authorize()
        self.user.set_password('ExternallyChanged!123')
        self.user.save(update_fields=['password'])
        self.assertRedirects(self.password_post(), reverse('forgot_password'), fetch_redirect_response=False)
        challenge = EmailOTPChallenge.objects.get(pk=context['id'])
        self.assertFalse(email_otp.grant_valid(challenge, self.user, context))
        self.user.email = 'changed@gmail.com'
        self.user.save(update_fields=['email'])
        self.assertFalse(email_otp.bound(challenge, self.user, context))

    def test_inactive_account_cannot_complete_recovery(self):
        self.authorize()
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        self.assertRedirects(self.password_post(), reverse('forgot_password'), fetch_redirect_response=False)

    def test_password_validation_failure_does_not_consume_grant(self):
        context = self.authorize()
        response = self.password_post(password='123')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(EmailOTPChallenge.objects.get(pk=context['id']).consumed_at)
        self.assertEqual(self.password_post().status_code, 302)

    def test_mismatched_passwords_keep_the_verified_grant(self):
        context = self.authorize()
        response = self.client.post(reverse('reset_password_otp'), {
            'password': 'UpdatedPassw0rd!', 'confirm_password': 'SomethingElse!123',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(EmailOTPChallenge.objects.get(pk=context['id']).consumed_at)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Passw0rd!'))

    @override_settings(FORGOT_PASSWORD_COOLDOWN_SECONDS=0)
    def test_resend_regenerates_a_code_that_randomly_matches_the_previous_one(self):
        with patch('app.email_otp.secrets.randbelow', side_effect=[42, 42, 73]):
            _context, old = self.start()
            self.client.post(reverse('verify_password_otp'), {'action': 'resend'})
        self.assertEqual(old, '000042')
        self.assertRegex(mail.outbox[-1].body, r'(?m)^000073$')
        self.assertContains(self.verify(old), 'invalid, expired, or already used')
        self.assertEqual(self.verify('000073').status_code, 302)

    def test_consumed_grant_cannot_be_restored_from_old_session_data(self):
        context = self.authorize()
        self.password_post()
        session = self.client.session
        session[email_otp.session_key(EmailOTPChallenge.RESET)] = context
        session.save()
        self.assertRedirects(self.password_post(password='AnotherPassword!123'), reverse('forgot_password'), fetch_redirect_response=False)

    def test_legacy_reset_link_still_works_and_revokes_recovery_grant(self):
        self.authorize()
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        url = reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {'password': 'LegacyPassword!123', 'confirm_password': 'LegacyPassword!123'}).status_code, 302)
        self.assertFalse(EmailOTPChallenge.objects.filter(purpose='reset', consumed_at__isnull=True).exists())
        self.assertRedirects(self.password_post(), reverse('forgot_password'), fetch_redirect_response=False)

    def test_legacy_verification_link_get_is_read_only_and_post_revokes_codes(self):
        self.start(EmailOTPChallenge.SIGNUP)
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = email_verification_token_generator.make_token(self.user)
        url = reverse('verify_email', kwargs={'uidb64': uid, 'token': token})
        self.assertContains(self.client.get(url), 'Confirm Email')
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(EmailOTPChallenge.objects.filter(purpose='signup', consumed_at__isnull=True).exists())

    def test_get_requests_do_not_send_email_or_modify_account_state(self):
        for name in ('register', 'forgot_password', 'resend_verification', 'verify_account_otp', 'verify_password_otp', 'reset_password_otp'):
            self.client.get(reverse(name))
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(EmailOTPChallenge.objects.exists())

    def test_verify_and_resend_require_csrf(self):
        context, code = self.start()
        other = Client(enforce_csrf_checks=True)
        session = other.session
        session[email_otp.session_key(EmailOTPChallenge.RESET)] = context
        session.save()
        for data in ({'code': code}, {'action': 'resend'}):
            self.assertEqual(other.post(reverse('verify_password_otp'), data).status_code, 403)
        self.assertEqual(other.post(reverse('reset_password_otp'), {'password': 'Anything!123'}).status_code, 403)

    def test_shared_store_failure_fails_closed(self):
        self.start()
        with patch('app.email_otp.consume_rules', side_effect=OperationalError('offline')):
            response = self.verify('123456')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response['Retry-After'], '5')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailOTPConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='concurrent-otp', email='parallel@gmail.com',
                                             password='Passw0rd!', role='customer')
        self.context = email_otp.new_context(self.user.email)
        with patch('app.email_otp.secrets.randbelow', return_value=731280):
            email_otp.send_code(self.user, EmailOTPChallenge.RESET, self.context)

    def parallel(self, operation):
        barrier = Barrier(2)
        def run(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return operation(index)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(run, range(2)))

    @skipUnlessDBFeature('has_select_for_update')
    def test_concurrent_code_verification_succeeds_once(self):
        def operation(index):
            request = RequestFactory().post('/forgot-password/verify/', REMOTE_ADDR=f'198.51.100.{index + 1}')
            return email_otp.verify_code(request, EmailOTPChallenge.RESET, self.context, '731280')[0]
        self.assertEqual(self.parallel(operation).count(True), 1)

    @skipUnlessDBFeature('has_select_for_update')
    def test_concurrent_password_submission_consumes_grant_once(self):
        request = RequestFactory().post('/forgot-password/verify/')
        self.assertTrue(email_otp.verify_code(request, EmailOTPChallenge.RESET, self.context, '731280')[0])
        results = self.parallel(lambda index: bool(email_otp.reset_password(self.context, f'NewPassword!{index}123')))
        self.assertEqual(results.count(True), 1)
        self.assertIsNotNone(EmailOTPChallenge.objects.get(pk=self.context['id']).consumed_at)

    @skipUnlessDBFeature('has_select_for_update')
    def test_concurrent_wrong_guesses_cannot_exceed_budget(self):
        request = RequestFactory().post('/forgot-password/verify/')
        for _ in range(4):
            email_otp.verify_code(request, EmailOTPChallenge.RESET, self.context, 'invalid')
        def operation(index):
            try:
                accepted, retry = email_otp.verify_code(request, EmailOTPChallenge.RESET, self.context, 'invalid')
                return retry > 0
            except RateLimited:
                return True
        self.assertEqual(self.parallel(operation), [True, True])
        bucket = RequestRateBucket.objects.get(pk=bucket_key('email-otp:wrong:reset', self.user.email))
        self.assertEqual(bucket.count, 5)
