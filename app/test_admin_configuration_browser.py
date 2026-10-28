"""Opt-in browser checks for async settings and profile verification."""
import os
import re
from datetime import timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import EmailOTPChallenge, ServiceChargeConfig, SiteSettings, User


@skipUnless(os.environ.get('RUN_CONFIGURATION_BROWSER') == '1', 'Optional settings/profile browser checks')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AdminConfigurationBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='configuration-browser', role='admin', email_verified=True,
            first_name='Jamie', last_name='Rivera', email='configuration@example.com', phone_number='09171234567', password='ExistingPassword!25')
        self.client.force_login(self.admin)
        SiteSettings.load()
        ServiceChargeConfig.objects.create(pk=1, amount=1000, notes='Original notes.', shop_lat='14.4', shop_lng='120.9')
        self.artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'

    def browser(self, p):
        browser = p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width':1440,'height':1000})
        context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
        context.add_init_script("localStorage.setItem('balloorina-theme','light')")
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url) else
            route.fulfill(status=200, content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}})};') if 'sweetalert2' in route.request.url else route.abort())
        return browser, context

    def test_feedback_timer_resumes_remaining_time_and_old_exit_cannot_hide_new_result(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.live_server_url+reverse('admin_site_settings'))
                page.clock.install()
                page.clock.pause_at(timezone.now()+timedelta(seconds=1))
                page.mouse.move(0,0)
                toast=page.locator('.cfg-toast')
                page.evaluate("AdminConfigurationFeedback.show('Settings saved.')")
                page.clock.fast_forward(2990)
                expect(toast).to_have_class(re.compile('is-visible'))
                page.clock.fast_forward(20)
                expect(toast).to_have_class(re.compile('is-leaving'))
                self.assertEqual(toast.evaluate('el=>getComputedStyle(el).animationName'),'cfg-toast-exit')
                page.clock.fast_forward(200);expect(toast).to_be_hidden()

                page.evaluate("AdminConfigurationFeedback.show('Paused feedback.')")
                page.clock.run_for(300);page.clock.fast_forward(1700)
                toast.hover();page.clock.fast_forward(5000)
                expect(toast).to_contain_text('Paused feedback.')
                page.mouse.move(0,0);page.clock.fast_forward(990)
                expect(toast).not_to_have_class(re.compile('is-leaving'))
                page.clock.fast_forward(20)
                expect(toast).to_have_class(re.compile('is-leaving'))
                # A newer result during the fade-out must survive the old exit timer.
                page.evaluate("AdminConfigurationFeedback.show('Newest result.')")
                page.clock.fast_forward(250)
                expect(toast).to_have_class(re.compile('is-visible'))
                expect(toast).to_contain_text('Newest result.')
                page.clock.fast_forward(2800);page.clock.fast_forward(200)
                expect(toast).to_be_hidden()

                page.evaluate("AdminConfigurationFeedback.show('Keyboard pause.')")
                toast.locator('button').focus();page.clock.fast_forward(5000)
                expect(toast).to_be_visible()
                toast.locator('button').evaluate('el=>el.blur()');page.clock.run_for(20)
                page.clock.fast_forward(3010);page.clock.fast_forward(200)
                expect(toast).to_be_hidden()

                page.emulate_media(reduced_motion='reduce')
                page.evaluate("AdminConfigurationFeedback.show('Reduced motion.')")
                self.assertEqual(toast.evaluate('el=>getComputedStyle(el).animationName'),'none')
                page.evaluate('AdminConfigurationFeedback.hide()')
                expect(toast).to_be_hidden()
                self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_settings_async_validation_save_dirty_tracking_and_reset(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser, context = self.browser(p); page = context.new_page(); errors=[]; documents=[]
            page.on('pageerror',lambda error: errors.append(str(error)))
            page.on('request',lambda req:documents.append(req.url) if req.resource_type=='document' else None)
            try:
                page.goto(self.live_server_url + reverse('admin_site_settings'))
                original_lat = page.locator('#ss_shop_lat').input_value()
                save = page.locator('#ss_btn_save'); expect(save).to_be_disabled()
                page.locator('#ss_site_name').fill('Browser business')
                page.locator('#ss_logistics_notes').fill('Browser logistics')
                page.locator('#ss_max_saved_designs').fill('0')
                save.click()
                expect(page.locator('[data-error-for=max_saved_designs]')).not_to_be_empty()
                expect(page.locator('#ss_site_name')).to_have_value('Browser business')
                page.locator('#ss_max_saved_designs').fill('32')
                page.locator('#ss_admin_emails').fill('wrong-email')
                save.click(); expect(page.locator('[data-error-for=admin_emails_for_notifications]')).not_to_be_empty()
                page.locator('#ss_admin_emails').fill('updates@example.com')
                save.click(); expect(page.locator('#ss_feedback')).to_have_text('All site settings saved successfully.')
                expect(save).to_be_disabled()
                page.locator('#ss_site_name').fill('Not saved')
                page.locator('#ss_reset').click(); expect(page.locator('#ss_site_name')).to_have_value('Browser business')
                expect(save).to_be_disabled()
                # An edited address must not retain stale coordinates when the map is offline.
                page.locator('#ss_address').fill('A new shop address')
                expect(page.locator('#ss_shop_lat')).to_have_value('')
                page.locator('#ss_reset').click(); expect(page.locator('#ss_shop_lat')).to_have_value(original_lat)
                self.assertEqual(len(documents),1); self.assertEqual(errors,[])
            finally: context.close(); browser.close()
        self.assertEqual(SiteSettings.load().max_saved_designs,32)
        self.assertEqual(ServiceChargeConfig.objects.get(pk=1).notes,'Browser logistics')

    def test_settings_and_profile_theme_layouts_and_password_dialog(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser,context=self.browser(p); page=context.new_page(); errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                for route in ('admin_site_settings','admin_profile'):
                    page.goto(self.live_server_url+reverse(route))
                    for theme in ('light','dark'):
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                        for width in (1440,900,390,320):
                            page.set_viewport_size({'width':width,'height':950})
                            page.wait_for_timeout(100)
                            self.assertLessEqual(page.locator('.cfg-workspace').evaluate('el=>el.scrollWidth-el.clientWidth'),1)
                            if route=='admin_site_settings':
                                field=page.locator('#ss_contact_email'); field.focus()
                                expect(field).to_have_css('outline-offset','2px')
                                page.locator('#ss_btn_save').scroll_into_view_if_needed()
                                self.assertTrue(page.locator('.cfg-savebar').evaluate('el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}'))
                                page.evaluate('scrollTo(0,0)')
                            else:
                                page.evaluate('scrollTo(0,0)')
                                page.get_by_role('button',name='Change Password',exact=True).click()
                                dialog=page.locator('#adminPasswordModal'); expect(dialog).to_be_visible()
                                self.assertLessEqual(dialog.evaluate('el=>el.scrollWidth-el.clientWidth'),1)
                                expect(page.get_by_role('button',name='Show current password',exact=True)).to_be_visible()
                                page.locator('#id_old_password').fill('Sensitive password')
                                page.get_by_role('button',name='Show current password',exact=True).click()
                                expect(page.locator('#id_old_password')).to_have_attribute('type','text')
                                page.screenshot(path=str(self.artifacts/f'admin-profile-dialog-{theme}-{width}.png'),animations='disabled')
                                page.get_by_role('button',name='Close password change',exact=True).click()
                                expect(page.locator('#id_old_password')).to_have_value('')
                                expect(page.locator('#id_old_password')).to_have_attribute('type','password')
                                page.evaluate('scrollTo(0,0)')
                            if width in (1440,390): page.screenshot(path=str(self.artifacts/f'{route}-redesign-{theme}-{width}.png'),animations='disabled')
                self.assertEqual(errors,[])
            finally: context.close(); browser.close()

    def test_password_code_flow_is_inline_numeric_and_keeps_the_document(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser,context=self.browser(p); page=context.new_page(); errors=[]; documents=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda req:documents.append(req.url) if req.resource_type=='document' else None)
            try:
                page.goto(self.live_server_url+reverse('admin_profile'))
                page.get_by_role('button',name='Change Password',exact=True).click()
                submit=page.locator('#btnSavePassword'); submit.click()
                expect(page.locator('[data-error-for=old_password]')).to_have_text('Current password is required.')
                page.locator('#id_old_password').fill('WrongPassword!25')
                page.locator('#id_new_password1').fill('NewPassword!26')
                page.locator('#id_new_password2').fill('NewPassword!26')
                submit.click(); expect(page.locator('[data-error-for=old_password]')).not_to_be_empty()
                page.locator('#id_old_password').fill('ExistingPassword!25'); submit.click()
                expect(page.locator('#apPasswordCodeForm')).to_be_visible()
                expect(page.locator('#apCodeRecipient')).to_contain_text('c***@example.com')
                expect(page.locator('#apResendCode')).to_be_disabled()
                expect(page.locator('.cfg-toast')).to_be_hidden()
                code=re.search(r'(?m)^\d{6}$',mail.outbox[-1].body).group()
                digit=page.get_by_label('Digit 1 of 6',exact=True)
                digit.fill('a'); expect(digit).to_have_value('')
                digit.evaluate('(el,code)=>{const data=new DataTransfer();data.setData("text",code);el.dispatchEvent(new ClipboardEvent("paste",{bubbles:true,clipboardData:data}));}',code)
                expect(page.get_by_label('Digit 6 of 6',exact=True)).to_have_value(code[-1])
                page.screenshot(path=str(self.artifacts/'admin-profile-password-code.png'),animations='disabled')
                submit.click(); expect(page.locator('#adminPasswordModal')).to_be_hidden()
                expect(page.locator('#apFeedback')).to_contain_text('successfully updated')
                expect(page.locator('.cfg-toast')).to_be_visible()
                expect(page.locator('.cfg-toast')).to_contain_text('successfully updated')
                page.screenshot(path=str(self.artifacts/'admin-profile-password-saved-feedback.png'),animations='disabled')
                self.assertEqual(len(documents),1); self.assertEqual(errors,[])
            finally: context.close(); browser.close()
        self.admin.refresh_from_db(); self.assertTrue(self.admin.check_password('NewPassword!26'))

    def test_expired_password_code_can_restart_without_duplicate_error_messages(self):
        from playwright.sync_api import sync_playwright, expect
        self.client.post(reverse('change_password'),{'old_password':'ExistingPassword!25',
            'new_password1':'NewPassword!26','new_password2':'NewPassword!26'},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        EmailOTPChallenge.objects.filter(user=self.admin).update(expires_at=timezone.now()-timedelta(seconds=1))
        with sync_playwright() as p:
            browser,context=self.browser(p); page=context.new_page()
            try:
                page.goto(self.live_server_url+reverse('admin_profile'))
                page.get_by_role('button',name='Change Password',exact=True).click()
                expect(page.locator('#apCodeExpired')).to_be_visible()
                expect(page.locator('#btnSavePassword')).to_be_disabled()
                expect(page.locator('#apCodeError')).to_be_empty()
                expect(page.locator('#apPasswordFeedback')).to_be_empty()
                page.locator('#apEditPassword').click()
                expect(page.locator('#adminChangePasswordForm')).to_be_visible()
                expect(page.locator('#btnSavePassword')).to_be_enabled()
            finally: context.close(); browser.close()

    def test_settings_shop_map_pin_reset_and_save_with_local_leaflet(self):
        from playwright.sync_api import sync_playwright, expect
        leaflet = self.artifacts/'leaflet.js'
        leaflet_css = self.artifacts/'leaflet.css'
        if not leaflet.exists() or not leaflet_css.exists():
            self.skipTest('Local Leaflet fixture is unavailable')
        with sync_playwright() as p:
            browser,context=self.browser(p); page=context.new_page(); errors=[]
            context.route('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',lambda route:route.fulfill(path=str(leaflet),content_type='application/javascript'))
            context.route('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',lambda route:route.fulfill(path=str(leaflet_css),content_type='text/css'))
            context.route('**'+reverse('booking_place_reverse')+'**',lambda route:route.fulfill(json={'results':[{'display_name':'Pinned shop address'}]}))
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.live_server_url+reverse('admin_site_settings'))
                expect(page.locator('#ss_shop_map')).to_have_class(re.compile('leaflet-container'))
                original=page.locator('#ss_shop_lat').input_value()
                expect(page.locator('#ss_btn_save')).to_be_disabled()
                page.locator('#ss_shop_map').click(position={'x':100,'y':90})
                expect(page.locator('#ss_address')).to_have_value('Pinned shop address')
                expect(page.locator('#ss_btn_save')).to_be_enabled()
                expect(page.locator('#ss_shop_lat')).not_to_have_value(original)
                self.assertTrue(page.locator('#ss_shop_lat').input_value())
                page.locator('#ss_reset').click()
                expect(page.locator('#ss_shop_lat')).to_have_value(original)
                expect(page.locator('#ss_btn_save')).to_be_disabled()
                page.locator('#ss_shop_map').click(position={'x':120,'y':90})
                expect(page.locator('#ss_address')).to_have_value('Pinned shop address')
                self.assertTrue(page.locator('#ss_shop_lat').input_value())
                page.locator('#ss_btn_save').click()
                expect(page.locator('#ss_feedback')).to_have_text('All site settings saved successfully.')
                self.assertEqual(errors,[])
                page.screenshot(path=str(self.artifacts/'admin-settings-map-save.png'),animations='disabled')
            finally: context.close(); browser.close()
