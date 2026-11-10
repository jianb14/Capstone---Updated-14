"""Opt-in: RUN_BOOKING_CHANGE_FEEDBACK_BROWSER=1."""
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .test_booking_change_feedback import feedback_booking
from .models import AddOn, AdditionalOnly, Booking, Payment


@skipUnless(os.environ.get('RUN_BOOKING_CHANGE_FEEDBACK_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies',
                   SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, SECURE_SSL_REDIRECT=False,
                   REQUEST_RATE_LIMITING_ENABLED=False)
class BookingChangeFeedbackBrowserTests(StaticLiveServerTestCase):
    def test_cancelled_extras_downgrades_keep_previous_selection(self):
        from playwright.sync_api import expect, sync_playwright

        user, booking, payment = feedback_booking()
        AddOn.objects.create(name='Entrance Arch', price=2000, solo_price=3000)
        AdditionalOnly.objects.create(name='Table Decor', price=1000)
        booking.package_type = 'Package 2 + Entrance Arch + Table Decor'
        booking.total_price = 13000
        booking.save()
        payment.amount = 13000
        payment.save()
        self.client.force_login(user)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(reduced_motion='reduce')
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + '/') else route.abort())
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            page.set_default_timeout(8000)
            try:
                page.goto(self.live_server_url + reverse('customer_profile'), wait_until='networkidle')
                page.get_by_role('button', name='Request Changes', exact=True).click()
                dialog = page.locator('dialog.client-feedback-dialog')
                dialog.get_by_role('textbox').fill('We need to adjust our package extras.')
                dialog.get_by_role('button', name='Continue to Changes').click()
                page.locator('#btnNextEditToSummary').click()
                for index, selector in enumerate(('.edit-addon-selector[data-name="Entrance Arch"]',
                                                  '.edit-additional-selector[data-name="Table Decor"]')):
                    selected = page.locator(selector)
                    expect(selected).to_have_class(re.compile(r'\bselected\b'))
                    selected.locator('.package-info').click()
                    expect(dialog.get_by_role('heading', name='Review your package change')).to_be_visible()
                    if index == 0:
                        page.keyboard.press('Escape')
                    else:
                        dialog.get_by_role('button', name='Keep Current Selection').click()
                    expect(selected).to_have_class(re.compile(r'\bselected\b'))
            finally:
                context.close()
                browser.close()

    def test_fresh_entry_check_downgrade_warning_and_no_excess_cases(self):
        from playwright.sync_api import expect, sync_playwright

        user, booking, payment = feedback_booking()
        self.client.force_login(user)
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check' / 'booking-change-feedback'
        artifacts.mkdir(exist_ok=True, parents=True)
        with ThreadPoolExecutor(max_workers=1) as database, sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + '/') else route.abort())
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            page.set_default_timeout(8000)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            wizard = page.locator('#editBookingModal')
            dialog = page.locator('dialog.client-feedback-dialog')

            def visit():
                page.goto(self.live_server_url + reverse('customer_profile'), wait_until='networkidle')

            def open_changes():
                page.get_by_role('button', name='Request Changes', exact=True).click()
                expect(dialog.get_by_role('heading', name='Request booking changes')).to_be_visible()
                dialog.get_by_role('textbox', name='Why are you requesting changes?').fill('We need a different package for our event.')
                dialog.get_by_role('button', name='Continue to Changes', exact=True).click()
                expect(wizard).to_have_class(re.compile(r'\bshow\b'))
                page.locator('#btnNextEditToSummary').click()

            try:
                visit()
                # The page was loaded when paid; a subsequent unverified proof must block entry.
                database.submit(lambda: Payment.objects.filter(pk=payment.pk).update(payment_status='pending')).result()
                page.get_by_role('button', name='Request Changes', exact=True).click()
                expect(page.locator('.client-feedback-toast')).to_contain_text('verification is complete')
                expect(dialog).to_have_count(0)
                expect(wizard).not_to_have_class(re.compile(r'\bshow\b'))
                page.screenshot(path=str(artifacts / 'blocked-before-form.png'))
                page.get_by_role('button', name='Dismiss notification').click()

                database.submit(lambda: Payment.objects.filter(pk=payment.pk).update(payment_status='verified')).result()
                open_changes()
                cheaper = wizard.locator('.edit-package-card[data-package="Package 1-A"]')
                original = wizard.locator('.edit-package-card[data-package="Package 2"]')
                cheaper.get_by_role('button', name='Sample setups for Package 1-A').click()
                gallery = wizard.locator('.package-gallery')
                expect(gallery).to_be_visible()
                expect(original).to_have_class(re.compile(r'\bselected\b'))
                gallery.get_by_role('button', name='Select this package', exact=True).click()
                expect(dialog.get_by_role('heading', name='Review your package change')).to_be_visible()
                expect(dialog).to_contain_text('2,000.00')
                expect(dialog).to_contain_text('estimate')
                for theme in ('light', 'dark'):
                    page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                    for width in (1440, 390):
                        page.set_viewport_size({'width': width, 'height': 900})
                        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                        page.screenshot(path=str(artifacts / f'downgrade-{theme}-{width}.png'))
                dialog.get_by_role('button', name='Keep Current Selection').click()
                expect(original).to_have_class(re.compile(r'\bselected\b'))
                expect(cheaper).not_to_have_class(re.compile(r'\bselected\b'))
                expect(gallery).to_be_visible()
                expect(gallery.locator('.package-gallery-select')).to_be_enabled()
                expect(gallery.locator('.package-gallery-select')).to_be_focused()
                gallery.get_by_role('button', name='Select this package', exact=True).click()
                dialog.get_by_role('button', name='Continue with Changes').click()
                expect(cheaper).to_have_class(re.compile(r'\bselected\b'))
                expect(gallery).to_be_hidden()
                page.locator('#btnNextEditStep').click()
                expect(page.locator('#edit-step-3')).to_be_visible()
                expect(dialog).to_have_count(0)
                self.assertEqual(database.submit(lambda: Booking.objects.get(pk=booking.pk).package_type).result(), 'Package 2')

                # A partial payment is below the revised total; there is no excess to warn about.
                database.submit(lambda: Payment.objects.filter(pk=payment.pk).update(amount=7500)).result()
                visit()
                open_changes()
                original.click()
                cheaper.click()
                expect(cheaper).to_have_class(re.compile(r'\bselected\b'))
                expect(dialog).to_have_count(0)

                # Direct pending edits do not run change-request financial warnings.
                database.submit(lambda: Booking.objects.filter(pk=booking.pk).update(status='pending')).result()
                visit()
                page.evaluate('(id) => window.openEditModal(id)', str(booking.pk))
                expect(wizard).to_have_class(re.compile(r'\bshow\b'))
                page.locator('#btnNextEditToSummary').click()
                cheaper.click()
                expect(dialog).to_have_count(0)
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()
