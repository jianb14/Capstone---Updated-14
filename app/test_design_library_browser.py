"""Optional library browser verification in isolated SQLite: RUN_DESIGN_BROWSER=1."""
import io
import json
import os
from pathlib import Path
from tempfile import gettempdir
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.base import ContentFile
from django.urls import reverse
from PIL import Image

from .design_validation import asset_payload
from .models import CanvasAsset, CanvasCategory, DesignOffer, DesignRequirement, Package, User, UserDesign


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
class DesignLibraryBrowserTests(StaticLiveServerTestCase):
    def test_library_and_offer_dialog_in_both_themes_and_three_screen_sizes(self):
        from playwright.sync_api import sync_playwright, expect

        user = User.objects.create_user(username='library_browser', role='customer')
        self.client.force_login(user)
        category = CanvasCategory.objects.create(name='Library browser panels')
        asset = CanvasAsset.objects.create(category=category, label='Panel', static_path='images/test.svg')
        package = Package.objects.create(name='Package 1-A', price=4799, features='2 Panels\nBalloons (max 2 colors)\nSetup and delivery')
        offer = DesignOffer.objects.create(kind='package', package=package, is_enabled=True, max_balloon_colors=2)
        DesignRequirement.objects.create(offer=offer, category=category, required=True, minimum=2, maximum=2)
        for index in range(3):
            extra_package = Package.objects.create(name=f'Package {index + 2}', price=5799 + index * 1000, features='2 Panels')
            extra_offer = DesignOffer.objects.create(kind='package', package=extra_package, is_enabled=True)
            DesignRequirement.objects.create(offer=extra_offer, category=category, required=True, minimum=2, maximum=2)
        payload = asset_payload(asset)
        obj = {'type': 'image', 'src': payload['src'], '_assetId': asset.pk, '_assetToken': payload['token']}
        ready = UserDesign.objects.create(user=user, name='Complete design', design_offer=offer, canvas_json=json.dumps({'objects': [obj, obj]}))
        draft = UserDesign.objects.create(user=user, name='My draft', design_offer=offer, canvas_json='{"objects": []}')
        output = io.BytesIO()
        Image.new('RGB', (3840, 2160), '#eeeeee').save(output, 'PNG')
        ready.thumbnail.save('browser-large.png', ContentFile(output.getvalue()))
        draft.thumbnail.save('browser-draft.png', ContentFile(output.getvalue()))
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
                        page.goto(self.live_server_url + reverse('my_designs'), wait_until='domcontentloaded')
                        page.evaluate('(theme) => {document.documentElement.dataset.theme = theme; localStorage.setItem("balloorina-theme", theme)}', theme)
                        draft_card = page.locator('.design-card').filter(has=page.locator('.design-draft'))
                        ready_card = page.locator('.design-card').filter(has=page.locator('.design-ready'))
                        expect(draft_card).to_contain_text('Add 2 more: Library browser panels')
                        expect(ready_card).to_contain_text('Your design is ready to book.')
                        self.assertEqual(ready_card.locator('.book-btn').evaluate('(el) => getComputedStyle(el).whiteSpace'), 'nowrap')
                        expect(draft_card.locator('.design-package-badge')).to_have_text('Package 1-A')
                        expect(draft_card.locator('.book-btn')).to_have_count(0)
                        action_width = draft_card.locator('.design-actions').bounding_box()['width']
                        self.assertAlmostEqual(draft_card.locator('.edit-btn').bounding_box()['width'], action_width, delta=1)
                        image = page.locator('.design-thumbnail').first
                        image.scroll_into_view_if_needed()
                        page.wait_for_function('document.querySelector(".design-thumbnail").naturalWidth > 0')
                        self.assertEqual(image.evaluate('(el) => el.naturalWidth'), 640)
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 1, (theme, width))
                        self.assertEqual(page.locator('.modal-overlay').first.evaluate('(el) => getComputedStyle(el).display'), 'none')
                        self.assertEqual(draft_card.locator('.design-package-badge').evaluate('(el) => getComputedStyle(el).backdropFilter'), 'none')
                        page.locator('.create-new-btn').click()
                        parent = page.locator('#selectPackageModal')
                        self.assertGreater(int(parent.evaluate('(el) => getComputedStyle(el).zIndex')), 10000)
                        tabs = parent.locator('[role="tab"]')
                        self.assertEqual(tabs.first.evaluate('(el) => getComputedStyle(el).backgroundColor'), 'rgba(0, 0, 0, 0)')
                        tabs.first.focus()
                        page.keyboard.press('ArrowRight')
                        expect(parent.locator('[data-design-tab="entrance"]')).to_be_focused()
                        expect(parent.locator('[data-design-panel="package"]')).to_be_hidden()
                        page.keyboard.press('Home')
                        page.screenshot(path=str(Path(gettempdir()) / f'balloorina-library-picker-{theme}-{width}.png'))
                        card = parent.locator('.pkg-card').first
                        before = card.bounding_box()['height']
                        card.locator('[data-offer-open]').click()
                        dialog = page.locator('#designOfferDetailsModal')
                        expect(dialog).to_be_visible()
                        expect(dialog).to_contain_text('2 required')
                        expect(dialog).to_contain_text('Maximum balloon colors: 2')
                        expect(dialog).to_contain_text('Uploaded photos are references')
                        expect(dialog).to_contain_text('You can save a draft anytime.')
                        expect(dialog.locator('.feature-modal-btn')).to_have_attribute('href', reverse('design_canvas') + f'?design_offer_id={offer.pk}&fresh=1')
                        self.assertAlmostEqual(card.bounding_box()['height'], before, delta=1)
                        self.assertLessEqual(dialog.evaluate('(el) => el.scrollWidth - el.clientWidth'), 1)
                        self.assertEqual(dialog.locator('.dl-detail-columns > section').first.evaluate('(el) => getComputedStyle(el).paddingTop'), '0px')
                        page.screenshot(path=str(Path(gettempdir()) / f'balloorina-library-modal-{theme}-{width}.png'))
                        page.keyboard.press('Escape')
                        expect(dialog).to_be_hidden()
                        expect(card.locator('[data-offer-open]')).to_be_focused()
                        expect(parent).to_be_visible()
                        self.assertTrue(page.evaluate('document.documentElement.classList.contains("design-modal-open")'))
                        card.locator('[data-offer-open]').click()
                        dialog.locator('.dl-back-btn').click()
                        expect(dialog).to_be_hidden()
                        page.keyboard.press('Escape')
                        expect(parent).to_be_hidden()
                        expect(page.locator('.create-new-btn')).to_be_focused()
                        self.assertFalse(page.evaluate('document.documentElement.classList.contains("design-modal-open")'))
                        page.screenshot(path=str(Path(gettempdir()) / f'balloorina-library-{theme}-{width}.png'), full_page=True)
                # The standalone entry point uses the same picker and dialog.
                page.goto(self.live_server_url + reverse('select_design_type') + f'?design_id={draft.pk}', wait_until='domcontentloaded')
                page.locator('[data-offer-open]').first.click()
                expect(page.locator('#designOfferDetailsModal .feature-modal-btn')).to_have_attribute('href', reverse('design_canvas') + f'?design_offer_id={offer.pk}&id={draft.pk}')
                page.keyboard.press('Escape')
                self.assertFalse(page.evaluate('document.documentElement.classList.contains("design-modal-open")'))
                self.assertFalse(errors, errors)
            finally:
                browser.close()
