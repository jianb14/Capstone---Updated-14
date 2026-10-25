"""Pending signup continuation, replacement email and authenticated password OTPs."""
import re
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import email_otp
from .models import EmailOTPChallenge, RequestRateBucket, User
from .request_protection import bucket_key


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class OTPAccountFlowTests(TestCase):
    old_password = 'InitialPassword!123'
    new_password = 'UpdatedPassword!456'

    def setUp(self):
        self.user = User.objects.create_user(username='pending-user', email='pending@gmail.com',
            password=self.old_password, first_name='Original', role='customer', email_verified=False)

    def latest_code(self):
        return re.search(r'(?m)^[0-9]{6}$', mail.outbox[-1].body).group()

    def signup(self):
        response = self.client.post(reverse('resend_verification'), {'email': self.user.email})
        self.assertEqual(response.status_code, 302)
        # The banner requires account ownership, not a public email-only request.
        self.client.post(reverse('login'), {'email': self.user.email, 'password': self.old_password})
        return self.latest_code()

    def replacement(self, email='replacement@gmail.com', password=None, **extra):
        return self.client.post(reverse('change_signup_email'), {'email': email,
            'password': self.old_password if password is None else password}, **extra)

    def start_change(self, client=None, **extra):
        client = client or self.client
        return client.post(reverse('change_password'), {'old_password': self.old_password,
            'new_password1': self.new_password, 'new_password2': self.new_password}, **extra)

    def verify_change(self, code=None, client=None):
        return (client or self.client).post(reverse('verify_change_password_otp'), {'code': code or self.latest_code()})

    def test_duplicate_signup_shows_persistent_continue_without_overwriting_account(self):
        code = self.signup()
        response = self.client.post(reverse('register'), {'email': self.user.email, 'username': self.user.username,
            'first_name': 'Overwritten', 'password': 'DifferentPassword!123', 'confirm_password': 'DifferentPassword!123'})
        self.assertContains(response, 'Continue Verification')
        self.assertContains(response, reverse('continue_verification'))
        self.assertEqual(len(mail.outbox), 1)
        response = self.client.post(reverse('continue_verification'), {'email': self.user.email})
        self.assertRedirects(response, reverse('verify_account_otp'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Original')
        self.assertTrue(self.user.check_password(self.old_password))
        self.assertRedirects(self.client.post(reverse('verify_account_otp'), {'code': code}), reverse('login'), fetch_redirect_response=False)

    def test_login_and_navigation_resume_same_code_without_extra_mail(self):
        self.signup()
        self.assertContains(self.client.get(reverse('login')), 'Continue Verification')
        self.assertContains(self.client.get(reverse('register')), 'Continue Verification')
        response = self.client.post(reverse('login'), {'email': self.user.email.upper(), 'password': self.old_password})
        self.assertContains(response, 'Continue Verification')
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.get(reverse('continue_verification')).status_code, 405)

    def test_different_browser_must_prove_account_ownership_before_continue(self):
        other = Client()
        response = other.post(reverse('continue_verification'), {'email': self.user.email})
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(other.post(reverse('login'), {'email': self.user.email, 'password': self.old_password}), 'Continue Verification')
        response = other.post(reverse('continue_verification'))
        self.assertRedirects(response, reverse('verify_account_otp'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.client.get(reverse('change_signup_email')).status_code, 302)

    def test_change_email_requires_original_password_and_get_does_not_send(self):
        self.signup()
        self.assertEqual(self.client.get(reverse('change_signup_email')).status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(self.replacement(password='wrong'), 'original password')
        self.assertEqual(len(mail.outbox), 1)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'pending@gmail.com')
        self.assertFalse(self.user.email_verified)

    def test_email_changes_only_after_new_otp_and_original_code_is_invalidated(self):
        old = self.signup()
        RequestRateBucket.objects.all().delete()
        self.assertRedirects(self.replacement(), reverse('verify_account_otp'), fetch_redirect_response=False)
        new = self.latest_code()
        self.assertEqual(mail.outbox[-1].to, ['replacement@gmail.com'])
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'pending@gmail.com')
        self.assertFalse(self.user.email_verified)
        page = self.client.post(reverse('verify_account_otp'), {'code': old})
        self.assertContains(page, 'invalid, expired, or already used')
        self.assertRedirects(self.client.post(reverse('verify_account_otp'), {'code': new}), reverse('login'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'replacement@gmail.com')
        self.assertTrue(self.user.email_verified)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_duplicate_email_is_rechecked_when_new_code_is_verified(self):
        self.signup()
        RequestRateBucket.objects.all().delete()
        self.replacement()
        code = self.latest_code()
        User.objects.create_user(username='claimed', email='replacement@gmail.com', password=self.old_password, role='customer')
        response = self.client.post(reverse('verify_account_otp'), {'code': code})
        self.assertContains(response, 'already registered')
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)
        self.assertEqual(self.user.email, 'pending@gmail.com')

    def test_change_email_provider_failure_preserves_original_challenge(self):
        old = self.signup()
        RequestRateBucket.objects.all().delete()
        with patch('app.email_otp.send_mail', side_effect=RuntimeError('provider unavailable')):
            self.assertContains(self.replacement(), 'account email has not changed')
        self.assertRedirects(self.client.post(reverse('verify_account_otp'), {'code': old}), reverse('login'), fetch_redirect_response=False)

    def test_resend_to_candidate_keeps_original_account_binding(self):
        self.signup()
        RequestRateBucket.objects.all().delete()
        self.replacement()
        old = self.latest_code()
        RequestRateBucket.objects.all().delete()
        self.client.post(reverse('verify_account_otp'), {'action': 'resend'})
        code = self.latest_code()
        self.assertNotEqual(old, code)
        self.assertEqual(mail.outbox[-1].to, ['replacement@gmail.com'])
        self.assertRedirects(self.client.post(reverse('verify_account_otp'), {'code': code}), reverse('login'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'replacement@gmail.com')

    def test_changing_recipient_does_not_reset_account_wrong_guess_budget(self):
        self.signup()
        for _ in range(4):
            self.client.post(reverse('verify_account_otp'), {'code': 'wrong'})
        RequestRateBucket.objects.exclude(key=bucket_key('email-otp:wrong:signup:account', str(self.user.pk))).delete()
        self.replacement(REMOTE_ADDR='198.51.100.10')
        response = self.client.post(reverse('verify_account_otp'), {'code': 'wrong'}, REMOTE_ADDR='198.51.100.11')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.client.post(reverse('verify_account_otp'), {'code': self.latest_code()}, REMOTE_ADDR='198.51.100.12').status_code, 429)

    def test_email_password_guess_budget_is_shared_across_sessions(self):
        self.signup()
        for _ in range(5):
            self.replacement(password='wrong')
        self.assertEqual(self.replacement(REMOTE_ADDR='198.51.100.20').status_code, 429)
        self.assertEqual(len(mail.outbox), 1)

    def test_authenticated_change_stages_only_hash_until_otp_then_keeps_current_session(self):
        self.user.email_verified = True
        self.user.save(update_fields=['email_verified'])
        self.client.force_login(self.user)
        response = self.start_change(HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['otp_required'])
        self.assertEqual(response.json()['redirect_url'], reverse('verify_change_password_otp'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))
        context = self.client.session[email_otp.session_key(EmailOTPChallenge.CHANGE)]
        self.assertNotIn(self.new_password, str(dict(self.client.session)))
        challenge = EmailOTPChallenge.objects.get(pk=context['id'])
        self.assertNotEqual(challenge.pending_password_hash, self.new_password)
        self.assertNotEqual(challenge.pending_password_hash, '')
        self.assertRedirects(self.verify_change(), reverse('customer_profile'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))
        self.assertEqual(self.client.session['_auth_user_hash'], self.user.get_session_auth_hash())
        challenge.refresh_from_db()
        self.assertEqual(challenge.pending_password_hash, '')
        self.assertIsNotNone(challenge.consumed_at)
        self.assertNotIn(email_otp.session_key(EmailOTPChallenge.CHANGE), self.client.session)

    def test_change_password_requires_current_password_and_existing_password_validation(self):
        self.client.force_login(self.user)
        for old, password in (('wrong', self.new_password), (self.old_password, '123')):
            response = self.client.post(reverse('change_password'), {'old_password': old,
                'new_password1': password, 'new_password2': password}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertFalse(response.json()['success'])
        self.assertEqual(len(mail.outbox), 0)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_change_otp_expiry_wrong_code_and_other_session_cannot_change_password(self):
        self.client.force_login(self.user)
        self.start_change()
        code = self.latest_code()
        other = Client()
        other.force_login(self.user)
        self.assertRedirects(other.post(reverse('verify_change_password_otp'), {'code': code}), reverse('customer_profile'), fetch_redirect_response=False)
        response = self.verify_change('wrong')
        self.assertContains(response, 'invalid, expired, or already used')
        challenge = EmailOTPChallenge.objects.get(purpose=EmailOTPChallenge.CHANGE)
        EmailOTPChallenge.objects.filter(pk=challenge.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertContains(self.verify_change(code), 'invalid, expired, or already used')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_change_otp_cannot_be_used_by_another_authenticated_account(self):
        self.client.force_login(self.user)
        self.start_change()
        code = self.latest_code()
        other_user = User.objects.create_user(username='other', email='other@gmail.com', password=self.old_password, role='customer')
        other = Client()
        other.force_login(other_user)
        session = other.session
        session[email_otp.session_key(EmailOTPChallenge.CHANGE)] = self.client.session[email_otp.session_key(EmailOTPChallenge.CHANGE)]
        session.save()
        self.assertEqual(other.post(reverse('verify_change_password_otp'), {'code': code}).status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_change_provider_failure_creates_no_usable_change_or_false_success(self):
        self.client.force_login(self.user)
        with patch('app.email_otp.send_mail', return_value=0):
            response = self.start_change(HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()['success'])
        self.assertNotIn(email_otp.session_key(EmailOTPChallenge.CHANGE), self.client.session)
        self.assertFalse(EmailOTPChallenge.objects.filter(consumed_at__isnull=True).exists())
        self.assertEqual(EmailOTPChallenge.objects.get().pending_password_hash, '')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_change_resend_invalidates_old_code_and_preserves_staged_password(self):
        self.client.force_login(self.user)
        self.start_change()
        old = self.latest_code()
        RequestRateBucket.objects.all().delete()
        self.client.post(reverse('verify_change_password_otp'), {'action': 'resend'})
        code = self.latest_code()
        self.assertContains(self.verify_change(old), 'invalid, expired, or already used')
        self.assertRedirects(self.verify_change(code), reverse('customer_profile'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))

    def test_admin_returns_to_admin_profile_after_change_verification(self):
        self.user.role = 'admin'
        self.user.save(update_fields=['role'])
        self.client.force_login(self.user)
        self.start_change()
        self.assertRedirects(self.verify_change(), reverse('admin_profile'), fetch_redirect_response=False)

    def test_six_named_fields_support_no_javascript_and_leading_zeros(self):
        with patch('app.email_otp.secrets.randbelow', return_value=42):
            self.signup()
        response = self.client.post(reverse('verify_account_otp'), {'digit_' + str(i): digit for i, digit in enumerate('000042', 1)})
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)

    def test_new_post_actions_are_csrf_protected_and_get_does_not_modify(self):
        self.signup()
        self.client.force_login(self.user)
        strict = Client(enforce_csrf_checks=True)
        strict.cookies = self.client.cookies
        for route in ('continue_verification', 'change_signup_email', 'change_password', 'verify_change_password_otp'):
            self.assertEqual(strict.post(reverse(route), {'email': 'next@gmail.com'}).status_code, 403)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailOTPChallenge.objects.count(), 1)

    def test_password_change_invalidates_outstanding_recovery_codes_and_grants(self):
        self.client.post(reverse('forgot_password'), {'email': self.user.email})
        recovery = self.client.session[email_otp.session_key(EmailOTPChallenge.RESET)]
        self.client.post(reverse('verify_password_otp'), {'code': self.latest_code()})
        self.client.force_login(self.user)
        self.start_change()
        self.verify_change()
        self.assertIsNotNone(EmailOTPChallenge.objects.get(pk=recovery['id']).consumed_at)
        self.assertRedirects(self.client.post(reverse('reset_password_otp'), {'password': 'AnotherPassword!123',
            'confirm_password': 'AnotherPassword!123'}), reverse('forgot_password'), fetch_redirect_response=False)

    def test_resend_failure_preserves_staged_password_and_usable_previous_change_code(self):
        self.client.force_login(self.user)
        self.start_change()
        code = self.latest_code()
        RequestRateBucket.objects.all().delete()
        with patch('app.email_otp.send_mail', side_effect=RuntimeError('provider unavailable')):
            self.client.post(reverse('verify_change_password_otp'), {'action': 'resend'})
        self.assertRedirects(self.verify_change(code), reverse('customer_profile'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))

    def test_issuance_refuses_stale_current_password_validation(self):
        old_hash = self.user.password
        self.user.set_password('ChangedElsewhere!123')
        self.user.save(update_fields=['password'])
        context = email_otp.new_context(self.user.email)
        from django.contrib.auth.hashers import make_password
        self.assertFalse(email_otp.send_code(self.user, EmailOTPChallenge.CHANGE, context,
            expected_password=old_hash, pending_password_hash=make_password(self.new_password)))
        self.assertEqual(len(mail.outbox), 0)

    def test_change_send_limits_survive_new_session_and_ip(self):
        self.client.force_login(self.user)
        self.start_change()
        other = Client()
        other.force_login(self.user)
        response = self.start_change(client=other, REMOTE_ADDR='198.51.100.8', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(mail.outbox), 1)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_account_lockout_remains_visible_after_refresh(self):
        self.signup()
        for _ in range(5):
            self.client.post(reverse('verify_account_otp'), {'code': 'wrong'})
        response = self.client.get(reverse('verify_account_otp'))
        self.assertGreater(response.context['verify_wait'], 0)
        self.assertContains(response, 'data-verify-wait="')

    def test_database_read_failure_renders_recoverable_503_instead_of_error_page(self):
        from django.db import OperationalError
        self.signup()
        with patch('app.email_otp.get_challenge', side_effect=OperationalError('offline')):
            response = self.client.get(reverse('verify_account_otp'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response['Retry-After'], '5')

    def test_ambiguous_legacy_email_does_not_authenticate_or_crash(self):
        User.objects.create_user(username='legacy-duplicate', email=self.user.email.upper(),
            password=self.old_password, role='customer', email_verified=True)
        response = self.client.post(reverse('login'), {'email': self.user.email, 'password': self.old_password})
        self.assertContains(response, 'Invalid email or password.')
        self.assertNotIn('_auth_user_id', self.client.session)
