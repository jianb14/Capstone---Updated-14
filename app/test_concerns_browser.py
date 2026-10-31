"""Opt-in browser regression for a committed submission whose response is lost."""
import os
import re
from pathlib import Path
from tempfile import gettempdir
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import ConcernImage, ConcernTicket, User
from .test_concerns import photo


@skipUnless(os.environ.get('RUN_CONCERN_BROWSER') == '1', 'Optional concern browser verification')
@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, REQUEST_RATE_LIMITING_ENABLED=False)
class ConcernBrowserTests(StaticLiveServerTestCase):
    maxDiff = None
    def test_history_with_long_subjects_stays_readable_on_mobile_and_desktop(self):
        from playwright.sync_api import sync_playwright, expect

        user = User.objects.create_user(username='concern-layout', role='customer', email_verified=True)
        self.client.force_login(user)
        for status, subject in (
            ('new', 'A payment screenshot did not upload'),
            ('in_progress', 'I need help updating the details of my upcoming birthday booking'),
            ('resolved', 'Unable to access my account'),
            ('cancelled', 'Duplicate concern submitted by mistake'),
            ('new', 'A' * 150),
        ):
            ConcernTicket.objects.create(user=user, category='booking', status=status, subject=subject, message='Details of the issue.')
        executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                context = browser.new_context(reduced_motion='reduce')
                context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(
                    content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}}),fire:()=>{}};'))
                context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                    'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
                page = context.new_page()
                page.goto(self.live_server_url + reverse('report_concern'))
                expect(page.locator('.concern-history-panel tbody tr')).to_have_count(5)
                expect(page.locator('label .concern-required')).to_have_count(4)
                expect(page.locator('.concern-optional')).to_have_text('(optional)')
                self.assertFalse(page.locator('#concern_images').evaluate('(input) => input.required'))
                # A fresh empty required field turns red as soon as it receives focus.
                page.locator('#subject').focus()
                expect(page.locator('#subject')).to_have_attribute('aria-invalid', 'true')
                page.locator('#concernSubmit').click()
                expect(page.locator('#category_error')).to_have_text('Please select a category.')
                expect(page.locator('#subject_error')).to_have_text('Please enter a subject.')
                expect(page.locator('#message_error')).to_have_text('Please enter your message.')
                for width in (1440, 1200, 390, 320):
                    page.set_viewport_size({'width': width, 'height': 900})
                    for theme in ('light', 'dark'):
                        page.evaluate('(theme) => document.documentElement.setAttribute("data-theme", theme)', theme)
                        page.locator('#subject').evaluate('(e) => e.blur()')
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                        palette = page.evaluate('''() => {
                            const style = selector => getComputedStyle(document.querySelector(selector));
                            return {table:style('.account-table').backgroundColor,
                                head:style('.account-table th').backgroundColor,
                                input:style('#subject').backgroundColor,
                                inputText:style('#subject').color,
                                inputBorder:style('#subject').borderColor,
                                headerText:style('.account-table th').color,
                                rowText:style('.account-table td').color,
                                rowBorder:style('.account-table td').borderBottomColor,
                                upload:style('#concernUploadZone').backgroundColor,
                                button:style('#concernBrowse').backgroundColor,
                                required:style('.concern-required').color};
                        }''')
                        self.assertEqual(palette, {
                            'table':'rgb(255, 255, 255)' if theme == 'light' else 'rgb(22, 22, 22)',
                            'head':'rgb(247, 247, 247)' if theme == 'light' else 'rgb(32, 32, 32)',
                            'input':'rgb(255, 255, 255)' if theme == 'light' else 'rgb(22, 22, 22)',
                            'inputText':'rgb(24, 24, 24)' if theme == 'light' else 'rgb(245, 245, 245)',
                            'inputBorder':'rgb(184, 53, 60)' if theme == 'light' else 'rgb(241, 145, 145)',
                            'headerText':'rgb(115, 115, 115)' if theme == 'light' else 'rgb(163, 163, 163)',
                            'rowText':'rgb(24, 24, 24)' if theme == 'light' else 'rgb(245, 245, 245)',
                            'rowBorder':'rgb(229, 229, 229)' if theme == 'light' else 'rgb(48, 48, 48)',
                            'upload':'rgb(247, 247, 247)' if theme == 'light' else 'rgb(32, 32, 32)',
                            'button':'rgb(255, 255, 255)' if theme == 'light' else 'rgb(22, 22, 22)',
                            'required':'rgb(184, 53, 60)' if theme == 'light' else 'rgb(241, 145, 145)',
                        })
                        self.assertEqual(page.locator('#subject_error').evaluate('(e)=>getComputedStyle(e).color'), palette['required'])
                        page.locator('#subject').focus()
                        focus = page.locator('#subject').evaluate('''e => {
                            const s=getComputedStyle(e); return [s.outlineColor,s.outlineWidth,s.outlineOffset,s.boxShadow];
                        }''')
                        self.assertEqual(focus, ['rgba(184, 53, 60, 0.4)' if theme == 'light'
                            else 'rgba(241, 145, 145, 0.4)', '2px', '2px', 'none'])
                        self.assertEqual(page.locator('#subject').evaluate('(e)=>getComputedStyle(e).borderColor'), palette['required'])
                        page.locator('#subject').fill('A valid subject')
                        expect(page.locator('#subject')).to_have_attribute('aria-invalid', 'false')
                        self.assertEqual(page.locator('#subject').evaluate('(e)=>getComputedStyle(e).outlineColor'),
                            'rgba(105, 105, 105, 0.4)' if theme == 'light' else 'rgba(153, 153, 153, 0.45)')
                        page.locator('#subject').evaluate('(e) => e.blur()')
                        self.assertEqual(page.locator('#subject').evaluate('(e)=>getComputedStyle(e).borderColor'),
                            'rgb(229, 229, 229)' if theme == 'light' else 'rgb(48, 48, 48)')
                        page.locator('#subject').fill('')
                        expect(page.locator('#subject')).to_have_attribute('aria-invalid', 'true')
                        # Whitespace stays invalid, including the conditional Other field.
                        page.locator('#category').select_option('other', force=True)
                        for field in ('message', 'other_category'):
                            control = page.locator('#' + field)
                            control.fill('   ')
                            expect(control).to_have_attribute('aria-invalid', 'true')
                            self.assertEqual(control.evaluate('(e)=>getComputedStyle(e).outlineColor'),
                                'rgba(184, 53, 60, 0.4)' if theme == 'light' else 'rgba(241, 145, 145, 0.4)')
                            control.fill('Valid details')
                            expect(control).to_have_attribute('aria-invalid', 'false')
                            self.assertEqual(control.evaluate('(e)=>getComputedStyle(e).outlineColor'),
                                'rgba(105, 105, 105, 0.4)' if theme == 'light' else 'rgba(153, 153, 153, 0.45)')
                            control.fill('')
                        page.locator('#category').select_option('', force=True)
                        category_trigger = page.get_by_role('button', name='Choose concern category')
                        category_trigger.focus()
                        expect(category_trigger).to_have_attribute('aria-invalid', 'true')
                        self.assertEqual(category_trigger.evaluate('(e)=>getComputedStyle(e).outlineColor'),
                            'rgba(184, 53, 60, 0.4)' if theme == 'light' else 'rgba(241, 145, 145, 0.4)')
                        category_trigger.click()
                        expect(category_trigger).to_have_attribute('aria-invalid', 'true')
                        page.locator('#categoryDropdown [data-value="account"]').click()
                        expect(category_trigger).to_have_attribute('aria-invalid', 'false')
                        self.assertEqual(category_trigger.evaluate('(e)=>getComputedStyle(e).borderColor'),
                            'rgb(229, 229, 229)' if theme == 'light' else 'rgb(48, 48, 48)')
                        page.locator('#category').select_option('', force=True)
                        for row in page.locator('.concern-history-panel tbody tr').all():
                            action = row.locator('.concern-eye').bounding_box()
                            row_box = row.bounding_box()
                            self.assertAlmostEqual(action['width'], action['height'], delta=1)
                            self.assertLessEqual(action['x'] + action['width'], row_box['x'] + row_box['width'] + 1)
                        if width in (1440, 390):
                            page.screenshot(path=str(Path(gettempdir()) / f'balloorina-concern-history-{width}-{theme}.png'), full_page=True)
                page.get_by_role('button', name='Choose concern category').focus()
                page.keyboard.press('Enter')
                page.keyboard.press('ArrowDown')
                page.keyboard.press('Enter')
                expect(page.locator('#category')).to_have_value('account')
            finally:
                browser.close()

    def test_spam_lost_response_retry_modal_and_cancellation_keep_one_ticket(self):
        from playwright.sync_api import sync_playwright, expect

        user = User.objects.create_user(username='concern-browser', role='customer', email_verified=True)
        admin = User.objects.create_user(username='concern-browser-admin', role='admin', email_verified=True, is_staff=True)
        self.client.force_login(user)
        admin_client = Client()
        admin_client.force_login(admin)
        today = timezone.localdate().isoformat()
        image = photo().read()
        alert = self.enterContext(patch('app.views.profiles.send_admin_alert_email', return_value=True))
        executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                def context_for(client):
                    context = browser.new_context(viewport={'width': 1366, 'height': 900}, reduced_motion='reduce')
                    context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(
                        content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}}),fire:()=>{}};'))
                    context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                    context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                        'value': client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
                    return context
                context = context_for(self.client)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + reverse('report_concern'))
                page.locator('#category').select_option('bug', force=True)
                page.locator('#subject').fill('Connection interrupted while submitting')
                page.locator('#message').fill('The page froze during submission.\nPlease review the attached screenshot.')
                with page.expect_file_chooser() as chooser:
                    page.get_by_role('button', name='Browse File', exact=True).click()
                chooser.value.set_files({'name': 'remove-me.png', 'mimeType': 'image/png', 'buffer': image})
                page.get_by_role('button', name='Remove remove-me.png', exact=True).click()
                expect(page.locator('#concernImagePreview img')).to_have_count(0)
                self.assertEqual(page.locator('#concern_images').evaluate('(input) => input.files.length'), 0)
                page.locator('#concernUploadZone').evaluate('''zone => {
                    const transfer = new DataTransfer();
                    transfer.items.add(new File(['invalid'], 'document.txt', {type: 'text/plain'}));
                    zone.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: transfer}));
                }''')
                expect(page.locator('#concernUploadFeedback')).to_contain_text('JPG, PNG or WEBP')
                page.locator('#concernUploadZone').evaluate('''zone => {
                    const transfer = new DataTransfer();
                    transfer.items.add(new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'large.png', {type: 'image/png'}));
                    zone.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: transfer}));
                }''')
                expect(page.locator('#concernUploadFeedback')).to_contain_text('5MB')
                page.locator('#concernUploadZone').evaluate('''(zone, bytes) => {
                    const transfer = new DataTransfer();
                    transfer.items.add(new File([new Uint8Array(bytes)], 'dropped.png', {type: 'image/png'}));
                    zone.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: transfer}));
                }''', list(image))
                expect(page.locator('#concernImagePreview img')).to_have_count(1)
                for theme in ('light', 'dark'):
                    page.evaluate('(theme) => document.documentElement.setAttribute("data-theme", theme)', theme)
                    page.locator('#concernUploadZone').screenshot(path=str(Path(gettempdir()) / f'balloorina-concern-upload-{theme}.png'))
                page.get_by_role('button', name='Remove dropped.png', exact=True).click()
                page.locator('#concern_images').set_input_files({'name': 'proof.png', 'mimeType': 'image/png', 'buffer': image})
                expect(page.locator('#concernSubjectCount')).to_have_text('39/150')
                page.screenshot(path=str(Path(gettempdir()) / 'balloorina-concern-page-empty.png'), full_page=True)
                key = page.locator('input[name="submission_key"]').input_value()
                posts = []
                def drop_first_response(route):
                    if route.request.method != 'POST':
                        route.continue_()
                        return
                    posts.append(route.request.url)
                    if len(posts) == 1:
                        # The server has committed; only its response fails to reach the browser.
                        response = route.fetch()
                        self.assertEqual(response.status, 200)
                        route.abort('failed')
                    else:
                        route.continue_()
                page.route('**/report-concern/', drop_first_response)
                page.evaluate('''() => {
                    const form = document.getElementById('concernForm');
                    for (let attempt = 0; attempt < 12; attempt++) form.requestSubmit();
                }''')
                expect(page.locator('#concernSubmitStatus')).to_contain_text('could not confirm')
                expect(page.locator('.client-feedback-toast[data-kind="error"]')).to_contain_text('could not confirm')
                page.get_by_role('button', name='Dismiss notification').click()
                self.assertEqual(len(posts), 1)
                expect(page.locator('#subject')).to_have_value('Connection interrupted while submitting')
                expect(page.locator('input[name="submission_key"]')).to_have_value(key)
                self.assertEqual(page.locator('#concern_images').evaluate('(input) => input.files.length'), 1)
                page.get_by_role('button', name='Try again', exact=True).click()
                expect(page.locator('.concern-history-panel tbody tr')).to_have_count(1)
                expect(page.locator('.client-feedback-toast[data-kind="success"]')).to_contain_text('Concern submitted')
                page.get_by_role('button', name='Dismiss notification').click()
                self.assertEqual(len(posts), 2)
                for width, height, device in ((1366, 900, 'desktop'), (390, 844, 'mobile'), (320, 760, 'small-mobile')):
                    page.set_viewport_size({'width': width, 'height': height})
                    for theme in ('light', 'dark'):
                        page.evaluate('(theme) => document.documentElement.setAttribute("data-theme", theme)', theme)
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                        page.screenshot(path=str(Path(gettempdir()) / f'balloorina-concern-page-{device}-{theme}.png'), full_page=True)
                page.set_viewport_size({'width': 1366, 'height': 900})
                view = page.get_by_role('button', name=re.compile(r'^View concern #CON-'))
                view.click()
                expect(page.locator('#concernDetailModal')).to_be_visible()
                expect(page.locator('#modalStatus')).to_have_text('New')
                page.get_by_role('button', name='View attachment 1', exact=True).click()
                expect(page.locator('#concernImageLightbox')).to_be_visible()
                close = page.get_by_role('button', name='Close image', exact=True)
                bounds = close.bounding_box()
                self.assertGreaterEqual(bounds['width'], 44)
                self.assertLessEqual(page.viewport_size['width'] - bounds['x'] - bounds['width'], 24)
                self.assertLessEqual(bounds['y'], 24)
                page.screenshot(path=str(Path(gettempdir()) / 'balloorina-concern-photo-viewer.png'))
                page.keyboard.press('Escape')
                expect(page.locator('#concernImageLightbox')).not_to_be_visible()
                for width, height, device in ((1366, 900, 'desktop'), (390, 844, 'mobile'), (320, 760, 'small-mobile')):
                    page.set_viewport_size({'width': width, 'height': height})
                    for theme in ('light', 'dark'):
                        page.evaluate('(theme) => document.documentElement.setAttribute("data-theme", theme)', theme)
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                        page.screenshot(path=str(Path(gettempdir()) / f'balloorina-concern-{device}-{theme}.png'), animations='disabled')
                page.locator('#modalCancel').click()
                expect(page.locator('#concernCancelModal')).to_be_visible()
                expect(page.locator('#concernCancelModal.client-feedback-dialog')).to_be_visible()
                expect(page.get_by_role('button', name='Keep concern', exact=True)).to_be_focused()
                page.get_by_role('button', name='Keep concern', exact=True).click()
                expect(page.locator('.concern-row-status')).to_have_text('New')
                page.get_by_role('button', name='Close', exact=True).click()
                page.locator('#subject').fill('An unsent draft must stay here')
                page.locator('#message').fill('Draft message to preserve while cancelling an older concern.')
                view.click()
                page.locator('#modalCancel').click()
                page.screenshot(path=str(Path(gettempdir()) / 'balloorina-concern-cancel-mobile.png'), animations='disabled')
                def fail_cancel(route):
                    route.fulfill(status=503, content_type='application/json',
                        body='{"success":false,"message":"Please retry cancellation."}')
                # Use the actual action so this verifies the visible retry path.
                cancel_url = page.locator('#cancelConcernForm').get_attribute('action')
                page.route('**' + cancel_url, fail_cancel)
                page.locator('#confirmCancelConcern').click()
                expect(page.locator('#cancelConcernFeedback')).to_have_text('Please retry cancellation.')
                expect(page.locator('#concernCancelModal')).to_be_visible()
                expect(page.locator('.client-feedback-toast[data-kind="error"]')).to_contain_text('Please retry cancellation.')
                page.get_by_role('button', name='Dismiss notification').click()
                page.unroute('**' + cancel_url, fail_cancel)
                page.locator('#confirmCancelConcern').click()
                expect(page.locator('.concern-row-status')).to_have_text('Cancelled')
                expect(page.locator('#modalStatus')).to_have_text('Cancelled')
                expect(page.locator('#concernCancelModal')).not_to_be_visible()
                expect(page.locator('#modalCancel')).not_to_be_visible()
                expect(page.locator('.client-feedback-toast[data-kind="success"]')).to_contain_text('cancelled')
                page.keyboard.press('Escape')
                expect(page.locator('#subject')).to_have_value('An unsent draft must stay here')
                expect(page.locator('#message')).to_have_value('Draft message to preserve while cancelling an older concern.')
                expect(page.locator('.concern-row-status')).to_have_text('Cancelled')
                expect(page.locator('[data-cancel-id]')).to_have_count(0)
                expect(view).to_be_focused()
                admin_page = context_for(admin_client).new_page()
                admin_page.goto(self.live_server_url + reverse('admin_concerns') +
                    f'?concern_status=cancelled&start_date={today}&end_date={today}')
                admin_page.locator('.btn-view-concern').click()
                expect(admin_page.locator('#concernUpdateForm')).not_to_be_visible()
                expect(admin_page.locator('#cancelledConcernNote')).to_be_visible()
                self.assertEqual(errors, [])
            finally:
                browser.close()
        self.assertEqual(ConcernTicket.objects.count(), 1)
        self.assertEqual(ConcernImage.objects.count(), 1)
        self.assertEqual(ConcernTicket.objects.get().status, 'cancelled')
        alert.assert_called_once()
