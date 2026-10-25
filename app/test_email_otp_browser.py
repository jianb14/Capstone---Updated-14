"""Opt-in, isolated browser check: RUN_EMAIL_OTP_BROWSER=1."""
import os
import re
from pathlib import Path
from tempfile import gettempdir
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core import mail
from django.test import override_settings
from django.urls import reverse

from .models import User


@skipUnless(os.environ.get('RUN_EMAIL_OTP_BROWSER') == '1', 'Optional OTP browser verification')
@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class EmailOTPBrowserTests(StaticLiveServerTestCase):
    def test_mobile_code_entry_countdown_errors_and_complete_recovery(self):
        from playwright.sync_api import sync_playwright, expect

        user = User.objects.create_user(username='otp-browser', email='browser@gmail.com',
                                        password='InitialPassword!123', role='customer')
        self.client.post(reverse('forgot_password'), {'email': user.email})
        code = re.search(r'(?m)^[0-9]{6}$', mail.outbox[-1].body).group()
        executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                context = browser.new_context(viewport={'width': 390, 'height': 844})
                # Keep this test offline while preserving the legacy reset page's toast interface.
                context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(
                    content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}})};'))
                context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                    'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + reverse('verify_password_otp'))
                expect(page.locator('input[name="code"]')).to_have_count(1)
                expect(page.locator('#otp-resend')).to_be_disabled()
                expect(page.locator('#otp-countdown')).to_contain_text('seconds')
                expect(page.locator('body')).to_contain_text('b***@gmail.com')
                for theme in ('light', 'dark'):
                    page.evaluate('(theme) => document.documentElement.setAttribute("data-theme", theme)', theme)
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
                    page.screenshot(path=str(Path(gettempdir()) / f'balloorina-otp-{theme}-mobile.png'),
                                    full_page=True, animations='disabled')
                page.reload()
                expect(page.locator('#otp-resend')).to_be_disabled()
                page.locator('#otp-code').fill('999999' if code != '999999' else '888888')
                page.get_by_role('button', name='Verify Code', exact=True).click()
                expect(page.get_by_role('alert')).to_contain_text('invalid, expired, or already used')
                page.locator('#otp-code').fill(code)
                page.get_by_role('button', name='Verify Code', exact=True).click()
                expect(page).to_have_url(self.live_server_url + reverse('reset_password_otp'))
                page.locator('#password').fill('BrowserUpdated!123')
                page.locator('#confirm_password').fill('BrowserUpdated!123')
                page.get_by_role('button', name='Update Password', exact=True).click()
                expect(page).to_have_url(self.live_server_url + reverse('login'))
                self.assertEqual(errors, [])
            finally:
                browser.close()
        user.refresh_from_db()
        self.assertTrue(user.check_password('BrowserUpdated!123'))
