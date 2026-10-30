"""Real FullCalendar browser checks: asynchronous actions, unchanged scheduling and responsive themes."""
import os
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import BlockedDate, Booking, User


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies', REQUEST_RATE_LIMITING_ENABLED=False)
class AdminCalendarBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='calendar-browser-admin', role='admin')
        self.customer = User.objects.create_user(username='calendar-browser-customer', first_name='Jamie', role='customer')
        self.target = timezone.localdate() + timedelta(days=10)
        self.booking = Booking.objects.create(user=self.customer, event_date=self.target, event_time=time(10),
            event_end_time=time(12), event_end_date=self.target, event_type='Birthday', event_location='Venue',
            package_type='Package A', total_price=5000, status='confirmed')
        Booking.objects.create(user=self.customer, event_date=self.target+timedelta(days=1), event_time=time(10),
            event_type='Wedding', package_type='Package A', total_price=5000, status='pending')
        self.client.force_login(self.admin)
        self.cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.artifacts = Path(settings.BASE_DIR)/'.booking-followup-check'
        self.artifacts.mkdir(exist_ok=True)

    def context(self, browser, width=1440, height=1000, theme='light', cdn=True):
        context = browser.new_context(viewport={'width':width,'height':height}, reduced_motion='reduce')
        source = self.artifacts/'fullcalendar-6.1.11.js'
        if cdn and not source.exists():
            from urllib.request import urlretrieve
            urlretrieve('https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.js', source)
        def external(route):
            if route.request.url.startswith(self.live_server_url + '/'):
                route.continue_()
            elif cdn and 'fullcalendar@6.1.11/index.global.min.js' in route.request.url:
                route.fulfill(path=str(source),content_type='application/javascript')
            elif 'sweetalert' in route.request.url:
                route.fulfill(body='window.Swal={mixin:()=>({fire:()=>{}}),fire:()=>Promise.resolve({}),DismissReason:{}};',content_type='application/javascript')
            else:
                route.abort()
        context.route('**/*', external)
        context.add_init_script('localStorage.setItem("balloorina-theme", "'+theme+'")')
        context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.cookie,'url':self.live_server_url}])
        return context

    def open_target(self, page):
        page.locator('#cal-title').click()
        year = int(page.locator('#myp-year-display').inner_text())
        while year != self.target.year:
            page.locator('#myp-next-year' if year < self.target.year else '#myp-prev-year').click()
            year = int(page.locator('#myp-year-display').inner_text())
        page.locator(f'[data-month="{self.target.month-1}"]').click()

    def test_calendar_navigation_filters_details_block_unblock_are_async(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            context = self.context(browser); page = context.new_page(); errors=[]
            page.on('pageerror', lambda error:errors.append(str(error)))
            page.goto(self.live_server_url+reverse('admin_calendar'),wait_until='domcontentloaded')
            page.evaluate('window.calendarSentinel=42')
            expect(page.locator('.fc-dayGridMonth-view')).to_be_visible(); self.open_target(page)
            target = page.locator(f'.fc-daygrid-day[data-date="{self.target.isoformat()}"]')
            expect(target.locator('.fc-event')).to_have_count(1)
            page.locator('[data-status=confirmed]').click()
            expect(page.locator('[data-status=confirmed]')).to_have_attribute('aria-pressed','true')
            expect(page.locator('.fc-event').filter(has_text='Jamie')).to_have_count(1)
            page.locator('[data-status=confirmed]').click()
            expect(page.locator('[data-status=confirmed]')).to_have_attribute('aria-pressed','false')
            target.locator('.fc-event').click()
            expect(page.locator('#calPopover')).to_contain_text('Confirmed')
            page.keyboard.press('Escape'); expect(page.locator('#calPopover')).to_be_hidden()
            page.locator('[data-view=timeGridWeek]').click(); expect(page.locator('.fc-timeGridWeek-view')).to_be_visible()
            page.locator('#cal-next').click(); page.locator('#cal-prev').click()
            page.locator('[data-view=dayGridMonth]').click(); self.open_target(page)
            page.get_by_role('button',name='Block Date',exact=True).click()
            expect(page.locator('[data-error-for=date]')).to_have_text('Please choose a date to block.')
            page.locator('#blockedDate').fill(self.target.isoformat())
            page.locator('#blockedReason').fill('Maintenance')
            expect(page.locator('#blockedConflictHint')).to_contain_text('already has 1 booking')
            page.get_by_role('button',name='Block Date',exact=True).click()
            expect(page.locator('#calConfirm')).to_be_visible()
            page.locator('#calConfirm').get_by_role('button',name='Cancel',exact=True).click()
            expect(page.get_by_text('No blocked dates',exact=True)).to_be_visible()
            page.get_by_role('button',name='Block Date',exact=True).click()
            page.get_by_role('button',name='Block Anyway',exact=True).click()
            expect(page.locator('.blocked-item')).to_have_count(1)
            expect(target).to_have_class(__import__('re').compile('booking-day-blocked'))
            expect(target.locator('.fc-event:not(.blocked-flag-event)')).to_have_count(1)
            expect(page.locator('.cfg-toast')).to_contain_text('remain on this date')
            page.get_by_role('button',name='Unblock',exact=True).click()
            page.locator('#calConfirm').get_by_role('button',name='Unblock',exact=True).click()
            expect(page.get_by_text('No blocked dates',exact=True)).to_be_visible()
            expect(target.locator('.booking-day-blocked-label')).to_have_count(0)
            expect(target.locator('.fc-event')).to_have_count(1)
            self.assertEqual(page.evaluate('window.calendarSentinel'),42)
            self.assertEqual(errors,[])
            context.close(); browser.close()
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status,'confirmed')
        self.assertFalse(BlockedDate.objects.exists())

    def test_light_dark_mobile_layout_focus_and_popover(self):
        from playwright.sync_api import sync_playwright, expect
        BlockedDate.objects.create(date=self.target, reason='Holiday', created_by=self.admin)
        empty_date = self.target+timedelta(days=2)
        BlockedDate.objects.create(date=empty_date, reason='No bookings', created_by=self.admin)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            for width,height in ((1440,1000),(390,844),(320,740)):
                for theme in ('light','dark'):
                    with self.subTest(width=width,theme=theme):
                        context = self.context(browser,width,height,theme); page = context.new_page(); errors=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        page.goto(self.live_server_url+reverse('admin_calendar'),wait_until='domcontentloaded'); self.open_target(page)
                        expect(page.locator('.fc')).to_be_visible()
                        self.assertLessEqual(page.locator('.admin-calendar-page').evaluate('(e)=>e.scrollWidth-e.clientWidth'),1)
                        self.assertLessEqual(page.locator('body').evaluate('(e)=>e.scrollWidth-innerWidth'),1)
                        cell = page.locator(f'.fc-daygrid-day[data-date="{self.target.isoformat()}"]')
                        expect(cell.locator('.booking-day-blocked-label')).to_be_visible()
                        expect(cell.locator('.fc-event:not(.blocked-flag-event)')).to_be_visible()
                        self.assertEqual(cell.evaluate('(e)=>getComputedStyle(e).backgroundColor'),
                            'rgb(247, 247, 247)' if theme == 'light' else 'rgb(32, 32, 32)')
                        self.assertGreaterEqual(page.locator('[data-view=dayGridMonth]').evaluate('(e)=>parseFloat(getComputedStyle(e).paddingLeft)'),10)
                        empty = page.locator(f'.fc-daygrid-day[data-date="{empty_date.isoformat()}"]')
                        label = empty.locator('.booking-day-blocked-label')
                        expect(label).to_be_visible(); expect(label.locator('svg')).to_be_visible()
                        if theme == 'dark':
                            self.assertEqual(label.evaluate('(e)=>getComputedStyle(e).color'),'rgb(163, 163, 163)')
                        centers = empty.evaluate('''e => {
                            const frame = e.querySelector('.fc-daygrid-day-frame').getBoundingClientRect();
                            const icon = e.querySelector('.booking-day-blocked-label svg').getBoundingClientRect();
                            const text = e.querySelector('.booking-day-blocked-label span').getBoundingClientRect();
                            const left = Math.min(icon.left,text.left), right = Math.max(icon.right,text.right);
                            const top = Math.min(icon.top,text.top), bottom = Math.max(icon.bottom,text.bottom);
                            const date = e.querySelector('.fc-daygrid-day-number').getBoundingClientRect();
                            return {dx: Math.abs((left+right-frame.left-frame.right)/2), stacked: icon.bottom < text.top, gap: top-date.bottom, contained: bottom <= frame.bottom};
                        }''')
                        self.assertLessEqual(centers['dx'],1)
                        self.assertTrue(centers['stacked'],centers); self.assertTrue(centers['contained'],centers)
                        self.assertGreaterEqual(centers['gap'],4)
                        expect(page.locator('.cal-blocked-key input,.cal-blocked-key button')).to_have_count(0)
                        expect(page.locator('.cal-blocked-key .cal-blocked-icon svg')).to_be_visible()
                        page.screenshot(path=str(self.artifacts/f'admin-calendar-{width}-{theme}.png'),full_page=True)
                        cell.locator('.fc-daygrid-day-number').click()
                        expect(page.locator('#calPopover')).to_be_visible()
                        expect(page.locator('#calPopover')).to_contain_text('existing booking(s) remain')
                        bounds = page.locator('#calPopover').bounding_box()
                        self.assertGreaterEqual(bounds['x'],0);self.assertLessEqual(bounds['x']+bounds['width'],width)
                        self.assertLessEqual(bounds['y']+bounds['height'],height)
                        page.locator('#calPopClose').click()
                        page.locator('#blockedReason').focus()
                        self.assertEqual(page.locator('#blockedReason').evaluate('(e)=>getComputedStyle(e).outlineWidth'),'2px')
                        page.locator('#blockedReason').fill('x'*300)
                        expect(page.locator('#blocked-reason-count')).to_have_text('255/255')
                        page.locator('[data-status=completed]').click()
                        expect(page.locator('[data-status=completed]')).to_have_attribute('aria-pressed','true')
                        page.locator('[data-status=completed]').click()
                        self.assertEqual(errors,[])
                        context.close()
            browser.close()

    def test_week_has_one_blocked_indicator_with_reason_and_preserves_bookings(self):
        from io import BytesIO
        from PIL import Image
        from playwright.sync_api import sync_playwright, expect
        self.target = timezone.localdate()-timedelta(days=timezone.localdate().weekday())
        self.booking.event_date = self.target
        self.booking.event_end_date = self.target
        self.booking.save(update_fields=['event_date','event_end_date'])
        empty_date = self.target+timedelta(days=2)
        reason = '<img src=x onerror=alert(1)> Shop closed'
        BlockedDate.objects.create(date=self.target, reason='Bookings remain', created_by=self.admin)
        BlockedDate.objects.create(date=empty_date, reason=reason, created_by=self.admin)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            for width,height in ((1440,1000),(390,844),(320,740)):
                for theme in ('light','dark'):
                    with self.subTest(width=width,theme=theme):
                        context = self.context(browser,width,height,theme); page = context.new_page(); errors=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        page.goto(self.live_server_url+reverse('admin_calendar'),wait_until='domcontentloaded'); self.open_target(page)
                        page.evaluate('window.calendarSentinel=64')
                        page.locator('[data-view=timeGridWeek]').click()
                        for _ in range(5):
                            if page.locator(f'.fc-timegrid-col[data-date="{self.target.isoformat()}"]').count():
                                break
                            page.locator('#cal-next').click()
                        flags = page.locator('.fc-timeGridWeek-view .blocked-flag-event:visible')
                        expect(flags).to_have_count(2)
                        expect(page.locator('.fc-timeGridWeek-view .booking-day-blocked-label')).to_have_count(0)
                        expect(page.locator('.fc-timegrid-body .fc-event').filter(has_text='Jamie').first).to_be_visible()
                        def assert_blocked_column_shading():
                            page.mouse.move(0,0)
                            expect(page.locator('.cfg-toast')).to_be_hidden(timeout=8000)
                            body = page.locator('.fc-timegrid-body')
                            rendered = Image.open(BytesIO(body.screenshot())).convert('RGB')
                            body_bounds = body.bounding_box()
                            # Check actual pixels: opaque slot rows can hide a correctly styled column.
                            for slot_index in (8,40):
                                slot = body.locator('.fc-timegrid-slot').nth(slot_index).bounding_box()
                                samples = {}
                                # Sample empty dates so booking cards cannot cover the column tint.
                                for date in (empty_date, self.target+timedelta(days=5)):
                                    column = body.locator(f'.fc-timegrid-col[data-date="{date.isoformat()}"]')
                                    bounds = column.bounding_box()
                                    x = round(bounds['x']+bounds['width']/2-body_bounds['x'])
                                    y = round(slot['y']+slot['height']/2-body_bounds['y'])
                                    samples[date] = rendered.getpixel((x,y))
                                blocked = samples[empty_date]
                                normal = samples[self.target+timedelta(days=5)]
                                contrast = [n-b if theme=='light' else b-n for b,n in zip(blocked,normal)]
                                self.assertTrue(all(value>=5 for value in contrast),samples)
                            if theme == 'light':
                                ordinary = page.locator('.fc-timeGridWeek-view :is(.fc-timegrid-col,.fc-daygrid-day):not(.booking-day-blocked)')
                                colors = ordinary.evaluate_all('cols=>cols.map(e=>getComputedStyle(e).backgroundColor)')
                                self.assertTrue(all(color=='rgb(255, 255, 255)' for color in colors),colors)
                        assert_blocked_column_shading()
                        for flag in flags.all():
                            expect(flag.locator('.cal-week-blocked')).to_have_text('Blocked')
                            expect(flag.locator('svg')).to_be_visible()
                            alignment = flag.evaluate('''e => {
                                const cell = e.closest('.fc-daygrid-day').getBoundingClientRect();
                                const icon = e.querySelector('svg').getBoundingClientRect();
                                const label = e.querySelector('.cal-week-blocked span').getBoundingClientRect();
                                return {x: Math.abs((icon.left+icon.right-cell.left-cell.right)/2), y: Math.abs((icon.top+label.bottom-cell.top-cell.bottom)/2)};
                            }''')
                            self.assertLessEqual(alignment['x'],2,alignment)
                            self.assertLessEqual(alignment['y'],2,alignment)
                        if theme == 'dark':
                            self.assertEqual(flags.first.evaluate('(e)=>getComputedStyle(e).color'),'rgb(163, 163, 163)')
                        page.screenshot(path=str(self.artifacts/f'admin-calendar-week-blocked-{width}-{theme}.png'),full_page=True)
                        empty_flag = flags.filter(has=page.locator('[aria-hidden=true]')).last
                        empty_flag.click()
                        expect(page.locator('#calPopover')).to_contain_text(reason)
                        expect(page.locator('#calPopover img')).to_have_count(0)
                        page.locator('#calPopClose').click()
                        empty_flag.focus(); page.keyboard.press('Enter')
                        expect(page.locator('#calPopover')).to_contain_text(reason)
                        page.locator('#calPopClose').click()
                        page.locator('[data-status=completed]').click()
                        expect(flags).to_have_count(2)
                        expect(page.locator('.fc-timegrid-body .fc-event:not(.blocked-flag-event)')).to_have_count(0)
                        page.locator('#cal-refresh').click()
                        expect(page.locator('#cal-refresh')).to_be_enabled()
                        expect(flags).to_have_count(2)
                        expect(page.locator('.fc-timeGridWeek-view .booking-day-blocked-label')).to_have_count(0)
                        assert_blocked_column_shading()
                        page.locator('[data-view=dayGridMonth]').click()
                        expect(page.locator(f'.fc-daygrid-day[data-date="{empty_date.isoformat()}"] .booking-day-blocked-label')).to_be_visible()
                        self.assertEqual(page.evaluate('window.calendarSentinel'),64)
                        self.assertLessEqual(page.locator('body').evaluate('(e)=>e.scrollWidth-innerWidth'),1)
                        self.assertEqual(errors,[])
                        context.close()
            browser.close()

    def test_open_page_archives_after_midnight_without_reload_or_deletion(self):
        from playwright.sync_api import sync_playwright, expect
        today = timezone.localdate()
        blocked = BlockedDate.objects.create(date=today, reason='Today only', created_by=self.admin)
        night = datetime.combine(today,time(23,59,30),tzinfo=ZoneInfo('Asia/Manila'))
        with patch('app.views.bookings.timezone.now', return_value=night) as server_clock:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
                context = self.context(browser); page = context.new_page(); errors=[]; methods=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('request',lambda request:methods.append(request.method))
                page.clock.install(time=night); page.clock.pause_at(night+timedelta(seconds=1))
                page.goto(self.live_server_url+reverse('admin_calendar'),wait_until='domcontentloaded')
                expect(page.locator('#blocked-date-count')).to_have_text('1')
                expect(page.locator('#pastBlockedDates')).to_be_hidden()
                page.evaluate('window.calendarSentinel=91')
                server_clock.return_value = night+timedelta(seconds=31)
                page.clock.fast_forward(31000)
                expect(page.locator('#blocked-date-count')).to_have_text('0')
                expect(page.locator('#pastBlockedDates')).to_be_visible()
                expect(page.locator('#past-blocked-date-count')).to_have_text('(1)')
                expect(page.locator('#blockedDate')).to_have_attribute('min',(today+timedelta(days=1)).isoformat())
                page.locator('#pastBlockedDates summary').click()
                expect(page.locator('#pastBlockedDatesList')).to_contain_text('Today only')
                expect(page.locator('#pastBlockedDatesList form,#pastBlockedDatesList button')).to_have_count(0)
                self.assertEqual(page.evaluate('window.calendarSentinel'),91)
                page.reload(wait_until='domcontentloaded')
                expect(page.locator('#blocked-date-count')).to_have_text('0')
                expect(page.locator('#past-blocked-date-count')).to_have_text('(1)')
                self.assertNotIn('POST',methods)
                self.assertEqual(errors,[])
                context.close(); browser.close()
        self.assertTrue(BlockedDate.objects.filter(pk=blocked.pk).exists())

    def test_mobile_bars_fill_days_and_empty_blocked_today_stays_readable(self):
        from playwright.sync_api import sync_playwright, expect
        today = timezone.localdate()
        busy_date = today.replace(day=1) if today.day != 1 else today+timedelta(days=1)
        BlockedDate.objects.create(date=today, reason='No bookings today', created_by=self.admin)
        BlockedDate.objects.create(date=busy_date, reason='Existing bookings remain', created_by=self.admin)
        for index in range(5):
            Booking.objects.create(user=self.customer, event_date=busy_date, event_time=time(8+index),
                event_end_time=time(9+index), event_end_date=busy_date, event_type='Birthday',
                package_type='Package A', total_price=5000, status='confirmed')
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            for width,height in ((443,915),(390,844),(320,740)):
                for theme in ('light','dark'):
                    with self.subTest(width=width,theme=theme):
                        context = self.context(browser,width,height,theme); page = context.new_page(); errors=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        page.goto(self.live_server_url+reverse('admin_calendar'),wait_until='domcontentloaded')
                        page.evaluate('window.calendarSentinel=58')
                        busy = page.locator(f'.fc-daygrid-day[data-date="{busy_date.isoformat()}"]')
                        bars = busy.locator('.cal-event-bar:visible')
                        expect(bars.first).to_be_visible()
                        widths = bars.evaluate_all('elements => elements.map(e => e.getBoundingClientRect().width / e.parentElement.getBoundingClientRect().width)')
                        self.assertTrue(all(.85 <= value <= 1 for value in widths),widths)
                        bar_styles = bars.evaluate_all('elements => elements.map(e => ({border: getComputedStyle(e).borderTopStyle, width: getComputedStyle(e).borderTopWidth, fill: getComputedStyle(e).backgroundColor, status: getComputedStyle(e).getPropertyValue("--cal-event-color").trim()}))')
                        self.assertTrue(all(style['border']=='dashed' and style['width']=='1px' and style['fill']!=style['status'] for style in bar_styles),bar_styles)
                        empty = page.locator(f'.fc-daygrid-day[data-date="{today.isoformat()}"]')
                        label = empty.locator('.booking-day-blocked-label')
                        expect(label).to_have_text('Blocked'); expect(label.locator('svg')).to_be_visible()
                        geometry = empty.evaluate('''e => {
                            const frame=e.querySelector('.fc-daygrid-day-frame').getBoundingClientRect();
                            const day=e.querySelector('.fc-daygrid-day-number').getBoundingClientRect();
                            const icon=e.querySelector('.booking-day-blocked-label svg').getBoundingClientRect();
                            const text=e.querySelector('.booking-day-blocked-label span').getBoundingClientRect();
                            return {gap: icon.top-day.bottom, stacked: icon.bottom < text.top, clipped: text.left < frame.left || text.right > frame.right || text.bottom > frame.bottom, size: parseFloat(getComputedStyle(e.querySelector('.booking-day-blocked-label')).fontSize), minHeight: getComputedStyle(e.querySelector('.fc-daygrid-day-frame')).minHeight, height: frame.height};
                        }''')
                        self.assertGreaterEqual(geometry['gap'],4,geometry); self.assertFalse(geometry['clipped'],geometry)
                        self.assertTrue(geometry['stacked'],geometry); self.assertEqual(geometry['minHeight'],'76px')
                        self.assertLessEqual(geometry['height'],80,geometry)
                        self.assertGreaterEqual(geometry['size'],9)
                        # Resize in place, then filter and refresh: neither markers nor bars disappear.
                        page.set_viewport_size({'width':1440,'height':1000})
                        expect(busy.locator('.cal-event-bar')).to_have_count(0)
                        page.set_viewport_size({'width':width,'height':height})
                        expect(bars.first).to_be_visible()
                        page.locator('[data-status=confirmed]').click()
                        expect(label).to_be_visible(); expect(bars.first).to_be_visible()
                        page.locator('#cal-refresh').click()
                        expect(page.locator('#cal-refresh')).to_be_enabled()
                        expect(label).to_be_visible(); expect(bars.first).to_be_visible()
                        empty.scroll_into_view_if_needed()
                        page.screenshot(path=str(self.artifacts/f'admin-calendar-mobile-bars-{width}-{theme}.png'))
                        busy.locator('.fc-daygrid-more-link').click()
                        expect(page.locator('.fc-popover')).to_be_visible()
                        expect(page.locator('.fc-popover .cal-event-bar')).to_have_count(0)
                        self.assertEqual(page.evaluate('window.calendarSentinel'),58)
                        self.assertLessEqual(page.locator('body').evaluate('(e)=>e.scrollWidth-innerWidth'),1)
                        self.assertEqual(errors,[])
                        context.close()
            browser.close()

    def test_request_failure_and_cdn_failure_preserve_usable_controls(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            context = self.context(browser,cdn=False); page = context.new_page()
            page.goto(self.live_server_url+reverse('admin_calendar'),wait_until='domcontentloaded')
            expect(page.locator('.calendar-load-error')).to_be_visible()
            expect(page.locator('#cal-prev')).to_be_disabled()
            page.evaluate('window.calendarSentinel=77')
            page.locator('#blockedDate').fill((self.target+timedelta(days=3)).isoformat())
            # Use the actual endpoint; other calendar controls remain functional during CDN failure.
            action = page.locator('.blocked-form').get_attribute('action')
            page.route('**'+action,lambda route:route.fulfill(status=500,body='error',content_type='text/html'))
            page.get_by_role('button',name='Block Date',exact=True).click()
            expect(page.locator('#blocked-form-error')).to_contain_text('could not be updated')
            expect(page.get_by_role('button',name='Block Date',exact=True)).to_be_enabled()
            self.assertEqual(page.evaluate('window.calendarSentinel'),77)
            context.close(); browser.close()
        self.assertFalse(BlockedDate.objects.exists())
