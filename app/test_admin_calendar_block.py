"""Regression tests para sa Option A: conflict-aware blocked dates (layer, don't mask).

Sakop:
- Block ng date na walang laman  -> direktang success.
- Block ng date na may bookings (pending o confirmed) nang walang
  `confirm_conflicts` -> WALANG BlockedDate na nalilikha + warning message.
- Block ng date na may bookings KASAMA ang `confirm_conflicts=1` ("Block Anyway")
  -> may BlockedDate, at BUHAY PA RIN ang Booking (data hindi nawawala).
- Unblock -> nawawala ang BlockedDate pero BUHAY PA RIN ang Booking.
"""
from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

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
        self.script = (base / 'static' / 'js' / 'admin_calendar.js').read_text(encoding='utf-8')
        css = (
            base / "static" / "css" / "admin_calendar.css"
        ).read_text(encoding="utf-8")
        self.stripped_css = "".join(css.split())

    def test_conflict_modal_markup_present(self):
        # Confirmation remains explicit before blocking dates with bookings.
        self.assertIn("function openBlockModal(", self.script)
        self.assertIn("'Block Anyway'", self.script)
        self.assertIn('id="calConfirm"', self.template)
        self.assertIn('id="blockDateConfirmConflicts"', self.template)
        self.assertIn('name="confirm_conflicts"', self.template)
        self.assertIn('id="blockedConflictHint"', self.template)
        self.assertIn("admin-booking-conflict-counts", self.template)

    def test_blocked_flag_event_class_hook_present(self):
        self.assertIn("blocked-flag-event", self.script)
        self.assertIn("eventClassNames", self.script)
        self.assertIn("isBlockedFlagEvent", self.script)

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
        # Keep the live conflict hint and day-popover warning.
        self.assertIn(".blocked-conflict-hint", self.stripped_css)
        self.assertIn(".blocked-conflict-hint[hidden]", self.stripped_css)
        self.assertIn(".cal-pop-blocked-warning", self.stripped_css)


class AdminCalendarAsyncTests(TestCase):
    setUp = BlockedDateConflictViewTests.setUp
    _make_booking = BlockedDateConflictViewTests._make_booking
    _future_date = BlockedDateConflictViewTests._future_date
    headers = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}

    def test_active_dates_and_read_only_history_keep_calendar_records(self):
        today = timezone.localdate()
        past = BlockedDate.objects.create(date=today-timedelta(days=1), reason='Previous holiday', created_by=self.admin)
        current = BlockedDate.objects.create(date=today, reason='Today', created_by=self.admin)
        future = BlockedDate.objects.create(date=today+timedelta(days=3), reason='Upcoming holiday', created_by=self.admin)
        html = self.client.get(reverse('admin_calendar'))
        data = self.client.get(reverse('admin_calendar'), **self.headers).json()
        self.assertEqual([item.pk for item in html.context['blocked_dates']], [current.pk, future.pk])
        self.assertEqual([item.pk for item in html.context['past_blocked_dates']], [past.pk])
        self.assertEqual([item['id'] for item in data['blocked_dates']], [current.pk, future.pk])
        self.assertEqual([item['id'] for item in data['past_blocked_dates']], [past.pk])
        self.assertNotIn('delete_url', data['past_blocked_dates'][0])
        self.assertEqual({item['start'] for item in data['events']}, {item.date.isoformat() for item in (past,current,future)})
        self.assertEqual(BlockedDate.objects.count(), 3)

    def test_blocks_archive_only_after_philippine_midnight_even_with_other_active_timezone(self):
        target = date(2026, 10, 30)
        blocked = BlockedDate.objects.create(date=target, reason='Holiday', created_by=self.admin)
        before_midnight = datetime(2026, 10, 30, 15, 59, 59, tzinfo=datetime_timezone.utc)
        with timezone.override('UTC'), patch('app.views.bookings.timezone.now', return_value=before_midnight):
            before = self.client.get(reverse('admin_calendar'), **self.headers).json()
        self.assertEqual(before['today_iso'], '2026-10-30')
        self.assertEqual(before['blocked_dates'][0]['id'], blocked.pk)
        self.assertEqual(before['past_blocked_dates'], [])
        self.assertEqual(before['next_day_at'], '2026-10-31T00:00:00+08:00')
        with timezone.override('UTC'), patch('app.views.bookings.timezone.now', return_value=before_midnight+timedelta(seconds=1)):
            after = self.client.get(reverse('admin_calendar'), **self.headers).json()
            html = self.client.get(reverse('admin_calendar'))
        self.assertEqual(after['today_iso'], '2026-10-31')
        self.assertEqual(after['blocked_dates'], [])
        self.assertEqual(after['past_blocked_dates'][0]['id'], blocked.pk)
        self.assertEqual(html.context['blocked_dates'], [])
        self.assertEqual(html.context['past_blocked_dates'][0].pk, blocked.pk)
        self.assertIn('2026-10-30', [item['start'] for item in after['events']])
        self.assertTrue(BlockedDate.objects.filter(pk=blocked.pk).exists())

    def test_history_is_newest_first_and_reason_is_escaped(self):
        today = timezone.localdate()
        older = BlockedDate.objects.create(date=today-timedelta(days=4), reason='Older')
        recent = BlockedDate.objects.create(date=today-timedelta(days=1), reason='<img src=x onerror=alert(1)>')
        html = self.client.get(reverse('admin_calendar'))
        self.assertEqual([item.pk for item in html.context['past_blocked_dates']], [recent.pk,older.pk])
        self.assertContains(html, '&lt;img src=x onerror=alert(1)&gt;')
        self.assertNotContains(html, '<img src=x onerror=alert(1)>')

    def test_html_and_json_expose_identical_calendar_dates_and_statuses(self):
        target = self._future_date()
        for status in ('pending', 'pending_payment', 'confirmed', 'completed', 'expired', 'cancelled'):
            self._make_booking(target, status)
        BlockedDate.objects.create(date=target, reason='Holiday', created_by=self.admin)
        html = self.client.get(reverse('admin_calendar'))
        data = self.client.get(reverse('admin_calendar'), **self.headers)
        self.assertEqual(data.status_code, 200)
        self.assertEqual(data.json()['events'], html.context['calendar_events'])
        self.assertEqual(data.json()['conflict_counts'], html.context['booking_conflict_counts'])
        self.assertEqual(data.json()['blocked_dates'][0]['date'], target.isoformat())
        self.assertEqual(data['Cache-Control'], 'no-store')

    def test_async_block_conflict_confirmation_and_unblock_preserve_booking(self):
        target = self._future_date()
        booking = self._make_booking(target, 'confirmed')
        values = {'date': target.isoformat(), 'reason':'Maintenance'}
        first = self.client.post(self.create_url, values, **self.headers)
        self.assertEqual(first.status_code, 409)
        self.assertTrue(first.json()['requires_confirmation'])
        self.assertFalse(BlockedDate.objects.exists())
        result = self.client.post(self.create_url, {**values, 'confirm_conflicts':'1'}, **self.headers)
        self.assertTrue(result.json()['ok'])
        blocked = BlockedDate.objects.get(date=target)
        duplicate = self.client.post(self.create_url, {**values, 'confirm_conflicts':'1'}, **self.headers)
        self.assertEqual(duplicate.json()['kind'], 'info')
        self.assertEqual(BlockedDate.objects.count(), 1)
        result = self.client.post(reverse('admin_blocked_date_delete', args=[blocked.pk]), **self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertFalse(BlockedDate.objects.exists())
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'confirmed')
        self.assertEqual(list(get_messages(result.wsgi_request)), [])

    def test_async_invalid_dates_have_inline_field_errors(self):
        for value in ('', 'not-a-date', (timezone.localdate()-timedelta(days=1)).isoformat()):
            with self.subTest(value=value):
                response = self.client.post(self.create_url, {'date':value}, **self.headers)
                self.assertEqual(response.status_code, 400)
                self.assertIn('date', response.json()['errors'])
        self.assertFalse(BlockedDate.objects.exists())

    def test_calendar_keeps_overnight_legacy_and_explicit_event_end_times(self):
        target = self._future_date()
        explicit = self._make_booking(target, 'confirmed')
        explicit.event_time = time(22)
        explicit.event_end_time = time(1)
        explicit.event_end_date = target + timedelta(days=1)
        explicit.save()
        legacy = self._make_booking(target, 'confirmed')
        default = self._make_booking(target, 'confirmed')
        default.special_requests = ''
        default.save(update_fields=['special_requests'])
        events = {item['booking_id']: item for item in self.client.get(reverse('admin_calendar'), **self.headers).json()['events']}
        self.assertEqual(events[explicit.pk]['end'], f'{target + timedelta(days=1)}T01:00:00')
        self.assertEqual(events[legacy.pk]['end'], f'{target}T12:00:00')
        self.assertEqual(events[default.pk]['end'], f'{target}T14:00:00')

    def test_async_empty_date_and_reason_limit_keep_original_rules(self):
        result = self.client.post(self.create_url, {'date':self._future_date().isoformat(), 'reason':'x'*300}, **self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(BlockedDate.objects.get().reason), 255)

    def test_temporary_quote_hold_cannot_be_overridden_by_block_anyway(self):
        from types import SimpleNamespace
        target = self._future_date()
        start = timezone.make_aware(timezone.datetime.combine(target, time(10)))
        hold = SimpleNamespace(hold_start=start, hold_end=start+timedelta(hours=2))
        with patch('app.booking_changes.live_holds', return_value=[hold]):
            response = self.client.post(self.create_url, {'date':target.isoformat(),'confirm_conflicts':'1'}, **self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertIn('temporary hold', response.json()['errors']['date'])
        self.assertFalse(BlockedDate.objects.exists())

    def test_json_calendar_and_mutations_require_admin_and_post_csrf(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse('admin_calendar'), **self.headers).status_code, 403)
        self.assertEqual(self.client.post(self.create_url, {'date':self._future_date().isoformat()}, **self.headers).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.create_url, **self.headers).status_code, 405)
        client = Client(enforce_csrf_checks=True); client.force_login(self.admin)
        self.assertEqual(client.post(self.create_url, {'date':self._future_date().isoformat()}, **self.headers).status_code, 403)
        self.assertFalse(BlockedDate.objects.exists())

    def test_calendar_data_with_quotes_and_markup_is_inert_json(self):
        self.customer.first_name = '</script><img src=x onerror=alert(1)>'
        self.customer.save(update_fields=['first_name'])
        self._make_booking(self._future_date(), 'confirmed')
        response = self.client.get(reverse('admin_calendar'))
        self.assertContains(response, '\\u003C/script\\u003E')
        self.assertNotContains(response, '<img src=x onerror=alert(1)>')
