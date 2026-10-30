from datetime import date, time
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .models import AuditLog, Booking, Package, Payment, ServiceChargeConfig, User


class LogisticsOverrideTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="logistics-admin", role="admin")
        self.customer = User.objects.create_user(username="logistics-owner", role="customer")
        self.package = Package.objects.create(name="Booked Package", price=5000)
        self.config = ServiceChargeConfig.objects.create(pk=1, amount=1000)
        self.booking = Booking.objects.create(user=self.customer, event_date=date(2099, 6, 15),
            event_time=time(7), event_type="Birthday", event_location="Bacoor, Cavite",
            package_type=self.package.name, logistics_fee=1000, logistics_fee_override=1500,
            overtime_fee=500, overtime_hours=1, total_price=7000, status="confirmed")
        self.url = reverse("admin_booking_logistics_override", args=[self.booking.id])
        self.client.force_login(self.admin)

    def test_explicit_reset_ignores_filled_input_and_restores_saved_fee(self):
        self.config.amount = 2000
        self.config.save()
        self.package.price = 9000
        self.package.save()
        response = self.client.post(self.url, {"action": "reset", "logistics_fee_override": "1500"}, follow=True)
        self.booking.refresh_from_db()
        self.assertIsNone(self.booking.logistics_fee_override)
        self.assertEqual(self.booking.logistics_fee, Decimal("1000"))
        self.assertEqual(self.booking.total_price, Decimal("6500"))
        self.assertEqual(self.booking.overtime_fee, Decimal("500"))
        self.assertContains(response, "Override removed. Logistics fee restored to ₱1,000.00.")
        self.assertTrue(AuditLog.objects.filter(action__icontains="cleared the logistics fee override").exists())
        self.assertTrue(self.booking.status_logs.filter(notes__icontains="cleared the logistics fee override").exists())

    def test_blank_input_still_clears_override(self):
        self.client.post(self.url, {"logistics_fee_override": ""})
        self.booking.refresh_from_db()
        self.assertIsNone(self.booking.logistics_fee_override)
        self.assertEqual(self.booking.total_price, Decimal("6500"))

    def test_zero_override_is_visible_and_can_be_reset(self):
        self.client.post(self.url, {"logistics_fee_override": "0"})
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.total_price, Decimal("5500"))
        response = self.client.get(reverse("admin_booking_detail", args=[self.booking.id]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertIn('value="0.00"', response.json()["html"])
        self.assertContains(response, "(manual fee)")
        self.client.post(self.url, {"action": "reset"})
        self.booking.refresh_from_db()
        self.assertIsNone(self.booking.logistics_fee_override)
        self.assertEqual(self.booking.total_price, Decimal("6500"))

    def test_double_reset_does_not_change_total_again(self):
        self.client.post(self.url, {"action": "reset"})
        self.client.post(self.url, {"action": "reset"})
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.total_price, Decimal("6500"))

    def test_override_is_the_entire_fee_not_an_additional_charge(self):
        self.client.post(self.url, {"logistics_fee_override": "1750.25"})
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.total_price, Decimal("7250.25"))

    def test_payment_records_are_unchanged_and_balance_follows_new_total(self):
        payment = Payment.objects.create(booking=self.booking, amount=7000, payment_status="verified",
            payment_method="gcash", transaction_ref="override-paid-1")
        original_payment = Payment.objects.values().get(pk=payment.pk)
        self.client.post(self.url, {"action": "reset"})
        self.assertEqual(Payment.objects.values().get(pk=payment.pk), original_payment)
        self.client.force_login(self.customer)
        response = self.client.get(reverse("booking_modal_content", args=[self.booking.id]))
        self.assertEqual(response.context["total_verified_paid"], Decimal("7000"))
        self.assertEqual(response.context["remaining_balance"], Decimal("-500"))

    def test_reset_is_not_shown_when_computed_fee_is_active(self):
        self.client.post(self.url, {"action": "reset"})
        response = self.client.get(reverse("admin_booking_detail", args=[self.booking.id]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(response, "restore the original computed fee")
        self.assertContains(response, "Service &amp; logistics")
        self.assertIn('value=""', response.json()["html"])

    def test_invalid_fee_is_rejected_without_changing_booking(self):
        for value in ("-1", "NaN", "Infinity", "wrong", "100000000", "1.123"):
            self.client.post(self.url, {"logistics_fee_override": value})
            self.booking.refresh_from_db()
            self.assertEqual(self.booking.logistics_fee_override, Decimal("1500"))
            self.assertEqual(self.booking.total_price, Decimal("7000"))

    def test_customer_cannot_override_or_reset_and_get_is_disallowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.force_login(self.customer)
        self.assertEqual(self.client.post(self.url, {"action": "reset"}).status_code, 403)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.logistics_fee_override, Decimal("1500"))
