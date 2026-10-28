"""The operational concern queue and staff feed include every submitted ticket."""
import os
import uuid
from datetime import datetime, timedelta, time, timezone as dt_timezone
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AdminNotification, Booking, ConcernTicket, Notification, User
from .views.admin import _get_reporting_date_range
from .test_concerns import payload


def fixture():
    customer=User.objects.create_user(username='admin-concern-customer',first_name='Jamie',last_name='Rivera',
        email='queue@example.com',phone_number='09170000000',role='customer',email_verified=True)
    admin=User.objects.create_user(username='admin-concern-staff',first_name='Alex',role='admin',email_verified=True)
    return customer,admin


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminConcernTests(TestCase):
    def setUp(self):
        self.user,self.admin=fixture();self.client.force_login(self.admin)
        self.enterContext(patch('app.views.profiles.send_admin_alert_email',return_value=True))

    def ticket(self,**kwargs):
        return ConcernTicket.objects.create(user=self.user,subject='Subject',message='Details',**kwargs)

    def test_default_includes_old_and_new_tickets_and_kpi_matches_sidebar(self):
        old=self.ticket();ConcernTicket.objects.filter(pk=old.pk).update(created_at=timezone.now()-timedelta(days=100))
        new=self.ticket();self.ticket(status='resolved');self.ticket(status='cancelled')
        response=self.client.get(reverse('admin_concerns'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['counts']['total'],4)
        self.assertEqual(response.context['new_concerns_count'],2)
        self.assertEqual(response.context['new_concerns'],2)
        self.assertEqual([ticket.pk for ticket in response.context['concern_rows']],list(ConcernTicket.objects.order_by('-created_at','-pk').values_list('pk',flat=True)))
        self.assertContains(response,str(new.pk));self.assertNotContains(response,'Recent Admin Notifications')

    def test_reporting_today_uses_philippine_date_after_midnight(self):
        from django.test import RequestFactory
        stamp=datetime(2026,10,25,18,0,tzinfo=dt_timezone.utc)
        with timezone.override('Asia/Manila'),patch('django.utils.timezone.now',return_value=stamp):
            start,end=_get_reporting_date_range(RequestFactory().get('/',{'filter_preset':'today'}))
        self.assertEqual(start.isoformat(),'2026-10-26');self.assertEqual(start,end)

    def test_submission_creates_one_exact_target_admin_notice_even_after_retries(self):
        client=Client();client.force_login(self.user);key=str(uuid.uuid4())
        for _ in range(3):
            response=client.post(reverse('report_concern'),payload(submission_key=key,subject='Payment and review problem'),HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code,200)
        ticket=ConcernTicket.objects.get();notice=AdminNotification.objects.get()
        self.assertEqual(notice.concern,ticket);self.assertEqual(notice.user,self.user)
        feed=self.client.get(reverse('admin_notification_feed')).json()
        self.assertEqual(feed['unread_count'],1);self.assertEqual(feed['new_concerns_count'],1)
        self.assertEqual(feed['items'][0]['target_url'],f"{reverse('admin_concerns')}?concern_id={ticket.pk}")
        self.assertFalse(AdminNotification.objects.get().is_read)

    def test_search_filters_stable_paging_and_bounded_show(self):
        for i in range(12):self.ticket(category='bug',status='new' if i%2 else 'in_progress')
        for query,size in ({},8),({'per_page':'4'},4),({'per_page':'999'},8):
            response=self.client.get(reverse('admin_concerns'),query)
            self.assertEqual(len(response.context['concern_rows']),size)
        response=self.client.get(reverse('admin_concerns'),{'q':'Jamie','category':'bug','concern_status':'new','per_page':'4','page':2},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['page'],2)
        self.assertEqual(response.json()['html'].count('class="ac-icon-btn btn-view-concern"'),2)
        ticket=self.ticket();response=self.client.get(reverse('admin_concerns'),{'q':f'#CON-{ticket.pk}'})
        self.assertEqual(list(response.context['concern_rows']),[ticket])
        empty=self.client.get(reverse('admin_concerns'),{'q':'no matching concern'})
        self.assertContains(empty,'No matching concerns')

    def test_explicit_dates_only_filter_table_and_invalid_ranges_are_rejected(self):
        old=self.ticket();ConcernTicket.objects.filter(pk=old.pk).update(created_at=timezone.now()-timedelta(days=100))
        today=self.ticket();stamp=timezone.localdate().isoformat()
        response=self.client.get(reverse('admin_concerns'),{'start_date':stamp,'end_date':stamp})
        self.assertEqual(list(response.context['concern_rows']),[today]);self.assertEqual(response.context['new_concerns'],2)
        for query in ({'start_date':stamp},{'start_date':'bad','end_date':stamp},{'start_date':'2026-10-26','end_date':'2026-10-25'}):
            response=self.client.get(reverse('admin_concerns'),query,HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code,400);self.assertTrue(response.json()['error'])

    def test_detail_permissions_fresh_data_update_validation_and_cancelled_conflict(self):
        ticket=self.ticket();details=reverse('admin_concern_details',args=[ticket.pk]);url=reverse('admin_concern_update',args=[ticket.pk])
        self.client.force_login(self.user);self.assertEqual(self.client.get(details).status_code,403)
        legacy=User.objects.create_user(username='retired-role',role='staff');self.client.force_login(legacy)
        self.assertEqual(self.client.get(details).status_code,403);self.assertEqual(self.client.post(url,{'status':'resolved'}).status_code,403)
        self.client.force_login(self.admin)
        for data in ({'status':'cancelled'},{'status':'resolved','admin_notes':'x'*10001}):
            self.assertEqual(self.client.post(url,data,HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code,400)
        response=self.client.post(url,{'status':'in_progress','admin_notes':'Investigating'},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.json()['ticket']['admin_notes'],'Investigating');self.assertEqual(Notification.objects.filter(concern=ticket).count(),1)
        self.assertEqual(self.client.get(details).json()['ticket']['status'],'in_progress')
        ConcernTicket.objects.filter(pk=ticket.pk).update(status='cancelled')
        self.assertEqual(self.client.post(url,{'status':'resolved'},HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code,409)
        strict=Client(enforce_csrf_checks=True);strict.force_login(self.admin)
        self.assertEqual(strict.post(url,{'status':'new'}).status_code,403)

    def test_admin_feed_read_actions_permissions_and_hidden_counts(self):
        ticket=self.ticket();notice=AdminNotification.objects.create(user=self.user,concern=ticket,message='New concern')
        AdminNotification.objects.create(user=self.user,message='Hidden',is_hidden=True)
        url=reverse('mark_admin_notification_read',args=[f'n_{notice.pk}'])
        self.assertEqual(self.client.get(url).status_code,405)
        strict=Client(enforce_csrf_checks=True);strict.force_login(self.admin);self.assertEqual(strict.post(url).status_code,403)
        self.client.force_login(self.user);self.assertEqual(self.client.get(reverse('admin_notification_feed')).status_code,403)
        self.assertEqual(self.client.post(url).status_code,403);self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('admin_notification_feed'),{'summary':1}).json()['unread_count'],1)
        self.assertEqual(self.client.post(url).json()['unread_count'],0)
        self.assertTrue(AdminNotification.objects.get(pk=notice.pk).is_read)
        self.assertEqual(self.client.post(reverse('mark_admin_notification_read',args=['n_bad'])).status_code,400)
        self.assertEqual(self.client.post(reverse('mark_notifications_read')).json()['unread_count'],0)

    def test_merged_cursor_keeps_every_item_when_timestamps_tie(self):
        booking=Booking.objects.create(user=self.user,event_date=timezone.localdate()+timedelta(days=100),
            event_time=time(10),event_type='Birthday',event_location='Test venue',package_type='Package 1',total_price=1000,status='confirmed')
        notices=[AdminNotification.objects.create(user=self.user,booking=booking,message='Review update') for _ in range(44)]
        stamp=timezone.now();AdminNotification.objects.update(created_at=stamp);Booking.objects.filter(pk=booking.pk).update(created_at=stamp)
        seen=[];cursor=None
        while True:
            response=self.client.get(reverse('admin_notification_feed'),{'cursor':cursor} if cursor else {})
            self.assertEqual(response.status_code,200);data=response.json();seen.extend(row['id'] for row in data['items']);cursor=data['next_cursor']
            if not cursor:break
        self.assertEqual(len(seen),45);self.assertEqual(len(set(seen)),45)
        self.assertEqual(seen[-1],f'b_{booking.pk}')
        self.assertEqual(self.client.get(reverse('admin_notification_feed'),{'cursor':'tampered'}).status_code,400)
        self.assertEqual(self.client.post(reverse('hide_notification',args=[f'n_{notices[0].pk}'])).status_code,200)


@skipUnless(os.environ.get('RUN_ADMIN_CONCERNS_BROWSER')=='1','Optional isolated admin concern browser checks')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminConcernBrowserTests(StaticLiveServerTestCase):
    def test_submission_admin_click_update_search_pagination_and_responsive_controls(self):
        from playwright.sync_api import expect,sync_playwright
        user,admin=fixture()
        for i in range(11):ConcernTicket.objects.create(user=user,subject=f'Existing concern {i}',message='Earlier report',category='bug')
        admin_client=Client();admin_client.force_login(admin);customer_client=Client();customer_client.force_login(user)
        artifacts=Path(settings.BASE_DIR)/'.booking-followup-check';artifacts.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000});customer=browser.new_context()
            for target,client in ((context,admin_client),(customer,customer_client)):
                target.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
                target.route('https://fonts.googleapis.com/**',lambda route:route.abort())
                target.route('https://cdnjs.cloudflare.com/**',lambda route:route.abort())
                target.route('https://cdn.jsdelivr.net/**',lambda route:route.fulfill(status=200,content_type='application/javascript',body='window.Swal={mixin:()=>({fire:()=>{}})};'))
            context.add_init_script("localStorage.setItem('balloorina-theme','light')")
            page=context.new_page();errors=[];documents=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            try:
                page.goto(self.live_server_url+reverse('admin_concerns'))
                expect(page.locator('.ac-table tbody tr')).to_have_count(8)
                expect(page.locator('[data-stat="new"]')).to_have_text('11')
                expect(page.locator('.sidebar [data-concerns-link] .nav-count-badge')).to_have_text('11')
                customer.request.get(self.live_server_url+reverse('report_concern'))
                csrf=next(cookie['value'] for cookie in customer.cookies() if cookie['name']==settings.CSRF_COOKIE_NAME)
                with patch('app.views.profiles.send_admin_alert_email',return_value=True):
                    response=customer.request.post(self.live_server_url+reverse('report_concern'),
                        form=payload(subject='Fresh submission across midnight',submission_key=str(uuid.uuid4())),
                        headers={'X-CSRFToken':csrf,'X-Requested-With':'XMLHttpRequest'})
                self.assertEqual(response.status,200)
                page.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(page.locator('.notif-badge')).to_have_text('1')
                expect(page.locator('.ac-table tbody tr').first).to_contain_text('Fresh submission across midnight')
                page.locator('#notif-bell').click()
                expect(page.locator('#notif-dropdown .notif-item')).to_have_count(1)
                page.locator('#notif-dropdown .notif-item').click()
                expect(page.locator('#concernDetailModal')).to_be_visible()
                expect(page.locator('#concernModalTitle')).to_have_text('Fresh submission across midnight')
                page.get_by_role('button',name='Concern status: New',exact=True).click()
                page.get_by_role('option',name='In Progress',exact=True).click()
                page.locator('#acUpdateNotes').fill('We are reviewing your concern now.')
                page.locator('#acUpdateSubmit').click()
                expect(page.locator('#acUpdateFeedback')).to_contain_text('Changes are visible')
                toast=page.locator('.cfg-toast')
                expect(toast).to_have_attribute('data-kind','success')
                expect(toast).to_contain_text('Concern updated. Changes are visible to the customer.')
                self.assertTrue(toast.evaluate("el=>el.matches(':popover-open')"))
                self.assertLess(toast.bounding_box()['y'],100)
                self.assertGreater(toast.bounding_box()['x'],900)
                expect(page.locator('#acUpdateSubmit')).to_be_enabled()
                expect(page.locator('[data-stat="in_progress"]')).to_have_text('1')
                expect(page.locator('#acDetailStatus')).to_have_text('In Progress')
                for theme,width,height in (('light',1440,1000),('dark',390,844)):
                    page.set_viewport_size({'width':width,'height':height});page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    box=page.locator('#concernDetailModal').bounding_box();self.assertGreaterEqual(box['x'],0);self.assertLessEqual(box['x']+box['width'],width)
                    page.screenshot(path=str(artifacts/f'admin-concern-modal-{theme}.png'),animations='disabled')
                page.get_by_role('button',name='Close concern details',exact=True).click()
                page.set_viewport_size({'width':1440,'height':1000});page.evaluate("document.documentElement.dataset.theme='light'")
                before=len(documents)
                page.get_by_role('searchbox',name='Search concerns').fill('Existing concern 5')
                expect(page.locator('.ac-table tbody tr')).to_have_count(1)
                page.get_by_role('button',name='Clear search',exact=True).click()
                expect(page.locator('.ac-table tbody tr')).to_have_count(8)
                page.get_by_role('link',name='Next page',exact=True).click()
                expect(page.locator('.ac-table tbody tr')).to_have_count(4)
                page.get_by_role('button',name='Rows per page: 8',exact=True).click()
                page.get_by_role('option',name='4',exact=True).click()
                expect(page.locator('.account-table-summary')).to_contain_text('1–4')
                page.get_by_role('searchbox',name='Search concerns').fill('nothing matches')
                expect(page.locator('.ac-empty h3')).to_have_text('No matching concerns')
                expect(page.locator('.ac-table')).to_have_count(0)
                expect(page.locator('.account-table-footer')).to_have_count(0)
                expect(page.locator('.ac-empty .account-empty-icon')).to_be_visible()
                page.locator('.ac-empty').screenshot(path=str(artifacts/'admin-concern-empty-corrected.png'),animations='disabled')
                page.get_by_role('button',name='Clear filters',exact=True).click()
                expect(page.locator('.ac-table tbody tr')).to_have_count(4)
                self.assertEqual(before,len(documents))
                for theme,width,height in (('light',1440,1000),('dark',390,844)):
                    page.set_viewport_size({'width':width,'height':height});page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    if width<1025:page.wait_for_function('document.querySelector(".sidebar").getBoundingClientRect().right<=0')
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                    page.screenshot(path=str(artifacts/f'admin-concern-queue-{theme}.png'),full_page=True,animations='disabled')
                page.locator('.profile-avatar-btn').click();expect(page.locator('#adminAccountMenu')).to_be_visible()
                page.keyboard.press('Escape');expect(page.locator('#adminAccountMenu')).to_be_hidden()
                page.locator('.theme-toggle-btn').click()
                page.wait_for_function('!document.documentElement.classList.contains("theme-revealing")')
                expect(page.locator('.theme-toggle-btn')).to_have_attribute('aria-label','Switch to dark mode')
                page.locator('#notif-bell').click()
                expect(page.locator('#notif-dropdown .notif-item')).to_have_count(1)
                expect(page.get_by_role('button',name='Remove notification',exact=True)).to_have_count(0)
                self.assertEqual(errors,[])
            except Exception:
                page.screenshot(path=str(artifacts/'admin-concern-failure.png'),full_page=True);raise
            finally:
                customer.close();context.close();browser.close()
        self.assertEqual(Notification.objects.get().concern.subject,'Fresh submission across midnight')
        self.assertTrue(AdminNotification.objects.get().is_read)
        self.assertFalse(AdminNotification.objects.get().is_hidden)

    def test_empty_dates_network_retry_attachments_and_mobile_header(self):
        from playwright.sync_api import expect,sync_playwright
        from .models import ConcernImage
        from .test_concerns import photo
        user,admin=fixture()
        admin.username='admin@example.com';admin.email='admin@example.com';admin.first_name='';admin.save()
        client=Client();client.force_login(admin)
        ticket=ConcernTicket.objects.create(user=user,subject='Retry loading this concern',message=('A long customer report.\n'*80),category='account')
        ConcernImage.objects.create(concern=ticket,image=photo())
        cancelled=ConcernTicket.objects.create(user=user,subject='Withdrawn report',message='No longer needed',status='cancelled')
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000})
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            context.route('https://fonts.googleapis.com/**',lambda route:route.abort())
            context.route('https://cdn.jsdelivr.net/**',lambda route:route.fulfill(status=200,content_type='application/javascript',body='window.Swal={mixin:()=>({fire:()=>{}})};'))
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(self.live_server_url+reverse('admin_concerns'))
            failures={'list':0,'details':0,'save':0}
            def intercept(route):
                url=route.request.url
                key='details' if '/details/' in url else 'save' if '/update/' in url else 'list' if 'q=retry' in url else None
                if key and not failures[key]:
                    failures[key]+=1;route.fulfill(status=503,content_type='application/json',body='{"message":"Temporary connection problem"}')
                else:route.continue_()
            page.route('**/staff/concerns/**',intercept)
            try:
                search=page.get_by_role('searchbox',name='Search concerns');search.fill('retry')
                expect(page.locator('#acListFeedback')).to_contain_text('Temporary connection problem')
                expect(page.locator('.ac-table tbody tr')).to_have_count(2)
                page.locator('#acListFeedback').get_by_role('button',name='Try again').click()
                expect(page.locator('.ac-table tbody tr')).to_have_count(1)
                page.get_by_role('button',name=f'View concern #CON-{ticket.pk}',exact=True).click()
                expect(page.locator('#acDetailFeedback')).to_contain_text('Temporary connection problem')
                page.locator('#acDetailFeedback').get_by_role('button',name='Try again').click()
                expect(page.locator('#concernModalTitle')).to_have_text(ticket.subject)
                page.get_by_role('button',name='View attachment 1',exact=True).click()
                expect(page.locator('#concernImageLightbox')).to_be_visible()
                page.get_by_role('button',name='Close attachment',exact=True).hover()
                self.assertNotEqual(page.get_by_role('button',name='Close attachment',exact=True).evaluate('(node)=>getComputedStyle(node).backgroundColor'),'rgba(0, 0, 0, 0)')
                page.keyboard.press('Escape');expect(page.locator('#concernImageLightbox')).not_to_be_visible()
                expect(page.locator('#concernDetailModal')).to_be_visible()
                page.locator('#acUpdateNotes').fill('Keep this draft after a failed request.')
                for theme in ('light','dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    page.locator('#acUpdateNotes').focus()
                    self.assertEqual(page.locator('#acUpdateNotes').evaluate('(node)=>getComputedStyle(node).outlineStyle'),'solid')
                    self.assertEqual(page.locator('#acUpdateNotes').evaluate('(node)=>getComputedStyle(node).outlineWidth'),'2px')
                page.get_by_role('button',name='Concern status: New',exact=True).click();page.get_by_role('option',name='In Progress',exact=True).click()
                page.locator('#acUpdateSubmit').click();expect(page.locator('#acUpdateFeedback')).to_contain_text('Temporary connection problem')
                toast=page.locator('.cfg-toast')
                expect(toast).to_have_attribute('data-kind','error')
                expect(toast).to_contain_text('Temporary connection problem')
                self.assertTrue(toast.evaluate("el=>el.matches(':popover-open')"))
                expect(page.locator('#acUpdateNotes')).to_have_value('Keep this draft after a failed request.')
                page.locator('#acUpdateSubmit').click();expect(page.locator('#acUpdateFeedback')).to_contain_text('Concern updated')
                expect(toast).to_have_attribute('data-kind','success')
                expect(toast).to_contain_text('Concern updated')
                expect(page.locator('#acUpdateSubmit')).to_be_enabled()
                page.get_by_role('button',name='Close concern details',exact=True).click()
                page.get_by_role('button',name='Dates',exact=True).click()
                page.locator('[name="start_date"]').fill('2026-10-26');page.locator('[name="end_date"]').fill('2026-10-25')
                page.get_by_role('button',name='Apply dates',exact=True).click();expect(page.locator('#acListFeedback')).to_contain_text('end date must')
                page.get_by_role('button',name='Clear dates',exact=True).click()
                page.get_by_role('button',name='Clear search',exact=True).click();expect(page.locator('.ac-table tbody tr')).to_have_count(2)
                for theme in ('light','dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    for field in (search,page.locator('[name="start_date"]')):
                        field.focus()
                        self.assertEqual(field.evaluate('(node)=>getComputedStyle(node).outlineStyle'),'solid')
                        self.assertEqual(field.evaluate('(node)=>getComputedStyle(node).outlineWidth'),'2px')
                        self.assertNotEqual(field.evaluate('(node)=>getComputedStyle(node).outlineColor'),'rgba(0, 0, 0, 0)')
                for node in (page.locator('.ac-dates'),page.locator('.ac-table th').first):
                    self.assertEqual(node.evaluate('(node)=>getComputedStyle(node).backgroundColor'),'rgb(32, 32, 32)')
                page.locator('.profile-avatar-btn').click()
                expect(page.locator('#adminAccountMenu')).to_be_visible()
                self.assertEqual(page.locator('#adminAccountMenu .user-info').inner_text().count('admin@example.com'),1)
                expect(page.locator('.admin-profile-trigger .admin-role')).to_have_text('Administrator')
                expect(page.locator('.admin-profile-trigger .profile-avatar-chevron')).to_have_count(0)
                self.assertGreater(page.locator('.admin-profile-trigger .dropdown-arrow').bounding_box()['x'],page.locator('.admin-profile-trigger .admin-avatar').bounding_box()['x'])
                page.screenshot(path=str(Path(settings.BASE_DIR)/'.booking-followup-check/admin-dropdown-corrected.png'),animations='disabled')
                page.evaluate("document.documentElement.dataset.theme='light'")
                page.screenshot(path=str(Path(settings.BASE_DIR)/'.booking-followup-check/admin-dropdown-corrected-light.png'),animations='disabled')
                page.keyboard.press('Escape')
                page.get_by_role('button',name='Filter concern status: All statuses',exact=True).click()
                page.keyboard.press('End');page.keyboard.press('Enter')
                expect(page.locator('.ac-table tbody tr')).to_have_count(1)
                page.get_by_role('button',name=f'View concern #CON-{cancelled.pk}',exact=True).click()
                expect(page.locator('#cancelledConcernNote')).to_be_visible();expect(page.locator('#acUpdateSubmit')).to_be_hidden()
                page.keyboard.press('Escape');expect(page.locator('#concernDetailModal')).not_to_be_visible()
                page.go_back();expect(page.locator('.ac-table tbody tr')).to_have_count(2)
                for width in (320,390,768):
                    page.set_viewport_size({'width':width,'height':850})
                    page.wait_for_function('document.querySelector(".sidebar").getBoundingClientRect().right<=0')
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                    page.locator('.profile-avatar-btn').click();expect(page.locator('#adminAccountMenu')).to_be_visible()
                    box=page.locator('#adminAccountMenu').bounding_box();self.assertGreaterEqual(box['x'],0);self.assertLessEqual(box['x']+box['width'],width)
                    page.keyboard.press('Escape')
                    page.locator('#notif-bell').click();expect(page.locator('#notif-dropdown .notif-empty h3')).to_have_text('No notifications yet')
                    box=page.locator('#notif-dropdown').bounding_box();self.assertGreaterEqual(box['x'],0);self.assertLessEqual(box['x']+box['width'],width)
                    page.keyboard.press('Escape')
                page.emulate_media(reduced_motion='reduce')
                page.locator('.theme-toggle-btn').click()
                self.assertFalse(page.evaluate('document.documentElement.classList.contains("theme-revealing")'))
                self.assertEqual(errors,[])
            except Exception:
                page.screenshot(path=str(Path(settings.BASE_DIR)/'.booking-followup-check/admin-concern-retry-failure.png'),full_page=True);raise
            finally:context.close();browser.close()
        self.assertEqual(Notification.objects.filter(concern=ticket).count(),1)
