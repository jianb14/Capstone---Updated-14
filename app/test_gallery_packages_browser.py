"""Opt-in end-to-end package uploads and category/package gallery filtering."""
import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from . import test_gallery_packages as fixtures
from .models import GalleryCategory, GalleryImage
from .test_admin_catalog import upload


@skipUnless(os.environ.get('RUN_GALLERY_BROWSER') == '1', 'Optional gallery package browser checks')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies',
                   REQUEST_RATE_LIMITING_ENABLED=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class GalleryPackageBrowserTests(StaticLiveServerTestCase):
    setUp = fixtures.GalleryPackageTests.setUp

    def context(self, browser, width=1440, height=1000, theme='light'):
        context = browser.new_context(viewport={'width':width,'height':height}, reduced_motion='reduce')
        context.add_init_script('localStorage.setItem("balloorina-theme", "'+theme+'")')
        context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,
            'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
        def external(route):
            if route.request.url.startswith(self.live_server_url+'/'):
                route.continue_()
            elif 'sweetalert' in route.request.url:
                route.fulfill(content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}})};')
            else:
                route.abort()
        context.route('**/*', external)
        return context

    def test_client_unified_filters_and_modal_package_metadata(self):
        from playwright.sync_api import sync_playwright, expect
        general = GalleryCategory.objects.create(name='General setups')
        GalleryCategory.objects.create(name='Empty category')
        GalleryImage.objects.create(category=general, image=upload('general.png'), caption='General legacy')
        GalleryImage.objects.create(category=self.birthday, package=self.inactive, image=upload('past.png'), caption='Past setup')
        artifacts = Path(settings.BASE_DIR)/'.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            for width,height in ((1440,1000),(390,844),(320,640)):
                for theme in ('light','dark'):
                    context = self.context(browser,width,height,theme)
                    page = context.new_page(); errors = []
                    page.on('pageerror', lambda error:errors.append(str(error)))
                    page.goto(self.live_server_url+reverse('gallery'), wait_until='domcontentloaded')
                    visible = page.locator('.gallery-item:not([hidden])')
                    categories = page.get_by_role('group', name='Gallery filters', exact=True)
                    packages = categories
                    expect(visible).to_have_count(6)
                    expect(packages.get_by_role('button',name='Package 3',exact=True)).to_have_count(0)
                    categories.get_by_role('button',name='Birthday',exact=True).click()
                    expect(visible).to_have_count(4)
                    packages.get_by_role('button',name='Package 1',exact=True).click()
                    expect(visible).to_have_count(2)
                    expect(categories.locator('[aria-pressed=true]')).to_have_count(1)
                    expect(categories.get_by_role('button',name='Birthday',exact=True)).to_have_attribute('aria-pressed','false')
                    self.assertEqual(set(visible.evaluate_all('(items)=>items.map(e=>e.dataset.package)')), {str(self.one.pk)})
                    first = page.locator(f'.gallery-item:not([hidden])[data-category="{self.birthday.pk}"]')
                    self.assertLessEqual(page.locator('body').evaluate('(e)=>e.scrollWidth-innerWidth'),1)
                    page.screenshot(path=str(artifacts/f'gallery-packages-{width}-{theme}.png'))
                    first.focus(); page.keyboard.press('Enter')
                    expect(page.locator('#galleryLightbox')).to_be_visible()
                    expect(page.locator('#lightboxCategory')).to_have_text('Birthday')
                    expect(page.locator('#lightboxPackage')).to_have_text('Package 1')
                    expect(page.locator('#lightboxCaption')).to_have_text('Birthday one')
                    page.screenshot(path=str(artifacts/f'gallery-package-modal-{width}-{theme}.png'))
                    page.keyboard.press('Escape'); expect(first).to_be_focused()
                    categories.get_by_role('button',name='Baptism',exact=True).click()
                    expect(categories.locator('[aria-pressed=true]')).to_have_count(1)
                    expect(packages.locator(f'[data-package="{self.two.pk}"]')).to_be_visible()
                    expect(categories.get_by_role('button',name='Baptism',exact=True)).to_have_attribute('aria-pressed','true')
                    expect(visible).to_have_count(1)
                    categories.get_by_role('button',name='General setups',exact=True).click()
                    expect(page.locator('#galleryPackageFilter')).to_have_count(0)
                    expect(visible).to_have_count(1)
                    visible.first.click()
                    expect(page.locator('#lightboxPackage')).to_be_hidden()
                    expect(page.locator('#lightboxCategory')).to_have_text('General setups')
                    page.keyboard.press('Escape')
                    categories.get_by_role('button',name='Empty category',exact=True).click()
                    expect(visible).to_have_count(0)
                    expect(page.locator('#galleryEmpty')).to_be_visible()
                    categories.get_by_role('button',name='All Projects',exact=True).click()
                    expect(visible).to_have_count(6)
                    expect(categories.locator('[aria-pressed=true]')).to_have_count(1)
                    self.assertEqual(errors,[])
                    context.close()
            browser.close()

    def test_admin_batch_assignment_edit_filters_and_public_results_are_connected(self):
        from playwright.sync_api import sync_playwright, expect
        photo = upload().read()
        artifacts = Path(settings.BASE_DIR)/'.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
            context = self.context(browser,390,844,'dark'); page = context.new_page(); errors = []
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(self.live_server_url+reverse('admin_gallery'),wait_until='domcontentloaded')
            page.get_by_role('button',name='Add gallery image',exact=True).click()
            dialog = page.locator('[data-catalog-dialog]')
            expect(dialog.get_by_role('button',name='Package: No specific package',exact=True)).to_be_visible()
            page.get_by_role('button',name='Category: Choose a category',exact=True).click()
            page.get_by_role('option',name='Birthday',exact=True).click()
            page.get_by_role('button',name='Package: No specific package',exact=True).click()
            page.get_by_role('option',name='Package 1',exact=True).click()
            page.locator('#catalog_caption').fill('Uploaded birthday')
            page.locator('#catalog_images').set_input_files([
                {'name':'batch-one.png','mimeType':'image/png','buffer':photo},
                {'name':'batch-two.png','mimeType':'image/png','buffer':photo}])
            for width,height in ((1440,1000),(390,844),(320,560)):
                page.set_viewport_size({'width':width,'height':height})
                dialog.locator('[data-catalog-body]').evaluate('(e)=>e.scrollTop=e.scrollHeight')
                expect(dialog.locator('.ac-dialog-footer')).to_be_in_viewport()
                self.assertLessEqual(dialog.evaluate('(e)=>e.scrollWidth-e.clientWidth'),1)
                page.screenshot(path=str(artifacts/f'admin-gallery-package-upload-{width}.png'))
            page.get_by_role('button',name='Add item',exact=True).click()
            expect(dialog).to_be_hidden()
            expect(page.locator('[data-catalog-row]')).to_have_count(7)
            page.get_by_role('button',name='Category filter: All categories',exact=True).click()
            page.get_by_role('option',name='Birthday',exact=True).click()
            page.get_by_role('button',name='Package filter: All packages',exact=True).click()
            page.get_by_role('option',name='Package 1',exact=True).click()
            expect(page.locator('[data-catalog-row]')).to_have_count(3)
            page.get_by_role('button',name='Edit Uploaded birthday',exact=True).first.click()
            page.get_by_role('button',name='Package: Package 1',exact=True).click()
            page.get_by_role('option',name='Package 2',exact=True).click()
            page.get_by_role('button',name='Save changes',exact=True).click()
            expect(dialog).to_be_hidden()
            expect(page.locator('[data-catalog-row]')).to_have_count(2)
            page.get_by_role('button',name='Package filter: Package 1',exact=True).click()
            page.get_by_role('option',name='No specific package',exact=True).click()
            expect(page.locator('[data-catalog-row]')).to_have_count(1)
            page.get_by_role('searchbox',name='Search library').fill('missing-photo')
            expect(page.get_by_text('No matching photos',exact=True)).to_be_visible()
            page.get_by_role('button',name='Clear filters',exact=True).click()
            expect(page.locator('[data-catalog-row]')).to_have_count(7)
            expect(page.get_by_role('button',name='Package filter: All packages',exact=True)).to_be_visible()
            page.goto(self.live_server_url+reverse('gallery'),wait_until='domcontentloaded')
            page.get_by_role('group',name='Gallery filters',exact=True).get_by_role('button',name='Birthday',exact=True).click()
            page.get_by_role('group',name='Gallery filters',exact=True).get_by_role('button',name='Package 2',exact=True).click()
            expect(page.locator('.gallery-item:not([hidden])')).to_have_count(2)
            self.assertEqual(errors,[])
            context.close(); browser.close()
        photos = GalleryImage.objects.filter(caption='Uploaded birthday')
        self.assertEqual(photos.count(),2)
        self.assertEqual(set(photos.values_list('package_id',flat=True)), {self.one.pk,self.two.pk})
