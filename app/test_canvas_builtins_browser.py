"""Optional browser verification of the built-in name tool across sessions."""
import importlib
import os
from pathlib import Path
from tempfile import gettempdir
from types import SimpleNamespace
from unittest import skipUnless

from django.apps import apps
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connection
from django.urls import reverse

from .canvas_builtins import STYRO_NAME
from .models import CanvasAsset, DesignOffer, DesignRequirement, Package, User


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
class BuiltinStyroBrowserTests(StaticLiveServerTestCase):
    def test_standalone_name_tool_counts_survives_undo_save_and_another_device(self):
        from playwright.sync_api import sync_playwright, expect

        # Live-server classes flush data between tests, including seeded rows.
        importlib.import_module('app.migrations.0103_builtin_styro_name').register_styro_name(apps, SimpleNamespace(connection=connection))
        asset = CanvasAsset.objects.get(builtin_key=STYRO_NAME)
        user = User.objects.create_user(username='builtin_browser', role='customer')
        self.client.force_login(user)
        package = Package.objects.create(name='Name package', price=1000)
        offer = DesignOffer.objects.create(kind='package', package=package, is_enabled=True)
        DesignRequirement.objects.create(offer=offer, category=asset.category, required=True, minimum=1, maximum=1)
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            context = browser.new_context()
            cookie = {'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}
            context.add_cookies([cookie])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                for theme in ('light', 'dark'):
                    for width, height in ((1440, 1000), (820, 1000), (390, 844)):
                        page.set_viewport_size({'width': width, 'height': height})
                        page.goto(self.live_server_url + reverse('design_canvas') + f'?design_offer_id={offer.pk}&fresh=1', wait_until='domcontentloaded')
                        page.evaluate('(theme) => {document.documentElement.dataset.theme = theme; localStorage.setItem("balloorina-theme", theme)}', theme)
                        expect(page.locator('#designOverallState')).to_contain_text('0 of 1')
                        page.locator('[data-panel-target="elementsPanel"]').click()
                        button = page.locator('#builtinStyroSection [data-asset-id]')
                        expect(button).to_be_visible()
                        expect(button).to_have_attribute('data-asset-id', str(asset.pk))
                        self.assertTrue(button.get_attribute('data-asset-token'))
                        expect(page.locator(f'.inventory-category [data-asset-id="{asset.pk}"]')).to_have_count(0)
                        page.locator('#builtinStyroSection').screenshot(path=str(Path(gettempdir()) / f'balloorina-styro-{theme}-{width}.png'))
                        button.click()
                        expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                        expect(page.locator('#cartInclusionsList')).to_contain_text('1/1 required')
                        page.locator('#undoBtn').click()
                        expect(page.locator('#cartInclusionsList')).to_contain_text('0/1 required')
                        if width <= 1024:
                            page.locator('#mobileCanvasToolsBtn').click()
                        page.locator('#redoBtn').click()
                        expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                page.locator('#saveDesignBtn').click()
                page.locator('#saveDesignNameInput').fill('Name saved across devices')
                with page.expect_response(lambda response: response.url.endswith('/my-designs/save/')) as saved:
                    page.locator('#saveDesignConfirmBtn').click()
                self.assertTrue(saved.value.json()['can_book'])
                design_id = saved.value.json()['id']
                second_context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                second_context.add_cookies([cookie])
                second_page = second_context.new_page()
                second_page.goto(self.live_server_url + reverse('design_canvas') + f'?id={design_id}', wait_until='domcontentloaded')
                expect(second_page.locator('#designOverallState')).to_contain_text('Ready to book')
                second_page.locator('[data-panel-target="elementsPanel"]').click()
                expect(second_page.locator('#builtinStyroSection [data-asset-id]')).to_have_attribute('data-asset-id', str(asset.pk))
                self.assertFalse(errors, errors)
            finally:
                browser.close()
