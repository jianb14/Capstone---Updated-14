"""Regression tests para sa booking date/time availability guardrails.

Sakop:
- Booking page: inline fully-booked banner + nearest-open-date suggestions
  (client-side), at 7AM–6PM / 2-hour-minimum guardrails sa time inputs.
- Edit booking flow (customer profile): parehong guardrails na naka-mirror.
- Backend (source of truth): past date, 7AM–6PM bounds, 2h minimum duration,
  at overlap rejection sa create_booking — hindi puwedeng bumigat o mahina
  dahil sa frontend changes.
- Smart-required pin: backend gate (map_available flag, anti-DevTools) +
  frontend gates/pin-status chips sa create at edit flow.
- Overtime UI labels: start-only hint, fee-breakdown toast, at end-dropdown
  labels/footer — lahat policy-driven mula sa SiteSettings.
"""
import re
from datetime import date, time, timedelta
from decimal import Decimal
from pathlib import Path

from django.test import Client, TestCase
from django.urls import reverse

from .models import Booking, BlockedDate, ServiceChargeConfig, SiteSettings, User

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
        # Start window: 7:00 AM – 5:45 PM (huling 15-min slot bago mag-6:00 PM)
        self.assertIn(
            "setBookingFieldError('start_time', 'Booking hours are 7:00 AM to 6:00 PM only. Please choose a start time between 7:00 AM and 5:45 PM.');",
            self.template,
        )
        # REGRESSION (overnight rule): WALANG 6:00 PM end-window error —
        # pwedeng lumagpas ng 6:00 PM at tumawid ng hatinggabi ang End.
        self.assertNotIn(
            "setBookingFieldError('end_time', 'Booking hours are 7:00 AM to 6:00 PM only. End time must be between 7:00 AM and 6:00 PM.');",
            self.template,
        )
        # Duration guard ay policy-driven (min hours mula sa SiteSettings)
        self.assertIn(
            "setBookingFieldError('end_time', `Event duration must be at least ${DURATION_POLICY.minHours} hour(s).`);",
            self.template,
        )
        # Time change handlers ay naka-wire sa Next-state choke point
        # REGRESSION: ang custom time picker ay nagse-dispatch ng 'change'
        # (hindi 'input'), kaya dapat naka-re-validate ang step-two fields
        # sa 'change' handler para malinis ang dating "is required*" error.
        self.assertIn(
            "startTimeInput.addEventListener('change', function () {",
            self.template,
        )
        self.assertIn(
            "endTimeInput.addEventListener('change', function () {",
            self.template,
        )
        self.assertIn(
            "if (bookingSubmitAttempted) validateBookingStepTwoFields();",
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
        # HTML attributes para sa native time picker. Start: 7:00 AM – 5:45 PM
        # (huling 15-min slot bago mag-6:00 PM close). End: hindi na binobound
        # sa 6:00 PM — pwedeng overnight basta't hindi lalampas sa max duration.
        self.assertIn('id="start_time" name="start_time" data-label="Start Time" min="07:00" max="17:45" step="900"', self.template)
        self.assertIn('id="end_time" name="end_time" data-label="End Time" min="07:00" max="23:59" step="900"', self.template)
        # JS: start floor/ceiling + end = start + min duration (overnight-aware
        # wraparound, walang 18:00 cap — max duration ang nagba-bound).
        self.assertIn("startTimeInput.max = '17:45';", self.template)
        self.assertIn("startTimeInput.step = 900;", self.template)
        self.assertIn(
            "minEndMinutes = startMinutes + (DURATION_POLICY.minHours * 60);",
            self.template,
        )
        self.assertIn(
            "if (minEndMinutes > 24 * 60) minEndMinutes -= 24 * 60;",
            self.template,
        )
        self.assertIn("endTimeInput.max = '23:59';", self.template)
        # Duration policy ay galing sa SiteSettings (data attrs + availability
        # payload) — hindi hardcoded sa template.
        self.assertIn("data-duration-min-hours=", self.template)
        self.assertIn("data-duration-included-hours=", self.template)
        self.assertIn("data-duration-overtime-rate=", self.template)
        self.assertIn("data-duration-max-hours=", self.template)

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
        self.assertIn("H.outsideCloser(pop, display", picker_c)
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
        shared_source = (BASE_DIR / "app" / "views" / "common.py").read_text(encoding="utf-8")
        self.assertIn("get_booking_form_availability()", views_source)
        self.assertIn('"leadDays"', shared_source)
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
        self.assertIn("client_booking.css' %}?v=20261021c", self.template)
        self.assertIn("booking_availability.js' %}?v=20261021d", self.template)
        self.assertIn("booking_picker_a.js' %}?v=20261014f", self.template)
        self.assertIn("booking_picker_c.js' %}?v=20261021b", self.template)

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
            self.assertIn("background-color: #1c1c1c !important", css, str(css_path))
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
        self.assertIn("admin_calendar.css' %}?v=20261020a", admin_tpl)
        # Client CSS: icon sa taas + text sa baba (vertical stack, hindi
        # magkatabi), may gap, at may tooltip arrow sa event tooltip.
        for css_path in (BOOKING_CSS, BOOKING_CSS_MIRROR):
            css = css_path.read_text(encoding="utf-8")
            self.assertIn("flex-direction: column;", css, str(css_path))
            self.assertIn("gap: 10px;", css, str(css_path))
            self.assertIn(".booking-event-tip::after", css, str(css_path))
            self.assertIn(".booking-event-tip.tip-below::after", css, str(css_path))
            # Mas malalim na gray (soft sa mata): unavailable bg (dark) +
            # today highlight (dark at light)
            self.assertIn(
                "background-color: #1c1c1c !important", css, str(css_path)
            )
            self.assertIn(
                "background-color: rgba(255, 255, 255, 0.06) !important",
                css,
                str(css_path),
            )
            self.assertIn(
                "background-color: rgba(17, 24, 39, 0.03) !important",
                css,
                str(css_path),
            )
            self.assertIn(
                "background-color: rgba(17, 24, 39, 0.05) !important",
                css,
                str(css_path),
            )
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

    def test_unavailable_custom_tooltip_and_light_faded_numbers(self):
        # Walang default browser title sa unavailable cells — ang custom
        # .booking-event-tip ang lumalabas sa hover (reason line lang kapag
        # may reason, via getBlockedDateLabel).
        self.assertNotIn(
            "setAttribute('title', getBlockedDateLabel", self.template
        )
        self.assertIn("arg.el.addEventListener('mouseenter'", self.template)
        self.assertIn(
            "arg.el.addEventListener('mouseleave', hideBookingEventTooltip)",
            self.template,
        )
        self.assertIn("showBookingEventTooltip(", self.template)
        # Light mode: faded ang numero ng lead-time (booking-day-disabled) at
        # past dates — opacity:1 (talo ang inline 0.45 ng JS); ang alpha ng
        # color ang nagf-fade, gaya ng dark mode. Today: solid pa rin.
        light_faded_number = (
            '[data-theme="light"] #booking-calendar .fc .fc-daygrid-day'
            ".booking-day-disabled .fc-daygrid-day-number"
        )
        for css_path in (BOOKING_CSS, BOOKING_CSS_MIRROR):
            css = css_path.read_text(encoding="utf-8")
            self.assertIn(light_faded_number, css, str(css_path))
            self.assertIn(
                "color: rgba(17, 24, 39, 0.4) !important", css, str(css_path)
            )
            # Today (19) na natamaan ng lead-time: faded ang number sa DARK at
            # LIGHT (gaya ng unavailable) pero naka-highlight pa rin ang bg —
            # may dedicated today+disabled number rules.
            self.assertRegex(
                css,
                r"\.fc-day-today\.booking-day-disabled \.fc-daygrid-day-number \{"
                r"[^}]*rgba\(255, 255, 255, 0\.45\)",
            )
            self.assertRegex(
                css,
                r"\.fc-day-today\.booking-day-disabled \.fc-daygrid-day-number \{"
                r"[^}]*rgba\(17, 24, 39, 0\.4\)",
            )


class EditBookingGuardrailTemplateTests(TestCase):
    """Ang edit-booking flow sa customer profile ay naka-mirror ng guardrails."""

    def setUp(self):
        self.template = PROFILE_TEMPLATE.read_text(encoding="utf-8")

    def test_time_inputs_enforce_operating_hours(self):
        self.assertIn('id="edit_start_time" name="start_time" min="07:00" max="17:45" step="900"', self.template)
        # WALANG max sa End — overnight/end-late ay allowed (mirrors booking page)
        self.assertIn('id="edit_end_time" name="end_time" min="07:00" step="900"', self.template)
        self.assertNotIn('id="edit_end_time" name="end_time" min="07:00" max="18:00"', self.template)
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
        self.assertIn("btnNextEditToSummary.disabled = violated || window.BookingAvailability.computeNextDisabled", self.template)
        self.assertIn(
            "if (editEndTimeEl) editEndTimeEl.addEventListener('change', refreshEditStepTwoNextState);",
            self.template,
        )
        self.assertIn('class="edit-date-hint"', self.template)
        self.assertIn("customer_profile.css' %}?v=20261013a", self.template)


class CreateBookingValidationTests(TestCase):
    """Backend rules — dapat pareho pa rin ang behaviour (source of truth).

    Sakop din ng bagong Step 3/4 rules: address min 10 chars + theme/palette
    required (max 3 colors) — pero iba ang tine-test ng bawat case dito.
    """

    def setUp(self):
        ServiceChargeConfig.objects.create(pk=1, shop_lat="14.414", shop_lng="120.982")
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
            # Step 4 required (theme + palette, max 3) — hindi ito ang
            # tine-test dito, kaya valid values lang palagi.
            "design_theme": "Princess",
            "color_palette": "Pink, Gold",
            # 📍 Smart-required pin: valid coords by default (map-alive booking);
            # ang gate tests mismo ang nag-o-override ng event_lat/lng + flag.
            "event_lat": "14.599500",
            "event_lng": "120.984200",
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

    def test_end_after_6pm_allowed(self):
        # OVERTNIGHT RULE: ang End ay hindi na binobound sa 6:00 PM —
        # basta't nasa loob ng min/max duration (ang START pa rin ang nasa
        # 7:00 AM–6:00 PM operating window).
        payload = self._post(start_time="16:00", end_time="19:00").json()
        self.assertTrue(payload["success"], payload)
        booking = Booking.objects.get(event_type="Birthday")
        self.assertEqual(booking.event_end_time, time(19, 0))
        self.assertEqual(booking.event_end_date, booking.event_date)
        self.assertEqual(booking.duration_minutes, 180)
        # 3 hours = included hours → walang overtime charge
        self.assertEqual(booking.overtime_hours, 0)
        self.assertEqual(booking.overtime_fee, 0)

    def test_overnight_end_next_day_with_overtime_snapshot(self):
        # Start 16:00 → end 02:00 = +1 day (10 hours). Overtime snapshot:
        # 600 min - 180 included = 420 min → 7 billable hours × ₱500.
        payload = self._post(start_time="16:00", end_time="02:00").json()
        self.assertTrue(payload["success"], payload)
        booking = Booking.objects.get(event_type="Birthday")
        self.assertEqual(booking.event_end_time, time(2, 0))
        self.assertEqual(
            booking.event_end_date, booking.event_date + timedelta(days=1)
        )
        self.assertEqual(booking.duration_minutes, 600)
        self.assertEqual(booking.overtime_hours, 7)
        self.assertEqual(booking.overtime_fee, 3500)

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


class BookingLeadTimeTests(TestCase):
    """Booking Rules > Lead Time — backend source of truth + template wiring.

    Sakop: rush reject sa create, boundary allow, edit reschedule reject,
    Services API unavailable + suggestions na walang rush, at fail-fast
    calendar guards (dateClick toast + disabled cells) sa template.
    """

    def setUp(self):
        ServiceChargeConfig.objects.create(pk=1, shop_lat="14.414", shop_lng="120.982")
        self.client = Client()
        self.user = User.objects.create_user(
            username="lead-cust",
            email="lead@test.com",
            password="pass12345",
            role="customer",
        )
        self.client.force_login(self.user)
        settings_obj = SiteSettings.load()
        settings_obj.booking_lead_time_days = 7
        settings_obj.save()
        self.url = reverse("create_booking")

    def _post(self, **overrides):
        from django.utils import timezone

        data = {
            "event_type": "Birthday",
            "event_date": (
                timezone.localdate() + timedelta(days=7)
            ).isoformat(),
            "start_time": "09:00",
            "end_time": "11:00",
            "event_location": "Test Venue",
            "package_type": "Package A",
            "total_price": "5000.00",
            "special_requests": "",
            # Step 4 required (theme + palette, max 3) — hindi ito ang
            # tine-test dito, kaya valid values lang palagi.
            "design_theme": "Princess",
            "color_palette": "Pink, Gold",
            # 📍 Smart-required pin: valid coords by default (map-alive booking);
            # ang gate tests mismo ang nag-o-override ng event_lat/lng + flag.
            "event_lat": "14.599500",
            "event_lng": "120.984200",
        }
        data.update(overrides)
        return self.client.post(
            self.url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )

    def test_rush_booking_rejected_with_earliest_date(self):
        from django.utils import timezone

        rush = timezone.localdate() + timedelta(days=2)
        min_date = timezone.localdate() + timedelta(days=7)
        payload = self._post(event_date=rush.isoformat()).json()
        self.assertFalse(payload["success"])
        self.assertIn("at least 7 day(s) in advance", payload["message"])
        self.assertIn(min_date.strftime("%B %d, %Y"), payload["message"])
        self.assertFalse(Booking.objects.filter(event_date=rush).exists())

    def test_boundary_date_allowed(self):
        from django.utils import timezone

        boundary = timezone.localdate() + timedelta(days=7)
        payload = self._post(event_date=boundary.isoformat()).json()
        self.assertTrue(payload["success"], payload)
        self.assertTrue(Booking.objects.filter(event_date=boundary).exists())

    def test_day_before_boundary_rejected(self):
        from django.utils import timezone

        before = timezone.localdate() + timedelta(days=6)
        payload = self._post(event_date=before.isoformat()).json()
        self.assertFalse(payload["success"])
        self.assertFalse(Booking.objects.filter(event_date=before).exists())

    def _make_booking(self, days=30):
        from django.utils import timezone

        return Booking.objects.create(
            user=self.user,
            event_date=timezone.localdate() + timedelta(days=days),
            event_time=time(9, 0),
            event_type="Birthday",
            event_location="Venue",
            package_type="Package A",
            total_price=5000,
            status="pending",
        )

    def _edit_post(self, booking, event_date):
        return self.client.post(
            reverse("edit_booking", args=[booking.id]),
            {
                "event_type": "Birthday",
                "event_date": event_date.isoformat(),
                "start_time": "09:00",
                "end_time": "11:00",
                "event_location": "Test Venue, Quezon City",
                "total_price": "5000.00",
                "special_requests": "",
                # Edit-modal strict (theme + palette kapag nasa POST).
                "design_theme": "Princess",
                "color_palette": "Pink, Gold",
            },
        )

    def test_edit_reschedule_to_rush_rejected(self):
        from django.utils import timezone

        booking = self._make_booking(days=30)
        rush = timezone.localdate() + timedelta(days=2)
        self._edit_post(booking, rush)
        booking.refresh_from_db()
        self.assertEqual(
            booking.event_date, timezone.localdate() + timedelta(days=30)
        )

    def test_edit_reschedule_to_allowed_date_succeeds(self):
        from django.utils import timezone

        booking = self._make_booking(days=30)
        target = timezone.localdate() + timedelta(days=10)
        self._edit_post(booking, target)
        booking.refresh_from_db()
        self.assertEqual(booking.event_date, target)

    def test_services_api_reports_rush_unavailable(self):
        from django.utils import timezone

        rush = timezone.localdate() + timedelta(days=2)
        min_date = timezone.localdate() + timedelta(days=7)
        response = self.client.get(
            reverse("check_date_availability") + "?date=" + rush.isoformat()
        )
        data = response.json()
        self.assertTrue(data["success"])
        self.assertFalse(data["available"])
        self.assertIn("at least 7 day(s) in advance", data["message"])
        self.assertEqual(data["min_bookable_date"], min_date.isoformat())
        for suggestion in data["suggestions"]:
            self.assertGreaterEqual(suggestion, min_date.isoformat())

    def test_booking_page_has_fail_fast_lead_guards(self):
        template = BOOKING_TEMPLATE.read_text(encoding="utf-8")
        # Calendar click: toast + no modal (fail-fast, hindi na papasok sa Step 1)
        self.assertIn("if (moduleIsLeadBlockedDate(clickedDate)) {", template)
        self.assertIn("showLeadBlockedToast();", template)
        # Calendar visual: ADMIN-blocked lang ang gray + "Unavailable" + ban
        # icon. Lead-time dates: faded/malabo na gaya ng past dates (gamit ang
        # booking-day-disabled) — walang "Unavailable" label, may toast pag click.
        self.assertIn("if (isBlockedDate(cellDate)) {", template)
        self.assertNotIn(
            "if (isBlockedDate(cellDate) || moduleIsLeadBlockedDate(cellDate)) {",
            template,
        )
        # Lead-time (kasama ang TODAY kapag natamaan) → faded/malabo na
        # booking-day-disabled — walang today exemption sa class hooks.
        self.assertIn("if (moduleIsLeadBlockedDate(cellDate)) {", template)
        self.assertNotIn("cellDate !== todayLocal", template)
        self.assertIn("return ['booking-day-disabled'];", template)
        self.assertIn("getLeadBlockedLabel(dateInput.value)", template)
        self.assertIn("booking-day-blocked-label", template)
        self.assertNotIn("booking-day-lead-blocked", template)

    def test_edit_modals_have_lead_guards(self):
        template = PROFILE_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("data-lead-days=", template)
        self.assertIn("data-min-bookable-date=", template)
        self.assertIn("isEditLeadBlocked", template)
        self.assertIn("isEditLeadBlocked(editEventDateEl.value)", template)
        self.assertFalse((BASE_DIR / "app/templates/client/booking/booking_form.html").exists())



class BlockedDateCalendarDisplayTests(TestCase):
    """Walang red "Unavailable" event pill sa client booking calendar.

    Ang admin-blocked dates ay pumapasok na lang sa `blocked_dates` payload
    (day-cell styling + tooltip + dateClick guard); ang `calendar_events` ay
    bookings lang — kapareho ng lead-time-blocked na walang event, kaya
    magkapareho ang itsura ng dalawang uri ng pagka-block sa calendar.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="block-cust",
            email="block@test.com",
            password="pass12345",
            role="customer",
        )
        self.client.force_login(self.user)
        self.url = reverse("booking_page")

    def _block_a_date(self):
        from django.utils import timezone

        blocked_date = timezone.localdate() + timedelta(days=14)
        BlockedDate.objects.create(
            date=blocked_date, reason="Holiday", created_by=self.user
        )
        return blocked_date

    def test_calendar_events_exclude_blocked_flag_pill(self):
        blocked_date = self._block_a_date()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        events = response.context["calendar_events"]
        # Walang pulang "Unavailable" flag event (#7f1d1d) — day-cell styling
        # na lang ang marker ng blocked dates.
        self.assertFalse(
            [e for e in events if e["title"] == "Unavailable"], events
        )
        self.assertFalse(
            [e for e in events if e.get("color") == "#7f1d1d"], events
        )
        # Hindi nawawala ang petsa sa blocked payload (styling/tooltip/guards).
        self.assertIn(
            {"date": blocked_date.isoformat(), "reason": "Holiday"},
            response.context["blocked_dates"],
        )


class CalendarLoadResilienceTests(TestCase):
    """Calendar "Loading…" regression guards.

    Dati: kapag hindi nag-load ang FullCalendar CDN (o may JS syntax error sa
    events array), nakatagan ang calendar area sa "Loading…" — walang guard,
    walang fallback. Ngayon:
    - escaped ang events array fields (hindi mababasag ng quote sa data),
    - may CDN/init try-catch + friendly fallback (guard JS),
    - may independent watchdog script block kahit mag-parse-error ang main
      inline script.
    """

    def setUp(self):
        self.template = BOOKING_TEMPLATE.read_text(encoding="utf-8")
        self.admin_template = (
            BASE_DIR / "app" / "templates" / "admin" / "admin_calendar.html"
        ).read_text(encoding="utf-8")
        self.guard_js = (
            BASE_DIR / "static" / "js" / "booking_calendar_guard.js"
        ).read_text(encoding="utf-8")

    def test_calendar_events_are_escaped(self):
        # Kahit anong apostrophe/quote sa title/start/end ay hindi na
        # mababasag ang inline JS (buo pa rin ang calendar + booking form).
        self.assertIn("title: '{{ event.title|escapejs }}'", self.template)
        self.assertIn("start: '{{ event.start|escapejs }}'", self.template)
        self.assertIn("end: '{{ event.end|escapejs }}'", self.template)

    def test_fullcalendar_init_is_guarded(self):
        # CDN failure o init/render error → friendly fallback, hindi buong
        # DOMContentLoaded handler ang namamatay (client man o admin).
        for tpl in (self.template, self.admin_template):
            self.assertIn("typeof FullCalendar === 'undefined'", tpl)
            self.assertIn("showBookingCalendarLoadError", tpl)

    def test_calendar_guard_js_loaded_before_fullcalendar_usage(self):
        # Naka-load bago magamit ang FullCalendar para laging handa ang
        # showBookingCalendarLoadError kapag bumigay ang init.
        self.assertIn("js/booking_calendar_guard.js", self.template)
        self.assertLess(
            self.template.index("js/booking_calendar_guard.js"),
            self.template.index("new FullCalendar.Calendar"),
        )
        self.assertIn("js/booking_calendar_guard.js", self.admin_template)

    def test_watchdog_replaces_stuck_loading_title(self):
        # Independent watchdog: kahit mag-parse-error ang main inline script,
        # mapapalitan ang "Loading…" ng error card + reload button.
        self.assertIn("showBookingCalendarLoadError", self.guard_js)
        self.assertIn("indexOf('Loading')", self.guard_js)
        self.assertIn("calendar-load-error", self.guard_js)
        self.assertIn("calendar-reload-btn", self.guard_js)

    def test_load_error_styles_present_in_css(self):
        for css_path in (BOOKING_CSS, BOOKING_CSS_MIRROR):
            css = css_path.read_text(encoding="utf-8")
            self.assertIn(".calendar-load-error {", css, str(css_path))
            self.assertIn(".calendar-reload-btn {", css, str(css_path))
        admin_css = (
            BASE_DIR / "static" / "css" / "admin_calendar.css"
        ).read_text(encoding="utf-8")
        self.assertIn(".calendar-load-error {", admin_css)
        self.assertIn(".calendar-reload-btn {", admin_css)

    def test_update_time_constraints_function_opener_present(self):
        # REGRESSION (2026-10-20): may edit na nagtanggal ng
        # `function updateTimeConstraints() {` opener habang nag-iinsert ng
        # overtime helpers. Nagiging stray `}` ang dating pang-closing nito —
        # nagsasara ng DOMContentLoaded callback habang nasa gitna pa ng
        # addEventListener( argument list → SyntaxError sa buong inline
        # script ("missing ) after argument list") → stuck sa "Loading…".
        self.assertEqual(
            self.template.count("function updateTimeConstraints() {"), 1
        )
        # Bukod sa opener, may tumatawag pa rin sa function (dateClick handler
        # at page init) — kung mawawala iyon, ReferenceError naman ang bunga.
        self.assertIn("updateTimeConstraints();", self.template)


class SmartRequiredPinGateTests(TestCase):
    """📍 Smart-required pin — backend gate sa create_booking (source of truth).

    Kapag buhay ang map (default map_available=1) ay KAILANGAN ang event_lat/lng
    kahit DevTools pa ang gamit. Kapag patay ang map (map_available=0, CDN fail),
    tuloy pa rin ang booking (base fee + admin review). Ang edit gate naman ay
    exempt sa legacy forms na walang event_lat/lng keys.
    """

    def setUp(self):
        ServiceChargeConfig.objects.create(pk=1, shop_lat="14.414", shop_lng="120.982")
        self.client = Client()
        self.user = User.objects.create_user(
            username="pin-cust",
            email="pin@test.com",
            password="pass12345",
            role="customer",
        )
        self.client.force_login(self.user)
        self.url = reverse("create_booking")

    def _post(self, **overrides):
        data = {
            "event_type": "Birthday",
            "event_date": (date.today() + timedelta(days=30)).isoformat(),
            "start_time": "09:00",
            "end_time": "11:00",
            "event_location": "Test Venue, Quezon City",
            "package_type": "Package A",
            "total_price": "5000.00",
            "special_requests": "",
            "design_theme": "Princess",
            "color_palette": "Pink, Gold",
        }
        data.update(overrides)
        return self.client.post(
            self.url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )

    def test_missing_pin_rejected_when_map_available(self):
        # Walang event_lat/lng keys at walang map_available → default "1" = gate
        payload = self._post(event_lat="", event_lng="").json()
        self.assertFalse(payload["success"])
        self.assertIn("drop a pin", payload["message"])
        self.assertFalse(Booking.objects.filter(user=self.user).exists())

    def test_one_sided_pin_stripped_then_rejected(self):
        # Half pin → parehong na-strip to None → pasok sa gate (anti-tamper)
        payload = self._post(event_lat="14.599500", event_lng="").json()
        self.assertFalse(payload["success"])
        self.assertIn("drop a pin", payload["message"])
        self.assertFalse(Booking.objects.filter(user=self.user).exists())

    def test_map_unavailable_flag_bypasses_gate(self):
        # CDN-fail path: map_available=0 + walang pin → tuloy ang booking
        payload = self._post(
            event_lat="", event_lng="", map_available="0"
        ).json()
        self.assertTrue(payload["success"], payload)
        booking = Booking.objects.get(user=self.user)
        self.assertIsNone(booking.event_lat)
        self.assertIsNone(booking.event_lng)

    def test_valid_pin_accepted_and_quote_snapshotted(self):
        payload = self._post(
            event_lat="14.599500", event_lng="120.984200"
        ).json()
        self.assertTrue(payload["success"], payload)
        booking = Booking.objects.get(user=self.user)
        self.assertEqual(booking.event_lat, Decimal("14.599500"))
        self.assertEqual(booking.event_lng, Decimal("120.984200"))
        # Logistics quote snapshot — hindi na magbabago kung i-edit ang config
        self.assertIsNotNone(booking.logistics_fee)


class SmartRequiredPinTemplateTests(TestCase):
    """📍 Frontend wiring ng smart-required pin: create/edit gates,
    map_available flag, onPinChange wiring, at pin-status chip."""

    def setUp(self):
        self.booking = BOOKING_TEMPLATE.read_text(encoding="utf-8")
        self.profile = PROFILE_TEMPLATE.read_text(encoding="utf-8")
        self.map_module = (
            BASE_DIR / "static" / "js" / "booking_location_map.js"
        ).read_text(encoding="utf-8")

    def test_create_flow_gate_and_flag(self):
        self.assertIn('id="map_available_input"', self.booking)
        # Live map + walang pin → naka-block ang Next (step-two validation)
        self.assertIn(
            "setBookingFieldError('event_location', 'Please drop a pin or pick from search so we can compute your exact logistics fee.');",
            self.booking,
        )
        # Flag flips sa validation: 1 = buhay ang map, 0 = CDN fail (bypass)
        self.assertIn("pinFlag.value = mapAlive ? '1' : '0';", self.booking)

    def test_edit_flow_gate_and_flag(self):
        self.assertIn('id="edit_map_available_input"', self.profile)
        self.assertIn(
            "setEditBookingFieldError('event_location', 'Please drop a pin or pick from search so we can compute your exact logistics fee.');",
            self.profile,
        )
        self.assertIn(
            "editPinFlag.value = editMapAlive ? '1' : '0';", self.profile
        )

    def test_on_pin_change_wired_in_both_flows(self):
        # Create: quote refresh + error clear + chip refresh
        self.assertIn("onPinChange: function ()", self.booking)
        self.assertGreaterEqual(
            self.booking.count("refreshBookingPinStatusText();"), 2
        )
        # Edit: error clear + chip refresh (summary ay nagre-render sa step 5)
        self.assertGreaterEqual(
            self.profile.count("onPinChange: function ()"), 1
        )
        self.assertGreaterEqual(
            self.profile.count("refreshEditPinStatusText();"), 2
        )
        # Module: nagno-notify kapag nag-place ng pin at kapag nag-drag
        self.assertIn("function notifyPinChange()", self.map_module)
        self.assertGreaterEqual(self.map_module.count("notifyPinChange();"), 2)

    def test_pin_status_chip_in_both_flows(self):
        self.assertIn('id="booking_pin_status"', self.booking)
        self.assertIn('id="edit_booking_pin_status"', self.profile)
        for tpl in (self.booking, self.profile):
            self.assertTrue("Pin saved. Check that it marks your exact venue." in tpl or "Pin saved — exact distance-based fee applied." in tpl)
            self.assertIn(
                "No pin yet — drop a pin or pick from search. Required to continue.",
                tpl,
            )
            self.assertIn("Map unavailable — pin optional", tpl)


class OvertimeLabelTemplateTests(TestCase):
    """⏱️ Overtime UI labels: start-only hint, fee-breakdown toast, at
    end-dropdown labels/footer — lahat hatid ng SiteSettings policy
    (includedHours + overtimeRate), hindi hardcoded."""

    def setUp(self):
        self.booking = BOOKING_TEMPLATE.read_text(encoding="utf-8")
        self.picker = (
            BASE_DIR / "static" / "js" / "booking_picker_c.js"
        ).read_text(encoding="utf-8")

    def test_start_only_hint_shows_included_window_and_rate(self):
        # Start-only hint: kapag may Start na, ilalabas kung hanggang kailan
        # kasama + kung magkano kada oras pag lampas (walang End pa na hinihintay)
        self.assertIn("→ included until", self.booking)
        self.assertIn("per started hour.`", self.booking)
        self.assertIn("DURATION_POLICY.includedHours * 60", self.booking)
        self.assertIn("DURATION_POLICY.overtimeRate", self.booking)
        # Overtime row sa order summary (price breakdown)
        self.assertIn('id="overtime_display"', self.booking)

    def test_overtime_toast_includes_fee_breakdown(self):
        # Taglish toast na may duration + billable hours + fee
        self.assertIn("'Heads up: may overtime ito.'", self.booking)
        self.assertIn("overtimeFee.toLocaleString('en-PH')", self.booking)

    def test_end_dropdown_labels_and_footer_use_policy(self):
        # Per-option "+₱X" suffix at footer — galing sa otPolicy, hindi hardcoded
        self.assertIn("otPolicy.includedMinutes", self.picker)
        self.assertIn("otPolicy.overtimeRate", self.picker)
        self.assertIn("otHours * otPolicy.overtimeRate", self.picker)
        self.assertIn("'Beyond ' + _untilLbl + ' = overtime (+₱'", self.picker)
        # Naka-load sa booking page nang may cache-bust
        self.assertIn("booking_picker_c.js' %}?v=", self.booking)


class BookingMapModuleScopeTests(TestCase):
    """📍 REGRESSION: ang `hasPin()` helper ay DITO nasa module scope.

    BUG (2026-10-21): nasa loob ng `init()` ang paggawa ng `hasPin`, pero
    na-expose ito sa public API (`window.BookingLocationMap.hasPin`). Sa
    'use strict' mode, nagta-trigger ito ng `ReferenceError: hasPin is not
    defined` PAG-EXECUTE ng script — kaya HINDI NA NAG-DEFINE ang buong
    `window.BookingLocationMap`, at patay ang mapa: gray box, walang tiles,
    at patay ang "Search" / "Use my location" (naka-attach sa init()).
    """

    def setUp(self):
        self.map_module = (
            BASE_DIR / "static" / "js" / "booking_location_map.js"
        ).read_text(encoding="utf-8")
        self.mirror = (
            BASE_DIR / "staticfiles" / "js" / "booking_location_map.js"
        ).read_text(encoding="utf-8")

    def test_has_pin_defined_at_module_scope(self):
        for source, label in (
            (self.map_module, "static/js"),
            (self.mirror, "staticfiles/js"),
        ):
            self.assertIn("function hasPin(", source, label)
            # Ang definition ay dapat NASA IBABA ng `function init(` —
            # ibig sabihin module scope, hindi nested sa init().
            has_pin_at = source.index("function hasPin(")
            init_at = source.index("function init(")
            self.assertLess(
                has_pin_at, init_at, f"{label}: hasPin() dapat module-scope"
            )

    def test_has_pin_not_nested_inside_init(self):
        # Walang nested na paggawa ng hasPin sa loob ng init().
        self.assertNotIn("        function hasPin(", self.map_module)
        self.assertNotIn("        function hasPin(", self.mirror)

    def test_public_api_exposes_has_pin(self):
        for source, label in (
            (self.map_module, "static/js"),
            (self.mirror, "staticfiles/js"),
        ):
            self.assertIn("hasPin: hasPin", source, label)

    def test_static_and_staticfiles_mirrors_in_sync(self):
        # Ang staticfiles/ mirror ay ginagamit ng WhiteNoise sa prod —
        # dapat byte-identical sa static/ (i.e. may parehong fix).
        self.assertEqual(
            self.map_module,
            self.mirror,
            "staticfiles/js/booking_location_map.js ay stale — sync ito.",
        )


class OvertimeStartOnlyHintTests(TestCase):
    """⏱️ REGRESSION: ang "included window" hint ay dapat mag-update kahit
    Start-only pa (walang End) — dati, hindi napupunta ang hint dahil ang
    `computeOvertimeInfo()` ay nagre-return ng null kapag walang End."""

    def setUp(self):
        self.booking = BOOKING_TEMPLATE.read_text(encoding="utf-8")

    def test_compute_overtime_info_supports_start_only(self):
        # Ang early-return ay dapat base sa START, hindi sa duration.
        self.assertIn(
            "const startMinutes = getMinutesFromTimeValue(startTimeInput.value);\n"
            "        if (startMinutes === null) return null;",
            self.booking,
        )
        # mayEnd flag para alam ng notice kung may End na.
        self.assertIn("hasEnd: durationMinutes !== null,", self.booking)

    def test_hint_updates_on_next_state_refresh(self):
        # REGRESSION: ang module branch ng refreshStepTwoNextState() ay
        # early-return, kaya dating hindi napapasok ang updateOvertimeNotice()
        # (=> "walang pinagbago" ang End time / overtime notice).
        self.assertIn(
            "function refreshStepTwoNextState() {\n"
            "        if (!btnNextToSummary) return;\n"
            "        btnNextToSummary.dataset.availabilityGuard = 'main';",
            self.booking,
        )
        refresh_block = self.booking[
            self.booking.index("function refreshStepTwoNextState() {"):self.booking.index(
                "function refreshStepTwoNextState() {"
            )
            + 1400
        ]
        # Ang updateOvertimeNotice ay dapat tawagin BEFORE ang module
        # branch (na early-return).
        self.assertIn("updateOvertimeNotice(true);", refresh_block)
        self.assertLess(
            refresh_block.index("updateOvertimeNotice(true);"),
            refresh_block.index("if (window.BookingAvailability"),
            "Ang overtime notice ay dapat i-update bago ang module early-return.",
        )

    def test_no_overtime_notice_without_end_time(self):
        # Walang End → walang overtime charge/toast, pero may hint pa.
        self.assertIn(
            "if (!info.hasEnd) {\n"
            "            if (notice) notice.hidden = true;",
            self.booking,
        )

    def test_start_only_hint_text_present(self):
        self.assertIn("→ included until", self.booking)
        self.assertIn("per started hour.`", self.booking)


class EditFlowTimeChangeRevalidationTests(TestCase):
    """⏱️ REGRESSION: ang edit-booking flow (customer profile) ay may parehong
    stale-error bug — ang custom time picker ay nagse-dispatch ng 'change',
    pero 'input' lang ang nakikinig, kaya nananatiling "is required*". """

    def setUp(self):
        self.profile = PROFILE_TEMPLATE.read_text(encoding="utf-8")

    def test_edit_time_fields_revalidate_on_change(self):
        self.assertIn(
            "[editStartTimeEl, editEndTimeEl, editEventDateEl].forEach((field) => {",
            self.profile,
        )
        self.assertIn(
            "field.addEventListener('change', () => {\n"
            "                if (editBookingSubmitAttempted) validateEditBookingForm();",
            self.profile,
        )
