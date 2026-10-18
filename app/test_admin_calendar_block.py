"""Regression tests para sa Option A: conflict-aware blocked dates (layer, don't mask).

Sakop:
- Block ng date na walang laman  -> direktang success.
- Block ng date na may bookings (pending o confirmed) nang walang
  `confirm_conflicts` -> WALANG BlockedDate na nalilikha + warning message.
- Block ng date na may bookings KASAMA ang `confirm_conflicts=1` ("Block Anyway")
  -> may BlockedDate, at BUHAY PA RIN ang Booking (data hindi nawawala).
- Unblock -> nawawala ang BlockedDate pero BUHAY PA RIN ang Booking.
"""
from datetime import date, time, timedelta
from pathlib import Path

from django.contrib.messages import get_messages
from django.test import Client, TestCase
from django.urls import reverse

from .models import BlockedDate, Booking, User


class BlockedDateConflictViewTests(TestCase):
    """Backend: confirmation flow kapag may laman ang date."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username="cal-admin",
            email="cal-admin@test.com",
            password="pass12345",
            role="admin",
        )
        self.customer = User.objects.create_user(
            username="cal-cust",
            email="cal-cust@test.com",
            password="pass12345",
            role="customer",
        )
        self.client.force_login(self.admin)
        self.create_url = reverse("admin_blocked_date_create")

    def _future_date(self, days=7):
        return date.today() + timedelta(days=days)

    def _make_booking(self, event_date, status="pending"):
        return Booking.objects.create(
            user=self.customer,
            event_date=event_date,
            event_time=time(10, 0),
            event_type="Birthday",
            event_location="Venue A",
            package_type="Package A",
            total_price=5000,
            status=status,
            special_requests="Notes\n(End Time: 12:00)",
        )

    def test_block_date_with_active_booking_requires_confirmation(self):
        target = self._future_date()
        booking = self._make_booking(target, status="confirmed")
        response = self.client.post(
            self.create_url, {"date": target.isoformat(), "reason": "Maintenance"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(BlockedDate.objects.filter(date=target).exists())
        self.assertTrue(Booking.objects.filter(id=booking.id).exists())
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("already has" in t for t in texts), texts)

    def test_block_anyway_with_confirmation_keeps_bookings_visible(self):
        target = self._future_date()
        booking = self._make_booking(target, status="confirmed")
        response = self.client.post(
            self.create_url,
            {
                "date": target.isoformat(),
                "reason": "Holiday",
                "confirm_conflicts": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(BlockedDate.objects.filter(date=target).exists())
        # OPTION A core guarantee: hindi nawawala ang booking data.
        self.assertTrue(Booking.objects.filter(id=booking.id).exists())
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("remain on" in t for t in texts), texts)


    def test_block_date_with_pending_booking_requires_confirmation(self):
        target = self._future_date()
        booking = self._make_booking(target, status="pending")
        response = self.client.post(
            self.create_url, {"date": target.isoformat(), "reason": "Holiday"}
        )
        self.assertEqual(response.status_code, 302)
        # WALANG BlockedDate na nalikha nang walang confirmation...
        self.assertFalse(BlockedDate.objects.filter(date=target).exists())
        # ...at BUHAY pa rin ang booking.
        self.assertTrue(Booking.objects.filter(id=booking.id).exists())
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(
            any("already has" in t and "Block Anyway" in t for t in texts),
            texts,
        )

    def test_block_empty_date_succeeds_directly(self):
        target = self._future_date()
        response = self.client.post(
            self.create_url, {"date": target.isoformat(), "reason": "Holiday"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(BlockedDate.objects.filter(date=target).exists())

    def test_unblock_preserves_bookings(self):
        target = self._future_date()
        booking = self._make_booking(target, status="confirmed")
        blocked = BlockedDate.objects.create(
            date=target, reason="Holiday", created_by=self.admin
        )
        unblock_url = reverse("admin_blocked_date_delete", args=[blocked.id])
        response = self.client.post(unblock_url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(BlockedDate.objects.filter(date=target).exists())
        self.assertTrue(Booking.objects.filter(id=booking.id).exists())

    def test_cancelled_bookings_do_not_trigger_confirmation(self):
        target = self._future_date()
        self._make_booking(target, status="cancelled")
        response = self.client.post(
            self.create_url, {"date": target.isoformat(), "reason": "Holiday"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(BlockedDate.objects.filter(date=target).exists())


class BlockedDateConflictTemplateTests(TestCase):
    """Template/CSS hooks para sa Option A UX."""

    def setUp(self):
        base = Path(__file__).resolve().parent.parent
        self.template = (
            base / "app" / "templates" / "admin" / "admin_calendar.html"
        ).read_text(encoding="utf-8")
        css = (
            base / "static" / "css" / "admin_calendar.css"
        ).read_text(encoding="utf-8")
        self.stripped_css = "".join(css.split())

    def test_conflict_modal_markup_present(self):
        # Conflict confirm ngayon ay SweetAlert2 (openBlockModal) — wala nang
        # #blockConflictModal custom modal (inagalaw ng admin-calendar polish).
        self.assertIn("function openBlockModal(", self.template)
        self.assertIn("confirmButtonText: 'Block Anyway'", self.template)
        self.assertIn('id="blockDateConfirmConflicts"', self.template)
        self.assertIn('name="confirm_conflicts"', self.template)
        self.assertIn('id="blockedConflictHint"', self.template)
        self.assertIn("admin-booking-conflict-counts", self.template)

    def test_blocked_flag_event_class_hook_present(self):
        self.assertIn("blocked-flag-event", self.template)
        self.assertIn("eventClassNames", self.template)
        self.assertIn("isBlockedFlagEvent", self.template)

    def test_booking_pills_not_hidden_on_blocked_cells(self):
        # Tanging ang "Unavailable" blocked-flag pill ang nakatago...
        self.assertIn(".fc-event.blocked-flag-event", self.stripped_css)
        # ...hindi ang blanket rule na nagtatago ng LAHAT ng event pills.
        self.assertNotIn(
            ".booking-day-blocked.fc-daygrid-day-frame"
            ".fc-event{display:none!important;}",
            self.stripped_css,
        )
        # Conflict indicator para sa booking pills sa blocked dates.
        self.assertIn(".fc-event:not(.blocked-flag-event)", self.stripped_css)

    def test_conflict_modal_css_present(self):
        # Ang dating .cal-block-confirm custom-modal styles ay SweetAlert2 na;
        # narito pa rin ang live conflict styles (hint + day-popover warning).
        self.assertIn(".blocked-conflict-hint", self.stripped_css)
        self.assertIn(".blocked-conflict-hint[hidden]", self.stripped_css)
        self.assertIn(".cal-pop-blocked-warning", self.stripped_css)
