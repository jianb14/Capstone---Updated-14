"""Tests for the opt-in client email notification on policy content updates."""
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import GuidelineItem, GuidelinePageContent, User


class PolicyUpdateNotifyTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username="admin1", email="admin@test.com", password="pass12345",
            role="admin", is_staff=True,
        )
        # Active customer with email -> should receive the notice
        self.customer = User.objects.create_user(
            username="cust1", email="cust1@test.com", password="pass12345",
            role="customer",
        )
        # Customer without email -> excluded
        User.objects.create_user(
            username="cust2", email="", password="pass12345", role="customer"
        )
        # Inactive customer -> excluded
        User.objects.create_user(
            username="cust3", email="cust3@test.com", password="pass12345",
            role="customer", is_active=False,
        )
        # Staff -> excluded
        User.objects.create_user(
            username="staff1", email="staff@test.com", password="pass12345",
            role="staff", is_staff=True,
        )
        self.url = reverse("admin_guidelines_content")

    def _post(self, **extra):
        payload = {"notify_clients": "on"}
        # Simulate the real admin form: the "Visible" checkbox for every
        # existing item is always submitted on save.
        for item in GuidelineItem.objects.all():
            payload[f"item_active_{item.id}"] = "on"
        payload.update(extra)
        return self.client.post(self.url, payload)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_changed_title_sends_notice_to_active_clients_only(self):
        self.client.force_login(self.admin)
        response = self._post(terms_title="Updated Terms Title")
        self.assertEqual(response.status_code, 302)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.subject, "Updated Guidelines, Terms & Privacy | Balloorina")
        self.assertEqual(email.to, ["cust1@test.com"])
        self.assertIn("Terms & Conditions", email.body)
        self.assertIn("http://testserver/terms-and-conditions/", email.body)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_no_change_no_email(self):
        self.client.force_login(self.admin)
        response = self._post()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_unchecked_box_no_email_even_with_change(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {"terms_title": "Another Title"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_new_item_triggers_email(self):
        self.client.force_login(self.admin)
        response = self._post(
            new_heading_privacy="New Privacy Rule",
            new_body_privacy="Be nice.",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Privacy Policy", mail.outbox[0].body)

        page = GuidelinePageContent.objects.get(page_key="privacy")
        new_item = page.items.filter(heading="New Privacy Rule").first()
        self.assertIsNotNone(new_item)
        self.assertTrue(new_item.is_active)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_smtp_failure_does_not_break_save(self):
        from unittest.mock import patch
        from django.core.mail import send_mail as real_send_mail

        self.client.force_login(self.admin)
        with patch("app.views.admin.send_mail", side_effect=Exception("SMTP down")):
            response = self._post(guidelines_title="Broken SMTP Title")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            GuidelinePageContent.objects.get(page_key="guidelines").title,
            "Broken SMTP Title",
        )
        self.assertEqual(len(mail.outbox), 0)
