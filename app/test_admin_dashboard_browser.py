"""Browser verification of async dashboard filters, charts, themes and recovery."""
import os
from datetime import time,timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Booking,BookingChangeRequest,ConcernTicket,Payment,User


@skipUnless(os.environ.get('RUN_ADMIN_DASHBOARD_BROWSER')=='1','Optional dashboard browser verification')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminDashboardBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        admin=User.objects.create_user(username='dashboard-browser-admin',role='admin',email_verified=True)
        customer=User.objects.create_user(username='dashboard-browser-customer',first_name='Jamie',last_name='Rivera',role='customer',email_verified=True)
        self.today=timezone.localdate()
        rows=[(0,'completed','Birthday','1200.25'),(0,'pending','Birthday','1000'),(0,'cancelled','Birthday','2000'),
            (0,'completed','Wedding','5000'),(-1,'confirmed','Birthday','2500'),(1,'confirmed','Wedding','4500'),(1,'cancel_requested','Birthday','1500')]
        bookings=[]
        for offset,status,event,value in rows:
            bookings.append(Booking.objects.create(user=customer,event_date=self.today+timedelta(days=offset),event_time=time(9),
                event_type=event,event_location='Venue',package_type='Package 1-A',total_price=value,status=status))
        for index,amount in enumerate(('300.15','200.10')):
            Payment.objects.create(booking=bookings[0],amount=amount,payment_status='verified',payment_method='gcash',transaction_ref=f'DASH-BROWSER-{index}')
        Payment.objects.create(booking=bookings[1],amount=200,payment_status='pending',payment_method='gcash',transaction_ref='DASH-BROWSER-PENDING')
        BookingChangeRequest.objects.create(booking=bookings[4],status='pending_review',reason='Update location',original_total=2500,quoted_total=2500)
        ConcernTicket.objects.create(user=customer,category='bug',subject='A question',message='Please help')
        self.client.force_login(admin);self.url=self.live_server_url+reverse('dashboard');self.artifacts=Path(settings.BASE_DIR)/'.booking-followup-check'

    def browser(self,playwright):
        browser=playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1000})
        context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
        context.add_init_script("localStorage.setItem('balloorina-theme','light')")
        context.route('https://fonts.googleapis.com/**',lambda route:route.abort())
        context.route('https://cdnjs.cloudflare.com/**',lambda route:route.abort())
        context.route('https://cdn.jsdelivr.net/**',lambda route:route.fulfill(status=200,content_type='application/javascript',body='window.Swal={mixin:()=>({fire:()=>{}})};'))
        return browser,context

    def test_filter_parity_history_chart_animation_and_refresh_keep_applied_dates(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();documents=[];errors=[]
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.url+'?filter_preset=today')
                total=page.locator('[data-kpi="bookings"]>strong');expect(total).to_have_text('4')
                page.wait_for_function('Object.keys(Chart.instances).length===2')
                original=page.evaluate('Chart.getChart(document.querySelector("[data-chart=trend]")).id')
                queue=page.locator('[data-queue="approvals"] .db-queue-count');expect(queue).to_have_text('1')
                page.get_by_role('button',name='Event type: All event types',exact=True).click()
                page.get_by_role('option',name='Wedding',exact=True).click()
                expect(total).to_have_text('1');expect(queue).to_have_text('1')
                self.assertEqual(page.evaluate('Chart.getChart(document.querySelector("[data-chart=trend]")).id'),original)
                self.assertEqual(page.evaluate('Chart.getChart(document.querySelector("[data-chart=trend]")).options.animation.duration'),620)
                self.assertIn('event_type=Wedding',page.locator('#dashboardAnalytics').get_attribute('href'))
                page.go_back();expect(total).to_have_text('4')
                page.get_by_role('button',name='Collections',exact=True).click()
                self.assertEqual(page.evaluate('Chart.getChart(document.querySelector("[data-chart=trend]")).data.datasets[0].data'),[500.25])
                # Editing dates alone must never change the report, its link or Refresh.
                applied_link=page.locator('#dashboardAnalytics').get_attribute('href')
                page.get_by_label('From date',exact=True).fill('2040-01-01');page.get_by_label('To date',exact=True).fill('2040-01-02')
                self.assertEqual(page.locator('#dashboardAnalytics').get_attribute('href'),applied_link)
                page.get_by_role('button',name='Refresh',exact=True).click()
                expect(page.locator('#dashboardLoadStatus')).to_contain_text('Updated')
                expect(total).to_have_text('4')
                self.assertEqual(page.locator('#dashboardAnalytics').get_attribute('href'),applied_link)
                page.get_by_label('From date',exact=True).fill('2040-01-02');page.get_by_label('To date',exact=True).fill('2040-01-01')
                page.get_by_role('button',name='Apply dates',exact=True).click()
                expect(page.locator('#dashboardError')).to_contain_text('cannot be after');expect(total).to_have_text('4')
                page.get_by_role('button',name='Reset',exact=True).click()
                expect(total).to_have_text('5');expect(page.locator('[data-period="7days"]')).to_have_attribute('aria-pressed','true')
                page.get_by_role('button',name='All time',exact=True).click();expect(total).to_have_text('7')
                expect(page.locator('.ar-scope')).to_contain_text('comparison is disabled')
                self.assertEqual(len(documents),1);self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_light_dark_mobile_focus_reduced_motion_and_no_overflow(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.url+'?filter_preset=today');page.wait_for_function('Object.keys(Chart.instances).length===2')
                for theme in ('light','dark'):
                    page.evaluate('(value)=>document.documentElement.dataset.theme=value',theme)
                    active=page.locator('[data-trend][aria-pressed="true"]')
                    self.assertEqual(active.evaluate('(node)=>getComputedStyle(node).backgroundColor'),'rgb(255, 255, 255)' if theme=='light' else 'rgb(22, 22, 22)')
                    for width in (1920,1440,768,390,320):
                        page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(250)
                        self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'),f'Overflow {theme}/{width}')
                        if width>=1440:self.assertEqual(page.locator('.ar-kpis').evaluate('(node)=>getComputedStyle(node).gridTemplateColumns.split(" ").length'),3)
                        for canvas in page.locator('[data-chart]').all():self.assertGreater(canvas.bounding_box()['width'],100)
                        page.screenshot(path=str(self.artifacts/f'admin-dashboard-{theme}-{width}.png'),full_page=True,animations='disabled')
                    page.get_by_label('From date',exact=True).focus()
                    self.assertEqual(page.get_by_label('From date',exact=True).evaluate('(node)=>getComputedStyle(node).outlineStyle'),'solid')
                    colors=page.locator('.ac-kpi-head').evaluate_all('(nodes)=>nodes.map(node=>getComputedStyle(node).color)')
                    self.assertGreater(len(set(colors)),2)
                page.emulate_media(reduced_motion='reduce')
                page.wait_for_function('Chart.getChart(document.querySelector("[data-chart=trend]")).options.animation.duration===0')
                self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_greeting_clock_rollover_shortcuts_and_async_refresh(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();documents=[];errors=[]
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.clock.install()
                page.goto(self.url+'?filter_preset=today')
                expect(page.locator('[data-greeting]')).to_be_visible()
                self.assertTrue(page.evaluate('document.querySelector("#dashboardOperations").getBoundingClientRect().bottom<=document.querySelector("#dashboardFilters").getBoundingClientRect().top'))
                page.get_by_role('link',name='Needs attention',exact=True).click()
                expect(page.locator('#dashboardAttentionTitle')).to_be_focused()
                page.evaluate('window.scrollTo(0,0)')
                page.get_by_role('link',name='Upcoming events',exact=True).click()
                expect(page.locator('#dashboardUpcomingTitle')).to_be_focused()
                page.evaluate('window.scrollTo(0,0)')
                page.get_by_role('link',name='View performance',exact=True).click()
                expect(page.locator('#dashboardFilters')).to_be_focused()
                # Fake browser time to verify rollover without waiting for real noon.
                page.evaluate("document.querySelector('[data-server-clock]').dataset.serverClock='2026-10-26T11:59:59+08:00';document.dispatchEvent(new Event('visibilitychange'))")
                expect(page.locator('[data-greeting]')).to_have_text('Good morning')
                page.clock.fast_forward(2100)
                expect(page.locator('[data-greeting]')).to_have_text('Good afternoon')
                page.evaluate("document.querySelector('[data-server-clock]').dataset.serverClock='2026-10-26T23:59:59+08:00';document.dispatchEvent(new Event('visibilitychange'))")
                expect(page.locator('[data-greeting]')).to_have_text('Good evening')
                page.clock.fast_forward(2100)
                expect(page.locator('[data-dashboard-date]')).to_contain_text('October 27, 2026')
                page.get_by_role('button',name='Refresh',exact=True).click()
                expect(page.locator('#dashboardLoadStatus')).to_contain_text('Updated')
                page.get_by_role('button',name='Today',exact=True).click()
                expect(page.locator('[data-kpi="bookings"]>strong')).to_have_text('4')
                self.assertEqual(len(documents),1);self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_empty_results_failure_recovery_stale_response_and_date_basis(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();documents=[];errors=[]
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.url+'?filter_preset=today');total=page.locator('[data-kpi="bookings"]>strong')
                expect(total).to_have_text('4')
                page.get_by_label('From date',exact=True).fill('2040-01-01');page.get_by_label('To date',exact=True).fill('2040-01-02')
                page.get_by_role('button',name='Apply dates',exact=True).click();expect(total).to_have_text('0')
                expect(page.locator('.ar-chart-empty')).to_have_count(2)
                self.assertEqual(page.evaluate('Object.keys(Chart.instances).length'),0)
                expect(page.locator('[data-queue="approvals"] .db-queue-count')).to_have_text('1')
                page.get_by_role('button',name='Today',exact=True).click();expect(total).to_have_text('4')
                page.wait_for_function('Object.keys(Chart.instances).length===2')
                # Rapid changes to different controls must keep both choices.
                page.evaluate("""() => {const f=document.querySelector('#dashboardFilters');f.elements.date_basis.value='created';f.elements.date_basis.dispatchEvent(new Event('change',{bubbles:true}));f.elements.event_type.value='Wedding';f.elements.event_type.dispatchEvent(new Event('change',{bubbles:true}));}""")
                expect(total).to_have_text('2')
                expect(page.get_by_role('button',name='Date basis: Booking submission date',exact=True)).to_be_visible()
                expect(page.get_by_role('button',name='Event type: Wedding',exact=True)).to_be_visible()
                page.get_by_role('button',name='Event type: Wedding',exact=True).click()
                page.get_by_role('option',name='All event types',exact=True).click();expect(total).to_have_text('7')
                # A late response to an old request must not replace the newest filter.
                page.evaluate("""() => {const original=window.fetch;window.fetch=(...args)=>original(...args).then(async response=>{if(String(args[0]).includes('filter_preset=7days'))await new Promise(resolve=>setTimeout(resolve,500));return response;});document.querySelector('[data-period="7days"]').click();setTimeout(()=>document.querySelector('[data-period="all"]').click(),50);}""")
                expect(page.locator('[data-period="all"]')).to_have_attribute('aria-pressed','true')
                page.wait_for_timeout(600);expect(page.locator('[data-period="all"]')).to_have_attribute('aria-pressed','true')
                page.route('**/dashboard/?**',lambda route:route.abort())
                page.get_by_role('button',name='Today',exact=True).click();expect(page.locator('#dashboardError')).not_to_be_empty()
                expect(total).to_have_text('7');expect(page.locator('[data-period="all"]')).to_have_attribute('aria-pressed','true')
                page.unroute('**/dashboard/?**')
                page.get_by_role('button',name='Refresh',exact=True).click()
                expect(page.locator('#dashboardError')).to_be_hidden();expect(total).to_have_text('7')
                self.assertEqual(len(documents),1);self.assertEqual(errors,[])
            finally:context.close();browser.close()
