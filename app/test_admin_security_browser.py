"""Opt-in end-to-end onboarding in real Chromium, with a disposable DB and local mail."""
import os
import re
from datetime import timedelta
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from .models import AdminInvitation, AdminSecurityChallenge, User

PASSWORD = 'Creator!Secure234'


@skipUnless(os.environ.get('RUN_ADMIN_SECURITY_BROWSER') == '1', 'Optional admin onboarding browser tests')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AdminSecurityBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser(username='onboard-owner', email='main@example.com', password=PASSWORD,
            first_name='Alex', role='admin', email_verified=True)
        self.client.force_login(self.owner)
        self.artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'
        mail.outbox = []

    def field(self, scope, caption):
        if caption == '6-digit verification code':
            return scope.locator('[data-otp-digit]').first
        # Visible required markers are excluded from the accessible name, but
        # Playwright label-text matching also includes their literal text.
        return scope.get_by_label(re.compile(r'^' + re.escape(caption) + r'\s*\*?$'))

    def browser(self, playwright):
        browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        if settings.SESSION_COOKIE_NAME in self.client.cookies:
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
        context.add_init_script("localStorage.setItem('balloorina-theme','light')")
        context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        context.route('https://cdnjs.cloudflare.com/**', lambda route: route.abort())
        context.route('https://cdn.jsdelivr.net/**', lambda route: route.fulfill(status=200, content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}})};'))
        return browser, context

    def test_async_invitation_and_recipient_acceptance(self):
        with sync_playwright() as p:
            browser, context = self.browser(p)
            page = context.new_page(); errors, documents = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
            try:
                page.goto(self.live_server_url + reverse('admin_user_list'))
                page.get_by_role('button', name='Create admin', exact=True).click()
                modal = page.locator('#adminInviteModal'); expect(modal).to_be_visible()
                self.field(page, 'First name').fill('Jamie')
                self.field(page, 'Last name').fill('Rivera')
                self.field(page, 'New admin email').fill('new-admin@example.com')
                self.field(page, 'Phone number').fill('09171234567')
                self.field(page, 'Your current password').first.fill(PASSWORD)
                page.get_by_role('button', name='Send authorization code', exact=True).click()
                expect(self.field(page, '6-digit verification code')).to_be_visible()
                toast = page.locator('.cfg-toast')
                expect(toast).to_be_visible()
                expect(toast).to_contain_text('A verification code was sent')
                self.assertLess(toast.bounding_box()['y'], 100)
                self.assertTrue(toast.evaluate("el=>el.matches(':popover-open')"))
                self.assertEqual(mail.outbox[-1].to, ['main@example.com'])
                code = re.search(r'\b\d{6}\b', mail.outbox[-1].body).group()
                page.get_by_role('button', name='Close admin invitation', exact=True).click()
                page.get_by_role('button', name='Create admin', exact=True).click()
                expect(self.field(page, '6-digit verification code')).to_be_visible()
                page.reload()
                page.get_by_role('button', name='Create admin', exact=True).click()
                expect(self.field(page, '6-digit verification code')).to_be_visible()
                self.assertEqual(len(mail.outbox), 1)
                self.field(page, '6-digit verification code').fill(code)
                page.get_by_role('button', name='Verify code and continue', exact=True).click()
                expect(modal.locator('.ase-feedback').first).to_contain_text('Invitation sent')
                expect(page.locator('.cfg-toast')).to_have_attribute('data-kind', 'success')
                expect(page.locator('.cfg-toast')).to_contain_text('Invitation sent')
                expect(modal.locator('.ase-invitation')).to_have_count(1)
                self.assertEqual(len(documents), 2)  # The explicit refresh above; forms never reload.
                self.assertEqual(mail.outbox[-1].to, ['new-admin@example.com'])
                link = re.search(r'https?://[^\s]+', mail.outbox[-1].body).group()
                recipient = browser.new_context(viewport={'width': 390, 'height': 844})
                recipient.add_init_script("localStorage.setItem('balloorina-theme','light')")
                recipient.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                recipient.route('https://cdnjs.cloudflare.com/**', lambda route: route.abort())
                recipient.route('https://cdn.jsdelivr.net/**', lambda route: route.fulfill(status=200, content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}})};'))
                accept = recipient.new_page(); accept.on('pageerror', lambda error: errors.append(str(error)))
                accept.goto(link)
                self.assertEqual(accept.url, self.live_server_url + reverse('admin_invitation_accept'))
                expect(accept.locator('#loginForm')).to_be_visible()
                expect(accept.locator('#adminAcceptModal')).to_be_visible()
                expect(accept.get_by_text('Welcome to the team', exact=True)).to_be_visible()
                self.field(accept, 'Create password').fill('Recipient!Secure786')
                self.field(accept, 'Confirm password').fill('Recipient!Secure786')
                accept.screenshot(path=str(self.artifacts / 'admin-invite-accept-mobile.png'))
                accept.get_by_role('button', name='Create my admin account', exact=True).click()
                expect(accept).to_have_url(self.live_server_url + reverse('login'))
                self.assertEqual(errors, [])
                recipient.close()
            finally:
                context.close(); browser.close()
        user = User.objects.get(email='new-admin@example.com')
        self.assertTrue(user.email_verified)
        self.assertFalse(user.is_superuser or user.is_staff)
        self.assertEqual(AdminInvitation.objects.get().status, 'accepted')

    def test_invitation_feedback_disabled_hover_and_revocation(self):
        with sync_playwright() as p:
            browser, context = self.browser(p)
            page = context.new_page(); errors, documents, revocations = [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
            page.on('request', lambda request: revocations.append(request.url) if request.method == 'POST' and '/revoke/' in request.url else None)
            try:
                page.goto(self.live_server_url + reverse('admin_user_list'))
                page.get_by_role('button', name='Create admin', exact=True).click()
                modal = page.locator('#adminInviteModal')
                form = modal.locator('[data-security-flow]')
                self.field(form, 'First name').fill('Jamie')
                self.field(form, 'Last name').fill('Rivera')
                self.field(form, 'New admin email').fill('revoke-admin@example.com')
                self.field(form, 'Phone number').fill('09171234567')
                self.field(form, 'Your current password').fill(PASSWORD)
                # Hold real mutation responses briefly to exercise the busy state.
                page.evaluate('''() => {
                    const original=window.fetch;
                    window.fetch=(...args)=>original(...args).then(async response=>{
                        if(args[1]?.method==='POST' && String(args[0]).includes('/security/'))
                            await new Promise(resolve=>setTimeout(resolve,650));
                        return response;
                    });
                }''')
                send = form.locator('[type=submit]')
                send.click()
                expect(send).to_be_disabled()
                expect(send).to_have_css('pointer-events', 'none')
                box = send.bounding_box(); page.mouse.move(box['x']+10, box['y']+10)
                self.assertFalse(send.evaluate("el=>el.matches(':hover')"))
                expect(form.locator('[data-otp-digit]').first).to_be_visible()
                toast = page.locator('.cfg-toast')
                expect(toast).to_contain_text('A verification code was sent')
                resend = form.locator('[data-security-resend]')
                style = '(el)=>{const s=getComputedStyle(el);return [s.backgroundColor,s.color,s.opacity,s.transform,s.boxShadow]}'
                for theme in ('light', 'dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                    page.mouse.move(0, 0)
                    expect(resend).to_be_disabled()
                    expect(resend).to_have_css('pointer-events', 'none')
                    resting = resend.evaluate(style)
                    box = resend.bounding_box(); page.mouse.move(box['x']+10, box['y']+10)
                    self.assertFalse(resend.evaluate("el=>el.matches(':hover')"))
                    self.assertEqual(resend.evaluate(style), resting)
                code = re.search(r'\b\d{6}\b', mail.outbox[-1].body).group()
                self.field(form, '6-digit verification code').fill(code)
                form.get_by_role('button', name='Verify code and continue', exact=True).click()
                expect(form.locator('[data-security-back]')).to_be_disabled()
                expect(form.locator('[data-security-resend]')).to_be_disabled()
                expect(modal.locator('.ase-invitation')).to_have_count(1)
                expect(toast).to_contain_text('Invitation sent')
                modal.locator('.ase-invitation').get_by_role('button', name='Revoke', exact=True).click()
                revoke = modal.locator('.ase-revoke')
                self.field(revoke, 'Your current password').fill('IncorrectPassword!24')
                revoke.get_by_role('button', name='Revoke invitation', exact=True).click()
                expect(revoke.locator('.ase-feedback')).to_contain_text('Your current password is incorrect')
                expect(toast).to_have_attribute('data-kind', 'error')
                expect(toast).to_contain_text('Your current password is incorrect')
                expect(modal.locator('.ase-invitation')).to_contain_text('Pending')
                self.field(revoke, 'Your current password').fill(PASSWORD)
                revoke.get_by_role('button', name='Revoke invitation', exact=True).evaluate('el=>{el.click();el.click()}')
                expect(revoke).to_be_hidden()
                expect(modal.locator('.ase-invitation')).to_contain_text('Revoked')
                expect(toast).to_have_attribute('data-kind', 'success')
                expect(toast).to_contain_text('Invitation revoked')
                expect(form.locator('.ase-feedback')).to_be_empty()
                self.assertLess(toast.bounding_box()['y'], 100)
                self.assertTrue(toast.evaluate("el=>el.matches(':popover-open')"))
                self.assertEqual(len(revocations), 2)  # One rejected attempt, then one successful POST.
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(self.artifacts / 'admin-users-feedback-mobile-dark.png'), animations='disabled')
                self.assertGreaterEqual(toast.bounding_box()['x'], 0)
                self.assertLessEqual(toast.bounding_box()['x'] + toast.bounding_box()['width'], 390)
                self.assertEqual(len(documents), 1)
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()
        self.assertEqual(AdminInvitation.objects.get().status, 'revoked')

    def test_invite_modal_light_dark_mobile_and_focus(self):
        with sync_playwright() as p:
            browser, context = self.browser(p)
            page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(self.live_server_url + reverse('admin_user_list'))
                page.get_by_role('button', name='Create admin', exact=True).click()
                modal = page.locator('#adminInviteModal')
                reference = context.new_page()
                reference.goto(self.live_server_url + reverse('admin_concerns'))
                focus_style = '(node)=>{const style=getComputedStyle(node);return Object.fromEntries(["outlineStyle","outlineWidth","outlineColor","outlineOffset","borderTopColor","boxShadow"].map(key=>[key,style[key]]))}'
                for theme in ('light', 'dark'):
                    page.evaluate('(theme)=>{document.documentElement.dataset.theme=theme}', theme)
                    reference.evaluate('(theme)=>{document.documentElement.dataset.theme=theme}', theme)
                    search = reference.locator('.ac-search input')
                    search.focus()
                    expect(search).to_have_css('outline-style', 'solid')
                    expected_focus = search.evaluate(focus_style)
                    for width in (1440, 768, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 844})
                        page.wait_for_timeout(200)
                        field = self.field(page, 'First name'); field.focus()
                        expect(field).to_have_css('outline-offset', '2px')
                        expect(field).to_have_css('box-shadow', 'none')
                        expect(field).to_have_css('border-top-color', expected_focus['borderTopColor'])
                        self.assertEqual(field.evaluate(focus_style), expected_focus)
                        box = modal.bounding_box()
                        self.assertGreaterEqual(box['x'], 0); self.assertLessEqual(box['x'] + box['width'], width)
                        self.assertFalse(modal.evaluate('(node)=>node.scrollWidth>node.clientWidth+1'))
                        close = page.get_by_role('button', name='Close admin invitation', exact=True)
                        self.assertGreaterEqual(close.bounding_box()['width'], 40)
                        page.screenshot(path=str(self.artifacts / f'admin-invite-{theme}-{width}.png'), animations='disabled')
                page.keyboard.press('Escape'); expect(modal).to_be_hidden()
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()

    def test_recipient_modal_validation_spacing_and_close_reveal_working_login(self):
        sent = self.client.post(reverse('admin_security_action', args=['invite', 'send']), {
            'first_name':'Jamie', 'last_name':'Rivera', 'email':'new-admin@example.com',
            'phone_number':'09171234567', 'current_password':PASSWORD})
        self.assertEqual(sent.status_code, 200)
        code = re.search(r'\b\d{6}\b', mail.outbox[-1].body).group()
        self.assertEqual(self.client.post(reverse('admin_security_action', args=['invite', 'confirm']), {'code':code}).status_code, 200)
        link = re.search(r'https?://[^\s]+', mail.outbox[-1].body).group().replace('http://testserver', self.live_server_url)
        self.client.logout()
        with sync_playwright() as p:
            browser, context = self.browser(p); page = context.new_page(); errors, documents = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
            try:
                page.goto(link)
                dialog = page.locator('#adminAcceptModal'); form = dialog.locator('[data-invitation-accept]')
                expect(dialog).to_be_visible(); expect(page.locator('#loginForm')).to_be_visible()
                initial_documents = len(documents)
                for theme in ('light', 'dark'):
                    page.evaluate('(theme)=>{document.documentElement.dataset.theme=theme}', theme)
                    expected_red = 'rgb(184, 53, 60)' if theme == 'light' else 'rgb(241, 145, 145)'
                    for width in (1440, 390, 320):
                        page.set_viewport_size({'width':width, 'height':844})
                        form.evaluate('(form)=>form.reset()')
                        form.get_by_role('button', name='Create my admin account').click()
                        expect(form.locator('#invitationPasswordError')).to_have_text('Create a password.')
                        expect(form.locator('#invitationConfirmError')).to_have_text('Confirm your password.')
                        expect(form.locator('[data-invitation-feedback]')).to_have_text('')
                        expect(form.locator('.ase-required').first).to_have_css('color', expected_red)
                        expect(form.locator('#invitationPasswordError')).to_have_css('color', expected_red)
                        gap = form.locator('#invitationPasswordError').bounding_box()['y'] - (
                            form.locator('#invitationPassword').bounding_box()['y'] + form.locator('#invitationPassword').bounding_box()['height'])
                        self.assertGreaterEqual(gap, 3); self.assertLess(gap, 7)
                        label = form.locator('label[for="invitationPassword"]').bounding_box()
                        label_gap = form.locator('#invitationPassword').bounding_box()['y'] - (label['y'] + label['height'])
                        self.assertGreaterEqual(label_gap, 3); self.assertLess(label_gap, 7)
                        self.assertFalse(dialog.evaluate('(node)=>node.scrollWidth>node.clientWidth+1'))
                        expect(form.locator('.password-requirements-title')).to_have_text('Password requirements')
                        expect(form.locator('.password-requirements-list')).to_have_css('display', 'grid')
                        self.field(form, 'Create password').fill('abc')
                        expect(form.locator('.password-rule.is-valid')).to_have_count(0)
                        self.field(form, 'Create password').fill('Abc1!')
                        expect(form.locator('.password-rule.is-valid')).to_have_count(3)
                        self.field(form, 'Create password').fill('QZ!49N8X')
                        expect(form.locator('.password-rule.is-valid')).to_have_count(4)
                        self.field(form, 'Confirm password').fill('Mismatch!Secure786')
                        form.get_by_role('button', name='Create my admin account').click()
                        expect(form.locator('#invitationPasswordError')).to_be_hidden()
                        expect(form.locator('#invitationConfirmError')).to_have_text('Passwords do not match.')
                        help_gap = form.locator('#invitationPasswordHelp').bounding_box()['y'] - (
                            form.locator('#invitationPassword').bounding_box()['y'] + form.locator('#invitationPassword').bounding_box()['height'])
                        self.assertGreaterEqual(help_gap, 5); self.assertLess(help_gap, 9)
                        page.screenshot(path=str(self.artifacts / f'admin-accept-modal-{theme}-{width}.png'), animations='disabled')
                self.assertEqual(len(documents), initial_documents)
                page.get_by_role('button', name='Close admin account setup').click()
                expect(dialog).to_be_hidden()
                expect(page).to_have_url(self.live_server_url + reverse('login'))
                expect(page.locator('#loginForm')).to_have_attribute('action', reverse('login'))
                self.assertEqual(len(documents), initial_documents)
                page.locator('#email').fill('main@example.com')
                page.locator('#password').fill(PASSWORD)
                page.get_by_role('button', name='Login', exact=True).click()
                expect(page).to_have_url(self.live_server_url + reverse('dashboard'))
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()
        self.assertFalse(User.objects.filter(email='new-admin@example.com').exists())

    def test_required_markers_and_validation_messages_are_red_in_both_themes(self):
        with sync_playwright() as p:
            browser, context = self.browser(p)
            page = context.new_page(); writes, errors = [], []
            page.on('request', lambda request: writes.append(request.url) if request.method == 'POST' and '/security/' in request.url else None)
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(self.live_server_url + reverse('admin_user_list'))
                page.get_by_role('button', name='Create admin', exact=True).click()
                form = page.locator('#adminInviteModal [data-security-flow]')
                submit = form.get_by_role('button', name='Send authorization code', exact=True)
                for theme in ('light', 'dark'):
                    page.evaluate('(theme)=>{document.documentElement.dataset.theme=theme}', theme)
                    page.set_viewport_size({'width': 390 if theme == 'dark' else 1440, 'height': 900})
                    form.evaluate('(form)=>form.reset()')
                    expected_red = 'rgb(184, 53, 60)' if theme == 'light' else 'rgb(241, 145, 145)'
                    expect(form.locator('[data-security-fields] .ase-required')).to_have_count(5)
                    expect(form.locator('.ase-required').first).to_have_css('color', expected_red)
                    write_count = len(writes)
                    submit.click()
                    expect(form.locator('.ase-field-error')).to_have_count(5)
                    for message in form.locator('.ase-field-error').all():
                        expect(message).to_have_css('color', expected_red)
                    error_gap = form.locator('#inviteFirstNameError').bounding_box()['y'] - (
                        form.locator('#inviteFirstName').bounding_box()['y'] + form.locator('#inviteFirstName').bounding_box()['height'])
                    self.assertGreaterEqual(error_gap, 7)
                    self.assertLess(error_gap, 12)
                    expect(form.locator('.ase-feedback')).to_have_text('')
                    self.assertEqual(len(writes), write_count)
                    self.field(form, 'First name').fill('Jamie')
                    self.field(form, 'Last name').fill('Rivera')
                    self.field(form, 'New admin email').fill('not-an-email')
                    self.field(form, 'Phone number').fill('123')
                    self.field(form, 'Your current password').fill('Wrong!Password123')
                    submit.click()
                    expect(form.locator('#inviteEmailError')).to_contain_text('valid email')
                    expect(form.locator('#invitePhoneError')).to_contain_text('10 to 15 digits')
                    self.assertEqual(len(writes), write_count)
                    self.field(form, 'New admin email').fill('new-admin@example.com')
                    self.field(form, 'Phone number').fill('09171234567')
                    submit.click()
                    expect(form.locator('.ase-feedback')).to_have_text('Your current password is incorrect.')
                    expect(form.locator('.ase-feedback')).to_have_css('color', expected_red)
                    password = form.locator('#inviteCurrentPassword')
                    summary_gap = form.locator('.ase-feedback').bounding_box()['y'] - (password.bounding_box()['y'] + password.bounding_box()['height'])
                    self.assertGreaterEqual(summary_gap, 7)
                    self.assertLess(summary_gap, 12)
                    self.assertEqual(len(writes), write_count + 1)
                    page.screenshot(path=str(self.artifacts / f'admin-invite-validation-{theme}.png'), animations='disabled')
                self.assertEqual(mail.outbox, [])
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()

    def test_unverified_admin_email_setup_in_browser(self):
        self.owner.email_verified = False; self.owner.save(update_fields=['email_verified'])
        with sync_playwright() as p:
            browser, context = self.browser(p); page = context.new_page(); errors, documents = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
            try:
                page.goto(self.live_server_url + reverse('admin_profile'))
                dialog = page.locator('#adminEmailModal')
                expect(dialog).to_be_hidden()
                page.get_by_role('button', name='Set up and verify email', exact=True).click()
                expect(dialog).to_be_visible()
                for theme in ('light', 'dark'):
                    page.evaluate('(theme)=>{document.documentElement.dataset.theme=theme}', theme)
                    for width in (1440, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 844})
                        self.field(dialog, 'Your accessible email').focus()
                        expect(self.field(dialog, 'Your accessible email')).to_have_css('outline-offset', '2px')
                        self.assertFalse(dialog.evaluate('(node)=>node.scrollWidth>node.clientWidth+1'))
                        self.assertGreaterEqual(dialog.bounding_box()['x'], 0)
                        page.screenshot(path=str(self.artifacts / f'admin-email-modal-{theme}-{width}.png'), animations='disabled')
                self.field(page, 'Your accessible email').fill('verified-main@example.com')
                self.field(page, 'Current password').fill(PASSWORD)
                page.get_by_role('button', name='Send verification code', exact=True).click()
                expect(self.field(page, '6-digit verification code')).to_be_visible()
                code = re.search(r'\b\d{6}\b', mail.outbox[-1].body).group()
                page.get_by_role('button', name='Close email verification', exact=True).click()
                expect(dialog).to_be_hidden()
                page.get_by_role('button', name='Set up and verify email', exact=True).click()
                expect(self.field(page, '6-digit verification code')).to_be_visible()
                page.reload()
                page.get_by_role('button', name='Set up and verify email', exact=True).click()
                expect(self.field(page, '6-digit verification code')).to_be_visible()
                self.assertEqual(len(mail.outbox), 1)
                page.screenshot(path=str(self.artifacts / 'admin-email-setup-code-mobile.png'))
                self.field(page, '6-digit verification code').fill(code)
                page.get_by_role('button', name='Verify code and continue', exact=True).click()
                expect(dialog).to_be_hidden()
                expect(page).to_have_url(self.live_server_url + reverse('admin_profile'))
                expect(page.locator('[data-email-verified-message]')).to_contain_text('verified-main@example.com')
                expect(page.locator('.ap-info-val [data-admin-email-value]')).to_have_text('verified-main@example.com')
                expect(page.locator('[data-open-email]')).to_be_hidden()
                expect(page.locator('.cfg-toast')).to_be_visible()
                expect(page.locator('.cfg-toast')).to_have_attribute('data-kind','success')
                expect(page.locator('#apFeedback')).to_be_visible()
                page.screenshot(path=str(self.artifacts / 'admin-profile-email-saved-feedback.png'),animations='disabled')
                self.assertEqual(len(documents), 2)  # Only the explicit refresh reloads the document.
                self.assertFalse(page.evaluate('document.body.classList.contains("ac-modal-open")'))
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()
        self.owner.refresh_from_db(); self.assertTrue(self.owner.email_verified); self.assertEqual(self.owner.email, 'verified-main@example.com')

    def test_restricted_login_and_legacy_email_link_open_the_profile_modal(self):
        self.owner.email_verified = False; self.owner.save(update_fields=['email_verified'])
        self.client.logout()
        response = self.client.post(reverse('login'), {'email': self.owner.email, 'password': PASSWORD})
        self.assertEqual(response.status_code, 302)
        with sync_playwright() as p:
            browser, context = self.browser(p); page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(self.live_server_url + reverse('admin_email_setup'))
                expect(page).to_have_url(re.compile(re.escape(self.live_server_url + reverse('admin_profile')) + r'\?verify_email=1'))
                dialog = page.locator('#adminEmailModal')
                expect(dialog).to_be_visible()
                page.get_by_role('button', name='Close email verification', exact=True).click()
                page.goto(self.live_server_url + reverse('admin_user_list'))
                expect(dialog).to_be_visible()
                expect(page).to_have_url(re.compile(re.escape(self.live_server_url + reverse('admin_profile')) + r'\?verify_email=1'))
                self.field(dialog, 'Your accessible email').fill('verified-main@example.com')
                self.field(dialog, 'Current password').fill(PASSWORD)
                dialog.get_by_role('button', name='Send verification code', exact=True).click()
                expect(self.field(dialog, '6-digit verification code')).to_be_visible()
                code = re.search(r'\b\d{6}\b', mail.outbox[-1].body).group()
                page.reload()
                expect(dialog).to_be_visible()
                self.field(dialog, '6-digit verification code').fill(code)
                dialog.get_by_role('button', name='Verify code and continue', exact=True).click()
                expect(dialog).to_be_hidden()
                expect(page).to_have_url(self.live_server_url + reverse('admin_profile'))
                page.goto(self.live_server_url + reverse('admin_user_list'))
                expect(page.get_by_role('button', name='Create admin', exact=True)).to_be_visible()
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()

    def test_email_modal_restores_expiry_and_resends_without_leaving_profile(self):
        self.owner.email_verified = False; self.owner.save(update_fields=['email_verified'])
        self.assertEqual(self.client.post(reverse('admin_security_action', args=['email', 'send']), {
            'email': 'verified-main@example.com', 'current_password': PASSWORD}).status_code, 200)
        AdminSecurityChallenge.objects.update(created_at=timezone.now() - timedelta(minutes=6),
                                              expires_at=timezone.now() - timedelta(minutes=1))
        with sync_playwright() as p:
            browser, context = self.browser(p); page = context.new_page(); errors, documents = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
            try:
                page.set_viewport_size({'width': 390, 'height': 844})
                page.goto(self.live_server_url + reverse('admin_profile') + '?verify_email=1')
                dialog = page.locator('#adminEmailModal')
                expect(dialog).to_be_visible()
                expect(dialog.locator('[data-security-expired]')).to_be_visible()
                expect(dialog.locator('[data-security-code]')).to_be_hidden()
                expect(dialog.locator('.ase-feedback')).to_have_text('')
                dialog.get_by_role('button', name='Send new code', exact=True).click()
                expect(self.field(dialog, '6-digit verification code')).to_be_visible()
                expect(dialog.locator('[data-security-resend]')).to_be_disabled()
                self.assertEqual(mail.outbox[-1].to, ['verified-main@example.com'])
                self.assertEqual(len(mail.outbox), 2)
                code = re.search(r'\b\d{6}\b', mail.outbox[-1].body).group()
                self.field(dialog, '6-digit verification code').fill(code)
                dialog.get_by_role('button', name='Verify code and continue', exact=True).click()
                expect(dialog).to_be_hidden()
                expect(page.locator('[data-email-verified-message]')).to_be_visible()
                self.assertEqual(len(documents), 1)
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()

    def test_six_digit_boxes_reject_letters_support_paste_navigation_and_leading_zeroes(self):
        with patch('app.admin_security.secrets.randbelow', return_value=42):
            response = self.client.post(reverse('admin_security_action', args=['invite', 'send']), {
                'first_name': 'Jamie', 'last_name': 'Rivera', 'email': 'new-admin@example.com',
                'phone_number': '09171234567', 'current_password': PASSWORD})
        self.assertEqual(response.status_code, 200)
        with sync_playwright() as p:
            browser, context = self.browser(p)
            page = context.new_page(); writes, errors = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: writes.append(request.post_data) if request.method == 'POST' and '/security/' in request.url else None)
            try:
                page.goto(self.live_server_url + reverse('admin_user_list'))
                page.get_by_role('button', name='Create admin', exact=True).click()
                boxes = page.locator('[data-otp-digit]'); expect(boxes).to_have_count(6)
                boxes.first.press_sequentially('abcXYZ')
                self.assertEqual(boxes.evaluate_all('(fields)=>fields.map(field=>field.value).join("")'), '')
                boxes.first.press_sequentially('12')
                expect(boxes.nth(0)).to_have_value('1'); expect(boxes.nth(1)).to_have_value('2')
                expect(boxes.nth(2)).to_be_focused()
                boxes.nth(2).press('Backspace')
                expect(boxes.nth(1)).to_be_focused(); expect(boxes.nth(1)).to_have_value('')
                boxes.nth(1).press('ArrowLeft'); expect(boxes.nth(0)).to_be_focused()
                boxes.first.press('ArrowRight'); expect(boxes.nth(1)).to_be_focused()
                page.get_by_role('button', name='Verify code and continue', exact=True).click()
                expect(page.locator('#inviteCodeError')).to_have_text('Enter all 6 digits from your email.')
                self.assertEqual(writes, [])
                for theme in ('light', 'dark'):
                    page.evaluate('(theme)=>{document.documentElement.dataset.theme=theme}', theme)
                    for width in (1440, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 900})
                        boxes.nth(2).evaluate("(field)=>{const clipboard=new DataTransfer();clipboard.setData('text','00 00-42');field.dispatchEvent(new ClipboardEvent('paste',{clipboardData:clipboard,bubbles:true,cancelable:true}));}")
                        self.assertEqual(boxes.evaluate_all('(fields)=>fields.map(field=>field.value).join("")'), '000042')
                        expect(page.locator('#inviteCodeError')).to_have_count(0)
                        expect(page.locator('#adminInviteModal .ase-feedback').first).to_have_text('')
                        expect(boxes.last).to_be_focused()
                        self.assertFalse(page.locator('#adminInviteModal').evaluate('(node)=>node.scrollWidth>node.clientWidth+1'))
                        page.screenshot(path=str(self.artifacts / f'admin-invite-otp-{theme}-{width}.png'), animations='disabled')
                # SMS/mail autofill can insert the whole code into one box.
                boxes.first.fill('000042')
                self.assertEqual(boxes.evaluate_all('(fields)=>fields.map(field=>field.value).join("")'), '000042')
                page.get_by_role('button', name='Verify code and continue', exact=True).click()
                expect(page.locator('#adminInviteModal .ase-feedback').first).to_contain_text('Invitation sent')
                self.assertEqual(len(writes), 1)
                self.assertIn('000042', writes[0])
                self.assertEqual(len(mail.outbox), 2)
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()

    def test_live_server_based_countdown_survives_refresh_close_and_expiry(self):
        self.assertEqual(self.client.post(reverse('admin_security_action', args=['invite', 'send']), {
            'first_name': 'Jamie', 'last_name': 'Rivera', 'email': 'new-admin@example.com',
            'phone_number': '09171234567', 'current_password': PASSWORD}).status_code, 200)
        AdminSecurityChallenge.objects.update(created_at=timezone.now() - timedelta(seconds=40),
                                              expires_at=timezone.now() + timedelta(seconds=40))
        challenge = AdminSecurityChallenge.objects.get()
        with sync_playwright() as p:
            browser, context = self.browser(p)
            page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.clock.install()
                page.goto(self.live_server_url + reverse('admin_user_list'))
                page.get_by_role('button', name='Create admin', exact=True).click()
                form = page.locator('#adminInviteModal [data-security-flow]')
                expiry, resend = form.locator('[data-code-expiry]'), form.locator('[data-security-resend]')
                expect(expiry).to_have_text(re.compile(r'Code expires in 0:(?:[0-3][0-9]|40)\.'))
                expect(resend).to_have_text(re.compile(r'Resend in 0:(?:[0-1][0-9]|20)'))
                expect(resend).to_be_disabled()
                before = expiry.inner_text()
                page.clock.fast_forward(3000)
                self.assertNotEqual(expiry.inner_text(), before)
                after = expiry.inner_text()
                page.get_by_role('button', name='Close admin invitation', exact=True).click()
                page.get_by_role('button', name='Create admin', exact=True).click()
                self.assertEqual(expiry.inner_text(), after)
                page.reload()
                page.get_by_role('button', name='Create admin', exact=True).click()
                expect(form).to_have_attribute('data-code-expires-at', challenge.expires_at.isoformat())
                expect(expiry).to_have_text(re.compile(r'Code expires in 0:(?:[0-3][0-9]|40)\.'))
                page.get_by_role('button', name='Verify code and continue', exact=True).click()
                expect(page.locator('#inviteCodeError')).to_be_visible()
                boxes = form.locator('[data-otp-digit]')
                gap = page.locator('#inviteCodeError').bounding_box()['y'] - (boxes.first.bounding_box()['y'] + boxes.first.bounding_box()['height'])
                self.assertGreaterEqual(gap, 7)
                self.assertLess(gap, 12)
                expect(form.locator('.ase-feedback')).to_have_text('')
                for theme in ('light', 'dark'):
                    page.evaluate('(theme)=>{document.documentElement.dataset.theme=theme}', theme)
                    page.screenshot(path=str(self.artifacts / f'admin-otp-countdown-{theme}.png'), animations='disabled')
                page.clock.fast_forward(21000)
                expect(resend).to_be_enabled()
                expect(resend).to_have_text('Resend code')
                # Returning to the saved code step after a refresh retains the
                # original deadline, not a fresh five-minute countdown.
                page.reload(); page.get_by_role('button', name='Create admin', exact=True).click()
                page.evaluate('document.documentElement.dataset.theme="dark"')
                page.clock.fast_forward(41000)
                expect(form).to_have_attribute('data-stage', 'expired')
                expect(form.locator('[data-security-expired]')).to_be_visible()
                expect(form.locator('[data-security-code]')).to_be_hidden()
                expect(form.locator('.ase-feedback')).to_have_text('')
                expect(form.locator('.ase-field-error')).to_have_count(0)
                expect(form.get_by_role('button', name='Send new code', exact=True)).to_be_enabled()
                expect(resend).to_be_hidden()
                self.assertEqual(len(mail.outbox), 1)
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()

    def test_expired_refresh_has_one_message_and_direct_resend_without_reentering_details(self):
        with patch('app.admin_security.secrets.randbelow', return_value=42):
            self.assertEqual(self.client.post(reverse('admin_security_action', args=['invite', 'send']), {
                'first_name': 'Jamie', 'last_name': 'Rivera', 'email': 'new-admin@example.com',
                'phone_number': '09171234567', 'current_password': PASSWORD}).status_code, 200)
        AdminSecurityChallenge.objects.update(created_at=timezone.now() - timedelta(minutes=6),
                                              expires_at=timezone.now() - timedelta(minutes=1))
        with sync_playwright() as p:
            browser, context = self.browser(p)
            page = context.new_page(); errors, writes, documents = [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: writes.append((request.url, request.post_data))
                    if request.method == 'POST' and '/security/' in request.url else None)
            page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
            try:
                page.goto(self.live_server_url + reverse('admin_user_list'))
                for theme in ('light', 'dark'):
                    page.reload()
                    page.evaluate('(theme)=>{document.documentElement.dataset.theme=theme}', theme)
                    page.set_viewport_size({'width': 390 if theme == 'dark' else 1440, 'height': 900})
                    page.get_by_role('button', name='Create admin', exact=True).click()
                    form = page.locator('#adminInviteModal [data-security-flow]')
                    expect(form).to_have_attribute('data-stage', 'expired')
                    expect(form.get_by_role('heading', name='Verification code expired')).to_have_count(1)
                    expect(form.locator('[data-security-code]')).to_be_hidden()
                    expect(form.locator('[data-security-fields]')).to_be_hidden()
                    expect(form.locator('.ase-feedback')).to_have_text('')
                    expect(form.get_by_role('button', name='Send new code', exact=True)).to_be_enabled()
                    self.assertFalse(page.locator('#adminInviteModal').evaluate('(node)=>node.scrollWidth>node.clientWidth+1'))
                    page.screenshot(path=str(self.artifacts / f'admin-otp-expired-{theme}.png'), animations='disabled')
                    page.get_by_role('button', name='Close admin invitation', exact=True).click()
                page.get_by_role('button', name='Create admin', exact=True).click()
                before_documents = len(documents)
                with patch('app.admin_security.secrets.randbelow', return_value=43):
                    form.get_by_role('button', name='Send new code', exact=True).click()
                    expect(form).to_have_attribute('data-stage', 'code')
                expect(form.locator('[data-security-expired]')).to_be_hidden()
                expect(form.locator('[data-code-expiry]')).to_contain_text('Code expires in 4:')
                expect(form.locator('[data-security-resend]')).to_be_disabled()
                self.assertEqual(len(writes), 1)
                self.assertIn('/invite/resend/', writes[0][0])
                self.assertNotIn('current_password', writes[0][1])
                self.assertEqual(len(mail.outbox), 2)
                self.assertEqual(mail.outbox[-1].to, ['main@example.com'])
                # An old code yields one message and remains in the usable code step.
                self.field(form, '6-digit verification code').fill('000042')
                form.get_by_role('button', name='Verify code and continue', exact=True).click()
                expect(form.locator('.ase-feedback')).to_contain_text('Incorrect code')
                expect(form.locator('.ase-field-error')).to_have_count(0)
                expect(form).to_have_attribute('data-stage', 'code')
                self.field(form, '6-digit verification code').fill('000043')
                form.get_by_role('button', name='Verify code and continue', exact=True).click()
                expect(form.locator('.ase-feedback')).to_contain_text('Invitation sent')
                self.assertEqual(len(documents), before_documents)
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()
        self.assertEqual(AdminInvitation.objects.get().email, 'new-admin@example.com')

    def test_active_code_can_be_resent_directly_after_cooldown(self):
        self.assertEqual(self.client.post(reverse('admin_security_action', args=['invite', 'send']), {
            'first_name': 'Jamie', 'last_name': 'Rivera', 'email': 'new-admin@example.com',
            'phone_number': '09171234567', 'current_password': PASSWORD}).status_code, 200)
        AdminSecurityChallenge.objects.update(created_at=timezone.now() - timedelta(seconds=61))
        with sync_playwright() as p:
            browser, context = self.browser(p); page = context.new_page()
            try:
                page.goto(self.live_server_url + reverse('admin_user_list'))
                page.get_by_role('button', name='Create admin', exact=True).click()
                form = page.locator('#adminInviteModal [data-security-flow]')
                expect(form.get_by_role('button', name='Resend code', exact=True)).to_be_enabled()
                form.get_by_role('button', name='Resend code', exact=True).click()
                expect(form.locator('.ase-feedback')).to_contain_text('A verification code was sent')
                expect(page.locator('.cfg-toast')).to_contain_text('A verification code was sent')
                expect(form.locator('[data-security-resend]')).to_be_disabled()
                expect(form.locator('[data-security-fields]')).to_be_hidden()
                self.assertEqual(len(mail.outbox), 2)
                self.assertEqual(mail.outbox[-1].to, ['main@example.com'])
            finally:
                context.close(); browser.close()

    def test_old_password_proof_restores_details_and_requests_only_password(self):
        self.assertEqual(self.client.post(reverse('admin_security_action', args=['invite', 'send']), {
            'first_name': 'Jamie', 'last_name': 'Rivera', 'email': 'new-admin@example.com',
            'phone_number': '09171234567', 'current_password': PASSWORD}).status_code, 200)
        challenge = AdminSecurityChallenge.objects.get()
        challenge.payload['_reauth_at'] = (timezone.now() - timedelta(minutes=16)).isoformat()
        challenge.expires_at = timezone.now() - timedelta(minutes=1)
        challenge.created_at = timezone.now() - timedelta(minutes=6)
        challenge.save(update_fields=['payload', 'expires_at', 'created_at'])
        with sync_playwright() as p:
            browser, context = self.browser(p); page = context.new_page()
            try:
                page.goto(self.live_server_url + reverse('admin_user_list'))
                page.get_by_role('button', name='Create admin', exact=True).click()
                form = page.locator('#adminInviteModal [data-security-flow]')
                expect(form).to_have_attribute('data-stage', 'details')
                expect(self.field(form, 'First name')).to_have_value('Jamie')
                expect(self.field(form, 'New admin email')).to_have_value('new-admin@example.com')
                expect(self.field(form, 'Your current password')).to_have_value('')
                expect(form.locator('.ase-feedback')).to_contain_text('Confirm your current password')
                self.field(form, 'Your current password').fill(PASSWORD)
                form.get_by_role('button', name='Send authorization code', exact=True).click()
                expect(form).to_have_attribute('data-stage', 'code')
                self.assertEqual(len(mail.outbox), 2)
            finally:
                context.close(); browser.close()
