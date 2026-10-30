"""Tests for the admin → customer backdrop design delivery (post-payment)."""
import base64
import io
import tempfile
from datetime import date, time
from unittest.mock import Mock, patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import AuditLog, Booking, BookingDesignDelivery, Notification, Payment, User

# Offline storage: para hindi humawak ng Cloudinary/network sa tests.
_OFFLINE_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


def _design_upload(name="design.png", content_type="image/png"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "#4895ef").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


class TempMediaMixin:
    """Lahat ng upload ay pumapasok sa pansamantalang MEDIA_ROOT (may cleanup)."""

    def setUp(self):
        super().setUp()
        media_temp = tempfile.TemporaryDirectory()
        self.addCleanup(media_temp.cleanup)
        settings_override = override_settings(
            STORAGES=_OFFLINE_STORAGES, MEDIA_ROOT=media_temp.name
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)


class DesignDeliveryTests(TempMediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.admin = User.objects.create_user(
            username="admin1", email="admin1@test.com",
            password="pass12345", role="admin",
        )
        self.customer = User.objects.create_user(
            username="cust1", email="cust1@test.com",
            password="pass12345", role="customer",
        )
        self.confirmed_booking = self._create_booking(
            user=self.customer, status="confirmed"
        )
        Payment.objects.create(booking=self.confirmed_booking, payment_status="verified", amount=1000, transaction_ref="design-delivery-fixture")

    def _create_booking(self, **kwargs):
        defaults = dict(
            user=self.customer,
            event_date=date(2099, 6, 15),
            event_time=time(10, 0),
            event_type="Birthday",
            event_location="Test Venue Street",
            package_type="Package A",
            total_price=5000,
            status="pending",
        )
        defaults.update(kwargs)
        return Booking.objects.create(**defaults)

    def _upload(self, booking, admin=None, upload=None):
        admin = admin or self.admin
        self.client.force_login(admin)
        return self.client.post(
            reverse("admin_booking_design_upload", args=[booking.id]),
            {"design_image": upload or _design_upload()},
            follow=False,
        )

    # ---- GATE: bayad muna bago mag-upload ----
    def test_upload_blocked_when_not_confirmed(self):
        pending = self._create_booking(status="pending")
        response = self._upload(pending)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            BookingDesignDelivery.objects.filter(booking=pending).count(), 0
        )

    def test_customer_cannot_upload(self):
        response = self._upload(self.confirmed_booking, admin=self.customer)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(BookingDesignDelivery.objects.count(), 0)

    def test_admin_upload_creates_delivery_and_notifies_customer(self):
        response = self._upload(self.confirmed_booking)
        self.assertEqual(response.status_code, 302)

        delivery = BookingDesignDelivery.objects.get(
            booking=self.confirmed_booking
        )
        self.assertEqual(delivery.uploaded_by, self.admin)
        self.assertTrue(delivery.image)

        self.assertTrue(
            Notification.objects.filter(
                booking=self.confirmed_booking,
                user=self.customer,
                message__icontains="backdrop design",
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                user=self.admin, action__icontains="Uploaded backdrop design"
            ).exists()
        )

    def test_non_image_file_rejected(self):
        bad = SimpleUploadedFile(
            "evil.txt", b"not an image", content_type="text/plain"
        )
        response = self._upload(self.confirmed_booking, upload=bad)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(BookingDesignDelivery.objects.count(), 0)

    def test_max_three_images_enforced(self):
        for _ in range(3):
            self._upload(self.confirmed_booking)
        self.assertEqual(
            BookingDesignDelivery.objects.filter(
                booking=self.confirmed_booking
            ).count(),
            3,
        )
        response = self._upload(self.confirmed_booking)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            BookingDesignDelivery.objects.filter(
                booking=self.confirmed_booking
            ).count(),
            3,
        )

    def test_delete_removes_delivery(self):
        self._upload(self.confirmed_booking)
        delivery = BookingDesignDelivery.objects.get(
            booking=self.confirmed_booking
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse(
                "admin_booking_design_delete",
                args=[self.confirmed_booking.id, delivery.id],
            )
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(BookingDesignDelivery.objects.count(), 0)

    # ---- CUSTOMER RECEIPT: booking details page ----
    def test_customer_sees_design_section_when_uploaded(self):
        self._upload(self.confirmed_booking)
        self.client.force_login(self.customer)
        body = self.client.get(
            reverse("booking_modal_content", args=[self.confirmed_booking.id]) + "?section=design"
        ).content.decode("utf-8")
        self.assertIn("Your Event Design", body)
        self.assertIn("Download Design", body)

    def test_profile_has_design_entrypoint_and_modal_fetches_its_content(self):
        self._upload(self.confirmed_booking)
        self.client.force_login(self.customer)
        response = self.client.get(reverse("customer_profile"))
        self.assertContains(response, "Design ready")
        self.assertContains(response, "View Event Design")
        self.assertContains(response, "Your Event Design")
        self.assertNotContains(response, "Download Design")
        response = self.client.get(reverse("booking_modal_content", args=[self.confirmed_booking.id]), {"section": "design"})
        self.assertContains(response, "Download Design")
        self.assertContains(response, "View full size")
        self.assertContains(response, reverse("booking_design_download", args=[
            self.confirmed_booking.id, self.confirmed_booking.design_deliveries.get().id]))

    def test_confirmed_booking_has_design_waiting_message_on_both_screens(self):
        self.client.force_login(self.customer)
        for url in (reverse("booking_modal_content", args=[self.confirmed_booking.id]), reverse("booking_modal_content", args=[self.confirmed_booking.id]) + "?section=design"):
            response = self.client.get(url)
            self.assertContains(response, "Your event design will appear here once uploaded by our team.")
            self.assertNotContains(response, "Download Design")
            self.assertNotContains(response, 'class="event-design-ready"')

    def test_other_customer_profile_does_not_include_delivered_design(self):
        self._upload(self.confirmed_booking)
        other = User.objects.create_user(username="other-design-owner", role="customer")
        self.client.force_login(other)
        response = self.client.get(reverse("customer_profile"))
        self.assertNotContains(response, "Download Design")
        self.assertNotContains(response, 'class="event-design-ready"')

    def test_delivery_caption_is_escaped_in_both_views(self):
        self._upload(self.confirmed_booking)
        delivery = self.confirmed_booking.design_deliveries.get()
        delivery.caption = '<script>alert("caption")</script>'
        delivery.save()
        self.client.force_login(self.customer)
        for url in (reverse("booking_modal_content", args=[self.confirmed_booking.id]) + "?section=design",):
            response = self.client.get(url)
            self.assertContains(response, '&lt;script&gt;')
            self.assertNotContains(response, '<script>alert("caption")</script>')

    def _download_url(self):
        self._upload(self.confirmed_booking)
        self.client.force_login(self.customer)
        return reverse("booking_design_download", args=[
            self.confirmed_booking.id, self.confirmed_booking.design_deliveries.get().id])

    def test_design_download_is_an_attachment_with_original_image_bytes(self):
        url = self._download_url()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn(".png", response["Content-Disposition"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(b"".join(response.streaming_content), _design_upload().read())

    def test_design_download_requires_login_and_booking_owner(self):
        url = self._download_url()
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        other = User.objects.create_user(username="other-downloader", role="customer")
        self.client.force_login(other)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_cannot_download_a_delivery_from_another_booking(self):
        self._download_url()
        another_booking = self._create_booking()
        delivery = self.confirmed_booking.design_deliveries.get()
        url = reverse("booking_design_download", args=[another_booking.id, delivery.id])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_missing_design_file_returns_404(self):
        url = self._download_url()
        delivery = self.confirmed_booking.design_deliveries.get()
        delivery.image.storage.delete(delivery.image.name)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_temporarily_unavailable_storage_returns_a_readable_error(self):
        url = self._download_url()
        with patch("django.db.models.fields.files.ImageFieldFile.open", side_effect=OSError("Unavailable")):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "temporarily unavailable", status_code=503)

    def test_download_handles_cloudinary_style_name_without_extension(self):
        url = self._download_url()
        with patch("django.db.models.fields.files.ImageFieldFile.open", return_value=io.BytesIO(_design_upload().read())):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn(".png", response["Content-Disposition"])
            self.assertEqual(b"".join(response.streaming_content), _design_upload().read())

    def test_design_section_hidden_without_upload(self):
        self.client.force_login(self.customer)
        body = self.client.get(
            reverse("booking_modal_content", args=[self.confirmed_booking.id])
        ).content.decode("utf-8")
        # "Download Design" ay nasa loob ng {% if %} block lang — hindi
        # lalabas kung walang na-upload na design ang admin.
        self.assertNotIn("Download Design", body)

    def test_admin_detail_shows_locked_state_before_confirmation(self):
        pending = self._create_booking(status="pending")
        self.client.force_login(self.admin)
        body = self.client.get(
            reverse("admin_booking_detail", args=[pending.id]), HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        ).json()["html"]
        self.assertNotIn("Send design</a>", body)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class DesignDeliveryEmailTests(TempMediaMixin, TransactionTestCase):
    """Exercise real commit hooks and email failures without sending live email."""

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(username='designer', role='admin')
        self.customer = User.objects.create_user(
            username='design-customer', first_name='Juan', email='juan@example.com', role='customer',
        )
        self.booking = Booking.objects.create(
            user=self.customer, status='confirmed', event_date=date(2099, 6, 15),
            event_time=time(10), event_type='Birthday', event_location='Venue',
            package_type='Package A', total_price=5000,
        )
        self.payment = Payment.objects.create(
            booking=self.booking, amount=1000, payment_status='verified', transaction_ref='email-paid',
        )
        self.client.force_login(self.admin)
        self.url = reverse('admin_booking_design_upload', args=[self.booking.pk])

    def post_design(self, **data):
        data.setdefault('design_image', _design_upload())
        return self.client.post(self.url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_design_email_has_customer_order_message_and_original_attachment(self):
        response = self.post_design(caption='Here is your pink birthday backdrop.')
        self.assertEqual(response.status_code, 200)
        self.assertIn('accepted for delivery', response.json()['message'])
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['juan@example.com'])
        self.assertIn(f'Order #{self.booking.pk}', message.subject)
        self.assertIn(f'Order #{self.booking.pk}', message.body)
        self.assertIn('Hi Juan,', message.body)
        self.assertIn('Here is your pink birthday backdrop.', message.body)
        self.assertNotIn('http', message.body)
        self.assertEqual(len(message.attachments), 1)
        filename, content, mimetype = message.attachments[0]
        delivery = self.booking.design_deliveries.get()
        self.assertEqual(filename, f'order-{self.booking.pk}-design-{delivery.pk}.png')
        self.assertEqual(content, _design_upload().read())
        self.assertEqual(mimetype, 'image/png')
        self.assertEqual(delivery.caption, 'Here is your pink birthday backdrop.')

    def test_blank_message_uses_default_and_username_fallback(self):
        self.customer.first_name = ''
        self.customer.save(update_fields=['first_name'])
        self.post_design(caption='   ')
        self.assertIn('Hi design-customer,', mail.outbox[0].body)
        self.assertIn('Please see the attached file', mail.outbox[0].body)

    def test_attachment_uses_actual_format_and_never_reopens_remote_storage(self):
        for image_format, extension, mimetype in [
            ('JPEG', 'jpg', 'image/jpeg'), ('PNG', 'png', 'image/png'), ('WEBP', 'webp', 'image/webp'),
        ]:
            with self.subTest(image_format=image_format):
                buffer = io.BytesIO()
                Image.new('RGB', (8, 8)).save(buffer, format=image_format)
                content = buffer.getvalue()
                # Real format wins even when a storage provider changes the name.
                upload = SimpleUploadedFile('customer-design.png', content, content_type='image/png')
                with patch('django.db.models.fields.files.ImageFieldFile.open', side_effect=OSError('remote unavailable')):
                    self.assertEqual(self.post_design(design_image=upload).status_code, 200)
                filename, attachment, content_type = mail.outbox[-1].attachments[0]
                self.assertTrue(filename.endswith(f'.{extension}'))
                self.assertEqual(attachment, content)
                self.assertEqual(content_type, mimetype)

    def test_email_runs_after_commit_and_replay_does_not_send_twice(self):
        from .design_delivery_email import send_design_delivery_email

        def check_commit(delivery, content):
            self.assertFalse(connection.in_atomic_block)
            self.assertTrue(BookingDesignDelivery.objects.filter(pk=delivery.pk).exists())
            return send_design_delivery_email(delivery, content)

        with patch('app.design_delivery_email.send_design_delivery_email', side_effect=check_commit) as send:
            self.assertEqual(self.post_design(submission_id='unique-design-email').status_code, 200)
            self.assertEqual(self.post_design(submission_id='unique-design-email').status_code, 200)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.booking.design_deliveries.count(), 1)
        self.assertEqual(Notification.objects.filter(booking=self.booking).count(), 1)

    def test_rollback_never_sends_email(self):
        with patch('app.design_delivery_email.send_design_delivery_email') as send:
            with self.assertRaisesMessage(RuntimeError, 'rollback'):
                with transaction.atomic():
                    self.assertEqual(self.post_design().status_code, 200)
                    send.assert_not_called()
                    raise RuntimeError('rollback')
            send.assert_not_called()
        self.assertFalse(self.booking.design_deliveries.exists())
        self.assertFalse(Notification.objects.filter(booking=self.booking).exists())

    def test_email_failure_keeps_design_and_notification_and_reports_problem(self):
        for result in [RuntimeError('secret-provider-data'), 0]:
            with self.subTest(result=result):
                kwargs = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
                with patch('app.design_delivery_email.EmailMessage.send', **kwargs) as send:
                    with self.assertLogs('app.design_delivery_email', level='WARNING') as logs:
                        response = self.post_design()
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()['success'])
                self.assertIn('email could not be confirmed', response.json()['message'])
                self.assertNotIn('secret-provider-data', ' '.join(logs.output))
                self.assertEqual(send.call_count, 1)
        self.assertEqual(self.booking.design_deliveries.count(), 2)
        self.assertEqual(Notification.objects.filter(booking=self.booking).count(), 2)

    def test_missing_customer_email_does_not_lose_design(self):
        self.customer.email = ''
        self.customer.save(update_fields=['email'])
        with self.assertLogs('app.design_delivery_email', level='WARNING'):
            response = self.post_design()
        self.assertEqual(response.status_code, 200)
        self.assertIn('email could not be confirmed', response.json()['message'])
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.booking.design_deliveries.count(), 1)

    def test_invalid_unpaid_or_unauthorized_uploads_never_send_email(self):
        with patch('app.design_delivery_email.send_design_delivery_email') as send:
            self.assertEqual(self.post_design(design_image=SimpleUploadedFile('bad.png', b'bad', content_type='image/png')).status_code, 400)
            self.assertEqual(self.post_design(caption='x' * 256).status_code, 400)
            self.payment.payment_status = 'pending'
            self.payment.save(update_fields=['payment_status'])
            self.assertEqual(self.post_design().status_code, 400)
            self.client.force_login(self.customer)
            self.assertEqual(self.post_design().status_code, 403)
            send.assert_not_called()
        self.assertFalse(self.booking.design_deliveries.exists())

    @override_settings(
        EMAIL_BACKEND='app.email_backend.BrevoEmailBackend',
        BREVO_API_KEY='test-only-key', DEFAULT_FROM_EMAIL='Balloorina <sender@example.com>',
    )
    def test_design_upload_reaches_brevo_as_base64_attachment(self):
        with patch('app.email_backend.requests.Session.post') as post:
            post.return_value = Mock(status_code=201)
            post.return_value.json.return_value = {'messageId': '<design-test@example.com>'}
            response = self.post_design(caption='Here is your design.')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(post.call_count, 1)
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['to'], [{'email': 'juan@example.com'}])
        self.assertIn(f'Order #{self.booking.pk}', payload['textContent'])
        self.assertIn('Here is your design.', payload['textContent'])
        self.assertEqual(base64.b64decode(payload['attachment'][0]['content']), _design_upload().read())
        self.assertTrue(payload['attachment'][0]['name'].endswith('.png'))
