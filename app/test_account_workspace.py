import os
import re
from datetime import date
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Booking, User


class AccountWorkspaceTests(TestCase):
    def test_every_account_page_has_shared_navigation_and_an_active_item(self):
        user = User.objects.create_user(username='account-layout', role='customer', email_verified=True)
        self.client.force_login(user)
        for name in ('my_profile','customer_profile','my_payments','my_reviews','report_concern'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code,200)
                self.assertContains(response,f'data-account-page="{name}"')
                self.assertContains(response,f'data-account-key="{name}" aria-current="page"')
                self.assertContains(response,f'data-account-menu-key="{name}" aria-current="page"')
                self.assertContains(response,'id="accountSidebarLinks"')
                self.assertNotContains(response,'account-mobile-toggle')
                self.assertContains(response,'account_navigation.js')
        self.assertNotContains(self.client.get(reverse('home')),'data-account-shell')


@skipUnless(os.environ.get('RUN_ACCOUNT_WORKSPACE_BROWSER') == '1','Optional browser integration')
@override_settings(SESSION_COOKIE_SECURE=False,CSRF_COOKIE_SECURE=False,REQUEST_RATE_LIMITING_ENABLED=False)
class AccountWorkspaceBrowserTests(StaticLiveServerTestCase):
    def test_all_routes_back_forward_repeated_mounts_modals_mobile_and_failure(self):
        from playwright.sync_api import expect, sync_playwright
        user = User.objects.create_user(username='workspace-browser',first_name='Jamie',last_name='Rivera',
            email='jamie@example.com',phone_number='09170000000',role='customer',email_verified=True)
        booking = Booking.objects.create(user=user,event_date=date(2026,1,1),event_location='Manila',
            status='completed',total_price=4799,package_type='Package 1-A',event_lat='14.414000',event_lng='120.982000')
        self.client.force_login(user)
        session = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        artifacts = Path(settings.BASE_DIR)/'.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context = browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':session,'url':self.live_server_url}])
            context.route('https://fonts.googleapis.com/**',lambda route:route.abort())
            leaflet = artifacts/'leaflet.js'
            def map_asset(route):
                resource = artifacts/route.request.url.rsplit('/',1)[-1]
                if resource.exists(): route.fulfill(path=str(resource))
                else: route.abort()
            context.route('https://unpkg.com/**',map_asset)
            context.route('https://*.tile.openstreetmap.org/**',lambda route:route.abort())
            sweetalert=artifacts/'sweetalert2.all.min.js'
            if sweetalert.exists(): context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11',lambda route:route.fulfill(content_type='application/javascript',body=sweetalert.read_text(encoding='utf-8')))
            page = context.new_page()
            errors, documents = [], []
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            def settled(key):
                expect(page.locator('#accountContent')).to_have_attribute('data-account-page',key)
                page.wait_for_function('!window.AccountNavigation.navigating')
                expect(page.locator(f'[data-account-key="{key}"]')).to_have_attribute('aria-current','page')
            def visit(key):
                if page.viewport_size['width']<=968:
                    page.get_by_role('button',name='Profile menu',exact=True).click()
                    page.locator(f'[data-account-menu-key="{key}"]').click()
                else: page.locator(f'[data-account-key="{key}"]').click()
                settled(key)
                expect(page.locator(f'[data-account-menu-key="{key}"]')).to_have_attribute('aria-current','page')
            try:
                page.goto(self.live_server_url+reverse('my_profile'),wait_until='domcontentloaded')
                page.evaluate('window.workspaceSentinel="persistent"; window.originalAccountSidebar=document.querySelector(".account-sidebar")')
                for _ in range(2):
                    visit('my_reviews')
                    page.locator('.btn-leave-review').first.click()
                    expect(page.locator('#reviewModal')).to_have_class(re.compile(r'\bshow\b'))
                    page.get_by_role('button',name='Close review form',exact=True).click()
                    visit('customer_profile')
                    if _ == 0:
                        # The existing booking search remains asynchronous after mounting.
                        with page.expect_response(lambda response:'/customer/?' in response.url and response.request.resource_type=='fetch'):
                            page.locator('#searchFilterInput').fill('No matching event')
                        expect(page.locator('#bookings-results td[data-label="Booking ID"]')).to_have_count(0)
                        with page.expect_response(lambda response:'/customer/?' in response.url and response.request.resource_type=='fetch'):
                            page.locator('#searchFilterInput').fill('')
                    page.locator(f'[onclick="openBookingModal(\'{booking.pk}\')"]').first.click()
                    expect(page.locator('#bookingModal')).to_have_class(re.compile(r'\bshow\b'))
                    if leaflet.exists(): expect(page.locator('#booking_modal_map.leaflet-container')).to_be_visible()
                    page.keyboard.press('Escape')
                    visit('my_payments')
                    expect(page.locator('.cp-tab-btn').first).to_be_visible()
                    page.locator('.cp-tab-btn').last.click()
                    visit('report_concern')
                    page.locator('#categoryDropdown .dropdown-trigger').click()
                    expect(page.locator('#categoryDropdown')).to_have_class('custom-filter-dropdown open')
                    page.locator('#categoryDropdown [data-value="booking"]').click()
                    expect(page.locator('#category')).to_have_value('booking')
                    visit('my_profile')
                    page.locator('.btn-edit-profile').click()
                    expect(page.locator('#profileModal')).to_be_visible()
                    page.get_by_role('button',name='Close edit profile',exact=True).click()
                    page.locator('.btn-change-password').click()
                    page.locator('#id_old_password').fill('TestPassword!25')
                    page.locator('[data-password-target="id_old_password"]').click()
                    expect(page.locator('#id_old_password')).to_have_attribute('type','text')
                    page.get_by_role('button',name='Close change password',exact=True).click()
                self.assertEqual(page.evaluate('window.workspaceSentinel'),'persistent')
                self.assertTrue(page.evaluate('window.originalAccountSidebar===document.querySelector(".account-sidebar")'))
                self.assertEqual(len(documents),1)
                # Re-selecting the current page cancels a slower pending navigation.
                blocked=[]
                page.route('**/my-payments/',lambda route:blocked.append(route))
                page.locator('[data-account-key="my_payments"]').click()
                page.wait_for_function('window.AccountNavigation.navigating')
                page.locator('[data-account-key="my_profile"]').click(); settled('my_profile')
                for request in blocked: request.abort()
                page.unroute('**/my-payments/')
                page.go_back(wait_until='commit'); settled('report_concern')
                page.go_forward(wait_until='commit'); settled('my_profile')
                page.route('**/my-reviews/',lambda route:route.fulfill(status=503,body='Unavailable'))
                page.locator('[data-account-key="my_reviews"]').click()
                expect(page.locator('.account-navigation-status')).to_contain_text('couldn’t open')
                expect(page.locator('#accountContent')).to_have_attribute('data-account-page','my_profile')
                page.unroute('**/my-reviews/')
                page.get_by_role('button',name='Try again',exact=True).click(); settled('my_reviews')
                # A real review POST still works after the page was loaded asynchronously.
                page.locator('.btn-leave-review').first.click()
                page.locator('label[for="star5"]').click()
                page.locator('#review_comment').fill('A beautiful event setup from our account workspace.')
                with page.expect_response(lambda response:response.url.endswith(reverse('submit_review',args=[booking.pk])) and response.request.method=='POST') as saved:
                    page.locator('#reviewForm [type="submit"]').click()
                self.assertEqual(saved.value.status,201)
                expect(page.locator('.mr-published-section')).to_contain_text('A beautiful event setup')
                self.assertEqual(len(documents),1)
                for theme in ('light','dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    for width,height in ((1440,1000),(1024,768),(768,900),(390,844),(320,568)):
                        page.set_viewport_size({'width':width,'height':height})
                        page.evaluate('scrollTo(0,0)')
                        self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth+1'))
                        expect(page.locator('.account-mobile-toggle')).to_have_count(0)
                        if width<=968:
                            expect(page.locator('.account-sidebar')).to_be_hidden()
                            page.get_by_role('button',name='Profile menu',exact=True).click()
                            expect(page.locator('#clientAccountMenu').get_by_role('link')).to_have_count(6)
                            expect(page.locator('[data-account-menu-key="my_reviews"]')).to_have_attribute('aria-current','page')
                            page.keyboard.press('Escape')
                        else: expect(page.locator('.account-sidebar')).to_be_visible()
                        page.screenshot(path=str(artifacts/f'account-workspace-{theme}-{width}.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                for theme in ('light','dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    for key in ('my_profile','customer_profile','my_payments','report_concern','my_reviews'):
                        visit(key)
                        expect(page.locator('#clientAccountMenu')).to_be_hidden()
                        expect(page.locator('.account-sidebar')).to_be_hidden()
                    if theme == 'light':
                        # The avatar's current-page link must also cancel a slower selection.
                        blocked=[]
                        page.route('**/my-payments/',lambda route:blocked.append(route))
                        page.get_by_role('button',name='Profile menu',exact=True).click()
                        page.locator('[data-account-menu-key="my_payments"]').click()
                        page.wait_for_function('window.AccountNavigation.navigating')
                        visit('my_reviews')
                        for request in blocked: request.abort()
                        page.unroute('**/my-payments/')
                    page.go_back(wait_until='commit'); settled('report_concern')
                    page.go_forward(wait_until='commit'); settled('my_reviews')
                    self.assertEqual(page.evaluate('window.workspaceSentinel'),'persistent')
                    self.assertEqual(len(documents),1)
                # Every account page must fit the sidebar's available width, not just the reviews page.
                for key in ('my_profile','customer_profile','my_payments','report_concern'):
                    page.set_viewport_size({'width':1440,'height':1000}); visit(key)
                    for theme in ('light','dark'):
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                        for width in (1440,1024,390,320):
                            page.set_viewport_size({'width':width,'height':1000})
                            page.wait_for_function('!document.querySelector(".nav-links").getAnimations().some(animation=>animation.playState==="running")')
                            self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth+1'),f'{key}: {width} {theme}')
                            self.assertFalse(page.locator('.nav-links').evaluate('el=>el.classList.contains("nav-active")'))
                            if width in (1440,390): page.screenshot(path=str(artifacts/f'account-{key}-{theme}-{width}.png'),full_page=True)
                self.assertEqual(errors,[])
            finally:
                if errors: print('Account browser errors:',errors)
                page.screenshot(path=str(artifacts/'account-workspace-last.png'),full_page=True)
                context.close(); browser.close()
