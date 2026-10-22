"""Optional real-browser regression checks for the outline canvas toolbars."""
import os
from pathlib import Path
from tempfile import gettempdir
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import CanvasAsset, CanvasCategory, DesignOffer, DesignRequirement, Package, User


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class CanvasToolbarsBrowserTests(StaticLiveServerTestCase):
    def test_outline_icons_text_state_and_object_controls_across_themes_and_sizes(self):
        from playwright.sync_api import sync_playwright, expect

        user = User.objects.create_user(username='toolbar_browser', role='customer')
        self.client.force_login(user)
        category = CanvasCategory.objects.create(name='Toolbar panels')
        asset = CanvasAsset.objects.create(category=category, label='Toolbar panel', static_path='images/canvas/premium/frames/panel_wall.svg')
        package = Package.objects.create(name='Toolbar package', price=4799)
        offer = DesignOffer.objects.create(kind='package', package=package, is_enabled=True)
        DesignRequirement.objects.create(offer=offer, category=category, required=True, minimum=1, maximum=2)
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
                    # Touch layouts have a separate, labelled-sheet workflow.
                    for width, height in ((1440, 1000), (1180, 1000)):
                        page.set_viewport_size({'width': width, 'height': height})
                        page.goto(self.live_server_url + reverse('design_canvas') + f'?design_offer_id={offer.pk}&fresh=1', wait_until='domcontentloaded')
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        expect(page.locator('#designOverallState')).to_contain_text('0 of 1')
                        if page.locator('#summaryFloatBtn').get_attribute('aria-expanded') == 'true':
                            page.locator('#summaryFloatBtn').click()
                        page.locator('[data-panel-target="textPanel"]').click()
                        page.locator('.text-preset-card[title="Add a Heading"]').press('Enter')
                        toolbar = page.locator('#selectionToolbar')
                        expect(toolbar).to_have_attribute('data-selection-type', 'text')
                        for sidebar_open in (True, False):
                            if not sidebar_open:
                                page.locator('[data-panel-target="textPanel"]').click()
                            self.assertTrue(toolbar.evaluate('''el => {
                                const rect = el.getBoundingClientRect();
                                const canvas = el.parentElement.getBoundingClientRect();
                                return rect.left >= canvas.left && rect.right <= canvas.right &&
                                    getComputedStyle(el).overflowX === 'auto';
                            }'''))
                            self.assertEqual(toolbar.locator('[data-toolbar-group="arrange"]').evaluate('(el) => getComputedStyle(el).borderRightWidth'), '0px')
                            expect(toolbar.locator('[data-toolbar-group="transform"]')).to_be_hidden()
                            toolbar.evaluate('(el) => el.scrollLeft = el.scrollWidth')
                            self.assertTrue(page.locator('#toBackBtn').evaluate('''el => {
                                const rect = el.getBoundingClientRect();
                                const toolbar = el.closest('.selection-toolbar').getBoundingClientRect();
                                return rect.left >= toolbar.left && rect.right <= toolbar.right;
                            }'''))
                        for selector in ('.canvas-main-toolbar', '#selectionToolbar', '#objectContextToolbar'):
                            toolbar = page.locator(selector)
                            expect(toolbar).to_be_visible()
                            expect(toolbar.locator('i')).to_have_count(0)
                            self.assertTrue(toolbar.locator('svg').evaluate_all('''icons => icons.every(icon =>
                                icon.getAttribute('fill') === 'none' && icon.getAttribute('stroke-width') === '1.6' &&
                                document.querySelector(icon.querySelector('use').getAttribute('href')))
                            '''))
                        for selector in ('#canvasSizeDisp', '#zoomLabel', '#fontSizeInput', '.dimension-toolbar-group label', '#fontFamilyDropdown .dropdown-trigger'):
                            self.assertEqual(page.locator(selector).first.evaluate('(el) => getComputedStyle(el).fontWeight'), '500')
                        expect(page.locator('#saveDesignBtn svg use')).to_have_attribute('href', '#ci-save')
                        expect(page.locator('#textBoldBtn')).to_have_attribute('aria-pressed', 'true')
                        page.locator('#textBoldBtn').click()
                        expect(page.locator('#textBoldBtn')).to_have_attribute('aria-pressed', 'false')
                        page.locator('#textItalicBtn').click()
                        expect(page.locator('#textItalicBtn')).to_have_attribute('aria-pressed', 'true')
                        page.locator('#textUnderlineBtn').click()
                        expect(page.locator('#textUnderlineBtn')).to_have_attribute('aria-pressed', 'true')
                        page.locator('#textAlignCenterBtn').click()
                        expect(page.locator('#textAlignCenterBtn')).to_have_attribute('aria-pressed', 'true')
                        page.locator('#fontFamilyDropdown .dropdown-trigger').click()
                        expect(page.locator('#fontFamilyOptions')).to_have_js_property('popover', 'manual')
                        expect(page.locator('#fontFamilyOptions:popover-open')).to_be_visible()
                        self.assertTrue(page.locator('#fontFamilyOptions').evaluate('''el => {
                            const rect = el.getBoundingClientRect();
                            return rect.left >= 0 && rect.right <= innerWidth && rect.top >= 0 && rect.bottom <= innerHeight;
                        }'''))
                        # Choose a real font from the menu while the row remains clipped.
                        page.locator('#fontFamilyOptions li[data-value="Montserrat"]').click()
                        expect(page.locator('#fontFamilySelect')).to_have_value('Montserrat')
                        expect(page.locator('#fontFamilyOptions:popover-open')).to_have_count(0)
                        page.keyboard.press('Escape')
                        page.locator('#contextLockBtn').click()
                        expect(page.locator('#contextLockBtn svg use')).to_have_attribute('href', '#ci-lock')
                        expect(page.locator('#contextLockBtn')).to_have_attribute('aria-label', 'Unlock selection')
                        expect(page.locator('#contextMoveUpBtn')).to_be_disabled()
                        page.locator('#contextLockBtn').click()
                        expect(page.locator('#contextLockBtn svg use')).to_have_attribute('href', '#ci-unlock')
                        expect(page.locator('#contextMoveUpBtn')).to_be_enabled()
                        page.screenshot(path=str(Path(gettempdir()) / f'balloorina-toolbars-text-{theme}-{width}.png'), animations='disabled')
                        page.locator('#contextDuplicateBtn').click()
                        expect(page.locator('.layer-row')).to_have_count(2)
                        page.locator('#undoBtn').click()
                        expect(page.locator('.layer-row')).to_have_count(1)
                        page.locator('[data-panel-target="elementsPanel"]').click()
                        page.locator(f'[data-asset-id="{asset.pk}"]').click()
                        page.locator('[data-panel-target="elementsPanel"]').click()
                        expect(page.locator('#selectionToolbar')).to_have_attribute('data-selection-type', 'object')
                        for button, icon in (('layerForwardBtn', 'layer-forward'), ('layerBackwardBtn', 'layer-backward'), ('toFrontBtn', 'layer-front'), ('toBackBtn', 'layer-back'), ('flipXBtn', 'flip-horizontal'), ('flipYBtn', 'flip-vertical'), ('skewLeftBtn', 'skew-left'), ('skewRightBtn', 'skew-right')):
                            expect(page.locator(f'#{button}')).to_be_visible()
                            expect(page.locator(f'#{button} svg use')).to_have_attribute('href', f'#ci-{icon}')
                        page.locator('#flipXBtn').click()
                        page.locator('#skewRightBtn').click()
                        expect(page.locator('#undoBtn')).to_be_enabled()
                        page.screenshot(path=str(Path(gettempdir()) / f'balloorina-toolbars-object-{theme}-{width}.png'), animations='disabled')
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 1)
                        expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                self.assertFalse(errors, errors)
            finally:
                browser.close()
