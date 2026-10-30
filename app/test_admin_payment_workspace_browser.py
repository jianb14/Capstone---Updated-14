"""Real-browser checks of payment actions through the existing Django endpoints."""
import os
from datetime import time, timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Booking, GCashConfig, Notification, Payment, User


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies', REQUEST_RATE_LIMITING_ENABLED=False)
class AdminPaymentWorkspaceBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='payments-admin', role='admin')
        self.config = GCashConfig.objects.create(downpayment_percent=20)
        self.customer = User.objects.create_user(username='payments-customer', first_name="Jamie O'Neil", role='customer')
        self.bookings = []
        for index in range(4):
            self.bookings.append(Booking.objects.create(user=self.customer,
                event_date=timezone.localdate()+timedelta(days=30+index), event_time=time(10),
                event_type='Birthday', event_location='Venue', package_type='Package A',
                total_price=6000, status='confirmed'))
        self.pending = [Payment.objects.create(booking=self.bookings[0], amount=1000,
            payment_method='gcash', payment_type='downpayment', payment_status='pending',
            transaction_ref=f'pending-proof-{index}') for index in range(8)]
        self.paid = Payment.objects.create(booking=self.bookings[1], amount=6000,
            payment_method='gcash', payment_type='full', payment_status='verified', transaction_ref='paid-history')
        Payment.objects.create(booking=self.bookings[2], amount=1000,
            payment_method='gcash', payment_type='downpayment', payment_status='verified', transaction_ref='partial-history')
        self.pending[-1].receipt_image.save('proof.svg', SimpleUploadedFile('proof.svg',
            b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="300"><rect width="200" height="300" fill="white"/></svg>',
            content_type='image/svg+xml'))
        stamp = timezone.now()
        for index, payment in enumerate(self.pending):
            Payment.objects.filter(pk=payment.pk).update(created_at=stamp+timedelta(seconds=index))
        self.client.force_login(self.admin)
        self.cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.artifacts = Path(settings.BASE_DIR)/'.booking-followup-check'
        self.artifacts.mkdir(exist_ok=True)

    def context(self, browser, width=1440, height=1000, theme='light'):
        context = browser.new_context(viewport={'width':width, 'height':height}, reduced_motion='reduce')
        def external(route):
            if route.request.url.startswith(self.live_server_url+'/'):
                route.continue_()
            elif 'sweetalert' in route.request.url:
                route.fulfill(body='window.Swal={mixin:()=>({fire:()=>{}}),fire:()=>Promise.resolve({}),DismissReason:{}};', content_type='application/javascript')
            else:
                route.abort()
        context.route('**/*', external)
        context.add_init_script('localStorage.setItem("balloorina-theme", "'+theme+'")')
        context.add_cookies([{'name':settings.SESSION_COOKIE_NAME, 'value':self.cookie, 'url':self.live_server_url}])
        return context

    def test_async_search_pagination_details_verify_reject_reminders_and_receipt(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            context = self.context(browser); page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(self.live_server_url+reverse('admin_payment_list'), wait_until='domcontentloaded')
            page.evaluate('window.paymentSentinel=42')
            expect(page.locator('#pmSection-pending tbody tr')).to_have_count(8)
            page.locator('#pmSection-pending .account-page-size .ac-select-trigger').click()
            page.get_by_role('option', name='4', exact=True).click()
            expect(page.locator('#pmSection-pending tbody tr')).to_have_count(4)
            page.locator('#pmSection-pending').get_by_role('link', name='Next page').click()
            page.wait_for_url('**pending_page=2*')
            expect(page.locator('#pmSection-pending tbody tr')).to_have_count(4)
            self.assertIn('pending_page=2', page.url)
            page.go_back()
            expect(page.locator('#pmSection-pending tbody tr')).to_have_count(4)
            self.assertIn('per_page=4', page.url)
            search = page.get_by_role('searchbox', name='Search payments')
            search.fill('paid-history')
            expect(page.locator('#pmSection-history tbody tr')).to_have_count(1)
            expect(search).to_be_focused()
            page.get_by_role('button', name='Clear search').click()
            expect(page.locator('#pmSection-history tbody tr')).to_have_count(2)
            search.fill('no-matching-reference')
            expect(page.locator('#pmSection-history .account-empty-state')).to_be_visible()
            expect(page.locator('#pmSection-history thead')).to_have_count(0)
            expect(page.locator('#pmSection-history .account-table-footer')).to_have_count(0)
            page.locator('#pmSection-history').get_by_role('button', name='Clear filters').click()
            expect(page.locator('#pmSection-history tbody tr')).to_have_count(2)
            page.get_by_role('link', name='Payment Settings', exact=True).click()
            expect(page.locator('#pmSettingsForm')).to_be_visible()
            page.locator('#pmDownpayment').fill('101')
            page.locator('#pmSettingsSave').click()
            expect(page.locator('#pmPercentError')).to_be_visible()
            expect(page.locator('#pmSettingsDialog')).to_be_visible()
            page.locator('#pmDownpayment').fill('30')
            page.locator('#pmSettingsSave').click()
            expect(page.locator('#pmSettingsDialog')).to_be_hidden()
            expect(page.locator('#pmSection-unpaid tbody')).to_contain_text('1800.00')
            expect(page.locator('.cfg-toast')).to_contain_text('Payment settings saved successfully.')
            page.wait_for_function('!document.querySelector("#pmQueues").hasAttribute("aria-busy")')
            first = page.locator('#pmSection-pending tbody tr').first
            first.get_by_role('link', name='View payment', exact=True).click()
            expect(page.locator('#pmDetailDialog')).to_be_visible()
            expect(page.locator('#pmDetailBody')).to_contain_text('Payment Information')
            page.locator('[data-payment-receipt]').click()
            expect(page.locator('#pmReceiptDialog')).to_be_visible()
            page.keyboard.press('Escape')
            expect(page.locator('#pmReceiptDialog')).to_be_hidden()
            page.locator('#pmDetailDialog').get_by_role('link', name='Approve Payment', exact=True).click()
            page.locator('#pmConfirmDialog').get_by_role('button', name='Approve Payment', exact=True).click()
            expect(page.locator('#pmConfirmDialog')).to_be_hidden()
            expect(page.locator('#pmDetailBody .pd-amount-row')).to_contain_text('Verified')
            page.keyboard.press('Escape')
            expect(page.locator('#pmSection-pending .pm-count')).to_have_text('7')
            first = page.locator('#pmSection-pending tbody tr').first
            first.get_by_role('button', name='Reject payment', exact=True).click()
            page.locator('#pmRejectReason').fill('   ')
            page.locator('#pmConfirmSubmit').click()
            expect(page.locator('#pmConfirmDialog')).to_be_visible()
            self.assertFalse(page.locator('#pmRejectReasonChoice').evaluate('(e)=>e.checkValidity()'))
            expect(page.locator('#pmReasonError')).to_have_text('Choose a reason before continuing.')
            page.get_by_role('button', name='Payment rejection reason: Choose a reason', exact=True).click()
            page.get_by_role('option', name='Payment amount does not match', exact=True).click()
            page.locator('#pmRejectReason').fill('Receipt amount does not match')
            page.locator('#pmConfirmSubmit').click()
            expect(page.locator('#pmConfirmDialog')).to_be_hidden()
            expect(page.locator('#pmSection-pending .pm-count')).to_have_text('6')
            expect(page.locator('#pmFeedback')).to_contain_text('rejected')
            page.locator('#pmSection-unpaid').get_by_role('button', name='Send payment reminder').first.click()
            page.locator('#pmConfirmSubmit').click()
            expect(page.locator('#pmConfirmDialog')).to_be_hidden()
            expect(page.locator('#pmFeedback')).to_contain_text('Payment reminder sent')
            page.locator('#pmSection-unpaid').get_by_role('button', name='Send payment reminder').first.click()
            page.locator('#pmConfirmSubmit').click()
            expect(page.locator('#pmConfirmDialog')).to_be_hidden()
            expect(page.locator('#pmFeedback')).to_contain_text('already sent')
            self.assertEqual(page.evaluate('window.paymentSentinel'), 42)
            self.assertEqual(errors, [])
            context.close(); browser.close()
        self.pending[-1].refresh_from_db(); self.pending[-2].refresh_from_db(); self.bookings[0].refresh_from_db()
        self.assertEqual(self.pending[-1].payment_status, 'verified')
        self.assertEqual(self.pending[-1].verified_by, self.admin)
        self.assertEqual(self.pending[-2].payment_status, 'rejected')
        self.assertEqual(self.pending[-2].notes, 'Payment amount does not match. Receipt amount does not match')
        self.assertEqual(self.bookings[0].payment_status, 'partial')
        self.assertEqual(Notification.objects.filter(message__icontains='payment reminder').count(), 1)
        self.config.refresh_from_db()
        self.assertEqual(self.config.downpayment_percent, 30)

    def test_detail_link_history_reload_and_close_restore_the_workspace(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            context = self.context(browser)
            page = context.new_page()
            page.goto(self.live_server_url + reverse('admin_payment_list'), wait_until='domcontentloaded')
            opener = page.locator('#pmSection-pending [data-payment-detail]').first
            opener.click()
            modal = page.locator('#pmDetailDialog')
            expect(modal).to_be_visible()
            expect(page.locator('#pmPaymentDetail')).to_be_visible()
            self.assertIn('open_payment=', page.url)
            page.go_back()
            expect(modal).to_be_hidden()
            page.go_forward()
            expect(modal).to_be_visible()
            expect(page.locator('#pmPaymentDetail')).to_be_visible()
            page.reload()
            expect(modal).to_be_visible()
            expect(page.locator('#pmPaymentDetail')).to_be_visible()
            page.keyboard.press('Escape')
            expect(modal).to_be_hidden()
            self.assertNotIn('open_payment=', page.url)
            context.close()
            browser.close()

    def test_light_dark_responsive_details_and_redirected_detail_action(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            for width,height in ((1440,1000),(768,1024),(390,844),(320,740)):
                for theme in ('light','dark'):
                    with self.subTest(width=width, theme=theme):
                        context = self.context(browser,width,height,theme); page = context.new_page(); errors=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        page.goto(self.live_server_url+reverse('admin_payment_list'),wait_until='domcontentloaded')
                        self.assertEqual(page.locator('html').evaluate('(e)=>e.dataset.theme === "light" ? "light" : "dark"'), theme)
                        page.screenshot(path=str(self.artifacts/f'payments-{theme}-{width}.png'),full_page=True)
                        self.assertLessEqual(page.locator('body').evaluate('(e)=>e.scrollWidth-innerWidth'),1)
                        self.assertLessEqual(page.locator('.pm-workspace').evaluate('(e)=>e.scrollWidth-e.clientWidth'),1)
                        self.assertEqual(page.locator('.ac-kpi').first.evaluate('(e)=>getComputedStyle(e).backgroundColor'),
                            'rgb(255, 255, 255)' if theme == 'light' else 'rgb(22, 22, 22)')
                        page.locator('#pmSection-pending [data-payment-detail]').first.click()
                        expect(page.locator('#pmDetailBody .pd-grid')).to_be_visible()
                        self.assertLessEqual(page.locator('#pmDetailDialog').evaluate('(e)=>e.scrollWidth-e.clientWidth'),1)
                        page.screenshot(path=str(self.artifacts/f'payment-details-{theme}-{width}.png'))
                        page.keyboard.press('Escape')
                        page.get_by_role('link',name='Payment Settings',exact=True).click()
                        expect(page.locator('#pmSettingsForm')).to_be_visible()
                        field = page.locator('#pmDownpayment')
                        field.fill('0')
                        page.locator('#pmSettingsSave').click()
                        expect(page.locator('#pmPercentError')).to_be_visible()
                        expected_error = 'rgb(184, 53, 60)' if theme == 'light' else 'rgb(241, 145, 145)'
                        self.assertEqual(page.locator('#pmPercentError').evaluate('(e)=>getComputedStyle(e).color'), expected_error)
                        save = page.locator('#pmSettingsSave')
                        self.assertEqual(save.evaluate('(e)=>getComputedStyle(e).color'),
                            'rgb(255, 255, 255)' if theme == 'light' else 'rgb(22, 22, 22)')
                        box=save.bounding_box()
                        self.assertLessEqual(box['y']+box['height'],height)
                        self.assertLessEqual(page.locator('#pmSettingsDialog').evaluate('(e)=>e.scrollWidth-e.clientWidth'),1)
                        page.screenshot(path=str(self.artifacts/f'payment-settings-{theme}-{width}.png'))
                        page.keyboard.press('Escape')
                        page.goto(self.live_server_url+reverse('admin_payment_detail',args=[self.pending[-1].pk]),wait_until='domcontentloaded')
                        self.assertLessEqual(page.locator('body').evaluate('(e)=>e.scrollWidth-innerWidth'),1)
                        self.assertEqual(errors,[])
                        context.close()
            context=self.context(browser); page=context.new_page()
            page.goto(self.live_server_url+reverse('admin_payment_detail',args=[self.pending[-1].pk]),wait_until='domcontentloaded')
            page.evaluate('window.paymentSentinel=42')
            page.get_by_role('button',name='Reject',exact=True).click()
            page.get_by_role('button', name='Payment rejection reason: Choose a reason', exact=True).click()
            page.get_by_role('option', name='Receipt is invalid or unreadable', exact=True).click()
            page.locator('#pmRejectReason').fill('Incorrect receipt')
            page.locator('#pmConfirmSubmit').click()
            expect(page.locator('.pd-amount-row')).to_contain_text('Rejected')
            expect(page.locator('#pmFeedback')).to_contain_text('rejected')
            self.assertEqual(page.evaluate('window.paymentSentinel'),42)
            context.close(); browser.close()
