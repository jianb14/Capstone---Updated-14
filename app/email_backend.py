"""Django email transport using Brevo's HTTPS API, without SMTP or retries."""

import base64
import logging
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.mail.backends.base import BaseEmailBackend
from django.core.validators import validate_email

logger = logging.getLogger(__name__)


class BrevoEmailError(Exception):
    """An email was not confirmed as accepted by Brevo."""


class BrevoEmailBackend(BaseEmailBackend):
    api_url = "https://api.brevo.com/v3/smtp/email"

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = getattr(settings, "BREVO_API_KEY", "").strip()
        self.timeout = kwargs.get("timeout", settings.EMAIL_TIMEOUT)

    @staticmethod
    def _address(value):
        name, address = parseaddr(value)
        try:
            validate_email(address)
        except ValidationError:
            raise BrevoEmailError("Email sender or recipient address is invalid.") from None
        result = {"email": address}
        if name:
            result["name"] = name
        return result

    def _payload(self, message):
        # Preserve Django's protection against newline/header injection.
        message.message()
        payload = {
            "sender": self._address(message.from_email),
            "subject": str(message.subject),
        }
        for field in ("to", "cc", "bcc"):
            addresses = getattr(message, field)
            if addresses:
                payload[field] = [self._address(value) for value in addresses]
        if message.reply_to:
            if len(message.reply_to) != 1:
                raise BrevoEmailError("Brevo supports one reply-to address per email.")
            payload["replyTo"] = self._address(message.reply_to[0])

        if message.content_subtype not in ("plain", "html"):
            raise BrevoEmailError("Unsupported email body type for Brevo.")
        content_key = "htmlContent" if message.content_subtype == "html" else "textContent"
        payload[content_key] = message.body or " "
        for content, mimetype in getattr(message, "alternatives", []):
            if mimetype != "text/html":
                raise BrevoEmailError("Unsupported email alternative type for Brevo.")
            payload["htmlContent"] = content

        if message.attachments:
            attachments = []
            for attachment in message.attachments:
                # The application uses Django's (filename, content, mimetype) format.
                if not isinstance(attachment, tuple) or not attachment[0]:
                    raise BrevoEmailError("Brevo attachments require a filename and content.")
                filename, content, _mimetype = attachment
                if isinstance(content, str):
                    content = content.encode(message.encoding or settings.DEFAULT_CHARSET)
                attachments.append({
                    "name": filename,
                    "content": base64.b64encode(content).decode("ascii"),
                })
            payload["attachment"] = attachments
        if message.extra_headers:
            # Envelope addresses belong in the API's dedicated fields; never leak Bcc.
            reserved = {"from", "to", "cc", "bcc", "reply-to", "subject"}
            if any(key.lower() in reserved for key in message.extra_headers):
                raise BrevoEmailError("Use Django's email address fields instead of address headers.")
            payload["headers"] = message.extra_headers
        return payload

    def _send(self, session, message):
        if not self.api_key:
            raise ImproperlyConfigured("Set BREVO_API_KEY in the service environment to send email.")
        payload = self._payload(message)
        try:
            response = session.post(
                self.api_url,
                headers={"api-key": self.api_key, "accept": "application/json"},
                json=payload,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            # Do not expose request headers, credentials, or message content in logs.
            raise BrevoEmailError("Brevo email API connection failed; acceptance is unconfirmed.") from None

        if response.status_code != 201:
            reasons = {
                400: "Check the verified sender and email fields.",
                401: "Check BREVO_API_KEY.",
                402: "Check the account's email credits.",
                403: "Check transactional email activation, sender verification, and API access.",
                429: "Brevo rate limit reached; try again later.",
            }
            reason = reasons.get(response.status_code, "Check Brevo service status and transactional logs.")
            raise BrevoEmailError(f"Brevo email API returned HTTP {response.status_code}. {reason}")
        try:
            message_id = response.json().get("messageId")
        except (ValueError, AttributeError):
            message_id = None
        if not isinstance(message_id, str) or not message_id.strip():
            raise BrevoEmailError("Brevo returned no message ID; email acceptance is unconfirmed.")
        message.brevo_message_id = message_id

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        sent = 0
        # One local HTTP session per batch; safe across web requests/worker threads.
        # No automatic retry: a timeout may happen after Brevo accepted an email.
        with requests.Session() as session:
            for message in email_messages:
                if not message.recipients():
                    continue
                try:
                    self._send(session, message)
                except Exception:
                    if not self.fail_silently:
                        raise
                    logger.warning("Brevo email was not confirmed as accepted. Check email configuration and Brevo logs.")
                else:
                    sent += 1
        return sent
