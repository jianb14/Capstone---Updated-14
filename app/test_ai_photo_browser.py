"""Photo composer, sent-image layout and source selection in a real browser."""
import re
from pathlib import Path
from unittest import skipUnless
import os

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import User
from .test_ai_jobs import image_bytes


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class AiPhotoBrowserTests(StaticLiveServerTestCase):
    def test_attachment_preview_sent_photo_and_original_selection_in_both_themes(self):
        from playwright.sync_api import sync_playwright, expect
        user = User.objects.create_user(username='photo-browser', role='customer')
        self.client.force_login(user)
        cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        root = Path(settings.BASE_DIR)
        screenshots = root/'.booking-followup-check'
        screenshots.mkdir(exist_ok=True)
        fixture = root/'media/gallery/birthday1.jpg'
        picture = fixture.read_bytes() if fixture.exists() else image_bytes()
        with sync_playwright() as playwright:
            executable = Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                for width, height in ((1440, 1000), (390, 844), (320, 640)):
                    for theme in ('light', 'dark'):
                        with self.subTest(width=width, theme=theme):
                            context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce')
                            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': cookie, 'url': self.live_server_url}])
                            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                            context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
                            context.route('**/media/**', lambda route: route.fulfill(body=picture, content_type='image/jpeg'))
                            sent, history, errors = [], [], []
                            photo_url = '/media/chat_attachments/photo.jpg'
                            def api(route):
                                request, url = route.request, route.request.url
                                if request.method == 'POST' and '/api/ai/requests/' in url:
                                    if 'multipart/' in request.headers.get('content-type', ''):
                                        body = (request.post_data_buffer or b'').decode('latin1')
                                        def field(name):
                                            match = re.search('name="'+name+'"\\r\\n\\r\\n([^\\r]*)', body)
                                            return match[1] if match else ''
                                        payload = {name: field(name) for name in ('request_id', 'message', 'reference_id', 'source_photo_id', 'intent')}
                                        image_url = photo_url
                                    else:
                                        payload = request.post_data_json
                                        image_url = ''
                                    sent.append(payload)
                                    message_id = len(sent)*2+9
                                    reply = 'What would you like to change in this photo?' if not payload['message'] else 'Your updated design is ready.'
                                    history.extend([
                                        {'id': message_id, 'role': 'user', 'content': payload['message'] or 'Attached photo', 'image_url': image_url},
                                        {'id': message_id+1, 'role': 'assistant', 'content': reply}])
                                    route.fulfill(json={'id': payload['request_id'], 'state': 'succeeded', 'session_id': 1,
                                        'user_message_id': message_id, 'assistant_message_id': message_id+1,
                                        'input_text': payload['message'] or 'Attached photo', 'input_image_url': image_url,
                                        'result': {'response': reply, 'session_id': 1}})
                                elif url.endswith('/active/'):
                                    route.fulfill(json={'request': None})
                                elif url.endswith('/sessions/'):
                                    route.fulfill(json={'sessions': [{'id': 1, 'title': 'Photo editing'}] if history else []})
                                else:
                                    route.fulfill(json={'messages': history})
                            context.route('**/api/chat/**', api)
                            context.route('**/api/ai/**', api)
                            page = context.new_page()
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            page.goto(self.live_server_url+reverse('home'), wait_until='domcontentloaded')
                            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                            page.locator('#ai-fab').click()
                            expect(page.locator('.ai-bot-msg').filter(has_text="Hello! I'm your virtual event planning assistant.")).to_have_count(1)
                            upload = {'name': 'My reference photo with a long file name.jpg', 'mimeType': 'image/jpeg', 'buffer': picture}
                            page.locator('#ai-widget-photo-input').set_input_files(upload)
                            expect(page.locator('.ai-input-area #ai-pending-photo-chip')).to_be_visible()
                            thumb = page.locator('.ai-pending-photo-thumb').last.bounding_box()
                            control = page.locator('#ai-widget-input').bounding_box()
                            self.assertLessEqual(thumb['y']+thumb['height'], control['y'])
                            page.get_by_role('button', name='Change colors', exact=True).click()
                            expect(page.locator('#ai-widget-input')).to_have_value('Change the color of ')
                            self.assertEqual(sent, [])
                            page.get_by_role('button', name='Remove attached photo').click()
                            expect(page.locator('#ai-composer-media')).to_be_hidden()
                            page.locator('#ai-widget-input').fill('Add gold balloons on the right. Keep the backdrop.')
                            page.locator('#ai-widget-photo-input').set_input_files(upload)
                            self.assertLessEqual(page.locator('#ai-widget').evaluate('(el) => el.scrollWidth-el.clientWidth'), 1)
                            page.screenshot(path=str(screenshots/f'ai-photo-composer-{width}-{theme}.png'), animations='disabled')
                            page.locator('#ai-widget-send').click()
                            expect(page.locator('#ai-pending-photo-chip')).to_have_count(0)
                            expect(page.locator('.ai-has-photo .ai-user-photo-thumb')).to_have_count(1)
                            expect(page.locator('.ai-has-photo .ai-user-text')).to_have_text('Add gold balloons on the right. Keep the backdrop.')
                            self.assertEqual(page.locator('.ai-has-photo').evaluate('(el) => getComputedStyle(el).backgroundColor'), 'rgba(0, 0, 0, 0)')
                            image_box = page.locator('.ai-user-photo').bounding_box()
                            text_box = page.locator('.ai-has-photo .ai-user-text').bounding_box()
                            self.assertLessEqual(image_box['y']+image_box['height'], text_box['y'])
                            page.screenshot(path=str(screenshots/f'ai-photo-sent-{width}-{theme}.png'), animations='disabled')
                            page.reload(wait_until='domcontentloaded')
                            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                            page.locator('#ai-fab').click()
                            expect(page.locator('.ai-has-photo .ai-user-photo-thumb')).to_have_count(1)
                            page.get_by_role('button', name='Edit this photo', exact=True).click()
                            expect(page.locator('.ai-reference-preview')).to_be_visible()
                            expect(page.locator('.ai-reference-preview > span')).to_have_text('Editing this photo')
                            expect(page.locator('.ai-reference-preview img')).to_have_attribute('src', re.compile('photo.jpg$'))
                            page.locator('#ai-widget-input').fill('Remove the flowers.')
                            page.locator('#ai-widget-send').click()
                            expect(page.locator('#ai-widget-send')).to_be_enabled()
                            self.assertEqual(str(sent[-1]['source_photo_id']), '11')
                            self.assertFalse(sent[-1]['reference_id'])
                            self.assertEqual(sent[-1]['intent'], 'revise')
                            self.assertEqual(errors, [])
                            context.close()
            finally:
                browser.close()
