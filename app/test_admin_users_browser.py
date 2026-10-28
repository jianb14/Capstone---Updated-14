"""Opt-in real-browser coverage of the asynchronous user directory and access dialogs."""
import os
from datetime import date
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from .models import Booking, Payment, User


@skipUnless(os.environ.get('RUN_ADMIN_USERS_BROWSER') == '1', 'Optional user-directory browser verification')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AdminUsersBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='directory-admin', email='admin@example.com', first_name='Alex', role='admin', email_verified=True)
        User.objects.bulk_create([User(username=f'directory-customer-{index}', first_name=f'Customer {index}',
            email=f'person{index}@example.com', role='customer', is_active=index != 0, email_verified=True) for index in range(35)])
        self.target = User.objects.create_user(username='directory-jamie', first_name='Jamie', last_name='Rivera',
            email='jamie@example.com', phone_number='09171234567', role='customer', email_verified=True)
        booking = Booking.objects.create(user=self.target, event_date=date(2099, 1, 15), event_type='Birthday', event_location='Test venue', total_price=5000, status='confirmed')
        Payment.objects.create(booking=booking, amount=2000, payment_method='gcash', payment_status='verified', transaction_ref='BROWSER-USER-PAY')
        self.client.force_login(self.admin)
        self.url = self.live_server_url + reverse('admin_user_list')
        self.artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'
        mail.outbox = []

    def browser(self, playwright):
        browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
        context.add_init_script("localStorage.setItem('balloorina-theme','light')")
        context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        context.route('https://cdnjs.cloudflare.com/**', lambda route: route.abort())
        context.route('https://cdn.jsdelivr.net/**', lambda route: route.fulfill(status=200, content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}})};'))
        return browser, context

    def test_async_search_filters_pages_details_confirmation_and_email(self):
        with sync_playwright() as p:
            browser, context = self.browser(p)
            page = context.new_page(); errors, documents, writes = [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda req: documents.append(req.url) if req.resource_type == 'document' else None)
            page.on('request', lambda req: writes.append(req.url) if req.method == 'POST' and '/toggle/' in req.url else None)
            try:
                page.goto(self.url)
                rows = page.locator('[data-user-row]')
                expect(rows).to_have_count(8)
                expect(page.locator('.account-page-ellipsis')).to_be_visible()
                page.get_by_role('link', name='Next page', exact=True).click()
                expect(page.locator('.account-pagination .is-current')).to_have_text('2')
                page.go_back()
                expect(page.locator('.account-pagination .is-current')).to_have_text('1')
                search = page.get_by_role('searchbox', name='Search users', exact=True)
                search.fill('Jamie Rivera')
                expect(rows).to_have_count(1)
                expect(rows.first).to_contain_text('jamie@example.com')
                page.get_by_role('button', name='Clear user search', exact=True).click()
                expect(rows).to_have_count(8)
                page.get_by_role('button', name='Rows per page: 8', exact=True).click()
                page.get_by_role('option', name='4', exact=True).click()
                expect(rows).to_have_count(4)
                search.fill('does-not-exist')
                expect(page.get_by_role('heading', name='No matching users', exact=True)).to_be_visible()
                expect(page.locator('.um-table thead')).to_have_count(0)
                page.get_by_role('button', name='Clear filters', exact=True).click()
                expect(rows).to_have_count(4)
                page.get_by_role('button', name='Filter user role: All roles', exact=True).click()
                page.get_by_role('option', name='Admin', exact=True).click()
                expect(rows).to_have_count(1)
                expect(rows.first).to_contain_text('directory-admin')
                page.get_by_role('button', name='Filter user role: Admin', exact=True).click()
                page.get_by_role('option', name='All roles', exact=True).click()
                search.fill('Jamie Rivera')
                expect(rows).to_have_count(1)
                page.get_by_role('link', name=f'View user #USER-{self.target.pk}', exact=True).click()
                modal = page.get_by_role('dialog', name='Account details', exact=True)
                expect(modal).to_be_visible()
                expect(modal).to_contain_text('2,000.00')
                expect(modal).to_contain_text('Recent bookings')
                expect(modal.get_by_role('link', name='Edit User', exact=True)).to_have_count(0)
                modal.get_by_role('button', name=f'Deactivate user #USER-{self.target.pk}', exact=True).click()
                confirmation = page.get_by_role('dialog', name='Deactivate account?', exact=True)
                expect(confirmation).to_be_visible()
                expect(confirmation).to_contain_text(self.target.email)
                page.get_by_role('button', name='Cancel', exact=True).click()
                self.assertEqual(writes, [])
                self.assertEqual(mail.outbox, [])
                modal.get_by_role('button', name=f'Deactivate user #USER-{self.target.pk}', exact=True).click()
                page.locator('#userAccessSubmit').evaluate('(node)=>{node.click();node.click();}')
                expect(confirmation).to_be_hidden()
                expect(page.locator('#userDetailContent .ac-status')).to_have_text('Inactive')
                expect(page.locator('[data-user-stat="inactive"]')).to_have_text('2')
                toast = page.locator('.cfg-toast')
                expect(toast).to_be_visible()
                expect(toast).to_have_attribute('data-kind', 'success')
                expect(toast).to_contain_text('deactivated')
                self.assertLess(toast.bounding_box()['y'], 100)
                self.assertGreater(toast.bounding_box()['x'], 900)
                self.assertTrue(toast.evaluate("el=>el.matches(':popover-open')"))
                page.screenshot(path=str(self.artifacts / 'admin-user-access-success.png'), animations='disabled')
                self.assertEqual(len(writes), 1)
                self.assertEqual(len(mail.outbox), 1)
                modal.get_by_role('button', name=f'Activate user #USER-{self.target.pk}', exact=True).click()
                page.get_by_role('button', name='Activate account', exact=True).click()
                expect(page.locator('#userDetailContent .ac-status')).to_have_text('Active')
                expect(page.locator('[data-user-stat="inactive"]')).to_have_text('1')
                self.assertEqual(len(mail.outbox), 2)
                page.get_by_role('button', name='Close account details', exact=True).click()
                expect(rows.first.locator('.ac-status')).to_have_text('Active')
                self.assertEqual(len(documents), 1)
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()

    def test_responsive_themes_focus_dropdowns_and_direct_detail_modal(self):
        with sync_playwright() as p:
            browser, context = self.browser(p)
            page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(self.url)
                page.get_by_role('searchbox', name='Search users', exact=True).fill('Jamie Rivera')
                expect(page.locator('[data-user-row]')).to_have_count(1)
                for theme in ('light', 'dark'):
                    page.evaluate('(theme)=>{if(theme==="light")document.documentElement.dataset.theme="light";else document.documentElement.removeAttribute("data-theme");}', theme)
                    for width in (1440, 1024, 768, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 1000})
                        page.wait_for_timeout(300)
                        search = page.get_by_role('searchbox', name='Search users', exact=True)
                        search.focus()
                        self.assertEqual(search.evaluate('(node)=>getComputedStyle(node).outlineStyle'), 'solid')
                        self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'), f'Page overflow {theme}/{width}')
                        page.get_by_role('button', name='Filter user role: All roles', exact=True).click()
                        menu = page.get_by_role('listbox', name='Filter user role', exact=True)
                        box = menu.bounding_box()
                        self.assertGreaterEqual(box['x'], 0)
                        self.assertLessEqual(box['x'] + box['width'], width)
                        self.assertLessEqual(menu.evaluate('(node)=>node.scrollWidth'), menu.evaluate('(node)=>node.clientWidth'))
                        page.keyboard.press('Escape')
                        page.screenshot(path=str(self.artifacts / f'admin-users-{theme}-{width}.png'), animations='disabled')
                        page.get_by_role('link', name=f'View user #USER-{self.target.pk}', exact=True).click()
                        modal = page.get_by_role('dialog', name='Account details', exact=True)
                        expect(modal.locator('[data-detail-user]')).to_be_visible()
                        box = modal.bounding_box()
                        self.assertGreaterEqual(box['x'], 0)
                        self.assertLessEqual(box['x'] + box['width'], width)
                        self.assertLessEqual(modal.evaluate('(node)=>node.scrollWidth'), modal.evaluate('(node)=>node.clientWidth'))
                        page.screenshot(path=str(self.artifacts / f'admin-user-details-{theme}-{width}.png'), animations='disabled')
                        modal.get_by_role('button', name=f'Deactivate user #USER-{self.target.pk}', exact=True).click()
                        expect(page.get_by_role('dialog', name='Deactivate account?', exact=True)).to_be_visible()
                        page.screenshot(path=str(self.artifacts / f'admin-user-confirmation-{theme}-{width}.png'), animations='disabled')
                        page.keyboard.press('Escape')
                        expect(modal).to_be_visible()
                        page.keyboard.press('Escape')
                        expect(modal).to_be_hidden()
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.goto(self.live_server_url + reverse('admin_user_detail', args=[self.target.pk]))
                expect(page.get_by_role('dialog', name='Account details', exact=True)).to_be_visible()
                expect(page.locator('[data-detail-user]')).to_contain_text('Jamie Rivera')
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()

    def test_error_recovery_stale_results_and_mail_failure_keep_current_state(self):
        with sync_playwright() as p:
            browser, context = self.browser(p)
            page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(self.url)
                search = page.get_by_role('searchbox', name='Search users', exact=True)
                page.evaluate('''() => {const original=window.fetch;window.fetch=(...args)=>original(...args).then(async response=>{if(String(args[0]).includes('search=older'))await new Promise(resolve=>setTimeout(resolve,500));return response;});}''')
                search.fill('older'); page.wait_for_timeout(350); search.fill('Jamie Rivera')
                expect(page.locator('[data-user-row]')).to_have_count(1)
                page.wait_for_timeout(650)
                expect(page.locator('[data-user-row]')).to_have_count(1)
                page.route('**/staff/users/?**', lambda route: route.abort())
                search.fill('offline-search')
                expect(page.locator('#userListFeedback').get_by_role('button', name='Try again', exact=True)).to_be_visible()
                expect(page.locator('[data-user-row]')).to_have_count(1)
                page.unroute('**/staff/users/?**')
                page.locator('#userListFeedback').get_by_role('button', name='Try again', exact=True).click()
                expect(page.get_by_role('heading', name='No matching users', exact=True)).to_be_visible()
                search.fill('Jamie Rivera')
                expect(page.locator('[data-user-row]')).to_have_count(1)
                page.get_by_role('link', name=f'View user #USER-{self.target.pk}', exact=True).click()
                modal = page.get_by_role('dialog', name='Account details', exact=True)
                expect(modal.locator('[data-detail-user]')).to_be_visible()
                with patch('app.user_management.EmailMultiAlternatives.send', side_effect=OSError('Email offline')):
                    with self.assertLogs('app.user_management', level='ERROR'):
                        modal.get_by_role('button', name=f'Deactivate user #USER-{self.target.pk}', exact=True).click()
                        page.get_by_role('button', name='Deactivate account', exact=True).click()
                        expect(page.locator('#userAccessFeedback')).to_contain_text('status was not changed')
                        expect(page.locator('.cfg-toast')).to_have_attribute('data-kind', 'error')
                        expect(page.locator('.cfg-toast')).to_contain_text('status was not changed')
                expect(page.get_by_role('dialog', name='Deactivate account?', exact=True)).to_be_visible()
                page.get_by_role('button', name='Cancel', exact=True).click()
                expect(page.locator('#userDetailContent .ac-status')).to_have_text('Active')
                self.assertEqual(mail.outbox, [])
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()
