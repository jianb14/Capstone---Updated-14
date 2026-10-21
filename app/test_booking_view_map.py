"""Regression tests para sa Location Map ng View Booking (My Bookings modal)
at sa expandable (fullscreen) read-only map.

Sakop:
- customer_profile View Booking modal (#bookingModal): may #modalMapRow na may
  #booking_modal_map container, pino-populate mula sa .raw-lat/.raw-lng.
- booking_location_map.js: idempotent na initReadOnly (reuse sa paulit-ulit na
  modal open) + fullscreen stage, may BookingLocationMap.collapse().
- Mirror sync ng static/ at staticfiles/ para sa map JS/CSS.
- Page wiring: view_booking at admin_booking_detail ay nagre-render ng mapa.
"""
from datetime import date, time
from pathlib import Path

from django.test import Client, TestCase
from django.urls import reverse

from .models import Booking, User

BASE_DIR = Path(__file__).resolve().parent.parent
PROFILE_TEMPLATE = BASE_DIR / "app" / "templates" / "client" / "customer_profile.html"
MAP_JS = BASE_DIR / "static" / "js" / "booking_location_map.js"
MAP_JS_MIRROR = BASE_DIR / "staticfiles" / "js" / "booking_location_map.js"
DESIGN_CSS = BASE_DIR / "static" / "css" / "booking_design_step.css"
DESIGN_CSS_MIRROR = BASE_DIR / "staticfiles" / "css" / "booking_design_step.css"


class BookingViewMapMarkupTests(TestCase):
    """Source-level wiring ng modal map + fullscreen stage."""

    def setUp(self):
        self.profile = (BASE_DIR / "app/templates/client/booking/_details_content.html").read_text(encoding="utf-8")
        self.controller = (BASE_DIR / "static/js/customer_booking_details.js").read_text(encoding="utf-8")
        self.module = MAP_JS.read_text(encoding="utf-8")
        self.css = DESIGN_CSS.read_text(encoding="utf-8")

    def test_view_booking_modal_has_map_container(self):
        # Container sa #bookingModal (My Bookings → View Details)
        self.assertIn('id="modalMapRow"', self.profile)
        self.assertIn('id="booking_modal_map"', self.profile)
        self.assertIn('data-lat="{{ booking.event_lat }}"', self.profile)
        self.assertIn('data-lng="{{ booking.event_lng }}"', self.profile)
        self.assertIn("initReadOnly", self.controller)
        self.assertIn("expandable: false", self.controller)
        self.assertIn("map.remove()", self.controller)

    def test_read_only_map_is_reusable_and_expandable(self):
        self.assertIn("function initReadOnly(", self.module)
        # Reuse guard para sa "Map container is already initialized"
        self.assertIn("__bookingMapCtx", self.module)
        # Fullscreen stage (body-level) + close helpers
        self.assertIn("booking-map-stage", self.module)
        self.assertIn("function expandMap(", self.module)
        self.assertIn("function collapseMap(", self.module)
        self.assertIn("collapse: collapseMap", self.module)
        # Habang naka-fullscreen: pinapayagan ang panning/zoom
        self.assertIn("map.dragging.enable()", self.module)

    def test_expand_styles_present(self):
        self.assertIn(".booking-map-expand-btn {", self.css)
        self.assertIn(".booking-map-stage {", self.css)
        self.assertIn("body.booking-map-stage-open {", self.css)

    def test_staticfiles_mirrors_in_sync(self):
        self.assertEqual(MAP_JS_MIRROR.read_text(encoding="utf-8"), self.module)
        self.assertEqual(DESIGN_CSS_MIRROR.read_text(encoding="utf-8"), self.css)


class BookingViewMapPageTests(TestCase):
    """Runtime rendering ng mapa sa detail surfaces."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="map_cust", email="map_cust@test.com", password="pass12345", role="customer"
        )
        self.admin = User.objects.create_user(
            username="map_admin", email="map_admin@test.com", password="pass12345", role="admin"
        )

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

    def test_profile_page_renders_modal_map_row(self):
        self._create_booking()
        self.client.force_login(self.user)
        response = self.client.get(reverse("customer_profile"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn('id="bookingModal"', body)
        self.assertIn('data-content-url=', body)
        # Raw coords ay naka-render para sa JS-populated modal map
        self.assertIn("raw-lat", body)
        self.assertIn("raw-lng", body)

    def test_view_booking_page_shows_map_with_pin(self):
        booking = self._create_booking(event_lat="14.599500", event_lng="120.984200")
        self.client.force_login(self.user)
        response = self.client.get(reverse("booking_modal_content", args=[booking.id]))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn('id="booking_modal_map"', body)
        self.assertIn("14.599500", body)

    def test_view_booking_page_fallback_without_pin(self):
        booking = self._create_booking()
        self.client.force_login(self.user)
        response = self.client.get(reverse("booking_modal_content", args=[booking.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("No map pin saved", response.content.decode("utf-8"))

    def test_admin_booking_detail_shows_map_with_pin(self):
        booking = self._create_booking(event_lat="14.599500", event_lng="120.984200")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_booking_detail", args=[booking.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="admin_booking_detail_map"', response.content.decode("utf-8"))

