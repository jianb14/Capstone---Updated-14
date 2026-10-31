"""Real-browser checks for local client feedback and destructive-action safeguards."""
import os
from datetime import date
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings

from .models import Booking, ChatSession, Review, User, UserDesign


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies',
    SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, REQUEST_RATE_LIMITING_ENABLED=False)
class ClientFeedbackBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='feedback-browser', first_name='Jamie',
            email='feedback-browser@example.com', password='Password!25', role='customer', email_verified=True)
        self.booking = Booking.objects.create(user=self.user, event_date=date(2026, 1, 1),
            event_location='Manila', status='completed', total_price=4799)
        self.review = Review.objects.create(user=self.user, booking=self.booking, rating=5, comment='Great setup')
        self.design = UserDesign.objects.create(user=self.user, name='Test design', canvas_json='{"objects":[]}')
        self.chat = ChatSession.objects.create(user=self.user, title='Saved chat')
        self.client.force_login(self.user)
        self.cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value

    def context(self, browser, width=1440, theme='light', authenticated=True):
        context = browser.new_context(viewport={'width': width, 'height': 960}, reduced_motion='reduce')
        context.route('**/*', lambda route: route.continue_()
            if route.request.url.startswith(self.live_server_url+'/') else route.abort())
        context.add_init_script('localStorage.setItem("balloorina-theme", "'+theme+'")')
        if authenticated:
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME, 'value':self.cookie, 'url':self.live_server_url}])
        return context

    def launch(self, pw):
        return pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)

    def test_feedback_layout_keyboard_safety_and_nested_modal_toast(self):
        from playwright.sync_api import sync_playwright, expect
        artifacts = Path(settings.BASE_DIR)/'.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        with sync_playwright() as pw:
            browser = self.launch(pw)
            for width, theme in ((1440,'light'), (1440,'dark'), (375,'light'), (375,'dark')):
                context = self.context(browser, width, theme); page = context.new_page(); errors = []
                page.on('pageerror', lambda error:errors.append(str(error)))
                page.goto(self.live_server_url+'/', wait_until='domcontentloaded')
                self.assertEqual(page.evaluate('typeof Swal'), 'undefined')
                page.evaluate('''() => { window.feedbackResult=null;
                    AppToast.confirm({title:'Delete this item?',text:'This action cannot be undone.',danger:true,
                        confirmText:'Delete items'}).then(r=>window.feedbackResult=r); }''')
                dialog = page.locator('.client-feedback-dialog')
                expect(dialog).to_be_visible()
                expect(dialog.get_by_role('button',name='Cancel',exact=True)).to_be_focused()
                box = dialog.bounding_box()
                self.assertGreaterEqual(box['x'], 0)
                self.assertLessEqual(box['x']+box['width'], width)
                self.assertLessEqual(box['height'], 912)
                color = dialog.get_by_role('button',name='Delete items').evaluate('(e)=>getComputedStyle(e).color')
                self.assertEqual(color, 'rgb(184, 53, 60)' if theme=='light' else 'rgb(241, 145, 145)')
                page.keyboard.press('Tab')
                expect(dialog.get_by_role('button',name='Delete items')).to_be_focused()
                page.evaluate('() => { AppToast.fire({icon:"success",title:"Saved successfully.",timer:0}); }')
                toast = page.locator('.client-feedback-toast')
                expect(toast).to_be_visible()
                self.assertEqual(toast.evaluate('(e)=>getComputedStyle(e).backgroundColor'),
                    'rgb(255, 255, 255)' if theme=='light' else 'rgb(32, 32, 32)')
                toastbox=toast.bounding_box()
                self.assertGreaterEqual(toastbox['x'], 0)
                self.assertLessEqual(toastbox['x']+toastbox['width'],width)
                toast.get_by_role('button',name='Dismiss notification').click()
                expect(toast).to_have_count(0)
                expect(dialog).to_be_visible()
                page.screenshot(path=str(artifacts/f'client-confirm-{theme}-{width}.png'))
                page.keyboard.press('Escape')
                expect(dialog).to_have_count(0)
                self.assertFalse(page.evaluate('window.feedbackResult.isConfirmed'))
                page.evaluate('''() => { AppToast.confirm({title:'Continue?'}).then(r=>window.feedbackResult=r); }''')
                expect(dialog).to_be_visible()
                dialog.get_by_role('button',name='Continue',exact=True).click()
                expect(dialog).to_have_count(0)
                self.assertTrue(page.evaluate('window.feedbackResult.isConfirmed'))
                self.assertEqual(errors,[])
                context.close()
            browser.close()

    def test_toast_queue_dedupe_literal_text_auto_dismiss_and_pointer_pause(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser=self.launch(pw); context=self.context(browser); page=context.new_page()
            page.goto(self.live_server_url+'/',wait_until='domcontentloaded')
            page.evaluate('''() => {
                AppToast.fire({icon:'error',title:'<img src=x onerror=alert(1)>',timer:0});
                AppToast.fire({icon:'error',title:'<img src=x onerror=alert(1)>',timer:0});
                AppToast.fire({icon:'info',title:'Second notification',timer:1500});
            }''')
            toast=page.locator('.client-feedback-toast')
            expect(toast).to_have_count(1)
            expect(toast).to_contain_text('<img src=x onerror=alert(1)>')
            expect(toast.locator('img')).to_have_count(0)
            toast.get_by_role('button',name='Dismiss notification').click()
            expect(toast).to_contain_text('Second notification')
            toast.hover()
            page.wait_for_timeout(1800)
            expect(toast).to_be_visible()
            page.mouse.move(0,0)
            expect(toast).to_have_count(0,timeout=2500)
            context.close(); browser.close()

    def test_booking_change_reason_stays_inline_and_returns_trimmed_valid_value(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser=self.launch(pw); context=self.context(browser); page=context.new_page()
            page.goto(self.live_server_url+'/customer/',wait_until='domcontentloaded')
            page.wait_for_function('typeof window.promptBookingChangeReason === "function"')
            page.evaluate('() => { window.reasonResult="waiting"; promptBookingChangeReason(1).then(r=>window.reasonResult=r); }')
            dialog=page.locator('.client-feedback-dialog'); field=dialog.locator('textarea')
            dialog.get_by_role('button',name='Continue to Changes').click()
            error=dialog.locator('.client-feedback-field-error')
            expect(error).to_be_visible()
            self.assertEqual(field.get_attribute('aria-invalid'),'true')
            self.assertEqual(error.evaluate('(e)=>getComputedStyle(e).color'),'rgb(184, 53, 60)')
            spacing=error.bounding_box()['y']-(field.bounding_box()['y']+field.bounding_box()['height'])
            self.assertGreaterEqual(spacing,6); self.assertLessEqual(spacing,9)
            field.fill('  More guests will attend our event.  ')
            expect(error).to_be_hidden()
            dialog.get_by_role('button',name='Continue to Changes').click()
            expect(dialog).to_have_count(0)
            self.assertEqual(page.evaluate('window.reasonResult'),'More guests will attend our event.')
            context.close(); browser.close()

    def test_review_delete_requires_confirmation_and_reports_html_failure_once(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser=self.launch(pw); context=self.context(browser); page=context.new_page(); posts=[]
            page.on('request',lambda r:posts.append(r.url) if r.method=='POST' and '/delete/' in r.url else None)
            page.goto(self.live_server_url+'/my-reviews/',wait_until='domcontentloaded')
            page.evaluate('window.pageSentinel=42')
            def open_delete():
                page.evaluate('(id)=>{ReviewPage.deleteReview(id)}',self.review.pk)
                expect(page.locator('.client-feedback-dialog')).to_be_visible()
            open_delete()
            page.get_by_role('button',name='Cancel',exact=True).click()
            expect(page.locator('.client-feedback-dialog')).to_have_count(0)
            self.assertEqual(posts,[])
            page.route('**/reviews/*/delete/',lambda route:route.fulfill(status=500,body='<html>Unavailable</html>',content_type='text/html'))
            open_delete()
            page.get_by_role('button',name='Delete review',exact=True).click()
            expect(page.locator('.client-feedback-toast')).to_contain_text('Could not delete your review.')
            expect(page.locator('.client-feedback-toast')).to_have_count(1)
            self.assertEqual(len(posts),1)
            page.unroute('**/reviews/*/delete/')
            page.locator('.client-feedback-toast button').click()
            open_delete()
            page.get_by_role('button',name='Delete review',exact=True).click()
            expect(page.locator('.client-feedback-toast')).to_contain_text('deleted')
            expect(page.locator('[data-review-page-content]')).not_to_contain_text('Great setup')
            self.assertEqual(page.evaluate('window.pageSentinel'),42)
            context.close(); browser.close()
        self.assertFalse(Review.objects.filter(pk=self.review.pk).exists())

    def test_ai_chat_deletion_failure_keeps_chat_and_success_updates_sidebar(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser=self.launch(pw); context=self.context(browser); page=context.new_page()
            page.goto(self.live_server_url+'/',wait_until='domcontentloaded')
            page.locator('#ai-fab').click()
            delete=page.get_by_role('button',name='Delete chat: Saved chat',exact=True)
            expect(delete).to_be_visible()
            page.route('**/api/chat/clear/',lambda route:route.fulfill(status=500,body='<html>Error</html>',content_type='text/html'))
            delete.click()
            page.get_by_role('button',name='Delete chat',exact=True).click()
            expect(page.locator('.client-feedback-toast')).to_contain_text('Could not delete your chat.')
            expect(delete).to_be_visible(); expect(delete).to_be_enabled()
            page.locator('.client-feedback-toast button').click()
            page.unroute('**/api/chat/clear/')
            delete.click()
            page.get_by_role('button',name='Delete chat',exact=True).click()
            expect(delete).to_have_count(0)
            expect(page.locator('.client-feedback-toast')).to_contain_text('Your chat has been deleted.')
            context.close(); browser.close()
        self.assertFalse(ChatSession.objects.filter(pk=self.chat.pk).exists())

    def test_design_rename_failure_and_delete_feedback_survives_existing_refresh(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser=self.launch(pw); context=self.context(browser); page=context.new_page()
            page.goto(self.live_server_url+'/my-designs/',wait_until='domcontentloaded')
            page.evaluate('(id)=>openRenameModal(id,"Test design")',self.design.pk)
            page.locator('#renameInput').fill('Renamed design')
            page.route('**/my-designs/rename/*/',lambda route:route.fulfill(status=500,body='<html>Error</html>',content_type='text/html'))
            page.get_by_role('button',name='Save Name',exact=True).click()
            expect(page.locator('.client-feedback-toast')).to_contain_text('Could not rename this design.')
            expect(page.locator('#renameModal')).to_be_visible()
            expect(page.locator('#title-'+str(self.design.pk))).to_have_text('Test design')
            page.locator('.client-feedback-toast button').click()
            page.unroute('**/my-designs/rename/*/')
            page.get_by_role('button',name='Save Name',exact=True).click()
            expect(page.locator('.client-feedback-toast')).to_contain_text('Design renamed successfully.')
            page.locator('.client-feedback-toast button').click()
            page.evaluate('(id)=>{openDeleteModal(id,"Renamed design")}',self.design.pk)
            page.get_by_role('button',name='Delete design',exact=True).click()
            expect(page.locator('.client-feedback-toast')).to_contain_text('Design deleted successfully')
            expect(page.locator('#title-'+str(self.design.pk))).to_have_count(0)
            self.assertIsNone(page.evaluate('sessionStorage.getItem("client-feedback-next")'))
            context.close(); browser.close()
        self.assertFalse(UserDesign.objects.filter(pk=self.design.pk).exists())

    def test_login_validation_and_error_feedback_in_both_themes(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = self.launch(pw)
            for theme in ('light', 'dark'):
                context = self.context(browser, 375, theme, authenticated=False)
                page = context.new_page(); errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url+'/login/', wait_until='domcontentloaded')
                page.locator('#loginForm button[type="submit"]').click()
                expect(page.locator('#loginForm .field-error').first).to_contain_text('required')
                expect(page.locator('.client-feedback-toast')).to_have_count(0)
                page.locator('#email').fill(self.user.email)
                page.locator('#password').fill('Wrong-password!25')
                page.locator('#loginForm button[type="submit"]').click()
                toast = page.locator('.client-feedback-toast')
                expect(toast).to_be_visible()
                self.assertEqual(toast.get_attribute('data-kind'), 'error')
                self.assertEqual(toast.evaluate('(e)=>getComputedStyle(e).backgroundColor'),
                    'rgb(255, 255, 255)' if theme=='light' else 'rgb(32, 32, 32)')
                page.screenshot(path=str(Path(settings.BASE_DIR)/'.booking-followup-check'/f'client-login-feedback-{theme}.png'))
                toast.get_by_role('button', name='Dismiss notification').click()
                expect(toast).to_have_count(0)
                self.assertEqual(errors, [])
                context.close()
            browser.close()

    def test_multiple_server_messages_execute_and_queue_once(self):
        from django.contrib.messages import constants, Message
        from django.template.loader import render_to_string
        from django.test import RequestFactory
        from playwright.sync_api import sync_playwright, expect
        request = RequestFactory().get('/feedback-check/')
        request.user = self.user; request.session = {}
        html = render_to_string('client/base.html', {'user':self.user, 'messages':[
            Message(constants.SUCCESS, 'First queued update'),
            Message(constants.ERROR, 'Second queued update'),
        ]}, request=request)
        with sync_playwright() as pw:
            browser = self.launch(pw); context = self.context(browser)
            page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/feedback-check/', lambda route: route.fulfill(body=html, content_type='text/html'))
            page.goto(self.live_server_url+'/feedback-check/', wait_until='domcontentloaded')
            toast = page.locator('.client-feedback-toast')
            expect(toast).to_contain_text('First queued update')
            toast.get_by_role('button', name='Dismiss notification').click()
            expect(toast).to_contain_text('Second queued update')
            self.assertEqual(errors, [])
            context.close(); browser.close()
