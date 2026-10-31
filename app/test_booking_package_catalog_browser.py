"""Visible popular labels and selectable, ordered booking cards on phones and desktop."""
import os
from datetime import date, time
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import Booking, Package, User
from .test_booking_package_catalog import seed_booking_packages


@skipUnless(os.environ.get('RUN_PACKAGES_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class BookingPackageCatalogBrowserTests(StaticLiveServerTestCase):
    def test_create_feedback_focus_picker_fonts_and_pin_warning_only_on_next(self):
        from playwright.sync_api import expect, sync_playwright
        from .test_concerns import photo

        seed_booking_packages()
        user = User.objects.create_user(username='booking-feedback-browser', role='customer', email_verified=True)
        self.client.force_login(user)
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            context = browser.new_context(reduced_motion='reduce')
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + '/') else route.abort())
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME, 'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url':self.live_server_url}])
            page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                for theme in ('light','dark'):
                    for width in (1440,390):
                        page.set_viewport_size({'width':width,'height':1000})
                        page.goto(self.live_server_url + reverse('booking_page') + '?from=packages&event_date=2099-06-15',wait_until='domcontentloaded')
                        page.evaluate('''theme => {
                            document.documentElement.dataset.theme=theme;
                            window.bookingNotices=[]; AppToast.fire=options=>{bookingNotices.push(options);return Promise.resolve({});};
                            // Exercise the live-map validation without external map requests.
                            BookingLocationMap.isMapReady=()=>true;
                            window.bookingClock=Date.now(); Date.now=()=>bookingClock;
                        }''', theme)
                        modal = page.locator('#bookingModalOverlay')
                        card = modal.locator('.package-card[data-package="Package 1-A"]')
                        card.hover()
                        expect(card).to_have_css('border-color','rgb(212, 212, 212)' if theme=='light' else 'rgb(66, 66, 66)')
                        expect(card).to_have_css('background-color','rgb(250, 250, 250)' if theme=='light' else 'rgb(27, 27, 27)')
                        card.click()
                        expect(card).to_have_css('border-color','rgb(189, 189, 189)' if theme=='light' else 'rgb(85, 85, 85)')
                        expect(card).to_have_css('background-color','rgb(243, 243, 243)' if theme=='light' else 'rgb(32, 32, 32)')
                        stepper = modal.locator('.stepper-wrapper')
                        geometry = stepper.evaluate('''el => {
                            const rect=el.getBoundingClientRect();
                            return [...el.querySelectorAll('.step-circle')].map((circle,index)=>{
                                const box=circle.getBoundingClientRect();
                                return {offset:Math.abs(box.x+box.width/2-(rect.x+rect.width*(index+.5)/5)),
                                    border:getComputedStyle(circle).borderWidth};
                            });
                        }''')
                        self.assertTrue(all(item['offset']<1 and item['border']=='0px' for item in geometry),geometry)
                        page.locator('#btnNextStep').click(); page.locator('#btnNextToDetails').click()
                        page.locator('#btnNextToSummary').click()
                        red = 'rgb(184, 53, 60)' if theme=='light' else 'rgb(241, 145, 145)'
                        red_ring = 'rgba(184, 53, 60, 0.4)' if theme=='light' else 'rgba(241, 145, 145, 0.4)'
                        normal_ring = 'rgba(105, 105, 105, 0.4)' if theme=='light' else 'rgba(153, 153, 153, 0.45)'
                        for selector in ('#event_type_error','#start_time_error','#end_time_error','#event_location_error','.input-required'):
                            expect(modal.locator(selector).first).to_have_css('color',red)
                        for selector in ('#start_time_display','#end_time_display','#event_location'):
                            control = page.locator(selector); control.focus()
                            expect(control).to_have_css('border-color',red)
                            expect(control).to_have_css('outline-color',red_ring)
                        self.assertEqual(page.evaluate('bookingNotices.length'),0)
                        trigger = page.locator('#eventTypeCustomSelect .custom-select-trigger')
                        trigger.click()
                        expect(trigger).to_have_attribute('aria-invalid','true')
                        expect(trigger).to_have_css('border-color',red)
                        expect(trigger).to_have_css('outline-color',red_ring)
                        # Opening and dismissing the list must preserve the error.
                        trigger.click(); trigger.click()
                        expect(trigger).to_have_css('outline-color',red_ring)
                        page.locator('#eventTypeCustomSelect [data-value="Birthday"]').click()
                        expect(trigger).to_have_attribute('aria-invalid','false')
                        page.evaluate('bookingClock+=10000')
                        page.locator('#start_time_display').click()
                        first_time = modal.locator('.booking-picker-pop:not([hidden]) .booking-picker-timeopt').first
                        first_time.focus()
                        expect(page.locator('#start_time_display')).to_have_css('border-color',red)
                        expect(page.locator('#start_time_display')).to_have_css('outline-color',red_ring)
                        expect(modal.locator('.booking-picker-timeopt').first).to_have_css('font-family','Montserrat, sans-serif')
                        modal.locator('.booking-picker-pop:not([hidden]) .booking-picker-timeopt[data-value="07:00"]').click()
                        expect(page.locator('#start_time_display')).to_have_attribute('aria-invalid','false')
                        expect(page.locator('#start_time_display')).to_have_css('outline-color',normal_ring)
                        page.evaluate('bookingClock+=10000')
                        page.locator('#end_time_display').click()
                        modal.locator('.booking-picker-pop:not([hidden]) .booking-picker-timeopt').first.focus()
                        expect(page.locator('#end_time_display')).to_have_css('border-color',red)
                        expect(page.locator('#end_time_display')).to_have_css('outline-color',red_ring)
                        modal.locator('.booking-picker-pop:not([hidden]) .booking-picker-timeopt[data-value="10:00"]').click()
                        page.locator('#event_location').fill('Molino Bacoor Cavite venue')
                        self.assertEqual(page.evaluate('bookingNotices.length'),0)
                        page.locator('#btnNextToSummary').click()
                        self.assertEqual(page.evaluate('bookingNotices.filter(n=>n.title==="Map pin required.").length'),1)
                        for value in ('Wedding','Birthday'):
                            page.evaluate('bookingClock+=10000')
                            page.locator('#eventTypeCustomSelect .custom-select-trigger').click()
                            page.locator('#eventTypeCustomSelect [data-value="'+value+'"]').click()
                        self.assertEqual(page.evaluate('bookingNotices.filter(n=>n.title==="Map pin required.").length'),1)
                        page.locator('#event_date').click()
                        expect(modal.locator('.booking-picker-pop:not([hidden]) .booking-picker-day').first).to_have_css('font-family','Montserrat, sans-serif')
                        page.locator('#event_location').focus()
                        page.evaluate('''() => {
                            document.getElementById('event_lat_input').value='14.414';
                            document.getElementById('event_lng_input').value='120.982';
                        }''')
                        page.locator('#btnNextToSummary').click()
                        expect(page.locator('#step-4')).to_be_visible()
                        page.locator('#designThemeChips [data-value="Other"]').click()
                        for selector in ('#design_theme_other','#motto_text','#booking_special_requests'):
                            control = page.locator(selector); control.focus()
                            expect(control).to_have_css('outline-color',normal_ring)
                            expect(control).to_have_css('outline-width','2px')
                        optional = modal.locator('.booking-optional').last
                        expect(optional).to_have_css('color','rgb(115, 115, 115)' if theme=='light' else 'rgb(163, 163, 163)')
                        browse = modal.get_by_role('button',name='Browse Files',exact=True)
                        browse.hover()
                        expect(browse).to_have_css('background-color','rgb(233, 233, 233)' if theme=='light' else 'rgb(51, 51, 51)')
                        zone = modal.locator('.reference-dropzone')
                        self.assertNotEqual(browse.evaluate('el=>getComputedStyle(el).backgroundColor'),zone.evaluate('el=>getComputedStyle(el).backgroundColor'))
                        expect(zone).to_contain_text('5MB per photo')
                        file_input = page.locator('#booking_reference_images_ui')
                        file_input.set_input_files({'name':'large.png','mimeType':'image/png','buffer':b'x'*(5*1024*1024+1)})
                        expect(zone.locator('.reference-upload-status')).to_contain_text('5MB or smaller')
                        self.assertEqual(page.locator('#booking_reference_images').evaluate('el=>el.files.length'),0)
                        file_input.set_input_files({'name':'small.png','mimeType':'image/png','buffer':photo().read()})
                        expect(zone.locator('.reference-upload-status')).to_contain_text('1 new image selected')
                        zone.dispatch_event('drop',{'dataTransfer':page.evaluate_handle('''()=>{
                            const transfer=new DataTransfer();
                            transfer.items.add(new File([new Uint8Array(5*1024*1024+1)],'large.png',{type:'image/png'}));
                            return transfer;
                        }''')})
                        expect(zone.locator('.reference-upload-status')).to_contain_text('5MB or smaller')
                        self.assertEqual(page.locator('#booking_reference_images').evaluate('el=>el.files.length'),1)
                        stepper.screenshot(path=str(artifacts / f'booking-connected-stepper-{theme}-{width}.png'))
                        browse.hover()
                        modal.screenshot(path=str(artifacts / f'booking-form-feedback-{theme}-{width}.png'))
                self.assertEqual(errors,[])
            finally:
                context.close(); browser.close()

    def test_popular_order_badge_bounds_and_selection_in_create_and_edit(self):
        from playwright.sync_api import expect, sync_playwright

        seed_booking_packages()
        Package.objects.filter(name__in=['Package 2', 'Package 3']).update(is_featured=True)
        Package.objects.create(name='Package 0', price=100, is_featured=True, is_active=False)
        user = User.objects.create_user(username='booking-package-browser', role='customer')
        self.client.force_login(user)
        booking = Booking.objects.create(user=user, event_type='Birthday', event_date=date(2099, 7, 15),
            event_time=time(8), event_location='Bacoor venue', package_type='Package 1-B',
            total_price=9500, status='pending')
        cookie = {'name': settings.SESSION_COOKIE_NAME,
                  'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}
        expected = ['Package 2', 'Package 3', 'Package 1', 'Package 1-A', 'Package 1-B', 'Package 10']
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        errors = []
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                for width in (1440, 820, 390, 320):
                    context = browser.new_context(viewport={'width': width, 'height': 1000},
                        has_touch=True, is_mobile=width <= 1024, reduced_motion='reduce')
                    context.add_cookies([cookie])
                    context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                    context.route('https://unpkg.com/**', lambda route: route.abort())
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    try:
                        for route, params, modal_id, step_id, input_id, next_id, back_id in (
                            ('booking_page', '?from=packages&event_date=2099-06-15',
                             'bookingModalOverlay', 'step-1', 'package_type_input', 'btnNextStep', 'btnBackToPackages'),
                            ('customer_profile', f'?open_edit={booking.pk}',
                             'editBookingModal', 'edit-step-1', 'edit_package_type_input', 'btnNextEditStep', 'btnPrevEditPreview'),
                        ):
                            page.goto(self.live_server_url + reverse(route) + params, wait_until='domcontentloaded')
                            modal = page.locator(f'#{modal_id}')
                            expect(modal).to_be_visible()
                            cards = page.locator(f'#{step_id} .package-card[data-package]')
                            self.assertEqual(cards.evaluate_all('(cards) => cards.map(card => card.dataset.package)'), expected)
                            expect(cards.locator('.booking-popular-badge')).to_have_count(2)
                            self.assertEqual(cards.filter(has=page.locator('.booking-popular-badge')).evaluate_all(
                                '(cards) => cards.map(card => card.dataset.package)'), ['Package 2', 'Package 3'])
                            for theme in ('light', 'dark'):
                                page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                                popular = cards.first
                                popular.locator('.booking-popular-badge').tap()
                                expect(popular).to_have_class('package-card selected' if route == 'booking_page'
                                                             else 'package-card edit-package-card selected')
                                bounds = popular.evaluate('''card => {
                                    const box = card.getBoundingClientRect();
                                    const badge = card.querySelector('.booking-popular-badge').getBoundingClientRect();
                                    const title = card.querySelector('h4').getBoundingClientRect();
                                    const check = getComputedStyle(card, '::before');
                                    return {left: badge.left - box.left, right: box.right - badge.right,
                                        top: badge.top - box.top, gap: title.top - badge.bottom,
                                        checkGap: box.right - parseFloat(check.right) - parseFloat(check.width) - badge.right};
                                }''')
                                self.assertTrue(all(value >= 0 for value in bounds.values()), f'{route}, {width}, {theme}: {bounds}')
                                self.assertLessEqual(modal.locator('.booking-modal-box').evaluate(
                                    'el => el.scrollWidth - el.clientWidth'), 1)
                                if width in (1440, 390):
                                    modal.screenshot(path=str(artifacts / f'booking-popular-{route}-{theme}-{width}.png'), animations='disabled')
                                page.locator(f'#{next_id}').tap()
                                expect(page.locator(f'#{input_id}')).to_have_value('Package 2')
                                page.locator(f'#{back_id}').tap()
                                cards.filter(has_text='Package 1-A').tap()
                                page.locator(f'#{next_id}').tap()
                                expect(page.locator(f'#{input_id}')).to_have_value('Package 1-A')
                                page.locator(f'#{back_id}').tap()
                                self.assertEqual(cards.evaluate_all('(cards) => cards.map(card => card.dataset.package)'), expected)
                    finally:
                        context.close()
                self.assertEqual(errors, [])
            finally:
                browser.close()
