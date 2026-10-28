"""Opt-in browser checks for the shared topbar and asynchronous global search."""
import os
from datetime import date, time
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from .models import AuditLog, Booking, Payment, User


@skipUnless(os.environ.get('RUN_ADMIN_NAVIGATION_BROWSER')=='1','Optional admin navigation browser verification')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminNavigationBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.admin=User.objects.create_user(username='topbar-admin',first_name='Alex',role='admin',email_verified=True)
        self.customer=User.objects.create_user(username='topbar-customer',first_name='Jamie',last_name='Rivera',email='jamie@example.com',role='customer',email_verified=True)
        self.booking=Booking.objects.create(user=self.customer,event_date=date(2099,10,30),event_time=time(10),event_type='Birthday',
            event_location='Test venue',package_type='Package 1-A',total_price=5000,status='confirmed')
        self.payment=Payment.objects.create(booking=self.booking,amount=2500,payment_method='gcash',payment_status='verified',transaction_ref='TOPBAR-PAY-ABC123')
        AuditLog.objects.create(user=self.admin,action='Admin navigation preview')
        self.client.force_login(self.admin);self.url=self.live_server_url+reverse('admin_audit_log')
        self.artifacts=Path(settings.BASE_DIR)/'.booking-followup-check'

    def browser(self,playwright,width=1440):
        browser=playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
        context=browser.new_context(viewport={'width':width,'height':1000})
        context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
        context.add_init_script("localStorage.setItem('balloorina-theme','light')")
        context.route('https://fonts.googleapis.com/**',lambda route:route.abort())
        context.route('https://cdnjs.cloudflare.com/**',lambda route:route.abort())
        context.route('https://cdn.jsdelivr.net/**',lambda route:route.fulfill(status=200,content_type='application/javascript',body='window.Swal={mixin:()=>({fire:()=>{}})};'))
        return browser,context

    def test_live_grouped_search_clear_keyboard_and_exact_detail_link(self):
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[];documents=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            try:
                page.goto(self.url)
                breadcrumb=page.get_by_role('navigation',name='Breadcrumb',exact=True)
                expect(breadcrumb.locator('[aria-current="page"]')).to_have_text('Audit log')
                search=page.get_by_role('combobox',name='Search admin records',exact=True)
                search.fill('Jamie Rivera')
                expect(page.locator('.admin-search-result')).to_have_count(3)
                expect(page.get_by_role('group',name='Bookings',exact=True)).to_be_visible()
                expect(page.get_by_role('group',name='Customers',exact=True)).to_be_visible()
                expect(page.get_by_role('group',name='Payments',exact=True)).to_be_visible()
                self.assertEqual(page.locator('.admin-search-result').first.get_attribute('href'),self.live_server_url+reverse('admin_booking_detail',args=[self.booking.pk]))
                search.press('ArrowDown');expect(page.locator('.admin-search-result').first).to_have_attribute('aria-selected','true')
                search.press('Escape');expect(page.locator('.admin-search-popup')).to_be_hidden()
                search.fill('TOPBAR-PAY-ABC123');expect(page.locator('.admin-search-result')).to_have_count(1)
                page.get_by_role('button',name='Clear global search',exact=True).click()
                expect(search).to_have_value('');expect(page.locator('.admin-search-result')).to_have_count(0)
                search.fill('no-such-person');expect(page.locator('.admin-search-status')).to_contain_text('No matching records')
                self.assertEqual(len(documents),1)
                search.fill('Jamie Rivera');expect(page.locator('.admin-search-result')).to_have_count(3)
                search.press('ArrowDown');search.press('ArrowDown');search.press('Enter')
                expect(page).to_have_url(self.live_server_url+reverse('admin_user_detail',args=[self.customer.pk]))
                page.get_by_role('button',name='Close account details',exact=True).click()
                breadcrumb=page.get_by_role('navigation',name='Breadcrumb',exact=True)
                expect(breadcrumb.locator('[aria-current="page"]')).to_have_text(f'User #{self.customer.pk}')
                expect(breadcrumb.get_by_role('link',name='Users',exact=True)).to_have_attribute('href',reverse('admin_user_list'))
                self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_responsive_themes_search_overlay_and_website_new_tab(self):
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.url)
                website=page.locator('.admin-website-link')
                expect(website).to_have_attribute('target','_blank');expect(website).to_have_attribute('rel','noopener noreferrer')
                with page.expect_popup() as popup:website.click()
                site=popup.value;site.wait_for_url(self.live_server_url+reverse('home'));site.close()
                for theme in ('light','dark'):
                    page.evaluate('(value)=>document.documentElement.dataset.theme=value',theme)
                    for width in (1440,1280,1024,768,390,320):
                        page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(150)
                        self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'),f'Page overflow {theme}/{width}')
                        expect(page.get_by_role('button',name='Account menu',exact=True)).to_be_visible()
                        expect(page.locator('.theme-toggle-btn')).to_be_visible()
                        expect(page.locator('#notif-bell')).to_be_visible()
                        if width<1280:page.get_by_role('button',name='Open global search',exact=True).click()
                        search=page.get_by_role('combobox',name='Search admin records',exact=True)
                        search.fill('Jamie');expect(page.locator('.admin-search-result')).to_have_count(3)
                        box=page.locator('.admin-search-popup').bounding_box();self.assertGreaterEqual(box['x'],0);self.assertLessEqual(box['x']+box['width'],width)
                        self.assertEqual(search.evaluate('(node)=>getComputedStyle(node).outlineStyle'),'solid')
                        page.screenshot(path=str(self.artifacts/f'admin-topbar-search-{theme}-{width}.png'),animations='disabled')
                        search.press('Escape');expect(page.locator('.admin-search-popup')).to_be_hidden()
                        page.screenshot(path=str(self.artifacts/f'admin-topbar-{theme}-{width}.png'),animations='disabled')
                page.get_by_role('button',name='Account menu',exact=True).click()
                expect(page.locator('#adminAccountMenu').get_by_role('link',name='View website',exact=True)).to_be_visible()
                self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_stale_responses_error_retry_menu_exclusion_and_escaping(self):
        self.customer.first_name='<img src=x onerror=alert(1)>';self.customer.save(update_fields=['first_name'])
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[];documents=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            try:
                page.goto(self.url);search=page.get_by_role('combobox',name='Search admin records',exact=True)
                page.evaluate("""() => {const original=window.fetch;window.fetch=(...args)=>original(...args).then(async response=>{if(String(args[0]).includes('q=missing'))await new Promise(resolve=>setTimeout(resolve,500));return response;});}""")
                search.fill('missing');page.wait_for_timeout(350);search.fill('jamie@example.com')
                expect(page.locator('.admin-search-result')).to_have_count(3);page.wait_for_timeout(650)
                expect(page.locator('.admin-search-result')).to_have_count(3)
                expect(page.locator('.admin-search-result').nth(1)).to_contain_text('<img src=x onerror=alert(1)>')
                expect(page.locator('.admin-search-popup img')).to_have_count(0)
                page.route('**/api/staff/search/**',lambda route:route.abort())
                search.fill('connection-error');expect(page.get_by_role('button',name='Try again',exact=True)).to_be_visible()
                page.unroute('**/api/staff/search/**')
                page.get_by_role('button',name='Try again',exact=True).click();expect(page.locator('.admin-search-status')).to_contain_text('No matching records')
                search.fill('jamie@example.com');expect(page.locator('.admin-search-result')).to_have_count(3)
                page.get_by_role('button',name='Account menu',exact=True).click();expect(page.locator('.admin-search-popup')).to_be_hidden()
                search.focus();expect(page.locator('#adminAccountMenu')).to_be_hidden()
                page.locator('#notif-bell').click();expect(page.locator('.admin-search-popup')).to_be_hidden()
                self.assertEqual(len(documents),1);self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_dropdown_website_icon_and_public_navbar_with_admin_session(self):
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[]
            context.on('page',lambda opened:opened.on('pageerror',lambda error:errors.append(str(error))))
            try:
                for theme in ('light','dark'):
                    context.add_init_script(f"localStorage.setItem('balloorina-theme','{theme}')")
                    for width in (1440,390,320):
                        page.set_viewport_size({'width':width,'height':1000})
                        page.goto(self.url)
                        page.get_by_role('button',name='Account menu',exact=True).click()
                        website=page.locator('#adminAccountMenu').get_by_role('link',name='View website',exact=True)
                        expect(website).to_be_visible()
                        icon=website.locator('svg')
                        self.assertEqual(icon.evaluate('(node)=>getComputedStyle(node).fill'),'none')
                        self.assertEqual(icon.evaluate('(node)=>getComputedStyle(node).stroke'),icon.evaluate('(node)=>getComputedStyle(node).color'))
                        self.assertEqual(icon.evaluate('(node)=>getComputedStyle(node).strokeWidth'),'1.5px')
                        with page.expect_popup() as popup:website.click()
                        site=popup.value
                        try:
                            site.set_viewport_size({'width':width,'height':1000})
                            site.wait_for_url(self.live_server_url+reverse('home'))
                            navbar=site.locator('nav.navbar')
                            expect(navbar.locator('.nav-logo')).to_be_visible()
                            expect(navbar.get_by_role('link',name='Dashboard',exact=True)).to_be_visible()
                            expect(navbar.get_by_role('link',name='Login',exact=True)).to_have_count(0)
                            self.assertFalse(site.evaluate('document.documentElement.scrollWidth>innerWidth'),f'Public page overflow {theme}/{width}')
                            if width<969:
                                navbar.get_by_role('button',name='Open menu',exact=True).click()
                            expect(navbar.get_by_role('link',name='Home',exact=True)).to_be_visible()
                            expect(navbar.get_by_role('link',name='Gallery',exact=True)).to_be_visible()
                            site.screenshot(path=str(self.artifacts/f'admin-view-website-{theme}-{width}.png'),animations='disabled')
                            if width<969:
                                navbar.get_by_role('button',name='Open menu',exact=True).click()
                            navbar.get_by_role('link',name='Dashboard',exact=True).click()
                            expect(site).to_have_url(self.live_server_url+reverse('dashboard'))
                            expect(site.locator('.admin-topbar')).to_be_visible()
                        finally:site.close()
                self.assertEqual(errors,[])
            finally:context.close();browser.close()
