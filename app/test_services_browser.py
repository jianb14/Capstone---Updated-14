"""Opt-in browser coverage: RUN_SERVICES_BROWSER=1 (isolated test database)."""
import json
import os
import re
from datetime import time, timedelta
from pathlib import Path
from unittest import skipUnless

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AdditionalOnly, AddOn, BlockedDate, Booking, Package, User


@skipUnless(os.environ.get('RUN_SERVICES_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, REQUEST_RATE_LIMITING_ENABLED=False)
class ServicesBrowserTests(StaticLiveServerTestCase):
    def test_service_tools_and_login_continuation(self):
        from playwright.sync_api import sync_playwright, expect

        user = User.objects.create_user(username='service-browser', email='service-browser@example.com',
            password='ServicePassword!23', role='customer', email_verified=True)
        package = Package.objects.create(name='Package A', price=10000, features='Backdrop')
        arch = AddOn.objects.create(name='Entrance A', price=3000, solo_price=4500, features='Arch')
        arch_b = AddOn.objects.create(name='Entrance B', price=4000, solo_price=5500, features='Arch')
        stand = AdditionalOnly.objects.create(name='Stand A', price=800, features='Stand')
        day = timezone.localdate() + timedelta(days=10)
        blocked = day + timedelta(days=1)
        full = day + timedelta(days=2)
        BlockedDate.objects.create(date=blocked, reason='Maintenance')
        Booking.objects.create(user=user, event_date=full, event_time=time(7), event_end_time=time(18),
            status='confirmed', package_type='Package A', total_price=10000)
        root = Path(__file__).resolve().parent.parent
        artifacts = root / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        image_bytes = (root / 'static/images/service_birthday.png').read_bytes()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            for url, name in (
                ('https://cdn.jsdelivr.net/npm/sweetalert2@11', 'sweetalert2.all.min.js'),
                ('https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.js', 'fullcalendar.js'),
                ('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js', 'leaflet.js'),
            ):
                if (artifacts / name).exists():
                    source = (artifacts / name).read_text(encoding='utf-8')
                    context.route(url, lambda route, request, source=source: route.fulfill(content_type='application/javascript', body=source))
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            context.route('**/media/ai_generated/service-test.png', lambda route: route.fulfill(content_type='image/png', body=image_bytes))
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def go(path):
                page.goto(self.live_server_url + path, wait_until='domcontentloaded')

            def choose(id, value):
                container = page.locator(f'.custom-select-container:has(#{id})')
                container.locator('.custom-select-trigger').click()
                container.locator(f'li[data-value="{value}"]').click()

            def login(destination='**/booking/?*', opens_form=True):
                expect(page.locator('#loginForm')).to_be_visible()
                page.locator('#email').fill(user.email)
                page.locator('#password').fill('ServicePassword!23')
                page.locator('#loginForm button[type="submit"]').click()
                page.wait_for_url(destination)
                if '/booking/' in destination:
                    if opens_form:
                        expect(page.locator('#bookingModalOverlay')).to_be_visible()
                    else:
                        expect(page.locator('#bookingModalOverlay')).to_be_hidden()
                        expect(page.locator('#booking-calendar-mount')).to_be_visible()

            def choose_booking_date(date):
                cell = page.locator(f'.fc-daygrid-day[data-date="{date.isoformat()}"]')
                for _ in range(3):
                    if cell.count() and cell.is_visible():
                        break
                    page.locator('#cal-next').click()
                cell.click(position={'x': 12, 'y': 12})
                expect(page.locator('#bookingModalOverlay')).to_be_visible()
                expect(page.locator('#event_date')).to_have_value(date.isoformat())
                expect(page.locator('#step-1')).to_be_visible()

            def shot(name, target):
                for theme in ('light', 'dark'):
                    for width in (1440, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        page.locator(target).scroll_into_view_if_needed()
                        page.wait_for_timeout(150)
                        page.screenshot(path=str(artifacts / f'services-{name}-{theme}-{width}.png'), animations='disabled')
                        overflow = page.evaluate('''() => ({width: innerWidth, scroll: document.documentElement.scrollWidth,
                            elements: [...document.querySelectorAll('body *')].filter(el => {
                                const r = el.getBoundingClientRect(); return r.width && r.right > innerWidth + 1;
                            }).slice(0, 12).map(el => [el.tagName, el.id, el.className, el.getBoundingClientRect().right])})''')
                        self.assertLessEqual(overflow['scroll'], overflow['width'], str(overflow))

            try:
                # Package-page Book Now carries the exact offer through login and calendar choice.
                go(reverse('package'))
                page.locator(f'.packages-carousel .package-cta[href$="package_id={package.pk}"]').click()
                login(opens_form=False)
                choose_booking_date(day)
                package_card = page.locator(f'#bookingModalOverlay .package-card[data-id="{package.pk}"]').first
                arch_card = page.locator(f'.addon-selector[data-id="{arch.pk}"]')
                stand_card = page.locator(f'.additional-selector[data-id="{stand.pk}"]')
                expect(package_card).to_have_class('package-card selected')
                expect(page.locator('#btnNextStep')).to_be_enabled()

                # Bundle arch stays active while the customer picks its required package.
                go(reverse('package'))
                page.locator(f'.addons-track .package-cta[href*="addon_id={arch.pk}&"]').click()
                expect(page.locator('#bookingModalOverlay')).to_be_hidden()
                choose_booking_date(day)
                expect(arch_card).to_have_class('package-card addon-selector selected')
                expect(page.locator('#btnNextStep')).to_be_disabled()
                expect(page.locator('#catalogSelectionHint')).to_contain_text('Choose a package')
                package_card.click()
                expect(arch_card).to_have_class('package-card addon-selector selected')
                expect(page.locator('#catalogSelectionHint')).to_be_hidden()
                expect(page.locator('#btnNextStep')).to_be_enabled()

                # Solo pricing on Package page enters the existing solo arch flow.
                go(reverse('package'))
                page.locator('.pricing-option[data-pricing="solo"]').click()
                arch_link = page.locator(f'.addons-track .package-cta[href*="addon_id={arch.pk}&"]')
                self.assertIn('arch_mode=solo', arch_link.get_attribute('href'))
                arch_link.click()
                choose_booking_date(day)
                expect(arch_card).to_have_class('package-card addon-selector selected')
                expect(package_card).to_have_class('package-card disabled')
                expect(page.locator('#btnNextStep')).to_be_enabled()

                # Stand selection survives guest login and activates with a solo base.
                context.clear_cookies()
                go(reverse('package'))
                stand_link = page.locator(f'.additionals-track .package-cta[href$="additional_id={stand.pk}"]')
                expect(stand_link).to_have_text('Add to Booking')
                expect(page.locator('.additionals-track .additional-requirement')).to_have_text('Requires a package or solo entrance arch.')
                stand_link.click()
                login(opens_form=False)
                choose_booking_date(day)
                expect(stand_card).to_have_class('package-card additional-selector disabled')
                expect(page.locator('#btnNextStep')).to_be_disabled()
                expect(page.locator('#catalogSelectionHint')).to_contain_text('Stand A will be added after you choose a package or solo entrance arch.')
                shot('stand-request', '#catalogSelectionHint')
                arch_card.click()
                expect(stand_card).to_have_class('package-card additional-selector selected')
                expect(page.locator('#catalogSelectionHint')).to_be_hidden()
                expect(page.locator('#btnNextStep')).to_be_enabled()
                page.locator('#btnNextStep').click()
                expect(page.locator('#step-2')).to_be_visible()
                expect(page.locator('#previewImagesGrid')).to_contain_text('Stand A')

                # A package also completes the stand request and the stand can be removed normally.
                go(reverse('package'))
                page.locator(f'.additionals-track .package-cta[href$="additional_id={stand.pk}"]').click()
                choose_booking_date(day)
                expect(stand_card).to_have_class('package-card additional-selector disabled')
                package_card.click()
                expect(stand_card).to_have_class('package-card additional-selector selected')
                expect(page.locator('#btnNextStep')).to_be_enabled()
                stand_card.click()
                expect(stand_card).to_have_class('package-card additional-selector')
                context.clear_cookies()

                # Guest estimate -> real login -> matching selections in the open booking form.
                go(reverse('services'))
                first = page.locator(f'input[name="estimatorAddon"][value="{arch.pk}"]')
                second = page.locator(f'input[name="estimatorAddon"][value="{arch_b.pk}"]')
                # Discard the old sticky draft, then start with a fresh estimate.
                page.evaluate('(values) => sessionStorage.setItem("balloorina.service-tools", JSON.stringify(values))',
                    {'estimatorPackage': str(package.pk), 'estimatorAddon': str(arch.pk)})
                page.reload(wait_until='domcontentloaded')
                expect(page.locator('#estimatorPackage')).to_have_value('')
                expect(first).not_to_be_checked()
                choose('estimatorPackage', str(package.pk))
                first.check()
                expect(page.locator('#estimatorSubtotal')).to_have_text('₱13,000.00')
                first.uncheck()
                expect(page.locator('#estimatorSubtotal')).to_have_text('₱10,000.00')
                second.check()
                first.check()
                expect(second).not_to_be_checked()
                page.locator(f'input[name="estimatorAdditional"][value="{stand.pk}"]').check()
                expect(page.locator('#estimatorSubtotal')).to_have_text('₱13,800.00')
                shot('estimate', '#price-estimator')
                page.get_by_role('button', name='Clear estimate', exact=True).click()
                expect(first).not_to_be_checked()
                expect(page.locator('#estimatorPackage')).to_have_value('')
                expect(page.locator('#estimatorTotal')).to_be_hidden()
                choose('estimatorPackage', str(package.pk))
                first.check()
                page.reload(wait_until='domcontentloaded')
                expect(first).not_to_be_checked()
                expect(page.locator('#estimatorPackage')).to_have_value('')
                choose('estimatorPackage', str(package.pk))
                first.check()
                page.locator(f'input[name="estimatorAdditional"][value="{stand.pk}"]').check()
                page.locator('#estimatorContinue').click()
                login(opens_form=False)
                choose_booking_date(day)
                expect(page.locator(f'#bookingModalOverlay .package-card[data-id="{package.pk}"]').first).to_have_class('package-card selected')
                expect(page.locator(f'.addon-selector[data-id="{arch.pk}"]')).to_have_class('package-card addon-selector selected')
                expect(page.locator(f'.additional-selector[data-id="{stand.pk}"]')).to_have_class('package-card additional-selector selected')

                # A Service date skips the calendar even when Continue comes from the estimate.
                go(reverse('services'))
                choose('estimatorPackage', str(package.pk))
                first.check()
                page.locator('#availabilityDate').evaluate('(el, value) => { el.value = value; el.dispatchEvent(new Event("change", {bubbles:true})); }', day.isoformat())
                page.locator('#estimatorContinue').click()
                expect(page.locator('#bookingModalOverlay')).to_be_visible()
                expect(page.locator('#step-1')).to_be_visible()
                expect(page.locator('#event_date')).to_have_value(day.isoformat())
                expect(page.locator(f'.addon-selector[data-id="{arch.pk}"]')).to_have_class('package-card addon-selector selected')

                # A date that became unavailable falls back to the calendar and keeps the estimate.
                go(reverse('booking_page') + f'?from=estimate&package_id={package.pk}&addon_id={arch.pk}&event_date={blocked.isoformat()}')
                expect(page.locator('#bookingModalOverlay')).to_be_hidden()
                choose_booking_date(day)
                expect(page.locator(f'.addon-selector[data-id="{arch.pk}"]')).to_have_class('package-card addon-selector selected')

                go(reverse('services'))
                expect(first).not_to_be_checked()
                expect(page.locator('#estimatorPackage')).to_have_value('')
                expect(page.locator('#estimatorTotal')).to_be_hidden()
                # The exact Step 3 calendar marks blocked/full dates.
                page.locator('#availabilityDate').evaluate('(el, value) => el.value = value', day.isoformat())
                page.locator('#availabilityDate').click()
                expect(page.locator('.booking-picker-pop')).to_be_visible()
                for _ in range(2):
                    if page.locator('.booking-picker-title').inner_text() == day.strftime('%B %Y'):
                        break
                    page.locator('.booking-picker-nav').last.click()
                expect(page.locator('.booking-picker-day.is-blocked')).to_have_count(1)
                expect(page.locator('.booking-picker-day.is-full')).to_have_count(1)
                self.assertTrue(page.locator('.booking-picker-day.is-blocked').is_disabled())
                self.assertTrue(page.locator('.booking-picker-day.is-full').is_disabled())
                shot('calendar', '#date-check')
                page.locator('#availabilityDate').click()
                page.locator('#availabilityDate').evaluate('(el, value) => { el.value = value; el.dispatchEvent(new Event("change", {bubbles:true})); }', blocked.isoformat())
                page.locator('#availabilityCheck').click()
                expect(page.locator('#availabilityResult')).to_contain_text('Choose another date')
                expect(page.locator('.availability-suggestions button')).to_have_count(3)
                expect(page.locator('#availabilityResult a')).to_have_count(0)
                shot('unavailable', '#availabilityResult')
                page.locator('#availabilityDate').evaluate('(el, value) => { el.value = value; el.dispatchEvent(new Event("change", {bubbles:true})); }', day.isoformat())
                page.locator('#availabilityCheck').click()
                expect(page.locator('#availabilityResult')).to_contain_text('Time slots available')
                shot('availability', '#availabilityResult')
                link = page.locator('#availabilityResult a').get_attribute('href')
                self.assertIn('event_date=' + day.isoformat(), link)
                page.get_by_role('button', name='Clear selected date', exact=True).click()
                expect(page.locator('#availabilityDate')).to_have_value('')
                expect(page.locator('#availabilityResult')).to_be_hidden()
                context.clear_cookies()
                go(link)
                login()
                expect(page.locator('#event_date')).to_have_value(day.isoformat())

                # Guest AI login returns to the quiz, then Other values and image download work.
                context.clear_cookies()
                go(reverse('services'))
                page.locator('#style-quiz a').click()
                page.locator('#email').fill(user.email)
                page.locator('#password').fill('ServicePassword!23')
                page.locator('#loginForm button[type="submit"]').click()
                page.wait_for_url('**/services/#style-quiz')
                page.locator('#quizSubmit').click()
                expect(page.locator('#quizResult')).to_contain_text('A little more detail')
                shot('quiz-validation', '#quizResult')
                page.locator('.custom-select-container:has(#quizEventType) .custom-select-trigger').click()
                shot('dropdown', '#style-quiz')
                page.locator('.custom-select-container:has(#quizEventType) .custom-select-trigger').click()
                choose('quizEventType', 'Other')
                expect(page.locator('#quizEventTypeOther')).to_be_visible()
                page.locator('#quizEventTypeOther').fill('Graduation')
                choose('quizVibe', 'Other')
                page.locator('#quizVibeOther').fill('Garden party')
                page.locator('#quizColors').fill('Pink, Gold, White')
                # A login interruption resumes this form once, without making normal visits sticky.
                context.clear_cookies()
                context.route('**/services/theme-quiz/', lambda route: route.fulfill(status=403,
                    content_type='application/json', body=json.dumps({'success': False, 'error': 'Please log in to get AI style suggestions.'})))
                page.locator('#quizSubmit').click()
                page.get_by_role('link', name='Log In and Continue', exact=True).click()
                login('**/services/#style-quiz')
                expect(page.locator('#quizEventTypeOther')).to_have_value('Graduation')
                expect(page.locator('#quizVibeOther')).to_have_value('Garden party')
                expect(page.locator('#quizColors')).to_have_value('Pink, Gold, White')
                self.assertIsNone(page.evaluate('sessionStorage.getItem("balloorina.service-quiz-resume")'))
                payloads = []
                def theme(route):
                    payloads.append(route.request.post_data_json)
                    route.fulfill(content_type='application/json', body=json.dumps({'success': True, 'response':
                        '**Garden Glow**\n\nA garden celebration in pink and gold.\n'
                        '<img src="/media/ai_generated/service-test.png" onerror="alert(1)">'}))
                context.route('**/services/theme-quiz/', theme)
                page.locator('#quizSubmit').click()
                expect(page.locator('.quiz-image-download')).to_be_visible()
                expect(page.locator('.quiz-image-download')).to_have_text('')
                expect(page.get_by_role('button', name='Download theme image')).to_be_visible()
                self.assertEqual(payloads[-1]['event_type'], 'Graduation')
                self.assertEqual(payloads[-1]['vibe'], 'Garden party')
                expect(page.locator('#quizResult strong')).to_contain_text(['Your AI Theme Suggestion', 'Garden Glow'])
                self.assertIsNone(page.locator('.quiz-image img').get_attribute('onerror'))
                with page.expect_download() as download:
                    page.locator('.quiz-image-download').click()
                self.assertEqual(download.value.suggested_filename, 'balloorina-theme-1.png')
                shot('quiz-theme', '#quizResult')
                # Expired session between generating and booking still retains the AI draft.
                context.clear_cookies()
                page.locator('#quizResult a').click()
                login(opens_form=False)
                choose_booking_date(day)
                expect(page.locator('#bookingModalOverlay')).to_be_visible()
                expect(page.locator('#event_type_other')).to_have_value('Graduation')
                expect(page.locator('#design_theme_input')).to_have_value('Garden party')
                expect(page.locator('#color_palette_input')).to_have_value('Pink, Gold, White')
                expect(page.locator('#booking_special_requests')).to_have_value(re.compile('Garden Glow'))
                page.wait_for_function('document.getElementById("booking_reference_images").files.length === 1')
                self.assertIsNone(page.evaluate('sessionStorage.getItem("balloorina.service-ai-booking")'))
                go(reverse('services'))
                expect(page.locator('#quizEventType')).to_have_value('')
                expect(page.locator('#quizColors')).to_have_value('')
                choose('quizEventType', 'Other')
                page.locator('#quizEventTypeOther').fill('Graduation')
                page.get_by_role('button', name='Clear AI style form', exact=True).click()
                expect(page.locator('#quizEventType')).to_have_value('')
                expect(page.locator('#quizEventTypeOther')).to_be_hidden()
                expect(page.locator('#quizResult')).to_be_hidden()
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()
