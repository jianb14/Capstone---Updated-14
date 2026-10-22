"""Optional real-browser check: RUN_DESIGN_BROWSER=1 with Playwright installed."""
import base64
import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse

from .models import CanvasAsset, CanvasCategory, DesignOffer, DesignRequirement, Package, User


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright browser verification')
class DesignBrowserTests(StaticLiveServerTestCase):
    def test_quantity_states_survive_duplicate_undo_upload_save_and_reopen(self):
        from playwright.sync_api import sync_playwright, expect

        user = User.objects.create_user(username='browser_designer', role='customer')
        self.client.force_login(user)
        panels, _ = CanvasCategory.objects.get_or_create(name='Panels')
        balloons = CanvasCategory.objects.create(name='Browser balloon decor')
        panel = CanvasAsset.objects.create(category=panels, label='Browser panel', static_path='images/canvas/premium/frames/panel_wall.svg')
        balloon = CanvasAsset.objects.create(category=balloons, label='Browser balloon', static_path='images/canvas/premium/balloons/circle_blank.svg')
        package = Package.objects.create(name='Browser package', features='Two panels and balloon decor', price=5000)
        offer = DesignOffer.objects.create(kind='package', package=package, is_enabled=True)
        DesignRequirement.objects.create(offer=offer, category=panels, required=True, minimum=2, maximum=2)
        DesignRequirement.objects.create(offer=offer, category=balloons, required=True, minimum=1)
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + reverse('my_designs'), wait_until='domcontentloaded', timeout=60000)
            page.locator('.create-new-btn').click()
            page.locator('[data-design-tab="stand"]').click()
            expect(page.locator('[data-design-panel="stand"]')).to_be_visible()
            expect(page.locator('[data-design-panel="package"]')).to_be_hidden()
            page.locator('[data-design-tab="package"]').click()
            page.locator('[data-offer-open]').click()
            expect(page.locator('#designOfferDetailsModal')).to_contain_text('2 required')
            page.locator('#designOfferDetailsModal .feature-modal-btn').click()
            page.wait_for_function('typeof fabric !== "undefined" && document.querySelector(".canvas-container")', timeout=30000)
            page.locator('[data-panel-target="elementsPanel"]').click()

            def add(asset, category):
                group = page.locator(f'.inventory-category[data-category-id="{category.pk}"]')
                header = group.locator('.category-header')
                if 'is-open' not in (header.get_attribute('class') or ''):
                    header.click()
                group.locator(f'[data-asset-id="{asset.pk}"]').click()

            add(panel, panels)
            expect(page.locator('#cartInclusionsList')).to_contain_text('1/2 required')
            page.keyboard.press('Control+d')
            expect(page.locator('#cartInclusionsList')).to_contain_text('2/2 required')
            page.locator('#undoBtn').click()
            expect(page.locator('#cartInclusionsList')).to_contain_text('1/2 required')
            page.locator('#redoBtn').click()
            expect(page.locator('#cartInclusionsList')).to_contain_text('2/2 required')
            add(balloon, balloons)
            expect(page.locator('#designOverallState')).to_contain_text('Ready to book', timeout=15000)
            expect(page.locator('.design-completion-row.is-complete')).to_have_count(2)
            page.locator('#contextDeleteBtn').click()
            expect(page.locator('#cartInclusionsList')).to_contain_text('0/1 required')
            page.locator('#undoBtn').click()
            expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
            page.locator('[data-panel-target="uploadsPanel"]').click()
            pixel = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
            page.locator('#userUploadInput').set_input_files({'name': 'balloon-reference.png', 'mimeType': 'image/png', 'buffer': pixel})
            page.locator('#userUploadsGrid .draggable-item').first.click()
            expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
            expect(page.locator('#cartInclusionsList')).to_contain_text('1/1 required')
            page.locator('#saveDesignBtn').click()
            page.locator('#saveDesignNameInput').fill('Browser complete design')
            page.locator('#saveDesignConfirmBtn').click()
            page.wait_for_url('**/my-designs/', timeout=20000)
            expect(page.locator('.design-badge.design-ready')).to_be_visible()
            page.locator('.design-actions .edit-btn').first.click()
            expect(page.locator('#designOverallState')).to_contain_text('Ready to book', timeout=20000)
            expect(page.locator('.design-completion-row.is-complete')).to_have_count(2)
            self.assertFalse(errors, errors)
            browser.close()
