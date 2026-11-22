"""Opt-in checks of theme visibility while changing booking selections."""
import os
from datetime import timedelta
from pathlib import Path
from tempfile import gettempdir
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import CanvasCategory, DesignOffer, DesignRequirement, Package
from .test_booking_change_feedback import feedback_booking


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies',
    SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, SECURE_SSL_REDIRECT=False,
    REQUEST_RATE_LIMITING_ENABLED=False)
class BookingThemeBrowserTests(StaticLiveServerTestCase):
    def test_create_edit_and_change_follow_package_inclusions(self):
        from playwright.sync_api import expect, sync_playwright

        user, booking, payment = feedback_booking()
        booking.status = 'pending'
        booking.save()
        payment.delete()
        change_booking = type(booking).objects.get(pk=booking.pk)
        change_booking.pk = None
        change_booking.status = 'confirmed'
        change_booking.event_date += timedelta(days=2)
        change_booking.event_end_date = change_booking.event_date
        change_booking.save()
        payment.booking = change_booking
        payment.save()
        theme, _ = CanvasCategory.objects.get_or_create(builtin_key='theme_decor', defaults={'name': 'Theme Decor'})
        DesignOffer.objects.create(kind='package', package=Package.objects.get(name='Package 1-A'))
        themed = DesignOffer.objects.create(kind='package', package=Package.objects.get(name='Package 2'))
        DesignRequirement.objects.create(offer=themed, category=theme)
        self.client.force_login(user)
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            context = browser.new_context(reduced_motion='reduce', viewport={'width': 1440, 'height': 1000})
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + '/') else route.abort())
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                for mode in ('create', 'edit', 'change'):
                    edit = mode != 'create'
                    edit_id = change_booking.pk if mode == 'change' else booking.pk
                    url = reverse('customer_profile') + f'?open_edit={edit_id}' if edit else reverse('booking_page') + '?from=estimate&event_date=2099-07-16'
                    page.goto(self.live_server_url + url, wait_until='networkidle')
                    if mode == 'change':
                        dialog = page.get_by_role('dialog')
                        dialog.locator('textarea').fill('Please change our package and decorations.')
                        dialog.get_by_role('button', name='Continue to Changes').click()
                    if not edit:
                        page.locator('#eventTypeCustomSelect .custom-select-trigger').click()
                        page.locator('#eventTypeCustomSelect [data-value="Birthday"]').click()
                        page.evaluate('''() => {
                            for (const [id,value] of Object.entries({event_date:'2099-07-16',start_time:'07:00',end_time:'10:00'})) {
                                const el=document.getElementById(id);el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}));
                            }
                        }''')
                        page.locator('#event_location').fill('Molino Bacoor Cavite venue')
                    page.locator('#btnNextEditToSummary' if edit else '#btnNextToSummary').click()
                    modal = page.locator('#editBookingModal' if edit else '#bookingModalOverlay')
                    chips = page.locator('#editDesignThemeChips' if edit else '#designThemeChips')
                    theme_input = page.locator('#edit_design_theme_input' if edit else '#design_theme_input')
                    next_package = page.locator('#btnNextEditStep' if edit else '#btnNextStep')
                    next_design = page.locator('#btnNextEditDesignToReview' if edit else '#btnNextDesignToReview')
                    back_package = page.locator('#btnPrevFromEditDesign' if edit else '#btnPrevFromDesign')
                    modal.locator('.package-card[data-package="Package 1-A"] .package-info').click()
                    if mode == 'change':
                        page.get_by_role('dialog').get_by_role('button', name='Continue with Changes').click()
                    next_package.click()
                    expect(chips).to_be_hidden()
                    expect(theme_input).to_have_value('')
                    palette = page.locator('#editDesignPaletteSwatches' if edit else '#designPaletteSwatches')
                    palette.locator('[data-color="Blue"]').click()
                    if mode != 'change':
                        next_design.click()
                        review = page.locator('#edit-step-4' if edit else '#step-4')
                        expect(review).to_be_visible()
                        theme_label = review.locator('.row-label').filter(has_text='Theme')
                        if edit:
                            # Preserve the existing review of a removed, previously booked theme.
                            expect(theme_label.locator('..')).to_contain_text('Removed')
                        else:
                            expect(theme_label).to_have_count(0)
                        page.locator('#btnPrevEditToDetails' if edit else '#btnBackToDetails').click()
                    back_package.click()
                    modal.locator('.package-card[data-package="Package 2"] .package-info').click()
                    next_package.click()
                    expect(chips).to_be_visible()
                    if chips.locator('.selected').count():
                        chips.locator('.selected').click()
                    next_design.click()
                    expect(page.locator('#edit_design_theme_error' if edit else '#design_theme_error')).to_contain_text('choose a theme')
                    chips.locator('[data-value="Princess"]').click()
                    expect(theme_input).to_have_value('Princess')
                    back_package.click()
                    modal.locator('.package-card[data-package="Package 1-A"] .package-info').click()
                    next_package.click()
                    expect(chips).to_be_hidden()
                    expect(theme_input).to_have_value('')
                    page.set_viewport_size({'width': 390, 'height': 844})
                    dismiss = page.get_by_role('button', name='Dismiss notification')
                    if dismiss.is_visible():
                        dismiss.click()
                    expect(dismiss).to_be_hidden(timeout=6000)
                    modal.screenshot(path=str(Path(gettempdir()) / f'booking-theme-{mode}.png'))
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 1)
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()
