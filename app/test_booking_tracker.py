"""Tests for the Booking Status Tracker on the booking details page."""
from datetime import date, time

from django.test import Client, TestCase
from django.urls import reverse

from .models import Booking, User


class BookingTrackerTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="cust", email="cust@test.com", password="pass12345", role="customer"
        )
        self.client.force_login(self.user)

    def _create_booking(self, **kwargs):
        defaults = dict(
            user=self.user,
            event_date=date(2099, 6, 15),
            event_time=time(10, 0),
            event_type="Birthday",
            event_location="Test Venue",
            package_type="Package A",
            total_price=5000,
            status="pending",
        )
        defaults.update(kwargs)
        return Booking.objects.create(**defaults)

    def _get_body(self, booking):
        response = self.client.get(reverse("view_booking", args=[booking.id]))
        self.assertEqual(response.status_code, 200)
        return response.content.decode("utf-8")

    def test_tracker_renders_all_four_steps(self):
        body = self._get_body(self._create_booking())
        self.assertIn("tracker-steps", body)
        for label in ("Requested", "Payment", "Confirmed", "Completed"):
            self.assertIn(f">{label}</span>", body)
        self.assertIn("tracker-message", body)

    def test_pending_booking_has_current_first_step(self):
        body = self._get_body(self._create_booking(status="pending"))
        self.assertEqual(body.count("tracker-step tracker-step-current"), 1)
        self.assertEqual(body.count("tracker-step tracker-step-upcoming"), 3)
        self.assertIn("review it shortly", body)
        self.assertIn("tracker-message-info", body)

    def test_confirmed_booking_fills_lines_and_shows_success(self):
        body = self._get_body(self._create_booking(status="confirmed"))
        # Requested + Payment are done, kaya may animated line fills
        self.assertEqual(body.count("tracker-line tracker-line-fill"), 2)
        self.assertEqual(body.count("tracker-step tracker-step-done"), 2)
        self.assertIn("tracker-message-success", body)

    def test_completed_booking_all_steps_done(self):
        body = self._get_body(self._create_booking(status="completed"))
        self.assertEqual(body.count("tracker-step tracker-step-done"), 3)
        self.assertEqual(body.count("tracker-step tracker-step-current"), 1)
        self.assertIn("Thank you for celebrating with us", body)

    def test_cancelled_booking_shows_failed_state(self):
        body = self._get_body(self._create_booking(status="cancelled"))
        self.assertIn("tracker-step tracker-step-failed", body)
        self.assertIn("tracker-message-danger", body)
        self.assertIn("has been cancelled", body)

    def test_expired_booking_shows_expired_message(self):
        body = self._get_body(self._create_booking(status="expired"))
        self.assertIn("tracker-step tracker-step-failed", body)
        self.assertIn("payment window closed", body)

    def test_cancel_requested_shows_warning(self):
        body = self._get_body(self._create_booking(status="cancel_requested"))
        self.assertIn("tracker-message-warn", body)
        self.assertIn("awaiting admin approval", body)

    def test_payment_step_note_reflects_verified_payment(self):
        body = self._get_body(self._create_booking(status="pending"))
        self.assertIn("Awaiting payment", body)

    def test_tracker_hidden_from_other_users(self):
        other = User.objects.create_user(
            username="other", email="other@test.com", password="pass12345", role="customer"
        )
        booking = self._create_booking(user=other)
        response = self.client.get(reverse("view_booking", args=[booking.id]))
        self.assertEqual(response.status_code, 403)

    def test_light_mode_overrides_present(self):
        # Dapat may light-mode adjustments ang tracker sa template
        from pathlib import Path

        template = (
            Path(__file__).resolve().parent.parent
            / "app" / "templates" / "client" / "booking" / "booking_detail.html"
        ).read_text(encoding="utf-8")
        self.assertIn('[data-theme="light"] .tracker', template)
        self.assertIn("@media (max-width: 640px)", template)
