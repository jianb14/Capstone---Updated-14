"""Optional browser coverage for booking deliveries in both support surfaces."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, time
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Booking, BookingChangeRequest, ChatMessage, Payment, User
from .test_design_delivery import TempMediaMixin, _design_upload


@skipUnless(os.environ.get('RUN_DESIGN_CHAT_BROWSER') == '1', 'Optional design chat browser checks')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class DesignDeliveryChatBrowserTests(TempMediaMixin, StaticLiveServerTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(username='delivery-admin', role='admin', email_verified=True)
        self.customer = User.objects.create_user(username='delivery-customer', first_name='Maria', role='customer',
            email='maria@example.com', email_verified=True)
        self.booking = Booking.objects.create(user=self.customer, status='confirmed', event_date=date(2099, 6, 15),
            event_time=time(10), event_type='Birthday', event_location='Test Venue', package_type='Package A', total_price=5000)
        Payment.objects.create(booking=self.booking, amount=1000, payment_status='verified', transaction_ref='chat-browser-paid')
        self.client.force_login(self.admin)
        self.cookies = {}
        for user in (self.admin, self.customer):
            client = Client(); client.force_login(user)
            self.cookies[user.pk] = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.artifacts = Path(settings.BASE_DIR) / '.booking-followup-check' / 'design-delivery-chat'
        self.artifacts.mkdir(parents=True, exist_ok=True)

    def context(self, browser, user):
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.cookies[user.pk], 'url': self.live_server_url}])
        context.add_init_script("localStorage.setItem('balloorina-theme','light')")
        context.route('https://**', lambda route: route.fulfill(body='window.Swal={mixin:()=>({fire:()=>{}}),fire:()=>Promise.resolve({}),DismissReason:{}};',
            content_type='application/javascript') if 'sweetalert' in route.request.url else route.abort())
        # SQLite cannot serialize activity heartbeats against concurrent delivery writes.
        # Exercise real uploads, chat sends and polling; receipt boundaries have API tests.
        context.route('**/api/support/action/', lambda route: route.fulfill(json={'success': True})
            if route.request.post_data_json.get('action') == 'activity' else route.continue_())
        return context

    def test_open_image_and_shared_photos_clear_deleted_deliveries(self):
        self.client.post(reverse('admin_booking_design_upload', args=[self.booking.pk]), {'design_image': _design_upload()})
        self.client.post(reverse('admin_booking_design_upload', args=[self.booking.pk]), {'design_image': _design_upload()})
        deliveries = list(self.booking.design_deliveries.order_by('pk'))
        from playwright.sync_api import expect, sync_playwright
        with ThreadPoolExecutor(max_workers=1) as db, sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = self.context(browser, self.customer)
            page = context.new_page()
            try:
                page.goto(self.live_server_url + reverse('home'))
                page.get_by_role('button', name='Chat with admin', exact=True).click()
                expect(page.locator('.sc-design-delivery')).to_have_count(2)
                page.locator('.sc-design-delivery').first.get_by_role('button', name='View attachment', exact=True).click()
                expect(page.locator('.sc-preview-image')).to_be_visible()
                db.submit(self.client.post, reverse('admin_booking_design_delete', args=[self.booking.pk, deliveries[0].pk])).result()
                expect(page.locator('.sc-preview-image')).to_have_count(0, timeout=15000)
                expect(page.get_by_role('link', name='Download image', exact=True)).to_have_count(0)
                expect(page.locator('[data-dialog-body]')).to_contain_text('This design was removed')
                page.get_by_role('button', name='Close dialog', exact=True).click()
                page.get_by_role('button', name='Conversation details', exact=True).click()
                expect(page.locator('.sc-media-grid img')).to_have_count(1)
                db.submit(self.client.post, reverse('admin_booking_design_delete', args=[self.booking.pk, deliveries[1].pk])).result()
                expect(page.locator('.sc-media-grid img')).to_have_count(0, timeout=15000)
                expect(page.locator('.sc-media-grid')).to_contain_text('No photos shared yet.')
            finally:
                context.close(); browser.close()

    def test_admin_delivery_customer_feedback_revisions_deletion_and_responsive_cards(self):
        from playwright.sync_api import expect, sync_playwright
        caption = '<img src=x onerror="window.deliveryUnsafe=true"> Please check the name.'
        with ThreadPoolExecutor(max_workers=1) as db, sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            admin_context = self.context(browser, self.admin)
            customer_context = self.context(browser, self.customer)
            admin = admin_context.new_page(); customer = customer_context.new_page(); errors = []
            for page in (admin, customer):
                page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                admin.goto(self.live_server_url + reverse('admin_booking_list') + '?status=', wait_until='domcontentloaded')
                row = admin.locator(f'[data-booking-id="{self.booking.pk}"]')
                row.get_by_role('link', name='Send design', exact=True).click()
                admin.locator('[data-design-file]').set_input_files({'name': 'design.png', 'mimeType': 'image/png', 'buffer': _design_upload().read()})
                admin.locator('#abDesignCaption').fill(caption)
                admin.locator('#abDetails').get_by_role('button', name='Send design', exact=True).click()
                expect(admin.locator('.ab-deliveries article')).to_have_count(1)
                message = db.submit(ChatMessage.objects.get).result()
                admin.goto(self.live_server_url + reverse('admin_chat_thread', args=[message.session_id]))
                customer.goto(self.live_server_url + reverse('home'))
                customer.get_by_role('button', name='Chat with admin', exact=True).click()
                for page in (admin, customer):
                    page.bring_to_front()
                    card = page.locator('.sc-design-delivery')
                    try:
                        expect(card).to_have_count(1, timeout=15000)
                    except AssertionError:
                        page.screenshot(path=str(self.artifacts / 'missing-card.png'))
                        self.fail(f'Delivery card missing at {page.url}; browser errors: {errors}')
                    expect(card.locator('.sc-design-title')).to_have_text('Design ready')
                    expect(card).to_contain_text(f'Booking #{self.booking.pk}')
                    expect(card).to_contain_text('Hi Maria!')
                    expect(card).to_contain_text(caption)
                    self.assertFalse(page.evaluate('Boolean(window.deliveryUnsafe)'))
                    self.assertEqual(card.locator('img').count(), 1)
                    expect(card.locator('img')).to_be_visible()
                    card.get_by_role('button', name='View attachment', exact=True).click()
                    expect(page.locator('.sc-preview-image')).to_be_visible()
                    self.assertTrue(page.locator('.sc-preview-image').evaluate('(img)=>img.complete && img.naturalWidth > 0'))
                    page.get_by_role('button', name='Close dialog', exact=True).click()
                    for theme in ('light', 'dark'):
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                        text_color = card.locator('.sc-message-text').evaluate('(el)=>getComputedStyle(el).color')
                        for selector in ('.sc-design-title', '.sc-design-booking', '.sc-design-link'):
                            self.assertEqual(card.locator(selector).evaluate('(el)=>getComputedStyle(el).color'),
                                text_color, f'{theme}: {selector} must follow the bubble text color')
                        for width in (1440, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            expect(card).to_be_visible()
                            self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'), f'{theme}/{width}')
                            self.assertFalse(card.evaluate('(el)=>el.scrollWidth > el.clientWidth'))
                            page.locator('[data-room]').screenshot(path=str(self.artifacts / f'{"admin" if page == admin else "customer"}-{theme}-{width}.png'))
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                self.assertEqual(customer.get_by_role('link', name='View booking', exact=True).get_attribute('href'),
                    reverse('view_booking', args=[self.booking.pk]))
                self.assertEqual(admin.get_by_role('link', name='View booking', exact=True).get_attribute('href'),
                    reverse('admin_booking_detail', args=[self.booking.pk]))
                admin.locator('.sc-design-delivery').get_by_role('button', name='Message options', exact=True).click()
                expect(admin.get_by_role('button', name='Edit message', exact=True)).to_have_count(0)
                expect(admin.get_by_role('button', name='Delete message', exact=True)).to_have_count(0)
                admin.keyboard.press('Escape')
                customer.get_by_label('Message', exact=True).fill('Please make the name bigger.')
                customer.get_by_role('button', name='Send message', exact=True).click()
                admin.bring_to_front()
                expect(admin.locator('.sc-message-text').last).to_have_text('Please make the name bigger.', timeout=15000)
                db.submit(BookingChangeRequest.objects.create, booking=self.booking, reason='Larger name', original_total=5000,
                    quoted_total=5000, status='applied', proposed={'_design_changed': True}, applied_at=timezone.now()).result()
                db.submit(self.client.post, reverse('admin_booking_design_upload', args=[self.booking.pk]),
                    {'design_image': _design_upload(), 'caption': 'Updated the name size.', 'submission_id': 'browser-revision'}).result()
                customer.bring_to_front()
                expect(customer.locator('.sc-design-delivery')).to_have_count(2, timeout=15000)
                expect(customer.locator('.sc-design-title').last).to_have_text('Updated design ready')
                db.submit(self.client.post, reverse('admin_booking_design_delete', args=[self.booking.pk, message.design_delivery_id])).result()
                customer.locator('.sc-design-delivery').first.scroll_into_view_if_needed()
                expect(customer.locator('.sc-design-delivery').first).to_contain_text('This design was removed', timeout=15000)
                expect(customer.locator('.sc-design-delivery').first.locator('img')).to_have_count(0)
                customer.get_by_role('link', name='View booking', exact=True).first.click()
                expect(customer.locator('#bookingModal')).to_be_visible()
                self.assertEqual(errors, [])
            finally:
                admin_context.close(); customer_context.close(); browser.close()
