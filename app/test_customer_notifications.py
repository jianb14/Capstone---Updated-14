"""Customer notification links, persistence and live navbar interactions."""
import os
from datetime import timedelta, time
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from .context_processors import _customer_notif_target_url
from .models import Booking, Notification, Payment, User


def notification_fixture():
    user=User.objects.create_user(username='notification-customer',first_name='Jamie',last_name='Rivera',
        email='notify@example.com',phone_number='09170000000',role='customer',email_verified=True)
    booking=Booking.objects.create(user=user,event_type='Birthday',event_date=timezone.localdate()+timedelta(days=80),
        event_time=time(9),event_end_time=time(11),event_location='Customer venue',package_type='Package 1-A',
        total_price=10000,status='confirmed')
    return user,booking


class CustomerNotificationTests(TestCase):
    def setUp(self):
        self.user,self.booking=notification_fixture()
        self.client.force_login(self.user)

    def notice(self,message='Your booking is confirmed'):
        return Notification.objects.create(user=self.user,booking=self.booking,message=message)

    def test_reads_are_post_only_owner_scoped_and_return_true_remaining_count(self):
        own=self.notice()
        other=User.objects.create_user(username='other-notifier',role='customer')
        foreign=Notification.objects.create(user=other,booking=self.booking,message='Private update')
        url=reverse('mark_customer_notification_read',args=[own.pk])
        self.assertEqual(self.client.get(url).status_code,405)
        self.assertFalse(Notification.objects.get(pk=own.pk).is_read)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.user)
        self.assertEqual(csrf.post(url).status_code,403)
        self.assertEqual(self.client.post(reverse('mark_customer_notification_read',args=[foreign.pk])).status_code,404)
        self.assertEqual(self.client.post(url).json()['unread_count'],0)
        self.assertEqual(self.client.post(url).status_code,200)
        self.assertFalse(Notification.objects.get(pk=foreign.pk).is_read)
        self.notice();self.notice()
        self.assertEqual(self.client.post(reverse('clear_all_notifications')).json()['unread_count'],0)
        self.assertFalse(Notification.objects.get(pk=foreign.pk).is_read)

    def test_feed_never_reads_and_cursor_is_stable_with_new_arrivals_and_equal_dates(self):
        stamp=timezone.now()
        rows=[self.notice(f'Update {i}') for i in range(25)]
        Notification.objects.filter(user=self.user).update(created_at=stamp)
        first=self.client.get(reverse('customer_notification_feed'))
        self.assertEqual(first.status_code,200)
        data=first.json();self.assertEqual(len(data['items']),20)
        self.assertEqual(data['unread_count'],25)
        self.assertEqual(first['Cache-Control'],'private, no-store')
        self.assertEqual(data['items'][0]['id'],rows[-1].pk)
        self.notice('Arrived between pages')
        second=self.client.get(reverse('customer_notification_feed'),{'cursor':data['next_cursor']}).json()
        ids=[row['id'] for row in data['items']+second['items']]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(set(ids),{row.pk for row in rows})
        self.assertIsNone(second['next_cursor'])
        self.assertEqual(Notification.objects.filter(user=self.user,is_read=False).count(),26)
        self.assertEqual(self.client.get(reverse('customer_notification_feed'),{'cursor':'invalid'}).status_code,400)
        self.assertEqual(self.client.post(reverse('customer_notification_feed')).status_code,405)

    def test_feed_hides_other_users_and_guards_role(self):
        self.notice('<script>plain text</script>')
        other=User.objects.create_user(username='feed-other',role='customer')
        Notification.objects.create(user=other,booking=self.booking,message='Other private notice')
        response=self.client.get(reverse('customer_notification_feed')).json()
        self.assertEqual([n['message'] for n in response['items']],['<script>plain text</script>'])
        self.user.role='admin';self.user.save(update_fields=['role'])
        self.assertEqual(self.client.get(reverse('customer_notification_feed')).status_code,403)

    def test_expired_or_denied_notices_do_not_open_an_empty_payment_tab(self):
        for message in ('Booking expired. Initial payment deadline passed.',
                'Your booking was NOT approved. Reason: payment issue.'):
            url=_customer_notif_target_url(self.notice(message))
            self.assertIn(f'/customer/?booking_id={self.booking.pk}&modal=details',url)
        self.booking.status='expired';self.booking.save(update_fields=['status'])
        self.assertIn('modal=details',_customer_notif_target_url(self.notice('Approved! Please proceed to payment.')))

    def test_unusual_message_text_cannot_break_the_navbar_or_match_review_by_substring(self):
        self.assertIn('/customer/',_customer_notif_target_url(self.notice('Corporate event confirmed.')))
        self.assertIn('modal=details',_customer_notif_target_url(self.notice('Payment note: PHP , unavailable.')))

    def test_payment_notice_uses_existing_record_and_opens_its_actual_page(self):
        target=Payment.objects.create(booking=self.booking,amount=1000,payment_method='gcash',
            payment_status='verified',transaction_ref='notice-target')
        notice=self.notice('Your payment of PHP 1,000.00 has been verified.')
        for i in range(10):
            Payment.objects.create(booking=self.booking,amount=200,payment_method='gcash',
                payment_status='verified',transaction_ref=f'newer-payment-{i}')
        url=_customer_notif_target_url(notice)
        self.assertIn(f'payment_id={target.pk}',url)
        response=self.client.get(url)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['payments_page_obj'].number,2)
        self.assertIn(target.pk,[pay.pk for pay in response.context['payments_page_obj']])
        other=User.objects.create_user(username='payment-isolation',role='customer')
        self.client.force_login(other)
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.client.get(reverse('my_payments'),{'payment_id':'invalid'}).status_code,404)

    def test_current_balance_notification_finds_matching_booking_or_details(self):
        notice=self.notice('Payment Reminder: please settle your balance.')
        for i in range(10):
            Booking.objects.create(user=self.user,event_type=f'Later {i}',event_date=self.booking.event_date,
                event_location='Venue',status='pending_payment',total_price=5000)
        response=self.client.get(_customer_notif_target_url(notice))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['action_required_page_obj'].number,2)
        self.booking.status='completed';self.booking.save(update_fields=['status'])
        stale=f'{reverse("my_payments")}?booking_id={self.booking.pk}&from_notif=1'
        self.assertRedirects(self.client.get(stale),f'{reverse("customer_profile")}?booking_id={self.booking.pk}&modal=details&from_notif=1',fetch_redirect_response=False)

    def test_pagination_does_not_reopen_notification_modals(self):
        from django.test import RequestFactory
        from .templatetags.account_ui import account_page_url
        request=RequestFactory().get('/my-payments/',{'payment_id':'1','booking_id':'2','modal':'details',
            'from_notif':'1','tab':'payment_history','status':'verified'})
        url=account_page_url({'request':request},'payments_page',2)
        self.assertNotIn('payment_id',url)
        self.assertNotIn('from_notif',url)
        self.assertNotIn('booking_id',url)
        self.assertIn('status=verified',url)
        self.assertIn('payments_page=2',url)


@skipUnless(os.environ.get('RUN_CUSTOMER_NOTIFICATIONS_BROWSER')=='1','Optional browser verification')
@override_settings(SESSION_COOKIE_SECURE=False,CSRF_COOKIE_SECURE=False,REQUEST_RATE_LIMITING_ENABLED=False)
class CustomerNotificationBrowserTests(StaticLiveServerTestCase):
    def test_slow_feed_cannot_restore_unread_state_after_mark_all(self):
        from playwright.sync_api import expect,sync_playwright
        user,booking=notification_fixture()
        Notification.objects.create(user=user,booking=booking,message='Your booking is confirmed.')
        self.client.force_login(user)
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context=browser.new_context(viewport={'width':1280,'height':900},reduced_motion='reduce')
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            page=context.new_page()
            try:
                page.goto(self.live_server_url+reverse('my_profile'),wait_until='domcontentloaded')
                endpoint=self.live_server_url+reverse('customer_notification_feed')
                stale=context.request.get(endpoint).json()
                held=[]
                def hold_first(route):
                    if not held:
                        held.append(route)
                    else:
                        route.continue_()
                page.route('**/notifications/',hold_first)
                with page.expect_request(endpoint):
                    page.locator('#notif-bell').click()
                page.get_by_role('button',name='Mark all as read',exact=True).click()
                expect(page.locator('.notif-badge')).to_have_count(0)
                self.assertEqual(len(held),1)
                held[0].fulfill(json=stale)
                expect(page.locator('.notif-list')).not_to_have_attribute('aria-busy','true')
                expect(page.locator('#notif-dropdown .notif-item.unread')).to_have_count(0)
                expect(page.locator('#notif-summary')).to_have_text("You're all caught up")
                expect(page.locator('#notif-dropdown')).to_be_visible()
            finally:
                context.close();browser.close()

    def test_panel_clicks_reads_retry_paging_modals_and_responsive_navigation(self):
        from playwright.sync_api import expect,sync_playwright
        user,booking=notification_fixture()
        payment=Payment.objects.create(booking=booking,amount=1000,payment_status='verified',
            payment_method='gcash',transaction_ref='notification-browser-payment')
        for i in range(23):
            Notification.objects.create(user=user,booking=booking,message=f'Booking update {i}')
        notice=Notification.objects.create(user=user,booking=booking,message='Your payment of PHP 1,000.00 has been verified.')
        expired=Booking.objects.create(user=user,event_type='Expired event',event_date=booking.event_date,
            event_location='Venue',status='expired',total_price=1000)
        expiration=Notification.objects.create(user=user,booking=expired,message='Booking expired. Initial payment deadline passed.')
        self.client.force_login(user)
        artifacts=Path(settings.BASE_DIR)/'.booking-followup-check';artifacts.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            context.route('https://fonts.googleapis.com/**',lambda route:route.abort())
            page=context.new_page();errors=[];documents=[];read_requests=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            page.on('request',lambda request:read_requests.append(request.url) if request.url.endswith('/read/') or request.url.endswith('/clear-all/') else None)
            bell=page.locator('#notif-bell');panel=page.locator('#notif-dropdown')
            def open_panel():
                with page.expect_response(lambda r:r.url==self.live_server_url+reverse('customer_notification_feed')):
                    bell.click()
                expect(panel).to_be_visible()
                expect(panel.locator('.notif-list')).not_to_have_attribute('aria-busy','true')
            try:
                page.goto(self.live_server_url+reverse('my_profile'),wait_until='domcontentloaded')
                open_panel()
                expect(panel.locator('.notif-item')).to_have_count(20)
                expect(page.locator('.notif-badge')).to_have_text('25')
                self.assertEqual(read_requests,[])
                panel.get_by_role('button',name='Load earlier notifications',exact=True).click()
                expect(panel.locator('.notif-item')).to_have_count(25)
                expect(panel.get_by_role('button',name='Load earlier notifications',exact=True)).to_be_hidden()
                page.route('**/notifications/*/read/',lambda route:route.fulfill(status=503,json={'message':'Unavailable'}))
                panel.locator(f'[data-id="{expiration.pk}"]').click()
                expect(page.locator('#accountContent')).to_have_attribute('data-account-page','customer_profile')
                expect(page.locator('#bookingModal')).to_be_visible()
                expect(page.locator('#bookingModal .booking-dialog-id')).to_contain_text(str(expired.pk))
                page.keyboard.press('Escape')
                page.unroute('**/notifications/*/read/')
                open_panel()
                expect(panel.locator(f'[data-id="{expiration.pk}"]')).to_have_class('notif-item unread')
                with page.expect_response(lambda r:r.url.endswith(f'/notifications/{notice.pk}/read/')):
                    panel.locator(f'[data-id="{notice.pk}"]').click()
                expect(page.locator('#accountContent')).to_have_attribute('data-account-page','my_payments')
                expect(page.locator('#bookingModal')).to_have_attribute('aria-hidden','false')
                expect(page.locator('#modal-pay-ref')).to_have_text('notification-browser-payment')
                expect(page.locator('.notif-badge')).to_have_text('24')
                page.get_by_role('button',name='Done',exact=True).click()
                open_panel()
                page.route('**/notifications/clear-all/',lambda route:route.fulfill(status=503,json={'message':'Unavailable'}))
                panel.get_by_role('button',name='Mark all as read',exact=True).click()
                expect(panel.locator('.notif-feedback')).to_contain_text('still unread')
                expect(page.locator('.notif-badge')).to_have_text('24')
                page.unroute('**/notifications/clear-all/')
                panel.get_by_role('button',name='Try again',exact=True).click()
                expect(page.locator('.notif-badge')).to_have_count(0)
                expect(panel.locator('.notif-item.unread')).to_have_count(0)
                expect(panel).to_be_visible()
                for theme in ('light','dark'):
                    for width,height in ((1440,1000),(390,844),(320,568),(640,360)):
                        page.set_viewport_size({'width':width,'height':height})
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                        page.wait_for_function('!document.querySelector(".nav-links").getAnimations().some(animation=>animation.playState==="running")')
                        box=panel.bounding_box()
                        self.assertGreaterEqual(box['x'],0)
                        self.assertGreaterEqual(box['y'],0)
                        self.assertLessEqual(box['x']+box['width'],width)
                        self.assertLessEqual(box['y']+box['height'],height)
                        if width<=600:
                            self.assertAlmostEqual(box['x'],12,delta=1)
                        self.assertTrue(panel.evaluate('(el)=>el.scrollWidth<=el.clientWidth+1'))
                        self.assertTrue(panel.evaluate('(el)=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+20,r.y+20));}'))
                        page.screenshot(path=str(artifacts/f'notification-panel-{theme}-{width}.png'))
                page.keyboard.press('Escape');expect(bell).to_be_focused()
                page.locator('.profile-avatar-btn').click()
                expect(page.locator('#clientAccountMenu')).to_be_visible()
                open_panel();expect(page.locator('#clientAccountMenu')).to_be_hidden()
                page.locator('.profile-avatar-btn').click();expect(panel).to_be_hidden()
                page.keyboard.press('Escape')
                page.route('**/notifications/',lambda route:route.fulfill(status=503,json={'message':'Unavailable'}))
                bell.click();expect(panel.locator('.notif-feedback')).to_contain_text('Unavailable')
                expect(panel.locator('.notif-item')).to_have_count(20)
                page.unroute('**/notifications/')
                panel.get_by_role('button',name='Try again',exact=True).click()
                expect(panel.locator('.notif-feedback')).to_be_hidden()
                self.assertEqual(len(documents),1)
                self.assertEqual(errors,[])
            except Exception:
                page.screenshot(path=str(artifacts/'notification-browser-failure.png'))
                raise
            finally:
                context.close();browser.close()
        self.assertEqual(Notification.objects.filter(user=user,is_read=False).count(),0)
