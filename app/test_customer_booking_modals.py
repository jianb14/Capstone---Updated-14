from datetime import date, time
from decimal import Decimal
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from .models import Booking, BookingDesignDelivery, Package, Payment, ServiceChargeConfig, User


class CustomerBookingModalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="modal-owner", role="customer")
        self.other = User.objects.create_user(username="modal-other", role="customer")
        self.client.force_login(self.user)
        Package.objects.create(name="Birthday Package", price=5000)
        ServiceChargeConfig.objects.create(pk=1, amount=1000, shop_lat=14.414, shop_lng=120.982)
        self.booking = Booking.objects.create(user=self.user, event_type="Birthday", event_date=date(2099, 6, 15),
            event_time=time(7), event_end_time=time(12), event_end_date=date(2099, 6, 15), duration_minutes=300,
            event_location="Molino, Bacoor, Cavite", event_lat="14.414000", event_lng="120.982000",
            venue_landmark="Blue gate", package_type="Birthday Package", logistics_fee=1000,
            overtime_hours=2, overtime_fee=1000, total_price=7000, status="pending_payment",
            design_theme="Princess", color_palette="Pink, Gold", special_requests="Blue balloons (End Time: 12:00)")
        self.url = reverse("booking_modal_content", args=[self.booking.pk])

    def payment(self, status="verified", amount=2000):
        return Payment.objects.create(booking=self.booking, amount=amount, payment_status=status,
            payment_method="gcash", transaction_ref=f"modal-payment-{status}-{Payment.objects.count()}")

    def test_legacy_details_url_redirects_to_the_customer_modal(self):
        response = self.client.get(reverse("view_booking", args=[self.booking.pk]))
        self.assertRedirects(response, f"{reverse('customer_profile')}?booking_id={self.booking.pk}&modal=details")
        response = self.client.get(reverse("view_booking", args=[self.booking.pk]), {"modal": "design"})
        self.assertRedirects(response, f"{reverse('customer_profile')}?booking_id={self.booking.pk}&modal=design")

    def test_new_endpoint_is_owner_only_get_only_and_uncached(self):
        self.assertEqual(self.client.post(self.url).status_code, 405)
        self.assertEqual(self.client.get(self.url, {"section": "unknown"}).status_code, 400)
        self.assertEqual(self.client.get(self.url)["Cache-Control"], "private, no-store")
        self.client.force_login(self.other)
        for url in (self.url, reverse("view_booking", args=[self.booking.pk])):
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_each_open_uses_fresh_status_and_verified_payment_amounts(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'booking-state-pending_payment')
        self.assertEqual(response.context["total_verified_paid"], 0)
        self.payment("pending", 5000)
        self.payment("rejected", 5000)
        self.payment("verified", 2000)
        response = self.client.get(self.url)
        self.assertContains(response, 'booking-state-confirmed')
        self.assertEqual(response.context["total_verified_paid"], Decimal("2000"))
        self.assertEqual(response.context["remaining_balance"], Decimal("5000"))
        self.assertContains(response, "Payment verified")
        self.assertContains(response, "Proceed to Payment")

    def test_details_contains_sections_and_exact_fee_explanations(self):
        response = self.client.get(self.url)
        for text in ("Event &amp; Venue", "Design Preferences", "Pricing &amp; Payment", "5h", "7:00 AM", "12:00 PM", "Blue gate", "Princess", "Pink, Gold", "2 hr(s) beyond the 3-hour package × ₱500/hr.", "View payment history"):
            self.assertContains(response, text)
        self.assertEqual(response.context["cleaned_requests"], "Blue balloons")

    def test_design_endpoint_contains_only_design_delivery_content(self):
        BookingDesignDelivery.objects.create(booking=self.booking, image="designs/example.png", caption="Pink backdrop")
        response = self.client.get(self.url, {"section": "design"})
        self.assertContains(response, "Pink backdrop")
        self.assertContains(response, "Download Design")
        for text in ('id="modalType"', 'id="modalPrice"', 'id="booking_modal_map"', "tracker-steps", "Pricing &amp; Payment", "Design Preferences"):
            self.assertNotContains(response, text)
        details = self.client.get(self.url)
        self.assertContains(details, "View Event Design")
        self.assertNotContains(details, "Download Design")

    def test_deleted_design_shows_empty_state_on_next_open(self):
        delivery = BookingDesignDelivery.objects.create(booking=self.booking, image="designs/example.png")
        delivery.delete()
        response = self.client.get(self.url, {"section": "design"})
        self.assertContains(response, "will appear here once uploaded")
        self.assertNotContains(response, "Download Design")

    def test_old_edit_url_and_filtered_off_page_edit_keep_saved_prefill(self):
        self.booking.status = "pending"
        self.booking.save()
        for number in range(11):
            Booking.objects.create(user=self.user, event_date=date(2099, 7, 15), event_time=time(7),
                event_location="Elsewhere", event_type=f"Other {number}", package_type="Birthday Package", total_price=6000)
        response = self.client.get(reverse("edit_booking", args=[self.booking.pk]))
        self.assertRedirects(response, f"{reverse('customer_profile')}?open_edit={self.booking.pk}")
        response = self.client.get(reverse("customer_profile"), {"open_edit": self.booking.pk, "status": "confirmed", "search": "unmatched"})
        self.assertContains(response, f'id="booking-data-{self.booking.pk}"')
        self.assertContains(response, 'class="raw-end-time">12:00')
        self.assertEqual(response.context["edit_link_booking"].pk, self.booking.pk)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("customer_profile"), {"open_edit": self.booking.pk}).status_code, 404)

    def test_event_date_does_not_mark_an_event_completed(self):
        self.booking.status, self.booking.event_date = "confirmed", date(2020, 1, 1)
        self.booking.save()
        self.payment()
        response = self.client.get(self.url)
        self.assertContains(response, 'booking-state-confirmed')
        self.assertEqual(response.context["tracker_steps"][3]["state"], "upcoming")

    def test_old_standalone_templates_are_removed(self):
        root = Path(__file__).resolve().parent / "templates/client/booking"
        self.assertFalse((root / "booking_detail.html").exists())
        self.assertFalse((root / "booking_form.html").exists())

    def test_profile_has_one_details_shell_and_one_design_shell(self):
        response = self.client.get(reverse("customer_profile"))
        self.assertContains(response, 'id="bookingModal"', count=1)
        self.assertContains(response, 'id="eventDesignModal"', count=1)
        self.assertNotContains(response, 'id="modalType"')  # Content is fetched on open.
