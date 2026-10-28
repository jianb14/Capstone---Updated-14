"""Real browser verification using only isolated test accounts and mail."""
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.core import mail
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import Booking, User


@skipUnless(os.environ.get('RUN_PROFILE_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class ProfileDeletionBrowserTests(StaticLiveServerTestCase):
    def test_reopening_while_status_is_loading_ignores_the_cancelled_request(self):
        from playwright.sync_api import expect, sync_playwright

        user = User.objects.create_user(username='deletion-reopen', email='reopen@example.com',
            password='ExistingPassword!25', role='customer', email_verified=True)
        self.client.force_login(user)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(reduced_motion='reduce')
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            page = context.new_page()
            try:
                page.goto(self.live_server_url + reverse('my_profile'), wait_until='domcontentloaded')
                # Close and reopen before the aborted first fetch can finish its catch/finally.
                page.evaluate('''() => {
                    const fetch = window.fetch.bind(window);
                    let pending = 0;
                    window.fetch = (url, options) => {
                        if (String(url).includes('/my-profile/deletion-status/') && ++pending <= 2) {
                            return new Promise((resolve, reject) => {
                                options.signal.addEventListener('abort', () =>
                                    reject(new DOMException('Aborted', 'AbortError')), {once: true});
                                window.finishDeletionStatus = () => resolve(new Response(JSON.stringify({
                                    success: true, blockers: [], can_delete: true, step: 'password',
                                    masked_email: 'r***@example.com', resend_wait: 0,
                                    has_password: true, email_verified: true
                                }), {headers: {'Content-Type': 'application/json'}}));
                            });
                        }
                        return fetch(url, options);
                    };
                    const button = document.getElementById('deleteAccountButton');
                    const dialog = document.getElementById('deleteAccountDialog');
                    button.click(); dialog.close(); button.click();
                }''')
                page.wait_for_function('document.getElementById("deleteAccountDialog").open')
                expect(page.locator('#deletionLoading')).to_be_visible()
                expect(page.locator('#deletionFeedback')).to_be_hidden()
                expect(page.locator('#deletionSubmit')).to_be_disabled()
                page.evaluate('window.finishDeletionStatus()')
                expect(page.locator('#deletionPassword')).to_be_visible()
                expect(page.locator('#deletionSubmit')).to_be_enabled()
                expect(page.locator('#deletionFeedback')).to_be_hidden()
                expect(page.locator('body')).to_have_css('overflow', 'hidden')
                page.locator('#deletionPassword').fill('Password that must be cleared')
                page.get_by_role('button', name='Show account password', exact=True).click()
                page.evaluate('''() => {
                    document.getElementById('deleteAccountDialog').close();
                    document.getElementById('deleteAccountButton').click();
                }''')
                expect(page.locator('#deletionPassword')).to_be_visible()
                expect(page.locator('#deletionPassword')).to_have_value('')
                expect(page.locator('#deletionPassword')).to_have_attribute('type', 'password')
                page.get_by_role('button', name='Keep my account', exact=True).click()
                expect(page.locator('#deleteAccountDialog')).not_to_be_visible()
                page.wait_for_function('document.body.style.overflow !== "hidden"')

                # A real current-request failure must still offer a working retry.
                page.unroute('**/my-profile/deletion-status/')
                page.route('**/my-profile/deletion-status/', lambda route: route.fulfill(
                    status=503, json={'success': False, 'message': 'Unavailable'}))
                page.locator('#deleteAccountButton').click()
                expect(page.locator('#deletionFeedback')).to_contain_text('could not check')
                expect(page.locator('#deletionSubmit')).to_be_enabled()
                page.unroute('**/my-profile/deletion-status/')
                page.locator('#deletionSubmit').click()
                expect(page.locator('#deletionPassword')).to_be_visible()
            finally:
                page.unroute('**/my-profile/deletion-status/')
                context.close()
                browser.close()

    def test_responsive_profile_deletion_blockers_verification_and_final_confirmation(self):
        from playwright.sync_api import expect, sync_playwright

        user=User.objects.create_user(username='deletion-browser',email='delete-browser@example.com',
            first_name='Jamie',last_name='Rivera',phone_number='09170000000',
            password='ExistingPassword!25',role='customer',email_verified=True)
        booking=Booking.objects.create(user=user,event_date=date(2026,1,1),event_type='Birthday',
            event_location='Private home',status='confirmed',total_price=0)
        self.client.force_login(user)
        artifacts=Path(settings.BASE_DIR)/'.booking-followup-check'; artifacts.mkdir(exist_ok=True)
        with sync_playwright() as playwright, ThreadPoolExecutor(max_workers=1) as executor:
            browser=playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,
                'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            context.route('https://fonts.googleapis.com/**',lambda route:route.abort())
            sweetalert=artifacts/'sweetalert2.all.min.js'
            if sweetalert.exists():
                context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11',lambda route:route.fulfill(
                    content_type='application/javascript',body=sweetalert.read_text(encoding='utf-8')))
            page=context.new_page(); errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.live_server_url+reverse('my_profile'),wait_until='domcontentloaded')
                page.evaluate("window.deletionPageSentinel='persistent'")
                page.locator('[data-account-key="my_reviews"]').click()
                expect(page.locator('#accountContent')).to_have_attribute('data-account-page','my_reviews')
                page.wait_for_function('!window.AccountNavigation.navigating')
                page.locator('[data-account-key="my_profile"]').click()
                expect(page.locator('#accountContent')).to_have_attribute('data-account-page','my_profile')
                page.wait_for_function('!window.AccountNavigation.navigating')
                self.assertEqual(page.evaluate('window.deletionPageSentinel'),'persistent')
                dialog=page.locator('#deleteAccountDialog')
                for theme in ('light','dark'):
                    for width,height in ((1440,1000),(390,844),(320,568),(640,360)):
                        page.set_viewport_size({'width':width,'height':height})
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                        page.wait_for_function('document.documentElement.scrollWidth<=innerWidth+1')
                        overflow=page.evaluate('''() => [...document.querySelectorAll('body *')].filter(el=>{
                            const r=el.getBoundingClientRect(); return r.width && r.right>innerWidth+1;
                        }).slice(0,12).map(el=>({tag:el.tagName,cls:el.className,right:el.getBoundingClientRect().right}))''')
                        self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth+1'),(theme,width,overflow))
                        page.evaluate('scrollTo(0,0)')
                        page.screenshot(path=str(artifacts/f'profile-overview-{theme}-{width}.png'),animations='disabled')
                        page.locator('#deleteAccountButton').click()
                        expect(page.locator('#deletionBlockers')).to_be_visible()
                        expect(page.locator('#deletionSubmit')).to_be_disabled()
                        expect(page.locator('#deletionBlockerList')).to_contain_text('still active')
                        bounds=dialog.bounding_box()
                        self.assertGreaterEqual(bounds['x'],0); self.assertGreaterEqual(bounds['y'],0)
                        self.assertLessEqual(bounds['x']+bounds['width'],width)
                        self.assertLessEqual(bounds['y']+bounds['height'],height)
                        expect(page.get_by_role('button',name='Keep my account',exact=True)).to_be_in_viewport()
                        page.screenshot(path=str(artifacts/f'profile-deletion-blocked-{theme}-{width}.png'),animations='disabled')
                        page.keyboard.press('Escape'); expect(dialog).not_to_be_visible()
                        expect(page.locator('#deleteAccountButton')).to_be_focused()
                executor.submit(lambda:Booking.objects.filter(pk=booking.pk).update(status='cancelled')).result()
                page.set_viewport_size({'width':390,'height':844})
                page.locator('#deleteAccountButton').click()
                expect(page.locator('#deletionPassword')).to_be_visible()
                page.locator('#deletionSubmit').click()
                expect(page.locator('#deletionFeedback')).to_contain_text('current password')
                page.locator('#deletionPassword').fill('Incorrect')
                page.locator('#deletionSubmit').click()
                expect(page.locator('#deletionFeedback')).to_contain_text('incorrect')
                page.locator('#deletionPassword').fill('ExistingPassword!25')
                page.get_by_role('button',name='Show account password',exact=True).click()
                expect(page.locator('#deletionPassword')).to_have_attribute('type','text')
                page.locator('#deletionSubmit').click()
                expect(page.locator('#deletionCode')).to_be_visible()
                expect(page.locator('#deletionResend')).to_be_disabled()
                self.assertFalse(executor.submit(lambda:User.objects.get(pk=user.pk).deleted_at is not None).result())
                code=re.search(r'\b\d{6}\b',mail.outbox[-1].body)[0]
                page.locator('#deletionCode').fill('111111' if code!='111111' else '222222')
                page.locator('#deletionSubmit').click()
                expect(page.locator('#deletionFeedback')).to_contain_text('incorrect or expired')
                page.keyboard.press('Escape')
                page.locator('#deleteAccountButton').click()
                expect(page.locator('#deletionCode')).to_be_visible()
                page.locator('#deletionCode').fill(code); page.locator('#deletionSubmit').click()
                expect(page.locator('#deletionConfirmStep')).to_be_visible()
                self.assertFalse(executor.submit(lambda:User.objects.get(pk=user.pk).deleted_at is not None).result())
                page.locator('#deletionSubmit').click()
                expect(page.locator('#deletionFeedback')).to_contain_text('permanent')
                page.locator('#deletionAcknowledge').check()
                page.screenshot(path=str(artifacts/'profile-deletion-confirm-mobile.png'),animations='disabled')
                page.locator('#deletionSubmit').click()
                page.wait_for_url('**/account-deleted/')
                expect(page.get_by_role('heading',name='Your account has been deleted')).to_be_visible()
                self.assertTrue(executor.submit(lambda:User.objects.get(pk=user.pk).deleted_at is not None).result())
                self.assertEqual(errors,[])
            finally:
                context.close(); browser.close()
