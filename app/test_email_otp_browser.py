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
                expect(page.locator('.otp-digit')).to_have_count(6)
                expect(page.locator('#otp-submit')).to_be_disabled()
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
                page.locator('#otp-digit-1').fill('999999' if code != '999999' else '888888')
                page.get_by_role('button', name='Verify Code', exact=True).click()
                expect(page.get_by_role('alert')).to_contain_text('invalid, expired, or already used')
                page.locator('#otp-digit-3').evaluate('''(element, code) => {
                    const data = new DataTransfer(); data.setData('text/plain', code);
                    element.dispatchEvent(new ClipboardEvent('paste', {clipboardData: data, bubbles: true}));
                }''', code)
                for index, digit in enumerate(code, 1):
                    expect(page.locator('#otp-digit-' + str(index))).to_have_value(digit)
                page.locator('#otp-digit-6').press('Backspace')
                page.locator('#otp-digit-6').press('Backspace')
                expect(page.locator('#otp-digit-5')).to_be_focused()
                page.locator('#otp-digit-5').fill(code[4:])
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

    def test_mobile_signup_resume_real_email_change_and_verification(self):
        from playwright.sync_api import sync_playwright, expect
        user = User.objects.create_user(username='signup-browser', email='oldbrowser@gmail.com',
            password='InitialPassword!123', role='customer')
        self.client.post(reverse('resend_verification'), {'email': user.email})
        self.client.post(reverse('login'), {'email': user.email, 'password': 'InitialPassword!123'})
        # Make only send cooldowns ready; GET navigation must never send a code.
        from .models import RequestRateBucket
        from django.utils import timezone
        from datetime import timedelta
        RequestRateBucket.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                context = browser.new_context(viewport={'width': 320, 'height': 760})
                context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(
                    content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}})};'))
                context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                    'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
                page = context.new_page()
                page.goto(self.live_server_url + reverse('login'))
                page.get_by_role('button', name='Continue Verification', exact=True).click()
                expect(page).to_have_url(self.live_server_url + reverse('verify_account_otp'))
                expect(page.locator('.otp-digit')).to_have_count(6)
                self.assertEqual(len(mail.outbox), 1)
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
                page.get_by_role('link', name='Change email address', exact=True).click()
                page.locator('#email').fill('newbrowser@gmail.com')
                page.locator('#password').fill('InitialPassword!123')
                page.get_by_role('button', name='Send Code to New Email', exact=True).click()
                expect(page).to_have_url(self.live_server_url + reverse('verify_account_otp'))
                expect(page.locator('body')).to_contain_text('n***@gmail.com')
                code = re.search(r'(?m)^[0-9]{6}$', mail.outbox[-1].body).group()
                page.locator('#otp-digit-1').fill(code)
                page.get_by_role('button', name='Verify Account', exact=True).click()
                expect(page).to_have_url(self.live_server_url + reverse('login'))
            finally:
                browser.close()
        user.refresh_from_db()
        self.assertEqual(user.email, 'newbrowser@gmail.com')
        self.assertTrue(user.email_verified)

    def test_authenticated_change_password_otp_works_in_browser(self):
        from playwright.sync_api import sync_playwright, expect
        user = User.objects.create_user(username='change-browser', email='changebrowser@gmail.com',
            password='InitialPassword!123', role='customer', email_verified=True)
        self.client.force_login(user)
        self.client.post(reverse('change_password'), {'old_password': 'InitialPassword!123',
            'new_password1': 'ChangedInBrowser!123', 'new_password2': 'ChangedInBrowser!123'})
        code = re.search(r'(?m)^[0-9]{6}$', mail.outbox[-1].body).group()
        executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                context = browser.new_context(viewport={'width': 1366, 'height': 900})
                context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(
                    content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}}),fire:()=>{}};'))
                context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                    'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
                page = context.new_page()
                page.goto(self.live_server_url + reverse('verify_change_password_otp'))
                expect(page.locator('body')).to_contain_text('Your password will change only after you verify this code.')
                page.locator('#otp-digit-1').fill(code)
                page.screenshot(path=str(Path(gettempdir()) / 'balloorina-otp-change-desktop.png'), full_page=True)
                page.get_by_role('button', name='Verify & Change Password', exact=True).click()
                expect(page).to_have_url(self.live_server_url + reverse('customer_profile'))
                # The current session must still authorize the profile after the hash changed.
                page.reload()
                expect(page).to_have_url(self.live_server_url + reverse('customer_profile'))
            finally:
                browser.close()
        user.refresh_from_db()
        self.assertTrue(user.check_password('ChangedInBrowser!123'))

    def test_login_banner_is_contextual_and_continue_never_asks_for_email_again(self):
        from playwright.sync_api import sync_playwright, expect
        user = User.objects.create_user(username='banner-browser', email='banner@gmail.com',
            password='InitialPassword!123', role='customer')
        executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                context = browser.new_context(viewport={'width': 390, 'height': 844})
                context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(
                    content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}})};'))
                context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + reverse('login'))
                expect(page.get_by_text('Finish verifying an account', exact=True)).to_have_count(0)
                expect(page.get_by_role('button', name='Continue Verification', exact=True)).to_have_count(0)
                page.locator('#email').fill(user.email)
                page.locator('#password').fill('InitialPassword!123')
                page.get_by_role('button', name='Login', exact=True).click()
                banner = page.locator('.pending-verification')
                expect(banner).to_be_visible()
                expect(banner).to_contain_text('b***@gmail.com')
                expect(banner.locator('input[name="email"]')).to_have_count(0)
                expect(page.locator('#email')).to_have_value(user.email)
                expect(page.locator('#password')).to_have_value('')
                self.assertEqual(len(mail.outbox), 0)
                for theme in ('light', 'dark'):
                    page.evaluate('(theme) => document.documentElement.setAttribute("data-theme", theme)', theme)
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
                    page.screenshot(path=str(Path(gettempdir()) / f'balloorina-signup-banner-{theme}.png'), full_page=True, animations='disabled')
                page.get_by_role('button', name='Continue Verification', exact=True).click()
                expect(page).to_have_url(self.live_server_url + reverse('verify_account_otp'))
                expect(page.locator('.otp-digit')).to_have_count(6)
                self.assertEqual(len(mail.outbox), 1)
                page.get_by_role('link', name='Back to login', exact=True).click()
                page.get_by_role('button', name='Continue Verification', exact=True).click()
                expect(page).to_have_url(self.live_server_url + reverse('verify_account_otp'))
                self.assertEqual(len(mail.outbox), 1)
                page.get_by_role('link', name='Back to login', exact=True).click()
                page.get_by_role('button', name='Use another account', exact=True).click()
                expect(page.locator('.pending-verification')).to_have_count(0)
                expect(page.locator('#email')).to_have_value('')
                self.assertEqual(errors, [])
            finally:
                browser.close()
        user.refresh_from_db()
        self.assertFalse(user.email_verified)
