"""Tests for notification deep-link routing (payment -> payment page, atbp.).

Dati lahat ng notif click ay bumabagsak sa booking detail
(customer_profile / admin_booking_detail), kahit payment o review yun —
kasi ang Notification/AdminNotification ay may booking FK lang, walang type
info. Ang routing helpers sa context_processors ay nagbabasa ng message
text para i-route bawat notif sa tamang page.
"""
from datetime import date, time

from django.test import Client, TestCase
from django.urls import reverse

from .context_processors import _admin_notif_target_url, _customer_notif_target_url
from .models import AdminNotification, Booking, Notification, Payment, User


class NotifRoutingTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.customer = User.objects.create_user(
            username="notif_cust", email="notif_cust@test.com",
            password="pass12345", role="customer",
        )
        self.admin = User.objects.create_user(
            username="notif_admin", email="notif_admin@test.com",
            password="pass12345", role="admin",
        )
        self.booking = Booking.objects.create(
            user=self.customer,
            event_date=date(2099, 6, 15),
            event_time=time(10, 0),
            event_type="Birthday",
            event_location="Test Venue",
            package_type="Package A",
            total_price=5000,
            status="pending",
        )

    def _customer_notif(self, message):
        return Notification.objects.create(
            user=self.customer, booking=self.booking, message=message
        )

    # ---- Customer routing ----

    def test_customer_design_ready_links_directly_to_event_design_section(self):
        notif = self._customer_notif(f"Your backdrop design for booking #{self.booking.id} is ready! Open your booking details to view and download it.")
        self.assertEqual(_customer_notif_target_url(notif), f"{reverse('customer_profile')}?booking_id={self.booking.id}&modal=design&from_notif=1")

    def test_customer_payment_verified_goes_to_payment_history(self):
        notif = self._customer_notif(
            f"Your payment of PHP 1,000.00 for Booking #{self.booking.id} "
            "has been verified. Thank you!"
        )
        url = _customer_notif_target_url(notif)
        self.assertEqual(url, f"{reverse('my_payments')}?tab=payment_history")

    def test_customer_payment_reminder_goes_to_payment_history(self):
        notif = self._customer_notif(
            f"Payment Reminder: Booking #{self.booking.id} for 2099-06-15 "
            "still has outstanding balance. Please settle your payment "
            "to secure your slot. Thank you!"
        )
        url = _customer_notif_target_url(notif)
        self.assertEqual(url, f"{reverse('my_payments')}?tab=payment_history")

    def test_customer_booking_approved_goes_to_action_required(self):
        notif = self._customer_notif(
            f"Great news! Your booking #{self.booking.id} has been approved! "
            "Please proceed to payment to confirm your slot."
        )
        url = _customer_notif_target_url(notif)
        self.assertEqual(url, f"{reverse('my_payments')}?tab=action_required")

    def test_customer_booking_confirmed_stays_on_profile_detail(self):
        notif = self._customer_notif(
            f"Hooray! Your booking #{self.booking.id} is now CONFIRMED! See you soon!"
        )
        url = _customer_notif_target_url(notif)
        self.assertEqual(
            url,
            f"{reverse('customer_profile')}?search={self.booking.id}"
            f"&booking_id={self.booking.id}&from_notif=1",
        )

    # ---- Admin routing ----

    def test_admin_new_payment_goes_to_payment_detail(self):
        payment = Payment.objects.create(
            booking=self.booking,
            amount=1000,
            payment_method="gcash",
            payment_type="downpayment",
            payment_status="pending",
            transaction_ref="NOTIFDETAIL123",
            gcash_reference_number="REF123",
            gcash_sender_name="Tester",
        )
        notif = AdminNotification.objects.create(
            booking=self.booking,
            user=self.customer,
            message=(
                f"New GCash payment submitted for Booking #{self.booking.id} "
                f"by {self.customer.username}. Amount: PHP 1,000.00 | Ref: REF123"
            ),
        )
        url = _admin_notif_target_url("event", notif.message, notif.booking)
        self.assertEqual(
            url, reverse("admin_payment_detail", args=[payment.id])
        )

    def test_admin_payment_without_record_falls_back_to_filtered_list(self):
        notif = AdminNotification.objects.create(
            booking=self.booking,
            user=self.customer,
            message=(
                f"New GCash payment submitted for Booking #{self.booking.id} "
                "by someone. Amount: PHP 1,000.00"
            ),
        )
        url = _admin_notif_target_url("event", notif.message, notif.booking)
        self.assertEqual(
            url, f"{reverse('admin_payment_list')}?search=booking:{self.booking.id}"
        )

    def test_admin_new_review_goes_to_review_detail(self):
        from .models import Review

        review = Review.objects.create(
            user=self.customer,
            booking=self.booking,
            rating=5,
            comment="Great service!",
        )
        notif = AdminNotification.objects.create(
            booking=self.booking,
            user=self.customer,
            message="submitted a new review.",
        )
        url = _admin_notif_target_url("event", notif.message, notif.booking)
        self.assertEqual(
            url, reverse("admin_review_detail", args=[review.id])
        )

    def test_admin_review_without_record_falls_back_to_reviews_list(self):
        notif = AdminNotification.objects.create(
            booking=self.booking,
            user=self.customer,
            message="submitted a new review.",
        )
        url = _admin_notif_target_url("event", notif.message, notif.booking)
        self.assertEqual(
            url, f"{reverse('admin_reviews')}?search={self.customer.username}"
        )

    def test_admin_chat_request_goes_to_chat_inbox(self):
        notif = AdminNotification.objects.create(
            user=self.customer,
            message=f"{self.customer.username} requested admin chat support: Help!",
        )
        url = _admin_notif_target_url("event", notif.message, notif.booking)
        self.assertEqual(url, reverse("admin_chat_inbox"))

    def test_admin_booking_approved_stays_on_booking_detail(self):
        notif = AdminNotification.objects.create(
            booking=self.booking,
            user=self.customer,
            message=f"Booking #{self.booking.id} approved by boss.",
        )
        url = _admin_notif_target_url("event", notif.message, notif.booking)
        self.assertEqual(
            url, reverse("admin_booking_detail", args=[self.booking.id])
        )

    # ---- End-to-end: payment deep-link filter works ----

    def test_admin_payment_list_booking_search_filters_payment(self):
        self.client.force_login(self.admin)
        target = Payment.objects.create(
            booking=self.booking,
            amount=1000,
            payment_method="gcash",
            payment_type="downpayment",
            payment_status="pending",
            transaction_ref="NOTIFTEST123",
            gcash_reference_number="REF123",
            gcash_sender_name="Tester",
        )
        other_booking = Booking.objects.create(
            user=self.customer,
            event_date=date(2000, 7, 20),
            event_time=time(10, 0),
            event_type="Wedding",
            event_location="Other Venue",
            package_type="Package B",
            total_price=8000,
            status="completed",
        )
        Payment.objects.create(
            booking=other_booking,
            amount=2000,
            payment_method="gcash",
            payment_type="downpayment",
            payment_status="pending",
            transaction_ref="NOTIFTEST456",
            gcash_reference_number="REF456",
            gcash_sender_name="Other",
        )
        other_payment = Payment.objects.get(transaction_ref="NOTIFTEST456")
        response = self.client.get(
            reverse("admin_payment_list"), {"search": f"booking:{self.booking.id}"}
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        # Payment ID cell lang ang i-assert (hindi buong body) — kasi ang "#<id>"
        # ay pwedeng mag-match sa ibang parte ng HTML tulad ng hex colors.
        self.assertIn(f"Payment ID\">#{target.id}", body)
        self.assertNotIn(f"Payment ID\">#{other_payment.id}", body)

