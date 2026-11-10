"""Opt-in browser coverage for event-first booking and on-demand sample galleries."""
import json
import os
import re
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import AddOn, AdditionalOnly, CanvasAsset, CanvasCategory, Design, DesignOffer, DesignRequirement, Package, UserDesign
from .design_validation import asset_payload
from .test_booking_change_feedback import feedback_booking
from .test_booking_preview import _preview_upload


@skipUnless(os.environ.get('RUN_BOOKING_FOUR_STEP_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies',
                   SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
                   SECURE_SSL_REDIRECT=False, REQUEST_RATE_LIMITING_ENABLED=False)
class BookingFourStepBrowserTests(StaticLiveServerTestCase):
    def test_saved_design_keeps_its_fixed_offer_and_back_navigation(self):
        from playwright.sync_api import expect, sync_playwright

        user, booking, payment = feedback_booking()
        booking.status = 'pending'
        booking.save()
        payment.delete()
        package = Package.objects.get(name='Package 1-A')
        category = CanvasCategory.objects.create(name='Saved-design test panels')
        asset = CanvasAsset.objects.create(category=category, label='Panel', static_path='images/test-panel.svg')
        offer = DesignOffer.objects.create(kind='package', package=package, is_enabled=True)
        DesignRequirement.objects.create(offer=offer, category=category, minimum=1, required=True)
        payload = asset_payload(asset)
        saved = UserDesign.objects.create(user=user, name='Saved birthday setup', design_offer=offer,
            thumbnail=_preview_upload(), canvas_json=json.dumps({'objects': [{'type': 'image',
                'src': payload['src'], '_assetId': asset.pk, '_assetToken': payload['token'],
                '_assetSource': payload['src'], '_categoryId': category.pk, '_designSource': 'catalog'}]}))
        Design.objects.create(booking=booking, style='Saved setup', color_palette='Pink, Gold',
            image=_preview_upload(), price_estimate=9000)
        self.client.force_login(user)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(reduced_motion='reduce')
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + '/') else route.abort())
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(self.live_server_url + reverse('booking_page') + f'?design_id={saved.pk}', wait_until='networkidle')
                expect(page.locator('#step-1')).to_be_visible()
                page.locator('#eventTypeCustomSelect .custom-select-trigger').click()
                page.locator('#eventTypeCustomSelect [data-value="Birthday"]').click()
                page.evaluate('''() => {
                    for (const [id,value] of Object.entries({event_date:'2099-07-16',start_time:'07:00',end_time:'10:00'})) {
                        const el=document.getElementById(id);el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}));
                    }
                }''')
                page.locator('#event_location').fill('Molino Bacoor Cavite venue')
                page.locator('#btnNextToSummary').click()
                expect(page.locator('#step-3')).to_be_visible()
                expect(page.locator('#package_type_input')).to_have_value('Package 1-A')
                expect(page.locator('[name="user_design_id"]')).to_have_value(str(saved.pk))
                page.locator('#btnPrevFromDesign').click()
                expect(page.locator('#step-1')).to_be_visible()
                page.goto(self.live_server_url + reverse('customer_profile') + f'?open_edit={booking.pk}', wait_until='networkidle')
                expect(page.locator('#edit-step-1')).to_be_visible()
                page.locator('#btnNextEditToSummary').click()
                expect(page.locator('#edit-step-3')).to_be_visible()
                expect(page.locator('#edit_package_type_input')).to_have_value('Package 2')
                page.locator('#btnPrevFromEditDesign').click()
                expect(page.locator('#edit-step-1')).to_be_visible()
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()

    def test_create_and_edit_navigation_and_sample_gallery(self):
        from playwright.sync_api import expect, sync_playwright

        user, booking, payment = feedback_booking()
        booking.status = 'pending'
        booking.save()
        payment.delete()
        first = Package.objects.get(name='Package 1-A')
        first.preview_images.create(image=_preview_upload())
        first.preview_images.create(image=_preview_upload('second.png'))
        first.features = '\n'.join(f'Included styling item {i}' for i in range(20))
        first.save()
        AddOn.objects.create(name='Entrance Arch', price=2000, solo_price=3000)
        AdditionalOnly.objects.create(name='Welcome Stand', price=1000)
        self.client.force_login(user)
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check' / 'package-gallery'
        artifacts.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(reduced_motion='reduce')
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + '/') else route.abort())
            context.route('**/media/**', lambda route: route.fulfill(content_type='image/png', body=_preview_upload().read()))
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            page.set_default_timeout(6000)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                for edit in (False, True):
                    prefix = 'edit-' if edit else ''
                    modal = page.locator('#editBookingModal' if edit else '#bookingModalOverlay')
                    for width, theme in ((1440, 'light'), (390, 'dark'), (390, 'light'), (1440, 'dark'), (768, 'light'), (320, 'dark')):
                        page.set_viewport_size({'width': width, 'height': 844 if width <= 390 else 1000})
                        url = reverse('customer_profile') + f'?open_edit={booking.pk}' if edit else reverse('booking_page') + '?from=estimate&event_date=2099-07-16'
                        page.goto(self.live_server_url + url, wait_until='networkidle')
                        page.evaluate('theme => { document.documentElement.dataset.theme=theme; }', theme)
                        expect(modal).to_be_visible()
                        expect(modal.locator('.stepper-step-icon')).to_have_count(4)
                        self.assertEqual(modal.locator('.step-label').all_text_contents(),
                            ['Event Details', 'Select Package', 'Design Preferences', 'Review & Confirm'])
                        expect(modal.locator(f'#{prefix}step-1')).to_be_visible()
                        date_field = page.locator('#edit_event_date' if edit else '#event_date')
                        original_date = date_field.input_value()
                        date_field.evaluate("el => { el.value=''; el.dispatchEvent(new Event('change',{bubbles:true})); }")
                        hints = modal.locator('.booking-picker-timehint')
                        for hint in (hints.nth(0), hints.nth(1)):
                            expect(hint).to_have_text('Pick an event date first')
                            expect(hint).to_have_css('opacity', '1')
                            expect(hint).to_have_css('text-transform', 'none')
                            contrast = hint.evaluate('''el => {
                                const rgb = value => value.match(/[0-9.]+/g).map(Number);
                                const luminance = color => color.slice(0,3).map(value => {
                                    const s=value/255;return s<=.04045?s/12.92:((s+.055)/1.055)**2.4;
                                }).reduce((total,value,index)=>total+value*[.2126,.7152,.0722][index],0);
                                let parent=el, background;
                                while(parent) {
                                    const color=rgb(getComputedStyle(parent).backgroundColor);
                                    if(color.length===3 || color[3]===1){background=color;break;}
                                    parent=parent.parentElement;
                                }
                                const foreground=luminance(rgb(getComputedStyle(el).color));
                                const bg=luminance(background);
                                return (Math.max(foreground,bg)+.05)/(Math.min(foreground,bg)+.05);
                            }''')
                            self.assertGreaterEqual(contrast, 4.5)
                        if width in (1440, 390):
                            hints.nth(0).scroll_into_view_if_needed()
                            modal.screenshot(path=str(artifacts / f'{"edit" if edit else "create"}-{width}-{theme}-date-hints.png'), animations='disabled')
                        date_field.evaluate("(el,value) => { el.value=value; el.dispatchEvent(new Event('change',{bubbles:true})); }", original_date)
                        if not edit:
                            expect(hints.nth(1)).to_have_text('Pick a start time first')
                        details_next = page.locator('#btnNextEditToSummary' if edit else '#btnNextToSummary')
                        if not edit:
                            details_next.click()
                            expect(page.locator('#step-1')).to_be_visible()
                            expect(page.locator('#event_type_error')).not_to_be_empty()
                            page.locator('#eventTypeCustomSelect .custom-select-trigger').click()
                            page.locator('#eventTypeCustomSelect [data-value="Birthday"]').click()
                            # Fill native values and fire the same change events as the pickers.
                            page.evaluate('''() => {
                                for (const [id,value] of Object.entries({start_time:'07:00',end_time:'10:00',event_lat_input:'14.414',event_lng_input:'120.982'})) {
                                    const input=document.getElementById(id);input.value=value;input.dispatchEvent(new Event('change',{bubbles:true}));
                                }
                            }''')
                            page.locator('#event_location').fill('Molino Bacoor Cavite venue')
                        details_next.click()
                        expect(modal.locator(f'#{prefix}step-2')).to_be_visible()
                        expect(modal.locator(f'#{prefix}step-2-indicator')).to_have_class(re.compile(r'\bactive\b'))
                        card = modal.locator('.package-card[data-package="Package 1-A"]')
                        card_height = card.evaluate('el => el.getBoundingClientRect().height')
                        card.locator('.package-info').click()
                        expect(card).to_have_class(re.compile(r'\bselected\b'))
                        self.assertAlmostEqual(card.evaluate('el => el.getBoundingClientRect().height'), card_height, delta=1)
                        footer = card.locator('.package-card-actions')
                        preview_bounds = card.locator('.package-preview-toggle').bounding_box()
                        remove_bounds = card.locator('.package-remove-control').bounding_box()
                        self.assertLess(preview_bounds['x'] + preview_bounds['width'], remove_bounds['x'])
                        self.assertAlmostEqual(preview_bounds['y'] + preview_bounds['height']/2, remove_bounds['y'] + remove_bounds['height']/2, delta=1)
                        self.assertLessEqual(footer.evaluate('el => el.getBoundingClientRect().height'), 46)
                        self.assertEqual(card.locator('.package-preview-toggle').evaluate('el => getComputedStyle(el).fontSize'), card.locator('.package-remove-control').evaluate('el => getComputedStyle(el).fontSize'))
                        expect(modal.locator('.package-gallery')).to_be_hidden()
                        view = card.get_by_role('button', name='Sample setups for Package 1-A')
                        card.locator('.package-info').focus()
                        page.keyboard.press('Enter')
                        expect(card).to_have_class(re.compile(r'\bselected\b'))
                        expect(modal.locator('.package-gallery')).to_be_hidden()
                        view.scroll_into_view_if_needed()
                        scroll_top = modal.locator('.booking-modal-box').evaluate('el => el.scrollTop')
                        view.click()
                        gallery = modal.locator('.package-gallery')
                        expect(gallery).to_be_visible()
                        expect(modal.locator(f'#{prefix}step-2')).to_be_hidden()
                        expect(gallery.locator('h3')).to_have_text('Package 1-A')
                        expect(gallery.locator('.package-gallery-image')).to_have_js_property('naturalWidth', 4)
                        expect(gallery.locator('.package-gallery-count')).to_have_text('1 of 2')
                        gallery.get_by_role('button', name='Next image').click()
                        expect(gallery.locator('.package-gallery-count')).to_have_text('2 of 2')
                        page.keyboard.press('ArrowLeft')
                        expect(gallery.locator('.package-gallery-count')).to_have_text('1 of 2')
                        modal.screenshot(path=str(artifacts / f'{"edit" if edit else "create"}-{width}-{theme}-sample.png'), animations='disabled')
                        self.assertLessEqual(gallery.locator('.package-gallery-stage').evaluate('el => el.getBoundingClientRect().height'), 361)
                        self.assertLessEqual(modal.locator('.booking-modal-box').evaluate('el => el.scrollHeight - el.clientHeight'), 1)
                        page.keyboard.press('Escape')
                        expect(gallery).to_be_hidden()
                        expect(view).to_be_focused()
                        self.assertAlmostEqual(modal.locator('.booking-modal-box').evaluate('el => el.scrollTop'), scroll_top, delta=2)
                        expect(card).to_have_class(re.compile(r'\bselected\b'))
                        view.click()
                        gallery.locator('.package-gallery-image').evaluate("img => img.src='/missing-preview.png'")
                        expect(gallery.locator('.preview-item-empty')).to_be_visible()
                        gallery.get_by_role('button', name='Back to packages', exact=True).click()
                        other = modal.locator('.package-card[data-package="Package 2"]')
                        other.get_by_role('button', name='Sample setups for Package 2').click()
                        expect(gallery.locator('.preview-item-empty')).to_be_visible()
                        expect(card).to_have_class(re.compile(r'\bselected\b'))
                        expect(other).not_to_have_class(re.compile(r'\bselected\b'))
                        gallery.get_by_role('button', name='Select this package', exact=True).click()
                        expect(gallery).to_be_hidden()
                        expect(other).to_have_class(re.compile(r'\bselected\b'))
                        extra = modal.locator('.package-card[data-name="Welcome Stand"]')
                        extra.locator('.package-info').click()
                        expect(extra).to_have_class(re.compile(r'\bselected\b'))
                        expect(gallery).to_be_hidden()
                        extra.get_by_role('button', name='Sample setups for Welcome Stand').click()
                        gallery.get_by_role('button', name='Select this item', exact=True).click()
                        expect(extra).to_have_class(re.compile(r'\bselected\b'))
                        expect(gallery).to_be_hidden()
                        other.locator('.package-remove-control').click()
                        expect(other).not_to_have_class(re.compile(r'\bselected\b'))
                        expect(extra).to_have_class(re.compile(r'\bdisabled\b'))
                        arch = modal.locator('.package-card[data-name="Entrance Arch"]')
                        arch.locator('.package-info').click()
                        expect(arch).to_have_class(re.compile(r'\bselected\b'))
                        expect(other).to_have_class(re.compile(r'\bdisabled\b'))
                        arch.locator('.package-info').click()
                        expect(page.locator('#btnNextEditStep' if edit else '#btnNextStep')).to_be_disabled()
                        other.locator('.package-info').click()
                        extra.locator('.package-info').click()
                        page.locator('#btnNextEditStep' if edit else '#btnNextStep').click()
                        expect(modal.locator(f'#{prefix}step-3')).to_be_visible()
                        if not edit:
                            page.locator('#designThemeChips [data-value="Princess"]').click()
                            page.locator('#designPaletteSwatches [data-color="Pink"]').click()
                        page.locator('#btnNextEditDesignToReview' if edit else '#btnNextDesignToReview').click()
                        expect(modal.locator(f'#{prefix}step-4')).to_be_visible()
                        expect(page.locator('#edit_total_price_input' if edit else '#total_price_input')).to_have_value('11000.00')
                        expect(modal.locator(f'#{prefix}step-4')).to_contain_text('Welcome Stand')
                        page.locator('#btnPrevEditToDetails' if edit else '#btnBackToDetails').click()
                        page.locator('#btnPrevFromEditDesign' if edit else '#btnPrevFromDesign').click()
                        expect(modal.locator(f'#{prefix}step-2')).to_be_visible()
                        expect(other).to_have_class(re.compile(r'\bselected\b'))
                        page.locator('#btnEditPackagesBack' if edit else '#btnPackagesBack').click()
                        expect(modal.locator(f'#{prefix}step-1')).to_be_visible()
                        expect(page.locator('#edit_event_location' if edit else '#event_location')).to_have_value('Molino Bacoor Cavite venue')
                        details_next.click()
                        modal.screenshot(path=str(artifacts / f'{"edit" if edit else "create"}-{width}-{theme}.png'), animations='disabled')
                        self.assertFalse(modal.evaluate('el => el.scrollWidth > el.clientWidth'))
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()
