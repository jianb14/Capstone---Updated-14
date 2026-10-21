import json
import shutil
import subprocess
from datetime import date, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Booking, Package, ServiceChargeConfig, SiteSettings, User
from .views.common import capture_booking_fee_policy, get_booking_display_breakdown, get_booking_form_availability


class BookingFormParityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="form-parity-customer", role="customer")
        self.client.force_login(self.user)
        self.config = ServiceChargeConfig.objects.create(pk=1, amount=1000, shop_lat=14.414, shop_lng=120.982, per_km_rate=30)
        site = SiteSettings.load()
        site.booking_overtime_rate = 750
        site.save()
        self.package = Package.objects.create(name="Package A", price=5000)
        self.booking = Booking.objects.create(user=self.user, event_type="Birthday", event_date=date(2099, 2, 15),
            event_time=time(7), event_end_time=time(11, 15), event_end_date=date(2099, 2, 15), duration_minutes=255,
            event_location="Baguio event venue", event_lat="16.4023", event_lng="120.596", venue_landmark="Blue gate",
            package_type="Package A", logistics_fee=7300, logistics_distance_km="225.7", overtime_hours=2,
            overtime_fee=1500, total_price=13800, special_requests="Bring the blue backdrop.",
            design_theme="Princess", color_palette="Pink, Gold", motto_text="Happy Birthday", status="pending")

    def test_profile_receives_saved_end_duration_and_all_fee_rows(self):
        response = self.client.get(reverse("customer_profile"))
        self.assertEqual(response.status_code, 200)
        row = next(b for b in response.context["page_obj"] if b.pk == self.booking.pk)
        self.assertEqual(row.schedule["end_time"], "11:15")
        self.assertEqual(row.schedule["duration_label"], "4h 15m")
        self.assertContains(response, 'class="raw-end-time">11:15')
        detail = self.client.get(reverse("booking_modal_content", args=[self.booking.pk]))
        for text in ["Items subtotal", "7,300.00", "1,500.00", "2 billable hours", "225.70"]:
            self.assertContains(detail, text)
        self.assertNotContains(response, 'id="edit_location_search"')
        self.assertContains(response, 'id="edit_event_location"')

    def test_modal_uses_recorded_price_breakdown(self):
        response = self.client.get(reverse("booking_modal_content", args=[self.booking.pk]))
        for text in ["Price Breakdown", "4h 15m", "7,300.00", "1,500.00", "13,800", "Blue gate", "Princess", "Pink, Gold"]:
            self.assertContains(response, text)

    def test_view_details_explains_logistics_and_overtime_arithmetic(self):
        for url in [reverse("booking_modal_content", args=[self.booking.pk])]:
            response = self.client.get(url)
            self.assertContains(response, "₱1,000.00 base + ₱6,300.00 outside-Cavite distance fee.")
            self.assertContains(response, "2 hr(s) beyond the 3-hour package × ₱750/hr.")
            self.assertContains(response, "Includes styling fee, toll fees, fuel, crew meals, and ingress/egress logistics.")

    def test_saved_fee_explanations_survive_admin_rate_and_notes_changes(self):
        original_notes = self.config.notes
        capture_booking_fee_policy(self.booking, {"base": Decimal("1000"), "capped": False, "in_cavite": False})
        self.booking.save(update_fields=["fee_policy_snapshot"])
        self.config.amount, self.config.notes = 1800, "Changed travel policy"
        self.config.save()
        site = SiteSettings.load()
        site.booking_included_hours, site.booking_overtime_rate = 5, 999
        site.save()
        self.booking.refresh_from_db()
        breakdown = get_booking_display_breakdown(self.booking)
        self.assertEqual(breakdown["logistics_notes"], original_notes)
        self.assertIn("₱1,000.00 base + ₱6,300.00", breakdown["logistics_explanation"])
        self.assertEqual(breakdown["overtime_explanation"], "2 hr(s) beyond the 3-hour package × ₱750/hr.")
        self.assertEqual(breakdown["computed_total"], Decimal("13800"))

    def test_legacy_overtime_uses_saved_fee_and_duration_instead_of_new_admin_rate(self):
        site = SiteSettings.load()
        site.booking_overtime_rate, site.booking_included_hours = 999, 5
        site.save()
        breakdown = get_booking_display_breakdown(self.booking)
        self.assertEqual(breakdown["overtime_explanation"], "2 hr(s) beyond the 3-hour package × ₱750/hr.")

    def test_logistics_override_has_a_confirmed_fee_explanation(self):
        self.booking.logistics_fee_override = Decimal("800")
        breakdown = get_booking_display_breakdown(self.booking)
        self.assertEqual(breakdown["logistics_explanation"], "Logistics fee: ₱800.00 · Confirmed by our team.")
        self.assertNotIn("base +", breakdown["logistics_explanation"])

    def test_browser_and_saved_view_use_the_same_fee_explanations(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is needed to compare fee explanations")
        script = "global.window=global; require('./static/js/booking_logistics.js'); require('./static/js/booking_availability.js');"
        script += "console.log(JSON.stringify({logistics:BookingLogistics.describeQuote({base:1000},{total:7300,extra:6300,inCavite:false,configured:true}),overtime:BookingAvailability.overtimeNote(2,3,750)}));"
        result = subprocess.run([node, "-e", script], cwd=settings.BASE_DIR, capture_output=True, text=True, encoding="utf-8", check=True)
        client = json.loads(result.stdout)
        saved = get_booking_display_breakdown(self.booking)
        self.assertEqual(client["logistics"], saved["logistics_explanation"])
        self.assertEqual(client["overtime"], saved["overtime_explanation"])

    def test_legacy_edit_link_opens_the_shared_edit_form(self):
        response = self.client.get(reverse("edit_booking", args=[self.booking.pk]))
        self.assertRedirects(response, reverse("customer_profile") + f"?open_edit={self.booking.pk}", fetch_redirect_response=False)

    def test_create_and_edit_receive_the_same_availability_policy(self):
        create = self.client.get(reverse("booking_page"))
        edit = self.client.get(reverse("customer_profile"))
        self.assertEqual(create.context["availability_data"], edit.context["availability_data"])
        self.assertEqual(create.context["availability_data"]["overtimeRate"], "750.00")

    def test_catalog_price_change_does_not_change_displayed_booked_total(self):
        self.package.price = 9000
        self.package.save()
        breakdown = get_booking_display_breakdown(self.booking)
        self.assertEqual(breakdown["subtotal"], Decimal("5000"))
        self.assertEqual(breakdown["computed_total"], Decimal("13800"))
        self.assertEqual(sum(item["amount"] for item in breakdown["items"]), Decimal("5000"))

    def test_edit_saves_new_overtime_using_the_admin_rate(self):
        response = self.client.post(reverse("edit_booking", args=[self.booking.pk]), {
            "event_type": "Birthday", "event_date": "2099-02-15", "start_time": "07:00", "end_time": "10:15",
            "event_location": "Bacoor venue address", "event_lat": "14.414", "event_lng": "120.982",
            "package_type": "Package A", "total_price": "1", "design_theme": "Princess", "color_palette": "Pink, Gold",
        })
        self.assertEqual(response.status_code, 302)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.overtime_fee, Decimal("750"))
        self.assertEqual(self.booking.logistics_fee, Decimal("1000"))
        self.assertEqual(self.booking.total_price, Decimal("6750"))
        self.assertEqual(self.booking.event_end_time, time(10, 15))
        self.assertEqual(self.booking.fee_policy_snapshot["included_hours"], 3)
        self.assertEqual(Decimal(self.booking.fee_policy_snapshot["overtime_rate"]), Decimal("750"))
        self.assertEqual(Decimal(self.booking.fee_policy_snapshot["logistics_base"]), Decimal("1000"))

    def test_availability_includes_overnight_conflicts(self):
        today = timezone.localdate()
        overnight = Booking.objects.create(user=self.user, event_date=today - timedelta(days=1), event_time=time(23),
            event_end_date=today, event_end_time=time(8), event_location="Night venue", package_type="Package A",
            total_price=5000, status="confirmed")
        records = get_booking_form_availability()["rangeRecords"]
        self.assertIn({"bookingId": overnight.pk, "date": today.isoformat(), "start": 0, "end": 480}, records)

    def test_shared_picker_keeps_custom_rates_and_excludes_the_edited_booking(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is needed for the shared picker policy check")
        payload = {"todayIso": "2099-02-01", "minDurationHours": 2, "includedHours": 3, "maxDurationHours": 24,
            "overtimeRate": "750", "excludeBookingId": 1, "rangeRecords": [
                {"bookingId": 1, "date": "2099-02-15", "start": 420, "end": 660},
                {"bookingId": 2, "date": "2099-02-15", "start": 720, "end": 840}]}
        script = "global.window=global; const payload=" + json.dumps(payload)
        script += ";global.document={getElementById:()=>({textContent:JSON.stringify(payload)})};require('./static/js/booking_availability.js');"
        script += "const A=BookingAvailability; console.log(JSON.stringify({data:A.readData(),policy:A.getDurationPolicy(),valid:A.validateTimes('17:45','20:45','2099-02-15')}));"
        result = subprocess.run([node, "-e", script], cwd=settings.BASE_DIR, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        self.assertEqual(data["policy"]["overtimeRate"], 750)
        self.assertEqual(data["data"]["bookedRanges"]["2099-02-15"], [[720, 840]])
        self.assertFalse(data["valid"]["violated"])
