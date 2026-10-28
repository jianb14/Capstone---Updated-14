"""Opt-in Chrome checks for page-content editing in both themes and on mobile."""
import io
import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from .models import (AboutContent, AboutValueItem, GuidelineItem, GuidelinePageContent,
    HomeContent, HomeFeatureItem, Service, ServiceContent, User)


@skipUnless(os.environ.get('RUN_PAGE_CONTENT_BROWSER') == '1', 'Optional content browser verification')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class PageContentBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='page-browser', role='admin', email_verified=True)
        self.client.force_login(self.admin)
        self.home = HomeContent.objects.first() or HomeContent.objects.create()
        self.about = AboutContent.objects.first() or AboutContent.objects.create()
        self.services = ServiceContent.objects.first() or ServiceContent.objects.create()
        for index in range(11):
            HomeFeatureItem.objects.create(home_content=self.home, title=f'Browser feature {index:02}', description='A content preview.', display_order=index)
        AboutValueItem.objects.create(about_content=self.about, title='Browser value', description='Our values')
        Service.objects.create(title='Browser service', description='A service description')
        policy, _ = GuidelinePageContent.objects.get_or_create(page_key='guidelines', defaults={'title': 'Booking Guidelines'})
        GuidelineItem.objects.create(page_content=policy, heading='Browser policy', body='Policy details')
        stream = io.BytesIO(); Image.new('RGB', (30, 30), '#bdb8b2').save(stream, 'PNG'); self.photo = stream.getvalue()
        self.artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'

    def browser(self, p):
        browser = p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
        context.add_init_script("localStorage.setItem('balloorina-theme','light')")
        context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        context.route('https://cdnjs.cloudflare.com/**', lambda route: route.abort())
        context.route('https://cdn.jsdelivr.net/**', lambda route: route.fulfill(status=200, content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}})};'))
        return browser, context

    def test_filter_pagination_sections_and_all_collection_mutations_without_reload(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser, context = self.browser(p); page = context.new_page(); errors = []; documents = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
            try:
                page.goto(self.live_server_url + reverse('admin_home_content'))
                expect(page.locator('[data-catalog-row]')).to_have_count(8)
                page.get_by_role('link', name='Page 2', exact=True).click()
                expect(page.locator('[data-catalog-row]')).to_have_count(3)
                page.get_by_role('button', name='Rows per page: 8', exact=True).click()
                page.get_by_role('option', name='4', exact=True).click()
                expect(page.locator('[data-catalog-row]')).to_have_count(4)
                page.get_by_role('searchbox', name='Search content').fill('missing-content')
                expect(page.get_by_text('No matching features', exact=True)).to_be_visible()
                expect(page.locator('thead')).to_have_count(0)
                page.get_by_role('button', name='Clear search', exact=True).click()
                expect(page.locator('[data-catalog-row]')).to_have_count(4)
                page.get_by_role('button', name='Edit Welcome section', exact=True).click()
                dialog = page.locator('[data-catalog-dialog]')
                page.locator('#content_hero_title').fill('')
                page.get_by_role('button', name='Save changes', exact=True).click()
                expect(dialog.locator('[data-error-for=hero_title]')).to_have_text('Main heading is required.')
                page.locator('#content_hero_title').fill('Our new welcome')
                page.get_by_role('button', name='Save changes', exact=True).click()
                expect(dialog).to_be_hidden()
                expect(page.locator('.cfg-toast')).to_contain_text('Welcome section saved successfully.')
                expect(page.locator('.content-section-preview').filter(has_text='Our new welcome')).to_be_visible()
                for route, singular, field in (
                    ('admin_home_content', 'feature', 'title'), ('admin_about_content', 'value', 'title'),
                    ('admin_service_content', 'service', 'title'), ('admin_guidelines_content', 'section', 'heading')):
                    if route != 'admin_home_content':
                        page.goto(self.live_server_url + reverse(route))
                    page.get_by_role('button', name='Add ' + singular, exact=True).first.click()
                    expect(dialog).to_be_visible()
                    page.get_by_role('button', name='Add item', exact=True).click()
                    if singular != 'section':
                        expect(dialog.locator(f'[data-error-for={field}]')).to_be_visible()
                    else:
                        expect(dialog.locator('[data-error-for=body]')).to_be_visible()
                    page.locator('#content_' + field).fill('Created ' + singular)
                    if singular == 'service':
                        page.locator('#content_description').fill('Service details')
                        page.locator('#content_image').set_input_files({'name': 'service.png', 'mimeType': 'image/png', 'buffer': self.photo})
                        expect(dialog.locator('[data-upload-previews] img')).to_have_count(1)
                    if singular == 'section':
                        page.locator('#content_body').fill('Policy details')
                    page.get_by_role('button', name='Add item', exact=True).click()
                    expect(dialog).to_be_hidden()
                    expect(page.locator('.cfg-toast')).to_have_attribute('data-kind', 'success')
                    page.get_by_role('searchbox', name='Search content').fill('Created ' + singular)
                    expect(page.locator('[data-catalog-row]')).to_have_count(1)
                    page.get_by_role('button', name='Edit Created ' + singular, exact=True).click()
                    page.locator('#content_' + field).fill('Updated ' + singular)
                    page.get_by_role('button', name='Save changes', exact=True).click()
                    expect(dialog).to_be_hidden()
                    page.get_by_role('searchbox', name='Search content').fill('Updated ' + singular)
                    expect(page.locator('[data-catalog-row]')).to_have_count(1)
                    page.get_by_role('button', name='View Updated ' + singular, exact=True).last.click()
                    expect(dialog.locator('h3')).to_have_text('Updated ' + singular)
                    page.get_by_role('button', name='Close dialog', exact=True).click()
                    page.get_by_role('button', name='Delete Updated ' + singular, exact=True).click()
                    page.get_by_role('button', name='Delete items', exact=True).click()
                    expect(page.locator('[data-delete-dialog]')).to_be_hidden()
                    expect(page.locator('[data-catalog-row]')).to_have_count(0)
                    expect(page.locator('.cfg-toast')).to_contain_text('1 item(s) deleted.')
                self.assertEqual(len(documents), 4)
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()

    def test_themes_mobile_focus_footer_and_failed_save_preserves_draft(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser, context = self.browser(p); page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                for route in ('admin_home_content', 'admin_about_content', 'admin_service_content', 'admin_guidelines_content'):
                    page.goto(self.live_server_url + reverse(route))
                    for theme in ('light', 'dark'):
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                        for width in (1440, 768, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 900})
                            self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'), f'{route}-{theme}-{width}')
                            search = page.get_by_role('searchbox', name='Search content')
                            if width in (1440, 390):
                                page.screenshot(path=str(self.artifacts / f'page-content-overview-{route}-{theme}-{width}.png'), full_page=True, animations='disabled')
                            search.focus()
                            outline = search.evaluate('el=>getComputedStyle(el).outlineColor')
                            self.assertNotEqual(outline, 'rgba(0, 0, 0, 0)')
                            page.get_by_role('button', name='Edit Welcome section' if route != 'admin_guidelines_content' else 'Edit Page introduction', exact=True).click()
                            dialog = page.locator('[data-catalog-dialog]')
                            expect(dialog.locator('form')).to_be_visible()
                            input_field = dialog.locator('input:not([type=hidden],[type=checkbox],[type=file])').first
                            input_field.focus()
                            self.assertEqual(input_field.evaluate('el=>getComputedStyle(el).outlineColor'), outline)
                            body, footer = dialog.locator('.ac-dialog-body'), dialog.locator('.ac-dialog-footer')
                            self.assertLessEqual(body.bounding_box()['y'] + body.bounding_box()['height'], footer.bounding_box()['y'] + 1)
                            self.assertLessEqual(footer.bounding_box()['y'] + footer.bounding_box()['height'], 900)
                            self.assertFalse(dialog.evaluate('el=>el.scrollWidth > el.clientWidth + 1'))
                            if route in ('admin_home_content', 'admin_guidelines_content') and width in (1440, 390):
                                page.screenshot(path=str(self.artifacts / f'page-content-{route}-{theme}-{width}.png'))
                            page.get_by_role('button', name='Cancel', exact=True).click()
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.goto(self.live_server_url + reverse('admin_service_content'))
                page.get_by_role('button', name='Add service', exact=True).first.click()
                page.locator('#content_title').fill('Retained draft')
                page.locator('#content_description').fill('Service details')
                page.locator('#content_image').set_input_files({'name': 'service.png', 'mimeType': 'image/png', 'buffer': self.photo})
                page.route('**/staff/page-content/services/services/create/0/', lambda route: route.fulfill(status=503, content_type='application/json', body='{"message":"Temporarily unavailable. Please try again."}'))
                page.get_by_role('button', name='Add item', exact=True).click()
                expect(page.locator('.cfg-toast')).to_have_attribute('data-kind', 'error')
                expect(page.locator('#content_title')).to_have_value('Retained draft')
                expect(page.locator('[data-upload-previews] img')).to_have_count(1)
                expect(page.locator('[data-catalog-dialog]')).to_be_visible()
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()

    def test_content_tabs_back_and_bulk_delete_keep_one_document(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser, context = self.browser(p); page = context.new_page(); documents = []; errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
            try:
                page.goto(self.live_server_url + reverse('admin_home_content'))
                page.get_by_role('link', name='How it works', exact=False).click()
                expect(page.get_by_role('button', name='Add step', exact=True).first).to_be_visible()
                page.get_by_role('link', name='FAQs', exact=False).click()
                expect(page.get_by_role('button', name='Add question', exact=True).first).to_be_visible()
                page.go_back()
                expect(page.get_by_role('button', name='Add step', exact=True).first).to_be_visible()
                page.get_by_role('link', name='Features', exact=False).click()
                expect(page.locator('[data-catalog-row]')).to_have_count(8)
                page.locator('[data-select-all]').check()
                expect(page.locator('[data-selected-count]')).to_have_text('8')
                page.get_by_role('button', name='Delete selected', exact=True).click()
                page.get_by_role('button', name='Delete items', exact=True).click()
                expect(page.locator('[data-delete-dialog]')).to_be_hidden()
                expect(page.locator('[data-catalog-row]')).to_have_count(3)
                expect(page.locator('.cfg-toast')).to_contain_text('8 item(s) deleted.')
                page.goto(self.live_server_url + reverse('admin_about_content'))
                page.get_by_role('link', name='Journey milestones', exact=False).click()
                expect(page.get_by_role('button', name='Add milestone', exact=True).first).to_be_visible()
                page.goto(self.live_server_url + reverse('admin_guidelines_content'))
                page.get_by_role('link', name='Terms & Conditions', exact=False).click()
                expect(page.locator('[name=tab]')).to_have_value('terms')
                page.get_by_role('link', name='Privacy Policy', exact=False).click()
                expect(page.locator('[name=tab]')).to_have_value('privacy')
                page.get_by_role('button', name='Edit Page introduction', exact=True).click()
                expect(page.locator('#content_title')).to_have_value('Privacy Policy')
                self.assertEqual(len(documents), 3)
                self.assertEqual(errors, [])
            finally:
                context.close(); browser.close()
