"""Regression tests para sa booking date/time availability guardrails.

Sakop:
- Booking page: inline fully-booked banner + nearest-open-date suggestions
  (client-side), at 7AM–6PM / 2-hour-minimum guardrails sa time inputs.
- Edit booking flow (customer profile): parehong guardrails na naka-mirror.
- Backend (source of truth): past date, 7AM–6PM bounds, 2h minimum duration,
  at overlap rejection sa create_booking — hindi puwedeng bumigat o mahina
  dahil sa frontend changes.
"""
import re
from datetime import date, time, timedelta
from pathlib import Path

from django.test import Client, TestCase
from django.urls import reverse

from .models import Booking, BlockedDate, User

BASE_DIR = Path(__file__).resolve().parent.parent

BOOKING_TEMPLATE = (
    BASE_DIR / "app" / "templates" / "client" / "booking" / "booking_page.html"
)
PROFILE_TEMPLATE = (
    BASE_DIR / "app" / "templates" / "client" / "customer_profile.html"
)
BOOKING_CSS = BASE_DIR / "static" / "css" / "client_booking.css"
BOOKING_CSS_MIRROR = BASE_DIR / "staticfiles" / "css" / "client_booking.css"


class BookingAvailabilityTemplateTests(TestCase):
    """Ang mga bagong UI hook ay naka-wire nang tama sa templates/CSS."""

    def setUp(self):
        self.template = BOOKING_TEMPLATE.read_text(encoding="utf-8")

    def test_fully_booked_banner_markup_present(self):
        # Inline banner sa ilalim ng Event Date (Option A)
        self.assertIn('id="event_date_availability"', self.template)
        self.assertIn('id="availability_suggestions"', self.template)
        self.assertIn(
            "This date is fully booked (7:00 AM – 6:00 PM all taken).",
            self.template,
        )

    def test_fully_booked_detection_functions_present(self):
        # Client-side union check at nearest-open-date suggestions
        self.assertIn("function isFullyBookedDate(", self.template)
        self.assertIn("function getBookedRangesForDate(", self.template)
        self.assertIn("function getNearestOpenDates(", self.template)
        self.assertIn("function updateEventDateAvailability(", self.template)

    def test_suggestions_mirrors_server_availability_logic(self):
        # 60-day window + 3 suggestions, iniiwasan ang past/blocked/fully-booked
        # (inline calendar functions pa rin; ang module ang ginagamit ng guards)
        self.assertIn("daysChecked < 60", self.template)
        self.assertIn("maxSuggestions = limit || 3", self.template)
        self.assertIn("if (isBlockedDate(candidate)) continue;", self.template)
        self.assertIn("if (isFullyBookedDate(candidate)) continue;", self.template)
        # Module mirror (server-data based, walang calendar dependency)
        module = (
            BASE_DIR / "static" / "js" / "booking_availability.js"
        ).read_text(encoding="utf-8")
        self.assertIn("daysChecked < SUGGESTION_WINDOW_DAYS", module)
        self.assertIn("isDateUnavailable(candidate, data)", module)

    def test_date_change_and_dateclick_refresh_banner(self):
        # change handler + page load + reset + chip + fallback block refresh()
        self.assertGreaterEqual(
            self.template.count("updateEventDateAvailability();"), 5
        )
        # Lahat ng entry points ay dumadaan din sa Next-state choke point
        self.assertGreaterEqual(self.template.count("refreshStepTwoNextState();"), 4)
        # dateClick handler (calendar cell): module bridge, may fully-booked guard
        self.assertIn("if (moduleIsBlockedDate(clickedDate)) {", self.template)
        self.assertIn("if (moduleIsFullyBookedDate(clickedDate)) {", self.template)

    def test_step_two_validation_blocks_fully_booked_date(self):
        self.assertIn(
            "setBookingFieldError('event_date', 'This date is fully booked (7:00 AM – 6:00 PM all taken). Please choose a different date.');",
            self.template,
        )

    def test_decoupled_module_wired_with_server_data(self):
        # Phase 1: module + server-side JSON data, hindi nakadepende sa calendar
        module = (
            BASE_DIR / "static" / "js" / "booking_availability.js"
        ).read_text(encoding="utf-8")
        self.assertIn("global.BookingAvailability = {", module)
        self.assertIn("function computeNextDisabled(", module)
        self.assertIn(
            '<script src="{% static \'js/booking_availability.js\' %}',
            self.template,
        )
        self.assertIn(
            '{{ availability_data|json_script:"booking-availability-data" }}',
            self.template,
        )
        # Bridge: inline guards dumadaan sa module, may calendar fallback
        self.assertIn("function moduleIsBlockedDate(", self.template)
        self.assertIn("function moduleIsFullyBookedDate(", self.template)
        self.assertIn("function moduleNearestOpenDates(", self.template)
        self.assertIn(
            "window.BookingAvailability.computeNextDisabled(",
            self.template,
        )
        # Fallback safety net: hiwalay na script block, sariling listener
        self.assertIn("Fallback safety net (Phase 1)", self.template)
        self.assertGreaterEqual(
            self.template.count(
                "document.addEventListener('DOMContentLoaded', function () {"
            ),
            2,
        )

    def test_single_writer_next_state_covers_empty_time(self):
        # Regression: blocked/fully-booked date + walang laman ang oras ay
        # dapat naka-disable pa rin ang Next (hindi ni-re-enable ng time guard
        # na nagbabalik ng False kapag null ang minutes).
        self.assertIn(
            "const dateBlocked = !!selectedDate && (",
            self.template,
        )
        self.assertIn(
            "btnNextToSummary.disabled = dateBlocked || timeViolated;",
            self.template,
        )
        # Reset path ay dumadaan din sa single writer, hindi direktang false
        self.assertIn(
            "updateEventDateAvailability();\n            refreshStepTwoNextState();",
            self.template,
        )

    def test_step_two_instant_time_guards_present(self):
        # Instant guard: hindi na hinihintay ang Next click
        self.assertIn("function validateStepTwoTimesInstant(", self.template)
        self.assertIn(
            "setBookingFieldError('start_time', 'Booking hours are 7:00 AM to 6:00 PM only. Please choose a start time between 7:00 AM and 4:00 PM.');",
            self.template,
        )
        self.assertIn(
            "setBookingFieldError('end_time', 'Booking hours are 7:00 AM to 6:00 PM only. End time must be between 7:00 AM and 6:00 PM.');",
            self.template,
        )
        self.assertIn(
            "setBookingFieldError('end_time', 'Event duration must be at least 2 hours.');",
            self.template,
        )
        # Time change handlers ay naka-wire sa Next-state choke point
        self.assertIn(
            "startTimeInput.addEventListener('change', function () { validateEndTime(); refreshStepTwoNextState(); });",
            self.template,
        )
        self.assertIn(
            "endTimeInput.addEventListener('change', refreshStepTwoNextState);",
            self.template,
        )
        # Helper hint sa ilalim ng Event Date (native picker limitation note)
        self.assertIn('class="booking-date-hint"', self.template)
        self.assertIn(".booking-date-hint {", BOOKING_CSS.read_text(encoding="utf-8"))
        self.assertIn(".booking-date-hint {", BOOKING_CSS_MIRROR.read_text(encoding="utf-8"))

    def test_date_input_min_is_refreshed(self):
        # Hindi lang sa unang load — naka-refresh lagi ang min attribute
        self.assertIn("dateInput.min = getLocalTodayStr();", self.template)

    def test_time_inputs_enforce_operating_hours(self):
        # HTML attributes para sa native time picker
        self.assertIn('id="start_time" name="start_time" data-label="Start Time" min="07:00" max="16:00" step="900"', self.template)
        self.assertIn('id="end_time" name="end_time" data-label="End Time" min="07:00" max="18:00" step="900"', self.template)
        # JS: start floor/ceiling + end = start + 2h, capped sa 18:00
        self.assertIn("startTimeInput.max = '16:00';", self.template)
        self.assertIn("startTimeInput.step = 900;", self.template)
        self.assertIn("minEndMinutes = startMinutes + 120;", self.template)
        self.assertIn("if (minEndMinutes > 18 * 60) minEndMinutes = 18 * 60;", self.template)
        self.assertIn("endTimeInput.max = '18:00';", self.template)

    def test_custom_pickers_no_focus_autoopen_and_sturdy_close(self):
        # Regression test para sa bug na "may nakalabas agad na time dropdown
        # at hindi na-cclose": walang focus auto-open, pointerdown-capture +
        # focusin outside-close, single-open via closeOthers, at walang
        # pagbubukas kapag walang slots.
        picker_a = (
            BASE_DIR / "static" / "js" / "booking_picker_a.js"
        ).read_text(encoding="utf-8")
        picker_c = (
            BASE_DIR / "static" / "js" / "booking_picker_c.js"
        ).read_text(encoding="utf-8")
        # WALANG focus auto-open (ito ang sanhi ng auto-bukas)
        self.assertNotIn(
            "addEventListener('focus', function () { if (pop.hidden) open(); });",
            picker_a + picker_c,
        )
        # Matibay na outside-close + single-open
        self.assertIn("outsideCloser", picker_a)
        self.assertIn("addEventListener('pointerdown'", picker_a)
        self.assertIn("closeOthers", picker_a)
        self.assertIn("closeOthers(pop)", picker_c)
        # Time dropdown: hindi bumubukas kapag walang slots
        self.assertIn("if (!slots().length) return;", picker_c)
        self.assertIn("H.outsideCloser(pop, input", picker_c)
        self.assertIn("booking-picker-timehint", picker_c)

    def test_custom_pickers_wired(self):
        # Custom date popover: blocked/past/lead/fully-booked disabled
        self.assertIn("booking_picker_a.js", self.template)
        self.assertIn("booking_picker_c.js", self.template)
        self.assertIn("window.BookingPickers.init({", self.template)
        module = (
            BASE_DIR / "static" / "js" / "booking_availability.js"
        ).read_text(encoding="utf-8")
        self.assertIn("function getDateBlockReason(", module)
        self.assertIn("function getMinBookableDate(", module)
        self.assertIn("function getAvailableStartSlots(", module)
        self.assertIn("function getAvailableEndSlots(", module)
        # Server → client wiring: ang view ang nagbibigay ng leadDays key,
        # at ang module ang bumabasa nito mula sa json_script payload.
        views_source = (
            BASE_DIR / "app" / "views" / "bookings.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"leadDays"', views_source)
        self.assertIn("data.leadDays", module)
        picker_a = (
            BASE_DIR / "static" / "js" / "booking_picker_a.js"
        ).read_text(encoding="utf-8")
        picker_c = (
            BASE_DIR / "static" / "js" / "booking_picker_c.js"
        ).read_text(encoding="utf-8")
        self.assertIn("getDateBlockReason", picker_a)
        self.assertIn("getAvailableStartSlots", picker_c)
        self.assertIn("getAvailableEndSlots", picker_c)
        for css_path in (BOOKING_CSS, BOOKING_CSS_MIRROR):
            css = css_path.read_text(encoding="utf-8")
            self.assertIn(".booking-picker-pop {", css, str(css_path))
            self.assertIn(".booking-picker-day.is-disabled {", css, str(css_path))

    def test_css_cache_bust_updated(self):
        # Cache-bust versions (i-bump kapag nagbabago ang picker/CSS/JS).
        self.assertIn("client_booking.css' %}?v=20261014f", self.template)
        self.assertIn("booking_availability.js' %}?v=20261013a", self.template)
        self.assertIn("booking_picker_a.js' %}?v=20261014f", self.template)
        self.assertIn("booking_picker_c.js' %}?v=20261014e", self.template)

    def test_step2_popover_hidden_icons_and_themed_scrollbar(self):
        # Regression: dapat nakatago ang time dropdown kapag hindi pa napipindot —
        # ang [hidden] ay dapat manalo sa display:flex ng .booking-picker-time
        # (kung hindi, parang "nakabukas agad" na blankong box sa Step 2).
        for css_path in (BOOKING_CSS, BOOKING_CSS_MIRROR):
            css = css_path.read_text(encoding="utf-8")
            self.assertIn(".booking-picker-pop[hidden]", css, str(css_path))
            # Themed scrollbar ng time dropdown (dark default + light mode)
            self.assertIn(
                ".booking-picker-time::-webkit-scrollbar {", css, str(css_path)
            )
            self.assertIn(
                '[data-theme="light"] .booking-picker-time::-webkit-scrollbar-thumb',
                css,
                str(css_path),
            )
            # Radius ng dropdown ay kapareho ng input fields (4px, hindi 12px)
            self.assertRegex(css, r"\.booking-picker-pop \{[^}]*border-radius: 4px")
            # Aktibong/selected = neutral gray (walang asul o pula sa theme)
            self.assertNotIn("#2563eb", css, str(css_path))
            self.assertNotIn(
                ".booking-picker-day.is-selected { background: #ef4444", css
            )
            self.assertIn(
                '[data-theme="light"] .booking-picker-day.is-selected { background: #e5e7eb',
                css,
                str(css_path),
            )
            # Light mode: kita pa rin ang unavailable (pula) at fully-booked (dilaw)
            self.assertIn(
                '[data-theme="light"] .booking-picker-day.is-blocked', css, str(css_path)
            )
            self.assertIn(
                '[data-theme="light"] .booking-picker-day.is-full', css, str(css_path)
            )
            # Minimal lang na shadow ng dropdown
            self.assertIn("box-shadow: 0 4px 12px", css, str(css_path))
            # Legend sa date dropdown (pula = unavailable, dilaw = fully booked)
            self.assertIn(".booking-picker-legend {", css, str(css_path))
            # Light-mode error border: pulang border gaya ng Event Type
            self.assertRegex(
                css,
                r'\[data-theme="light"\] \.time-field input\.has-error \{'
                r'[^}]*border-color: #ef4444',
            )
            # Unavailable sa calendar = light gray (hindi na aggressive na pula)
            self.assertNotIn("#991b1b", css, str(css_path))
            self.assertIn("background-color: #2a2a2a !important", css, str(css_path))
            # Hindi nag-ho-hover ang unavailable (lahat ng light hover may :not)
            self.assertGreaterEqual(
                css.count(
                    "not(.booking-day-disabled):not(.booking-day-blocked):"
                    "not(.fc-day-other)"
                ),
                7,
                str(css_path),
            )
            # Light mode: may sariling bg/border ang oras options (hindi invisible)
            self.assertIn(
                '[data-theme="light"] .booking-picker-timeopt {',
                css,
                str(css_path),
            )
        picker_a = (
            BASE_DIR / "static" / "js" / "booking_picker_a.js"
        ).read_text(encoding="utf-8")
        picker_c = (
            BASE_DIR / "static" / "js" / "booking_picker_c.js"
        ).read_text(encoding="utf-8")
        # Clickable icons sa kanan ng field: calendar sa date, clock sa Start/End
        self.assertIn("booking-picker-icon", picker_a)
        self.assertIn("fa-calendar-days", picker_a)
        self.assertIn("booking-picker-icon", picker_c)
        self.assertIn("fa-clock", picker_c)
        # Popover naka-attach sa input holder (6px gap lang sa taas nito)
        self.assertIn("popHost", picker_a)
        self.assertIn("popHost", picker_c)
        # Legend ng kulay sa date dropdown footer
        self.assertIn("booking-picker-legend", picker_a)

    def test_unavailable_calendar_light_gray_and_blocked_icon(self):
        # Client + admin calendar: light gray na unavailable cell (hindi
        # aggressive na pula), may blocked icon sa label, at may light-mode
        # readable na kulay ng number/label.
        admin_css = (
            BASE_DIR / "static" / "css" / "admin_calendar.css"
        ).read_text(encoding="utf-8")
        self.assertNotIn("#991b1b", admin_css)
        self.assertIn("background-color: #2a2a2a !important", admin_css)
        self.assertIn("background-color: #e5e7eb !important", admin_css)
        # Blocked icon sa "Unavailable" label (client + admin calendar)
        self.assertIn("fa-ban", self.template)
        admin_tpl = (
            BASE_DIR / "app" / "templates" / "admin" / "admin_calendar.html"
        ).read_text(encoding="utf-8")
        self.assertIn("fa-ban", admin_tpl)
        # Admin CSS cache-bust (bagong design ng unavailable cells)
        self.assertIn("admin_calendar.css' %}?v=20261014b", admin_tpl)
        # Regression: hindi dapat na-trap sa CSS comment ang light-mode
        # number/label rules ng blocked cells (nawawala sila sa light mode
        # kapag nasa loob ng /* ... */).
        stripped_admin = re.sub(r"/\*.*?\*/", "", admin_css, flags=re.S)
        self.assertIn(
            '[data-theme="light"] #admin-calendar .fc .fc-daygrid-day'
            ".booking-day-blocked .fc-daygrid-day-number",
            stripped_admin,
        )
        self.assertIn(
            '[data-theme="light"] #admin-calendar .fc .fc-daygrid-day'
            ".booking-day-blocked .booking-day-blocked-label",
            stripped_admin,
        )

    def test_banner_styles_present_in_css(self):
        for css_path in (BOOKING_CSS, BOOKING_CSS_MIRROR):
            css = css_path.read_text(encoding="utf-8")
            self.assertIn(".booking-availability-banner {", css, str(css_path))
            self.assertIn(".availability-date-chip:hover {", css, str(css_path))
            self.assertIn('[data-theme="light"] .booking-availability-banner {', css, str(css_path))


class EditBookingGuardrailTemplateTests(TestCase):
    """Ang edit-booking flow sa customer profile ay naka-mirror ng guardrails."""

    def setUp(self):
        self.template = PROFILE_TEMPLATE.read_text(encoding="utf-8")

    def test_time_inputs_enforce_operating_hours(self):
        self.assertIn('id="edit_start_time" name="start_time" min="07:00" max="16:00" step="900"', self.template)
        self.assertIn('id="edit_end_time" name="end_time" min="07:00" max="18:00" step="900"', self.template)
        self.assertIn("function updateEditTimeConstraints(", self.template)
        self.assertIn("function getEditTodayIso(", self.template)
        self.assertIn(
            "updateEditTimeConstraints();",
            self.template,
        )

    def test_past_date_validation_in_both_validators(self):
        # Dalawang validateEditBookingForm ang umiiral (inline + steppers)
        self.assertEqual(self.template.count("Event Date cannot be in the past.*"), 2)

    def test_edit_modal_instant_time_guards_present(self):
        # Mirror ng booking_page: instant guard + Next-button choke point
        self.assertIn("function validateEditTimesInstant(", self.template)
        self.assertIn("function refreshEditStepTwoNextState(", self.template)
        self.assertIn("btnNextEditToSummary.disabled = validateEditTimesInstant()", self.template)
        self.assertIn(
            "if (editEndTimeEl) editEndTimeEl.addEventListener('change', refreshEditStepTwoNextState);",
            self.template,
        )
        self.assertIn('class="edit-date-hint"', self.template)
        self.assertIn("customer_profile.css' %}?v=20261013a", self.template)


class CreateBookingValidationTests(TestCase):
    """Backend rules — dapat pareho pa rin ang behaviour (source of truth)."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="avail-cust",
            email="avail@test.com",
            password="pass12345",
            role="customer",
        )
        self.client.force_login(self.user)
        self.url = reverse("create_booking")

    def _future_date(self, days=30):
        return date.today() + timedelta(days=days)

    def _post(self, **overrides):
        data = {
            "event_type": "Birthday",
            "event_date": self._future_date().isoformat(),
            "start_time": "09:00",
            "end_time": "11:00",
            "event_location": "Test Venue",
            "package_type": "Package A",
            "total_price": "5000.00",
            "special_requests": "",
        }
        data.update(overrides)
        return self.client.post(
            self.url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )

    def test_past_date_rejected(self):
        # Gumamit ng 2 araw ang nakaraan para sigurado kahit anong timezone
        # (ang server ay naka-UTC: sa hatinggabi ng PH, ang "kahapon" sa
        # local date ay "ngayon" pa sa UTC kaya time-check ang unang tatama).
        past = (date.today() - timedelta(days=2)).isoformat()
        payload = self._post(
            event_date=past, start_time="07:00", end_time="09:00"
        ).json()
        self.assertFalse(payload["success"])
        self.assertIn("Cannot book a date in the past.", payload["message"])

    def test_start_before_7am_rejected(self):
        payload = self._post(start_time="06:00", end_time="08:00").json()
        self.assertFalse(payload["success"])
        self.assertIn(
            "Booking hours are 7:00 AM to 6:00 PM only.", payload["message"]
        )

    def test_end_after_6pm_rejected(self):
        payload = self._post(start_time="16:00", end_time="19:00").json()
        self.assertFalse(payload["success"])
        self.assertIn(
            "End time must be between 7:00 AM and 6:00 PM.", payload["message"]
        )

    def test_short_duration_rejected(self):
        payload = self._post(start_time="09:00", end_time="10:00").json()
        self.assertFalse(payload["success"])
        self.assertIn(
            "Please choose an end time that is at least 2 hours after the start time.",
            payload["message"],
        )

    def test_overlapping_slot_rejected(self):
        event_date = self._future_date()
        Booking.objects.create(
            user=self.user,
            event_date=event_date,
            event_time=time(10, 0),
            event_type="Wedding",
            event_location="Venue B",
            package_type="Package B",
            total_price=7000,
            status="confirmed",
            special_requests="Notes\n(End Time: 12:00)",
        )
        payload = self._post(
            event_date=event_date.isoformat(),
            start_time="11:00",
            end_time="13:00",
        ).json()
        self.assertFalse(payload["success"])
        self.assertIn("This time slot is already booked", payload["message"])

    def test_admin_blocked_date_rejected(self):
        event_date = self._future_date()
        BlockedDate.objects.create(
            date=event_date, reason="Maintenance", created_by=self.user
        )
        payload = self._post(event_date=event_date.isoformat()).json()
        self.assertFalse(payload["success"])
        self.assertIn("is not available for booking", payload["message"])

    def test_valid_booking_succeeds(self):
        payload = self._post().json()
        self.assertTrue(payload["success"], payload)
        self.assertTrue(
            Booking.objects.filter(
                event_date=self._future_date(), event_time=time(9, 0)
            ).exists()
        )

    def test_overlap_ignores_non_blocking_statuses(self):
        # Ang "pending" na status ay hindi nagba-block (gaya ng dati)
        event_date = self._future_date()
        Booking.objects.create(
            user=self.user,
            event_date=event_date,
            event_time=time(10, 0),
            event_type="Debut",
            event_location="Venue C",
            package_type="Package C",
            total_price=6000,
            status="pending",
            special_requests="Notes\n(End Time: 12:00)",
        )
        payload = self._post(
            event_date=event_date.isoformat(),
            start_time="11:00",
            end_time="13:00",
        ).json()
        self.assertTrue(payload["success"], payload)

