import importlib
import io
import os
import re
from pathlib import Path
from tempfile import gettempdir
from types import SimpleNamespace
from unittest import skipUnless

from PIL import Image
from django.apps import apps
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connection
from django.urls import reverse

from .models import CanvasAsset, CanvasCategory, DesignOffer, DesignRequirement, Package, User
from .test_canvas_uploads import TemporaryCanvasStorage


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
class CategoryUploadsBrowserTests(TemporaryCanvasStorage, StaticLiveServerTestCase):
    def test_theme_decor_catalog_and_upload_share_allowance(self):
        from playwright.sync_api import sync_playwright, expect

        user = User.objects.create_user(username='theme-catalog-browser', role='customer')
        self.client.force_login(user)
        theme, _ = CanvasCategory.objects.get_or_create(builtin_key='theme_decor', defaults={
            'name': 'Theme Decor', 'available_package': True, 'available_entrance': True, 'available_stand': True})
        asset = CanvasAsset.objects.create(category=theme, label='Catalog theme decoration',
            static_path='images/canvas/premium/frames/panel_wall.svg')
        offer = DesignOffer.objects.create(kind='package',
            package=Package.objects.create(name='Theme catalog package', price=1000), is_enabled=True)
        DesignRequirement.objects.create(offer=offer, category=theme, required=True, minimum=2, maximum=2)
        panels = CanvasCategory.objects.create(name='Non-themed panels')
        CanvasAsset.objects.create(category=panels, label='Panel', static_path=asset.static_path)
        excluded = DesignOffer.objects.create(kind='package',
            package=Package.objects.create(name='No theme decor package', price=900), is_enabled=True)
        DesignRequirement.objects.create(offer=excluded, category=panels, required=True, minimum=1)
        stream = io.BytesIO()
        Image.new('RGBA', (48, 72), (30, 100, 180, 120)).save(stream, 'PNG')
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(self.live_server_url + reverse('design_canvas') + f'?design_offer_id={excluded.pk}&fresh=1')
                page.locator('[data-panel-target="elementsPanel"]').click()
                group = page.locator(f'.inventory-category[data-category-id="{theme.pk}"]')
                expect(group).to_be_hidden()
                page.goto(self.live_server_url + reverse('design_canvas') + f'?design_offer_id={offer.pk}&fresh=1')
                page.locator('[data-panel-target="elementsPanel"]').click()
                expect(group).to_be_visible()
                catalog = group.locator(f'[data-asset-id="{asset.pk}"]')
                expect(catalog).to_be_visible()
                self.assertTrue(group.evaluate('''el => Boolean(el.querySelector('.catalog-asset-items')
                    .compareDocumentPosition(el.querySelector('.category-upload-controls')) & Node.DOCUMENT_POSITION_FOLLOWING)'''))
                catalog.click()
                expect(page.locator('#cartInclusionsList')).to_contain_text('1/2 required')
                group.locator('[data-category-file]').set_input_files({
                    'name': 'my-theme-prop.png', 'mimeType': 'image/png', 'buffer': stream.getvalue()})
                dialog = page.get_by_role('dialog', name='Upload image')
                dialog.get_by_role('button', name='Use original', exact=True).click()
                dialog.get_by_role('button', name='Use image', exact=True).click()
                group.locator('[data-upload-id]').click()
                expect(page.locator('#cartInclusionsList')).to_contain_text('2/2 required')
                expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                page.locator('#saveDesignBtn').click()
                page.locator('#saveDesignNameInput').fill('Catalog and uploaded theme decor')
                page.locator('#saveDesignConfirmBtn').click()
                page.wait_for_url('**/my-designs/', timeout=20000)
                page.locator('.design-actions .edit-btn').first.click()
                expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                page.locator('[data-panel-target="elementsPanel"]').click()
                expect(catalog).to_be_visible()
                expect(group.locator('[data-upload-id]')).to_have_count(1)
                page.locator('#canvasSidebar').screenshot(path=str(Path(gettempdir()) / 'theme-decor-catalog-desktop.png'))
                for theme_name in ('light', 'dark'):
                    page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme_name)
                    expect(catalog).to_be_visible()
                    expect(group.locator('[data-upload-id]')).to_be_visible()
                page.set_viewport_size({'width': 390, 'height': 844})
                page.reload()
                expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                page.locator('[data-panel-target="elementsPanel"]').click()
                expect(page.locator('#mobileInventoryDialog')).to_be_visible()
                expect(catalog).to_be_visible()
                expect(group.locator('[data-upload-id]')).to_be_visible()
                page.locator('#mobileInventoryDialog').screenshot(path=str(Path(gettempdir()) / 'theme-decor-catalog-mobile.png'))
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 1)
                self.assertFalse(errors, errors)
            finally:
                context.close()
                browser.close()

    def test_asset_cutout_preview_original_retry_and_cancel(self):
        from playwright.sync_api import sync_playwright, expect
        user=User.objects.create_user(username='cutout-preview-owner',role='customer')
        self.client.force_login(user)
        category=CanvasCategory.objects.create(name='Cutout panels')
        CanvasAsset.objects.create(category=category,label='Panel',static_path='images/canvas/premium/frames/panel_wall.svg')
        offer=DesignOffer.objects.create(kind='package',package=Package.objects.create(name='Cutout package',price=1000),is_enabled=True)
        DesignRequirement.objects.create(offer=offer,category=category,minimum=1,required=True)
        output=io.BytesIO()
        Image.new('RGBA',(48,72),(200,40,40,0)).save(output,'PNG')
        cutout=output.getvalue()
        original=io.BytesIO()
        Image.new('RGB',(48,72),'red').save(original,'JPEG')
        file={'name':'opaque-panel.jpg','mimeType':'image/jpeg','buffer':original.getvalue()}
        with sync_playwright() as playwright:
            executable=Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe'
            browser=playwright.chromium.launch(executable_path=str(executable),headless=True)
            context=browser.new_context(reduced_motion='reduce',viewport={'width':1440,'height':1000})
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            page=context.new_page()
            try:
                page.route('**/my-designs/uploads/preview/',lambda route:route.fulfill(status=200,content_type='image/png',body=cutout))
                page.goto(self.live_server_url+reverse('design_canvas')+f'?design_offer_id={offer.pk}&fresh=1')
                page.locator('[data-panel-target="elementsPanel"]').click()
                picker=page.locator(f'[data-category-upload="{category.pk}"] [data-category-file]')
                picker.set_input_files(file)
                dialog=page.get_by_role('dialog',name='Upload image')
                expect(dialog.locator('[data-background-status]')).to_contain_text('Background removed')
                expect(dialog.locator('[data-balloon-color-fields]')).to_be_hidden()
                dialog.get_by_role('button',name='Use image',exact=True).click()
                card=page.locator('[data-upload-id]')
                expect(card).to_have_count(1)
                png=context.request.get(self.live_server_url+card.get_attribute('data-src')).body()
                self.assertEqual(Image.open(io.BytesIO(png)).convert('RGBA').getpixel((0,0))[3],0)
                page.unroute('**/my-designs/uploads/preview/')
                page.route('**/my-designs/uploads/preview/',lambda route:route.fulfill(status=503,content_type='application/json',body='{"message":"Try again or use the original photo."}'))
                picker.set_input_files(file)
                expect(dialog.locator('[data-background-status]')).to_contain_text('original')
                expect(dialog.get_by_role('button',name='Use image',exact=True)).to_be_disabled()
                dialog.get_by_role('button',name='Use original',exact=True).click()
                expect(dialog.locator('[data-background-status]')).to_contain_text('Original')
                dialog.get_by_role('button',name='Use image',exact=True).click()
                expect(card).to_have_count(2)
                jpg=context.request.get(self.live_server_url+card.last.get_attribute('data-src')).body()
                self.assertEqual(Image.open(io.BytesIO(jpg)).convert('RGBA').getpixel((0,0))[3],255)
                picker.set_input_files(file)
                expect(dialog.locator('[data-background-status]')).to_contain_text('original')
                page.unroute('**/my-designs/uploads/preview/')
                page.route('**/my-designs/uploads/preview/',lambda route:route.fulfill(status=200,content_type='image/png',body=cutout))
                dialog.get_by_role('button',name='Remove background',exact=True).click()
                expect(dialog.locator('[data-background-status]')).to_contain_text('Background removed')
                dialog.get_by_role('button',name='Cancel',exact=True).click()
                expect(card).to_have_count(2)
            finally:
                context.close();browser.close()

    def test_three_color_upload_upgrades_and_is_placed_after_confirmation(self):
        from playwright.sync_api import sync_playwright, expect
        user = User.objects.create_user(username='upload-upgrade-owner', role='customer')
        self.client.force_login(user)
        category = CanvasCategory.objects.create(name='Upgrade balloons', is_balloon=True)
        CanvasAsset.objects.create(category=category, label='Balloon', static_path='images/canvas/premium/frames/panel_wall.svg')
        offers = []
        for label, price, colors in [('Package 1-A', 4799, 2), ('Package 1-B', 5799, 3)]:
            offer = DesignOffer.objects.create(kind='package', package=Package.objects.create(name=label, price=price), is_enabled=True, max_balloon_colors=colors)
            DesignRequirement.objects.create(offer=offer, category=category, required=True, minimum=1)
            offers.append(offer)
        stream = io.BytesIO()
        Image.new('RGBA', (48, 72), (200, 40, 40, 160)).save(stream, 'PNG')
        file = {'name':'three-colors.png','mimeType':'image/png','buffer':stream.getvalue()}
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            context = browser.new_context(reduced_motion='reduce', viewport={'width':1440,'height':1000})
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            page = context.new_page()
            try:
                page.goto(self.live_server_url + reverse('design_canvas') + f'?design_offer_id={offers[0].pk}&fresh=1')
                page.locator('[data-panel-target="elementsPanel"]').click()
                page.locator(f'[data-category-upload="{category.pk}"] [data-category-file]').set_input_files(file)
                dialog = page.get_by_role('dialog', name='Balloon photo colors')
                for color in ('Red','White','Black'):
                    dialog.get_by_role('checkbox',name=color,exact=True).check()
                dialog.get_by_role('button',name='Save colors').click()
                photo = page.locator('[data-upload-id]')
                photo.click()
                expect(page.locator('#upgradeModal')).to_be_visible()
                expect(page.locator('#upgradeDetails')).to_contain_text('Package 1-B')
                page.locator('#cancelUpgradeBtn').click()
                expect(page.locator('#cartBaseName')).to_contain_text('Package 1-A')
                photo.click()
                page.locator('#confirmUpgradeBtn').click()
                expect(page.locator('#cartBaseName')).to_contain_text('Package 1-B')
                expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                expect(page.locator('#layersCountBadge')).to_have_text('1')
            finally:
                context.close(); browser.close()

    def test_balloon_preview_labels_edit_history_and_reopen(self):
        from playwright.sync_api import sync_playwright, expect

        user = User.objects.create_user(username='balloon-colors-browser', role='customer')
        self.client.force_login(user)
        balloons = CanvasCategory.objects.create(name='Balloon photo colors', is_balloon=True)
        CanvasAsset.objects.create(category=balloons, label='Catalog balloon', static_path='images/canvas/premium/frames/panel_wall.svg')
        offer = DesignOffer.objects.create(kind='package', package=Package.objects.create(name='Photo color package', price=1000), is_enabled=True, max_balloon_colors=2)
        DesignRequirement.objects.create(offer=offer, category=balloons, required=True, minimum=1, maximum=3)
        stream = io.BytesIO()
        Image.new('RGBA', (48, 72), (210, 60, 60, 160)).save(stream, 'PNG')
        file = {'name': 'red-balloon.png', 'mimeType': 'image/png', 'buffer': stream.getvalue()}
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.emulate_media(reduced_motion='no-preference')
                page.goto(self.live_server_url + reverse('design_canvas') + f'?design_offer_id={offer.pk}&fresh=1')
                page.locator('[data-panel-target="elementsPanel"]').click()
                group = page.locator(f'.inventory-category[data-category-id="{balloons.pk}"]')
                expect(group.locator('.category-upload-colors')).to_have_count(0)
                group.locator('.catalog-asset-items .draggable-item').first.click()
                expect(page.locator('#objectColorFields')).to_be_enabled()
                expect(page.locator('#itemColorPicker')).to_be_enabled()
                expect(page.locator('#itemColorPicker')).to_have_css('opacity', '1')
                page.locator('#contextDeleteBtn').click()
                expect(page.locator('#layersCountBadge')).to_have_text('0')
                picker = group.locator('[data-category-file]')
                picker.set_input_files(file)
                dialog = page.get_by_role('dialog', name='Balloon photo colors')
                expect(dialog).to_be_visible()
                self.assertTrue(dialog.evaluate('el => Math.abs(el.getBoundingClientRect().left + el.offsetWidth / 2 - innerWidth / 2) < 2'))
                self.assertTrue(dialog.evaluate('el => Math.abs(el.getBoundingClientRect().top + el.offsetHeight / 2 - innerHeight / 2) < 2'))
                expect(dialog.locator('[aria-label="Close balloon colors"] svg use')).to_have_attribute('href', '#ci-close')
                for theme in ('light', 'dark'):
                    page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                    metrics = dialog.evaluate('''el => {
                        const input=el.querySelector('input[type="checkbox"]');
                        input.checked=true;
                        input.focus();
                        const style=getComputedStyle(input), tick=getComputedStyle(input,'::after');
                        return {duration:style.transitionDuration,tickDuration:tick.transitionDuration,
                            background:style.backgroundColor,expected:getComputedStyle(el).color,
                            close:el.querySelector('[aria-label="Close balloon colors"]').offsetHeight,
                            action:el.querySelector('[data-save-colors]').offsetHeight,
                            scrollbar:getComputedStyle(el.querySelector('.balloon-colors-body')).scrollbarColor};
                    }''')
                    self.assertEqual(metrics['duration'], '0s', metrics)
                    self.assertEqual(metrics['tickDuration'], '0s', metrics)
                    self.assertEqual(metrics['background'], metrics['expected'], metrics)
                    self.assertEqual(metrics['close'], 36, metrics)
                    self.assertGreaterEqual(metrics['action'], 42, metrics)
                    self.assertNotEqual(metrics['scrollbar'], 'auto', metrics)
                    dialog.get_by_role('checkbox', name='White', exact=True).uncheck()
                self.assertEqual(dialog.locator('input[type="checkbox"]').first.evaluate('el => getComputedStyle(el).appearance'), 'none')
                expect(dialog.locator('img')).to_have_attribute('src', re.compile('^blob:'))
                expect(group.locator('[data-upload-id]')).to_have_count(0)
                dialog.get_by_role('button', name='Save colors').click()
                expect(dialog.locator('[data-color-error]')).to_contain_text('Choose at least 1')
                dialog.get_by_role('checkbox', name='Red', exact=True).check()
                dialog.get_by_role('button', name='Save colors').click()
                card = group.locator('.category-upload-card')
                expect(card).to_have_count(1)
                expect(group.locator('.custom-uploads-heading')).to_have_count(1)
                expect(card.locator('.custom-upload-tag')).to_have_count(0)
                self.assertTrue(card.locator('.upload-color-labels').evaluate('el => !el.textContent.trim()'))
                self.assertLessEqual(card.get_by_role('button', name='Edit colors').bounding_box()['height'], 30)
                self.assertTrue(card.locator('.upload-color-labels').evaluate('el => el.getBoundingClientRect().bottom <= el.parentElement.getBoundingClientRect().bottom'))
                expect(card.locator('.upload-color-labels [data-color="#e74c3c"]')).to_have_count(1)
                old_id = card.locator('[data-upload-id]').get_attribute('data-upload-id')
                card.locator('[data-upload-id]').click()
                expect(page.locator('#selectedUploadColors')).to_contain_text('Red')
                expect(page.locator('#objectColorFields')).to_be_disabled()
                expect(page.locator('#customObjectColor')).to_be_disabled()
                expect(page.locator('#itemColorPicker')).to_be_disabled()
                expect(page.locator('#itemColorPicker')).to_have_css('opacity', '0.4')
                expect(page.locator('#itemColorPicker')).to_have_css('cursor', 'not-allowed')
                for theme in ('light', 'dark'):
                    page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                    expect(page.locator('#itemColorPicker')).to_be_disabled()
                    expect(page.locator('#itemColorPicker')).to_have_css('opacity', '0.4')
                self.assertTrue(page.locator('#selectionToolbar').evaluate('''el => {
                    const row=el.querySelector(".selection-controls-row");
                    const groups=[...row.children].filter(child=>child.offsetWidth);
                    const needed=groups.reduce((sum,child)=>sum+child.getBoundingClientRect().width,0)+Math.max(0,groups.length-1)*6+40;
                    return el.getBoundingClientRect().width <= needed;
                }'''))
                page.screenshot(path=str(Path(gettempdir()) / 'library-polish-desktop-selection.png'))
                expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                page.keyboard.press('Control+d')
                expect(page.locator('#layersCountBadge')).to_have_text('2')
                page.locator('#selectedUploadColors').get_by_role('button', name='Edit colors').click()
                dialog.get_by_role('checkbox', name='Red', exact=True).uncheck()
                dialog.get_by_role('checkbox', name='Blue', exact=True).check()
                dialog.get_by_role('button', name='Save colors').click()
                expect(page.locator('#selectedUploadColors')).to_contain_text('Blue')
                expect(card.locator('.upload-color-labels [data-color="#3498db"]')).to_have_count(1)
                new_id = card.locator('[data-upload-id]').get_attribute('data-upload-id')
                self.assertNotEqual(old_id, new_id)
                expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                page.locator('#undoBtn').click()
                expect(card.locator('.upload-color-labels [data-color="#e74c3c"]')).to_have_count(1)
                page.locator('#redoBtn').click()
                expect(card.locator('.upload-color-labels [data-color="#3498db"]')).to_have_count(1)
                card.get_by_role('button', name='Edit colors').click()
                dialog.locator('input[type="color"]').fill('#12abcf')
                dialog.get_by_role('button', name='Add color', exact=True).click()
                page.route('**/my-designs/uploads/*/colors/', lambda route: route.abort(), times=1)
                dialog.get_by_role('button', name='Save colors').click()
                expect(dialog.locator('[data-color-error]')).to_be_visible()
                expect(card.locator('.upload-color-labels [data-color="#12abcf"]')).to_have_count(0)
                dialog.get_by_role('button', name='Save colors').click()
                expect(card.locator('.upload-color-labels [data-color="#12abcf"]')).to_have_count(1)
                expect(card.get_by_role('button', name='Edit colors')).to_be_focused()
                card.get_by_role('button', name='Edit colors').click()
                dialog.get_by_role('checkbox', name='Red', exact=True).check()
                dialog.get_by_role('checkbox', name='Green', exact=True).check()
                dialog.get_by_role('button', name='Save colors').click()
                expect(dialog.locator('[data-color-error]')).to_contain_text('2 balloon colors')
                dialog.get_by_role('button', name='Cancel', exact=True).click()
                expect(card.locator('.upload-color-labels [data-color="#3498db"]')).to_have_count(1)
                picker.set_input_files([file, {**file, 'name': 'other-balloon.png'}])
                expect(dialog.get_by_role('checkbox', name='Red', exact=True)).not_to_be_checked()
                dialog.get_by_role('checkbox', name='Red', exact=True).check()
                dialog.get_by_role('button', name='Cancel', exact=True).click()
                expect(dialog).to_be_visible()
                expect(dialog.get_by_role('checkbox', name='Red', exact=True)).not_to_be_checked()
                page.keyboard.press('Escape')
                expect(dialog).to_be_hidden()
                expect(card).to_have_count(1)
                page.locator('#saveDesignBtn').click()
                page.locator('#saveDesignNameInput').fill('Balloon declared colors')
                page.locator('#saveDesignConfirmBtn').click()
                page.wait_for_url('**/my-designs/', timeout=20000)
                page.goto(self.live_server_url + reverse('design_canvas') + f'?design_offer_id={offer.pk}&fresh=1')
                page.locator('[data-panel-target="elementsPanel"]').click()
                expect(card.locator('.upload-color-labels [data-color="#12abcf"]')).to_have_count(1)
                page.goto(self.live_server_url + reverse('my_designs'))
                page.locator('.design-actions .edit-btn').first.click()
                page.locator('[data-panel-target="elementsPanel"]').click()
                expect(card.locator('.upload-color-labels [data-color="#3498db"]')).to_have_count(1)
                expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
                page.set_viewport_size({'width': 390, 'height': 844})
                page.reload()
                expect(page.locator('.design-canvas-section')).to_have_class(re.compile('mobile-editor-mode'))
                page.locator('[data-panel-target="elementsPanel"]').click()
                expect(page.locator('#mobileInventoryDialog')).to_be_visible()
                if 'is-open' not in group.locator('.category-header').get_attribute('class'):
                    group.locator('.category-header').click()
                expect(card).to_be_visible()
                self.assertLessEqual(card.get_by_role('button', name='Edit colors').bounding_box()['height'], 30)
                self.assertLessEqual(card.locator('.upload-library-remove').bounding_box()['height'], 28)
                card.scroll_into_view_if_needed()
                card.screenshot(path=str(Path(gettempdir()) / 'library-polish-mobile-card.png'))
                page.screenshot(path=str(Path(gettempdir()) / 'balloon-colors-mobile-library.png'))
                card.get_by_role('button', name='Edit colors').click()
                expect(dialog).to_be_visible()
                self.assertLessEqual(dialog.evaluate('el => el.getBoundingClientRect().right'), 390)
                self.assertTrue(dialog.locator('[data-save-colors]').evaluate('el => el.getBoundingClientRect().bottom <= el.closest("dialog").getBoundingClientRect().bottom'))
                dialog.screenshot(path=str(Path(gettempdir()) / 'balloon-colors-mobile.png'))
                page.set_viewport_size({'width': 768, 'height': 1000})
                page.evaluate("document.documentElement.dataset.theme = 'light'")
                self.assertTrue(dialog.evaluate('el => getComputedStyle(el.querySelector("input:checked")).backgroundColor === getComputedStyle(el).color'))
                dialog.screenshot(path=str(Path(gettempdir()) / 'balloon-colors-tablet-light.png'))
                page.set_viewport_size({'width': 1440, 'height': 1000})
                # Changing out of mobile mode closes its inventory, while this modal stays active.
                dialog.screenshot(path=str(Path(gettempdir()) / 'balloon-colors-desktop-light.png'))
                dialog.get_by_role('button', name='Cancel', exact=True).click()
                page.set_viewport_size({'width': 390, 'height': 844})
                page.reload()
                page.locator('[data-panel-target="elementsPanel"]').click()
                card.locator('[data-upload-id]').click()
                expect(page.locator('#mobileSelectionName')).to_contain_text('Colors: Blue')
                expect(page.locator('#mobileSelectionName')).to_contain_text('#12ABCF')
                expect(page.locator('#itemColorPicker')).to_be_disabled()
                expect(page.locator('#itemColorPicker')).to_have_css('opacity', '0.4')
                self.assertFalse(errors, errors)
            finally:
                context.close()
                browser.close()

    def test_upload_placement_count_save_reopen_and_mobile_theme(self):
        from playwright.sync_api import sync_playwright, expect

        importlib.import_module('app.migrations.0122_category_uploads').register_theme_decor(apps, SimpleNamespace(connection=connection))
        user = User.objects.create_user(username='category-browser', role='customer')
        self.client.force_login(user)
        panels = CanvasCategory.objects.create(name='Upload browser panels')
        asset = CanvasAsset.objects.create(category=panels, label='Default panel', static_path='images/canvas/premium/frames/panel_wall.svg')
        package = Package.objects.create(name='Upload browser package', price=1000)
        offer = DesignOffer.objects.create(kind='package', package=package, is_enabled=True)
        DesignRequirement.objects.create(offer=offer, category=panels, required=True, minimum=2, maximum=2)
        theme = CanvasCategory.objects.get(builtin_key='theme_decor')
        themed_offer = DesignOffer.objects.create(kind='package', package=Package.objects.create(name='Themed browser package', price=1500), is_enabled=True)
        DesignRequirement.objects.create(offer=themed_offer, category=panels, required=True, minimum=2, maximum=2)
        DesignRequirement.objects.create(offer=themed_offer, category=theme, required=True, minimum=1, maximum=2)
        stream = io.BytesIO()
        Image.new('RGBA', (48, 72), (30, 100, 180, 120)).save(stream, 'PNG')
        file = {'name': 'custom-panel.png', 'mimeType': 'image/png', 'buffer': stream.getvalue()}
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + reverse('design_canvas') + f'?design_offer_id={offer.pk}&fresh=1')
            page.locator('[data-panel-target="elementsPanel"]').click()
            group = page.locator(f'.inventory-category[data-category-id="{panels.pk}"]')
            disabled_theme = page.locator(f'.inventory-category[data-category-id="{theme.pk}"]')
            expect(disabled_theme).to_be_hidden()
            self.assertTrue(group.evaluate('''el => Boolean(el.querySelector('.catalog-asset-items').compareDocumentPosition(el.querySelector('.category-upload-controls')) & Node.DOCUMENT_POSITION_FOLLOWING)'''))
            expect(page.locator('#referenceUploadDropzone')).to_have_count(0)
            group.locator('[data-category-file]').set_input_files(file)
            page.get_by_role('dialog', name='Upload image').get_by_role('button',name='Use image',exact=True).click()
            card = group.locator('[data-upload-id]')
            expect(card).to_have_count(1)
            remove = group.locator('.upload-library-remove')
            expect(remove.locator('svg use')).to_have_attribute('href', '#ci-close')
            self.assertLessEqual(remove.bounding_box()['width'], 28)
            self.assertLessEqual(remove.bounding_box()['height'], 28)
            self.assertTrue(remove.evaluate('''el => {
                const button = el.getBoundingClientRect(), card = el.parentElement.getBoundingClientRect();
                return button.top < card.top + 10 && button.right > card.right - 10;
            }'''))
            self.assertGreater(group.locator(f'[data-asset-id="{asset.pk}"]').bounding_box()['width'], 50)
            expect(page.locator('#designOverallState')).to_contain_text('0 of 1')
            card.click()
            expect(page.locator('#cartInclusionsList')).to_contain_text('1/2 required', timeout=15000)
            group.locator(f'[data-asset-id="{asset.pk}"]').click()
            expect(page.locator('#designOverallState')).to_contain_text('Ready to book', timeout=15000)
            page.locator('#undoBtn').click()
            expect(page.locator('#cartInclusionsList')).to_contain_text('1/2 required')
            page.locator('#redoBtn').click()
            expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
            page.locator('#saveDesignBtn').click()
            page.locator('#saveDesignNameInput').fill('Custom category layout')
            page.locator('#saveDesignConfirmBtn').click()
            page.wait_for_url('**/my-designs/', timeout=20000)
            page.locator('.design-actions .edit-btn').first.click()
            expect(page.locator('#designOverallState')).to_contain_text('Ready to book', timeout=20000)
            page.evaluate('''() => {
                const key = `designCanvasDraft:v1:design-${window.currentDesignId}:kind-package:offer-${window.designOffer.id}`;
                localStorage.setItem(key, JSON.stringify({canvas_json: JSON.stringify({objects: []}), upload_user_id: 'different-customer', uploads: {}}));
            }''')
            page.reload()
            expect(page.locator('#designOverallState')).to_contain_text('Ready to book', timeout=20000)
            page.locator('[data-panel-target="elementsPanel"]').click()
            expect(page.locator(f'[data-upload-library="{panels.pk}"] [data-upload-id]')).to_have_count(1)
            page.locator('#canvasSidebar').screenshot(path=str(Path(gettempdir()) / 'category-uploads-desktop.png'))
            page.locator(f'[data-upload-library="{panels.pk}"] .upload-library-remove').click()
            expect(page.locator(f'[data-upload-library="{panels.pk}"] [data-upload-id]')).to_have_count(0)
            expect(page.locator('#designOverallState')).to_contain_text('Ready to book')
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(page.url + f'&design_offer_id={themed_offer.pk}')
            page.locator('[data-panel-target="elementsPanel"]').click()
            theme_group = page.locator(f'.inventory-category[data-category-id="{theme.pk}"]')
            if 'is-open' not in (theme_group.locator('.category-header').get_attribute('class') or ''):
                theme_group.locator('.category-header').click()
            expect(theme_group.locator('[data-browse-category]')).to_be_enabled()
            theme_group.locator('[data-category-file]').set_input_files({**file, 'name': 'themed-ball.png'})
            page.get_by_role('dialog', name='Upload image').get_by_role('button',name='Use image',exact=True).click()
            theme_card = theme_group.locator('[data-upload-id]')
            expect(theme_card).to_have_count(1)
            page.evaluate("document.documentElement.dataset.theme = 'light'")
            self.assertTrue(theme_card.evaluate('(el) => el.querySelector("img").getBoundingClientRect().bottom <= el.querySelector(".item-label").getBoundingClientRect().top'))
            page.locator('#canvasSidebar').screenshot(path=str(Path(gettempdir()) / 'category-uploads-mobile.png'))
            theme_card.click()
            expect(page.locator('#mobileChecklistCount')).to_have_text('0')
            expect(page.locator('#layersCountBadge')).to_have_text('3')
            layer_count = page.locator('#layersCountBadge').inner_text()
            page.evaluate('(id) => { window.designOffer = window.allDesignOffers[String(id)]; }', package.pk)
            if page.locator('#mobileInventoryDialog').is_visible():
                page.locator('#mobileInventoryDialog [data-mobile-close]').click()
            page.keyboard.press('Control+d')
            expect(page.get_by_text('This custom image is not included in the selected package.', exact=True)).to_be_visible()
            expect(page.locator('#layersCountBadge')).to_have_text(layer_count)
            page.locator('[data-panel-target="uploadsPanel"]').click()
            expect(page.locator('#mobileCanvasToolsDialog')).to_be_visible()
            expect(page.locator('#mobileCanvasBackground .bg-upload-btn')).to_be_visible()
            page.locator('#mobileCanvasToolsDialog [data-mobile-close]').click()
            page.locator('[data-panel-target="uploadsPanel"]').click()
            expect(page.locator('#mobileCanvasToolsDialog')).to_be_visible()
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 1)
            self.assertFalse(errors, errors)
            browser.close()
