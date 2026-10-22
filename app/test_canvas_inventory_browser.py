"""Optional browser checks for inventory styling, search, and outline controls."""
import base64
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

from .models import CanvasAsset, CanvasCategory, DesignOffer, DesignRequirement, Package, User


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
class CanvasInventoryBrowserTests(StaticLiveServerTestCase):
    def test_flat_inventory_search_badge_order_and_layer_actions(self):
        from playwright.sync_api import sync_playwright, expect

        importlib.import_module('app.migrations.0103_builtin_styro_name').register_styro_name(apps, SimpleNamespace(connection=connection))
        builtin = CanvasAsset.objects.get(builtin_key='styrofoam_name')
        category = CanvasCategory.objects.create(name='Inventory panels')
        panel = CanvasAsset.objects.create(category=category, label='Panel wall', static_path='images/canvas/premium/frames/panel_wall.svg')
        flowers = CanvasCategory.objects.create(name='Inventory flowers')
        CanvasAsset.objects.create(category=flowers, label='Flower decor', static_path='images/canvas/premium/balloons/circle_blank.svg')
        package = Package.objects.create(name='Inventory package', price=4799)
        offer = DesignOffer.objects.create(kind='package', package=package, is_enabled=True)
        for group in (category, builtin.category):
            DesignRequirement.objects.create(offer=offer, category=group, required=True, minimum=1, maximum=2)
        DesignRequirement.objects.create(offer=offer, category=flowers, minimum=0, maximum=1)
        user = User.objects.create_user(username='inventory_browser', role='customer')
        self.client.force_login(user)

        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            context = browser.new_context()
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                for theme in ('light', 'dark'):
                    for width, height in ((1440, 1000), (820, 1000), (390, 844)):
                        page.set_viewport_size({'width': width, 'height': height})
                        page.goto(self.live_server_url + reverse('design_canvas') + f'?design_offer_id={offer.pk}&fresh=1', wait_until='domcontentloaded')
                        page.evaluate('(theme) => {document.documentElement.dataset.theme = theme; localStorage.setItem("balloorina-theme", theme)}', theme)
                        expect(page.locator('#designOverallState')).to_contain_text('0 of 2')
                        if page.locator('#summaryFloatBtn').get_attribute('aria-expanded') == 'true':
                            page.locator('#summaryFloatBtn').click()
                        page.locator('[data-panel-target="elementsPanel"]').click()
                        sidebar = page.locator('#canvasSidebar')
                        expect(sidebar.locator('i.fas, i.far')).to_have_count(0)
                        expect(page.locator('.canvas-tool-rail i')).to_have_count(0)
                        for label in sidebar.locator('#elementsPanel .section-label').all():
                            self.assertEqual(label.evaluate('(el) => getComputedStyle(el).textTransform'), 'none')
                            self.assertEqual(label.evaluate('(el) => getComputedStyle(el).fontWeight'), '600')
                        for target in (sidebar, page.locator('.rail-btn.active'), sidebar.locator('.draggable-item').first):
                            self.assertEqual(target.evaluate('(el) => getComputedStyle(el).backgroundImage'), 'none')
                        header = sidebar.locator(f'.inventory-category[data-category-id="{category.pk}"] .category-header')
                        expect(header.locator('.inventory-required')).to_have_text('Required')
                        self.assertTrue(header.locator('.inventory-required').evaluate('(el) => el.nextElementSibling.classList.contains("chevron")'))
                        search = sidebar.locator('#assetSearchInput')
                        search.focus()
                        self.assertNotEqual(sidebar.locator('.panel-search').evaluate('(el) => getComputedStyle(el).boxShadow'), 'none')
                        search.fill('flower')
                        expect(sidebar.locator('#clearAssetSearch')).to_be_visible()
                        expect(sidebar.locator(f'.inventory-category[data-category-id="{flowers.pk}"]')).to_be_visible()
                        expect(sidebar.locator(f'.inventory-category[data-category-id="{category.pk}"]')).to_be_hidden()
                        expect(sidebar.locator('#builtinStyroSection')).to_be_hidden()
                        sidebar.locator('#clearAssetSearch').click()
                        expect(search).to_have_value('')
                        expect(search).to_be_focused()
                        expect(sidebar.locator('#clearAssetSearch')).to_be_hidden()
                        expect(sidebar.locator('#builtinStyroSection')).to_be_visible()
                        sidebar.screenshot(path=str(Path(gettempdir()) / f'balloorina-inventory-assets-{theme}-{width}.png'), animations='disabled')
                        if width <= 1024:
                            page.locator('#mobileInventoryDialog [data-mobile-close]').click()
                        for tab in ('textPanel', 'uploadsPanel', 'layersPanel'):
                            page.locator(f'[data-panel-target="{tab}"]').click()
                            expect(sidebar.locator(f'#{tab}')).to_be_visible()
                            expect(sidebar.locator('i.fas, i.far')).to_have_count(0)
                            for label in sidebar.locator(f'#{tab} .section-label').all():
                                self.assertEqual(label.evaluate('(el) => getComputedStyle(el).textTransform'), 'none')
                            if tab == 'uploadsPanel':
                                upload_box = page.locator('#referenceUploadDropzone')
                                page.locator('#browseReferenceFiles').scroll_into_view_if_needed()
                                self.assertLessEqual(upload_box.evaluate('(el) => el.scrollHeight - el.clientHeight'), 1)
                                count = page.locator('#userUploadsGrid .draggable-item').count()
                                image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL1sAAAAASUVORK5CYII=')
                                with page.expect_file_chooser() as picker:
                                    page.locator('#browseReferenceFiles').press('Enter')
                                picker.value.set_files({'name': 'reference.png', 'mimeType': 'image/png', 'buffer': image})
                                expect(page.locator('#userUploadsGrid .draggable-item')).to_have_count(count + 1)
                                card = page.locator('#userUploadsGrid .draggable-item').first
                                self.assertTrue(card.evaluate('(el) => el.querySelector("small").getBoundingClientRect().top >= el.querySelector("img").getBoundingClientRect().bottom'))
                                if width == 1440:
                                    page.evaluate('''() => {
                                        window.uploadTransfer = new DataTransfer();
                                        uploadTransfer.items.add(new File([Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL1sAAAAASUVORK5CYII='), c => c.charCodeAt(0))], 'drop.png', {type: 'image/png'}));
                                        document.querySelector('#referenceUploadDropzone').dispatchEvent(new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: uploadTransfer}));
                                    }''')
                                    expect(upload_box).to_have_class('upload-dropzone is-file-over')
                                    page.evaluate('''() => document.querySelector('#referenceUploadDropzone').dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: uploadTransfer}))''')
                                    expect(upload_box).to_have_class('upload-dropzone')
                                    expect(page.locator('#userUploadsGrid .draggable-item')).to_have_count(count + 2)
                                    page.locator('#userUploadInput').set_input_files({'name': 'invalid.txt', 'mimeType': 'text/plain', 'buffer': b'not an image'})
                                    expect(page.locator('#userUploadsGrid .draggable-item')).to_have_count(count + 2)
                                expect(page.locator('#designOverallState')).to_contain_text('0 of 2')
                            sidebar.screenshot(path=str(Path(gettempdir()) / f'balloorina-inventory-{tab}-{theme}-{width}.png'), animations='disabled')
                            if width <= 1024:
                                page.locator('#mobileInventoryDialog [data-mobile-close]').click()
                        self.assertLessEqual(sidebar.evaluate('(el) => el.scrollWidth - el.clientWidth'), 1)
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 1)
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.goto(self.live_server_url + reverse('design_canvas') + f'?design_offer_id={offer.pk}&fresh=1', wait_until='domcontentloaded')
                page.locator('[data-panel-target="textPanel"]').click()
                page.locator('.text-preset-card[title="Add a Heading"]').press('Enter')
                page.locator('[data-panel-target="layersPanel"]').click()
                row = page.locator('.layer-row').first
                expect(row).to_be_visible()
                expect(row.locator('i')).to_have_count(0)
                row.locator('[aria-label="Hide"]').click()
                expect(page.locator('.layer-row [aria-label="Show"] svg use')).to_have_attribute('href', '#ci-eye-off')
                page.locator('.layer-row [aria-label="Show"]').click()
                page.locator('.layer-row [aria-label="Lock"]').click()
                expect(page.locator('.layer-row')).to_have_class('layer-row is-locked is-active')
                expect(page.locator('.layer-row [aria-label="Unlock"] svg use')).to_have_attribute('href', '#ci-lock')
                page.locator('.layer-row [aria-label="Unlock"]').click()
                page.locator('.layer-row [aria-label="Delete layer"]').click()
                expect(page.locator('.layer-row')).to_have_count(0)
                for theme in ('light', 'dark'):
                    page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                    page.locator('[data-panel-target="textPanel"]').click()
                    for title in ('Add a Heading', 'Add a Subheading', 'Add a little body text'):
                        page.locator(f'.text-preset-card[title="{title}"]').press('Enter')
                    page.locator('[data-panel-target="layersPanel"]').click()
                    rows = page.locator('.layer-row')
                    expect(rows).to_have_count(3)
                    initial_order = rows.evaluate_all('(rows) => rows.map(row => row.dataset.layerId)')
                    page.evaluate('''() => {
                        window.layerTransfer = new DataTransfer();
                        window.dragSource = document.querySelector('.layer-row');
                        dragSource.dispatchEvent(new DragEvent('dragstart', {bubbles: true, cancelable: true, dataTransfer: layerTransfer}));
                    }''')
                    for position, marker in (('top', 'drop-before'), ('bottom', 'drop-after')):
                        rows.nth(1).evaluate('''(el, position) => {
                            const rect = el.getBoundingClientRect();
                            el.dispatchEvent(new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: layerTransfer, clientY: position === 'top' ? rect.top + 2 : rect.bottom - 2}));
                        }''', position)
                        expect(page.locator(f'.layer-row.{marker}')).to_have_count(1)
                        self.assertNotEqual(rows.nth(1).evaluate('(el) => getComputedStyle(el).boxShadow'), 'none')
                    page.locator('#canvasSidebar').screenshot(path=str(Path(gettempdir()) / f'balloorina-layer-insertion-{theme}.png'), animations='disabled')
                    page.evaluate('''() => dragSource.dispatchEvent(new DragEvent('dragend', {bubbles: true, dataTransfer: layerTransfer}))''')
                    expect(page.locator('.drop-before, .drop-after, .drop-at-end')).to_have_count(0)
                    # Native browser drag: move the front layer behind the last row.
                    rows.first.drag_to(rows.last, target_position={'x': 60, 'y': rows.last.bounding_box()['height'] - 3})
                    expect(rows.last).to_have_attribute('data-layer-id', initial_order[0])
                    page.locator('#undoBtn').click()
                    expect(rows.first).to_have_attribute('data-layer-id', initial_order[0])
                    self.assertEqual(rows.evaluate_all('(rows) => rows.map(row => row.dataset.layerId)'), initial_order)
                    # The empty space below the list is also a visible drop destination.
                    page.evaluate('''() => {
                        window.dragSource = document.querySelector('.layer-row');
                        dragSource.dispatchEvent(new DragEvent('dragstart', {bubbles: true, cancelable: true, dataTransfer: layerTransfer}));
                        document.querySelector('#layersList').dispatchEvent(new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: layerTransfer}));
                    }''')
                    expect(page.locator('#layersList')).to_have_class('layers-list drop-at-end')
                    self.assertEqual(page.locator('#layersList').evaluate('(el) => getComputedStyle(el, "::after").height'), '3px')
                    page.evaluate('''() => {
                        document.querySelector('#layersList').dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: layerTransfer}));
                        dragSource.dispatchEvent(new DragEvent('dragend', {bubbles: true, dataTransfer: layerTransfer}));
                    }''')
                    expect(rows.last).to_have_attribute('data-layer-id', initial_order[0])
                    expect(page.locator('.drop-before, .drop-after, .drop-at-end')).to_have_count(0)
                    for _ in range(3):
                        rows.first.locator('[aria-label="Delete layer"]').click()
                # A pinned background stays last; the marker must show above it.
                page.locator('[data-panel-target="textPanel"]').click()
                for title in ('Add a Heading', 'Add a Subheading'):
                    page.locator(f'.text-preset-card[title="{title}"]').press('Enter')
                page.locator('[data-panel-target="uploadsPanel"]').click()
                page.locator('#bgImageUpload').set_input_files({'name': 'background.png', 'mimeType': 'image/png', 'buffer': image})
                page.locator('[data-panel-target="layersPanel"]').click()
                expect(rows).to_have_count(3)
                expect(rows.last).to_have_class('layer-row is-bg')
                expect(rows.last).to_have_attribute('draggable', 'false')
                initial_order = rows.evaluate_all('(rows) => rows.map(row => row.dataset.layerId)')
                page.evaluate('''() => {
                    window.dragSource = document.querySelector('.layer-row');
                    dragSource.dispatchEvent(new DragEvent('dragstart', {bubbles: true, cancelable: true, dataTransfer: layerTransfer}));
                    const bg = document.querySelector('.layer-row.is-bg');
                    bg.dispatchEvent(new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: layerTransfer, clientY: bg.getBoundingClientRect().bottom - 2}));
                }''')
                expect(rows.last).to_have_class('layer-row is-bg drop-before')
                page.evaluate('''() => document.querySelector('#layersList').dispatchEvent(new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: layerTransfer}))''')
                expect(rows.last).to_have_class('layer-row is-bg drop-before')
                expect(page.locator('#layersList')).to_have_class('layers-list')
                page.evaluate('''() => {
                    document.querySelector('#layersList').dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: layerTransfer}));
                    dragSource.dispatchEvent(new DragEvent('dragend', {bubbles: true, dataTransfer: layerTransfer}));
                }''')
                expect(rows.nth(1)).to_have_attribute('data-layer-id', initial_order[0])
                expect(rows.last).to_have_class('layer-row is-bg')
                expect(page.locator('.drop-before, .drop-after, .drop-at-end')).to_have_count(0)
                page.locator('#undoBtn').click()
                expect(rows.first).to_have_attribute('data-layer-id', initial_order[0])
                self.assertFalse(errors, errors)
            finally:
                browser.close()
