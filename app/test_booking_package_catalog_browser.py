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
