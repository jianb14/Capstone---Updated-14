"""Optional real-browser checks for QR payment and merchant verification."""
import os
from datetime import time, timedelta
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Booking, GCashConfig, Payment, User
from .test_gcash_qr import png


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies', REQUEST_RATE_LIMITING_ENABLED=False)
class GCashQRBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qr-browser-customer', role='customer')
        self.admin = User.objects.create_user(username='qr-browser-admin', role='admin')
        self.config = GCashConfig.objects.create(gcash_name='Balloorina Test Merchant', qr_code_image=png('test-qr.png'))
        self.booking = Booking.objects.create(user=self.user, status='pending_payment', total_price=6000,
            event_date=timezone.localdate()+timedelta(days=30), event_time=time(10), event_type='Birthday',
            package_type='Package A', event_location='Test Venue', payment_due_at=timezone.now()+timedelta(hours=24))
        self.artifacts = Path(settings.BASE_DIR)/'.booking-followup-check'

    def context(self, browser, user, width=1440, theme='light'):
        self.client.force_login(user)
        context = browser.new_context(viewport={'width':width, 'height':1000}, reduced_motion='reduce')
        def external(route):
            if route.request.url.startswith(self.live_server_url+'/'):
                route.continue_()
            elif 'sweetalert' in route.request.url:
                route.fulfill(body='window.Swal={mixin:()=>({fire:()=>{}}),fire:()=>Promise.resolve({}),DismissReason:{}};', content_type='application/javascript')
            else:
                route.abort()
        context.route('**/*', external)
        context.add_init_script('localStorage.setItem("balloorina-theme", "'+theme+'")')
        context.add_cookies([{'name':settings.SESSION_COOKIE_NAME, 'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url':self.live_server_url}])
        return context

    @patch.dict(os.environ, {'DJANGO_ALLOW_ASYNC_UNSAFE':'true'})
    def test_customer_submission_admin_check_and_responsive_forms(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            for width, theme in ((1440,'light'), (768,'light'), (390,'light'), (390,'dark')):
                context = self.context(browser, self.user, width, theme)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url+reverse('payment_page', args=[self.booking.pk]), wait_until='domcontentloaded')
                expect(page.get_by_role('heading', name='Pay with GCash QR')).to_be_visible()
                self.assertTrue(page.locator('.pu-qr-image').evaluate('(image) => image.complete && image.naturalWidth > 0'))
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                contrast = page.locator('.pu-proof-fields').evaluate('''element => {
                    const luminance = color => {
                        const channels = color.match(/[\\d.]+/g).slice(0, 3).map(Number).map(v => v/255);
                        const values = channels.map(v => v <= .04045 ? v/12.92 : ((v+.055)/1.055)**2.4);
                        return values[0]*.2126 + values[1]*.7152 + values[2]*.0722;
                    };
                    const style = getComputedStyle(element);
                    const a = luminance(style.color), b = luminance(style.backgroundColor);
                    return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
                }''')
                self.assertGreaterEqual(contrast, 4.5)
                page.screenshot(path=str(self.artifacts/f'gcash-customer-{width}-{theme}.png'), full_page=True)
                self.assertEqual(errors, [])
                context.close()
            context = self.context(browser, self.user)
            page = context.new_page()
            page.goto(self.live_server_url+reverse('payment_page', args=[self.booking.pk]))
            page.locator('label.cp-option-card').filter(has=page.locator('input[value="downpayment"]')).click()
            expect(page.locator('#js-amount-to-pay-2')).to_have_text('1200.00')
            page.get_by_label('GCash transaction reference').fill('1234567890123')
            page.get_by_label('Sender name on the transaction').fill('Test Sender')
            page.get_by_label('Transaction date and time').fill(timezone.localtime().strftime('%Y-%m-%dT%H:%M'))
            page.locator('input[name="receipt_image"]').set_input_files({'name':'proof.png', 'mimeType':'image/png', 'buffer':png().read()})
            page.locator('#js-refund-ack').check()
            page.get_by_role('button', name='Submit GCash payment proof').click()
            page.wait_for_url('**/my-payments/**')
            payment = Payment.objects.get()
            self.assertEqual(payment.payment_status, 'pending')
            page.locator('[data-pay-gcash-reference="1234567890123"]').first.click()
            expect(page.locator('#modal-gcash-reference')).to_have_text('1234567890123')
            expect(page.locator('#modal-pay-proof')).to_have_attribute('href', reverse('payment_proof', args=[payment.pk]))
            page.locator('#modal-pay-proof').click()
            expect(page.locator('#paymentProofDialog')).to_be_visible()
            expect(page.locator('#paymentProofDialog img')).to_be_visible()
            for width, theme in ((1440, 'light'), (390, 'light'), (390, 'dark')):
                page.set_viewport_size({'width':width, 'height':844})
                page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                self.assertLessEqual(page.locator('#paymentProofDialog').evaluate('(e)=>e.scrollWidth-e.clientWidth'), 1)
                page.screenshot(path=str(self.artifacts/f'customer-proof-preview-{width}-{theme}.png'))
            page.set_viewport_size({'width':1440, 'height':1000})
            page.evaluate('document.documentElement.dataset.theme="light"')
            page.screenshot(path=str(self.artifacts/'customer-proof-preview.png'))
            page.keyboard.press('Escape')
            expect(page.locator('#paymentProofDialog')).not_to_be_visible()
            expect(page.locator('#bookingModal')).to_be_visible()
            page.locator('#modal-pay-proof').click()
            page.get_by_role('button', name='Close submitted proof').click()
            expect(page.locator('#modal-pay-payment-id').locator('..')).not_to_be_visible()
            page.get_by_role('button', name='Close payment details').click()
            badge_style = page.locator('.account-table .mp-status--pending').first.evaluate('(e)=>{const s=getComputedStyle(e);return [s.color,s.backgroundColor,s.borderRadius,s.fontSize,s.fontWeight]}')
            page.goto(self.live_server_url+reverse('payment_page', args=[self.booking.pk]), wait_until='domcontentloaded')
            expect(page.locator('.pu-transaction')).to_have_count(1)
            expect(page.locator('.pu-transaction')).to_contain_text('1200.00')
            expect(page.locator('.pu-transaction')).to_contain_text('Pending')
            self.assertEqual(page.locator('.pu-transaction .mp-status').evaluate('(e)=>{const s=getComputedStyle(e);return [s.color,s.backgroundColor,s.borderRadius,s.fontSize,s.fontWeight]}'), badge_style)
            page.locator('.pu-history').screenshot(path=str(self.artifacts/'payment-history-list-populated.png'))
            context.close()
            context = self.context(browser, self.admin)
            page = context.new_page()
            page.goto(self.live_server_url+reverse('admin_payment_list'))
            page.locator('[data-payment-settings]').click()
            page.get_by_label('Recipient / merchant name').fill('Updated Test Merchant')
            page.get_by_role('button', name='Save settings').click()
            expect(page.locator('#pmSettingsDialog')).not_to_be_visible()
            expect(page.locator('#pmQueues')).not_to_have_attribute('aria-busy', 'true')
            self.config.refresh_from_db()
            self.assertEqual(self.config.gcash_name, 'Updated Test Merchant')
            payment.refresh_from_db()
            self.assertEqual(payment.gcash_recipient_name, 'Balloorina Test Merchant')
            page.locator('#pmSection-pending [data-payment-action="verify"]').first.click()
            expect(page.locator('#pmConfirmSubmit')).to_be_disabled()
            self.assertEqual(page.locator('#pmMerchantConfirmed').evaluate('(e)=>getComputedStyle(e).backgroundColor'), 'rgba(0, 0, 0, 0)')
            page.locator('#pmMerchantConfirmed').check()
            for theme in ('light', 'dark'):
                page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                page.locator('#pmMerchantConfirmed').focus()
                check_style = page.locator('#pmMerchantConfirmed').evaluate('(e)=>{const s=getComputedStyle(e);return {image:s.backgroundImage,fill:s.backgroundColor}}')
                self.assertIn('data:image/svg+xml', check_style['image'])
                self.assertEqual(check_style['fill'], 'rgb(24, 24, 24)' if theme == 'light' else 'rgb(245, 245, 245)')
                page.screenshot(path=str(self.artifacts/f'admin-checked-focused-{theme}.png'))
            page.evaluate('document.documentElement.dataset.theme="light"')
            self.assertEqual(page.locator('#pmMerchantConfirmed').evaluate('(e)=>getComputedStyle(e).appearance'), 'none')
            self.assertEqual(page.locator('#pmMerchantConfirmed').evaluate('(e)=>getComputedStyle(e).backgroundColor'), 'rgb(24, 24, 24)')
            page.screenshot(path=str(self.artifacts/'gcash-admin-merchant-check.png'), full_page=True)
            page.locator('#pmConfirmSubmit').click()
            expect(page.locator('#pmConfirmDialog')).not_to_be_visible()
            payment.refresh_from_db()
            self.assertEqual(payment.payment_status, 'verified')
            context.close()
            browser.close()

    @patch.dict(os.environ, {'DJANGO_ALLOW_ASYNC_UNSAFE':'true'})
    def test_payment_settings_fields_and_image_upload_are_responsive(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            for width, theme in ((1440,'light'), (768,'light'), (390,'light'), (320,'light'), (1440,'dark'), (390,'dark')):
                context = self.context(browser, self.admin, width, theme)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url+reverse('admin_payment_list'))
                page.locator('[data-payment-settings]').click()
                expect(page.locator('#pmSettingsForm')).to_be_visible()
                deposit = page.locator('#pmDownpayment').bounding_box()
                section = page.locator('.pm-deposit-row').bounding_box()
                help_box = page.locator('#pmPercentHelp').bounding_box()
                self.assertAlmostEqual(deposit['width'], section['width'], delta=2)
                self.assertGreaterEqual(help_box['y'], deposit['y'] + deposit['height'])
                page.screenshot(path=str(self.artifacts/f'payment-settings-style-{width}-{theme}.png'), full_page=True)
                for name in ('gcash_name', 'gcash_number', 'instructions'):
                    field = page.locator(f'#pmSettingsForm [name="{name}"]')
                    box = field.bounding_box()
                    self.assertGreaterEqual(box['height'], 44)
                    self.assertGreaterEqual(box['width'], min(240, width-90))
                self.assertLessEqual(page.locator('#pmSettingsDialog').evaluate('(e)=>e.scrollWidth-e.clientWidth'), 1)
                expect(page.locator('#pmSettingsForm').get_by_role('button', name='Browse Files')).to_be_visible()
                self.assertEqual(errors, [])
                context.close()
            context = self.context(browser, self.admin)
            page = context.new_page()
            page.goto(self.live_server_url+reverse('admin_payment_list'))
            page.locator('[data-payment-settings]').click()
            upload = page.locator('#pmSettingsForm [data-payment-upload]')
            upload.locator('input[type=file]').set_input_files({'name':'replacement-qr.png', 'mimeType':'image/png', 'buffer':png().read()})
            expect(upload.locator('[data-upload-preview]')).to_be_visible()
            expect(upload.locator('[data-upload-filename]')).to_have_text('replacement-qr.png')
            upload.get_by_role('button', name='Remove selected image').click()
            expect(upload.locator('[data-upload-preview]')).not_to_be_visible()
            self.assertEqual(upload.locator('input[type=file]').evaluate('(e)=>e.files.length'), 0)
            upload.locator('input[type=file]').set_input_files({'name':'bad.txt', 'mimeType':'text/plain', 'buffer':b'invalid'})
            expect(upload.locator('[data-upload-feedback]')).to_contain_text('PNG or JPEG')
            upload.locator('input[type=file]').set_input_files({'name':'merchant-qr.png', 'mimeType':'image/png', 'buffer':png().read()})
            page.get_by_label('Recipient / merchant name').fill('Styled Merchant')
            page.get_by_label('Payment instructions').fill('Check the recipient before paying.')
            page.locator('#pmSettingsSave').click()
            expect(page.locator('#pmSettingsDialog')).not_to_be_visible()
            self.config.refresh_from_db()
            self.assertEqual(self.config.gcash_name, 'Styled Merchant')
            self.assertIn('merchant-qr', self.config.qr_code_image.name)
            context.close()
            browser.close()

    @patch.dict(os.environ, {'DJANGO_ALLOW_ASYNC_UNSAFE':'true'})
    def test_customer_payment_upload_preview_drop_remove_and_unavailable_design(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            for width, theme in ((1440,'light'), (768,'light'), (390,'light'), (320,'light'), (1440,'dark'), (390,'dark')):
                context = self.context(browser, self.user, width, theme)
                page = context.new_page()
                page.goto(self.live_server_url+reverse('payment_page', args=[self.booking.pk]), wait_until='domcontentloaded')
                page.screenshot(path=str(self.artifacts/f'payment-form-style-{width}-{theme}.png'), full_page=True)
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                expect(page.get_by_role('heading', name='Pay with GCash QR')).to_be_visible()
                upload = page.locator('[data-payment-upload]')
                expect(page.locator('.pu-history table')).to_have_count(0)
                expect(page.locator('.pu-history-empty')).to_contain_text('No payments yet')
                field = page.get_by_label('GCash transaction reference')
                field.focus()
                styles = field.evaluate('(e)=>({bg:getComputedStyle(e).backgroundColor,outline:getComputedStyle(e).outlineWidth,ring:getComputedStyle(e).outlineColor})')
                self.assertEqual(styles['bg'], 'rgba(0, 0, 0, 0)')
                self.assertEqual(styles['outline'], '2px')
                self.assertEqual(styles['ring'], 'rgba(105, 105, 105, 0.4)' if theme == 'light' else 'rgba(153, 153, 153, 0.45)')
                self.assertEqual(page.locator('.pu-proof-field label > span').first.evaluate('(e)=>getComputedStyle(e).color'), 'rgb(184, 53, 60)' if theme == 'light' else 'rgb(241, 145, 145)')
                self.assertEqual(page.locator('.cp-option-card').first.evaluate('(e)=>getComputedStyle(e).boxShadow'), 'none')
                field.blur()
                selected_color = page.locator('.cp-option-card').first.evaluate('(e)=>getComputedStyle(e).backgroundColor')
                page.locator('.cp-option-card').nth(1).hover()
                page.wait_for_timeout(250)
                self.assertNotEqual(page.locator('.cp-option-card').nth(1).evaluate('(e)=>getComputedStyle(e).backgroundColor'), selected_color)
                self.assertEqual(page.locator('.booking-deadline-note--payment').evaluate('(e)=>getComputedStyle(e).backgroundColor'), 'rgba(210, 153, 24, 0.09)')
                self.assertEqual(page.locator('.booking-deadline-note--payment').evaluate('(e)=>getComputedStyle(e).borderTopWidth'), '1px')
                self.assertNotEqual(page.locator('.cp-option-card').first.evaluate('(e)=>getComputedStyle(e).backgroundColor'), 'rgba(0, 0, 0, 0)')
                self.assertEqual(page.locator('.pu-step-num').first.evaluate('(e)=>getComputedStyle(e).backgroundColor'), 'rgb(17, 24, 39)' if theme == 'light' else 'rgb(255, 255, 255)')
                download = page.locator('.pu-qr-download')
                border = download.evaluate('(e)=>getComputedStyle(e).borderColor')
                download.hover()
                page.wait_for_timeout(250)
                self.assertEqual(download.evaluate('(e)=>getComputedStyle(e).borderColor'), border)
                if width in (1440, 390):
                    page.locator('.pu-head [data-site-guide-start]').click()
                    seen = []
                    for _ in range(15):
                        seen.append(page.locator('[data-guide-title]').inner_text())
                        if seen[-1] == 'Upload payment screenshot' and width == 390:
                            page.screenshot(path=str(self.artifacts/f'payment-proof-guide-{theme}.png'))
                        next_button = page.locator('[data-guide-next]')
                        if next_button.inner_text() == 'Done':
                            next_button.click()
                            break
                        next_button.click()
                    self.assertIn('Submit payment proof', seen)
                    self.assertIn('Upload payment screenshot', seen)
                    self.assertFalse(page.locator('#js-refund-ack').is_checked())
                expect(upload.get_by_role('button', name='Browse Files')).to_be_visible()
                upload.locator('input[type=file]').set_input_files({'name':'receipt.png', 'mimeType':'image/png', 'buffer':png().read()})
                expect(upload.locator('[data-upload-filename]')).to_have_text('receipt.png')
                expect(upload.locator('[data-upload-preview] img')).to_be_visible()
                upload.get_by_role('button', name='Remove selected image').click()
                self.assertEqual(upload.locator('input[type=file]').evaluate('(e)=>e.files.length'), 0)
                self.config.qr_code_image = ''
                self.config.save(update_fields=['qr_code_image'])
                page.reload(wait_until='domcontentloaded')
                expect(page.get_by_role('heading', name='Payment Unavailable', exact=True)).to_be_visible()
                page.evaluate('window.scrollTo(0, 0)')
                page.screenshot(path=str(self.artifacts/f'payment-unavailable-style-{width}-{theme}.png'), full_page=True)
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                self.config.qr_code_image = 'gcash_config/test-placeholder.png'
                self.config.save(update_fields=['qr_code_image'])
                self.config.qr_code_image.save('test-qr.png', png(), save=True)
                context.close()
            context = self.context(browser, self.user)
            page = context.new_page()
            page.goto(self.live_server_url+reverse('payment_page', args=[self.booking.pk]))
            image = list(png().read())
            page.locator('[data-payment-upload]').evaluate('''(element, bytes) => {
                const transfer = new DataTransfer();
                transfer.items.add(new File([new Uint8Array(bytes)], 'dropped-receipt.png', {type:'image/png'}));
                element.querySelector('[data-upload-zone]').dispatchEvent(new DragEvent('drop', {bubbles:true, dataTransfer:transfer}));
            }''', image)
            expect(page.locator('[data-upload-filename]')).to_have_text('dropped-receipt.png')
            page.locator('label.cp-option-card').filter(has=page.locator('input[value="downpayment"]')).click()
            expect(page.locator('[data-qr-amount]')).to_have_text('1200.00')
            expect(page.locator('#js-summary-amount')).to_have_text('1200.00')
            context.close()
            self.booking.status = 'confirmed'
            self.booking.save(update_fields=['status'])
            for width, theme in ((1440, 'light'), (390, 'dark')):
                context = self.context(browser, self.user, width, theme)
                page = context.new_page()
                page.goto(self.live_server_url+reverse('payment_page', args=[self.booking.pk]), wait_until='domcontentloaded')
                note = page.locator('.booking-deadline-note--design')
                expect(note).to_contain_text('Design in preparation')
                self.assertEqual(note.evaluate('(e)=>getComputedStyle(e).backgroundColor'), 'rgba(35, 164, 106, 0.09)')
                self.assertEqual(note.evaluate('(e)=>getComputedStyle(e).color'), 'rgb(24, 116, 71)' if theme == 'light' else 'rgb(123, 212, 161)')
                page.screenshot(path=str(self.artifacts/f'payment-design-notice-{theme}.png'))
                context.close()
            browser.close()

    @patch.dict(os.environ, {'DJANGO_ALLOW_ASYNC_UNSAFE':'true'})
    def test_invalid_optional_qr_can_be_cleared_without_losing_other_edits(self):
        from playwright.sync_api import sync_playwright, expect
        original_qr = self.config.qr_code_image.name
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            context = self.context(browser, self.admin)
            page = context.new_page()
            page.goto(self.live_server_url+reverse('admin_payment_list'))
            page.locator('[data-payment-settings]').click()
            page.get_by_label('Recipient / merchant name').fill('Edited recipient')
            upload = page.locator('#pmSettingsForm [data-payment-upload]')
            upload.locator('input[type=file]').set_input_files({'name':'invalid.txt', 'mimeType':'text/plain', 'buffer':b'invalid'})
            expect(upload.locator('[data-upload-feedback]')).to_contain_text('PNG or JPEG')
            upload.get_by_role('button', name='Clear selection').click()
            expect(upload.locator('[data-upload-feedback]')).to_be_empty()
            page.locator('#pmSettingsSave').click()
            expect(page.locator('#pmSettingsDialog')).not_to_be_visible()
            self.config.refresh_from_db()
            self.assertEqual(self.config.gcash_name, 'Edited recipient')
            self.assertEqual(self.config.qr_code_image.name, original_qr)
            context.close()
            browser.close()
