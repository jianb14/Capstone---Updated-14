"""Concern status notices are atomic, owner-scoped and open the exact ticket."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from .context_processors import _customer_notif_target_url
from .models import Booking, ConcernTicket, Notification, User
from .views.admin import admin_concern_update


def concern_fixture():
    customer=User.objects.create_user(username='concern-notification-customer',first_name='Jamie',
        email='concern-notice@example.com',role='customer',email_verified=True)
    admin=User.objects.create_user(username='concern-notification-admin',role='admin',email_verified=True)
    ticket=ConcernTicket.objects.create(user=customer,category='account',subject='Please check my profile',message='Account details are not updating.')
    return customer,admin,ticket


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class ConcernNotificationTests(TestCase):
    def setUp(self):
        self.user,self.admin,self.ticket=concern_fixture()
        self.client.force_login(self.admin)

    def update(self,status,notes=''):
        return self.client.post(reverse('admin_concern_update',args=[self.ticket.pk]),{'status':status,'admin_notes':notes})

    def test_status_changes_create_one_unread_notice_without_a_booking(self):
        self.assertEqual(self.update('in_progress','We are investigating.').status_code,302)
        notice=Notification.objects.get()
        self.assertEqual(notice.user_id,self.user.pk)
        self.assertEqual(notice.concern_id,self.ticket.pk)
        self.assertIsNone(notice.booking_id)
        self.assertFalse(notice.is_read)
        self.assertIn('In Progress',notice.message)
        self.update('in_progress','We are investigating.')
        self.update('in_progress','A new response without a status change.')
        self.assertEqual(Notification.objects.count(),1)
        self.update('resolved','Profile fixed. Please check again.')
        self.assertEqual(Notification.objects.count(),2)
        self.assertIn('resolved',Notification.objects.order_by('-pk').first().message)
        self.update('resolved','Profile fixed.')
        self.assertEqual(Notification.objects.count(),2)
        self.update('new')
        self.assertEqual(Notification.objects.count(),3)

    def test_invalid_cancelled_and_unauthorized_updates_create_no_notice(self):
        self.update('invalid')
        self.update('cancelled')
        self.update('new','Please provide a screenshot.')
        self.assertFalse(Notification.objects.exists())
        self.ticket.status='cancelled';self.ticket.save(update_fields=['status'])
        self.update('resolved')
        self.assertFalse(Notification.objects.exists())
        self.client.force_login(self.user)
        self.assertEqual(self.update('in_progress').status_code,403)
        strict=Client(enforce_csrf_checks=True);strict.force_login(self.admin)
        self.assertEqual(strict.post(reverse('admin_concern_update',args=[self.ticket.pk]),{'status':'in_progress'}).status_code,403)

    def test_status_and_notice_rollback_together_when_update_fails(self):
        with patch('app.views.admin.log_action',side_effect=RuntimeError('Audit failed')):
            with self.assertRaises(RuntimeError):
                self.update('in_progress','Not committed')
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status,'new')
        self.assertFalse(self.ticket.admin_notes)
        self.assertFalse(Notification.objects.exists())

    def test_feed_and_read_count_support_concerns_and_preserve_ownership(self):
        self.update('in_progress')
        self.client.force_login(self.user)
        feed=self.client.get(reverse('customer_notification_feed')).json()
        self.assertEqual(feed['unread_count'],1)
        item=feed['items'][0]
        expected=f'{reverse("report_concern")}?concern_id={self.ticket.pk}&from_notif=1'
        self.assertEqual(item['target_url'],expected)
        self.assertEqual(self.client.get(reverse('customer_notification_feed'),{'summary':'1'}).json(),{'unread_count':1})
        self.assertEqual(self.client.post(item['read_url']).json()['unread_count'],0)
        self.assertEqual(self.client.get(reverse('customer_notification_feed'),{'summary':'1'}).json(),{'unread_count':0})
        other=User.objects.create_user(username='private-concern-owner',role='customer')
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse('customer_notification_feed')).json()['items'],[])
        self.assertEqual(self.client.get(expected).status_code,404)
        self.assertEqual(self.client.post(item['read_url']).status_code,404)

    def test_older_concern_opens_its_page_with_latest_response_and_clean_pagination_links(self):
        for i in range(18):
            ConcernTicket.objects.create(user=self.user,subject=f'Later concern {i}',message='Details')
        self.update('resolved','Fixed now. <b>This is plain text.</b>')
        notice=Notification.objects.get()
        self.client.force_login(self.user)
        response=self.client.get(_customer_notif_target_url(notice))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['tickets_page'].number,3)
        data=next(item for item in response.context['ticket_data'] if item['id']==self.ticket.pk)
        self.assertEqual(data['status'],'resolved')
        self.assertEqual(data['admin_notes'],'Fixed now. <b>This is plain text.</b>')
        self.assertEqual(self.client.get(reverse('report_concern'),{'concern_id':'invalid'}).status_code,404)
        self.assertEqual(self.client.get(reverse('report_concern'),{'concern_id':self.ticket.pk,'per_page':'4'}).context['tickets_page'].number,5)

    def test_notification_target_constraint_and_concern_cleanup(self):
        booking=Booking.objects.create(user=self.user,event_date=timezone.localdate(),event_location='Venue',total_price=1000)
        for targets in ({},{'booking':booking,'concern':self.ticket}):
            with self.assertRaises(IntegrityError),transaction.atomic():
                Notification.objects.create(user=self.user,message='Invalid target',**targets)
        legacy=Notification.objects.create(user=self.user,booking=booking,message='Existing booking notice')
        self.update('in_progress')
        self.ticket.delete()
        self.assertEqual(list(Notification.objects.values_list('pk',flat=True)),[legacy.pk])


class ConcernNotificationConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_parallel_identical_status_saves_only_notify_once(self):
        user,admin,ticket=concern_fixture()
        gate=Barrier(3)
        def update(_):
            close_old_connections()
            try:
                request=RequestFactory().post(reverse('admin_concern_update',args=[ticket.pk]),{'status':'in_progress','admin_notes':'Investigating'})
                request.user=admin;request.session={};request._messages=FallbackStorage(request)
                gate.wait(timeout=10)
                return admin_concern_update(request,ticket.pk).status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(update,range(3)))
        self.assertEqual(results,[302]*3)
        self.assertEqual(Notification.objects.filter(concern=ticket,user=user).count(),1)


@skipUnless(os.environ.get('RUN_CONCERN_NOTIFICATIONS_BROWSER')=='1','Optional browser verification')
@override_settings(SESSION_COOKIE_SECURE=False,CSRF_COOKIE_SECURE=False,REQUEST_RATE_LIMITING_ENABLED=False)
class ConcernNotificationBrowserTests(StaticLiveServerTestCase):
    def test_admin_update_reaches_customer_badge_and_opens_exact_older_concern_without_reload(self):
        from playwright.sync_api import expect,sync_playwright
        user,admin,ticket=concern_fixture()
        for i in range(12):
            ConcernTicket.objects.create(user=user,category='bug',subject=f'Newer issue {i}',message='Details')
        self.client.force_login(user)
        cookie={'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}
        admin_client=Client();admin_client.force_login(admin)
        admin_cookie={'name':settings.SESSION_COOKIE_NAME,'value':admin_client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}
        artifacts=Path(settings.BASE_DIR)/'.booking-followup-check';artifacts.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
            staff=browser.new_context()
            context.add_cookies([cookie]);staff.add_cookies([admin_cookie])
            context.route('https://fonts.googleapis.com/**',lambda route:route.abort())
            page=context.new_page();documents=[];errors=[]
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            page.on('pageerror',lambda error:errors.append(str(error)))
            self.assertEqual(staff.request.get(self.live_server_url+reverse('admin_concerns')).status,200)
            csrf=next(cookie['value'] for cookie in staff.cookies() if cookie['name']==settings.CSRF_COOKIE_NAME)
            def update(status,notes):
                response=staff.request.post(self.live_server_url+reverse('admin_concern_update',args=[ticket.pk]),
                    form={'status':status,'admin_notes':notes},headers={'X-CSRFToken':csrf},max_redirects=0)
                self.assertEqual(response.status,302)
            def check_badge(count):
                with page.expect_response(lambda r:'/notifications/?summary=1' in r.url):
                    page.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(page.locator('.notif-badge')).to_have_text(str(count))
            def click_notice(text):
                with page.expect_response(lambda r:r.url==self.live_server_url+reverse('customer_notification_feed')):
                    page.locator('#notif-bell').click()
                expect(page.locator('.notif-list')).not_to_have_attribute('aria-busy','true')
                page.locator('#notif-dropdown .notif-item').filter(has_text=text).click()
                expect(page.locator('#concernDetailModal')).to_be_visible()
                expect(page.locator('#modalTicket')).to_have_text(f'#CON-{ticket.pk}')
            try:
                page.goto(self.live_server_url+reverse('my_profile'),wait_until='domcontentloaded')
                expect(page.locator('.notif-badge')).to_have_count(0)
                update('in_progress','Our team is investigating your account issue.')
                check_badge(1)
                click_notice('In Progress')
                expect(page.locator('#accountContent')).to_have_attribute('data-account-page','report_concern')
                expect(page.locator('#modalStatus')).to_have_text('In Progress')
                expect(page.locator('#modalAdminNotes')).to_have_text('Our team is investigating your account issue.')
                expect(page.locator('#modalCancel')).to_be_hidden()
                expect(page.locator('.notif-badge')).to_have_count(0)
                self.assertIn('page=2',page.url)
                page.get_by_role('button',name='Close concern details',exact=True).click()
                page.get_by_role('link',name='Previous page',exact=True).click()
                page.wait_for_function('new URL(location.href).searchParams.get("page")==="1"')
                expect(page.locator('.account-table-summary')).to_contain_text('1–8')
                expect(page.locator('#concernDetailModal')).not_to_be_visible()
                update('resolved','The issue is fixed. Please check your profile.')
                update('resolved','The issue is fixed. Please check your profile.')
                check_badge(1)
                click_notice('has been resolved')
                expect(page.locator('#modalStatus')).to_have_text('Resolved')
                expect(page.locator('#modalAdminNotes')).to_have_text('The issue is fixed. Please check your profile.')
                for theme,width,height in (('light',1440,1000),('dark',390,844)):
                    page.set_viewport_size({'width':width,'height':height})
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    box=page.locator('#concernDetailModal').bounding_box()
                    self.assertGreaterEqual(box['x'],0)
                    self.assertLessEqual(box['x']+box['width'],width)
                    page.screenshot(path=str(artifacts/f'concern-status-notification-{theme}.png'))
                self.assertEqual(len(documents),1)
                self.assertEqual(errors,[])
            except Exception:
                page.screenshot(path=str(artifacts/'concern-notification-failure.png'))
                raise
            finally:
                staff.close();context.close();browser.close()
        self.assertEqual(Notification.objects.filter(concern=ticket).count(),2)
