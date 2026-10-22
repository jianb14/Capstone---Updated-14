"""Touch workflows for the labelled mobile canvas, using isolated test data."""
import json
import os
from pathlib import Path
from tempfile import gettempdir
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import CanvasAsset, CanvasCategory, DesignOffer, DesignRequirement, Package, User, UserDesign


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class CanvasMobileBrowserTests(StaticLiveServerTestCase):
    def test_touch_add_edit_reorder_checklist_save_and_device_switch(self):
        from playwright.sync_api import sync_playwright, expect

        user = User.objects.create_user(username='mobile_canvas_browser', role='customer')
        self.client.force_login(user)
        category = CanvasCategory.objects.create(name='Mobile panels')
        asset = CanvasAsset.objects.create(category=category, label='Backdrop panel', static_path='images/canvas/premium/frames/panel_wall.svg')
        package = Package.objects.create(name='Mobile package', price=4799)
        offer = DesignOffer.objects.create(kind='package', package=package, is_enabled=True)
        DesignRequirement.objects.create(offer=offer, category=category, required=True, minimum=1, maximum=2)
        cookie = {'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}
        saved_id = None
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            errors = []
            try:
                for theme in ('light', 'dark'):
                    for width, height in ((320, 740), (390, 844), (600, 900), (820, 1000)):
                        context = browser.new_context(viewport={'width': width, 'height': height}, has_touch=True, is_mobile=True)
                        context.add_cookies([cookie])
                        page = context.new_page()
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(self.live_server_url + reverse('design_canvas') + f'?design_offer_id={offer.pk}&fresh=1', wait_until='domcontentloaded')
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        expect(page.locator('body')).to_have_class('canvas-mobile-active')
                        expect(page.locator('#designOverallState')).to_contain_text('0 of 1')
                        expect(page.locator('#mobileEditorGuide')).to_be_visible()
                        expect(page.locator('#mobileRequirementsTitle')).to_have_text('0 of 1 requirement complete')
                        expect(page.locator('#mobileRequirementsCopy')).to_contain_text('Add required items to book')
                        expect(page.locator('#mobileChecklistCount')).to_have_text('1')
                        page.locator('#mobileRequiredItemsBtn').tap()
                        expect(page.locator('#mobileChecklistDialog')).to_be_visible()
                        expect(page.locator('#cartInclusionsList')).to_contain_text('Add 1 more')
                        page.locator('#mobileChecklistDialog [data-mobile-close]').tap()
                        for selector in ('#saveDesignBtn', '#undoBtn', '#mobileCanvasToolsBtn'):
                            button = page.locator(selector)
                            expect(button).to_be_visible()
                            self.assertGreaterEqual(button.bounding_box()['height'], 48)
                        expect(page.locator('.canvas-tool-rail .rail-btn')).to_have_count(5)
                        self.assertLessEqual(page.locator('.canvas-tool-rail').evaluate('(el) => el.scrollWidth - el.clientWidth'), 1)
                        self.assertLessEqual(page.locator('.canvas-main-toolbar').evaluate('(el) => el.scrollWidth - el.clientWidth'), 1)
                        self.assertGreater(page.locator('#canvasDropZone').bounding_box()['height'], height * .45)
                        toolbar_box = page.locator('.canvas-main-toolbar').bounding_box()
                        self.assertGreaterEqual(page.locator('#mobileEditorGuide').bounding_box()['y'], toolbar_box['y'] + toolbar_box['height'])
                        # Pointer tooltips belong above the bottom navigation,
                        # including the first and last buttons near screen edges.
                        for button in page.locator('.canvas-tool-rail .rail-btn').all():
                            button.hover()
                            tooltip = page.locator('.selection-toolbar-tooltip:popover-open')
                            expect(tooltip).to_be_visible()
                            expect(tooltip).to_have_attribute('data-placement', 'top')
                            tip_box = tooltip.bounding_box()
                            self.assertLessEqual(tip_box['y'] + tip_box['height'], button.bounding_box()['y'])
                            self.assertGreaterEqual(tip_box['x'], 0)
                            self.assertLessEqual(tip_box['x'] + tip_box['width'], width)
                        page.screenshot(path=str(Path(gettempdir()) / f'balloorina-mobile-navigation-tooltip-{theme}-{width}.png'), animations='disabled')
                        page.mouse.move(0, 0)
                        expect(page.locator('#ai-fab')).to_be_hidden()
                        expect(page.locator('#adminChatToggle')).to_be_hidden()
                        page.screenshot(path=str(Path(gettempdir()) / f'balloorina-mobile-canvas-{theme}-{width}.png'), animations='disabled')
                        page.locator('[data-panel-target="textPanel"]').tap()
                        expect(page.locator('#mobileInventoryDialog')).to_be_visible()
                        page.locator('.text-preset-card[title="Add a Heading"]').tap()
                        expect(page.locator('#mobileInventoryDialog')).to_be_hidden()
                        expect(page.locator('#mobileSelectionBar')).to_be_visible()
                        expect(page.locator('#selectionToolbar')).to_be_hidden()
                        page.locator('#mobileEditItemBtn').tap()
                        expect(page.locator('#mobileObjectText')).to_be_visible()
                        self.assertFalse(page.locator('#mobileEditItemDialog').evaluate('(el) => el.matches(":modal")'))
                        canvas_box = page.locator('#canvasDropZone').bounding_box()
                        edit_box = page.locator('#mobileEditItemDialog').bounding_box()
                        self.assertGreater(canvas_box['height'], 180)
                        self.assertLessEqual(canvas_box['y'] + canvas_box['height'], edit_box['y'] + 1)
                        expect(page.locator('.canvas-tool-rail')).to_be_hidden()
                        expect(page.locator('#mobileObjectText')).to_have_css('font-size', '16px')
                        page.locator('#mobileObjectText').fill("Maria's birthday")
                        if width == 390:
                            # Keep Done reachable when the available keyboard viewport shrinks.
                            page.set_viewport_size({'width': width, 'height': 520})
                            self.assertLessEqual(page.locator('#mobileEditItemDialog [data-mobile-close]').bounding_box()['y'] + 48, 520)
                            page.set_viewport_size({'width': width, 'height': height})
                        page.locator('#fontSizeInput').fill('64')
                        page.locator('#fontSizeInput').press('Tab')
                        page.locator('#fontFamilyDropdown .dropdown-trigger').tap()
                        page.locator('#fontFamilyOptions li[data-value="Montserrat"]').tap()
                        expect(page.locator('#fontFamilySelect')).to_have_value('Montserrat')
                        page.locator('button[data-edit-section="position"]').tap()
                        page.locator('#contextLockBtn').tap()
                        expect(page.locator('#mobileLockedNote')).to_be_visible()
                        expect(page.locator('#mobileObjectText')).to_be_disabled()
                        page.locator('#contextLockBtn').tap()
                        expect(page.locator('#mobileObjectText')).to_be_enabled()
                        page.locator('button[data-edit-section="text"]').tap()
                        self.assertLessEqual(page.locator('#mobileEditItemDialog').evaluate('(el) => el.scrollWidth - el.clientWidth'), 1)
                        page.screenshot(path=str(Path(gettempdir()) / f'balloorina-mobile-edit-{theme}-{width}.png'), animations='disabled')
                        page.locator('#mobileEditItemDialog [data-mobile-close]').tap()
                        page.locator('#undoBtn').hover()
                        tooltip = page.locator('.selection-toolbar-tooltip:popover-open')
                        expect(tooltip).to_be_visible()
                        expect(tooltip).to_contain_text('Undo')
                        expect(tooltip).to_have_attribute('data-placement', 'bottom')
                        self.assertGreaterEqual(tooltip.bounding_box()['y'], page.locator('#undoBtn').bounding_box()['y'] + 48)
                        page.screenshot(path=str(Path(gettempdir()) / f'balloorina-mobile-guidance-{theme}-{width}.png'), animations='disabled')
                        page.locator('#undoBtn').tap()
                        page.locator('#mobileCanvasToolsBtn').tap()
                        page.locator('#redoBtn').tap()
                        expect(page.locator('#mobileCanvasToolsDialog')).to_be_hidden()
                        if theme == 'light' and width == 390:
                            page.locator('#mobileCanvasToolsBtn').tap()
                            expect(page.locator('#mobileCanvasToolsDialog')).not_to_contain_text('Need help')
                            expect(page.locator('#mobileMessageStaff, #mobileAskAssistant')).to_have_count(0)
                            dropdown = page.locator('#mobileCanvasToolsDialog details').first
                            expect(dropdown.locator('summary svg use')).to_have_attribute('href', '#ci-chevron')
                            expect(dropdown.locator('summary')).to_have_css('list-style-type', 'none')
                            dropdown.locator('summary').tap()
                            expect(dropdown).to_have_attribute('open', '')
                            page.screenshot(path=str(Path(gettempdir()) / 'balloorina-mobile-tools.png'), animations='disabled')
                            page.locator('#mobileCanvasToolsDialog [data-mobile-close]').tap()
                        page.locator('#mobileChecklistBtn').tap()
                        expect(page.locator('#mobileChecklistDialog')).to_be_visible()
                        page.locator('#cartInclusionsList .design-add-missing').first.tap()
                        expect(page.locator('#mobileChecklistDialog')).to_be_hidden()
                        expect(page.locator('#mobileInventoryDialog')).to_be_visible()
                        page.locator(f'[data-asset-id="{asset.pk}"]').tap()
                        expect(page.locator('#mobileInventoryDialog')).to_be_hidden()
                        expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                        expect(page.locator('#mobileRequirementsTitle')).to_have_text('Ready to book')
                        expect(page.locator('#mobileEditorGuide')).to_have_class('mobile-editor-guide mobile-editor-only is-ready')
                        expect(page.locator('#mobileChecklistCount')).to_have_text('0')
                        page.locator('#mobileEditItemBtn').tap()
                        expect(page.locator('button[data-edit-section="adjust"]')).to_have_attribute('aria-pressed', 'true')
                        expect(page.locator('button[data-edit-section="text"]')).to_be_hidden()
                        # Every tilt updates the real, unobstructed canvas while
                        # the controls stay open. No Done / Edit cycle is needed.
                        canvas_image = page.locator('#designCanvas').evaluate('(el) => el.toDataURL()')
                        for _ in range(3):
                            page.locator('#skewRightBtn').tap()
                            expect(page.locator('#mobileEditItemDialog')).to_be_visible()
                            updated_image = page.locator('#designCanvas').evaluate('(el) => el.toDataURL()')
                            self.assertNotEqual(updated_image, canvas_image)
                            canvas_image = updated_image
                        page.screenshot(path=str(Path(gettempdir()) / f'balloorina-mobile-tilt-{theme}-{width}.png'), animations='disabled')
                        page.locator('button[data-edit-section="position"]').tap()
                        page.locator('#contextMoveRightBtn').tap()
                        self.assertNotEqual(page.locator('#designCanvas').evaluate('(el) => el.toDataURL()'), canvas_image)
                        if width == 390:
                            page.set_viewport_size({'width': 844, 'height': 430})
                            expect(page.locator('#mobileEditItemDialog')).to_be_visible()
                            stage = page.locator('#canvasDropZone').bounding_box()
                            dock = page.locator('#mobileEditItemDialog').bounding_box()
                            self.assertLessEqual(stage['x'] + stage['width'], dock['x'] + 1)
                            self.assertGreater(stage['height'], 180)
                            self.assertLessEqual(dock['y'] + dock['height'], 431)
                            page.screenshot(path=str(Path(gettempdir()) / f'balloorina-mobile-edit-landscape-{theme}.png'), animations='disabled')
                            page.set_viewport_size({'width': width, 'height': height})
                            page.locator('#mobileEditItemDialog [data-mobile-close]').press('Escape')
                            expect(page.locator('#mobileEditItemDialog')).to_be_hidden()
                            expect(page.locator('#mobileEditItemBtn')).to_be_focused()
                        else:
                            page.locator('#mobileEditItemDialog [data-mobile-close]').tap()
                        expect(page.locator('.canvas-tool-rail')).to_be_visible()
                        page.locator('[data-panel-target="layersPanel"]').tap()
                        rows = page.locator('#layersList .layer-row')
                        expect(rows).to_have_count(2)
                        if theme == 'light' and width == 390:
                            page.screenshot(path=str(Path(gettempdir()) / 'balloorina-mobile-layers.png'), animations='disabled')
                        first_id = rows.first.get_attribute('data-layer-id')
                        rows.first.locator('.mobile-layer-order button').last.tap()
                        expect(rows.last).to_have_attribute('data-layer-id', first_id)
                        expect(page.locator('#mobileInventoryDialog')).to_be_visible()
                        page.locator('#mobileInventoryDialog [data-mobile-close]').tap()
                        page.locator('#mobileChecklistBtn').tap()
                        expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                        page.locator('#mobileChecklistDialog [data-mobile-close]').tap()
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 1)
                        if theme == 'dark' and width == 820:
                            # Save is reachable directly from the live edit view.
                            page.locator('#mobileEditItemBtn').tap()
                            page.locator('#saveDesignBtn').tap()
                            page.locator('#saveDesignNameInput').fill('Mobile birthday design')
                            with page.expect_response(lambda response: response.url.endswith('/my-designs/save/')) as response:
                                page.locator('#saveDesignConfirmBtn').tap()
                            result = response.value.json()
                            self.assertEqual(result['status'], 'success', result)
                            self.assertTrue(result['can_book'], result)
                            saved_id = result['id']
                        context.close()
                # A new device loads the same saved text and design requirements.
                context = browser.new_context(viewport={'width': 390, 'height': 844}, has_touch=True, is_mobile=True)
                context.add_cookies([cookie])
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + reverse('design_canvas') + f'?id={saved_id}', wait_until='domcontentloaded')
                expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                page.set_viewport_size({'width': 1440, 'height': 1000})
                expect(page.locator('body')).not_to_have_class('canvas-mobile-active')
                self.assertEqual(page.locator('#selectionToolbar').evaluate('(el) => el.parentElement.id'), 'canvasDropZone')
                self.assertTrue(page.locator('#canvasSidebar').evaluate('(el) => el.parentElement.classList.contains("design-layout")'))
                page.set_viewport_size({'width': 390, 'height': 844})
                expect(page.locator('body')).to_have_class('canvas-mobile-active')
                self.assertEqual(page.locator('#selectionToolbar').evaluate('(el) => el.parentElement.id'), 'mobileSelectionTools')
                self.assertFalse(errors, errors)
            finally:
                browser.close()
        design = UserDesign.objects.get(pk=saved_id)
        state = json.loads(design.canvas_json)
        self.assertTrue(any(obj.get('text') == "Maria's birthday" for obj in state['objects']))
        panel = next(obj for obj in state['objects'] if str(obj.get('_assetId')) == str(asset.pk))
        self.assertEqual(panel.get('skewX'), 15, panel)
