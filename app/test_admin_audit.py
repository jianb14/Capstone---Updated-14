"""Staff audit history stays bounded, private and usable without full-page reloads."""
import os
from datetime import datetime, timezone as datetime_timezone
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, User


def audit_users():
    admin=User.objects.create_user(username='audit-admin@example.com',email='audit-admin@example.com',role='admin',email_verified=True)
    customer=User.objects.create_user(username='audit-customer',first_name='Jamie',last_name='Rivera',email='audit-customer@example.com',role='customer',email_verified=True)
    staff=User.objects.create_user(username='audit-staff',role='staff',email_verified=True)
    return admin,customer,staff


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminAuditTests(TestCase):
    def setUp(self):
        self.admin,self.customer,self.staff=audit_users();self.client.force_login(self.admin)
        self.url=reverse('admin_audit_log')

    def test_only_admins_can_read_history_and_post_cannot_mutate_it(self):
        log=AuditLog.objects.create(user=self.admin,action='Original activity')
        self.assertEqual(Client().get(self.url).status_code,302)
        for user in (self.customer,self.staff):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code,403)
            self.assertEqual(self.client.get(self.url,HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code,403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.url,{'action':'Changed'}).status_code,405)
        self.assertEqual(AuditLog.objects.get(pk=log.pk).action,'Original activity')

    def test_default_eight_show_four_and_stable_tied_timestamp_pages(self):
        items=[AuditLog.objects.create(user=self.customer,action=f'Activity {i}') for i in range(21)]
        AuditLog.objects.update(created_at=timezone.now())
        first=self.client.get(self.url);second=self.client.get(self.url,{'page':2})
        expected=[item.pk for item in reversed(items)]
        self.assertEqual([log.pk for log in first.context['logs']],expected[:8])
        self.assertEqual([log.pk for log in second.context['logs']],expected[8:16])
        for query,size in (({'per_page':'4'},4),({'per_page':'500'},8),({'per_page':'invalid'},8)):
            response=self.client.get(self.url,query);self.assertEqual(len(response.context['logs']),size)
        self.assertEqual(self.client.get(self.url,{'page':'invalid'}).context['logs'].number,1)
        self.assertEqual(self.client.get(self.url,{'page':'99999'}).context['logs'].number,3)

    def test_search_full_name_email_action_and_exact_log_id(self):
        target=AuditLog.objects.create(user=self.customer,action='Updated a birthday booking')
        AuditLog.objects.create(user=self.admin,action='Unrelated activity')
        for search in ('Jamie','Rivera','audit-customer@example.com','birthday',f'#LOG-{target.pk}'):
            response=self.client.get(self.url,{'search':search})
            self.assertEqual(list(response.context['logs']),[target])
        response=self.client.get(self.url,{'search':'not present'})
        self.assertContains(response,'No matching activities');self.assertNotContains(response,'<table')
        self.assertNotContains(response,'data-list-footer')

    def test_supported_roles_and_system_filter_preserve_legacy_history(self):
        rows={role:AuditLog.objects.create(user=user,action=f'{role} activity') for role,user in
              [('admin',self.admin),('customer',self.customer),('staff',self.staff),('system',None)]}
        for role,item in rows.items():
            if role == 'staff':
                continue
            response=self.client.get(self.url,{'role':role})
            self.assertEqual(list(response.context['logs']),[item])
        for role in ('staff','not-a-role'):
            response=self.client.get(self.url,{'role':role})
            self.assertEqual(response.context['logs'].paginator.count,4)
            self.assertEqual(response.context['role_filter'],'')
            self.assertNotContains(response,'<option value="staff"')
            self.assertContains(response,'Unknown')

    def test_local_date_filter_includes_midnight_and_validates_bad_ranges(self):
        old=AuditLog.objects.create(user=self.customer,action='Before local midnight')
        today=AuditLog.objects.create(user=self.customer,action='After local midnight')
        AuditLog.objects.filter(pk=old.pk).update(created_at=datetime(2026,10,25,15,59,tzinfo=datetime_timezone.utc))
        AuditLog.objects.filter(pk=today.pk).update(created_at=datetime(2026,10,25,16,1,tzinfo=datetime_timezone.utc))
        with timezone.override('Asia/Manila'):
            response=self.client.get(self.url,{'date_from':'2026-10-26','date_to':'2026-10-26'})
            self.assertEqual(list(response.context['logs']),[today])
        for query in ({'date_from':'bad','date_to':'2026-10-26'}, {'date_from':'2026-10-26'},
                      {'date_from':'2026-10-27','date_to':'2026-10-26'}, {'date_from':'2026-13-90','date_to':'2026-10-26'}):
            response=self.client.get(self.url,query,HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code,400);self.assertTrue(response.json()['error'])
            self.assertEqual(self.client.get(self.url,query).status_code,200)

    def test_combined_filters_and_private_fragment_response(self):
        wanted=AuditLog.objects.create(user=self.customer,action='Unique account activity')
        AuditLog.objects.create(user=self.admin,action='Unique admin activity')
        stamp=timezone.localdate().isoformat()
        response=self.client.get(self.url,{'search':'Unique','role':'customer','date_from':stamp,'date_to':stamp,'per_page':'4'},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual(data['page'],1);self.assertEqual(data['per_page'],4)
        self.assertIn(f'data-audit-row="{wanted.pk}"',data['html'])
        self.assertNotIn('<html',data['html']);self.assertIn('private, no-store',response['Cache-Control'])

    def test_full_activity_is_escaped_and_removed_accounts_render_without_links(self):
        action='<script>alert("unsafe")</script>\n'+'Long details '*100
        item=AuditLog.objects.create(user=None,action=action)
        response=self.client.get(self.url)
        self.assertContains(response,f'aria-controls="audit-detail-{item.pk}"')
        self.assertContains(response,'&lt;script&gt;');self.assertNotContains(response,'<script>alert(')
        self.assertContains(response,'System / removed account');self.assertNotContains(response,'audit-account-link')

    def test_summary_does_not_repeat_email_and_full_details_show_existing_account(self):
        item=AuditLog.objects.create(user=self.admin,action='Logged in')
        response=self.client.get(self.url)
        self.assertContains(response,f'href="{reverse("admin_user_detail",args=[self.admin.pk])}"')
        self.assertContains(response,'Philippine time');self.assertContains(response,f'#LOG-{item.pk}')
        self.assertContains(response,'audit-admin@example.com')
        customer_log=AuditLog.objects.create(user=self.customer,action='Updated profile')
        response=self.client.get(self.url,{'search':f'#LOG-{customer_log.pk}'})
        self.assertContains(response,f'#USER-{self.customer.pk}')
        self.assertContains(response,'audit-customer@example.com')


@skipUnless(os.environ.get('RUN_ADMIN_AUDIT_BROWSER')=='1','Optional audit browser verification')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminAuditBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.admin,self.customer,self.staff=audit_users()
        self.artifacts=Path(settings.BASE_DIR)/'.booking-followup-check';self.artifacts.mkdir(exist_ok=True)
        for i in range(39):AuditLog.objects.create(user=None if i==0 else self.customer if i%2 else self.admin,action=f'Recorded activity {i}.')
        self.action='Unique detailed update for a temporary issue.\n'+'LongAuditDetail'*180
        self.latest=AuditLog.objects.create(user=self.admin,action=self.action)
        self.client.force_login(self.admin)

    def browser_context(self,p):
        browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1000})
        context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
        context.add_init_script("localStorage.setItem('balloorina-theme','light')")
        context.route('https://fonts.googleapis.com/**',lambda route:route.abort())
        context.route('https://cdnjs.cloudflare.com/**',lambda route:route.abort())
        context.route('https://cdn.jsdelivr.net/**',lambda route:route.fulfill(status=200,content_type='application/javascript',body='window.Swal={mixin:()=>({fire:()=>{}})};'))
        return browser,context

    def test_async_filters_pagination_details_and_responsive_themes(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser_context(p);page=context.new_page();documents=[];errors=[]
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.live_server_url+reverse('admin_audit_log'))
                expect(page.locator('[data-audit-row]')).to_have_count(8)
                expect(page.locator('.account-page-ellipsis')).to_be_visible()
                first=page.locator('[data-audit-row]').first;first.locator('td').first.click()
                detail=page.locator(f'#audit-detail-{self.latest.pk}')
                expect(detail).to_be_visible();expect(detail.locator('.audit-full-action')).to_have_text(self.action)
                expect(detail.locator('.audit-full-action')).to_have_attribute('role','region')
                page.get_by_role('button',name=f'Hide details for activity #LOG-{self.latest.pk}').press('Enter')
                expect(detail).to_be_hidden()
                toggle=page.get_by_role('button',name=f'Show details for activity #LOG-{self.latest.pk}')
                toggle.press('Space');expect(detail).to_be_visible();page.keyboard.press('Escape');expect(detail).to_be_hidden()
                expect(toggle).to_be_focused()
                page.get_by_role('link',name='Next page',exact=True).click()
                expect(page.locator('.account-pagination [aria-current="page"]')).to_have_text('2')
                page.get_by_role('button',name='Rows per page: 8',exact=True).click();page.get_by_role('option',name='4',exact=True).click()
                expect(page.locator('[data-audit-row]')).to_have_count(4)
                expect(page.locator('.account-table-summary')).to_contain_text('1–4')
                search=page.get_by_role('searchbox',name='Search audit logs');search.fill('Unique detailed update')
                expect(page.locator('[data-audit-row]')).to_have_count(1)
                page.get_by_role('button',name='Clear search',exact=True).click();expect(page.locator('[data-audit-row]')).to_have_count(4)
                search.fill('no matches for this activity');expect(page.locator('.ac-empty h3')).to_have_text('No matching activities')
                expect(page.locator('.audit-table')).to_have_count(0);expect(page.locator('.account-table-footer')).to_have_count(0)
                page.get_by_role('button',name='Clear filters',exact=True).click();expect(page.locator('[data-audit-row]')).to_have_count(4)
                page.get_by_role('button',name='Filter account role: All roles',exact=True).click();page.keyboard.press('End');page.keyboard.press('Enter')
                expect(page.locator('[data-audit-row]')).to_have_count(1);page.locator('[data-audit-toggle]').click()
                expect(page.locator('.audit-log-detail:not([hidden])')).to_contain_text('System')
                expect(page.locator('.audit-account-link')).to_have_count(0)
                page.get_by_role('button',name='Filter account role: System / removed account',exact=True).click();page.keyboard.press('Home');page.keyboard.press('Enter')
                expect(page.locator('[data-audit-row]')).to_have_count(4)
                page.get_by_role('button',name='Dates',exact=True).click()
                page.locator('[name="date_from"]').fill('2026-10-27');page.locator('[name="date_to"]').fill('2026-10-26')
                page.get_by_role('button',name='Apply dates',exact=True).click();expect(page.locator('#auditListFeedback')).to_contain_text('end date must')
                page.get_by_role('button',name='Clear dates',exact=True).click()
                expect(page.locator('[data-audit-row]')).to_have_count(4)
                page.locator('[data-audit-row]').first.click();expect(detail).to_be_visible()
                for theme,width,height in [('light',1440,1000),('dark',390,844),('light',320,850),('dark',768,1000)]:
                    page.set_viewport_size({'width':width,'height':height});page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    if width<1025:page.wait_for_function('document.querySelector(".sidebar").getBoundingClientRect().right<=0')
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                    panel=detail.locator('.audit-detail-panel');box=panel.bounding_box();self.assertGreaterEqual(box['x'],0);self.assertLessEqual(box['x']+box['width'],width)
                    expect(detail.locator('td')).to_have_css('text-align','left')
                    expect(panel).to_have_css('border-top-width','0px');expect(panel).to_have_css('background-color','rgba(0, 0, 0, 0)')
                    if width<800:
                        page.locator('.audit-table-scroll').evaluate('(node)=>node.scrollLeft=node.scrollWidth')
                        box=panel.bounding_box();self.assertGreaterEqual(box['x'],0);self.assertLessEqual(box['x']+box['width'],width)
                        page.locator('.audit-table-scroll').evaluate('(node)=>node.scrollLeft=0')
                    page.screenshot(path=str(self.artifacts/f'audit-details-{theme}-{width}.png'),full_page=True,animations='disabled')
                    search.focus();self.assertEqual(search.evaluate('(node)=>getComputedStyle(node).outlineStyle'),'solid')
                    page.get_by_role('button',name='Filter account role: All roles',exact=True).click()
                    menu=page.get_by_role('listbox',name='Filter account role',exact=True)
                    expect(menu).to_be_visible();expect(menu.get_by_role('option')).to_have_count(4)
                    self.assertFalse(menu.evaluate('(node)=>node.scrollWidth>node.clientWidth || node.scrollHeight>node.clientHeight+1'))
                    menu_box=menu.bounding_box();self.assertGreaterEqual(menu_box['x'],12);self.assertLessEqual(menu_box['x']+menu_box['width'],width-12)
                    expect(menu.get_by_role('option',name='System / removed account',exact=True)).to_be_in_viewport()
                    page.screenshot(path=str(self.artifacts/f'audit-role-menu-{theme}-{width}.png'),animations='disabled')
                    page.keyboard.press('Escape');expect(menu).to_be_hidden()
                self.assertEqual(len(documents),1);self.assertEqual(errors,[])
            except Exception:
                page.screenshot(path=str(self.artifacts/'audit-browser-failure.png'),full_page=True);raise
            finally:context.close();browser.close()

    def test_failed_request_retry_back_forward_and_keyboard_dropdown(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser_context(p);page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.live_server_url+reverse('admin_audit_log'))
                failed=[]
                def intercept(route):
                    if 'search=temporary' in route.request.url and not failed:
                        failed.append(True);route.fulfill(status=503,content_type='application/json',body='{"message":"Temporary connection problem"}')
                    else:route.continue_()
                page.route('**/staff/audit-log/**',intercept)
                search=page.get_by_role('searchbox',name='Search audit logs');search.fill('temporary')
                expect(page.locator('#auditListFeedback')).to_contain_text('Temporary connection problem')
                expect(page.locator('[data-audit-row]')).to_have_count(8)
                expect(search).to_have_value('temporary')
                page.locator('#auditListFeedback').get_by_role('button',name='Try again').click()
                expect(page.locator('[data-audit-row]')).to_have_count(1)
                page.get_by_role('button',name='Clear search',exact=True).click();expect(page.locator('[data-audit-row]')).to_have_count(8)
                page.go_back();expect(search).to_have_value('temporary');expect(page.locator('[data-audit-row]')).to_have_count(1)
                page.go_forward();expect(search).to_have_value('');expect(page.locator('[data-audit-row]')).to_have_count(8)
                button=page.get_by_role('button',name='Filter account role: All roles',exact=True)
                button.focus();page.keyboard.press('ArrowDown');page.keyboard.press('ArrowDown');page.keyboard.press('Enter')
                expect(page.get_by_role('button',name='Filter account role: Admin',exact=True)).to_be_visible()
                expect(page.locator('[data-audit-row]')).to_have_count(8)
                self.assertEqual(errors,[])
            except Exception:
                page.screenshot(path=str(self.artifacts/'audit-retry-failure.png'),full_page=True);raise
            finally:context.close();browser.close()
