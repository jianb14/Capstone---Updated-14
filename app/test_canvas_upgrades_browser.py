"""Panel/color upgrade confirmation, compatibility, retries, and unchanged toast motion."""
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
class CanvasUpgradesBrowserTests(StaticLiveServerTestCase):
    def test_panels_colors_only_cancel_retry_save_and_limits(self):
        from playwright.sync_api import sync_playwright, expect

        user = User.objects.create_user(username='upgrade_browser', role='customer')
        self.client.force_login(user)
        panels = CanvasCategory.objects.create(name='Upgrade panels')
        balloons = CanvasCategory.objects.create(name='Upgrade balloons', is_balloon=True)
        chairs = CanvasCategory.objects.create(name='Upgrade chairs')
        panel = CanvasAsset.objects.create(category=panels, label='Panel', static_path='images/canvas/premium/frames/panel_wall.svg')
        balloon = CanvasAsset.objects.create(category=balloons, label='Balloon', static_path='images/canvas/premium/balloons/circle_blank.svg')
        chair = CanvasAsset.objects.create(category=chairs, label='Chair', static_path='images/canvas/premium/frames/panel_wall.svg')
        offers = []
        # The cheapest higher package excludes the existing chair and must be skipped.
        for name, price, maximum, colors, has_chair in [('Package 1-A', 4799, 1, 2, True), ('Incompatible', 5299, 2, 4, False), ('Package 1-B', 5799, 2, 3, True), ('Package 3', 9799, 3, 4, True)]:
            package = Package.objects.create(name=name, price=price)
            offer = DesignOffer.objects.create(kind='package', package=package, is_enabled=True, max_balloon_colors=colors)
            DesignRequirement.objects.create(offer=offer, category=panels, required=True, minimum=maximum, maximum=maximum, display_name='Backdrop panel')
            DesignRequirement.objects.create(offer=offer, category=balloons, required=True, minimum=1)
            if has_chair:
                DesignRequirement.objects.create(offer=offer, category=chairs, required=False, minimum=0, maximum=1, display_name='Chair')
            offers.append(offer)
        base, _, higher, largest = offers
        saved_id = None
        cookie = {'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            errors = []
            try:
                for theme in ('light', 'dark'):
                    for width, height in ((1440, 1000), (820, 1000), (390, 844), (320, 740)):
                        mobile = width <= 1024
                        context = browser.new_context(viewport={'width': width, 'height': height}, has_touch=mobile, is_mobile=mobile)
                        context.add_cookies([cookie])
                        page = context.new_page()
                        page.on('pageerror', lambda error: errors.append(str(error)))

                        def fresh(offer=base):
                            page.goto(self.live_server_url + reverse('design_canvas') + f'?design_offer_id={offer.pk}&fresh=1', wait_until='domcontentloaded')
                            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                            expect(page.locator('#designOverallState')).to_contain_text('0 of 2')

                        def add(asset):
                            tab = page.locator('[data-panel-target="elementsPanel"]')
                            if mobile and not page.locator('#mobileInventoryDialog').evaluate('(el) => el.open'):
                                expect(tab).to_have_attribute('aria-pressed', 'false')
                            if 'active' not in (tab.get_attribute('class') or ''):
                                tab.click()
                            group = page.locator(f'.inventory-category[data-category-id="{asset.category_id}"]')
                            if 'is-open' not in (group.locator('.category-header').get_attribute('class') or ''):
                                group.locator('.category-header').click()
                            previous_count = page.locator('#layersList .layer-row').count()
                            group.locator(f'[data-asset-id="{asset.pk}"]').click()
                            page.wait_for_function('''count => document.querySelectorAll('#layersList .layer-row').length > count ||
                                document.querySelector('#upgradeModal').matches(':popover-open') || document.querySelector('.canvas-toast-container .toast.show')''', arg=previous_count)
                            if mobile and page.locator('#layersList .layer-row').count() > previous_count:
                                expect(page.locator('#mobileInventoryDialog')).to_be_hidden()
                                expect(tab).to_have_attribute('aria-pressed', 'false')

                        def color(value):
                            if mobile:
                                page.locator('#mobileEditItemBtn').click()
                                page.locator('button[data-edit-section="adjust"]').click()
                            page.locator('#itemColorPicker').evaluate('(el, value) => {el.value = value; el.dispatchEvent(new Event("input", {bubbles:true}));}', value)
                            if mobile and page.locator('#mobileEditItemDialog').is_visible():
                                page.locator('#mobileEditItemDialog [data-mobile-close]').click()

                        modal = page.locator('#upgradeModal')
                        fresh()
                        add(chair)
                        add(chair)
                        toast = page.locator('.canvas-toast-container .toast').last
                        expect(toast).to_have_class('toast toast-error show')
                        expect(toast).to_contain_text('Chair')
                        expect(modal).to_be_hidden()
                        self.assertEqual(toast.evaluate('(el) => getComputedStyle(el).transitionDuration'), '0.3s')
                        self.assertEqual(toast.evaluate('(el) => getComputedStyle(el).transitionTimingFunction'), 'cubic-bezier(0.68, -0.55, 0.265, 1.55)')
                        expect(toast).to_have_css('transform', 'matrix(1, 0, 0, 1, 0, 0)')
                        self.assertLessEqual(toast.bounding_box()['x'] + toast.bounding_box()['width'], width)
                        page.screenshot(path=str(Path(gettempdir()) / f'balloorina-limit-{theme}-{width}.png'), animations='disabled')
                        toast.locator('.canvas-toast-close').click()
                        if mobile:
                            expect(page.locator('#mobileInventoryDialog')).to_be_visible()
                            page.locator('#mobileInventoryDialog [data-mobile-close]').click()
                        add(panel)
                        add(panel)
                        expect(modal).to_be_visible()
                        expect(modal.locator('#upgradeDetails')).to_contain_text('Package 1-B')
                        expect(modal.locator('#upgradeDetails')).to_contain_text('\u20b15,799')
                        expect(modal.locator('#upgradeDetails')).not_to_contain_text('Incompatible')
                        page.locator('#cancelUpgradeBtn').click()
                        expect(page.locator('.canvas-toast-container .toast-success')).to_have_count(0)
                        expect(page.locator('#layersList .layer-row')).to_have_count(2)
                        self.assertEqual(page.evaluate('window.designOffer.id'), base.pk)
                        add(panel)
                        page.keyboard.press('Escape')
                        expect(modal).to_be_hidden()
                        # Duplicate is another panel-entry path; confirm retries it once.
                        if mobile:
                            page.locator('#mobileEditItemBtn').click()
                            page.locator('button[data-edit-section="position"]').click()
                        page.locator('#contextDuplicateBtn').click()
                        expect(modal).to_be_visible()
                        page.screenshot(path=str(Path(gettempdir()) / f'balloorina-panel-upgrade-{theme}-{width}.png'), animations='disabled')
                        page.locator('#confirmUpgradeBtn').click()
                        expect(modal).to_be_hidden()
                        expect(page.locator('#layersList .layer-row')).to_have_count(3)
                        success = page.locator('.canvas-toast-container .toast-success').last
                        expect(success).to_have_class('toast toast-success show')
                        expect(success).to_contain_text('Package upgraded')
                        expect(success).to_contain_text('Package 1-B')
                        expect(success).to_contain_text('\u20b15,799')
                        expect(success).to_have_attribute('role', 'status')
                        self.assertEqual(page.evaluate('window.designOffer.id'), higher.pk)
                        self.assertEqual(page.evaluate('String(window.basePackageId)'), str(higher.package_id))
                        expect(page.locator('#cartBaseName')).to_have_text('Package 1-B')
                        expect(page.locator('#cartBasePrice')).to_have_text('\u20b15,799')
                        expect(page.locator(f'#cartInclusionsList [data-category-id="{panels.pk}"]')).to_contain_text('2/2 required')
                        # Reload an unsaved upgrade: the package and design both survive.
                        page.reload(wait_until='domcontentloaded')
                        expect(page.locator('#layersList .layer-row')).to_have_count(3)
                        self.assertEqual(page.evaluate('window.designOffer.id'), higher.pk)

                        fresh()
                        add(chair)
                        add(panel)
                        add(balloon)
                        color('#ff0000')
                        add(balloon)
                        color('#0000ff')
                        add(balloon)
                        color('#00ff00')
                        expect(modal).to_be_visible()
                        expect(page.locator('#upgradeModalTitle')).to_have_text('Need more balloon colors?')
                        expect(page.locator('#upgradeDetails')).to_contain_text('Up to 3 balloon colors')
                        page.locator('#cancelUpgradeBtn').click()
                        self.assertEqual(page.evaluate('window.designOffer.id'), base.pk)
                        color('#00ff00')
                        expect(modal).to_be_visible()
                        page.screenshot(path=str(Path(gettempdir()) / f'balloorina-color-upgrade-{theme}-{width}.png'), animations='disabled')
                        page.locator('#confirmUpgradeBtn').click()
                        self.assertEqual(page.evaluate('window.designOffer.id'), higher.pk)
                        expect(page.locator('.canvas-toast-container .toast-success').last).to_contain_text('Package upgraded')
                        expect(page.locator('#layersList .layer-row')).to_have_count(5)
                        expect(page.locator('#itemColorPicker')).to_have_value('#00ff00')
                        # The new package's higher required minimum takes effect.
                        expect(page.locator(f'#cartInclusionsList [data-category-id="{panels.pk}"]')).to_contain_text('1/2 required')
                        add(panel)
                        expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                        if theme == 'dark' and width == 390:
                            page.locator('#saveDesignBtn').click()
                            page.locator('#saveDesignNameInput').fill('Upgraded design')
                            with page.expect_response(lambda response: response.url.endswith('/my-designs/save/')) as response:
                                page.locator('#saveDesignConfirmBtn').click()
                            result = response.value.json()
                            self.assertTrue(result.get('can_book'), result)
                            saved_id = result['id']
                        fresh(largest)
                        for _ in range(3):
                            add(panel)
                        add(panel)
                        expect(modal).to_be_hidden()
                        toast = page.locator('.canvas-toast-container .toast').last
                        expect(toast).to_contain_text('No compatible higher package')
                        expect(page.locator('#layersList .layer-row')).to_have_count(3)
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 1)
                        context.close()
                self.assertFalse(errors, errors)
            finally:
                browser.close()
        design = UserDesign.objects.get(pk=saved_id)
        self.assertEqual(design.design_offer_id, higher.pk)
        self.assertEqual(design.base_package_id, higher.package_id)
        state = json.loads(design.canvas_json)
        colored = [obj for obj in state['objects'] if str(obj.get('_assetId')) == str(balloon.pk)]
        self.assertEqual({obj.get('_currentColor') for obj in colored}, {'#ff0000', '#0000ff', '#00ff00'})
