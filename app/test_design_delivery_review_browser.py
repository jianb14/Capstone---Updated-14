"""Optional end-to-end review form and customer explanation checks."""
import os
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Booking, Payment, User
from .test_design_delivery import TempMediaMixin


@skipUnless(os.environ.get('RUN_DESIGN_REVIEW_BROWSER') == '1', 'Optional design review browser checks')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False, SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class DesignDeliveryReviewBrowserTests(TempMediaMixin, StaticLiveServerTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(username='review-browser-admin', role='admin', email_verified=True)
        self.customer = User.objects.create_user(username='review-browser-customer', role='customer',
            first_name='Maria', email_verified=True)
        self.day = timezone.localdate() - timedelta(days=1)
        self.booking = Booking.objects.create(user=self.customer, status='confirmed', event_date=self.day,
            event_time=time(15), event_end_time=time(19), event_type='Birthday', event_location='Bacoor',
            package_type='Birthday Package', total_price=5000,
            design_due_at=timezone.make_aware(datetime.combine(self.day - timedelta(days=1), time(15))))
        Payment.objects.create(booking=self.booking, amount=1000, payment_status='verified', transaction_ref='browser-review-paid')
        self.cookies = {}
        for user in (self.admin, self.customer):
            client = Client(); client.force_login(user)
            self.cookies[user.pk] = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.artifacts = Path(settings.BASE_DIR) / '.booking-followup-check' / 'design-review'
        self.artifacts.mkdir(parents=True, exist_ok=True)

    def context(self, browser, user, width=1440, theme='light'):
        context = browser.new_context(viewport={'width': width, 'height': 1000}, reduced_motion='reduce')
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.cookies[user.pk], 'url': self.live_server_url}])
        context.add_init_script(f"localStorage.setItem('balloorina-theme','{theme}')")
        context.route('https://**', lambda route: route.fulfill(
            body='window.Swal={mixin:()=>({fire:()=>{}}),fire:()=>Promise.resolve({}),DismissReason:{}};',
            content_type='application/javascript') if 'sweetalert' in route.request.url else route.abort())
        return context

    def test_resolve_missing_design_and_show_customer_the_recorded_explanation(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            admin_context = self.context(browser, self.admin)
            customer_context = self.context(browser, self.customer, 390, 'dark')
            admin = admin_context.new_page(); customer = customer_context.new_page(); errors = []
            admin.on('pageerror', lambda error: errors.append(str(error)))
            customer.on('pageerror', lambda error: errors.append(str(error)))
            try:
                admin.goto(self.live_server_url + reverse('admin_booking_list') +
                    f'?tab=designs&design_status=review&open_booking={self.booking.pk}&section=design')
                dialog = admin.locator('#abDetails')
                expect(dialog).to_be_visible()
                expect(dialog).to_contain_text('Needs admin action')
                expect(admin.locator('[data-action="complete"]')).to_have_count(0)
                dialog.get_by_text('Record design resolution', exact=True).click()
                form = dialog.locator('[data-design-review-form]')
                form.get_by_role('button', name='Save resolution', exact=True).click()
                expect(form.locator('[name=outcome]')).to_have_attribute('aria-invalid', 'true')
                form.get_by_role('button', name='Design resolution outcome:', exact=False).click()
                admin.get_by_role('option', name='Delivered outside the system', exact=True).click()
                expect(form.locator('[data-error-for=outcome]')).to_be_hidden()
                form.locator('[name=delivered_at]').fill(f'{self.day}T14:00')
                notes = 'Shown to the customer at the venue. The requested event styling was fulfilled.'
                form.locator('[name=notes]').fill(notes)
                form.locator('[name=service_fulfilled]').check()
                self.assertTrue(form.locator('.ab-review-consent').evaluate('''(label) => {
                    const range = document.createRange();
                    range.selectNode([...label.childNodes].find(node => node.nodeType === 3 && node.textContent.trim()));
                    return range.getBoundingClientRect().left >= label.querySelector('input').getBoundingClientRect().right;
                }'''))
                for width, theme in [(1440, 'light'), (390, 'dark'), (320, 'light')]:
                    admin.set_viewport_size({'width': width, 'height': 1000})
                    admin.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                    admin.screenshot(path=str(self.artifacts / f'admin-resolution-{width}-{theme}.png'))
                    self.assertTrue(dialog.evaluate('(node) => node.scrollWidth <= node.clientWidth + 1'))
                form.get_by_role('button', name='Save resolution', exact=True).click()
                expect(dialog).to_contain_text('Design issue resolved')
                expect(dialog).to_contain_text(notes)
                expect(dialog.locator('[data-design-review-form]')).to_have_count(0)
                customer.goto(self.live_server_url + reverse('customer_profile'))
                customer.get_by_role('link', name='View Details', exact=True).first.click()
                expect(customer.locator('#bookingModal')).to_contain_text('Design delivery resolution')
                expect(customer.locator('#bookingModal')).to_contain_text(notes)
                customer.screenshot(path=str(self.artifacts / 'customer-resolution-390-dark.png'))
                self.assertEqual(errors, [])
            finally:
                admin_context.close(); customer_context.close(); browser.close()
