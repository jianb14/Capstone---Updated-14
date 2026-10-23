"""Exercise the customer guide with real chat markup and mocked AI responses."""
import json
import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import User


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class AIDesignGuideBrowserTests(StaticLiveServerTestCase):
    def test_guide_review_send_and_accessible_layouts(self):
        from playwright.sync_api import sync_playwright, expect
        from .services import _warning_message_for_strike, _ban_message

        user = User.objects.create_user(username='guide_customer', role='customer')
        self.client.force_login(user)
        cookie = {'name': settings.SESSION_COOKIE_NAME,
                  'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                  'url': self.live_server_url}
        screenshots = Path(settings.BASE_DIR) / '.booking-followup-check'
        screenshots.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                for width, height in ((1440, 1000), (390, 844), (320, 640), (600, 500)):
                    for theme in ('light', 'dark'):
                        with self.subTest(width=width, theme=theme):
                            context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce')
                            context.add_cookies([cookie])
                            sent = []
                            errors = []
                            fallback = False
                            moderation_stage = 0
                            moderation_history = False

                            def chat_reply(route):
                                url = route.request.url
                                if '/api/ai/requests/' in url and route.request.method == 'POST':
                                    payload = route.request.post_data_json
                                    if moderation_stage:
                                        result = {'response': _warning_message_for_strike(moderation_stage) if moderation_stage < 3 else _ban_message(600),
                                            'is_warning': moderation_stage < 3, 'is_banned': moderation_stage == 3,
                                            'ban_remaining_seconds': 600 if moderation_stage == 3 else 0}
                                    else:
                                        sent.append(payload)
                                        text = ('Your fallback design is ready.' if fallback else
                                            'Your design idea is ready. <img src="/media/ai_generated/guide-preview.png" alt="Balloorina Design Concept" data-ai-prompt="Sample backdrop" style="max-width:100%;">')
                                        result = {'response': text}
                                        if not fallback:
                                            result['images'] = [{'id': 'guide-preview', 'url': '/media/ai_generated/guide-preview.png'}]
                                    result['session_id'] = 1
                                    route.fulfill(json={'id': payload['request_id'], 'state': 'succeeded', 'session_id': 1,
                                        'input_text': payload['message'], 'result': result})
                                elif url.endswith('/active/'):
                                    route.fulfill(json={'request': None})
                                elif url.endswith('/sessions/'):
                                    route.fulfill(json={'sessions': [{'id': 1, 'title': 'Design ideas'}],
                                        'is_banned': moderation_stage == 3, 'ban_remaining_seconds': 600 if moderation_stage == 3 else 0})
                                elif '/history/' in url and moderation_history:
                                    route.fulfill(json={'messages': [{'role': 'assistant', 'content': _warning_message_for_strike(n)} for n in (1, 2)]})
                                else:
                                    route.fulfill(json={})

                            context.route('**/api/chat/**', chat_reply)
                            context.route('**/api/ai/**', chat_reply)
                            context.route('**/media/ai_generated/guide-preview.png', lambda route: route.fulfill(path=str(Path(settings.BASE_DIR) / 'static/images/sustainable.png'), content_type='image/png'))
                            # Keep optional third-party presentation assets out of this interaction test.
                            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                            context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
                            context.route('https://cdnjs.cloudflare.com/**', lambda route: route.abort())
                            sweetalert = Path(settings.BASE_DIR) / '.booking-followup-check/sweetalert2.all.min.js'
                            if sweetalert.exists():
                                context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(path=str(sweetalert), content_type='application/javascript'))
                            page = context.new_page()
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            page.goto(self.live_server_url + reverse('home'), wait_until='domcontentloaded')
                            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                            page.locator('#ai-fab').click()
                            expect(page.locator('#ai-widget-input')).to_be_visible()
                            expect(page.locator('#ai-widget')).to_have_css('opacity', '1')
                            expect(page.locator('#ai-widget-input')).to_have_attribute('placeholder', 'Type an idea or question...')
                            expect(page.locator('#ai-widget-input')).to_have_css('padding-left', '2px')
                            expect(page.locator('.ai-suggestion-chips .ai-chip')).to_have_count(3)
                            expect(page.locator('.ai-chat-header h3')).to_have_text('Balloorina AI')
                            expect(page.locator('.ai-chat-header p')).to_have_text('Backdrop ideas & event help')
                            expect(page.locator('.ai-chat-header #ai-guide-open')).to_have_text('Design guide')
                            expect(page.locator('.ai-chat-header #ai-guide-example')).to_have_text('Sample description')
                            expect(page.locator('#ai-guide-open svg')).to_have_count(2)
                            expect(page.locator('#ai-close svg')).to_have_count(1)
                            expect(page.locator('#ai-close')).to_have_css('width', '40px')
                            expect(page.locator('#ai-widget .ai-input-area')).to_have_css('border-radius', '10px')
                            expect(page.locator('.ai-recent-chat-delete svg')).to_have_count(1)
                            expect(page.locator('.ai-recent-chat-delete svg')).to_have_css('width', '14px')
                            expect(page.locator('#ai-new-chat svg')).to_have_css('width', '16px')
                            if width == 1440:
                                page.locator('.ai-recent-chat-delete').hover()
                                expect(page.locator('.ai-recent-chat-delete')).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
                            for control in ('#ai-widget-photo', '#ai-widget-mic', '#ai-widget-send'):
                                expect(page.locator(control)).to_have_css('border-radius', '6px')
                            for control in ('#ai-widget-photo', '#ai-widget-mic'):
                                page.mouse.move(0, 0)
                                expect(page.locator(control)).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
                                page.locator(control).hover()
                                expect(page.locator(control)).to_have_css('background-color', 'rgb(229, 231, 235)' if theme == 'light' else 'rgb(42, 42, 42)')
                            page.mouse.move(0, 0)
                            delete_color = page.locator('.ai-recent-chat-delete').evaluate('(el) => getComputedStyle(el).color.match(/\\d+/g).map(Number)')
                            self.assertEqual(len(set(delete_color)), 1)
                            # Header changes are intentional; the existing chat controls retain their styles.
                            chat_styles = page.evaluate('''() => {
                                const selectors = ['#ai-widget', '#ai-fab', '.ai-message-bubble', '.ai-new-chat-btn',
                                    '.ai-chip', '.ai-suggestion-chips'];
                                const properties = ['fontSize', 'fontFamily', 'lineHeight', 'padding',
                                    'borderRadius', 'minWidth', 'minHeight', 'color', 'backgroundColor',
                                    'display', 'gap', 'flexWrap', 'overflowX', 'overflowY'];
                                const read = () => Object.fromEntries(selectors.map(selector => {
                                    const style = getComputedStyle(document.querySelector(selector));
                                    return [selector, Object.fromEntries(properties.map(key => [key, style[key]]))];
                                }));
                                const stylesheet = document.querySelector('link[href*="ai_design_guide.css"]');
                                const withGuide = read();
                                stylesheet.disabled = true;
                                const original = read();
                                stylesheet.disabled = false;
                                return {withGuide, original};
                            }''')
                            self.assertEqual(chat_styles['withGuide'], chat_styles['original'])
                            page.screenshot(path=str(screenshots / f'ai-header-english-{width}-{theme}.png'), animations='disabled')
                            page.locator('#ai-widget-input').fill('Unfinished message')
                            page.locator('#ai-guide-open').click()
                            expect(page.locator('#ai-guide-title')).to_be_focused()
                            expect(page.locator('#ai-design-guide')).to_have_attribute('lang', 'en')
                            expect(page.locator('#ai-guide-title')).to_have_text("What's the occasion?")
                            expect(page.locator('[name="guide_occasion"]').first).to_have_css('appearance', 'none')
                            expect(page.locator('[name="guide_occasion"]').first).to_have_css('background-color', 'rgb(255, 255, 255)' if theme == 'light' else 'rgb(0, 0, 0)')
                            expect(page.locator('.ai-guide-content')).to_have_css('scrollbar-width', 'thin')
                            self.assertEqual(page.locator('#ai-design-guide').evaluate('(el) => getComputedStyle(el).padding'), '0px')
                            page.screenshot(path=str(screenshots / f'ai-guide-occasion-{width}-{theme}.png'))
                            expect(page.locator('#ai-widget-input')).to_be_hidden()
                            self.assertEqual(sent, [])
                            page.locator('#ai-guide-next').click()
                            expect(page.locator('#ai-guide-error')).to_contain_text('Choose an occasion')
                            expect(page.locator('[name="guide_occasion"]').first).to_be_focused()
                            page.locator('[name="guide_occasion"][value="other"]').check()
                            page.locator('#ai-guide-next').click()
                            expect(page.locator('#ai-guide-other')).to_be_focused()
                            expect(page.locator('#ai-guide-other')).to_have_css('outline-color', 'rgb(107, 107, 107)' if theme == 'light' else 'rgb(176, 176, 176)')
                            page.screenshot(path=str(screenshots / f'ai-guide-monochrome-focus-{width}-{theme}.png'), animations='disabled')
                            page.locator('#ai-guide-other').fill('Graduation')
                            # Keyboard activation of next works as well as touch/click.
                            page.locator('#ai-guide-next').focus()
                            page.keyboard.press('Enter')
                            expect(page.locator('#ai-guide-progress')).to_contain_text('Step 2 of 4')
                            page.locator('#ai-guide-suggest').click()
                            expect(page.locator('.ai-guide-style-choice')).to_have_count(3)
                            previous = set(page.locator('.ai-guide-style-choice strong').all_text_contents())
                            page.locator('#ai-guide-suggest').click()
                            following = set(page.locator('.ai-guide-style-choice strong').all_text_contents())
                            self.assertEqual(len(following), 3)
                            self.assertFalse(previous & following)
                            expect(page.locator('#ai-guide-theme')).to_have_value('')
                            chosen_theme = page.locator('.ai-guide-style-choice strong').first.inner_text()
                            chosen_colors = page.locator('.ai-guide-style-choice small').first.inner_text()
                            page.locator('.ai-guide-style-choice').first.click()
                            expect(page.locator('#ai-guide-theme')).to_have_value(chosen_theme)
                            page.locator('#ai-guide-suggest').click()
                            self.assertFalse(following & set(page.locator('.ai-guide-style-choice strong').all_text_contents()))
                            expect(page.locator('#ai-guide-theme')).to_have_value(chosen_theme)
                            expect(page.locator('#ai-guide-colors')).to_have_value(chosen_colors)
                            if width == 1440:
                                page.locator('#ai-guide-theme').fill('Spider-Man')
                                page.locator('#ai-guide-colors').fill('blue')
                            page.screenshot(path=str(screenshots / f'ai-guide-style-{width}-{theme}.png'))
                            self.assertEqual(sent, [])
                            page.locator('#ai-guide-next').click()
                            page.locator('#ai-guide-name').fill('Sofia')
                            page.locator('#ai-guide-age').fill('21')
                            page.locator('#ai-guide-details').fill('Add floral decorations and a balloon garland.')
                            page.locator('#ai-guide-next').click()
                            preview = page.locator('#ai-guide-preview')
                            self.assertIn('Graduation', preview.input_value())
                            if width == 1440:
                                self.assertIn('with a Spider-Man theme in blue.', preview.input_value())
                            else:
                                self.assertIn(f'with a {chosen_theme} theme in {chosen_colors}.', preview.input_value())
                            self.assertIn('Sofia', preview.input_value())
                            self.assertTrue(preview.input_value().startswith('Create a balloon backdrop design'))
                            self.assertNotIn('\n', preview.input_value())
                            self.assertNotIn('Theme:', preview.input_value())
                            edited = preview.input_value() + ' Keep it elegant and simple.'
                            preview.fill(edited)
                            page.locator('#ai-guide-back').click()
                            page.locator('#ai-guide-next').click()
                            expect(preview).to_have_value(edited)
                            # Closing and reopening preserves both the guide and ordinary chat drafts.
                            page.keyboard.press('Escape')
                            expect(page.locator('#ai-guide-open')).to_be_focused()
                            expect(page.locator('#ai-widget-input')).to_have_value('Unfinished message')
                            page.locator('#ai-guide-open').click()
                            expect(preview).to_have_value(edited)
                            page.locator('#ai-guide-open').click()
                            expect(page.locator('#ai-design-guide')).to_be_hidden()
                            page.locator('#ai-guide-open').click()
                            expect(preview).to_have_value(edited)
                            for selector in ('#ai-guide-next', '#ai-guide-back'):
                                self.assertGreaterEqual(page.locator(selector).bounding_box()['height'], 36)
                                self.assertLessEqual(page.locator(selector).bounding_box()['height'], 40)
                            self.assertLessEqual(page.locator('#ai-design-guide').evaluate('(el) => el.scrollWidth - el.clientWidth'), 1)
                            self.assertLessEqual(page.locator('.ai-guide-body').evaluate('(el) => el.scrollWidth - el.clientWidth'), 1)
                            button = page.locator('#ai-guide-next').bounding_box()
                            self.assertLessEqual(button['y'] + button['height'], height)
                            self.assertEqual(preview.evaluate('(el) => getComputedStyle(el).fontSize'), '16px' if width <= 480 else '13px')
                            page.screenshot(path=str(screenshots / f'ai-guide-review-{width}-{theme}.png'))
                            preview.fill(' ')
                            page.locator('#ai-guide-next').click()
                            expect(page.locator('#ai-guide-error')).to_contain_text('Add a description')
                            expect(preview).to_be_focused()
                            preview.fill(edited)
                            self.assertEqual(sent, [])
                            page.locator('#ai-guide-next').click()
                            expect(page.locator('#ai-design-guide')).to_be_hidden()
                            expect(page.locator('#ai-chat-box')).to_contain_text('Your design idea is ready.')
                            self.assertEqual(len(sent), 1)
                            self.assertEqual(sent[0]['message'], edited)
                            edit = page.get_by_role('button', name='Edit this design')
                            expect(edit).to_be_visible()
                            edit_box, like_box = page.evaluate('''() => ['.ai-design-actions button', '.ai-fb-like'].map(selector => {
                                const rect = document.querySelector(selector).getBoundingClientRect();
                                return {x: rect.x, y: rect.y, height: rect.height};
                            })''')
                            self.assertLessEqual(abs(edit_box['y'] + edit_box['height'] / 2 - like_box['y'] - like_box['height'] / 2), 1)
                            self.assertLess(edit_box['x'], like_box['x'])
                            self.assertEqual(page.locator('.ai-design-actions').evaluate('(el) => el.parentElement.className'), 'ai-feedback-row')
                            for feedback in ('.ai-fb-like', '.ai-fb-dislike'):
                                page.locator(feedback).hover()
                                expect(page.locator(feedback)).to_have_css('color', 'rgb(32, 32, 32)' if theme == 'light' else 'rgb(255, 255, 255)')
                            if width in (1440, 320):
                                page.locator('.ai-fb-like').click()
                                expect(page.locator('.ai-fb-like')).to_have_css('color', 'rgb(21, 128, 61)' if theme == 'light' else 'rgb(34, 197, 94)')
                            else:
                                page.locator('.ai-fb-dislike').click()
                                expect(page.locator('.ai-fb-dislike')).to_have_css('color', 'rgb(185, 28, 28)' if theme == 'light' else 'rgb(239, 68, 68)')
                            expect(page.locator('#ai-chat-box .ai-user-msg').last).to_have_text(edited)
                            page.screenshot(path=str(screenshots / f'ai-guide-chat-message-{width}-{theme}.png'), animations='disabled')
                            expect(page.locator('#ai-widget-input')).to_have_value('Unfinished message')
                            # Sample fills the composer; it never starts generation automatically.
                            page.locator('#ai-guide-open').click()
                            page.locator('#ai-guide-example').click()
                            expect(page.locator('#ai-design-guide')).to_be_hidden()
                            self.assertIn('Unfinished message', page.locator('#ai-widget-input').input_value())
                            self.assertIn('butterfly', page.locator('#ai-widget-input').input_value())
                            self.assertEqual(len(sent), 1)
                            # Another saved request sends the reviewed guide, preserving the composer draft.
                            fallback = True
                            page.locator('#ai-guide-open').click()
                            page.locator('#ai-guide-next').click()
                            expect(page.locator('#ai-chat-box')).to_contain_text('Your fallback design is ready.')
                            self.assertEqual(len(sent), 2)
                            self.assertEqual(sent[-1]['message'], edited)
                            expect(page.locator('#ai-chat-box .ai-user-msg')).to_have_count(2)
                            self.assertIn('Unfinished message', page.locator('#ai-widget-input').input_value())
                            # A larger text setting keeps the guide scrollable and its action reachable.
                            if width == 390:
                                page.evaluate('document.documentElement.style.fontSize = "200%"')
                                page.locator('#ai-guide-open').click()
                                self.assertLessEqual(page.locator('.ai-guide-body').evaluate('(el) => el.scrollWidth - el.clientWidth'), 1)
                                action = page.locator('#ai-guide-next').bounding_box()
                                self.assertLessEqual(action['y'] + action['height'], height)
                                page.screenshot(path=str(screenshots / f'ai-guide-large-text-{theme}.png'))
                                page.locator('#ai-guide-exit').click()
                                page.evaluate('document.documentElement.style.fontSize = ""')
                            # Actual server warning templates stay legible live and after history reload.
                            for moderation_stage in (1, 2):
                                page.locator('#ai-widget-input').fill('Moderation UI test')
                                page.locator('#ai-widget-send').click()
                                expect(page.locator('.ai-warning-msg')).to_have_count(moderation_stage)
                            notice = page.locator('.ai-bot-msg:has(.ai-moderation-content)').last
                            expect(notice).to_have_css('color', 'rgb(117, 45, 38)' if theme == 'light' else 'rgb(243, 196, 191)')
                            page.screenshot(path=str(screenshots / f'ai-warnings-{width}-{theme}.png'), animations='disabled')
                            moderation_history = True
                            page.reload(wait_until='domcontentloaded')
                            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                            page.locator('#ai-fab').click()
                            expect(page.locator('.ai-moderation-content')).to_have_count(2)
                            notice = page.locator('.ai-bot-msg:has(.ai-moderation-content)').last
                            expect(notice).to_have_css('color', 'rgb(117, 45, 38)' if theme == 'light' else 'rgb(243, 196, 191)')
                            moderation_stage = 3
                            page.locator('#ai-widget-input').fill('Ban notice UI test')
                            page.locator('#ai-widget-send').click()
                            expect(page.locator('#ai-ban-overlay')).to_be_visible()
                            expect(page.locator('#ai-widget-input')).to_be_disabled()
                            expect(page.locator('#ai-ban-title')).to_have_text('Chat temporarily paused')
                            expect(page.locator('.ai-ban-card')).to_have_css('background-color', 'rgb(255, 255, 255)' if theme == 'light' else 'rgb(23, 23, 23)')
                            expect(page.locator('#ai-ban-title')).to_have_css('color', 'rgb(32, 32, 32)' if theme == 'light' else 'rgb(245, 245, 245)')
                            header_box = page.locator('.ai-chat-header').bounding_box()
                            self.assertGreaterEqual(page.locator('#ai-ban-overlay').bounding_box()['y'], header_box['y'] + header_box['height'] - 1)
                            self.assertLessEqual(page.locator('.ai-ban-card').evaluate('(el) => el.scrollWidth - el.clientWidth'), 1)
                            page.screenshot(path=str(screenshots / f'ai-ban-notice-{width}-{theme}.png'), animations='disabled')
                            page.locator('#ai-close').click()
                            expect(page.locator('#ai-widget')).to_be_hidden()
                            expect(page.locator('#ai-fab')).to_be_visible()
                            self.assertEqual(errors, [])
                            context.close()
            finally:
                browser.close()
