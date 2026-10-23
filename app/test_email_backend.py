"""Brevo transport contract and failure handling; no live emails are sent."""
import base64
import os
import runpy
from unittest.mock import Mock, patch

import requests
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import BadHeaderError, EmailMessage, EmailMultiAlternatives, get_connection, send_mail
from django.test import SimpleTestCase, override_settings

from .email_backend import BrevoEmailBackend, BrevoEmailError


@override_settings(
    EMAIL_BACKEND="app.email_backend.BrevoEmailBackend",
    BREVO_API_KEY="test-brevo-key",
    DEFAULT_FROM_EMAIL="Balloorina <sender@example.com>",
    EMAIL_TIMEOUT=10,
)
class BrevoEmailBackendTests(SimpleTestCase):
    def setUp(self):
        self.post = self.enterContext(patch("app.email_backend.requests.Session.post"))
        self.post.return_value = Mock(status_code=201)
        self.post.return_value.json.return_value = {"messageId": "<test-message@example.com>"}

    def send(self, **kwargs):
        return send_mail("Test subject", "Hello, customer!", None, ["customer@gmail.com"], **kwargs)

    def test_send_mail_uses_https_with_verified_sender_and_original_content(self):
        self.assertEqual(self.send(), 1)
        args, kwargs = self.post.call_args
        self.assertEqual(args, ("https://api.brevo.com/v3/smtp/email",))
        self.assertEqual(kwargs["headers"]["api-key"], "test-brevo-key")
        self.assertEqual(kwargs["timeout"], 10)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["json"], {
            "sender": {"name": "Balloorina", "email": "sender@example.com"},
            "to": [{"email": "customer@gmail.com"}],
            "subject": "Test subject", "textContent": "Hello, customer!",
        })

    def test_html_cc_bcc_reply_to_headers_and_attachments_survive_transport(self):
        message = EmailMultiAlternatives(
            "Receipt", "Plain receipt", to=["Customer <customer@example.com>"],
            cc=["staff@example.com"], bcc=["audit@example.com"],
            reply_to=["Support <support@example.com>"], headers={"X-Reference": "booking-10"},
        )
        message.attach_alternative("<p>HTML receipt</p>", "text/html")
        message.attach("receipt.pdf", b"%PDF-1.4", "application/pdf")
        message.attach("note.txt", "Salamat po!", "text/plain")
        self.assertEqual(message.send(), 1)
        payload = self.post.call_args.kwargs["json"]
        self.assertEqual(payload["to"], [{"name": "Customer", "email": "customer@example.com"}])
        self.assertEqual(payload["cc"], [{"email": "staff@example.com"}])
        self.assertEqual(payload["bcc"], [{"email": "audit@example.com"}])
        self.assertEqual(payload["replyTo"], {"name": "Support", "email": "support@example.com"})
        self.assertEqual(payload["textContent"], "Plain receipt")
        self.assertEqual(payload["htmlContent"], "<p>HTML receipt</p>")
        self.assertEqual(payload["headers"], {"X-Reference": "booking-10"})
        self.assertEqual(base64.b64decode(payload["attachment"][0]["content"]), b"%PDF-1.4")
        self.assertEqual(base64.b64decode(payload["attachment"][1]["content"]), b"Salamat po!")
        self.assertEqual(message.brevo_message_id, "<test-message@example.com>")

    def test_html_only_email(self):
        message = EmailMessage("HTML", "<p>Hello</p>", to=["customer@gmail.com"])
        message.content_subtype = "html"
        self.assertEqual(message.send(), 1)
        payload = self.post.call_args.kwargs["json"]
        self.assertEqual(payload["htmlContent"], "<p>Hello</p>")
        self.assertNotIn("textContent", payload)

    def test_empty_batch_or_missing_recipients_makes_no_request(self):
        backend = get_connection()
        self.assertEqual(backend.send_messages([]), 0)
        self.assertEqual(backend.send_messages([EmailMessage("No recipients", "Body")]), 0)
        self.post.assert_not_called()

    @override_settings(BREVO_API_KEY="")
    def test_missing_key_fails_without_network_or_smtp_fallback(self):
        with patch("smtplib.SMTP") as smtp:
            with self.assertRaisesMessage(ImproperlyConfigured, "BREVO_API_KEY"):
                self.send()
        self.post.assert_not_called()
        smtp.assert_not_called()

    def test_provider_errors_are_not_counted_and_do_not_expose_response_content(self):
        for status in (400, 401, 402, 403, 429, 500, 503, 302):
            with self.subTest(status=status):
                self.post.return_value.status_code = status
                self.post.return_value.text = "secret provider response"
                with self.assertRaises(BrevoEmailError) as error:
                    self.send()
                self.assertIn(f"HTTP {status}", str(error.exception))
                self.assertNotIn("secret provider response", str(error.exception))

    def test_timeout_is_not_retried_and_does_not_expose_credentials(self):
        self.post.side_effect = requests.Timeout("secret header: test-brevo-key")
        with self.assertRaises(BrevoEmailError) as error:
            self.send()
        self.assertNotIn("test-brevo-key", str(error.exception))
        self.assertEqual(self.post.call_count, 1)

    def test_success_response_requires_a_message_id(self):
        for data in ({}, {"messageId": ""}, {"messageId": None}, []):
            with self.subTest(data=data):
                self.post.return_value.json.return_value = data
                with self.assertRaises(BrevoEmailError):
                    self.send()
        self.post.return_value.json.side_effect = ValueError("not JSON")
        with self.assertRaises(BrevoEmailError):
            self.send()

    def test_fail_silently_returns_zero_and_logs_failure(self):
        self.post.return_value.status_code = 401
        with self.assertLogs("app.email_backend", level="WARNING") as logs:
            self.assertEqual(self.send(fail_silently=True), 0)
        self.assertNotIn("test-brevo-key", " ".join(logs.output))

    def test_batch_counts_only_accepted_messages_and_continues_when_silent(self):
        failure = Mock(status_code=429)
        success = self.post.return_value
        self.post.side_effect = [failure, success]
        messages = [EmailMessage("First", "One", to=["one@example.com"]),
                    EmailMessage("Second", "Two", to=["two@example.com"])]
        with self.assertLogs("app.email_backend", level="WARNING"):
            self.assertEqual(get_connection(fail_silently=True).send_messages(messages), 1)
        self.assertEqual(self.post.call_count, 2)

    def test_header_injection_and_invalid_sender_are_rejected_before_http(self):
        with self.assertRaises(BadHeaderError):
            send_mail("Test\nBcc: attacker@example.com", "Body", None, ["customer@gmail.com"])
        with self.assertRaises(BrevoEmailError):
            send_mail("Test", "Body", "not-an-email", ["customer@gmail.com"])
        self.post.assert_not_called()


class EmailSettingsTests(SimpleTestCase):
    def test_default_and_legacy_smtp_settings_use_brevo_and_test_backends_remain_available(self):
        for backend in (None, "django.core.mail.backends.smtp.EmailBackend",
                        "django.core.mail.backends.locmem.EmailBackend",
                        "django.core.mail.backends.console.EmailBackend"):
            with self.subTest(backend=backend):
                environment = {"SECRET_KEY": "test-only", "DATABASE_URL": "sqlite:///:memory:"}
                if backend is not None:
                    environment["EMAIL_BACKEND"] = backend
                with patch.dict(os.environ, environment, clear=True), patch("dotenv.load_dotenv"):
                    config = runpy.run_module("Project.settings")
                expected = backend if backend and ".smtp." not in backend else "app.email_backend.BrevoEmailBackend"
                self.assertEqual(config["EMAIL_BACKEND"], expected)
                self.assertEqual(config["SERVER_EMAIL"], config["DEFAULT_FROM_EMAIL"])
