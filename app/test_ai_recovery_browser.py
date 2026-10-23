"""Real browser checks for guide drafts and recovery of an accepted photo request."""
import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import User
from .test_ai_jobs import image_bytes


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class AiRecoveryBrowserTests(StaticLiveServerTestCase):
    def test_permanent_failure_has_no_retry_and_temporary_failure_has_a_countdown(self):
        import time
        from playwright.sync_api import sync_playwright, expect
        user = User.objects.create_user(username='ai-error-browser', role='customer')
        self.client.force_login(user)
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                for width in (1440, 390):
                    for theme in ('light', 'dark'):
                        with self.subTest(width=width, theme=theme):
                            context = browser.new_context(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
                            sent, errors = [], []
                            def route_api(route):
                                url = route.request.url
                                if '/api/ai/requests/' in url and route.request.method == 'POST':
                                    payload = route.request.post_data_json
                                    sent.append(payload)
                                    temporary = len(sent) > 1
                                    result = {'session_id': 1, 'response': 'The assistant is busy. Please try again shortly.' if temporary else
                                        'The assistant is unavailable right now. Please contact our team for help.',
                                        'retry_available': temporary, 'retry_after': 17 if temporary else 0,
                                        'retry_at': time.time()+17 if temporary else None}
                                    route.fulfill(json={'id': payload['request_id'], 'state': 'failed', 'session_id': 1,
                                        'user_message_id': len(sent)*2-1, 'assistant_message_id': len(sent)*2,
                                        'input_text': payload['message'], 'result': result})
                                elif url.endswith('/active/'):
                                    route.fulfill(json={'request': None})
                                elif url.endswith('/sessions/'):
                                    route.fulfill(json={'sessions': [{'id': 1, 'title': 'Help'}]})
                                else:
                                    route.fulfill(json={'messages': []})
                            context.route('**/api/chat/**', route_api)
                            context.route('**/api/ai/**', route_api)
                            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                            context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
                            page = context.new_page()
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            page.goto(self.live_server_url + reverse('home'), wait_until='domcontentloaded')
                            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                            page.locator('#ai-fab').click()
                            page.locator('#ai-widget-input').fill('What colors suit a wedding?')
                            page.locator('#ai-widget-send').click()
                            last = page.locator('#ai-chat-box .ai-bot-msg').last
                            expect(last).to_contain_text('Please contact our team')
                            expect(last.locator('.ai-request-retry')).to_have_count(0)
                            expect(page.locator('#ai-widget-send')).to_be_enabled()
                            page.locator('#ai-widget-input').fill('Suggest suitable colors')
                            page.locator('#ai-widget-send').click()
                            expect(last).to_contain_text('The assistant is busy')
                            expect(last.locator('.ai-request-retry')).to_be_disabled()
                            expect(last.locator('.ai-request-retry')).to_contain_text('Try again in')
                            self.assertEqual(len(sent), 2)
                            self.assertEqual(errors, [])
                            context.close()
            finally:
                browser.close()

    def test_refresh_reconnects_to_one_photo_request_and_preserves_draft(self):
        from playwright.sync_api import sync_playwright, expect
        user = User.objects.create_user(username='ai-recovery-browser', role='customer')
        self.client.force_login(user)
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                context = browser.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
                context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                    'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
                sent, jobs, errors = [], {}, []
                completed = False
                artifact_id = '97c6f53a-7fa4-4e06-9f0f-b977581e57f8'
                image_url = '/media/ai_generated/recovery.png'
                photo_url = '/media/chat_attachments/inspiration.png'
                from .services import _image_success_reply
                response_text = _image_success_reply(image_url, 'Birthday backdrop for "Sofia" in pink',
                    'Your saved design is ready.\n\n1. **Package 1-A**\n- One panel\n- Balloons\n\n'
                    '1. **Package 1-B**\n  - Two colors\n\n1. **Package 2**\n  - Two panels\n\nSample AI concept:')

                def job_data(record):
                    return {**record, 'state': 'succeeded' if completed else 'running', 'status': 'Creating your design…',
                        'stage': 'generating', 'assistant_message_id': record['user_message_id'] + 1 if completed else None,
                        'result': {'response': response_text, 'session_id': 1,
                            'images': [{'id': artifact_id, 'url': image_url}]} if completed else {}}

                def route_api(route):
                    url = route.request.url
                    if '/api/ai/requests/' in url and route.request.method == 'POST':
                        if route.request.headers.get('content-type', '').startswith('multipart/'):
                            import re
                            body = (route.request.post_data_buffer or b'').decode('latin1')
                            def field(name):
                                match = re.search('name="' + name + '"\r\n\r\n([^\r]*)', body)
                                return match.group(1) if match else ''
                            payload = {'request_id': field('request_id'), 'message': field('message')}
                        else:
                            payload = route.request.post_data_json
                        sent.append(payload)
                        record = {'id': payload['request_id'], 'session_id': 1, 'input_text': payload['message'],
                            'input_image_url': photo_url if len(sent) == 1 else '',
                            'user_message_id': 11 + (len(sent)-1)*2, 'kind': 'photo_edit' if len(sent) == 1 else 'revise'}
                        jobs[record['id']] = record
                        if len(sent) == 1:
                            route.abort()  # The server accepted it, but its HTTP response was lost.
                        else:
                            route.fulfill(json=job_data(record))
                    elif url.endswith('/active/'):
                        route.fulfill(json={'request': None})
                    elif '/api/ai/requests/' in url:
                        key = url.rstrip('/').split('/')[-1]
                        route.fulfill(json=job_data(jobs[key]) if key in jobs else {}, status=200 if key in jobs else 404)
                    elif url.endswith('/sessions/'):
                        route.fulfill(json={'sessions': [{'id': 1, 'title': 'My design'}]})
                    elif '/history/' in url:
                        messages = []
                        if jobs:
                            first = next(iter(jobs.values()))
                            messages.append({'id': 11, 'role': 'user', 'content': first['input_text'], 'image_url': photo_url})
                            if completed:
                                messages.append({'id': 12, 'role': 'assistant', 'content': response_text,
                                    'ai_images': [{'id': artifact_id, 'url': image_url}]})
                        route.fulfill(json={'messages': messages})
                    else:
                        route.fulfill(json={})

                context.route('**/api/chat/**', route_api)
                context.route('**/api/ai/**', route_api)
                context.route('**/media/**', lambda route: route.fulfill(body=image_bytes(), content_type='image/png'))
                context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + reverse('home'), wait_until='domcontentloaded')
                page.locator('#ai-fab').click()
                page.locator('#ai-guide-open').click()
                page.locator('[name="guide_occasion"][value="Wedding"]').check()
                page.locator('#ai-guide-next').click()
                page.locator('#ai-guide-suggest').click()
                chosen_theme = page.locator('.ai-guide-style-choice strong').first.inner_text()
                chosen_colors = page.locator('.ai-guide-style-choice small').first.inner_text()
                page.locator('.ai-guide-style-choice').first.click()
                expect(page.locator('#ai-guide-theme')).to_have_value(chosen_theme)
                page.reload(wait_until='domcontentloaded')
                page.locator('#ai-fab').click()
                page.locator('#ai-guide-open').click()
                expect(page.locator('#ai-guide-progress')).to_contain_text('Step 2 of 4')
                expect(page.locator('#ai-guide-theme')).to_have_value(chosen_theme)
                expect(page.locator('#ai-guide-colors')).to_have_value(chosen_colors)
                page.locator('#ai-guide-exit').click()
                page.locator('#ai-widget-input').fill('Generate a blue balloon backdrop from this photo')
                page.locator('#ai-widget-photo-input').set_input_files({'name': 'inspiration.png', 'mimeType': 'image/png', 'buffer': image_bytes()})
                page.locator('#ai-widget-send').click()
                page.wait_for_function("Object.keys(localStorage).some(key => key.startsWith('balloorina-ai-pending:'))")
                expect(page.locator('.ai-request-status')).to_contain_text('Reconnecting')
                self.assertEqual(len(sent), 1)
                original_id = sent[0]['request_id']
                page.reload(wait_until='domcontentloaded')
                page.locator('#ai-fab').click()
                expect(page.locator('.ai-request-status')).to_contain_text('Creating your design')
                self.assertEqual(len(sent), 1)
                completed = True
                expect(page.locator('#ai-chat-box')).to_contain_text('Your saved design is ready.')
                expect(page.locator('#ai-chat-box .ai-user-msg')).to_have_count(1)
                expect(page.locator('#ai-chat-box .ai-user-photo-thumb')).to_have_count(1)
                expect(page.locator('img[data-ai-generated-image="1"]')).to_have_attribute('data-ai-prompt', 'Birthday backdrop for "Sofia" in pink')
                packages = page.locator('#ai-chat-box .ai-bot-msg > ol')
                expect(packages).to_have_count(1)
                expect(packages.locator(':scope > li')).to_have_count(3)
                expect(packages.locator(':scope > li > strong')).to_have_text(['Package 1-A', 'Package 1-B', 'Package 2'])
                expect(packages.locator(':scope > li > ul')).to_have_count(3)
                expect(packages).to_have_css('list-style-type', 'decimal')
                edit_box = page.get_by_role('button', name='Edit this design').bounding_box()
                like_box = page.locator('.ai-fb-like').bounding_box()
                self.assertLessEqual(abs(edit_box['y'] + edit_box['height'] / 2 - like_box['y'] - like_box['height'] / 2), 1)
                self.assertEqual(len(sent), 1)
                self.assertIn(original_id, jobs)
                page.get_by_role('button', name='Edit this design').click()
                expect(page.locator('#ai-widget-input')).to_have_attribute('placeholder', 'Describe the changes you want...')
                page.locator('#ai-widget-input').fill('Change only the balloons to pink')
                page.reload(wait_until='domcontentloaded')
                page.locator('#ai-fab').click()
                expect(page.locator('#ai-widget-input')).to_have_value('Change only the balloons to pink')
                expect(page.locator('#ai-widget-input')).to_have_attribute('placeholder', 'Describe the changes you want...')
                page.locator('#ai-widget-send').click()
                expect(page.locator('#ai-widget-send')).to_be_enabled()
                self.assertEqual(sent[-1]['reference_id'], artifact_id)
                self.assertEqual(sent[-1]['intent'], 'revise')
                self.assertEqual(errors, [])
                context.close()
            finally:
                browser.close()
