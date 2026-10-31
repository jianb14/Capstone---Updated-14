"""Regression tests para sa Step 3 location map + Step 4 Design Preferences.

Sakop:
- create_booking: nasasave ang event_lat/lng, venue_landmark, design_theme,
  color_palette, motto_text; graceful degradation kapag walang map data;
  hindi na-i-keep ang half/invalid coords.
- edit_booking WIPE-GUARD: partial submissions (walang bagong
  fields sa POST) ay HINDI dapat mag-wipe ng naka-save na mapa/design data.
- Templates: stepper wiring (5-step booking page / 4-step edit modal),
  Step 4 markup, map module/CSS links, at detail/admin display surfaces.
"""
from datetime import time
from decimal import Decimal
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from .models import Booking, ServiceChargeConfig, User

BASE_DIR = Path(__file__).resolve().parent.parent
BOOKING_PAGE = BASE_DIR / "app" / "templates" / "client" / "booking" / "booking_page.html"
BOOKING_DETAIL = BASE_DIR / "app" / "templates" / "client" / "booking" / "_details_content.html"
PROFILE_TEMPLATE = BASE_DIR / "app" / "templates" / "client" / "customer_profile.html"
ADMIN_BOOKING_DETAIL = BASE_DIR / "app" / "templates" / "admin" / "booking" / "admin_booking_detail.html"
ADMIN_PAYMENT_DETAIL = BASE_DIR / "app" / "templates" / "admin" / "payment" / "admin_payment_detail.html"
MAP_JS = BASE_DIR / "static" / "js" / "booking_location_map.js"
MAP_JS_MIRROR = BASE_DIR / "staticfiles" / "js" / "booking_location_map.js"
DESIGN_CSS = BASE_DIR / "static" / "css" / "booking_design_step.css"
DESIGN_CSS_MIRROR = BASE_DIR / "staticfiles" / "css" / "booking_design_step.css"


def read_profile_source():
    paths = [PROFILE_TEMPLATE, BOOKING_DETAIL,
        BASE_DIR / "app/templates/client/booking/_edit_data.html"]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def _base_payload(**overrides):
    data = {
        "event_type": "Birthday",
        "event_date": "2030-01-15",
        "start_time": "09:00",
        "end_time": "11:00",
        "event_location": "Test Venue, Quezon City",
        "package_type": "Package A",
        "total_price": "5000.00",
        "special_requests": "",
        # Step 4 required (theme + palette, max 3) — laging kasama by default
        "design_theme": "Princess",
        "color_palette": "Pink, Gold",
        # 📍 Smart-required pin: valid coords by default (map-alive booking).
        # Ang create gate ay nagre-reject kapag walang pin at hindi flag=0 —
        # kaya ang map-degradation tests ay nag-o-override ng coords/flag.
        "event_lat": "14.599500",
        "event_lng": "120.984200",
    }
    data.update(overrides)
    return data


class BookingDesignStepTests(TestCase):
    """Backend save/update ng bagong Step 3/4 fields."""

    def setUp(self):
        ServiceChargeConfig.objects.create(pk=1, shop_lat="14.414", shop_lng="120.982")
        self.user = User.objects.create_user(
            username="design_customer", password="pass1234", role="customer"
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _create_booking(self, **fields):
        defaults = {
            "user": self.user,
            "event_date": "2030-01-15",
            "event_time": time(9, 0),
            "event_type": "Birthday",
            "event_location": "Venue A",
            "package_type": "Package A",
            "total_price": 5000,
            "status": "pending",
        }
        defaults.update(fields)
        return Booking.objects.create(**defaults)

    # --- create_booking -------------------------------------------------

    def test_oversized_reference_rejected_before_creating_booking(self):
        for field in ('reference_images', 'reference_image'):
            with self.subTest(field=field):
                upload = SimpleUploadedFile('large.png', b'x' * (5 * 1024 * 1024 + 1), content_type='image/png')
                response = self.client.post(reverse('create_booking'), _base_payload(**{field: upload}),
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                self.assertEqual(response.status_code, 400)
                self.assertIn('5MB', response.json()['message'])
                self.assertFalse(Booking.objects.filter(user=self.user).exists())

    def test_oversized_reference_edit_preserves_booking(self):
        booking = self._create_booking(motto_text='Original motto')
        upload = SimpleUploadedFile('large.png', b'x' * (5 * 1024 * 1024 + 1), content_type='image/png')
        response = self.client.post(reverse('edit_booking', args=[booking.pk]),
            _base_payload(motto_text='Changed motto', reference_images=upload),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertIn('5MB', response.json()['message'])
        booking.refresh_from_db()
        self.assertEqual(booking.motto_text, 'Original motto')

    def test_reference_size_limit_accepts_exactly_five_megabytes(self):
        from django.test import RequestFactory
        from .views.bookings import _reference_upload_size_error

        upload = SimpleUploadedFile('boundary.png', b'x' * (5 * 1024 * 1024), content_type='image/png')
        request = RequestFactory().post('/', {'reference_images': upload})
        self.assertEqual(_reference_upload_size_error(request), '')

    def test_create_booking_saves_map_and_design_fields(self):
        resp = self.client.post(
            reverse("create_booking"),
            _base_payload(
                event_lat="14.599500",
                event_lng="120.984200",
                venue_landmark="Katabi ng Blue Gate",
                design_theme="Princess",
                color_palette="Pink, Gold",
                motto_text="Happy 18th, Maria!",
            ),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)

        booking = Booking.objects.get(user=self.user)
        self.assertEqual(booking.event_lat, Decimal("14.599500"))
        self.assertEqual(booking.event_lng, Decimal("120.984200"))
        self.assertEqual(booking.venue_landmark, "Katabi ng Blue Gate")
        self.assertEqual(booking.design_theme, "Princess")
        self.assertEqual(booking.color_palette, "Pink, Gold")
        self.assertEqual(booking.motto_text, "Happy 18th, Maria!")

    def test_create_booking_without_map_still_succeeds(self):
        """Graceful degradation (patay ang map → map_available=0): text location
        lang, walang coords — OK pa rin (base fee + admin review later)."""
        resp = self.client.post(
            reverse("create_booking"),
            _base_payload(event_lat="", event_lng="", map_available="0"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)

        booking = Booking.objects.get(user=self.user)
        self.assertIsNone(booking.event_lat)
        self.assertIsNone(booking.event_lng)
        self.assertEqual(booking.event_location, "Test Venue, Quezon City")

    def test_create_booking_rejects_blank_theme(self):
        resp = self.client.post(
            reverse("create_booking"),
            _base_payload(design_theme=""),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Booking.objects.filter(user=self.user).exists())
        self.assertIn("theme", resp.json()["message"].lower())

    def test_create_booking_rejects_blank_palette(self):
        resp = self.client.post(
            reverse("create_booking"),
            _base_payload(color_palette=""),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Booking.objects.filter(user=self.user).exists())

    def test_create_booking_rejects_too_many_palette_colors(self):
        resp = self.client.post(
            reverse("create_booking"),
            _base_payload(color_palette="Pink, Gold, White, Blue"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Booking.objects.filter(user=self.user).exists())
        self.assertIn("3", resp.json()["message"])

    def test_create_booking_accepts_three_palette_colors(self):
        resp = self.client.post(
            reverse("create_booking"),
            _base_payload(color_palette="Pink, Gold, White"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        booking = Booking.objects.get(user=self.user)
        self.assertEqual(booking.color_palette, "Pink, Gold, White")

    def test_create_booking_rejects_short_address(self):
        resp = self.client.post(
            reverse("create_booking"),
            _base_payload(event_location="QC"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Booking.objects.filter(user=self.user).exists())
        self.assertIn("10", resp.json()["message"])

    def test_create_booking_discards_invalid_coords(self):
        # Garbage coords → parehong na-sanitize to None; patay ang map (flag 0)
        # kaya tuloy ang booking — walang stale pin na nai-store.
        resp = self.client.post(
            reverse("create_booking"),
            _base_payload(event_lat="999", event_lng="not-a-number", map_available="0"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)

        booking = Booking.objects.get(user=self.user)
        self.assertIsNone(booking.event_lat)
        self.assertIsNone(booking.event_lng)

    def test_create_booking_rejects_half_coords(self):
        """Kapag isa lang ang laman ng lat/lng, pareho → None (walang stale pin)."""
        resp = self.client.post(
            reverse("create_booking"),
            _base_payload(event_lat="14.599500", event_lng="", map_available="0"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)

        booking = Booking.objects.get(user=self.user)
        self.assertIsNone(booking.event_lat)
        self.assertIsNone(booking.event_lng)

    # --- edit_booking wipe-guard ---------------------------------------

    def test_legacy_edit_post_does_not_wipe_design_fields(self):
        """Partial POST (walang bagong keys) = hindi nagbabago
        ang naka-save na mapa/design data."""
        booking = self._create_booking(
            event_lat=Decimal("14.599500"),
            event_lng=Decimal("120.984200"),
            venue_landmark="Blue Gate",
            design_theme="Princess",
            color_palette="Pink, Gold",
            motto_text="Happy 18th!",
        )

        legacy_payload = _base_payload(
            event_location="Venue A (updated)",
            special_requests="New notes",
        )

        resp = self.client.post(reverse("edit_booking", args=[booking.id]), legacy_payload)
        self.assertEqual(resp.status_code, 302)

        booking.refresh_from_db()
        # Na-update ang lumang fields…
        self.assertEqual(booking.event_location, "Venue A (updated)")
        # …pero hindi nabura ang mapa/design data (wipe-guard)
        self.assertEqual(booking.event_lat, Decimal("14.599500"))
        self.assertEqual(booking.event_lng, Decimal("120.984200"))
        self.assertEqual(booking.venue_landmark, "Blue Gate")
        self.assertEqual(booking.design_theme, "Princess")
        self.assertEqual(booking.color_palette, "Pink, Gold")
        self.assertEqual(booking.motto_text, "Happy 18th!")

    def test_edit_post_updates_design_fields_when_keys_present(self):
        booking = self._create_booking(design_theme="Rainbow", motto_text="Old")

        resp = self.client.post(
            reverse("edit_booking", args=[booking.id]),
            _base_payload(
                design_theme="Dinosaur",
                color_palette="Green, Brown",
                motto_text="Roar 5th!",
                venue_landmark="Gate 3",
                event_lat="14.600000",
                event_lng="121.000000",
            ),
        )
        self.assertEqual(resp.status_code, 302)

        booking.refresh_from_db()
        self.assertEqual(booking.design_theme, "Dinosaur")
        self.assertEqual(booking.color_palette, "Green, Brown")
        self.assertEqual(booking.motto_text, "Roar 5th!")
        self.assertEqual(booking.venue_landmark, "Gate 3")
        self.assertEqual(booking.event_lat, Decimal("14.600000"))

    def test_edit_modal_post_rejects_blank_theme(self):
        """Strict sa edit modal (keys present): blank theme = reject."""
        booking = self._create_booking(design_theme="Rainbow", color_palette="Pink")

        resp = self.client.post(
            reverse("edit_booking", args=[booking.id]),
            _base_payload(design_theme="", color_palette="Pink"),
        )
        self.assertEqual(resp.status_code, 302)

        booking.refresh_from_db()
        self.assertEqual(booking.design_theme, "Rainbow")

    def test_edit_modal_post_rejects_too_many_palette_colors(self):
        booking = self._create_booking(design_theme="Rainbow", color_palette="Pink")

        resp = self.client.post(
            reverse("edit_booking", args=[booking.id]),
            _base_payload(
                design_theme="Rainbow",
                color_palette="Pink, Gold, White, Blue",
            ),
        )
        self.assertEqual(resp.status_code, 302)

        booking.refresh_from_db()
        self.assertEqual(booking.color_palette, "Pink")

    def test_edit_modal_post_rejects_short_address(self):
        booking = self._create_booking()

        resp = self.client.post(
            reverse("edit_booking", args=[booking.id]),
            _base_payload(event_location="QC"),
        )
        self.assertEqual(resp.status_code, 302)

        booking.refresh_from_db()
        self.assertNotEqual(booking.event_location, "QC")

class BookingDesignStepTemplateTests(TestCase):
    """Wiring ng stepper/map/design-preferences markup sa mga template."""

    def setUp(self):
        self.page = BOOKING_PAGE.read_text(encoding="utf-8")

    def test_booking_page_stepper_has_five_steps(self):
        for step_no in range(1, 6):
            self.assertIn(f'id="step-{step_no}-indicator"', self.page)
        self.assertIn('id="step-4"', self.page)
        self.assertIn('id="step-5"', self.page)
        self.assertIn("Design Preferences", self.page)
        self.assertIn("STEPPER_PROGRESS", self.page)
        self.assertIn("['0%', '20%', '40%', '60%', '80%']", self.page)

    def test_booking_page_location_card_wiring(self):
        self.assertIn('id="booking_location_map"', self.page)
        self.assertIn('id="event_location"', self.page)
        self.assertNotIn('id="location_search"', self.page)
        self.assertIn('id="location_suggestions"', self.page)
        self.assertIn('id="location_use_my"', self.page)
        self.assertIn('name="event_lat"', self.page)
        self.assertIn('name="event_lng"', self.page)
        self.assertIn('name="venue_landmark"', self.page)
        self.assertIn("booking_location_map.js", self.page)
        self.assertIn("leaflet@1.9.4", self.page)
        self.assertIn("window.BookingLocationMap", self.page)

    def test_booking_page_design_preferences_wiring(self):
        self.assertIn('id="designThemeChips"', self.page)
        self.assertIn('id="designPaletteSwatches"', self.page)
        self.assertIn('name="design_theme"', self.page)
        self.assertIn('name="color_palette"', self.page)
        self.assertIn('name="motto_text"', self.page)
        self.assertIn('id="btnNextDesignToReview"', self.page)
        self.assertIn('id="btnPrevFromDesign"', self.page)
        # Step 4 required: theme + palette (max 3)
        self.assertIn('id="design_theme_error"', self.page)
        self.assertIn('id="color_palette_error"', self.page)
        self.assertIn('MAX_PALETTE_COLORS = 3', self.page)
        self.assertIn('validateDesignPreferences', self.page)
        self.assertIn('No map pin — our crew will confirm', self.page)
        # Step 3 strength: min-length hint (map pa rin optional)
        self.assertIn('at least 10 characters', self.page)
        # English landmark placeholder (walang Tagalog copy)
        self.assertIn('Near Blue Gate, 2nd floor of Robinsons Mall', self.page)
        self.assertNotIn('katabi ng Blue Gate', self.page)
        # Moved mula Step 3: nasa Step 4 na ngayon ang mga ito
        self.assertIn('name="special_requests"', self.page)
        self.assertIn('name="reference_images"', self.page)
        # Review step ay Step 5 na
        self.assertIn('id="btnSubmitBooking"', self.page)
        self.assertIn("showStep(5)", self.page)

    def test_edit_modal_has_five_steps_with_design_step(self):
        profile = read_profile_source()
        for step_no in range(1, 6):
            self.assertIn(f'id="edit-step-{step_no}-indicator"', profile)
        self.assertIn('id="edit-step-5"', profile)
        # Bagong Preview step (mirror ng booking page Step 2)
        self.assertIn('id="editPreviewImagesGrid"', profile)
        self.assertIn('id="editPreviewEmptyMessage"', profile)
        self.assertIn('id="btnPrevEditPreview"', profile)
        self.assertIn('id="btnNextEditPreview"', profile)
        self.assertIn('renderEditPackagePreview', profile)
        self.assertIn('edit-preview-data', profile)
        self.assertIn('id="editDesignThemeChips"', profile)
        self.assertIn('id="editDesignPaletteSwatches"', profile)
        self.assertIn('name="design_theme"', profile)
        self.assertIn('name="color_palette"', profile)
        self.assertIn('name="motto_text"', profile)
        self.assertIn('id="edit_booking_location_map"', profile)
        self.assertIn('name="event_lat"', profile)
        self.assertIn('name="venue_landmark"', profile)
        self.assertIn('id="btnNextEditDesignToReview"', profile)
        self.assertIn("EDIT_STEP_PROGRESS", profile)
        self.assertIn("['0%', '20%', '40%', '60%', '80%']", profile)
        self.assertIn("showEditStep(5)", profile)
        # Step 4 required wiring
        self.assertIn('id="edit_design_theme_error"', profile)
        self.assertIn('id="edit_color_palette_error"', profile)
        self.assertIn('EDIT_MAX_PALETTE_COLORS = 3', profile)
        self.assertIn('validateEditDesignPreferences', profile)
        self.assertIn('No map pin — our crew will confirm', profile)
        # English landmark placeholder
        self.assertIn('Near Blue Gate, 2nd floor of Robinsons Mall', profile)
        self.assertNotIn('katabi ng Blue Gate', profile)
        # Prefill raw data para sa lumang bookings
        for raw_key in ("raw-lat", "raw-lng", "raw-theme", "raw-palette", "raw-motto", "raw-landmark"):
            self.assertIn(raw_key, profile)

    def test_edit_modal_view_details_shows_design_rows(self):
        profile = read_profile_source()
        self.assertIn('id="modalTheme"', profile)
        self.assertIn('id="modalPalette"', profile)
        self.assertIn('id="modalMotto"', profile)
        self.assertIn('id="modalLandmarkRow"', profile)
        self.assertIn("Design Notes / Special Requests", profile)

    def test_edit_modal_has_required_design_fields(self):
        legacy = read_profile_source()
        self.assertIn('name="venue_landmark"', legacy)
        self.assertIn('name="design_theme"', legacy)
        self.assertIn('name="color_palette"', legacy)
        self.assertIn('name="motto_text"', legacy)
        self.assertIn("Design Notes / Special Requests", legacy)
        self.assertIn("Near Blue Gate, 2nd floor of Robinsons Mall", legacy)
        self.assertNotIn("katabi ng Blue Gate", legacy)

    def test_detail_and_admin_surfaces_show_design_data(self):
        detail = BOOKING_DETAIL.read_text(encoding="utf-8")
        self.assertIn('id="booking_modal_map"', detail)
        self.assertIn("Design Preferences", detail)
        self.assertIn("Design Notes / Special Requests", detail)
        self.assertIn("booking.venue_landmark", detail)
        # Laging render (fallback kapag walang coords/data)
        self.assertIn("No map pin saved", detail)
        self.assertIn('booking.design_theme|default', detail)
        self.assertIn('booking.color_palette|default', detail)

        admin_detail = ADMIN_BOOKING_DETAIL.read_text(encoding="utf-8")
        self.assertIn('id="admin_booking_detail_map"', admin_detail)
        self.assertIn("Design Preferences", admin_detail)
        self.assertIn("Design Notes / Special Requests", admin_detail)
        self.assertIn("booking.motto_text", admin_detail)
        self.assertIn("No map pin saved", admin_detail)

        admin_payment = ADMIN_PAYMENT_DETAIL.read_text(encoding="utf-8")
        self.assertIn("booking.design_theme", admin_payment)
        self.assertIn("booking.venue_landmark", admin_payment)

    def test_map_module_and_css_files_exist(self):
        for path in (MAP_JS, MAP_JS_MIRROR, DESIGN_CSS, DESIGN_CSS_MIRROR):
            self.assertTrue(path.exists(), str(path))

        module = MAP_JS.read_text(encoding="utf-8")
        self.assertIn("global.BookingLocationMap", module)
        self.assertIn("function initReadOnly(", module)
        self.assertIn("/booking/places/search/", module)
        self.assertIn("/booking/places/reverse/", module)
        # Tile provider: Esri World Street Map primary (libre, walang key —
        # hindi tulad ng CARTO na nagre-require na ng key kahit free tier),
        # OSM France HOT ang fallback. Walang cartocdn o
        # tile.openstreetmap.org tile layer dapat.
        self.assertIn("server.arcgisonline.com", module)
        self.assertIn("tile.openstreetmap.fr/hot", module)
        self.assertNotIn("cartocdn", module)
        self.assertNotIn("tileLayer('https://tile.openstreetmap.org", module)
        # Step D: short-form credit (hindi full paragraph) + prefix off +
        # custom dot pin sa editable map (walang default flag/image marker).
        self.assertIn("Source: Esri, TomTom, Garmin, FAO, NOAA, USGS", module)
        self.assertNotIn("Esri China (Hong Kong)", module)
        self.assertIn("setPrefix(false)", module)
        self.assertIn("booking-map-div-icon", module)
        # Step E: English status copy
        self.assertIn("Finding address for the pinned location", module)
        self.assertNotIn("katabi ng Blue Gate", module)
        # Graceful degradation guard: kapag walang Leaflet, huwag mag-crash
        self.assertIn("typeof global.L === 'undefined'", module)

        # Mirror ay naka-sync sa source
        mirror = MAP_JS_MIRROR.read_text(encoding="utf-8")
        self.assertEqual(mirror, module)

        css = DESIGN_CSS.read_text(encoding="utf-8")
        self.assertIn(".design-chip {", css)
        self.assertIn(".booking-location-map {", css)
        self.assertIn('[data-theme="light"] .design-chip', css)
        # Step D: minimized attribution + disabled palette button state
        self.assertIn(".leaflet-control-attribution", css)
        self.assertIn(".palette-add-btn:disabled", css)

        css_mirror = DESIGN_CSS_MIRROR.read_text(encoding="utf-8")
        self.assertEqual(css_mirror, css)
