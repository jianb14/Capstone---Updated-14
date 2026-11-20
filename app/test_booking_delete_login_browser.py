"""Browser regression checks for booking deletion and admin login feedback."""
import os
from datetime import timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.utils import timezone

from .models import Booking, User


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies',
    SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, REQUEST_RATE_LIMITING_ENABLED=False)
class BookingDeleteLoginBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username='delete-feedback-customer',
            email='delete-feedback@example.com', password='Password!25', role='customer', email_verified=True)
        self.admin = User.objects.create_user(username='login-feedback-admin',
            email='login-admin@example.com', password='Password!25', role='admin', email_verified=True)
        self.booking = Booking.objects.create(user=self.customer,
            event_date=timezone.localdate() + timedelta(days=20), event_location='Bacoor', total_price=5000)
        self.artifacts = Path(settings.BASE_DIR) / '.booking-followup-check' / 'booking-delete-login'
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.cookies = {}
        for user in (self.customer, self.admin):
            self.client.force_login(user)
            self.cookies[user.pk] = self.client.cookies[settings.SESSION_COOKIE_NAME].value

    def context(self, browser, width=1440, theme='light', user=None):
        context = browser.new_context(viewport={'width': width, 'height': 960}, reduced_motion='reduce')
        context.route('**/*', lambda route: route.continue_()
            if route.request.url.startswith(self.live_server_url + '/') else route.abort())
        context.add_init_script('localStorage.setItem("balloorina-theme", "' + theme + '")')
        if user:
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.cookies[user.pk], 'url': self.live_server_url}])
        return context

    def test_booking_delete_matches_request_changes_with_red_button_and_cancel_never_posts(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            for width, theme in ((1440, 'light'), (1440, 'dark'), (390, 'light'), (390, 'dark')):
                context = self.context(browser, width, theme, self.customer)
                page = context.new_page(); posts = []; errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: posts.append(request.url)
                    if request.method == 'POST' and '/delete/' in request.url else None)
                page.goto(self.live_server_url + '/customer/', wait_until='domcontentloaded')
                page.evaluate('(id) => { window.promptBookingChangeReason(id); }', self.booking.pk)
                reference = page.locator('.client-feedback-dialog')
                expect(reference).to_be_visible()
                expected = reference.evaluate('''e => {
                    const s=getComputedStyle(e); return {width:s.width, radius:s.borderRadius, background:s.backgroundColor,
                        padding:s.padding, title:getComputedStyle(e.querySelector('h2')).fontSize,
                        body:getComputedStyle(e.querySelector('.client-feedback-message')).color};
                }''')
                page.keyboard.press('Escape')
                expect(reference).to_have_count(0)
                trigger = page.get_by_role('link', name='Delete Booking', exact=True)
                trigger.click()
                dialog = page.locator('#deleteBookingModal')
                expect(dialog).to_be_visible()
                actual = dialog.locator('.modal-card').evaluate('''e => {
                    const s=getComputedStyle(e); return {width:s.width, radius:s.borderRadius, background:s.backgroundColor,
                        padding:s.padding, title:getComputedStyle(e.querySelector('h2')).fontSize,
                        body:getComputedStyle(e.querySelector('#deleteBookingDescription')).color};
                }''')
                self.assertEqual(actual, expected)
                danger = dialog.get_by_role('button', name='Delete booking', exact=True)
                self.assertEqual(danger.evaluate('e => getComputedStyle(e).backgroundColor'), 'rgb(186, 60, 69)')
                self.assertEqual(danger.evaluate('e => getComputedStyle(e).color'), 'rgb(255, 255, 255)')
                card = dialog.locator('.modal-card').bounding_box()
                self.assertAlmostEqual(card['y'] + card['height'] / 2, 480, delta=2)
                expect(dialog.get_by_role('button', name='Cancel', exact=True)).to_be_focused()
                page.screenshot(path=str(self.artifacts / f'booking-delete-{theme}-{width}.png'))
                page.keyboard.press('Escape')
                expect(dialog).to_be_hidden(); expect(trigger).to_be_focused()
                trigger.click(); dialog.get_by_role('button', name='Cancel', exact=True).click()
                expect(dialog).to_be_hidden()
                self.assertEqual(posts, []); self.assertEqual(errors, [])
                context.close()
            browser.close()
        self.assertTrue(Booking.objects.filter(pk=self.booking.pk).exists())

    def test_confirmed_delete_posts_once_and_preserves_custom_feedback(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            context = self.context(browser, user=self.customer)
            page = context.new_page(); posts = []
            page.on('request', lambda request: posts.append(request.url)
                if request.method == 'POST' and '/delete/' in request.url else None)
            page.goto(self.live_server_url + '/customer/', wait_until='domcontentloaded')
            page.get_by_role('link', name='Delete Booking', exact=True).click()
            page.locator('#deleteBookingModal').get_by_role('button', name='Delete booking', exact=True).click()
            expect(page.locator('.client-feedback-toast')).to_contain_text('Booking deleted successfully!')
            self.assertEqual(len(posts), 1)
            context.close(); browser.close()
        self.assertFalse(Booking.objects.filter(pk=self.booking.pk).exists())

    def test_actual_admin_login_uses_custom_toast(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            for theme in ('light', 'dark'):
                context = self.context(browser, theme=theme)
                page = context.new_page(); errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + '/login/', wait_until='domcontentloaded')
                page.locator('#email').fill(self.admin.email)
                page.locator('#password').fill('Password!25')
                page.locator('#loginForm button[type="submit"]').click()
                expect(page).to_have_url(self.live_server_url + '/dashboard/')
                toast = page.locator('.client-feedback-toast')
                expect(toast).to_contain_text('Login successful! Welcome to the dashboard.')
                expect(toast).to_have_count(1)
                expect(page.locator('.swal2-container')).to_have_count(0)
                self.assertEqual(errors, [])
                page.screenshot(path=str(self.artifacts / f'admin-login-{theme}.png'))
                context.close()
            browser.close()
