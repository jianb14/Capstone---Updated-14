import os
from pathlib import Path
from unittest import skipUnless
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from .models import BookingChangeRequest, Package
from .booking_changes import snapshot
from . import test_admin_booking_workspace as fixtures
from .test_design_delivery import _design_upload


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class AdminBookingWorkspaceBrowserTests(StaticLiveServerTestCase):
    booking = fixtures.AdminBookingWorkspaceTests.booking

    def setUp(self):
        from .models import User
        self.admin = User.objects.create_user(username='browser-booking-admin', role='admin')
        self.user = User.objects.create_user(username='browser-booking-customer', first_name='Review', last_name='Customer', role='customer')
        Package.objects.create(name='Package A',price=4000)
        self.bookings = [self.booking() for _ in range(10)]
        self.pending = self.booking(status='pending', paid=False)
        original = snapshot(self.bookings[0]); proposed = {**original, 'motto_text':'Updated text'}
        self.change = BookingChangeRequest.objects.create(booking=self.bookings[0], original=original,
            proposed=proposed, status='pending_review', original_total=5000, quoted_total=5000, reason='Please update the backdrop text.')
        self.client.force_login(self.admin)
        self.cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value

    def context(self, browser, width=1440, height=1000, theme='light'):
        context = browser.new_context(viewport={'width':width,'height':height}, reduced_motion='reduce')
        context.route('https://**', lambda route: route.fulfill(body='window.Swal={mixin:()=>({fire:()=>{}}),fire:()=>Promise.resolve({}),DismissReason:{}};',content_type='application/javascript') if 'sweetalert' in route.request.url else route.abort())
        context.add_init_script('localStorage.setItem("balloorina-theme", "'+theme+'")')
        context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.cookie,'url':self.live_server_url}])
        return context

    def test_async_paging_search_modals_design_delivery_and_request_validation(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
            context = self.context(browser); page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(self.live_server_url+reverse('admin_booking_list'),wait_until='domcontentloaded')
            page.evaluate('window.bookingWorkspaceSentinel=123')
            expect(page.locator('.ab-table tbody tr')).to_have_count(8)
            page.get_by_role('link',name='Page 2',exact=True).click()
            expect(page.locator('.ab-table tbody tr')).to_have_count(3)
            page.get_by_role('button',name='Rows per page: 8',exact=True).click()
            page.get_by_role('option',name='4',exact=True).click()
            expect(page.locator('.ab-table tbody tr')).to_have_count(4)
            search = page.get_by_role('searchbox',name='Search bookings')
            search.fill('unmatched')
            expect(page.get_by_text('No matching bookings',exact=True)).to_be_visible()
            expect(page.locator('.ab-table')).to_have_count(0)
            page.get_by_role('button',name='Clear search',exact=True).click()
            expect(page.locator('.ab-table tbody tr')).to_have_count(4)
            page.get_by_role('link',name='Design Delivery',exact=False).click()
            expect(page.locator('.ab-table tbody tr')).to_have_count(8)
            row = page.locator(f'[data-booking-id="{self.bookings[0].pk}"]')
            row.get_by_role('link',name='Send design',exact=True).click()
            expect(page.locator('#abDetails')).to_be_visible()
            expect(page.locator('#abModalTitle')).to_have_text('Design delivery')
            page.locator('#abDetails').get_by_role('button',name='Send design',exact=True).click()
            expect(page.locator('[data-error-for=design_image]')).to_be_visible()
            page.locator('[data-design-file]').set_input_files({'name':'bad.txt','mimeType':'text/plain','buffer':b'bad'})
            expect(page.locator('[data-error-for=design_image]')).to_contain_text('Choose a JPG')
            page.locator('[data-design-file]').set_input_files({'name':'design.png','mimeType':'image/png','buffer':_design_upload().read()})
            page.locator('#abDesignCaption').fill('Final backdrop')
            page.screenshot(path=str(Path(settings.BASE_DIR)/'.booking-followup-check'/'booking-design-modal-light.png'))
            page.locator('#abDetails').get_by_role('button',name='Send design',exact=True).click()
            expect(page.locator('.ab-deliveries article')).to_have_count(1)
            expect(page.locator('.ab-deliveries')).to_contain_text('Final backdrop')
            page.locator('#abDetails').get_by_role('button',name='Close design delivery',exact=True).click()
            expect(row).to_contain_text('Design sent')
            page.get_by_role('link',name='Change Requests',exact=False).click()
            expect(page.locator('[data-request-id]')).to_have_count(1)
            page.get_by_role('link',name='Review Request',exact=True).click()
            expect(page.locator('#abModalTitle')).to_have_text('Review change request')
            page.screenshot(path=str(Path(settings.BASE_DIR)/'.booking-followup-check'/'booking-change-modal-light.png'))
            page.locator('.change-decline-section summary').click()
            page.get_by_role('button',name='Decline Change Request',exact=True).click()
            expect(page.locator('[data-error-for=admin_notes]')).to_be_visible()
            page.locator('#change_decline_reason').fill('Please coordinate these changes with our team.')
            page.get_by_role('button',name='Decline Change Request',exact=True).click()
            expect(page.locator('#abDetails')).to_contain_text('Declined')
            expect(page.get_by_role('button',name='Decline Change Request',exact=True)).to_have_count(0)
            page.locator('#abDetails').get_by_role('button',name='Close change request',exact=True).click()
            expect(page.get_by_text('No active change requests',exact=True)).to_be_visible()
            self.assertEqual(page.evaluate('window.bookingWorkspaceSentinel'),123)
            self.assertEqual(errors,[])
            context.close(); browser.close()

    def test_light_dark_responsive_modal_footer_focus_and_date_validation(self):
        from playwright.sync_api import sync_playwright, expect
        screenshots = Path(settings.BASE_DIR)/'.booking-followup-check'
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
            for width,height in ((1440,1000),(390,844),(320,640)):
                for theme in ('light','dark'):
                    with self.subTest(width=width,theme=theme):
                        context = self.context(browser,width,height,theme); page = context.new_page(); errors=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        page.goto(self.live_server_url+reverse('admin_booking_list'),wait_until='domcontentloaded')
                        self.assertEqual(page.locator('html').get_attribute('data-theme'),'light' if theme == 'light' else None)
                        search = page.get_by_role('searchbox',name='Search bookings'); search.focus()
                        self.assertEqual(search.evaluate('(e)=>getComputedStyle(e).outlineWidth'),'2px')
                        self.assertLessEqual(page.locator('.ab-workspace').evaluate('(e)=>e.scrollWidth-e.clientWidth'),1)
                        page.screenshot(path=str(screenshots/f'booking-workspace-{width}-{theme}.png'),full_page=True)
                        page.locator('[data-booking-modal]').first.click()
                        expect(page.locator('#abModalTitle')).to_have_text('Booking details')
                        body = page.locator('#abDetails .ab-modal-body')
                        body.evaluate('(e)=>e.scrollTop=e.scrollHeight')
                        expect(page.locator('#abDetails .ab-modal-footer')).to_be_in_viewport()
                        self.assertLessEqual(page.locator('#abDetails').evaluate('(e)=>e.scrollWidth-e.clientWidth'),1)
                        page.screenshot(path=str(screenshots/f'booking-details-{width}-{theme}.png'))
                        page.locator('#abDetails').get_by_role('button',name='Close booking details',exact=True).click()
                        page.locator('.ab-send').first.click()
                        expect(page.locator('#abModalTitle')).to_have_text('Design delivery')
                        page.locator('#abDetails .ab-modal-body').evaluate('(e)=>e.scrollTop=e.scrollHeight')
                        expect(page.locator('#abDetails .ab-modal-footer')).to_be_in_viewport()
                        self.assertLessEqual(page.locator('#abDetails').evaluate('(e)=>e.scrollWidth-e.clientWidth'),1)
                        page.screenshot(path=str(screenshots/f'booking-design-{width}-{theme}.png'))
                        page.locator('#abDetails').get_by_role('button',name='Close design delivery',exact=True).click()
                        page.get_by_role('link',name='Change Requests',exact=False).click()
                        page.get_by_role('link',name='Review Request',exact=True).click()
                        expect(page.locator('#abModalTitle')).to_have_text('Review change request')
                        self.assertLessEqual(page.locator('#abDetails').evaluate('(e)=>e.scrollWidth-e.clientWidth'),1)
                        if width > 600:
                            self.assertEqual(page.locator('.change-comparison th').first.evaluate('(e)=>getComputedStyle(e).backgroundColor'),
                                'rgb(247, 247, 247)' if theme == 'light' else 'rgb(32, 32, 32)')
                        page.screenshot(path=str(screenshots/f'booking-change-{width}-{theme}.png'))
                        page.locator('#abDetails').get_by_role('button',name='Close change request',exact=True).click()
                        page.locator('.ab-tabs').get_by_role('link',name='Bookings',exact=False).click()
                        page.get_by_role('button',name='Dates',exact=True).click()
                        page.locator('[name=date_from]').fill('2099-02-02'); page.locator('[name=date_to]').fill('2099-01-01')
                        page.get_by_role('button',name='Apply dates',exact=True).click()
                        expect(page.locator('[data-filter-error]')).to_contain_text('end date must be on or after')
                        self.assertEqual(errors,[])
                        context.close()
            browser.close()

    def test_buttons_map_history_validation_and_change_comparison_in_both_themes(self):
        from playwright.sync_api import sync_playwright, expect
        from .models import Booking, BookingStatusLog
        from urllib.request import urlopen
        # Use the real Leaflet renderer, not a marker stub. Cache is optional.
        sources = {}
        for extension in ('js', 'css'):
            filename = Path(settings.BASE_DIR)/'.booking-followup-check'/f'leaflet.{extension}'
            if filename.exists():
                sources[extension] = filename.read_text(encoding='utf-8')
            else:
                with urlopen(f'https://unpkg.com/leaflet@1.9.4/dist/leaflet.{extension}', timeout=20) as response:
                    sources[extension] = response.read().decode('utf-8')
        booking = self.bookings[-1]
        Booking.objects.filter(pk=booking.pk).update(event_lat='14.595000', event_lng='120.973000')
        for index in range(15):
            BookingStatusLog.objects.create(booking=booking, new_status=('pending','pending_payment','confirmed','cancelled','expired')[index%5],
                notes=f'Booking history entry {index}', changed_by=self.admin if index%2 else None)
        self.change.status = 'quoted'
        self.change.quote = {'items':[], 'logistics':1000, 'overtime':0, 'difference':0}
        self.change.save(update_fields=['status','quote'])
        screenshots = Path(settings.BASE_DIR)/'.booking-followup-check'
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            for width,height in ((1440,1000),(390,844)):
                for theme in ('light','dark'):
                    with self.subTest(width=width,theme=theme):
                        context = self.context(browser,width,height,theme)
                        context.route('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js', lambda route: route.fulfill(content_type='application/javascript',body=sources['js']))
                        context.route('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css', lambda route: route.fulfill(content_type='text/css',body=sources['css']))
                        page = context.new_page(); errors = []
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        page.goto(self.live_server_url+reverse('admin_booking_list'),wait_until='domcontentloaded')
                        page.evaluate('window.bookingWorkspaceSentinel=321')
                        row = page.locator(f'[data-booking-id="{booking.pk}"]')
                        buttons = row.locator('.ab-actions > *')
                        colors = buttons.evaluate_all('(items)=>items.map(e=>getComputedStyle(e).backgroundColor)')
                        self.assertEqual(len(set(colors)),1)
                        row.hover()
                        self.assertEqual(buttons.evaluate_all('(items)=>items.map(e=>getComputedStyle(e).backgroundColor)'),colors)
                        buttons.first.hover()
                        self.assertNotEqual(buttons.first.evaluate('(e)=>getComputedStyle(e).backgroundColor'),colors[0])
                        row.get_by_role('link',name='View booking',exact=True).click()
                        expect(page.locator('#abModalTitle')).to_have_text('Booking details')
                        self.assertLessEqual(page.locator('.ab-booking-summary>.ab-badge').bounding_box()['height'],36)
                        expect(page.locator('.ab-history-item:visible')).to_have_count(7)
                        page.get_by_role('button',name='Show more',exact=True).click()
                        expect(page.locator('.ab-history-item:visible')).to_have_count(15)
                        bullet_colors = page.locator('.ab-history-item').evaluate_all('(items)=>items.map(e=>getComputedStyle(e,"::before").backgroundColor)')
                        self.assertGreater(len(set(bullet_colors)),2)
                        page.get_by_role('button',name='Show less',exact=True).click()
                        expect(page.locator('.ab-history-item:visible')).to_have_count(7)
                        venue = page.locator('#abVenueMap'); venue.scroll_into_view_if_needed()
                        marker = venue.locator('.map-pin-dot')
                        expect(marker).to_be_visible()
                        self.assertEqual(marker.evaluate('(e)=>getComputedStyle(e).width'),'20px')
                        coordinates = venue.evaluate('(e)=>e.__bookingMapCtx.marker.getLatLng()')
                        self.assertAlmostEqual(coordinates['lat'],14.595,places=5)
                        self.assertAlmostEqual(coordinates['lng'],120.973,places=5)
                        page.screenshot(path=str(screenshots/f'booking-map-pin-{width}-{theme}.png'))
                        page.locator('#abDetails').get_by_role('button',name='Close booking details',exact=True).click()
                        row.locator('.ab-send').click()
                        expect(page.locator('#abModalTitle')).to_have_text('Design delivery')
                        caption = page.locator('#abDesignCaption'); caption.fill('')
                        caption.focus(); page.keyboard.insert_text('x'*300)
                        self.assertEqual(len(caption.input_value()),255)
                        expect(page.locator('[data-caption-count]')).to_have_text('255/255')
                        header_top = page.locator('#abDetails .ab-modal-header').bounding_box()['y']
                        page.locator('#abDetails').get_by_role('button',name='Send design',exact=True).click()
                        expect(page.locator('#abImageError')).to_be_visible()
                        expect(page.locator('#abDetails [data-browse]')).to_be_focused()
                        expect(page.locator('#abDetails .ab-modal-header')).to_be_in_viewport()
                        expect(page.locator('#abDetails .ab-modal-footer')).to_be_in_viewport()
                        self.assertAlmostEqual(page.locator('#abDetails .ab-modal-header').bounding_box()['y'],header_top,delta=1)
                        self.assertEqual(page.locator('#abDetails').evaluate('(e)=>[e.scrollTop,e.querySelector(".ab-modal-shell").scrollTop,e.querySelector("form").scrollTop]'),[0,0,0])
                        page.screenshot(path=str(screenshots/f'booking-design-required-{width}-{theme}.png'))
                        page.locator('#abDetails').get_by_role('button',name='Close design delivery',exact=True).click()
                        page.get_by_role('link',name='Change Requests',exact=False).click()
                        request_row = page.locator('[data-request-id]').first
                        review = request_row.locator('[data-booking-modal]')
                        page.mouse.move(1,1)
                        review_color = review.evaluate('(e)=>getComputedStyle(e).backgroundColor')
                        request_row.hover()
                        self.assertEqual(review.evaluate('(e)=>getComputedStyle(e).backgroundColor'),review_color)
                        review.click()
                        expect(page.locator('#abModalTitle')).to_have_text('Review change request')
                        changed = page.locator('.change-comparison tbody td').last
                        original = page.locator('.change-comparison tbody td').first
                        self.assertNotEqual(changed.evaluate('(e)=>getComputedStyle(e).backgroundColor'),original.evaluate('(e)=>getComputedStyle(e).backgroundColor'))
                        color = changed.evaluate('(e)=>getComputedStyle(e).backgroundColor')
                        changed.hover()
                        self.assertEqual(changed.evaluate('(e)=>getComputedStyle(e).backgroundColor'),color)
                        self.assertEqual(page.locator('.change-quote-breakdown').first.evaluate('(e)=>getComputedStyle(e).borderTopColor'),'rgb(229, 229, 229)' if theme == 'light' else 'rgb(48, 48, 48)')
                        page.screenshot(path=str(screenshots/f'booking-change-highlight-{width}-{theme}.png'))
                        self.assertEqual(page.evaluate('window.bookingWorkspaceSentinel'),321)
                        self.assertFalse(errors,errors)
                        context.close()
            browser.close()

    def test_failed_search_keeps_results_and_back_forward_restore_modal_without_reload(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
            context = self.context(browser); page = context.new_page()
            page.goto(self.live_server_url+reverse('admin_booking_list'),wait_until='domcontentloaded')
            page.evaluate('window.bookingWorkspaceSentinel=456')
            page.locator('[data-booking-modal]').first.click()
            expect(page.locator('#abDetails')).to_be_visible()
            page.go_back()
            expect(page.locator('#abDetails')).not_to_be_visible()
            page.go_forward()
            expect(page.locator('#abDetails')).to_be_visible()
            page.locator('#abDetails').get_by_role('button',name='Close booking details',exact=True).click()
            queue_pattern = self.live_server_url+reverse('admin_booking_list')+'?**'
            page.route(queue_pattern, lambda route: route.abort())
            page.get_by_role('searchbox',name='Search bookings').fill('failed search')
            expect(page.locator('[data-load-error]')).to_contain_text('Your last results are still shown.')
            expect(page.locator('.ab-table tbody tr')).to_have_count(8)
            page.unroute(queue_pattern)
            page.get_by_role('button',name='Clear search',exact=True).click()
            expect(page.locator('[data-load-error]')).not_to_be_visible()
            expect(page.locator('.ab-table tbody tr')).to_have_count(8)
            self.assertEqual(page.evaluate('window.bookingWorkspaceSentinel'),456)
            context.close(); browser.close()

    def test_modal_errors_distinguish_server_records_permissions_and_login_then_retry(self):
        from playwright.sync_api import sync_playwright, expect
        from .models import BookingStatusLog
        BookingStatusLog.objects.create(booking=self.pending, new_status='pending', changed_by=None,
            notes='System generated history entry.')
        detail_url = self.live_server_url+reverse('admin_booking_detail', args=[self.pending.pk])
        cases = (
            (500, 'The server could not load this information.'),
            (404, 'This record could not be found.'),
            (403, 'You do not have permission'),
            (401, 'Your session has ended.'),
            (200, 'The server returned an unexpected response.'),
        )
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
            for theme in ('light', 'dark'):
                context = self.context(browser, width=390, height=844, theme=theme)
                page = context.new_page(); errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url+reverse('admin_booking_list'),wait_until='domcontentloaded')
                page.evaluate('window.bookingWorkspaceSentinel=789')
                for status, message in cases:
                    page.route(detail_url, lambda route: route.fulfill(status=status,content_type='text/html',body='<h1>Server response</h1>'))
                    page.locator(f'[data-booking-id="{self.pending.pk}"] [data-booking-modal]').first.click()
                    expect(page.locator('#abModalTitle')).to_have_text('Unable to load details')
                    expect(page.locator('#abDetails [role=alert]')).to_contain_text(message)
                    spacing = page.locator('#abDetails .ab-modal-error').evaluate('(body) => body.querySelector("button").getBoundingClientRect().top - body.querySelector("p").getBoundingClientRect().bottom')
                    self.assertGreaterEqual(spacing, 14)
                    page.unroute(detail_url)
                    page.get_by_role('button', name='Try again', exact=True).click()
                    expect(page.locator('#abModalTitle')).to_have_text('Booking details')
                    expect(page.locator('#abDetails')).to_contain_text('System / removed account')
                    page.locator('#abDetails').get_by_role('button',name='Close booking details',exact=True).click()
                page.route(self.live_server_url+'/login/**', lambda route: route.fulfill(content_type='text/html',body='<h1>Sign in</h1>'))
                page.route(detail_url, lambda route: route.fulfill(status=302, headers={'Location':'/login/?next=/staff/bookings/'}))
                page.locator(f'[data-booking-id="{self.pending.pk}"] [data-booking-modal]').first.click()
                expect(page.locator('#abDetails [role=alert]')).to_contain_text('Your session has ended.')
                self.assertEqual(page.evaluate('window.bookingWorkspaceSentinel'), 789)
                self.assertFalse(errors, errors)
                context.close()
            browser.close()
