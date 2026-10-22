"""Optional browser checks for settings, counters, and a stale-tab save conflict."""
import os
from pathlib import Path
from tempfile import gettempdir
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client
from django.urls import reverse

from .models import CanvasAsset, CanvasCategory, DesignOffer, DesignRequirement, Package, SiteSettings, User, UserDesign


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
class DesignLimitsBrowserTests(StaticLiveServerTestCase):
    def test_settings_counter_and_limit_conflict_keep_unsaved_canvas(self):
        from playwright.sync_api import sync_playwright, expect

        customer = User.objects.create_user(username='limit_browser_customer', role='customer')
        admin = User.objects.create_user(username='limit_browser_admin', role='admin')
        self.client.force_login(customer)
        admin_client = Client()
        admin_client.force_login(admin)
        site = SiteSettings.load()
        site.max_saved_designs = 2
        site.save()
        category = CanvasCategory.objects.create(name='Limit browser panels')
        asset = CanvasAsset.objects.create(category=category, label='Panel', static_path='images/canvas/premium/frames/panel_wall.svg')
        package = Package.objects.create(name='Limit package', price=5000, features='1 Panel')
        offer = DesignOffer.objects.create(kind='package', package=package, is_enabled=True)
        DesignRequirement.objects.create(offer=offer, category=category, required=True, minimum=1, maximum=1)
        for index in range(2):
            UserDesign.objects.create(user=customer, name=f'Saved draft {index}', design_offer=offer, canvas_json='{"objects": []}')

        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                contexts = [browser.new_context(viewport={'width': 1440, 'height': 1000}) for _ in range(2)]
                for context, client in zip(contexts, (self.client, admin_client)):
                    context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
                page, admin_page = [context.new_page() for context in contexts]
                errors = []
                for target in (page, admin_page):
                    target.on('pageerror', lambda error: errors.append(str(error)))
                for theme in ('light', 'dark'):
                    for width, height in ((1440, 1000), (820, 1000), (390, 844)):
                        for target, endpoint in ((page, 'my_designs'), (admin_page, 'admin_site_settings')):
                            target.set_viewport_size({'width': width, 'height': height})
                            target.goto(self.live_server_url + reverse(endpoint), wait_until='domcontentloaded')
                            target.evaluate('(theme) => {document.documentElement.dataset.theme = theme; localStorage.setItem("balloorina-theme", theme)}', theme)
                        expect(page.locator('#designStorageCount')).to_contain_text('2/2 designs saved')
                        expect(page.locator('.create-new-btn')).to_be_disabled()
                        expect(page.locator('#designLimitNote')).to_be_visible()
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 1)
                        form = admin_page.locator('#design-settings')
                        expect(form.locator('input[name="max_saved_designs"]')).to_have_value('2')
                        self.assertLessEqual(form.evaluate('(el) => el.scrollWidth - el.clientWidth'), 1)
                        input_field = form.locator('#ss_max_saved_designs')
                        input_field.fill('0')
                        admin_page.locator('#ss_btn_save').click()
                        expect(form.locator('#ss_design_limit_error')).to_be_visible()
                        expect(input_field).to_have_attribute('aria-invalid', 'true')
                        self.assertEqual(form.locator('#ss_design_limit_error').evaluate('(el) => getComputedStyle(el).color'), 'rgb(239, 68, 68)')
                        input_field.fill('2')
                        expect(input_field).to_have_attribute('aria-invalid', 'false')
                        expect(form.locator('#ss_design_limit_error')).to_be_hidden()
                        form.screenshot(path=str(Path(gettempdir()) / f'balloorina-design-limit-admin-{theme}-{width}.png'), animations='disabled')

                def set_limit(value):
                    admin_page.locator('#ss_max_saved_designs').fill(str(value))
                    admin_page.locator('#ss_btn_save').click()
                    admin_page.wait_for_url('**/staff/settings/')
                    expect(admin_page.locator('#ss_max_saved_designs')).to_have_value(str(value))

                for target in (page, admin_page):
                    target.set_viewport_size({'width': 1440, 'height': 1000})
                set_limit(3)
                page.reload(wait_until='domcontentloaded')
                expect(page.locator('#designStorageCount')).to_contain_text('2/3 designs saved')
                expect(page.locator('.create-new-btn')).to_be_enabled()
                page.locator('.create-new-btn').click()
                page.locator('[data-offer-open]').click()
                page.locator('#designOfferDetailsModal .feature-modal-btn').click()
                page.wait_for_function('typeof fabric !== "undefined" && document.querySelector(".canvas-container")')
                page.locator('[data-panel-target="elementsPanel"]').click()
                group = page.locator(f'.inventory-category[data-category-id="{category.pk}"]')
                if 'is-open' not in (group.locator('.category-header').get_attribute('class') or ''):
                    group.locator('.category-header').click()
                group.locator(f'[data-asset-id="{asset.pk}"]').click()
                expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                # Another tab/admin change fills this allowance after the editor was opened.
                set_limit(2)
                page.locator('#saveDesignBtn').click()
                page.locator('#saveDesignNameInput').fill('Keep my unsaved work')
                with page.expect_response(lambda response: response.url.endswith('/my-designs/save/')) as conflict:
                    page.locator('#saveDesignConfirmBtn').click()
                self.assertEqual(conflict.value.status, 409)
                expect(page.locator('#saveDesignModal')).to_be_visible()
                expect(page.locator('#saveDesignNameInput')).to_have_value('Keep my unsaved work')
                expect(page.locator('#saveDesignConfirmBtn')).to_be_enabled()
                self.assertIn(reverse('design_canvas'), page.url)
                self.assertEqual(conflict.value.json()['design_usage']['used'], 2)
                set_limit(3)
                page.locator('#saveDesignConfirmBtn').click()
                page.wait_for_url('**/my-designs/', timeout=20000)
                expect(page.locator('#designStorageCount')).to_contain_text('3/3 designs saved')
                expect(page.locator('.create-new-btn')).to_be_disabled()
                page.locator('.design-card').filter(has=page.locator('.design-ready')).locator('.edit-btn').click()
                expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                page.locator('#saveDesignBtn').click()
                page.wait_for_url('**/my-designs/', timeout=20000)
                expect(page.locator('#designStorageCount')).to_contain_text('3/3 designs saved')
                self.assertFalse(errors, errors)
            finally:
                browser.close()
