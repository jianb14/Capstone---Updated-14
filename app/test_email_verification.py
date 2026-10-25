"""Tests for the email verification flow (register, verify link, login gate, resend)."""
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import User
from .views.auth import email_verification_token_generator


class EmailVerificationFlowTests(TestCase):
    def setUp(self):
        # LocMemCache default at per-process — i-clear para hindi mag-leak ang
        # rate-limit counters sa pagitan ng tests.
        cache.clear()
        self.client = Client()
        self.unverified = User.objects.create_user(
            username="unverified",
            email="unverified@gmail.com",
            password="pass12345",
            first_name="Unverified",
            role="customer",
            email_verified=False,
        )
        self.verified = User.objects.create_user(
            username="verified",
            email="verified@gmail.com",
            password="pass12345",
            first_name="Verified",
            role="customer",
            email_verified=True,
        )

    def _verify_url(self, user, token):
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        return reverse("verify_email", kwargs={"uidb64": uid, "token": token})

    # Registration ──────────────────────────────────────────────────────

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_register_creates_unverified_account_and_sends_code(self):
        response = self.client.post(
            reverse("register"),
            {
                "first_name": "New",
                "last_name": "Customer",
                "username": "newcustomer",
                "email": "newcustomer@gmail.com",
                "phone": "09171234567",
                "password": "Passw0rd!",
                "confirm_password": "Passw0rd!",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("verify_account_otp"))

        user = User.objects.get(username="newcustomer")
        self.assertFalse(user.email_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["newcustomer@gmail.com"])
        self.assertRegex(mail.outbox[0].body, r"(?m)^[0-9]{6}$")

    def test_public_duplicate_signup_does_not_disclose_verification_status(self):
        self.unverified.email = self.unverified.email.upper()
        self.unverified.save(update_fields=['email'])
        response = self.client.post(
            reverse("register"),
            {
                "first_name": "Dup",
                "last_name": "User",
                "username": "duplicate",
                "email": self.unverified.email,
                "phone": "09171234567",
                "password": "Passw0rd!",
                "confirm_password": "Passw0rd!",
            },
        )
        self.assertRedirects(response, reverse('verify_account_otp'), fetch_redirect_response=False)
        page = self.client.get(response.url)
        self.assertNotContains(page, 'not yet verified')
        self.assertContains(page, 'If your account still needs verification')

    # Login gate ─────────────────────────────────────────────────────────

    def test_login_shows_private_banner_and_continue_requests_code_without_retyping_email(self):
        response = self.client.post(
            reverse("login"),
            {"email": self.unverified.email, "password": "pass12345"},
        )
        self.assertContains(response, 'Continue Verification')
        self.assertContains(response, 'u***@gmail.com')
        self.assertContains(response, 'value="unverified@gmail.com"')
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertRedirects(self.client.post(reverse('continue_verification')), reverse('verify_account_otp'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)

    def test_login_allows_verified_user(self):
        response = self.client.post(
            reverse("login"),
            {"email": self.verified.email, "password": "pass12345"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))
        self.assertIn("_auth_user_id", self.client.session)

    # Verification link ──────────────────────────────────────────────────

    def test_valid_link_marks_email_verified_and_allows_login(self):
        token = email_verification_token_generator.make_token(self.unverified)
        page = self.client.get(self._verify_url(self.unverified, token))
        self.assertContains(page, "Confirm Email")
        self.unverified.refresh_from_db()
        self.assertFalse(self.unverified.email_verified)
        response = self.client.post(self._verify_url(self.unverified, token))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("login"))

        self.unverified.refresh_from_db()
        self.assertTrue(self.unverified.email_verified)

        login_response = self.client.post(
            reverse("login"),
            {"email": self.unverified.email, "password": "pass12345"},
        )
        self.assertEqual(login_response.status_code, 302)

    @override_settings(EMAIL_VERIFICATION_TIMEOUT=-1)
    def test_expired_link_redirects_to_login_with_resend_prompt(self):
        """Regression: expired links must land on the login page (with a
        resend button), never back on register ('Email already exists')."""
        token = email_verification_token_generator.make_token(self.unverified)
        response = self.client.get(self._verify_url(self.unverified, token))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("login"))
        self.assertNotEqual(response.url, reverse("register"))

        self.unverified.refresh_from_db()
        self.assertFalse(self.unverified.email_verified)

        page = self.client.get(reverse("login"))
        self.assertContains(page, 'invalid or expired')
        self.assertNotContains(page, self.unverified.email)
        self.assertNotContains(page, 'Continue Verification')

    def test_reset_token_is_not_accepted_for_verification(self):
        token = default_token_generator.make_token(self.unverified)
        response = self.client.get(self._verify_url(self.unverified, token))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("login"))

        self.unverified.refresh_from_db()
        self.assertFalse(self.unverified.email_verified)

    # Resend flow ────────────────────────────────────────────────────────

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_resend_sends_new_email_for_unverified_account(self):
        response = self.client.post(
            reverse("resend_verification"), {"email": self.unverified.email}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("verify_account_otp"))

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.unverified.email])
        self.assertRegex(mail.outbox[0].body, r"(?m)^[0-9]{6}$")

        page = self.client.get(reverse("verify_account_otp"))
        self.assertContains(page, "If your account still needs verification")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_resend_unknown_email_stays_generic_and_sends_nothing(self):
        response = self.client.post(
            reverse("resend_verification"), {"email": "nobody@gmail.com"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

        page = self.client.get(reverse("verify_account_otp"))
        self.assertContains(page, "If your account still needs verification")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_resend_for_verified_account_sends_nothing(self):
        response = self.client.post(
            reverse("resend_verification"), {"email": self.verified.email}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_resend_is_rate_limited_by_cooldown(self):
        first = self.client.post(
            reverse("resend_verification"), {"email": self.unverified.email}
        )
        self.assertEqual(first.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

        second = self.client.post(
            reverse("resend_verification"), {"email": self.unverified.email}
        )
        self.assertEqual(second.status_code, 429)
        self.assertIn('Retry-After', second)
        self.assertContains(second, "Please wait", status_code=429)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        VERIFICATION_RESEND_COOLDOWN_SECONDS=0,
        VERIFICATION_RESEND_RATE_LIMIT_PER_EMAIL=2,
        VERIFICATION_RESEND_RATE_LIMIT_PER_IP=100,
    )
    def test_resend_email_limit_blocks_after_max_requests(self):
        for _ in range(2):
            ok = self.client.post(
                reverse("resend_verification"), {"email": self.unverified.email}
            )
            self.assertEqual(ok.status_code, 302)
        self.assertEqual(len(mail.outbox), 2)

        blocked = self.client.post(
            reverse("resend_verification"), {"email": self.unverified.email}
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertContains(blocked, "Too many verification email requests", status_code=429)
        self.assertEqual(len(mail.outbox), 2)



