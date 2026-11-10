"""Opt-in live browser tests: RUN_CUSTOMER_UPDATE_BAR_BROWSER=1."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Notification, Payment
from .test_customer_notifications import notification_fixture


@skipUnless(os.environ.get('RUN_CUSTOMER_UPDATE_BAR_BROWSER') == '1', 'Optional browser verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies',
                   SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, REQUEST_RATE_LIMITING_ENABLED=False)
class CustomerUpdateBarBrowserTests(StaticLiveServerTestCase):
    def test_offline_login_delivery_is_once_and_failed_receipts_retry_without_regrouping(self):
        from playwright.sync_api import expect, sync_playwright

        user, booking = notification_fixture()
        user.set_password('CustomerUpdates!123'); user.save()
        with ThreadPoolExecutor(max_workers=1) as database, sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
            context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(self.live_server_url+'/') else route.abort())
            page=context.new_page(); bar=page.locator('#customer-update-bar'); errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            ack_url=self.live_server_url+reverse('ack_customer_update_bar')

            def notice(message):
                return database.submit(lambda:Notification.objects.create(user_id=user.pk,booking_id=booking.pk,message=message).pk).result()

            def login():
                response=database.submit(lambda:self.client.post(reverse('login'),{'email':user.email,'password':'CustomerUpdates!123'})).result()
                self.assertEqual(response.status_code,302)
                context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
                page.goto(self.live_server_url+reverse('my_profile'),wait_until='networkidle')

            def logout():
                page.evaluate('sessionStorage.clear()')
                database.submit(self.client.logout).result()
                context.clear_cookies()
                page.goto(self.live_server_url+reverse('gallery'),wait_until='networkidle')

            try:
                page.goto(self.live_server_url+reverse('gallery'),wait_until='networkidle')
                first=notice(f'Great news! Your booking #{booking.pk} has been approved! Please proceed to payment.')
                login()
                expect(bar).to_be_visible()
                expect(bar.locator('.customer-update-title')).to_have_text(f'Booking #{booking.pk} approved.')
                self.assertTrue(database.submit(lambda:Notification.objects.get(pk=first).bar_shown_at is not None).result())
                self.assertFalse(database.submit(lambda:Notification.objects.get(pk=first).is_read).result())
                bar.get_by_role('button',name='Dismiss update',exact=True).click()
                logout(); login(); expect(bar).to_be_hidden()
                logout()
                notice(f'Your payment of PHP 1,500.00 for Booking #{booking.pk} has been verified. Thank you!')
                notice(f'Your backdrop design for booking #{booking.pk} is ready! Open your booking details to view and download it.')
                page.route(ack_url,lambda route:route.fulfill(status=503,json={'message':'Unavailable'}))
                login(); expect(bar.locator('.customer-update-title')).to_have_text('2 new updates')
                with page.expect_response(lambda response:response.url==ack_url and response.status==503):
                    page.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(bar.locator('.customer-update-title')).to_have_text('2 new updates')
                page.reload(wait_until='networkidle')
                expect(bar.locator('.customer-update-title')).to_have_text('2 new updates')
                page.unroute(ack_url)
                # Signing in in another tab rotates CSRF while this DOM stays old.
                database.submit(lambda:self.client.post(reverse('login'),{'email':user.email,'password':'CustomerUpdates!123'})).result()
                context.add_cookies([{'name':name,'value':self.client.cookies[name].value,'url':self.live_server_url}
                    for name in (settings.SESSION_COOKIE_NAME,settings.CSRF_COOKIE_NAME)])
                with page.expect_navigation(wait_until='networkidle'):
                    with page.expect_response(lambda response:'updates=1' in response.url and response.status==409):
                        page.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(bar).to_be_hidden()
                self.assertEqual(database.submit(lambda:Notification.objects.filter(user=user,bar_shown_at__isnull=False).count()).result(),3)
                self.assertEqual(database.submit(lambda:Notification.objects.filter(user=user,is_read=False).count()).result(),3)
                logout(); login(); expect(bar).to_be_hidden()
                self.assertEqual(errors,[])
            finally:
                database.submit(connections.close_all).result()
                context.close();browser.close()

    def test_navigation_keeps_remaining_time_grouping_and_dismissal(self):
        from playwright.sync_api import expect, sync_playwright

        user, booking = notification_fixture()
        self.client.force_login(user)
        with ThreadPoolExecutor(max_workers=1) as database, sync_playwright() as p:
            browser = p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width':1440,'height':1000}, reduced_motion='reduce')
            context.route('**/*', lambda route:route.continue_() if route.request.url.startswith(self.live_server_url+'/') else route.abort())
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            page = context.new_page(); bar = page.locator('#customer-update-bar'); errors=[]
            page.on('pageerror', lambda error:errors.append(str(error)))

            def notice():
                database.submit(lambda:Notification.objects.create(user_id=user.pk, booking_id=booking.pk,
                    message=f'Hooray! Your booking #{booking.pk} is now CONFIRMED! See you soon!')).result()

            def poll():
                page.wait_for_load_state('networkidle')
                with page.expect_response(lambda response:'updates=1' in response.url):
                    page.evaluate('window.dispatchEvent(new Event("focus"))')

            try:
                page.goto(self.live_server_url+reverse('my_profile'),wait_until='networkidle')
                notice(); poll(); expect(bar).to_be_visible()
                action=bar.locator('.customer-update-action')
                close=bar.locator('.customer-update-close')
                page.mouse.move(2,500)
                self.assertEqual(action.evaluate('el=>getComputedStyle(el).textDecorationLine'),'none')
                action.hover()
                self.assertEqual(action.evaluate('el=>getComputedStyle(el).textDecorationLine'),'underline')
                self.assertEqual(action.evaluate('el=>getComputedStyle(el).backgroundColor'),'rgba(0, 0, 0, 0)')
                close.hover()
                box=close.bounding_box()
                self.assertAlmostEqual(box['width'],box['height'],delta=1)
                page.mouse.move(2,500)
                page.wait_for_timeout(3000)
                def check_early_restore(route):
                    response=route.fetch()
                    html=response.text().replace('</body>', '<script>window.barVisibleDuringParse=!!document.getElementById("customer-update-bar")&&!document.getElementById("customer-update-bar").hidden;</script></body>')
                    route.fulfill(response=response,body=html)
                page.route(self.live_server_url+reverse('gallery'),check_early_restore)
                with page.expect_navigation(wait_until='networkidle'):
                    page.locator(f'.nav-links a[href="{reverse("gallery")}"]').click()
                expect(bar).to_be_visible()
                self.assertTrue(page.evaluate('window.barVisibleDuringParse'))
                expect(bar.locator('.customer-update-title')).to_have_text(f'Booking #{booking.pk} confirmed.')
                page.mouse.move(2,500)
                page.wait_for_timeout(2500)
                expect(bar).to_be_visible()
                # Resetting to eight seconds on the second page would fail this.
                page.wait_for_function('document.getElementById("customer-update-bar").hidden',timeout=3500)
                page.reload(wait_until='networkidle'); expect(bar).to_be_hidden()

                notice(); notice(); poll()
                expect(bar.locator('.customer-update-title')).to_have_text('2 new updates')
                page.goto(self.live_server_url+reverse('my_profile'),wait_until='networkidle')
                expect(bar).to_be_visible()
                expect(bar.locator('.customer-update-title')).to_have_text('2 new updates')
                notice(); poll()
                expect(bar.locator('.customer-update-title')).to_have_text('3 new updates')
                bar.get_by_role('button',name='Dismiss update',exact=True).click()
                page.reload(wait_until='networkidle'); expect(bar).to_be_hidden()
                page.go_back(wait_until='networkidle'); expect(bar).to_be_hidden()
                self.assertEqual(errors,[])
                self.assertEqual(database.submit(lambda:Notification.objects.filter(user=user,is_read=True).count()).result(),0)
            finally:
                database.submit(connections.close_all).result()
                context.close(); browser.close()

    def test_single_payment_action_reads_its_notice_and_guest_has_no_bar(self):
        from playwright.sync_api import expect, sync_playwright

        user, booking = notification_fixture()
        Payment.objects.create(booking=booking, amount=1500, payment_method='gcash',
            payment_status='verified', transaction_ref='update-bar-payment')
        self.client.force_login(user)
        with ThreadPoolExecutor(max_workers=1) as database, sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context=browser.new_context(reduced_motion='reduce')
            context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(self.live_server_url+'/') else route.abort())
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            page=context.new_page()
            try:
                page.goto(self.live_server_url+reverse('my_profile'),wait_until='networkidle')
                notice=database.submit(lambda:Notification.objects.create(user_id=user.pk,booking_id=booking.pk,
                    message=f'Your payment of PHP 1,500.00 for Booking #{booking.pk} has been verified. Thank you!').pk).result()
                with page.expect_response(lambda response:'updates=1' in response.url):
                    page.evaluate('window.dispatchEvent(new Event("focus"))')
                bar=page.locator('#customer-update-bar');expect(bar).to_be_visible()
                page.wait_for_load_state('networkidle')
                with page.expect_response(lambda response:response.url.endswith(f'/notifications/{notice}/read/')):
                    bar.get_by_role('button',name='View payment',exact=True).click()
                expect(page.locator('#accountContent')).to_have_attribute('data-account-page','my_payments')
                expect(page.locator('#modal-pay-ref')).to_have_text('update-bar-payment')
                self.assertTrue(database.submit(lambda:Notification.objects.get(pk=notice).is_read).result())
                context.clear_cookies()
                page.goto(self.live_server_url+reverse('gallery'),wait_until='networkidle')
                expect(page.locator('#customer-update-bar')).to_have_count(0)
            finally:
                database.submit(connections.close_all).result()
                context.close();browser.close()

    def test_single_two_grouping_recovery_navigation_and_accessibility(self):
        from playwright.sync_api import expect, sync_playwright

        user, booking = notification_fixture()
        approved = f'Great news! Your booking #{booking.pk} has been approved! Please proceed to payment.'
        Notification.objects.create(user=user, booking=booking, message=approved, bar_shown_at=timezone.now())
        self.client.force_login(user)
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check/customer-update-bar'
        artifacts.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=1) as database, sync_playwright() as p:
            browser = p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width':1440, 'height':1000}, reduced_motion='reduce')
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + '/') else route.abort())
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME, 'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url':self.live_server_url}])
            page = context.new_page(); errors=[]; reads=[]
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: reads.append(request.url) if request.method == 'POST' and request.url.endswith(('/read/','/clear-all/')) else None)
            bar = page.locator('#customer-update-bar')

            def notice(message):
                return database.submit(lambda: Notification.objects.create(user_id=user.pk, booking_id=booking.pk, message=message).pk).result()

            def poll():
                page.wait_for_load_state('networkidle')
                with page.expect_response(lambda response: 'updates=1' in response.url):
                    page.evaluate('window.dispatchEvent(new Event("focus"))')

            try:
                page.goto(self.live_server_url + reverse('my_profile'), wait_until='networkidle')
                expect(bar).to_have_count(1); expect(bar).to_be_hidden()
                page.get_by_role('button',name='Edit profile',exact=True).click()
                name = page.locator('#profile_first_name'); name.focus(); expect(name).to_be_focused()
                before = page.locator('h1').first.bounding_box()
                notice(approved)
                page.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(bar).to_be_hidden(); expect(name).to_be_focused()
                page.get_by_role('button',name='Close edit profile',exact=True).click()
                # Closing a native dialog resumes the deferred update check.
                expect(bar).to_be_visible()
                expect(bar.locator('.customer-update-title')).to_have_text(f'Booking #{booking.pk} approved.')
                expect(bar.locator('.customer-update-action')).to_have_text('View booking')
                self.assertAlmostEqual(page.locator('h1').first.bounding_box()['y'], before['y'], delta=1)
                poll(); expect(bar.locator('.customer-update-title')).to_have_text(f'Booking #{booking.pk} approved.')
                bar.get_by_role('button',name='Dismiss update',exact=True).click()
                expect(bar).to_be_hidden()
                page.reload(wait_until='networkidle'); expect(bar).to_be_hidden()
                # Two new records must group even when unread count has no net increase.
                database.submit(lambda: Notification.objects.filter(user=user).update(is_read=True)).result()
                notice(f'Your payment of PHP 1,500.00 for Booking #{booking.pk} has been verified. Thank you!')
                notice(f'Your backdrop design for booking #{booking.pk} is ready! Open your booking details to view and download it.')
                poll(); expect(bar.locator('.customer-update-title')).to_have_text('2 new updates')
                expect(bar.locator('.customer-update-action')).to_have_text('View updates')
                for width, theme in ((1440,'light'), (390,'light'), (390,'dark'), (320,'dark'), (1440,'dark')):
                    page.set_viewport_size({'width':width,'height':844 if width < 500 else 1000})
                    page.evaluate('theme=>document.documentElement.dataset.theme=theme', theme)
                    bounds=bar.bounding_box()
                    self.assertAlmostEqual(bounds['width'],width,delta=1)
                    self.assertAlmostEqual(bounds['y'],page.locator('.navbar').bounding_box()['height'],delta=1)
                    self.assertFalse(bar.evaluate('el=>el.scrollWidth>el.clientWidth'))
                    page.screenshot(path=str(artifacts/f'grouped-{width}-{theme}.png'))
                expect(bar).to_have_count(1)
                bar.get_by_role('button', name='View updates', exact=True).click()
                expect(page.locator('#notif-dropdown')).to_be_visible(); expect(bar).to_be_hidden()
                self.assertEqual(reads, [])
                page.keyboard.press('Escape')
                page.set_viewport_size({'width':1440,'height':1000})
                page.goto(self.live_server_url + reverse('gallery'), wait_until='networkidle')
                expect(bar).to_be_hidden()
                notice(f'Booking change request #1 for Booking #{booking.pk}: Your quote is ready. Open Booking Details to review and accept it before the deadline.')
                endpoint=self.live_server_url+reverse('customer_notification_feed')
                fail=[True]
                def failing_once(route):
                    if 'updates=1' in route.request.url and fail[0]:
                        fail[0]=False;route.fulfill(status=503,json={'message':'Temporarily unavailable'})
                    else: route.continue_()
                page.route(endpoint+'?*',failing_once)
                poll(); expect(bar).to_be_hidden()
                poll(); expect(bar.locator('.customer-update-action')).to_have_text('Review quote')
                bar.locator('.customer-update-action').focus()
                page.wait_for_timeout(8500); expect(bar).to_be_visible()
                bar.get_by_role('button',name='Dismiss update',exact=True).click(); expect(bar).to_be_hidden()
                expect(page.locator('#notif-bell')).to_be_focused()
                page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'))")
                notice(f'Booking #{booking.pk} expired. The initial payment deadline passed.')
                page.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(bar).to_be_hidden()
                with page.expect_response(lambda response:'updates=1' in response.url):
                    page.evaluate("delete document.hidden;document.dispatchEvent(new Event('visibilitychange'))")
                expect(bar).to_be_visible()
                page.mouse.move(2,700)
                page.wait_for_function('document.getElementById("customer-update-bar").hidden', timeout=11000)
                # A sign-in changed in another tab must refresh this stale shell,
                # delivering undisplayed notifications from the previous login.
                database.submit(lambda:self.client.force_login(user)).result()
                context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
                notice(approved)
                with page.expect_navigation(wait_until='networkidle'):
                    with page.expect_response(lambda response:'updates=1' in response.url and response.status==409):
                        page.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(bar).to_be_visible()
                expect(bar.locator('.customer-update-title')).to_have_text(f'Booking #{booking.pk} approved.')
                self.assertEqual(reads, [])
                self.assertEqual(errors, [])
            finally:
                database.submit(connections.close_all).result()
                context.close();browser.close()
