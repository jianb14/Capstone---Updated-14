"""Optional browser coverage for summary layout and live required/optional progress."""
import json
import os
from pathlib import Path
from tempfile import gettempdir
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse

from .design_validation import asset_payload
from .models import CanvasAsset, CanvasCategory, DesignOffer, DesignRequirement, Package, User, UserDesign


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
class DesignSummaryBrowserTests(StaticLiveServerTestCase):
    def test_stacked_summary_progress_optional_items_and_validation(self):
        from playwright.sync_api import sync_playwright, expect

        user = User.objects.create_user(username='summary_browser', role='customer')
        self.client.force_login(user)
        package = Package.objects.create(name='Package 4 with a longer offer name', price=12899)
        offer = DesignOffer.objects.create(kind='package', package=package, is_enabled=True, max_balloon_colors=2)
        assets = []
        for name, minimum, maximum, balloon in (
            ('Panels and decorative backdrop structures', 2, 2, False),
            ('Balloons', 1, None, True),
            ('Celebrant chair', 1, 2, False),
            ('Styrofoam celebrant name', 0, 1, False),
            ('Drop lights', 0, 1, False),
            ('Additional floral arrangements', 0, None, False),
        ):
            category, _ = CanvasCategory.objects.get_or_create(name=name, defaults={'is_balloon': balloon})
            asset = CanvasAsset.objects.create(category=category, label=name, static_path='images/canvas/premium/frames/panel_wall.svg')
            assets.append(asset)
            DesignRequirement.objects.create(offer=offer, category=category, required=minimum > 0, minimum=minimum, maximum=maximum)
        payload = asset_payload(assets[0])
        obj = {'type': 'image', 'src': payload['src'], '_assetId': assets[0].pk, '_assetToken': payload['token'], '_assetSource': payload['src'], '_designSource': 'catalog', 'left': 50, 'top': 50, 'width': 100, 'height': 150}
        invalid = UserDesign.objects.create(user=user, name='Over allowance', design_offer=offer, canvas_json=json.dumps({'version': '5.3.1', 'objects': [obj] * 3}))

        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            context = browser.new_context()
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def open_summary():
                button = page.locator('#summaryFloatBtn')
                if button.get_attribute('aria-expanded') != 'true':
                    page.locator('#mobileChecklistBtn' if page.viewport_size['width'] <= 1024 else '#summaryFloatBtn').click()

            def close_summary():
                if page.viewport_size['width'] <= 1024:
                    page.locator('#mobileChecklistDialog [data-mobile-close]').click()
                else:
                    page.locator('#summaryFloatBtn').click()

            def add(asset):
                tab = page.locator('[data-panel-target="elementsPanel"]')
                if 'active' not in (tab.get_attribute('class') or ''):
                    tab.click()
                group = page.locator(f'.inventory-category[data-category-id="{asset.category_id}"]')
                if 'is-open' not in (group.locator('.category-header').get_attribute('class') or ''):
                    group.locator('.category-header').click()
                group.locator(f'[data-asset-id="{asset.pk}"]').click()

            try:
                for theme in ('light', 'dark'):
                    for width, height in ((1440, 1000), (820, 1000), (390, 844)):
                        page.set_viewport_size({'width': width, 'height': height})
                        page.goto(self.live_server_url + reverse('design_canvas') + f'?design_offer_id={offer.pk}&fresh=1', wait_until='domcontentloaded')
                        page.evaluate('(theme) => {document.documentElement.dataset.theme = theme; localStorage.setItem("balloorina-theme", theme)}', theme)
                        expect(page.locator('#designOverallState')).to_contain_text('0 of 3 requirements complete')
                        open_summary()
                        panel = page.locator('#summaryFloatPanel')
                        expect(page.locator('#cartBasePrice')).to_have_text('\u20b112,899')
                        expect(page.locator('#cartInclusionsList > li')).to_have_count(3)
                        expect(page.locator('#cartOptionalList')).to_be_visible()
                        expect(page.locator('#cartOptionalList')).to_contain_text('Optional inclusion')
                        expect(page.locator('#cartInclusionsList')).to_contain_text('Add 2 more to complete')
                        expect(page.locator('#cartInclusionsList')).not_to_contain_text('Kulang')
                        close_summary()
                        expect(page.locator('#summaryFloatBtn')).to_have_attribute('aria-expanded', 'false')
                        if width > 1024:
                            expect(page.locator('#summaryFloatBtn .btn-icon')).to_have_css('transform', 'matrix(1, 0, 0, 1, 0, 0)')
                        open_summary()
                        if width > 1024:
                            expect(page.locator('#summaryFloatBtn .btn-icon')).to_have_css('transform', 'matrix(-1, 0, 0, -1, 0, 0)')
                        for index, row in enumerate(page.locator('#cartInclusionsList > li').all()):
                            page.evaluate('''index => document.querySelectorAll('#cartInclusionsList > li')[index].scrollIntoView({block: 'nearest', behavior: 'instant'})''', index)
                            expect(row.locator('.design-row-name')).to_be_visible()
                            # Server eligibility updates replace these rows. Read the current
                            # layout atomically instead of holding three detached node handles.
                            metrics = page.evaluate('''index => {
                                const row = document.querySelectorAll('#cartInclusionsList > li')[index];
                                const rect = selector => {
                                    const box = row.querySelector(selector).getBoundingClientRect();
                                    return {y: box.top, height: box.height, width: box.width};
                                };
                                return {heading: rect('.design-row-name'), detail: rect('.design-row-detail'), button: rect('.design-add-missing')};
                            }''', index)
                            heading, detail, button = metrics['heading'], metrics['detail'], metrics['button']
                            self.assertGreater(heading['height'], 0)
                            self.assertGreaterEqual(detail['y'], heading['y'] + heading['height'])
                            self.assertGreaterEqual(button['y'], detail['y'] + detail['height'])
                            self.assertAlmostEqual(button['width'], heading['width'], delta=1)
                            self.assertLessEqual(row.evaluate('(el) => el.scrollWidth - el.clientWidth'), 1)
                        self.assertLessEqual(panel.evaluate('(el) => el.scrollWidth - el.clientWidth'), 1)
                        panel.screenshot(path=str(Path(gettempdir()) / f'balloorina-summary-{theme}-{width}.png'), animations='disabled')
                        expect(page.locator('#cartOptionalList')).to_be_visible()
                        expect(page.locator('#cartOptionalList > li')).to_have_count(3)
                        # Required and optional rows remain separate after navigation to assets.
                        page.locator('#cartInclusionsList .design-add-missing').first.click()
                        expect(page.locator(f'.inventory-category[data-category-id="{assets[0].category_id}"] .category-header')).to_have_class('category-header is-open')
                        if width <= 1024:
                            expect(page.locator('#summaryFloatBtn')).to_have_attribute('aria-expanded', 'false')

                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.goto(self.live_server_url + reverse('design_canvas') + f'?design_offer_id={offer.pk}&fresh=1', wait_until='domcontentloaded')
                expect(page.locator('#designOverallState')).to_contain_text('0 of 3')
                add(assets[0])
                page.keyboard.press('Control+d')
                add(assets[1])
                add(assets[2])
                expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                expect(page.locator('#designOverallState progress')).to_have_attribute('value', '3')
                expect(page.locator('#cartInclusionsList .is-complete')).to_have_count(3)
                expect(page.locator('#cartInclusionsList')).to_contain_text('1/1 required')
                expect(page.locator('#cartInclusionsList')).to_contain_text('1/2 included')
                expect(page.locator('#cartInclusionsList')).to_contain_text('Up to 2 balloon colors')
                with page.expect_response(lambda response: response.url.endswith('/my-designs/evaluate/')):
                    add(assets[3])
                expect(page.locator('#cartOptionalList .is-complete')).to_have_count(1)
                expect(page.locator('#cartOptionalList .is-complete .design-row-name')).to_have_css('color', 'rgb(134, 216, 168)')
                expect(page.locator('#cartOptionalList')).to_be_visible()
                page.locator('#undoBtn').click()
                expect(page.locator('#cartOptionalList .is-complete')).to_have_count(0)
                expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                page.goto(self.live_server_url + reverse('design_canvas') + f'?id={invalid.pk}', wait_until='domcontentloaded')
                expect(page.locator('#designOverallState')).to_contain_text('Needs review')
                expect(page.locator('#designReviewItems')).to_be_visible()
                expect(page.locator('#designReviewList')).to_contain_text('maximum 2, currently 3')
                expect(page.locator('#cartInclusionsList .is-invalid')).to_have_count(1)
                page.set_viewport_size({'width': 390, 'height': 844})
                expect(page.locator('#mobileRequirementsTitle')).to_have_text('Review items before booking')
                expect(page.locator('#mobileEditorGuide')).not_to_have_class('mobile-editor-guide mobile-editor-only is-ready')
                page.locator('#mobileRequiredItemsBtn').click()
                expect(page.locator('#mobileChecklistDialog')).to_be_visible()
                expect(page.locator('#designReviewList')).to_contain_text('maximum 2, currently 3')
                self.assertFalse(errors, errors)
            finally:
                browser.close()
