"""Optional admin editor browser checks with RUN_DESIGN_BROWSER=1 and Playwright."""
import io
import os
import base64
from pathlib import Path
from tempfile import gettempdir
from unittest import skipUnless

from PIL import Image
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse

from .models import User, Package, AddOn, AdditionalOnly, CanvasCategory, CanvasAsset, DesignOffer
from .offer_inclusions import store_inclusions


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright browser verification')
class OfferEditorBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='browser_offer_admin', role='admin')
        self.client.force_login(self.admin)
        self.panels = CanvasCategory.objects.create(name='Browser panels', available_entrance=True, available_stand=True)
        self.balloons = CanvasCategory.objects.create(name='Browser balloons', is_balloon=True, available_entrance=True, available_stand=True)
        for category in (self.panels, self.balloons):
            CanvasAsset.objects.create(category=category, label=category.name, static_path='images/canvas/premium/frames/panel_wall.svg', available_entrance=True, available_stand=True)
        self.offers = []
        for kind, model, endpoint in [('package', Package, 'package'), ('entrance', AddOn, 'addon'), ('stand', AdditionalOnly, 'additional')]:
            kwargs = {'name': 'Browser ' + kind, 'price': 5000, 'features': ''}
            if kind == 'entrance': kwargs['solo_price'] = 7500
            item = model.objects.create(**kwargs)
            offer = DesignOffer.objects.create(kind=kind, **{kind: item})
            store_inclusions(offer, [
                {'row_type': 'item', 'name': 'Panels', 'quantity': 2, 'category_id': self.panels.pk, 'required_minimum': 2, 'order': 0},
                {'row_type': 'item', 'name': 'Balloons', 'quantity': None, 'category_id': self.balloons.pk, 'required_minimum': 1, 'order': 1},
                {'row_type': 'service', 'name': 'Setup and delivery', 'quantity': None, 'category_id': None, 'required_minimum': 0, 'order': 2},
            ], 2, False)
            self.offers.append((offer, endpoint))

    def launch(self, playwright):
        executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
        browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
        return browser, context

    def test_six_forms_in_both_themes_at_desktop_tablet_and_mobile_sizes(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser, context = self.launch(playwright)
            try:
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                urls = []
                for offer, endpoint in self.offers:
                    urls.extend([(reverse('admin_' + endpoint + '_create'), False), (reverse('admin_' + endpoint + '_edit', args=[offer.item.pk]), True)])
                for theme in ('dark', 'light'):
                    for width, height in ((1440, 1000), (1024, 900), (390, 844)):
                        page.set_viewport_size({'width': width, 'height': height})
                        for url, editing in urls:
                            page.goto(self.live_server_url + url, wait_until='domcontentloaded')
                            page.evaluate('(theme) => {localStorage.setItem("balloorina-theme", theme); if (theme === "light") document.documentElement.dataset.theme = "light"; else document.documentElement.removeAttribute("data-theme");}', theme)
                            expect(page.locator('#addCanvasItem')).to_be_visible()
                            expect(page.locator('textarea[name="features"]')).to_have_count(0)
                            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 1, (theme, width, url))
                            colors = page.locator('#id_name').evaluate('(el) => {const s = getComputedStyle(el); return [s.backgroundColor,s.color]}')
                            self.assertNotEqual(colors[0], colors[1], (theme, width, colors))
                            if editing:
                                expect(page.locator('.oe-inclusion-row')).to_have_count(3)
                                expect(page.locator('#balloonSettings')).to_be_visible()
                                checkbox = page.locator('[data-row-required]').first
                                expected_background = 'rgb(244, 244, 244)' if theme == 'dark' else 'rgb(23, 23, 23)'
                                self.assertEqual(checkbox.evaluate('(el) => getComputedStyle(el).backgroundColor'), expected_background)
                                page.locator('.oe-row-name input').first.focus()
                                page.keyboard.press('Tab')
                                expect(checkbox).to_be_focused()
                                self.assertEqual(checkbox.evaluate('(el) => getComputedStyle(el).outlineStyle'), 'solid', (theme, width, url))
                                first_row = page.locator('.oe-inclusion-row').first
                                first_row.locator('.oe-design-settings summary').click()
                                first_row.locator('[data-category-trigger]').click()
                                expect(first_row.locator('[data-category-options]')).to_be_visible()
                                first_row.locator('[data-category-trigger]').press('Escape')
                                first_row.locator('.oe-design-settings summary').click()
                            else:
                                expect(page.locator('#balloonSettings')).to_be_hidden()
                            if editing and url.endswith(f'packages/{self.offers[0][0].item.pk}/edit/') and width in (1440, 390):
                                path = Path(gettempdir()) / f'balloorina-offer-{theme}-{width}.png'
                                page.screenshot(path=str(path), full_page=True, animations="disabled")
                self.assertFalse(errors, errors)
            finally:
                browser.close()

    def test_inclusions_live_preview_file_browse_drop_and_validation_recovery(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser, context = self.launch(playwright)
            try:
                page = context.new_page()
                page.goto(self.live_server_url + reverse('admin_package_create'), wait_until='domcontentloaded')
                page.set_viewport_size({'width': 390, 'height': 844})
                page.locator('#id_name').fill('New monochrome package')
                page.locator('#id_price').fill('6000')
                page.locator('#addCanvasItem').click()
                page.locator('#categorySearch').fill('panels')
                page.locator('.oe-category-option').filter(has_text='Browser panels').click()
                row = page.locator('.oe-inclusion-row').first
                row.locator('[data-row-field="quantity"]').fill('2')
                row.locator('[data-row-required]').check()
                row.locator('.oe-design-settings summary').click()
                expect(row.locator('[data-row-field="required_minimum"]')).to_have_value('2')
                row.locator('[data-row-field="quantity"]').fill('3')
                expect(row.locator('[data-row-field="required_minimum"]')).to_have_value('3')
                row.locator('[data-row-field="required_minimum"]').fill('1')
                row.locator('[data-row-field="quantity"]').fill('4')
                expect(row.locator('[data-row-field="required_minimum"]')).to_have_value('1')
                expect(page.locator('#customerPreviewInclusions')).to_contain_text('4 Browser panels')
                trigger = row.locator('[data-category-trigger]')
                trigger.press('ArrowDown')
                expect(trigger).to_have_attribute('aria-expanded', 'true')
                trigger.press('Home')
                trigger.press_sequentially('Browser')
                trigger.press('Enter')
                expect(row.locator('[data-row-field="category_id"]')).to_have_value(str(self.balloons.pk))
                expect(row.locator('[data-row-field="required_minimum"]')).to_have_value('1')
                expect(page.locator('#balloonSettings')).to_be_visible()
                trigger.click()
                row.get_by_role('option', name='Browser panels', exact=True).click()
                expect(row.locator('[data-row-field="category_id"]')).to_have_value(str(self.panels.pk))
                expect(page.locator('#customerPreviewInclusions')).to_contain_text('4 Browser panels')
                trigger.click()
                trigger.press('Escape')
                expect(trigger).to_have_attribute('aria-expanded', 'false')
                expect(trigger).to_be_focused()
                page.locator('#addCanvasItem').click()
                expect(page.locator('.oe-category-option').filter(has_text='Browser panels')).to_be_disabled()
                page.keyboard.press('Escape')
                page.locator('#addService').click()
                page.locator('.oe-inclusion-row').last.locator('[data-row-field="name"]').fill('Setup and delivery')
                expect(page.locator('.oe-inclusion-row').last.locator('.oe-service-tag')).to_be_visible()
                page.locator('#addCanvasItem').click()
                page.locator('.oe-category-option').filter(has_text='Browser balloons').click()
                expect(page.locator('#balloonSettings')).to_be_visible()
                page.locator('#id_design_max_colors').fill('2')
                expect(page.locator('#customerPreviewInclusions')).to_contain_text('max 2 colors')
                page.locator('.oe-inclusion-row').last.locator('[data-remove-row]').click()
                expect(page.locator('#balloonSettings')).to_be_hidden()
                page.locator('#addCanvasItem').click()
                page.locator('.oe-category-option').filter(has_text='Browser balloons').click()
                page.locator('.oe-inclusion-row').last.locator('[data-row-required]').check()
                row.locator('.oe-design-settings summary').click()
                trigger.click()
                expect(row.get_by_role('option', name='Browser balloons — Already included', exact=True)).to_be_disabled()
                page.locator('#inclusionsTitle').click()
                expect(trigger).to_have_attribute('aria-expanded', 'false')
                stream = io.BytesIO(); Image.new('RGB', (30, 30), 'gray').save(stream, 'PNG')
                with page.expect_file_chooser() as chooser:
                    page.locator('#browsePreviewImages').click()
                chooser.value.set_files([{'name': name, 'mimeType': 'image/png', 'buffer': stream.getvalue()} for name in ('one.png', 'two.png')])
                expect(page.locator('#previewImageCount')).to_have_text('2/2')
                expect(page.locator('#browsePreviewImages')).to_be_disabled()
                page.evaluate('''() => {const transfer = new DataTransfer(); transfer.items.add(new File(['text'], 'invalid.txt', {type:'text/plain'})); document.getElementById('previewDropzone').dispatchEvent(new DragEvent('drop', {bubbles:true, dataTransfer:transfer}));}''')
                expect(page.locator('#previewImageErrors')).to_contain_text('choose an image file')
                page.locator('.oe-image-card button').first.click()
                expect(page.locator('#previewImageCount')).to_have_text('1/2')
                page.evaluate('''(png) => {const bytes = Uint8Array.from(atob(png), char => char.charCodeAt(0)); const transfer = new DataTransfer(); transfer.items.add(new File([bytes], 'dropped.png', {type:'image/png'})); document.getElementById('previewDropzone').dispatchEvent(new DragEvent('drop', {bubbles:true, dataTransfer:transfer}));}''', base64.b64encode(stream.getvalue()).decode('ascii'))
                expect(page.locator('#previewImageCount')).to_have_text('2/2')
                page.locator('.oe-image-card button').first.click()
                expect(page.locator('#previewImageCount')).to_have_text('1/2')
                page.locator('#id_design_enabled').check()
                row.locator('[data-row-field="required_minimum"]').fill('5')
                page.locator('#id_price').fill('')
                page.locator('#id_name').fill('')
                page.locator('#saveOfferButton').click()
                expect(page.locator('#error_name')).to_contain_text('required')
                expect(page.locator('#error_price')).to_contain_text('required')
                expect(row.locator('.oe-row-errors')).to_contain_text('cannot exceed')
                expect(page.locator('#previewImageCount')).to_have_text('1/2')
                expect(row.locator('[data-row-field="quantity"]')).to_have_value('4')
                expect(page.locator('#customerPreviewInclusions')).to_contain_text('Setup and delivery')
                page.locator('#id_name').fill('New monochrome package')
                expect(page.locator('#error_name')).to_be_empty()
                expect(page.locator('#id_name')).not_to_have_attribute('aria-invalid', 'true')
                expect(page.locator('#id_price')).to_have_attribute('aria-invalid', 'true')
                expect(page.locator('#offerErrorSummary')).to_be_visible()
                page.locator('#id_price').fill('6000')
                expect(page.locator('#error_price')).to_be_empty()
                expect(page.locator('#offerErrorSummary')).to_be_visible()
                row.locator('[data-row-field="required_minimum"]').fill('1')
                expect(row.locator('.oe-row-errors')).to_be_empty()
                expect(row.locator('[data-row-field="required_minimum"]')).not_to_have_attribute('aria-invalid', 'true')
                expect(page.locator('#offerErrorSummary')).to_be_hidden()
                page.locator('#saveOfferButton').click()
                page.wait_for_url('**/staff/packages/', timeout=20000)
            finally:
                browser.close()

        package = Package.objects.get(name='New monochrome package')
        self.assertEqual(package.preview_images.count(), 1)
        offer = DesignOffer.objects.get(package=package)
        self.assertEqual(offer.requirements.get(category=self.panels).minimum, 1)
        self.assertEqual(offer.requirements.get(category=self.panels).maximum, 4)
        self.assertEqual(offer.max_balloon_colors, 2)
        self.assertTrue(offer.is_enabled)
