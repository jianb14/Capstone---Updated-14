"""Opt-in profile dialogs: layout, keyboard behavior, save and password OTP handoff."""
import json
import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import User


@skipUnless(os.environ.get('RUN_PROFILE_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, REQUEST_RATE_LIMITING_ENABLED=False)
class ProfileDialogsBrowserTests(StaticLiveServerTestCase):
    def test_dialog_layout_reset_validation_profile_save_and_otp_redirect(self):
        from playwright.sync_api import expect, sync_playwright

        user = User.objects.create_user(username='profile-dialog-customer', email='profile@example.com',
            password='ExistingPassword!25', role='customer', email_verified=True,
            first_name='Jamie', last_name='Rivera', phone_number='09170000000')
        self.client.force_login(user)
        session = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        artifacts = Path(__file__).resolve().parent.parent / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': session, 'url': self.live_server_url}])
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            sweetalert = artifacts / 'sweetalert2.all.min.js'
            if sweetalert.exists():
                context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(
                    content_type='application/javascript', body=sweetalert.read_text(encoding='utf-8')))
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(self.live_server_url + reverse('my_profile'), wait_until='domcontentloaded')
                for theme in ('light', 'dark'):
                    for width, height in ((1440, 1000), (390, 844), (320, 568), (640, 360)):
                        page.set_viewport_size({'width': width, 'height': height})
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        for kind, trigger, close, focus in (
                            ('profile', '.btn-edit-profile', 'Close edit profile', '#profile_first_name'),
                            ('password', '.btn-change-password', 'Close change password', '#id_old_password'),
                        ):
                            page.locator(trigger).click()
                            dialog = page.locator(f'#{kind}Modal')
                            expect(dialog).to_be_visible()
                            expect(page.locator(focus)).to_be_focused()
                            bounds = dialog.evaluate('''el => {
                                const rect = node => {const r=node.getBoundingClientRect(); return {x:r.x,y:r.y,right:r.right,bottom:r.bottom};};
                                const fields=el.querySelector('.profile-dialog__fields');
                                return {dialog:rect(el), close:rect(el.querySelector('.profile-dialog__close')),
                                    actions:rect(el.querySelector('.profile-dialog__actions')),
                                    horizontalOverflow:el.scrollWidth > el.clientWidth + 1,
                                    fieldsHeight:fields.clientHeight, scrollable:fields.scrollHeight > fields.clientHeight};
                            }''')
                            self.assertGreaterEqual(bounds['dialog']['x'], 0)
                            self.assertGreaterEqual(bounds['dialog']['y'], 0)
                            self.assertLessEqual(bounds['dialog']['right'], width)
                            self.assertLessEqual(bounds['dialog']['bottom'], height)
                            self.assertLessEqual(bounds['actions']['bottom'], bounds['dialog']['bottom'])
                            self.assertGreaterEqual(bounds['close']['y'], bounds['dialog']['y'])
                            self.assertFalse(bounds['horizontalOverflow'])
                            self.assertGreater(bounds['fieldsHeight'], 0)
                            if kind == 'password' and height <= 568:
                                self.assertTrue(bounds['scrollable'])
                            for _ in range(12):
                                page.keyboard.press('Tab')
                                self.assertTrue(dialog.evaluate('el => el.contains(document.activeElement)'))
                            page.screenshot(path=str(artifacts / f'profile-dialog-{kind}-{theme}-{width}.png'), animations='disabled')
                            page.get_by_role('button', name=close, exact=True).click()
                            expect(dialog).not_to_be_visible()
                            expect(page.locator(trigger)).to_be_focused()

                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.locator('.btn-edit-profile').click()
                page.locator('#profile_first_name').fill('Unsaved')
                page.keyboard.press('Escape')
                page.locator('.btn-edit-profile').click()
                expect(page.locator('#profile_first_name')).to_have_value('Jamie')
                for field in ('first_name', 'last_name', 'phone_number'):
                    page.locator('#profile_' + field).fill('   ')
                page.get_by_role('button', name='Save Changes', exact=True).click()
                expect(page.locator('#profile_first_name')).to_be_focused()
                for error in ('profileFirstNameError', 'profileLastNameError', 'profilePhoneError'):
                    expect(page.locator('#' + error)).to_be_visible()
                    expect(page.locator('#' + error)).to_contain_text('required')
                page.locator('#profile_first_name').fill('Jamie')
                page.locator('#profile_last_name').fill('Rivera')
                page.locator('#profile_phone_number').fill('123')
                expect(page.locator('#profilePhoneError')).to_contain_text('10 and 15 digits')
                page.locator('#profile_phone_number').fill('09170000000')
                expect(page.locator('#profileModal .field-error:visible')).to_have_count(0)
                page.locator('#profile_first_name').fill('Jamie Updated')
                page.get_by_role('button', name='Save Changes', exact=True).click()
                expect(page.locator('.my-profile-title h2')).to_have_text('Jamie Updated Rivera')
                page.locator('.btn-edit-profile').click()
                expect(page.locator('#profile_first_name')).to_have_value('Jamie Updated')
                page.mouse.click(1, 1)
                expect(page.locator('#profileModal')).not_to_be_visible()

                page.locator('.btn-change-password').click()
                page.get_by_role('button', name='Send Verification Code', exact=True).click()
                expect(page.locator('#oldPasswordError')).to_contain_text('required')
                expect(page.locator('#id_old_password')).to_be_focused()
                page.locator('#id_old_password').fill('WrongPassword!25')
                page.locator('#id_new_password1').fill('NewPassword!26')
                page.locator('#id_new_password2').fill('NewPassword!26')
                expect(page.locator('#changePasswordRequirements .is-valid')).to_have_count(4)
                page.get_by_role('button', name='Show new password', exact=True).click()
                expect(page.locator('#id_new_password1')).to_have_attribute('type', 'text')
                page.keyboard.press('Escape')
                page.locator('.btn-change-password').click()
                expect(page.locator('#id_new_password1')).to_have_value('')
                expect(page.locator('#id_new_password1')).to_have_attribute('type', 'password')
                expect(page.locator('#changePasswordRequirements .is-valid')).to_have_count(0)
                expect(page.locator('#oldPasswordError')).to_be_hidden()
                page.locator('#id_old_password').fill('WrongPassword!25')
                page.locator('#id_new_password1').fill('NewPassword!26')
                page.locator('#id_new_password2').fill('NewPassword!26')
                page.get_by_role('button', name='Send Verification Code', exact=True).click()
                expect(page.locator('#passwordFormMessage')).to_be_visible()
                expect(page.locator('#oldPasswordError')).to_be_visible()
                expect(page.locator('#id_old_password')).to_be_focused()

                page.locator('#id_old_password').fill('ExistingPassword!25')
                endpoint = self.live_server_url + reverse('change_password')
                page.route(endpoint, lambda route: route.fulfill(status=503, content_type='application/json',
                    body=json.dumps({'success': False, 'errors': {'__all__': ['Please try sending your code later.']}})), times=1)
                page.get_by_role('button', name='Send Verification Code', exact=True).click()
                expect(page.locator('#passwordFormMessage')).to_have_text('Please try sending your code later.')
                expect(page.locator('#btnSavePassword')).to_be_enabled()
                page.get_by_role('button', name='Send Verification Code', exact=True).click()
                expect(page.locator('#profilePasswordOtpDialog')).to_be_visible()
                expect(page.locator('#profileOtpCode')).to_be_visible()
                self.assertEqual(page.url,self.live_server_url + reverse('my_profile'))
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()
