"""Real request-mode review checks. Enable RUN_BOOKING_CHANGE_REVIEW_BROWSER=1."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .test_booking_change_feedback import feedback_booking
from .test_booking_preview import _preview_upload
from .models import AddOn, AdditionalOnly, BookingChangeRequest, BookingImage, Design, Package, Payment


@skipUnless(os.environ.get('RUN_BOOKING_CHANGE_REVIEW_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies',
                   SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, SECURE_SSL_REDIRECT=False,
                   REQUEST_RATE_LIMITING_ENABLED=False)
class BookingChangeReviewBrowserTests(StaticLiveServerTestCase):
    def test_pending_edits_show_added_changed_and_previous_without_request_mode(self):
        from playwright.sync_api import expect, sync_playwright
        user, booking, payment = feedback_booking()
        booking.status = 'pending'
        booking.save()
        payment.delete()
        Package.objects.create(name='Package Upgrade', price=12000)
        AddOn.objects.create(name='New Entrance', price=2000, solo_price=3000)
        custom = type(booking).objects.get(pk=booking.pk)
        custom.pk = None
        custom.package_type = 'My Design'
        custom.fee_policy_snapshot['catalog_items'] = [{'label':'My Design','amount':'9000.00'}]
        custom.save()
        Design.objects.create(booking=custom, image=_preview_upload('pending-design.png'), style='Custom', color_palette='Pink', price_estimate=9000)
        self.client.force_login(user)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context()
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + '/') else route.abort())
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            try:
                endpoint = self.live_server_url + reverse('edit_booking', args=[booking.pk]) + '?review_original=1'
                baseline = context.request.get(endpoint, headers={'X-Requested-With':'XMLHttpRequest'}).json()
                held = []
                page.route(endpoint, lambda route: held.append(route))
                page.goto(self.live_server_url + reverse('customer_profile'), wait_until='networkidle')
                with page.expect_request(endpoint):
                    page.evaluate('(id) => {window.pendingOpeningA=window.openEditModal(id);}', booking.pk)
                page.evaluate('(id) => {window.openEditModal(id);}', custom.pk)
                expect(page.locator('#editBookingForm')).to_have_attribute('action', reverse('edit_booking', args=[custom.pk]))
                held[0].fulfill(json=baseline)
                page.evaluate('() => window.pendingOpeningA')
                expect(page.locator('#editBookingForm')).to_have_attribute('action', reverse('edit_booking', args=[custom.pk]))
                page.unroute(endpoint)
                page.locator('#editBookingModal .close-btn').click()
                page.evaluate('(id) => {window.openEditModal(id);}', booking.pk)
                expect(page.locator('#editBookingModal')).to_be_visible()
                expect(page.locator('#editBookingForm')).to_have_attribute('action', reverse('edit_booking', args=[booking.pk]))
                page.locator('#btnNextEditToSummary').click()
                page.locator('.edit-package-card[data-package="Package Upgrade"] .package-info').click()
                page.locator('.edit-addon-selector[data-name="New Entrance"] .package-info').click()
                page.locator('#btnNextEditStep').click()
                page.locator('#edit_motto_text').fill('New pending message')
                page.locator('#btnNextEditDesignToReview').click()
                summary = page.locator('#edit-booking-item-list')
                expect(summary.locator('.change-review-badge')).to_have_text(['Changed', 'Added'])
                expect(summary).to_contain_text('Previously: Package 2 — ₱9,000.00')
                expect(summary).not_to_contain_text('Previously: None')
                expect(page.locator('#edit-booking-details-list')).to_contain_text('Previously: Happy Birthday')
                expect(page.locator('#editChangePaymentSummary')).not_to_be_visible()
                expect(page.locator('#changeRequestBanner')).not_to_be_visible()
                submit = page.get_by_role('button', name='Update Booking', exact=True)
                expect(submit).to_be_enabled()
                submit.click()
                dialog = page.locator('dialog.client-feedback-dialog')
                expect(dialog.get_by_role('heading')).to_have_text('Save your booking changes?')
                expect(dialog).to_contain_text('Please check your updated details. Your booking will remain pending for review.')
                dialog.get_by_role('button', name='Review Again', exact=True).click()
                expect(page.locator('#editBookingModal')).to_be_visible()
                submit.click()
                dialog.get_by_role('button', name='Save Changes', exact=True).click()
                expect(page.locator('#editBookingModal')).not_to_be_visible()
                page.goto(self.live_server_url + reverse('customer_profile') + f'?open_edit={custom.pk}', wait_until='networkidle')
                page.locator('#btnNextEditToSummary').click()
                page.locator('#edit_motto_text').fill('Updated custom message')
                page.locator('#btnNextEditDesignToReview').click()
                expect(page.locator('#edit_price_display')).to_have_text('₱10,000.00')
                expect(summary).to_contain_text('My Design')
                page.get_by_role('button', name='Update Booking', exact=True).click()
                page.locator('dialog.client-feedback-dialog').get_by_role('button', name='Save Changes', exact=True).click()
                expect(page.locator('#editBookingModal')).not_to_be_visible()
            finally:
                context.close()
                browser.close()
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'pending')
        self.assertEqual(booking.package_type, 'Package Upgrade + New Entrance')
        self.assertEqual(booking.motto_text, 'New pending message')
        self.assertFalse(BookingChangeRequest.objects.exists())
        custom.refresh_from_db()
        self.assertEqual(custom.total_price, 10000)
        self.assertEqual(custom.motto_text, 'Updated custom message')

    def test_replaced_extras_show_the_previous_item_from_the_same_role(self):
        from playwright.sync_api import expect, sync_playwright
        from .views.common import capture_booking_fee_policy
        user, booking, payment = feedback_booking()
        AddOn.objects.create(name='Old Entrance', price=2000, solo_price=3000)
        AddOn.objects.create(name='New Entrance', price=3000, solo_price=4000)
        AdditionalOnly.objects.create(name='Old Stand', price=1000)
        AdditionalOnly.objects.create(name='New Stand', price=1500)
        Package.objects.create(name='Package Upgrade', price=12000)
        booking.package_type = 'Package 2 + Old Entrance + Old Stand'
        booking.total_price = 13000
        capture_booking_fee_policy(booking)
        booking.save()
        payment.amount = 5000
        payment.save()
        self.client.force_login(user)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + '/') else route.abort())
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            try:
                page.goto(self.live_server_url + reverse('customer_profile'), wait_until='networkidle')
                page.get_by_role('button', name='Request Changes', exact=True).click()
                dialog = page.locator('dialog.client-feedback-dialog')
                dialog.get_by_role('textbox').fill('Please replace our package and selected extras.')
                dialog.get_by_role('button', name='Continue to Changes').click()
                page.locator('#btnNextEditToSummary').click()
                page.locator('.edit-package-card[data-package="Package Upgrade"] .package-info').click()
                page.locator('.edit-addon-selector[data-name="New Entrance"] .package-info').click()
                page.locator('.edit-additional-selector[data-name="New Stand"] .package-info').click()
                page.locator('#btnNextEditStep').click()
                page.locator('#btnNextEditDesignToReview').click()
                summary = page.locator('#edit-booking-item-list')
                expect(summary.locator('.change-review-before')).to_have_text([
                    'Previously: Package 2 — ₱9,000.00',
                    'Previously: Old Entrance (Add-on) — ₱2,000.00',
                    'Previously: Old Stand (Additional) — ₱1,000.00'])
                expect(summary.locator('.row-value')).to_have_text(['₱12,000.00', '₱3,000.00', '₱1,500.00'])
                expect(summary.locator('.summary-row')).to_have_count(3)
                page.locator('#btnPrevEditToDetails').click()
                page.locator('#btnPrevFromEditDesign').click()
                page.locator('.edit-addon-selector[data-name="Old Entrance"] .package-info').click()
                page.locator('.edit-additional-selector[data-name="Old Stand"] .package-info').click()
                page.locator('#btnNextEditStep').click()
                page.locator('#btnNextEditDesignToReview').click()
                expect(summary.locator('.change-review-before')).to_have_text(['Previously: Package 2 — ₱9,000.00'])
            finally:
                context.close()
                browser.close()

    def test_pinned_review_map_in_create_edit_and_change_request(self):
        from urllib.request import urlopen
        from playwright.sync_api import expect, sync_playwright
        user, booking, payment = feedback_booking()
        booking.logistics_fee_override = 1500
        booking.total_price = 10500
        booking.save()
        payment.amount = 10500
        payment.save()
        pending = type(booking).objects.get(pk=booking.pk)
        pending.pk = None
        pending.status = 'pending'
        pending.save()
        self.client.force_login(user)
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check/review-map'
        artifacts.mkdir(parents=True, exist_ok=True)
        # Use the application's actual Leaflet version; cache assets for offline reruns.
        for filename in ('leaflet.js', 'leaflet.css'):
            cached = artifacts / filename
            if not cached.exists():
                cached.write_bytes(urlopen('https://unpkg.com/leaflet@1.9.4/dist/' + filename, timeout=30).read())
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + '/') else route.abort())
            context.route('**/leaflet@1.9.4/dist/leaflet.js', lambda route: route.fulfill(content_type='application/javascript', body=(artifacts / 'leaflet.js').read_bytes()))
            context.route('**/leaflet@1.9.4/dist/leaflet.css', lambda route: route.fulfill(content_type='text/css', body=(artifacts / 'leaflet.css').read_bytes()))
            context.route('**/MapServer/tile/**', lambda route: route.fulfill(content_type='image/png', body=_preview_upload().read()))
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            page.set_default_timeout(10000)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                for mode in ('create', 'edit', 'request'):
                    edit = mode != 'create'
                    prefix = 'edit_' if edit else ''
                    if mode == 'create':
                        page.goto(self.live_server_url + reverse('booking_page') + '?from=estimate&event_date=2099-07-17', wait_until='networkidle')
                        page.locator('#eventTypeCustomSelect .custom-select-trigger').click()
                        page.locator('#eventTypeCustomSelect [data-value="Birthday"]').click()
                    elif mode == 'edit':
                        page.goto(self.live_server_url + reverse('customer_profile') + f'?open_edit={pending.pk}', wait_until='networkidle')
                    else:
                        page.locator('#editBookingModal .close-btn').click()
                        page.get_by_role('button', name='Request Changes', exact=True).click()
                        dialog = page.locator('dialog.client-feedback-dialog')
                        dialog.get_by_role('textbox').fill('We need a longer event and a different venue pin.')
                        dialog.get_by_role('button', name='Continue to Changes').click()
                    if not edit:
                        page.locator('#event_location').fill('Molino Bacoor Cavite venue')
                    page.evaluate('''prefix => {
                        if (!prefix) {
                            const date = document.getElementById('event_date');date.value='2099-07-17';
                            date.dispatchEvent(new Event('change',{bubbles:true}));
                        }
                        for (const [name, value] of Object.entries({start_time:'07:00',end_time:'12:00',event_lat_input:'14.415',event_lng_input:'120.983'})) {
                            const input=document.getElementById(prefix+name);input.value=value;
                            input.dispatchEvent(new Event('change',{bubbles:true}));
                        }
                    }''', prefix)
                    overtime = page.locator('#' + prefix + 'overtime_notice')
                    expect(overtime).to_be_visible()
                    expect(overtime).to_contain_text('2 started hours')
                    expect(page.locator('#' + prefix + 'overtime_notice_amount')).to_have_text('+₱1,000.00')
                    for width, theme in ((1440, 'light'), (390, 'dark')):
                        page.set_viewport_size({'width': width, 'height': 1000})
                        page.evaluate('theme => document.documentElement.dataset.theme=theme', theme)
                        neutral = overtime.evaluate('''el => {
                            const rgb=getComputedStyle(el).backgroundColor.match(/[0-9.]+/g).slice(0,3).map(Number);
                            return Math.max(...rgb)-Math.min(...rgb)<20 && el.scrollWidth<=el.clientWidth+1;
                        }''')
                        self.assertTrue(neutral)
                        self.assertLess(overtime.bounding_box()['height'], 85)
                        overtime.scroll_into_view_if_needed()
                        page.screenshot(path=str(artifacts / f'{mode}-overtime-{width}-{theme}.png'))
                    page.locator('#btnNextEditToSummary' if edit else '#btnNextToSummary').click()
                    expect(page.locator('#edit-step-2' if edit else '#step-2')).to_be_visible()
                    if not edit:
                        page.locator('.package-card[data-package="Package 2"] .package-info').click()
                    page.locator('#btnNextEditStep' if edit else '#btnNextStep').click()
                    if not edit:
                        page.locator('#designThemeChips [data-value="Princess"]').click()
                        page.locator('#designPaletteSwatches [data-color="Pink"]').click()
                    page.locator('#btnNextEditDesignToReview' if edit else '#btnNextDesignToReview').click()
                    map_id = 'edit_booking_review_map' if edit else 'booking_review_map'
                    map_element = page.locator('#' + map_id)
                    expect(map_element).to_be_visible()
                    expect(map_element.locator('.map-pin-dot')).to_have_count(1)
                    marker = map_element.evaluate('el => {const p=el.__bookingMapCtx.marker.getLatLng();return [p.lat,p.lng];}')
                    self.assertEqual(marker, [14.415, 120.983])
                    self.assertFalse(map_element.evaluate('el => el.__bookingMapCtx.map.dragging.enabled()'))
                    if mode == 'request':
                        expect(page.locator('#editServiceChargeRow .change-review-badge')).to_have_text('Changed')
                        expect(page.locator('#editOvertimeRow .change-review-badge')).to_have_text('Changed')
                        expect(page.locator('#editServiceChargeRow')).to_contain_text('Previously: ₱1,500.00')
                    # Reuse the same map when returning to review, with the latest coordinates.
                    page.locator('#btnPrevEditToDetails' if edit else '#btnBackToDetails').click()
                    page.evaluate('prefix => {const input=document.getElementById(prefix+"event_lat_input");input.value="14.416";input.dispatchEvent(new Event("change",{bubbles:true}));}', prefix)
                    page.locator('#btnNextEditDesignToReview' if edit else '#btnNextDesignToReview').click()
                    expect(map_element).to_be_visible()
                    self.assertEqual(map_element.evaluate('el => el.__bookingMapCtx.marker.getLatLng().lat'), 14.416)
                    for width, theme in ((1440, 'light'), (390, 'dark')):
                        page.set_viewport_size({'width': width, 'height': 1000})
                        page.evaluate('theme => document.documentElement.dataset.theme=theme', theme)
                        map_element.scroll_into_view_if_needed()
                        page.screenshot(path=str(artifacts / f'{mode}-map-{width}-{theme}.png'))
                    # An empty pin must never keep displaying the previous venue marker.
                    if mode == 'create':
                        page.evaluate('''() => {
                            document.getElementById('event_lat_input').value='';
                            document.getElementById('event_lng_input').value='';
                            document.getElementById('btnNextDesignToReview').click();
                        }''')
                        expect(map_element).not_to_be_visible()
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()

    def test_partial_paid_upgrade_review_and_revert(self):
        from playwright.sync_api import expect, sync_playwright
        user, booking, payment = feedback_booking()
        payment.amount = 5000
        payment.save()
        original_image = BookingImage.objects.create(booking=booking, image=_preview_upload('original.png'))
        Package.objects.create(name='Package Upgrade', price=12000)
        AddOn.objects.create(name='New Entrance', price=2000, solo_price=3000)
        AdditionalOnly.objects.create(name='New Stand', price=500)
        self.client.force_login(user)
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check/request-review-refinement'
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + '/') else route.abort())
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            page.set_default_timeout(10000)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(self.live_server_url + reverse('customer_profile'), wait_until='networkidle')
                page.get_by_role('button', name='Request Changes', exact=True).click()
                dialog = page.locator('dialog.client-feedback-dialog')
                dialog.get_by_role('textbox').fill('We need to upgrade the event package.')
                dialog.get_by_role('button', name='Continue to Changes').click()
                page.locator('#btnNextEditToSummary').click()
                page.locator('.edit-package-card[data-package="Package Upgrade"] .package-info').click()
                page.locator('#btnNextEditStep').click()
                page.locator('#btnNextEditDesignToReview').click()
                expect(page.locator('#editChangePaymentSummary')).to_be_visible()
                expect(page.locator('[data-review-money="verified_paid"]')).to_have_text('₱5,000.00')
                expect(page.locator('[data-review-money="remaining"]')).to_have_text('₱8,000.00')
                expect(page.locator('#editChangePaymentNote')).to_contain_text('₱3,000.00 for this change')
                expect(page.locator('#editChangePaymentNote')).to_contain_text('₱5,000.00 booking balance')
                details = page.locator('#edit-booking-details-list')
                expect(details).to_contain_text('Package 2')
                expect(details).to_contain_text('Package Upgrade')
                expect(details.locator('.change-review-badge')).to_have_count(1)
                # Preserve the original icon/label/value rows without callout decoration.
                expect(details.locator('.summary-row .row-label .form-icon').first).to_be_visible()
                alignment = details.locator('.summary-row').first.evaluate('''el => {
                    const label = el.querySelector('.row-label').getBoundingClientRect();
                    const value = el.querySelector('.row-value').getBoundingClientRect();
                    const badge = el.querySelector('.change-review-badge').getBoundingClientRect();
                    return {left: Math.abs(label.left-value.left),
                        badge: Math.abs(label.top+label.height/2-badge.top-badge.height/2)};
                }''')
                self.assertLess(alignment['left'], 2)
                self.assertLess(alignment['badge'], 4)
                expect(details.locator('.summary-row').first).to_have_css('border-left-width', '0px')
                expect(details.locator('.summary-row').first).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
                summary = page.locator('#edit-booking-item-list')
                expect(summary).to_contain_text('Package Upgrade')
                expect(summary.locator('.change-review-before')).to_have_text('Previously: Package 2 — ₱9,000.00')
                expect(summary.locator('.summary-row')).to_have_count(1)
                expect(summary.locator('.change-review-badge')).to_have_text(['Changed'])
                expect(summary.locator('.row-value')).to_have_text(['₱12,000.00'])
                total_alignment = page.locator('#editChangeTotals').evaluate('''el => {
                    const label=el.querySelector('.row-label').getBoundingClientRect();
                    const amount=el.querySelector('.row-value').getBoundingClientRect();
                    const delta=document.getElementById('editChangePriceDifference').getBoundingClientRect();
                    return {amount:Math.abs(label.top-amount.top),delta:delta.top-el.getBoundingClientRect().bottom};
                }''')
                self.assertLess(total_alignment['amount'], 3)
                self.assertGreaterEqual(total_alignment['delta'], -1)
                expect(page.get_by_role('heading', name='Payment Breakdown', exact=True)).to_have_count(0)
                self.assertLess(len(page.locator('#editChangePaymentSummary').inner_text().split()), 55)
                expect(page.locator('#editBookingForm button[type="submit"]')).to_be_enabled()
                for width, theme in ((1440, 'light'), (390, 'light'), (390, 'dark'), (1440, 'dark')):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    page.evaluate('theme => document.documentElement.dataset.theme=theme', theme)
                    page.locator('#editChangePaymentSummary').scroll_into_view_if_needed()
                    page.screenshot(path=str(artifacts / f'payment-{width}-{theme}.png'))
                    page.locator('#edit-step-4 h3').scroll_into_view_if_needed()
                    page.screenshot(path=str(artifacts / f'review-{width}-{theme}.png'))
                    self.assertTrue(page.locator('#edit-step-4').evaluate('el => el.scrollWidth <= el.clientWidth + 1'))
                page.locator('#btnPrevEditToDetails').click()
                page.locator('#btnPrevFromEditDesign').click()
                page.locator('.edit-addon-selector[data-name="New Entrance"] .package-info').click()
                page.locator('.edit-additional-selector[data-name="New Stand"] .package-info').click()
                page.locator('#btnNextEditStep').click()
                page.locator('#btnNextEditDesignToReview').click()
                expect(summary.locator('.change-review-before')).to_have_text([
                    'Previously: Package 2 — ₱9,000.00'])
                expect(summary.locator('.change-review-badge')).to_have_text(['Changed', 'Added', 'Added'])
                expect(summary).not_to_contain_text('Previously: None')
                page.locator('#btnPrevEditToDetails').click()
                page.locator('#btnPrevFromEditDesign').click()
                page.locator('.edit-addon-selector[data-name="New Entrance"] .package-info').click()
                page.locator('.edit-additional-selector[data-name="New Stand"] .package-info').click()
                page.locator('.edit-package-card[data-package="Package 2"] .package-info').click()
                page.locator('#btnNextEditStep').click()
                page.locator('#btnNextEditDesignToReview').click()
                note=page.locator('#changeReviewNoChanges')
                expect(note).to_be_visible()
                expect(note).to_have_text('No changes yet. Go back and update at least one detail to submit your request.')
                expect(note.locator('i,svg')).to_have_count(0)
                toast=page.locator('.client-feedback-toast')
                expect(toast).to_contain_text('No changes yet')
                expect(toast).to_contain_text('Go back and update at least one detail to submit your request.')
                expect(page.locator('#changeReviewStatus')).to_have_text('')
                expect(page.locator('#editBookingForm button[type="submit"]')).to_be_disabled()
                submit=page.locator('#editBookingForm button[type="submit"]')
                for theme in ('light','dark'):
                    page.evaluate('theme=>document.documentElement.dataset.theme=theme',theme)
                    expect(submit).to_have_css('opacity','0.6')
                    expect(submit).to_have_css('cursor','not-allowed')
                    disabled_background=submit.evaluate('el=>getComputedStyle(el).backgroundColor')
                    submit.hover(force=True)
                    expect(submit).to_have_css('background-color',disabled_background)
                page.locator('#btnPrevEditToDetails').click()
                page.locator('#edit_motto_text').fill('')
                page.evaluate("""() => {
                    const latitude = document.getElementById('edit_event_lat_input');
                    latitude.value = '14.4141';
                    latitude.dispatchEvent(new Event('change', {bubbles:true}));
                    document.getElementById('edit_venue_landmark').value = 'Near the main gate';
                }""")
                page.locator('#editExistingImagesGrid [title="Remove image"]').click()
                page.locator('#edit_reference_images_ui').set_input_files({'name': 'new.png', 'mimeType': 'image/png', 'buffer': _preview_upload().read()})
                page.locator('#btnNextEditDesignToReview').click()
                expect(details).to_contain_text('Happy Birthday')
                expect(note).not_to_be_visible()
                expect(submit).to_be_enabled()
                expect(submit).not_to_have_css('opacity','0.6')
                expect(details).not_to_contain_text('Map pin updated')
                expect(details).not_to_contain_text('Previously: Pin saved')
                expect(page.locator('#editBookingReviewMapRow .row-label')).to_have_text('Map Pin Changed')
                expect(page.locator('#editBookingReviewMapRow .change-review-badge')).to_have_text('Changed')
                expect(page.locator('#edit-step-4')).not_to_contain_text('Venue Map')
                expect(details).to_contain_text('Near the main gate')
                expect(details.locator('.change-review-badge', has_text='Removed')).to_have_count(2)
                expect(details.locator('.change-review-badge', has_text='Added')).to_have_count(2)
                expect(details.locator('figcaption .change-review-badge')).to_have_count(0)
                expect(details.locator('.row-info .change-review-badge', has_text='Added')).to_have_count(2)
                expect(page.locator('[data-review-money="remaining"]')).to_have_text('₱5,000.00')
                # A failed refresh must hide old amounts and provide a working retry.
                endpoint = self.live_server_url + reverse('request_booking_change', args=[booking.pk])
                page.route(endpoint, lambda route: route.abort())
                page.locator('#btnPrevEditToDetails').click()
                page.locator('#btnNextEditDesignToReview').click()
                expect(page.locator('#changeReviewRetry')).to_be_visible()
                expect(page.locator('#changeReviewStatus')).to_have_text('Unable to check your changes. Please try again.')
                expect(page.locator('#editChangePaymentSummary')).not_to_be_visible()
                expect(page.locator('#editBookingForm button[type="submit"]')).to_be_disabled()
                page.unroute(endpoint)
                page.locator('#changeReviewRetry').click()
                expect(page.locator('#editChangePaymentSummary')).to_be_visible()
                # A received payment becoming pending while editing still blocks review.
                with ThreadPoolExecutor(max_workers=1) as database:
                    database.submit(lambda: Payment.objects.filter(pk=payment.pk).update(payment_status='pending')).result()
                    page.locator('#btnPrevEditToDetails').click()
                    page.locator('#btnNextEditDesignToReview').click()
                    expect(page.locator('#changeReviewStatus')).to_contain_text('still being verified')
                    expect(page.locator('#editBookingForm button[type="submit"]')).to_be_disabled()
                    database.submit(lambda: Payment.objects.filter(pk=payment.pk).update(payment_status='verified')).result()
                page.locator('#changeReviewRetry').click()
                expect(page.locator('#editBookingForm button[type="submit"]')).to_be_enabled()
                page.locator('#editBookingForm button[type="submit"]').click()
                dialog = page.locator('dialog.client-feedback-dialog')
                expect(dialog.get_by_role('heading')).to_have_text('Submit your change request?')
                expect(dialog).to_contain_text('Our team will review your changes and send a final quote. Your current booking stays unchanged until the changes are finalized.')
                dialog.get_by_role('button', name='Review Again', exact=True).click()
                expect(page.locator('#editBookingModal')).to_be_visible()
                page.locator('#editBookingForm button[type="submit"]').click()
                page.evaluate('''() => {const input=document.getElementById('edit_motto_text');input.value='Changed while confirming';input.dispatchEvent(new Event('input',{bubbles:true}));}''')
                dialog.get_by_role('button', name='Submit Request', exact=True).click()
                expect(page.locator('#editBookingModal')).to_be_visible()
                expect(page.locator('#editBookingForm [data-account-form-message]')).to_contain_text('Please review')
                page.locator('#btnPrevEditToDetails').click()
                page.locator('#edit_motto_text').fill('')
                page.locator('#btnNextEditDesignToReview').click()
                expect(page.locator('#editBookingForm button[type="submit"]')).to_be_enabled()
                page.locator('#editBookingForm button[type="submit"]').click()
                dialog.get_by_role('button', name='Submit Request', exact=True).click()
                expect(page.locator('#editBookingModal')).not_to_be_visible()
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()
        change = BookingChangeRequest.objects.get(booking=booking)
        self.assertEqual(change.proposed['motto_text'], '')
        self.assertEqual(change.proposed['_remove_images'], [str(original_image.pk)])
        self.assertEqual(change.images.count(), 1)
        booking.refresh_from_db()
        self.assertEqual(booking.motto_text, 'Happy Birthday')
        self.assertEqual(booking.images.count(), 1)

    def test_fresh_excess_acknowledgment_and_overpaid_upgrade(self):
        from playwright.sync_api import expect, sync_playwright
        user, booking, payment = feedback_booking()
        payment.amount = 5000
        payment.save()
        Package.objects.create(name='Package Upgrade', price=12000)
        self.client.force_login(user)
        with sync_playwright() as playwright, ThreadPoolExecutor(max_workers=1) as database:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context()
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + '/') else route.abort())
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            page.set_default_timeout(10000)
            try:
                page.goto(self.live_server_url + reverse('customer_profile'), wait_until='networkidle')
                page.get_by_role('button', name='Request Changes', exact=True).click()
                dialog = page.locator('dialog.client-feedback-dialog')
                dialog.get_by_role('textbox').fill('We want to revise the package selection.')
                dialog.get_by_role('button', name='Continue to Changes').click()
                page.locator('#btnNextEditToSummary').click()
                page.locator('.edit-package-card[data-package="Package 1-A"] .package-info').click()
                page.locator('#btnNextEditStep').click()
                database.submit(lambda: Payment.objects.filter(pk=payment.pk).update(amount=10000)).result()
                page.locator('#btnNextEditDesignToReview').click()
                expect(dialog.get_by_role('heading', name='Review your package change')).to_be_visible()
                expect(dialog).to_contain_text('₱2,000.00')
                dialog.get_by_role('button', name='Keep Current Selection').click()
                expect(page.locator('#editBookingForm button[type="submit"]')).to_be_disabled()
                page.locator('#changeReviewRetry').click()
                dialog.get_by_role('button', name='Continue with Changes').click()
                expect(page.locator('[data-review-money="remaining"]')).to_have_text('₱0.00')
                expect(page.locator('#editChangeExcess')).to_be_visible()
                expect(page.locator('[data-review-money="excess"]')).to_have_text('₱2,000.00')
                expect(page.locator('[data-review-money="verified_paid"]')).to_have_text('₱10,000.00')
                page.locator('#btnPrevEditToDetails').click()
                page.locator('#btnPrevFromEditDesign').click()
                page.locator('.edit-package-card[data-package="Package Upgrade"] .package-info').click()
                page.locator('#btnNextEditStep').click()
                database.submit(lambda: Payment.objects.filter(pk=payment.pk).update(amount=11000)).result()
                page.locator('#btnNextEditDesignToReview').click()
                expect(page.locator('#editChangePaymentNote')).to_contain_text('Team review required')
                expect(page.locator('#editChangePaymentNote')).not_to_contain_text('Includes')
                expect(page.locator('[data-review-money="remaining"]')).to_have_text('₱2,000.00')
                # An unpaid booking shows its full revised balance without a change top-up.
                database.submit(lambda: Payment.objects.filter(pk=payment.pk).update(amount=0)).result()
                page.locator('#btnPrevEditToDetails').click()
                page.locator('#btnNextEditDesignToReview').click()
                expect(page.locator('[data-review-money="verified_paid"]')).to_have_text('₱0.00')
                expect(page.locator('[data-review-money="remaining"]')).to_have_text('₱13,000.00')
                expect(page.locator('#editChangePaymentNote')).to_contain_text('Full amount unpaid')
            finally:
                context.close()
                browser.close()

    def test_custom_design_and_close_then_pending_edit(self):
        from playwright.sync_api import expect, sync_playwright
        user, booking, payment = feedback_booking()
        booking.package_type = 'My Design'
        booking.fee_policy_snapshot['catalog_items'] = [{'label': 'My Design', 'amount': '9000.00'}]
        booking.save()
        Design.objects.create(booking=booking, image=_preview_upload('design.png'), style='Custom', color_palette='Pink', price_estimate=9000)
        pending = type(booking).objects.get(pk=booking.pk)
        pending.pk = None
        pending.status = 'pending'
        pending.package_type = 'Package 2'
        pending.save()
        self.client.force_login(user)
        with sync_playwright() as playwright, ThreadPoolExecutor(max_workers=1) as database:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context()
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + '/') else route.abort())
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            page.set_default_timeout(10000)
            try:
                page.goto(self.live_server_url + reverse('customer_profile'), wait_until='networkidle')
                page.get_by_role('button', name='Request Changes', exact=True).click()
                dialog = page.locator('dialog.client-feedback-dialog')
                dialog.get_by_role('textbox').fill('Please change the message on our design.')
                dialog.get_by_role('button', name='Continue to Changes').click()
                page.locator('#btnNextEditToSummary').click()
                page.locator('#edit_motto_text').fill('Updated custom message')
                page.locator('#btnNextEditDesignToReview').click()
                expect(page.locator('#edit-booking-details-list')).to_contain_text('Custom Design')
                expect(page.locator('#edit-booking-details-list img')).to_have_count(1)
                expect(page.locator('#edit_price_display')).to_have_text('₱10,000.00')
                expect(page.locator('#editBookingForm button[type="submit"]')).to_be_enabled()
                page.locator('#editBookingModal .close-btn').click()
                expect(page.locator('#editBookingModal')).not_to_be_visible()
                # A normal pending edit must regain its original markup and enabled controls.
                page.get_by_role('link', name='Edit Booking', exact=True).click()
                page.locator('#btnNextEditToSummary').click()
                page.locator('#btnNextEditStep').click()
                page.locator('#btnNextEditDesignToReview').click()
                expect(page.locator('#edit-step-4')).to_be_visible()
                expect(page.locator('#editChangePaymentSummary')).not_to_be_visible()
                expect(page.locator('#editOvertimeRow')).to_be_visible()
                expect(page.locator('#editBookingForm button[type="submit"]')).to_be_enabled()
                expect(page.locator('#editReviewTotalLabel')).to_have_text('Total Price')
            finally:
                context.close()
                browser.close()
