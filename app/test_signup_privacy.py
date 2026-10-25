"""Ownership-aware signup banners and public account-status privacy."""
from datetime import timedelta
from unittest.mock import patch
import re

from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from . import email_otp, signup_lifecycle
from .models import EmailOTPChallenge, RequestRateBucket, User
from .views.auth import email_verification_token_generator


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SignupPrivacyTests(TestCase):
    password = 'PrivatePassword!123'

    def payload(self, **overrides):
        return dict({'first_name': 'Private', 'last_name': 'Customer', 'username': 'signup-private',
            'email': 'private@gmail.com', 'phone': '09171234567', 'password': self.password,
            'confirm_password': self.password}, **overrides)

    def create_signup(self, **overrides):
        data = self.payload(**overrides)
        response = self.client.post(reverse('register'), data)
        self.assertRedirects(response, reverse('verify_account_otp'), fetch_redirect_response=False)
        return User.objects.get(username=data['username'])

    def login(self, user, client=None, password=None):
        return (client or self.client).post(reverse('login'), {'email': user.email,
            'password': self.password if password is None else password})

    def test_new_visitor_has_no_verification_shortcut_or_banner(self):
        for name in ('login', 'register'):
            response = self.client.get(reverse(name))
            self.assertNotContains(response, 'Finish verifying an account')
            self.assertNotContains(response, 'Continue Verification')
            self.assertNotContains(response, 'Pending account verification')
        self.assertEqual(len(mail.outbox), 0)

    def test_own_signup_banner_is_masked_and_continue_needs_no_email_field(self):
        user = self.create_signup()
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'Continue Verification')
        aside = response.content.decode().split('<aside', 1)[1].split('</aside>', 1)[0]
        self.assertIn('p***@gmail.com', aside)
        self.assertNotIn(user.email, aside)
        self.assertNotIn('name="email"', aside)
        self.assertNotIn(user.username, aside)
        self.assertContains(response, 'value="private@gmail.com"')
        self.assertRedirects(self.client.post(reverse('continue_verification')), reverse('verify_account_otp'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertIn('no-store', response['Cache-Control'])

    def test_public_email_only_request_does_not_create_private_banner(self):
        user = User.objects.create_user(username='existing', email='existing@gmail.com', password=self.password, role='customer')
        self.client.post(reverse('resend_verification'), {'email': user.email})
        for name in ('login', 'register'):
            response = self.client.get(reverse(name))
            self.assertNotContains(response, 'Continue Verification')
            self.assertNotContains(response, user.email)
        self.assertNotIn(signup_lifecycle.RESUME_KEY, self.client.session)

    def test_login_reveals_pending_status_only_after_correct_credentials_and_does_not_send(self):
        user = User.objects.create_user(username='existing', email='existing@gmail.com', password=self.password, role='customer')
        response = self.login(user, password='wrong')
        self.assertContains(response, 'Invalid email or password.')
        self.assertNotContains(response, 'Continue Verification')
        response = self.login(user)
        self.assertContains(response, 'Continue Verification')
        self.assertContains(response, 'value="existing@gmail.com"')
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertNotContains(response, 'value="' + self.password + '"')
        self.assertRedirects(self.client.post(reverse('continue_verification')), reverse('verify_account_otp'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [user.email])

    def test_public_registration_email_and_username_conflicts_share_new_signup_response(self):
        pending = User.objects.create_user(username='pending', email='pending@gmail.com', password=self.password, role='customer')
        verified = User.objects.create_user(username='verified', email='verified@gmail.com', password=self.password,
            role='customer', email_verified=True)
        cases = [self.payload(email=pending.email), self.payload(email=verified.email),
                 self.payload(username=verified.username, email='unused-name@gmail.com'), self.payload(email='brandnew@gmail.com')]
        notices = []
        for index, data in enumerate(cases):
            client = Client()
            response = client.post(reverse('register'), data, REMOTE_ADDR='198.51.100.' + str(index + 1))
            self.assertRedirects(response, reverse('verify_account_otp'), fetch_redirect_response=False)
            page = client.get(response.url)
            self.assertNotContains(page, 'already exists')
            self.assertNotContains(page, 'not yet verified')
            self.assertNotContains(page, 'Continue Verification')
            notices.append([(str(item), item.tags) for item in page.context['messages']])
        self.assertTrue(all(value == notices[0] for value in notices))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(User.objects.count(), 3)
        pending.refresh_from_db()
        self.assertFalse(pending.email_verified)
        self.assertTrue(pending.check_password(self.password))

    def test_continue_without_ownership_cannot_select_an_account_from_posted_email(self):
        user = User.objects.create_user(username='existing', email='existing@gmail.com', password=self.password, role='customer')
        self.assertRedirects(self.client.post(reverse('continue_verification'), {'email': user.email}), reverse('login'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(EmailOTPChallenge.objects.exists())

    def test_owned_continue_ignores_other_email_and_never_switches_accounts(self):
        first = self.create_signup()
        second = User.objects.create_user(username='second', email='second@gmail.com', password=self.password, role='customer')
        self.client.post(reverse('continue_verification'), {'email': second.email})
        context = self.client.session[signup_lifecycle.OTP_KEY]
        self.assertEqual(EmailOTPChallenge.objects.get(pk=context['id']).user_id, first.pk)
        self.assertEqual(len(mail.outbox), 1)

    def test_multiple_signups_keep_only_latest_private_continuation(self):
        with patch('app.email_otp.secrets.randbelow', return_value=123456):
            first = self.create_signup()
        first_code = re.search(r'(?m)^[0-9]{6}$', mail.outbox[-1].body).group()
        RequestRateBucket.objects.all().delete()
        with patch('app.email_otp.secrets.randbelow', return_value=654321):
            second = self.create_signup(username='second-user', email='second@gmail.com')
        page = self.client.get(reverse('login'))
        self.assertContains(page, 's***@gmail.com')
        self.assertNotContains(page, 'p***@gmail.com')
        self.assertEqual(self.client.session[signup_lifecycle.RESUME_KEY]['user_id'], second.pk)
        self.assertEqual(User.objects.count(), 2)
        self.assertContains(self.client.post(reverse('verify_account_otp'), {'code': first_code}), 'invalid, expired, or already used')
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.email_verified)
        self.assertFalse(second.email_verified)
        self.assertContains(self.login(first), 'p***@gmail.com')
        self.assertNotIn(signup_lifecycle.OTP_KEY, self.client.session)
        RequestRateBucket.objects.all().delete()
        self.client.post(reverse('continue_verification'))
        self.assertEqual(mail.outbox[-1].to, [first.email])

    def test_use_another_account_forgets_browser_state_without_deleting_account(self):
        user = self.create_signup()
        identifier = self.client.session[signup_lifecycle.OTP_KEY]['id']
        self.assertEqual(self.client.get(reverse('dismiss_signup_verification')).status_code, 405)
        self.assertRedirects(self.client.post(reverse('dismiss_signup_verification')), reverse('login'), fetch_redirect_response=False)
        self.assertNotContains(self.client.get(reverse('login')), 'Continue Verification')
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertTrue(EmailOTPChallenge.objects.filter(pk=identifier, consumed_at__isnull=True).exists())
        self.assertNotIn(signup_lifecycle.RESUME_KEY, self.client.session)
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(strict.post(reverse('dismiss_signup_verification')).status_code, 403)

    def test_verified_or_changed_account_does_not_leave_stale_private_banner(self):
        user = self.create_signup()
        user.email_verified = True
        user.save(update_fields=['email_verified'])
        self.assertNotContains(self.client.get(reverse('login')), 'Continue Verification')
        self.assertNotIn(signup_lifecycle.RESUME_KEY, self.client.session)

    def test_password_change_and_expired_signup_invalidate_private_continuation(self):
        user = self.create_signup()
        user.set_password('ChangedPassword!456')
        user.save(update_fields=['password'])
        self.assertNotContains(self.client.get(reverse('login')), 'Continue Verification')
        self.login(user, password='ChangedPassword!456')
        User.objects.filter(pk=user.pk).update(pending_signup_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertNotContains(self.client.get(reverse('login')), 'Continue Verification')
        self.assertNotIn(signup_lifecycle.RESUME_KEY, self.client.session)

    def test_known_provider_failure_stays_on_prefilled_login_with_no_false_success(self):
        user = User.objects.create_user(username='existing', email='existing@gmail.com', password=self.password, role='customer')
        self.login(user)
        with patch('app.email_otp.send_mail', side_effect=RuntimeError('provider unavailable')):
            response = self.client.post(reverse('continue_verification'))
        self.assertContains(response, 'We could not send your code', status_code=503)
        self.assertContains(response, 'value="existing@gmail.com"', status_code=503)
        self.assertNotIn(signup_lifecycle.OTP_KEY, self.client.session)
        self.assertFalse(EmailOTPChallenge.objects.filter(consumed_at__isnull=True).exists())
        user.refresh_from_db()
        self.assertFalse(user.email_verified)

    def test_invalid_legacy_links_do_not_reveal_email_or_verification_status(self):
        user = User.objects.create_user(username='legacy', email='secret@gmail.com', password=self.password, role='customer')
        known = reverse('verify_email', kwargs={'uidb64': urlsafe_base64_encode(force_bytes(user.pk)), 'token': 'invalid'})
        missing = reverse('verify_email', kwargs={'uidb64': urlsafe_base64_encode(force_bytes(user.pk + 10000)), 'token': 'invalid'})
        messages = []
        for url in (known, missing):
            client = Client()
            response = client.get(url, follow=True)
            self.assertNotContains(response, user.email)
            self.assertNotContains(response, 'Continue Verification')
            messages.append([str(item) for item in response.context['messages']])
        self.assertEqual(messages[0], messages[1])

    def test_registration_failure_rolls_back_new_signup_and_does_not_remember_it(self):
        with patch('app.email_otp.send_mail', return_value=0):
            response = self.client.post(reverse('register'), self.payload())
        self.assertContains(response, 'We could not send a verification email')
        self.assertFalse(User.objects.exists())
        self.assertFalse(EmailOTPChallenge.objects.exists())
        self.assertNotIn(signup_lifecycle.RESUME_KEY, self.client.session)

    def test_expired_unused_signup_can_register_again_without_waiting_for_worker(self):
        user = self.create_signup()
        old_identifier = user.pk
        User.objects.filter(pk=user.pk).update(pending_signup_expires_at=timezone.now() - timedelta(seconds=1))
        RequestRateBucket.objects.all().delete()
        self.client.post(reverse('register'), self.payload())
        self.assertFalse(User.objects.filter(pk=old_identifier).exists())
        new_user = User.objects.get(username='signup-private')
        self.assertNotEqual(new_user.pk, old_identifier)
        self.assertGreater(new_user.pending_signup_expires_at, timezone.now())
        self.assertFalse(new_user.email_verified)

    def test_successful_otp_and_legacy_verification_clear_retention_marker(self):
        user = self.create_signup()
        code = re.search(r'(?m)^[0-9]{6}$', mail.outbox[-1].body).group()
        self.client.post(reverse('verify_account_otp'), {'code': code})
        user.refresh_from_db()
        self.assertIsNone(user.pending_signup_expires_at)
        self.assertNotIn(signup_lifecycle.RESUME_KEY, self.client.session)
        RequestRateBucket.objects.all().delete()
        other = self.create_signup(username='legacy-new', email='legacynew@gmail.com')
        token = email_verification_token_generator.make_token(other)
        url = reverse('verify_email', kwargs={'uidb64': urlsafe_base64_encode(force_bytes(other.pk)), 'token': token})
        self.client.post(url)
        other.refresh_from_db()
        self.assertIsNone(other.pending_signup_expires_at)

    def test_private_session_is_not_shared_with_another_browser(self):
        self.create_signup()
        self.assertNotContains(Client().get(reverse('login')), 'Continue Verification')

    def test_retention_marker_is_opt_in_and_does_not_backfill_existing_accounts(self):
        user = User.objects.create_user(username='legacy', email='legacy@gmail.com', password=self.password, role='customer')
        self.assertIsNone(user.pending_signup_expires_at)
        new_user = self.create_signup()
        self.assertAlmostEqual((new_user.pending_signup_expires_at - new_user.date_joined).total_seconds(), 7 * 86400, delta=5)

    def test_signup_expiry_blocks_a_still_live_code_without_get_deleting_account(self):
        user = self.create_signup()
        code = re.search(r'(?m)^[0-9]{6}$', mail.outbox[-1].body).group()
        User.objects.filter(pk=user.pk).update(pending_signup_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertRedirects(self.client.get(reverse('verify_account_otp')), reverse('register'), fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertNotIn(signup_lifecycle.RESUME_KEY, self.client.session)
        self.assertNotIn(signup_lifecycle.OTP_KEY, self.client.session)
        user.refresh_from_db()
        self.assertFalse(user.email_verified)

    def test_signup_login_cooldown_stays_inline_and_does_not_ask_for_email(self):
        user = self.create_signup()
        other = Client()
        self.login(user, client=other)
        response = other.post(reverse('continue_verification'))
        self.assertContains(response, 'Continue Verification', status_code=429)
        self.assertContains(response, 'value="private@gmail.com"', status_code=429)
        self.assertNotContains(response, 'id="resendVerificationForm"', status_code=429)
        self.assertIn('Retry-After', response)

    def test_malformed_continuation_state_fails_closed_without_disclosing_user(self):
        session = self.client.session
        session[signup_lifecycle.RESUME_KEY] = {'user_id': 'invalid', 'email': 'private@gmail.com', 'password_digest': 'fake'}
        session.save()
        response = self.client.get(reverse('login'))
        self.assertNotContains(response, 'Continue Verification')
        self.assertNotContains(response, 'private@gmail.com')

    def test_invalid_field_lengths_cannot_bypass_generic_conflict_responses(self):
        user = User.objects.create_user(username='existing', email='existing@gmail.com', password=self.password, role='customer')
        for field in ('username', 'first_name', 'last_name'):
            for email in (user.email, 'new@gmail.com'):
                response = Client().post(reverse('register'), self.payload(**{'email': email, field: 'x' * 151}))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'already exists')
                self.assertNotContains(response, 'Continue Verification')
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(PENDING_SIGNUP_CLEANUP_ENABLED=False)
    def test_disabling_automatic_cleanup_also_disables_registration_reclamation(self):
        user = self.create_signup()
        User.objects.filter(pk=user.pk).update(pending_signup_expires_at=timezone.now() - timedelta(days=1))
        RequestRateBucket.objects.all().delete()
        self.client.post(reverse('register'), self.payload())
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertEqual(User.objects.count(), 1)

    def test_stale_tab_does_not_continue_a_different_pending_signup(self):
        self.create_signup()
        reference = self.client.session[signup_lifecycle.RESUME_KEY]['reference']
        RequestRateBucket.objects.all().delete()
        self.create_signup(username='second-user', email='second@gmail.com')
        response = self.client.post(reverse('continue_verification'), {'signup_reference': reference})
        self.assertContains(response, 'Your active signup has changed')
        self.assertContains(response, 's***@gmail.com')
        self.assertEqual(len(mail.outbox), 2)
