"""RUN_MULTI_DESIGN_BROWSER=1: real pages, isolated DB/media, no external requests."""
import os
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from . import test_design_requirements as fixtures
from .models import Booking, ServiceChargeConfig
from .test_booking_preview import _preview_upload


@skipUnless(os.environ.get('RUN_MULTI_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies', SESSION_COOKIE_SECURE=False,
                   CSRF_COOKIE_SECURE=False, SECURE_SSL_REDIRECT=False, REQUEST_RATE_LIMITING_ENABLED=False)
class MultiDesignBrowserTests(StaticLiveServerTestCase):
    obj = fixtures.DesignRequirementsTests.obj
    canvas = fixtures.DesignRequirementsTests.canvas
    complete = fixtures.DesignRequirementsTests.complete
    design = fixtures.DesignRequirementsTests.design

    def test_delete_updates_library_and_selection_without_reloading(self):
        from playwright.sync_api import sync_playwright, expect
        from .models import SiteSettings
        config = SiteSettings.load()
        config.max_saved_designs = 7
        config.save()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width':1440, 'height':1000}, reduced_motion='reduce')
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url+'/') else route.abort())
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME, 'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url':self.live_server_url}])
            page = context.new_page()
            try:
                page.goto(self.live_server_url+reverse('my_designs'), wait_until='domcontentloaded')
                expect(page.locator('.create-new-btn')).to_be_disabled()
                for kind in ('package', 'stand'):
                    page.locator(f'[data-select-design="{self.saved[kind].pk}"]').click()
                page.locator('[name="q"]').fill('Blush birthday')
                expect(page.locator('.design-card')).to_have_count(1)
                page.evaluate('window.deleteDocumentMarker = "preserved"')
                page.evaluate('(id)=>{window.openDeleteModal(id);}', self.saved['package'].pk)
                page.get_by_role('button', name='Delete design', exact=True).click()
                expect(page.locator('.design-card')).to_have_count(0)
                expect(page.locator('#designStorageCount strong')).to_have_text('6/7')
                self.assertEqual(page.evaluate('window.deleteDocumentMarker'), 'preserved')
                expect(page.locator('[name="q"]')).to_have_value('Blush birthday')
                expect(page.locator('.create-new-btn')).to_be_enabled()
                expect(page.locator('#designLimitNote')).to_have_count(0)
                expect(page.locator('#designBookingCount')).to_have_text('0/3')
                expect(page.locator('.designs-stats-bar .design-stat-value').first).to_have_text('6')
                expect(page.locator('.client-feedback-toast')).to_contain_text('Design deleted successfully', timeout=15000)
            finally:
                context.close(); browser.close()

    def test_delete_last_page_and_retry_failed_list_refresh(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width':390, 'height':844}, reduced_motion='reduce')
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url+'/') else route.abort())
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME, 'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url':self.live_server_url}])
            page = context.new_page()
            try:
                page.goto(self.live_server_url+reverse('my_designs')+'?per_page=4&sort=newest&page=2', wait_until='domcontentloaded')
                page.evaluate('document.documentElement.dataset.theme="dark";window.deleteDocumentMarker="preserved"')
                expect(page.locator('.design-card')).to_have_count(3)
                page.route('**/my-designs/?*', lambda route: route.fulfill(status=503, body='Unavailable'), times=1)
                for used, remaining in ((6, 2), (5, 1), (4, 4)):
                    design_id = int(page.locator('.design-card').last.get_attribute('data-design-id'))
                    page.evaluate('(id)=>{window.openDeleteModal(id);}', design_id)
                    page.get_by_role('button', name='Delete design', exact=True).click()
                    if remaining == 2:
                        expect(page.locator('#designSearchStatus')).to_contain_text('Design deleted. Could not refresh')
                        expect(page.locator('.client-feedback-toast')).to_contain_text('Design deleted successfully')
                        page.get_by_role('button', name='Try again', exact=True).click()
                    expect(page.locator('#designLibraryResults')).to_have_attribute('data-page', '1' if remaining == 4 else '2')
                    expect(page.locator('.design-card')).to_have_count(remaining)
                    expect(page.locator('#designSearchStatus')).to_be_hidden()
                    expect(page.locator('#designStorageCount strong')).to_have_text(f'{used}/20')
                expect(page).to_have_url(self.live_server_url+reverse('my_designs')+'?per_page=4&sort=newest&page=1')
                expect(page.locator('#designStorageCount strong')).to_have_text('4/20')
                self.assertEqual(page.evaluate('window.deleteDocumentMarker'), 'preserved')
                self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
            finally:
                context.close(); browser.close()

    def test_selection_controls_and_hover_states_in_both_themes(self):
        from playwright.sync_api import sync_playwright, expect
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check/multi-design-polish'
        artifacts.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context = browser.new_context(viewport={'width':1440,'height':1000}, reduced_motion='reduce')
            context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(self.live_server_url+'/') else route.abort())
            context.route('**/fonts.googleapis.com/**',lambda route:route.fulfill(content_type='text/css',body="@font-face{font-family:Montserrat;src:url('"+self.live_server_url+"/static/fonts/canvas/montserrat/normal.woff2');font-weight:100 900}"))
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            page=context.new_page()
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            def style(locator):
                return locator.evaluate('(el)=>{const s=getComputedStyle(el);return [s.backgroundColor,s.borderColor,s.boxShadow,s.transform]}')
            try:
                page.goto(self.live_server_url+reverse('my_designs'),wait_until='domcontentloaded')
                for theme in ('light','dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    expect(page.locator('#designStorageCount span')).to_be_visible()
                    expect(page.locator(f'[data-design-rate="{self.saved["stand"].pk}"]')).to_be_empty()
                    self.assertEqual(page.locator('[name="q"]').evaluate('el=>getComputedStyle(el).paddingRight'),'14px')
                    page.locator('#designBookingClear').click() if page.locator('#designBookingClear').is_enabled() else None
                    expect(page.locator('.design-booking-art svg')).to_have_count(3)
                    marker=page.locator(f'[data-check-design="{self.saved["package"].pk}"]')
                    marker.click()
                    expect(marker).to_have_attribute('aria-checked','true')
                    expect(page.locator('.client-feedback-toast')).to_have_count(1)
                    toast=page.locator('.client-feedback-toast')
                    self.assertLess(toast.bounding_box()['y'],100)
                    page.evaluate('window.AppToast.close()')
                    card=page.locator(f'[data-design-id="{self.saved["package"].pk}"]')
                    page.locator('.designs-header').hover()
                    before=style(card)
                    card.hover()
                    self.assertEqual(style(card),before)
                    selected=card.locator('[data-select-design]')
                    before=style(selected)
                    selected.hover()
                    self.assertEqual(style(selected),before)
                    disabled=page.locator(f'[data-select-design="{self.alternative.pk}"]')
                    before=style(disabled)
                    disabled.hover(force=True)
                    self.assertEqual(style(disabled),before)
                    remove=page.locator(f'[data-remove-design="{self.saved["package"].pk}"]')
                    size=remove.bounding_box()
                    background=style(remove)[0]
                    remove.hover()
                    self.assertNotEqual(style(remove)[0],background)
                    self.assertEqual(remove.bounding_box()['width'],size['width'])
                    self.assertEqual(remove.bounding_box()['height'],size['height'])
                    self.assertEqual(remove.locator('svg').evaluate('el=>el.getBoundingClientRect().width'),16)
                    marker.click()
                    expect(marker).to_have_attribute('aria-checked','false')
                    expect(page.locator('#designBookingCount')).to_have_text('0/3')
                    expect(page.locator('#designSelectionFeedback')).to_be_hidden(timeout=5000)
                    for width in (1440,1024,768,390,320):
                        page.set_viewport_size({'width':width,'height':844})
                        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                        trigger=page.locator('.designs-sort .ac-select-trigger')
                        trigger.click()
                        label=trigger.locator('span').first
                        self.assertLessEqual(label.evaluate('el=>el.getBoundingClientRect().height'),26)
                        page.keyboard.press('Escape')
                        if width<=980:
                            page.locator('#designBookingOpen').click()
                            expect(page.locator('#designBookingClose svg')).to_be_visible()
                            self.assertEqual(page.locator('#designBookingClose svg').evaluate('el=>el.getBoundingClientRect().width'),18)
                            self.assertEqual(page.locator('#designBookingDialog').evaluate('el=>getComputedStyle(el).overflowY'),'hidden')
                            self.assertEqual(page.locator('.design-booking-scroll-area').evaluate('el=>getComputedStyle(el).scrollbarWidth'),'thin')
                            expect(page.locator('#designBookingOpen svg')).to_have_count(1)
                            page.screenshot(path=str(artifacts/f'{theme}-{width}-summary.png'))
                            if width==390:
                                page.set_viewport_size({'width':width,'height':520})
                                close_y=page.locator('#designBookingClose').bounding_box()['y']
                                scroll=page.locator('.design-booking-scroll-area')
                                self.assertTrue(scroll.evaluate('el=>el.scrollHeight>el.clientHeight'))
                                scroll.evaluate('el=>el.scrollTop=el.scrollHeight')
                                self.assertEqual(page.locator('#designBookingClose').bounding_box()['y'],close_y)
                            page.keyboard.press('Escape')
                    page.set_viewport_size({'width':1440,'height':1000})
                    marker.click()
                    expect(page.locator('#designBookingContinue svg')).to_be_visible()
                    page.evaluate('window.scrollTo(0,0)')
                    page.screenshot(path=str(artifacts/f'{theme}-desktop.png'),full_page=True)
                self.assertEqual(errors,[])
            finally:
                context.close();browser.close()

    def setUp(self):
        fixtures.DesignRequirementsTests.setUpTestData.__func__(type(self))
        ServiceChargeConfig.objects.update_or_create(pk=1, defaults={'amount': 100})
        self.saved = {
            'package': self.design(name='Blush birthday setup'),
            'entrance': self.design(self.canvas(self.obj(self.balloon)), self.entrance_offer, name='Blush entrance arch'),
            'stand': self.design(self.canvas(self.obj(self.balloon)), self.stand_offer, name='Birthday welcome'),
        }
        for kind, design in self.saved.items():
            design.thumbnail.save(f'{kind}.png', _preview_upload())
        self.alternative = self.design(name='Alternative package')
        for i in range(3):
            self.design(name=f'Other package {i}')
        self.client.force_login(self.user)

    @patch('app.views.bookings.send_admin_alert_email')
    @patch.dict(os.environ, {'DJANGO_ALLOW_ASYNC_UNSAFE': 'true'})
    def test_selection_handoff_quote_review_and_one_booking(self, alert):
        from playwright.sync_api import sync_playwright, expect

        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check/multi-design-booking'
        artifacts.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width':1440, 'height':1050}, reduced_motion='reduce')
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + '/') else route.abort())
            context.route('**/fonts.googleapis.com/**', lambda route: route.fulfill(content_type='text/css', body="@font-face{font-family:Montserrat;src:url('" + self.live_server_url + "/static/fonts/canvas/montserrat/normal.woff2');font-weight:100 900}"))
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME, 'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url':self.live_server_url}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            choose = lambda kind: page.locator(f'[data-select-design="{self.saved[kind].pk}"]')
            try:
                page.goto(self.live_server_url + reverse('my_designs'), wait_until='domcontentloaded', timeout=60000)
                page.evaluate("document.documentElement.dataset.theme='light'")
                expect(choose('stand')).to_be_disabled()
                choose('package').click()
                expect(page.locator(f'[data-select-design="{self.alternative.pk}"]')).to_be_disabled()
                choose('entrance').click()
                choose('stand').click()
                expect(page.locator('#designBookingCount')).to_have_text('3/3')
                expect(page.locator('#designBookingTotal')).to_have_text('₱7,700.00')
                package_card = page.locator(f'[data-design-id="{self.saved["package"].pk}"]')
                package_card.locator('.menu-dots-btn').click()
                package_card.get_by_role('menuitem', name='Rename', exact=True).click()
                page.locator('#renameInput').fill('Renamed birthday design')
                page.locator('#renameSave').click()
                expect(page.locator('#designBookingSlots')).to_contain_text('Renamed birthday design')
                page.locator('[name="q"]').fill('Alternative')
                expect(page.locator('#designLibraryResults .design-card')).to_have_count(1)
                expect(page.locator('#designBookingCount')).to_have_text('3/3')
                page.locator('#designSearchClear').click()
                expect(page.locator('#designLibraryResults .design-card')).to_have_count(7)
                page.locator('.account-page-size .ac-select-trigger').click()
                page.locator('.account-page-size .ac-select-menu [data-value="4"]').click()
                expect(page.locator('#designLibraryResults .design-card')).to_have_count(4)
                page.locator('[data-list-page][href*="page=2"]').first.click()
                expect(page.locator('#designLibraryResults .design-card')).to_have_count(3)
                expect(page.locator('#designBookingCount')).to_have_text('3/3')
                page.locator('.account-page-size .ac-select-trigger').click()
                page.locator('.account-page-size .ac-select-menu [data-value="8"]').click()
                expect(page.locator('#designLibraryResults .design-card')).to_have_count(7)
                page.locator('[data-design-kind="entrance"]').click()
                expect(page.locator('#designLibraryResults .design-card')).to_have_count(1)
                expect(page.locator('#designBookingTotal')).to_have_text('₱7,700.00')
                page.locator('[data-design-kind=""]').click()
                expect(page.locator('#designLibraryResults .design-card')).to_have_count(7)
                page.screenshot(path=str(artifacts/'desktop-light.png'), full_page=True)
                page.evaluate("document.documentElement.dataset.theme='dark'")
                page.screenshot(path=str(artifacts/'desktop-dark.png'), full_page=True)
                page.evaluate("document.documentElement.dataset.theme='light'")
                page.set_viewport_size({'width':390,'height':844})
                self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                page.locator('#designBookingOpen').click()
                expect(page.locator('#designBookingDialog')).to_be_visible()
                page.screenshot(path=str(artifacts/'mobile-summary.png'))
                page.locator(f'[data-remove-design="{self.saved["package"].pk}"]').click()
                expect(page.locator('#designBookingTotal')).to_have_text('₱3,700.00')
                page.locator(f'[data-remove-design="{self.saved["entrance"].pk}"]').click()
                expect(page.locator('#designBookingCount')).to_have_text('0/3')
                expect(page.locator('#designBookingContinue')).to_be_disabled()
                page.keyboard.press('Escape')
                expect(page.locator('#designBookingDialog')).not_to_be_visible()
                self.assertEqual(page.evaluate('document.activeElement.id'), 'designBookingOpen')
                page.set_viewport_size({'width':1440,'height':1050})
                for kind in ('package','entrance','stand'):
                    choose(kind).click()
                page.locator('#designBookingContinue').click()
                expect(page.locator('#bookingModalOverlay')).to_have_class(__import__('re').compile('show'))
                expect(page.locator('[name="user_design_id"]')).to_have_count(3)
                expect(page.locator('#savedDesignSelectionSummary p')).to_have_count(3)
                expect(page.locator('.saved-design-booking-preview')).to_have_count(3)
                page.locator('#eventTypeCustomSelect .custom-select-trigger').click()
                page.locator('#eventTypeCustomSelect [data-value="Birthday"]').click()
                page.evaluate('''() => {
                    for (const [id, value] of Object.entries({event_date:'2030-01-15',start_time:'09:00',end_time:'11:00'})) {
                        const field=document.getElementById(id);field.value=value;field.dispatchEvent(new Event('change',{bubbles:true}));
                    }
                    document.querySelector('[name="map_available"]').value='0';
                }''')
                page.locator('#event_location').fill('Test Venue in Cavite')
                page.locator('#btnNextToSummary').click()
                expect(page.locator('#step-3')).to_be_visible()
                expect(page.locator('.saved-design-offer-badge')).to_have_text([self.package.name, self.entrance.name, self.stand.name])
                expect(page.locator('#savedDesignSelectionSummary p > span').first).to_have_text(self.package.name)
                expect(page.locator('.saved-design-booking-rate')).to_have_text('With package rate')
                for theme, background in (('light', 'rgb(247, 247, 247)'), ('dark', 'rgb(32, 32, 32)')):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                    self.assertEqual(page.locator('.saved-design-booking-selection').evaluate('el=>getComputedStyle(el).backgroundColor'), background)
                    for width in (1440, 768, 390, 320):
                        page.set_viewport_size({'width':width, 'height':1050 if width==1440 else 844})
                        panel = page.locator('.saved-design-booking-selection')
                        panel.scroll_into_view_if_needed()
                        self.assertFalse(page.locator('#bookingModalOverlay .booking-modal-box').evaluate('el=>el.scrollWidth>el.clientWidth'))
                        self.assertTrue(page.locator('.saved-design-booking-preview').evaluate_all('figures=>figures.every(figure=>{const image=figure.querySelector("img").getBoundingClientRect(),badge=figure.querySelector(".saved-design-offer-badge").getBoundingClientRect();return badge.bottom<=image.bottom&&badge.top>=image.top&&badge.left>=image.left&&badge.right<=image.right;})'))
                        if width != 320:
                            page.screenshot(path=str(artifacts/f'selected-designs-{theme}-{width}.png'))
                            page.locator('.saved-design-booking-preview').last.scroll_into_view_if_needed()
                            page.screenshot(path=str(artifacts/f'preview-badges-{theme}-{width}.png'))
                page.set_viewport_size({'width':1440, 'height':1050})
                page.evaluate('document.documentElement.dataset.theme="light"')
                page.locator('#btnPrevFromDesign').click()
                expect(page.locator('#event_location')).to_have_value('Test Venue in Cavite')
                page.locator('#btnNextToSummary').click()
                page.locator('#designPaletteSwatches button').first.click()
                page.locator('#btnNextDesignToReview').click()
                expect(page.locator('#step-4')).to_be_visible()
                self.entrance.price = 1700
                self.entrance.save()
                ServiceChargeConfig.objects.filter(pk=1).update(amount=300)
                page.locator('#btnSubmitBooking').click()
                with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith(reverse('create_booking'))) as request:
                    page.get_by_role('button', name='Submit Request', exact=True).click()
                self.assertEqual(request.value.status,409)
                expect(page.locator('#savedDesignFeedback')).to_contain_text('Review the updated selection')
                expect(page.locator('#savedDesignSelectionSummary')).to_contain_text('1,700.00')
                expect(page.locator('#total_price_input')).to_have_value('8200.00')
                self.assertEqual(Booking.objects.count(),0)
                page.screenshot(path=str(artifacts/'updated-quote-review.png'), full_page=True)
                page.locator('#btnSubmitBooking').click()
                with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith(reverse('create_booking'))) as request:
                    page.get_by_role('button', name='Submit Request', exact=True).click()
                self.assertTrue(request.value.json()['success'],request.value.text())
                booking = Booking.objects.get()
                self.assertEqual(booking.designs.count(),3)
                self.assertEqual(str(booking.total_price),'8200.00')
                self.assertIsNone(page.evaluate(f"sessionStorage.getItem('balloorina:design-booking:{self.user.pk}')"))
                details_url = self.live_server_url+reverse('customer_profile')+f'?booking_id={booking.pk}&modal=details'
                page.goto(details_url, wait_until='domcontentloaded')
                references = page.locator('#viewMultiImageGrid [data-booking-reference]')
                expect(references).to_have_count(3)
                expect(references.locator('.booking-reference-badge')).to_have_text([self.package.name, self.entrance.name, self.stand.name])
                for theme in ('light', 'dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                    for width in (1440, 390, 320):
                        page.set_viewport_size({'width':width,'height':844})
                        trigger = references.first
                        trigger.click()
                        viewer = page.locator('#bookingReferenceDialog')
                        expect(viewer).to_be_visible()
                        expect(viewer.locator('h2')).to_have_text(self.package.name)
                        self.assertEqual(len(context.pages), 1)
                        self.assertEqual(page.url, details_url)
                        self.assertFalse(viewer.evaluate('el=>el.scrollWidth>el.clientWidth'))
                        page.screenshot(path=str(artifacts/f'reference-viewer-{theme}-{width}.png'))
                        page.keyboard.press('Escape')
                        expect(viewer).not_to_be_visible()
                        expect(page.locator('#bookingModal')).to_have_class(__import__('re').compile('show'))
                        expect(trigger).to_be_focused()
                references.nth(1).click()
                page.get_by_role('button', name='Close image preview', exact=True).click()
                expect(page.locator('#bookingReferenceDialog')).not_to_be_visible()
                expect(references.nth(1)).to_be_focused()
                self.assertEqual(errors,[])
            finally:
                context.close()
                browser.close()

    @patch.dict(os.environ, {'DJANGO_ALLOW_ASYNC_UNSAFE': 'true'})
    def test_restored_library_revalidates_and_keyboard_focus_stays_visible(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context = browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
            context.route('**/*',lambda route: route.continue_() if route.request.url.startswith(self.live_server_url+'/') else route.abort())
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            page = context.new_page()
            try:
                page.goto(self.live_server_url+reverse('my_designs'),wait_until='domcontentloaded')
                button = page.locator(f'[data-select-design="{self.saved["package"].pk}"]')
                button.click()
                page.locator(f'[data-remove-design="{self.saved["package"].pk}"]').click()
                self.assertEqual(page.evaluate('document.activeElement.id'),'designBookingSummaryTitle')
                button.click()
                self.saved['package'].delete()
                page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
                expect(page.locator('#designBookingNotice')).to_contain_text('no longer available')
                expect(page.locator('#designBookingContinue')).to_be_disabled()
                page.locator('#designBookingClear').click()
                expect(page.locator('#designBookingCount')).to_have_text('0/3')
            finally:
                context.close();browser.close()

    @patch.dict(os.environ, {'DJANGO_ALLOW_ASYNC_UNSAFE': 'true'})
    def test_complimentary_extras_require_a_package_when_solo_rate_is_zero(self):
        from playwright.sync_api import sync_playwright, expect
        self.entrance.price = 0
        self.entrance.solo_price = 0
        self.entrance.save()
        self.stand.price = 0
        self.stand.save()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context = browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
            context.route('**/*',lambda route: route.continue_() if route.request.url.startswith(self.live_server_url+'/') else route.abort())
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            page = context.new_page()
            try:
                page.goto(self.live_server_url+reverse('my_designs'),wait_until='domcontentloaded')
                entrance = page.locator(f'[data-select-design="{self.saved["entrance"].pk}"]')
                expect(entrance).to_be_disabled()
                for kind in ('package','entrance','stand'):
                    page.locator(f'[data-select-design="{self.saved[kind].pk}"]').click()
                expect(page.locator('#designBookingTotal')).to_have_text('₱5,000.00')
                expect(page.locator('#designBookingContinue')).to_be_enabled()
                for width in (768,390,320):
                    page.set_viewport_size({'width':width,'height':844})
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'),f'Overflow at {width}')
            finally:
                context.close();browser.close()
