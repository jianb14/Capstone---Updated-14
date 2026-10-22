"""Optional end-to-end verification of the shared settings form and save bar."""
import os
from pathlib import Path
from unittest import skipUnless
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from .models import ServiceChargeConfig, SiteSettings, User


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional browser verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class SiteSettingsBrowserTests(StaticLiveServerTestCase):
    def test_sections_single_save_dirty_tracking_and_map_stacking(self):
        from playwright.sync_api import sync_playwright, expect
        admin = User.objects.create_user(username='settings-browser', role='admin')
        self.client.force_login(admin)
        ServiceChargeConfig.objects.create(pk=1, amount=1000, notes='Original notes.', shop_lat='14.4', shop_lng='120.9')
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            try:
                context = browser.new_context()
                context.add_init_script('window.Swal = {mixin: () => ({fire: () => Promise.resolve({})}), fire: () => Promise.resolve({}), stopTimer() {}, resumeTimer() {}, DismissReason: {cancel: "cancel"}};')
                context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
                # Avoid depending on the availability of external maps/fonts.
                context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url) else route.abort())
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                for theme in ('light', 'dark'):
                    for width in (1440, 820, 390):
                        page.set_viewport_size({'width': width, 'height': 1000})
                        page.goto(self.live_server_url + reverse('admin_site_settings'), wait_until='domcontentloaded')
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        expect(page.locator('#ss_form button[type="submit"]')).to_have_count(1)
                        save = page.locator('#ss_btn_save')
                        expect(save).to_be_disabled()
                        notes = page.locator('#ss_logistics_notes')
                        notes.fill('Browser updated notes.')
                        expect(save).to_be_enabled()
                        notes.fill('Original notes.')
                        expect(save).to_be_disabled()
                        page.locator('#ss_max_saved_designs').fill('0')
                        save.click()
                        expect(page.locator('#ss_design_limit_error')).to_be_visible()
                        expect(save).to_be_enabled()
                        page.locator('#ss_max_saved_designs').fill('25')
                        expect(page.locator('#ss_design_limit_error')).to_be_hidden()
                        # Simulate Leaflet's pane stacking without a network map.
                        page.locator('#ss_shop_map').evaluate('el => { el.style.position="relative"; const pane=document.createElement("div"); pane.style.cssText="position:absolute;inset:0;z-index:1000;background:#ccc"; el.replaceChildren(pane); el.scrollIntoView({block:"center"}); }')
                        page.wait_for_timeout(100)
                        self.assertTrue(page.locator('.ss-savebar').evaluate('el => {const r=el.getBoundingClientRect(); const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return el.contains(hit);}'))
                        if width > 600:
                            for field in ('ss_contact_phone', 'ss_change_cutoff'):
                                self.assertEqual(page.locator('#' + field).evaluate('el=>getComputedStyle(el.closest(".ss-field")).gridColumn'), '1 / -1')
                        for field in ('ss_payment_window', 'ss_design_lead', 'ss_change_cutoff'):
                            expect(page.locator('#' + field).locator('..').locator('svg')).to_be_visible()
                        self.assertLessEqual(page.locator('.ss-page').evaluate('el=>el.scrollWidth-el.clientWidth'), 1)
                notes.fill('Saved with the common button.')
                page.locator('#ss_logistics_per_km_rate').fill('55')
                with page.expect_navigation(wait_until='domcontentloaded'):
                    save.click()
                expect(page.locator('#ss_max_saved_designs')).to_have_value('25')
                expect(page.locator('#ss_logistics_notes')).to_have_value('Saved with the common button.')
                self.assertFalse(errors, errors)
            finally:
                browser.close()
        self.assertEqual(SiteSettings.load().max_saved_designs, 25)
        self.assertEqual(ServiceChargeConfig.objects.get(pk=1).per_km_rate, 55)
