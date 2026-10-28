"""Exercise existing email triggers through the real Brevo backend with mocked HTTP."""
from datetime import date, time, timedelta
from unittest.mock import Mock, patch
import re

import requests
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    AuditLog, Booking, ChatMessage, ChatNotification, ChatSession, ConcernTicket,
    GuidelinePageContent, Notification, Payment, ServiceChargeConfig, SiteSettings, User,
)
from .test_booking_design_step import _base_payload
from .views.common import send_admin_alert_email


@override_settings(
    EMAIL_BACKEND="app.email_backend.BrevoEmailBackend",
    BREVO_API_KEY="test-brevo-key",
    DEFAULT_FROM_EMAIL="Balloorina <sender@example.com>",
)
class BrevoEmailDeliveryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.post = self.enterContext(patch("app.email_backend.requests.Session.post"))
        self.post.return_value = Mock(status_code=201)
        self.post.return_value.json.return_value = {"messageId": "<accepted@example.com>"}
        self.user = User.objects.create_user(
            username="mail-customer", email="customer@gmail.com", password="Passw0rd!",
            first_name="Customer", role="customer", email_verified=True,
        )
        self.admin = User.objects.create_user(
            username="mail-admin", email="admin@example.com", password="Passw0rd!",
            role="admin", is_staff=True, email_verified=True,
        )
        self.site = SiteSettings.load()
        self.site.email_notifications_enabled = True
        self.site.admin_emails_for_notifications = "admin@example.com, staff@example.com"
        self.site.save()

    def payload(self, subject, recipients):
        self.post.assert_called_once()
        payload = self.post.call_args.kwargs["json"]
        self.assertIn(subject, payload["subject"])
        self.assertEqual([item["email"] for item in payload["to"]], recipients)
        self.assertEqual(payload["sender"], {"name": "Balloorina", "email": "sender@example.com"})
        self.assertTrue(payload["textContent"])
        return payload

    def booking(self):
        return Booking.objects.create(
            user=self.user, event_date=date(2030, 1, 15), event_time=time(9),
            event_type="Birthday", event_location="Test venue", total_price=5000,
            status="pending_payment", payment_due_at=timezone.now() + timedelta(hours=24),
        )

    def registration_data(self):
        return {
            "first_name": "New", "last_name": "Customer", "username": "new-mail-customer",
            "email": "newcustomer@gmail.com", "phone": "09171234567",
            "password": "Passw0rd!", "confirm_password": "Passw0rd!",
        }

    def test_admin_security_codes_and_invitation_use_configured_brevo_backend(self):
        self.admin.is_superuser = True
        self.admin.save(update_fields=['is_superuser'])
        self.client.force_login(self.admin)
        data = {'first_name': 'Jamie', 'last_name': 'Rivera', 'email': 'invited-admin@example.com',
                'phone_number': '09171234567', 'current_password': 'Passw0rd!'}
        self.assertEqual(self.client.post(reverse('admin_security_action', args=['invite', 'send']), data, secure=True).status_code, 200)
        payload = self.payload('Balloorina admin verification code', ['admin@example.com'])
        code = re.search(r'\b\d{6}\b', payload['textContent']).group()
        self.post.reset_mock()
        self.assertEqual(self.client.post(reverse('admin_security_action', args=['invite', 'confirm']), {'code': code}, secure=True).status_code, 200)
        payload = self.payload('You are invited to administer Balloorina', ['invited-admin@example.com'])
        self.assertIn('/admin-invitation/', payload['textContent'])
        self.assertFalse(User.objects.filter(email='invited-admin@example.com').exists())

    def test_registration_code_verifies_account_then_allows_login(self):
        response = self.client.post(reverse("register"), self.registration_data(), secure=True)
        self.assertRedirects(response, reverse("verify_account_otp"), fetch_redirect_response=False)
        payload = self.payload("Verify your Balloorina account", ["newcustomer@gmail.com"])
        user = User.objects.get(username="new-mail-customer")
        self.assertFalse(user.email_verified)
        code = re.search(r"(?m)^[0-9]{6}$", payload["textContent"]).group()
        self.client.post(reverse("verify_account_otp"), {"code": code}, secure=True)
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        self.assertEqual(self.client.post(reverse("login"), {
            "email": user.email, "password": "Passw0rd!",
        }).status_code, 302)

    def test_registration_failure_does_not_claim_success_or_leave_unusable_account(self):
        self.post.return_value.status_code = 401
        with self.assertLogs("app.views.common", level="ERROR"):
            response = self.client.post(reverse("register"), self.registration_data())
        self.assertContains(response, "We could not send a verification email")
        self.assertFalse(User.objects.filter(username="new-mail-customer").exists())

    def test_zero_send_count_also_fails_registration(self):
        with patch("app.email_otp.send_mail", return_value=0), self.assertLogs(level="ERROR"):
            response = self.client.post(reverse("register"), self.registration_data())
        self.assertContains(response, "We could not send a verification email")
        self.assertFalse(User.objects.filter(username="new-mail-customer").exists())

    def test_resend_verification_goes_through_brevo(self):
        self.user.email_verified = False
        self.user.save(update_fields=["email_verified"])
        self.assertEqual(self.client.post(reverse("resend_verification"), {"email": self.user.email}).status_code, 302)
        payload = self.payload("Verify your Balloorina account", [self.user.email])
        self.assertRegex(payload["textContent"], r"(?m)^[0-9]{6}$")

    def test_forgot_password_code_can_reset_password(self):
        response = self.client.post(reverse("forgot_password"), {"email": self.user.email}, secure=True)
        self.assertEqual(response.status_code, 302)
        payload = self.payload("Balloorina Password Reset", [self.user.email])
        code = re.search(r"(?m)^[0-9]{6}$", payload["textContent"]).group()
        self.client.post(reverse("verify_password_otp"), {"code": code}, secure=True)
        self.assertEqual(self.client.post(reverse("reset_password_otp"), {
            "password": "NewPassw0rd!", "confirm_password": "NewPassw0rd!",
        }, secure=True).status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewPassw0rd!"))

    def test_forgot_password_and_resend_failures_keep_generic_responses(self):
        self.post.side_effect = requests.Timeout()
        self.user.email_verified = False
        self.user.save(update_fields=["email_verified"])
        for route, text in (("forgot_password", "If the email exists"),
                            ("resend_verification", "If your account still needs verification")):
            with self.subTest(route=route), self.assertLogs(level="ERROR"):
                response = self.client.post(reverse(route), {"email": self.user.email}, follow=True)
                self.assertContains(response, text)
        self.assertFalse(AuditLog.objects.filter(action="Verification email resent.").exists())

    def test_admin_password_reset_is_retired_without_sending_mail(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin_user_reset_password", args=[self.user.pk]))
        self.assertEqual(response.status_code, 403)
        self.post.assert_not_called()

    def test_account_access_change_uses_brevo(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin_user_toggle", args=[self.user.pk]),
            {"action": "deactivate", "expected_active": "1"})
        self.assertEqual(response.status_code, 200)
        payload = self.payload("account has been deactivated", [self.user.email])
        self.assertIn("htmlContent", payload)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_booking_alert_uses_configured_admin_addresses(self):
        ServiceChargeConfig.objects.create(pk=1, shop_lat="14.414", shop_lng="120.982")
        self.client.force_login(self.user)
        response = self.client.post(reverse("create_booking"), _base_payload(), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertTrue(response.json()["success"], response.content)
        booking = Booking.objects.get()
        self.payload(f"New Booking #{booking.pk}", ["admin@example.com", "staff@example.com"])

    def test_disabled_admin_alerts_send_nothing(self):
        self.site.email_notifications_enabled = False
        self.site.save()
        self.assertFalse(send_admin_alert_email("Booking", "Body"))
        self.post.assert_not_called()

    def test_admin_alert_reports_provider_failure_without_raising(self):
        self.post.return_value.status_code = 429
        with self.assertLogs(level="ERROR"):
            self.assertFalse(send_admin_alert_email("Booking", "Body"))

    def test_payment_proof_submission_sends_admin_alert(self):
        booking = self.booking()
        self.client.force_login(self.user)
        response = self.client.post(reverse("submit_payment", args=[booking.pk]), {
            "gcash_ref_number": "1234567890123", "sender_name": "Customer",
            "amount": "5000", "payment_option": "full", "refund_ack": "on",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Payment.objects.filter(booking=booking).exists())
        self.payload("New Payment Proof", ["admin@example.com", "staff@example.com"])

    def test_concern_submission_sends_admin_alert(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("report_concern"), {
            "category": "other", "other_category": "Account question",
            "subject": "Help needed", "message": "Please review my concern.",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ConcernTicket.objects.filter(user=self.user).exists())
        self.payload("New Concern Ticket", ["admin@example.com", "staff@example.com"])

    def test_payment_reminder_sends_customer_email_and_in_app_notification(self):
        booking = self.booking()
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin_send_payment_reminder", args=[booking.pk]))
        self.assertEqual(response.status_code, 302)
        self.payload("Payment Reminder", [self.user.email])
        self.assertTrue(Notification.objects.filter(user=self.user, booking=booking).exists())
        self.assertTrue(AuditLog.objects.filter(action__contains="(email sent)").exists())

    def test_payment_reminder_failure_keeps_in_app_notification_and_records_failure(self):
        booking = self.booking()
        self.client.force_login(self.admin)
        self.post.return_value.status_code = 403
        with self.assertLogs(level="ERROR"):
            response = self.client.post(reverse("admin_send_payment_reminder", args=[booking.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Notification.objects.filter(user=self.user, booking=booking).exists())
        self.assertTrue(AuditLog.objects.filter(action__contains="email failed (in-app sent)").exists())

    def test_offline_support_reply_sends_real_email_message_parameter(self):
        session = ChatSession.objects.create(user=self.user, is_admin_support=True, status="pending_admin")
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin_chat_thread", args=[session.pk]), {"message": "We can help!"})
        self.assertEqual(response.status_code, 302)
        payload = self.payload("New message from Balloorina support", [self.user.email])
        self.assertIn("We can help!", payload["textContent"])
        self.assertTrue(ChatNotification.objects.filter(session=session).exists())

    def test_support_email_failure_does_not_lose_chat_or_in_app_notification(self):
        session = ChatSession.objects.create(user=self.user, is_admin_support=True, status="pending_admin")
        self.client.force_login(self.admin)
        self.post.side_effect = requests.Timeout()
        with self.assertLogs(level="ERROR"):
            response = self.client.post(reverse("admin_chat_thread", args=[session.pk]), {"message": "We can help!"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ChatMessage.objects.filter(session=session, message="We can help!").exists())
        self.assertTrue(ChatNotification.objects.filter(session=session).exists())

    def test_online_support_customer_does_not_get_unnecessary_email(self):
        session = ChatSession.objects.create(
            user=self.user, is_admin_support=True, status="active_admin",
            client_last_active_at=timezone.now(),
        )
        self.client.force_login(self.admin)
        self.client.post(reverse("admin_chat_thread", args=[session.pk]), {"message": "Hello!"})
        self.post.assert_not_called()

    def test_policy_update_sends_individual_emails_without_exposing_other_customers(self):
        other = User.objects.create_user(username="other-customer", email="other@gmail.com", role="customer")
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin_guidelines_content"), {
            "notify_clients": "on", "terms_title": "Updated Terms",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.post.call_count, 2)
        recipients = []
        for call in self.post.call_args_list:
            payload = call.kwargs["json"]
            self.assertEqual(len(payload["to"]), 1)
            self.assertNotIn("cc", payload)
            self.assertNotIn("bcc", payload)
            recipients.append(payload["to"][0]["email"])
        self.assertCountEqual(recipients, [self.user.email, other.email])

    def test_policy_save_survives_brevo_failure(self):
        self.client.force_login(self.admin)
        self.post.return_value.status_code = 402
        with self.assertLogs(level="ERROR"):
            response = self.client.post(reverse("admin_guidelines_content"), {
                "notify_clients": "on", "terms_title": "Updated Terms",
            })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(GuidelinePageContent.objects.get(page_key="terms").title, "Updated Terms")
