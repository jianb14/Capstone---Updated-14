"""Opt-in verification of the admin sidebar's persisted UI state and mobile drawer."""
import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import AuditLog, ConcernTicket, User


@skipUnless(os.environ.get('RUN_ADMIN_SIDEBAR_BROWSER') == '1', 'Optional sidebar browser verification')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminSidebarBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='sidebar-admin', first_name='Alex',
            email='sidebar@example.com', role='admin', email_verified=True)
        customer = User.objects.create_user(username='sidebar-customer', role='customer', email_verified=True)
        for index in range(3):
            ConcernTicket.objects.create(user=customer, subject=f'Concern {index}', message='Details')
        AuditLog.objects.create(user=self.admin, action='Sidebar preview activity')
        self.client.force_login(self.admin)
        self.artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'

    def context(self, playwright, width=1440, collapsed=False):
        browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': width, 'height': 1000 if width > 1024 else 844})
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            'url': self.live_server_url}])
        context.add_init_script("localStorage.setItem('balloorina-theme','light')")
        if collapsed:
            context.add_init_script("localStorage.setItem('balloorina-admin-sidebar','collapsed')")
        context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        context.route('https://cdnjs.cloudflare.com/**', lambda route: route.abort())
        context.route('https://cdn.jsdelivr.net/**', lambda route: route.fulfill(status=200,
            content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}})};'))
        return browser, context

    def test_desktop_collapse_tooltips_counts_persistence_and_no_toggle_reload(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as playwright:
            browser, context = self.context(playwright)
            page = context.new_page(); errors = []; documents = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
            try:
                page.goto(self.live_server_url + reverse('admin_audit_log'))
                sidebar = page.locator('[data-admin-sidebar]')
                expanded_width = sidebar.bounding_box()['width']
                page.screenshot(path=str(self.artifacts / 'admin-sidebar-expanded-light.png'), animations='disabled')
                page.get_by_role('button', name='Collapse sidebar', exact=True).click()
                page.wait_for_function('document.querySelector(".sidebar").getBoundingClientRect().width < 100')
                self.assertLess(sidebar.bounding_box()['width'], expanded_width / 2)
                page.wait_for_function('Math.abs(document.querySelector(".sidebar").getBoundingClientRect().width-document.querySelector(".main-content").getBoundingClientRect().left)<1')
                expect(page.get_by_role('button', name='Expand sidebar', exact=True)).to_have_attribute('aria-expanded', 'false')
                dashboard = sidebar.get_by_role('link', name='Dashboard', exact=True)
                dashboard.hover(); expect(page.get_by_role('tooltip')).to_have_text('Dashboard')
                self.assertGreaterEqual(page.get_by_role('tooltip').bounding_box()['x'], sidebar.bounding_box()['width'])
                page.keyboard.press('Escape'); expect(page.get_by_role('tooltip')).to_have_count(0)
                sidebar.get_by_role('link', name='AI Health', exact=True).focus()
                expect(page.get_by_role('tooltip')).to_have_text('AI Health')
                concerns = sidebar.locator('[data-concerns-link]')
                concerns.hover(); expect(page.locator('.admin-sidebar-tooltip-count')).to_have_text('3')
                concerns.locator('.nav-count-badge').evaluate('(node)=>node.textContent="4"')
                expect(page.locator('.admin-sidebar-tooltip-count')).to_have_text('4')
                page.screenshot(path=str(self.artifacts / 'admin-sidebar-tooltip-light.png'), animations='disabled')
                page.keyboard.press('Escape')
                page.emulate_media(reduced_motion='reduce')
                for theme in ('light', 'dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                    logout = sidebar.get_by_role('link', name='Log Out', exact=True)
                    before = logout.evaluate('(node)=>getComputedStyle(node).color')
                    page.mouse.move(500, 200)
                    logout.hover(); expect(logout).to_have_css('color', before)
                    expect(logout.locator('span')).to_have_css('color', before)
                    self.assertNotEqual(logout.evaluate('(node)=>getComputedStyle(node).backgroundColor'), 'rgba(0, 0, 0, 0)')
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                    page.screenshot(path=str(self.artifacts / f'admin-sidebar-tooltip-{theme}.png'), animations='disabled')
                    page.keyboard.press('Escape')
                    page.screenshot(path=str(self.artifacts / f'admin-sidebar-collapsed-{theme}.png'), animations='disabled')
                self.assertEqual(len(documents), 1)
                # Desktop preference survives ordinary navigation to a new admin page.
                concerns.click(); page.wait_for_url('**/staff/concerns/')
                expect(page.get_by_role('button', name='Expand sidebar', exact=True)).to_be_visible()
                self.assertLess(sidebar.bounding_box()['width'], expanded_width / 2)
                page.reload(); expect(page.get_by_role('button', name='Expand sidebar', exact=True)).to_be_visible()
                page.get_by_role('button', name='Expand sidebar', exact=True).press('Space')
                expect(page.get_by_role('button', name='Collapse sidebar', exact=True)).to_have_attribute('aria-expanded', 'true')
                page.get_by_role('button', name='Collapse sidebar', exact=True).press('Enter')
                expect(page.get_by_role('button', name='Expand sidebar', exact=True)).to_be_visible()
                page.emulate_media(reduced_motion='reduce')
                expect(sidebar).to_have_css('transition-duration', '0s')
                page.evaluate("()=>{Storage.prototype.setItem=()=>{throw new DOMException('Storage disabled','SecurityError')};}")
                page.get_by_role('button', name='Expand sidebar', exact=True).click()
                expect(page.get_by_role('button', name='Collapse sidebar', exact=True)).to_be_visible()
                self.assertEqual(errors, [])
            except Exception:
                page.screenshot(path=str(self.artifacts / 'admin-sidebar-desktop-failure.png'), full_page=True); raise
            finally:
                context.close(); browser.close()

    def test_mobile_drawer_focus_escape_backdrop_and_desktop_resize(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as playwright:
            browser, context = self.context(playwright, width=390, collapsed=True)
            page = context.new_page(); errors = []; documents = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
            try:
                page.goto(self.live_server_url + reverse('admin_audit_log'))
                sidebar = page.locator('[data-admin-sidebar]'); trigger = page.get_by_role('button', name='Toggle menu', exact=True)
                expect(sidebar).to_have_attribute('aria-hidden', 'true')
                self.assertTrue(sidebar.evaluate('(node)=>node.inert'))
                trigger.click(); expect(sidebar).to_have_attribute('aria-hidden', 'false')
                close = page.get_by_role('button', name='Close admin menu', exact=True)
                expect(close).to_be_focused(); expect(page.get_by_role('button', name='Expand sidebar', exact=True)).to_be_hidden()
                page.keyboard.press('Escape'); expect(trigger).to_be_focused(); expect(sidebar).to_have_attribute('aria-hidden', 'true')
                trigger.click(); page.locator('.sidebar-overlay').click(position={'x': 370, 'y': 300})
                expect(sidebar).to_have_attribute('aria-hidden', 'true')
                trigger.click(); close.click(); expect(trigger).to_be_focused()
                for width, theme in ((390, 'light'), (320, 'dark'), (768, 'dark')):
                    page.set_viewport_size({'width': width, 'height': 844})
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                    trigger.click(); expect(close).to_be_focused()
                    sidebar.get_by_role('link', name='Balloorina admin home', exact=True).focus()
                    page.keyboard.press('Shift+Tab'); expect(sidebar.get_by_role('link', name='Log Out', exact=True)).to_be_focused()
                    page.keyboard.press('Tab'); expect(sidebar.get_by_role('link', name='Balloorina admin home', exact=True)).to_be_focused()
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                    self.assertEqual(page.evaluate("localStorage.getItem('balloorina-admin-sidebar')"), 'collapsed')
                    page.screenshot(path=str(self.artifacts / f'admin-sidebar-mobile-{theme}-{width}.png'), animations='disabled')
                    page.keyboard.press('Escape')
                trigger.click(); page.set_viewport_size({'width': 1440, 'height': 1000})
                expect(page.locator('.sidebar-overlay')).not_to_have_class('sidebar-overlay active')
                expect(page.get_by_role('button', name='Expand sidebar', exact=True)).to_be_visible()
                page.wait_for_function('document.querySelector(".sidebar").getBoundingClientRect().width < 100')
                self.assertLess(sidebar.bounding_box()['width'], 100)
                self.assertFalse(page.evaluate("document.body.classList.contains('admin-sidebar-open')"))
                self.assertEqual(len(documents), 1); self.assertEqual(errors, [])
            except Exception:
                page.screenshot(path=str(self.artifacts / 'admin-sidebar-mobile-failure.png'), full_page=True); raise
            finally:
                context.close(); browser.close()
