"""Password visibility controls across public, customer and staff forms."""
import os
from html.parser import HTMLParser
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import User


class PasswordFields(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields, self.buttons = [], []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'input' and attrs.get('type') == 'password':
            self.fields.append(attrs['id'])
        if tag == 'button' and 'data-password-target' in attrs:
            self.buttons.append(attrs)


class PasswordPages:
    def password_pages(self):
        customer = User.objects.create_user(username='eye-customer', email='eye@example.com',
            password='ExistingPassword!25', email_verified=True, role='customer')
        admin = User.objects.create_user(username='eye-admin', email='admin@example.com',
            password='ExistingPassword!25', email_verified=True, role='admin', is_staff=True)
        pending = User.objects.create_user(username='eye-pending', email='eye.pending@gmail.com',
            password='ExistingPassword!25', email_verified=False, role='customer')
        customer_client, admin_client, signup_client = Client(), Client(), Client()
        customer_client.force_login(customer)
        admin_client.force_login(admin)
        self.assertEqual(signup_client.post(reverse('resend_verification'), {'email': pending.email}).status_code, 302)
        reset_url = reverse('password_reset_confirm', kwargs={
            'uidb64': urlsafe_base64_encode(force_bytes(customer.pk)),
            'token': default_token_generator.make_token(customer)})
        return [
            ('login', Client(), reverse('login'), None, 1),
            ('register', Client(), reverse('register'), None, 2),
            ('reset', Client(), reset_url, None, 2),
            ('signup-email', signup_client, reverse('change_signup_email'), None, 1),
            ('customer', customer_client, reverse('my_profile'), '.btn-change-password', 4),
            ('admin', admin_client, reverse('admin_profile'), 'button[onclick="openPasswordModal()"]', 3),
        ]


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', REQUEST_RATE_LIMITING_ENABLED=False)
class PasswordVisibilityRenderingTests(PasswordPages, TestCase):
    def test_every_password_field_has_an_accessible_non_submit_control(self):
        for name, client, url, trigger, count in self.password_pages():
            with self.subTest(page=name):
                response = client.get(url)
                self.assertEqual(response.status_code, 200)
                parser = PasswordFields()
                parser.feed(response.content.decode())
                self.assertEqual(len(parser.fields), count)
                self.assertEqual(sorted(parser.fields), sorted(b['data-password-target'] for b in parser.buttons))
                for button in parser.buttons:
                    self.assertEqual(button['type'], 'button')
                    self.assertEqual(button['aria-controls'], button['data-password-target'])
                    self.assertEqual(button['aria-pressed'], 'false')
                    self.assertTrue(button['aria-label'].startswith('Show '))


@skipUnless(os.environ.get('RUN_PASSWORD_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', REQUEST_RATE_LIMITING_ENABLED=False)
class PasswordVisibilityBrowserTests(PasswordPages, StaticLiveServerTestCase):
    def test_all_buttons_mouse_keyboard_theme_and_reset(self):
        from playwright.sync_api import expect, sync_playwright

        pages = self.password_pages()
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            try:
                for name, client, url, trigger, count in pages:
                    context = browser.new_context(reduced_motion='reduce')
                    if settings.SESSION_COOKIE_NAME in client.cookies:
                        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                            'value': client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
                    context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                    sweetalert = artifacts / 'sweetalert2.all.min.js'
                    if sweetalert.exists():
                        context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(
                            content_type='application/javascript', body=sweetalert.read_text(encoding='utf-8')))
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(self.live_server_url + url, wait_until='domcontentloaded')
                    if trigger:
                        page.locator(trigger).click()
                    page.evaluate('''() => {
                        window.testSubmits = 0;
                        document.addEventListener('submit', event => { event.preventDefault(); window.testSubmits++; }, true);
                    }''')
                    for theme in ('light', 'dark'):
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        for width in (1440, 390):
                            page.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
                            buttons = page.locator('button[data-password-target]:visible')
                            expect(buttons).to_have_count(3 if name == 'customer' else count)
                            for index in range(buttons.count()):
                                button = buttons.nth(index)
                                field = page.locator('#' + button.get_attribute('aria-controls'))
                                field.fill('VisibilityCheck!25')
                                field.evaluate('el => el.setSelectionRange(3, 8)')
                                button.click()
                                expect(field).to_have_attribute('type', 'text')
                                expect(field).to_have_value('VisibilityCheck!25')
                                expect(button).to_have_attribute('aria-pressed', 'true')
                                expect(button).to_have_attribute('aria-label', 'Hide ' + button.get_attribute('data-password-label'))
                                expect(button.locator('.password-visibility-hide')).to_be_visible()
                                expect(button.locator('.password-visibility-show')).to_be_hidden()
                                self.assertEqual(field.evaluate('el => [el.selectionStart, el.selectionEnd]'), [3, 8])
                                field.focus()
                                page.keyboard.press('Tab')
                                expect(button).to_be_focused()
                                self.assertNotEqual(button.evaluate('el => getComputedStyle(el).outlineStyle'), 'none', name)
                                button.press('Space')
                                expect(field).to_have_attribute('type', 'password')
                                button.press('Enter')
                                expect(field).to_have_attribute('type', 'text')
                                expect(button).to_be_focused()
                                button.hover()
                                style = button.evaluate('''el => ({color:getComputedStyle(el).color,
                                    width:el.getBoundingClientRect().width, height:el.getBoundingClientRect().height,
                                    stroke:getComputedStyle(el.querySelector('svg')).stroke})''')
                                self.assertGreaterEqual(style['width'], 40)
                                self.assertGreaterEqual(style['height'], 40)
                                self.assertEqual(style['color'], style['stroke'])
                                self.assertEqual(style['color'], 'rgb(24, 24, 27)' if theme == 'light' else 'rgb(244, 244, 245)')
                                button.click()
                                expect(field).to_have_attribute('type', 'password')
                            self.assertEqual(page.evaluate('window.testSubmits'), 0)
                            if name in ('login', 'customer', 'admin'):
                                page.screenshot(path=str(artifacts / f'password-eye-{name}-{theme}-{width}.png'), animations='disabled')
                    for button in page.locator('button[data-password-target]:visible').all():
                        button.click()
                    page.locator('button[data-password-target]:visible').first.evaluate('el => el.form.reset()')
                    expect(page.locator('button[data-password-target][aria-pressed="true"]')).to_have_count(0)
                    for field in page.locator('.password-visibility-field > input').all():
                        expect(field).to_have_attribute('type', 'password')
                        expect(field).to_have_value('')
                    if trigger:
                        page.locator('button[data-password-target]:visible').first.click()
                        page.evaluate('closePasswordModal()')
                        page.locator(trigger).click()
                        expect(page.locator('button[data-password-target][aria-pressed="true"]')).to_have_count(0)
                    self.assertEqual(errors, [], name)
                    context.close()
            finally:
                browser.close()
