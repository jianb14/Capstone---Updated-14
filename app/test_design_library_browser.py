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
    def test_search_clear_sort_pagination_menu_and_rename(self):
        from playwright.sync_api import sync_playwright, expect

        user = User.objects.create_user(username='library-controls', role='customer', email_verified=True)
        self.client.force_login(user)
        package = Package.objects.create(name='Birthday Package Gold',price=5000)
        for index in range(9):
            UserDesign.objects.create(user=user, name=f'Design {index:02}', base_package=package if index == 8 else None, canvas_json='{"objects": []}')
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            context = browser.new_context(reduced_motion='reduce')
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + '/') else route.abort())
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME, 'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url':self.live_server_url}])
            page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                for theme in ('light','dark'):
                    for width in (1440,390):
                        page.set_viewport_size({'width':width,'height':900})
                        page.goto(self.live_server_url + reverse('my_designs') + '?sort=name&per_page=4', wait_until='domcontentloaded')
                        page.evaluate('window.libraryDocument="preserved"')
                        page.evaluate('(theme)=>{document.documentElement.dataset.theme=theme;localStorage.setItem("balloorina-theme",theme)}', theme)
                        expect(page.locator('.design-card')).to_have_count(4)
                        expect(page.locator('.account-table-summary')).to_contain_text('of 9')
                        expect(page.get_by_role('button', name='Clear design search')).to_be_hidden()
                        search = page.get_by_role('searchbox', name='Search designs')
                        search.fill('Birthday Gold')
                        expect(page.locator('.design-card')).to_have_count(1)
                        expect(page.locator('.design-package-badge')).to_have_text('Birthday Package Gold')
                        search.fill('Design 08')
                        expect(page.get_by_role('button', name='Clear design search')).to_be_visible()
                        expect(page.locator('#designLibraryResults[aria-busy]')).to_have_count(0)
                        expect(page.locator('.design-card')).to_have_count(1)
                        expect(search).to_be_focused()
                        search.fill('no matching setup')
                        expect(page.get_by_text('No matching designs',exact=True)).to_be_visible()
                        page.locator('[data-clear-design-search]').click()
                        expect(page.locator('.design-card')).to_have_count(4)
                        search.fill('Design 08')
                        expect(page.locator('.design-card')).to_have_count(1)
                        page.get_by_role('button', name='Clear design search').click()
                        expect(page.locator('.design-card')).to_have_count(4)
                        if theme == 'light' and width == 1440:
                            page.route('**/my-designs/?**q=broken**',lambda route:route.fulfill(status=503,body='Unavailable'),times=1)
                            search.fill('broken')
                            expect(page.locator('#designSearchStatus')).to_contain_text('Your previous results are still here')
                            expect(page.locator('.design-card')).to_have_count(4)
                            page.locator('#designSearchStatus').get_by_role('button',name='Try again').click()
                            expect(page.get_by_text('No matching designs',exact=True)).to_be_visible()
                            page.locator('[data-clear-design-search]').click()
                            expect(page.locator('.design-card')).to_have_count(4)
                        expect(page.get_by_role('button', name='Sort designs: Name A-Z')).to_be_visible()
                        solid = 'rgb(255, 255, 255)' if theme == 'light' else 'rgb(22, 22, 22)'
                        sort_button = page.get_by_role('button', name='Sort designs: Name A-Z')
                        sort_button.hover(); expect(sort_button).to_have_css('background-color',solid)
                        size_button = page.get_by_role('button',name='Rows per page: 4')
                        size_button.hover(); expect(size_button).to_have_css('background-color',solid)
                        expect(page.locator('.design-stat-card svg,.design-stat-card p')).to_have_count(0)
                        expect(page.locator('.design-stat-label')).to_have_count(3)
                        expect(page.locator('.design-stat-value')).to_have_count(3)
                        expect(page.locator('#designSearchStatus')).to_be_hidden()
                        dots = page.locator('.menu-dots-btn').first
                        dots.click()
                        menu = page.get_by_role('menu', name='Design actions')
                        expect(menu).to_be_visible()
                        expect(menu.get_by_role('menuitem', name='Rename', exact=True)).to_be_focused()
                        page.keyboard.press('Escape'); expect(menu).to_be_hidden(); expect(dots).to_be_focused()
                        dots.click(); menu.get_by_role('menuitem', name='Rename', exact=True).click()
                        modal = page.locator('#renameModal')
                        expect(modal).to_be_visible()
                        name = page.locator('#renameInput')
                        expect(name).to_be_focused()
                        name.fill('   '); page.get_by_role('button', name='Save Name', exact=True).click()
                        expect(page.locator('#renameNameError')).to_have_text('Please enter a design name.')
                        expect(name).to_have_attribute('aria-invalid','true')
                        new_name = f'Renamed {theme} {width}'
                        name.fill(new_name); expect(page.locator('#renameNameError')).to_be_hidden()
                        page.screenshot(path=str(artifacts / f'design-rename-{theme}-{width}.png'))
                        page.get_by_role('button', name='Save Name', exact=True).click()
                        expect(modal).not_to_be_visible()
                        expect(page.locator('.design-title').first).to_have_text(new_name)
                        dots.click(); menu.get_by_role('menuitem', name='Rename', exact=True).click()
                        expect(name).to_have_value(new_name)
                        page.get_by_role('button', name='Close rename design', exact=True).click()
                        expect(dots).to_be_focused()
                        page.get_by_role('button', name='Sort designs: Name A-Z').click()
                        page.get_by_role('option', name='Oldest First', exact=True).click()
                        expect(page.locator('#designLibraryResults[aria-busy]')).to_have_count(0)
                        expect(page.get_by_role('button', name='Sort designs: Oldest First')).to_be_visible()
                        page.get_by_role('button', name='Rows per page: 4').click()
                        page.get_by_role('option', name='8', exact=True).click()
                        expect(page.locator('.design-card')).to_have_count(8)
                        page.get_by_role('link', name='Next page', exact=True).click()
                        expect(page.locator('.design-card')).to_have_count(1)
                        expect(page.get_by_role('button', name='Sort designs: Oldest First')).to_be_visible()
                        expect(page.get_by_role('button', name='Rows per page: 8')).to_be_visible()
                        self.assertEqual(page.evaluate('window.libraryDocument'),'preserved')
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
                        page.screenshot(path=str(artifacts / f'design-library-controls-{theme}-{width}.png'), full_page=True)
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()

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
                        card.hover()
                        expect(card).to_have_css('border-color','rgb(206, 206, 206)' if theme == 'light' else 'rgb(74, 74, 74)')
                        expect(card).to_have_css('background-color','rgb(245, 245, 245)' if theme == 'light' else 'rgb(27, 27, 27)')
                        expect(card).to_have_css('border-radius','14px')
                        button = card.locator('[data-offer-open]')
                        button.hover()
                        expect(button).to_have_css('border-radius','10px')
                        expect(button).to_have_css('background-color','rgb(48, 48, 48)' if theme == 'light' else 'rgb(228, 228, 231)')
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
