"""Optional real-browser support tests, using two independent signed-in accounts."""
import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse

from .models import ChatMessage, ChatSession, User


@skipUnless(os.environ.get('RUN_SUPPORT_CHAT_BROWSER') == '1', 'Optional support chat browser checks')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SupportChatBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='support-browser-admin', role='admin', email_verified=True)
        self.customer = User.objects.create_user(username='support-browser-customer', first_name='Jamie', last_name='Rivera', role='customer', email_verified=True)
        self.other = User.objects.create_user(username='support-browser-other', first_name='Taylor', role='customer', email_verified=True)
        self.session = ChatSession.objects.create(user=self.customer, assigned_admin=self.admin, status='active_admin', is_admin_support=True)
        self.second = ChatSession.objects.create(user=self.other, assigned_admin=self.admin, status='active_admin', is_admin_support=True)
        ChatMessage.objects.bulk_create([ChatMessage(session=self.session, sender=self.customer, receiver=self.admin, message=f'Customer note {n}') for n in range(56)])
        first = self.session.messages.order_by('pk').first()
        first.is_pinned = True; first.pinned_by = self.customer; first.save(update_fields=['is_pinned', 'pinned_by'])
        self.artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'
        self.cookies = {}
        for user in (self.admin, self.customer):
            client = Client(); client.force_login(user)
            self.cookies[user.pk] = client.cookies[settings.SESSION_COOKIE_NAME].value

    def context(self, browser, user):
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.cookies[user.pk], 'url': self.live_server_url}])
        context.add_init_script("localStorage.setItem('balloorina-theme','light')")
        context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        context.route('https://cdnjs.cloudflare.com/**', lambda route: route.abort())
        context.route('https://cdn.jsdelivr.net/**', lambda route: route.fulfill(status=200, content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}})};'))
        return context

    def test_async_inbox_thread_drafts_reply_retry_search_and_customer_updates(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            admin_context = self.context(browser, self.admin); client_context = self.context(browser, self.customer)
            admin = admin_context.new_page(); customer = client_context.new_page(); errors = []; documents = []
            for page in (admin, customer):
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
            try:
                admin.goto(self.live_server_url + reverse('admin_chat_inbox'))
                expect(admin.locator('[data-session-link]')).to_have_count(2)
                admin.locator(f'[data-session-link="{self.session.pk}"]').click()
                expect(admin.locator('[data-message]')).to_have_count(50)
                unchanged = admin.locator('[data-message]').last
                unchanged.evaluate('(el)=>el.keepExistingNode=true')
                admin.get_by_label('Message', exact=True).fill('Preserve row identity')
                admin.wait_for_timeout(5000)
                self.assertTrue(unchanged.evaluate('(el)=>el.keepExistingNode===true'))
                admin.get_by_role('button', name='Conversation details', exact=True).click()
                admin.locator('.sc-pin-item').filter(has_text='Customer note 0').click()
                expect(admin.locator('[data-message]')).to_have_count(56)
                admin.get_by_label('Message', exact=True).fill('Draft for Jamie')
                admin.locator(f'[data-session-link="{self.second.pk}"]').click()
                expect(admin.get_by_label('Message', exact=True)).to_have_value('')
                admin.locator(f'[data-session-link="{self.session.pk}"]').click()
                expect(admin.get_by_label('Message', exact=True)).to_have_value('Draft for Jamie')
                # Required validation is inline, with the draft retained on network failure.
                admin.get_by_label('Message', exact=True).fill('')
                admin.get_by_role('button', name='Send message', exact=True).click()
                expect(admin.locator('[data-error]')).to_contain_text('Write a message')
                admin.get_by_label('Message', exact=True).fill('Hello Jamie, happy to help.')
                # Simulate a saved send whose response is lost, then retry the same token.
                def lose_response(route):
                    route.fetch(); route.abort()
                admin.route('**/api/support/send/', lose_response, times=1)
                admin.get_by_role('button', name='Send message', exact=True).click()
                expect(admin.locator('[data-error]')).to_contain_text('Could not connect')
                expect(admin.get_by_label('Message', exact=True)).to_have_value('Hello Jamie, happy to help.')
                admin.get_by_role('button', name='Send message', exact=True).click()
                expect(admin.get_by_label('Message', exact=True)).to_have_value('')
                state = admin.request.get(self.live_server_url + reverse('support_state') + f'?session_id={self.session.pk}').json()
                self.assertEqual(sum(message['content'] == 'Hello Jamie, happy to help.' for message in state['messages']), 1)
                customer.goto(self.live_server_url + reverse('home'))
                customer.get_by_role('button', name='Chat with admin', exact=True).click()
                expect(customer.locator('.sc-message-text').last).to_have_text('Hello Jamie, happy to help.')
                customer.get_by_label('Message', exact=True).fill('Thank you, support!')
                customer.get_by_role('button', name='Send message', exact=True).click()
                expect(customer.get_by_label('Message', exact=True)).to_have_value('')
                admin.bring_to_front()
                expect(admin.locator('.sc-message-text').last).to_have_text('Thank you, support!', timeout=15000)
                admin.get_by_role('button', name='Search this conversation', exact=True).click()
                admin.get_by_label('Search messages', exact=True).fill('Customer note 0')
                expect(admin.locator('[data-message]')).to_have_count(1)
                admin.get_by_role('button', name='Clear message search', exact=True).click()
                expect(admin.locator('[data-message]')).to_have_count(50)
                admin.get_by_role('button', name='Search this conversation', exact=True).click()
                self.assertEqual(len(documents), 2)
                self.assertEqual(errors, [])
            finally:
                admin_context.close(); client_context.close(); browser.close()

    def test_light_dark_responsive_modals_uploads_and_message_actions(self):
        from playwright.sync_api import expect, sync_playwright
        from .test_support_chat import photo
        image = photo()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = self.context(browser, self.admin); page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(self.live_server_url + reverse('admin_chat_thread', args=[self.session.pk]))
                expect(page.locator('[data-message]')).to_have_count(50)
                page.locator('[data-file]').set_input_files({'name': 'reference.png', 'mimeType': 'image/png', 'buffer': image.read()})
                expect(page.locator('.sc-attachment')).to_have_count(1)
                page.get_by_label('Message', exact=True).fill('Reference image')
                page.get_by_role('button', name='Send message', exact=True).click()
                expect(page.get_by_label('Message', exact=True)).to_have_value('')
                expect(page.locator('.sc-message-photo')).to_have_count(1)
                own = page.locator('.sc-message.sc-own').filter(has_text='Reference image')
                own.get_by_role('button', name='Message options', exact=True).click()
                own.get_by_role('button', name='Edit message', exact=True).click()
                page.get_by_label('Message', exact=True).fill('Updated reference')
                page.get_by_role('button', name='Send message', exact=True).click()
                expect(page.locator('.sc-message-text').filter(has_text='Updated reference')).to_have_count(1)
                own = page.locator('.sc-message.sc-own').filter(has_text='Updated reference')
                own.get_by_role('button', name='Message options', exact=True).click()
                own.get_by_role('button', name='Pin message', exact=True).click()
                expect(page.locator('[data-pins]')).to_be_visible()
                page.get_by_role('button', name='Conversation details', exact=True).click()
                expect(page.locator('[data-dialog]')).to_be_visible()
                expect(page.locator('.sc-media-grid img')).to_have_count(1)
                page.get_by_role('button', name='Done', exact=True).click()
                for theme in ('light', 'dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                    bubble_text = page.locator('.sc-message-text').filter(has_text='Updated reference')
                    self.assertEqual(bubble_text.evaluate('(el)=>getComputedStyle(el).color'), 'rgb(255, 255, 255)' if theme == 'light' else 'rgb(24, 24, 24)')
                    header_font = page.locator('.admin-topbar .admin-avatar').evaluate('el=>getComputedStyle(el).fontFamily')
                    for avatar in page.locator('.sc-avatar').all():
                        self.assertEqual(avatar.evaluate('el=>getComputedStyle(el).color'), 'rgb(255, 255, 255)' if theme == 'light' else 'rgb(24, 24, 24)')
                        self.assertEqual(avatar.evaluate('el=>getComputedStyle(el).fontFamily'), header_font)
                        self.assertEqual(avatar.evaluate('el=>getComputedStyle(el).fontWeight'), '600')
                    for width in (1920, 1440, 768, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 1000}); page.wait_for_timeout(180)
                        self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'), f'{theme}/{width}')
                        self.assertGreater(page.locator('.sc-compose-field').bounding_box()['width'], 150)
                        page.screenshot(path=str(self.artifacts / f'support-admin-{theme}-{width}.png'), full_page=True, animations='disabled')
                    page.get_by_label('Message', exact=True).focus()
                    self.assertEqual(page.locator('.sc-compose-field').evaluate('(el)=>getComputedStyle(el).outlineStyle'), 'solid')
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.get_by_role('button', name='View attachment', exact=True).click()
                expect(page.locator('.sc-preview-image')).to_be_visible()
                page.get_by_role('button', name='Close dialog', exact=True).click()
                page.locator('.sc-message.sc-own').filter(has_text='Updated reference').get_by_role('button', name='Message options', exact=True).click()
                page.get_by_role('button', name='Delete message', exact=True).click()
                page.locator('[data-dialog]').get_by_role('button', name='Delete message', exact=True).click()
                expect(page.locator('.sc-message.sc-deleted')).to_have_count(1)
                self.assertEqual(errors, [])
            finally: context.close(); browser.close()

    def test_admin_fullscreen_preserves_chat_and_handles_keyboard_and_mobile(self):
        from playwright.sync_api import expect, sync_playwright
        from .test_support_chat import photo
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = self.context(browser, self.admin); page = context.new_page(); errors = []; documents = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
            # Track the first visible message, including its offset inside the scroll area.
            reading_position = '''el => {
                const top = el.getBoundingClientRect().top;
                const row = [...el.querySelectorAll('[data-message]')].find(row => row.getBoundingClientRect().bottom > top);
                return {id: row?.dataset.message, offset: row ? row.getBoundingClientRect().top - top : 0};
            }'''
            try:
                page.goto(self.live_server_url + reverse('admin_chat_inbox'))
                expect(page.locator('[data-session-link]')).to_have_count(2)
                enter = page.get_by_role('button', name='Enter full screen', exact=True)
                enter.click()
                full = page.get_by_role('dialog', name='Full-screen support inbox', exact=True)
                expect(full).to_be_visible()
                expect(full.locator('[data-welcome]')).to_be_visible()
                # Native modality keeps keyboard users out of the covered admin navigation.
                for _ in range(10):
                    page.keyboard.press('Tab')
                    # Chrome may move focus to its address bar at the tab boundary.
                    self.assertTrue(page.evaluate('!document.hasFocus() || !!document.activeElement.closest(".sc-fullscreen-dialog")'))
                self.assertFalse(page.locator('#adminSidebar a').first.evaluate('el => {el.focus(); return document.activeElement === el;}'))
                page.get_by_role('button', name='Exit full screen', exact=True).focus()
                page.keyboard.press('Escape')
                expect(enter).to_be_focused()
                expect(full).to_have_count(0)
                page.locator(f'[data-session-link="{self.session.pk}"]').click()
                expect(page.locator('[data-message]')).to_have_count(50)
                message = page.get_by_label('Message', exact=True)
                message.fill('Draft stays with its photo')
                message.evaluate('el => el.originalChatInput = true')
                page.locator('[data-file]').set_input_files({'name': 'fullscreen-photo.png', 'mimeType': 'image/png', 'buffer': photo().read()})
                history = page.locator('[data-history]')
                page.wait_for_timeout(250)  # Let newly fetched message entrances finish before measuring their positions.
                history.evaluate('el => el.scrollTop = 400')
                before = history.evaluate(reading_position)
                page_scroll = page.evaluate('scrollY')
                enter.click()
                expect(full).to_be_visible()
                expect(message).to_have_value('Draft stays with its photo')
                self.assertTrue(message.evaluate('el => el.originalChatInput === true'))
                expect(page.locator('.sc-attachment')).to_have_count(1)
                after = history.evaluate(reading_position)
                self.assertEqual(after['id'], before['id'])
                self.assertLess(abs(after['offset'] - before['offset']), 2)
                self.assertEqual(page.evaluate('getComputedStyle(document.documentElement).overflowY'), 'hidden')
                # Changing conversations in full screen retains each draft as in normal mode.
                page.locator(f'[data-session-link="{self.second.pk}"]').click()
                expect(message).to_have_value('')
                page.locator(f'[data-session-link="{self.session.pk}"]').click()
                expect(message).to_have_value('Draft stays with its photo')
                expect(page.locator('.sc-attachment')).to_have_count(1)
                message.fill('Sent in full screen')
                page.get_by_role('button', name='Send message', exact=True).click()
                expect(message).to_have_value('')
                expect(page.locator('.sc-message-text').filter(has_text='Sent in full screen')).to_have_count(1)
                expect(full).to_be_visible()
                # Escape dismisses the image/details dialog or message menu first.
                page.get_by_role('button', name='Conversation details', exact=True).click()
                expect(page.locator('.sc-media-grid img')).to_have_count(1)
                page.locator('.sc-media-grid button').click()
                expect(page.locator('.sc-preview-image')).to_be_visible()
                page.keyboard.press('Escape')
                expect(page.locator('[data-dialog]')).not_to_be_visible()
                expect(full).to_be_visible()
                own = page.locator('.sc-message.sc-own').filter(has_text='Sent in full screen')
                own.get_by_role('button', name='Message options', exact=True).click()
                expect(own.locator('.sc-message-menu')).to_be_visible()
                page.keyboard.press('Escape')
                expect(own.locator('.sc-message-menu')).to_have_count(0)
                expect(full).to_be_visible()
                history.evaluate('el => el.scrollTop = 600')
                before = history.evaluate(reading_position)
                page.get_by_role('button', name='Exit full screen', exact=True).click()
                expect(enter).to_be_focused()
                after = history.evaluate(reading_position)
                self.assertEqual(after['id'], before['id'])
                self.assertLess(abs(after['offset'] - before['offset']), 2)
                self.assertEqual(page.evaluate('scrollY'), page_scroll)
                enter.click()
                for theme in ('light', 'dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                    header_font = page.locator('.admin-topbar .admin-avatar').evaluate('el=>getComputedStyle(el).fontFamily')
                    for avatar in page.locator('.sc-avatar').all():
                        self.assertEqual(avatar.evaluate('el=>getComputedStyle(el).color'), 'rgb(255, 255, 255)' if theme == 'light' else 'rgb(24, 24, 24)')
                        self.assertEqual(avatar.evaluate('el=>getComputedStyle(el).fontFamily'), header_font)
                    for width in (1440, 768, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 700})
                        bounds = full.bounding_box()
                        self.assertEqual(bounds['x'], 0)
                        self.assertEqual(bounds['y'], 0)
                        self.assertEqual(bounds['width'], width)
                        self.assertEqual(bounds['height'], 700)
                        self.assertFalse(full.evaluate('el => el.scrollWidth > el.clientWidth'))
                        composer = page.locator('.sc-compose-field').bounding_box()
                        self.assertLess(composer['y'] + composer['height'], 700)
                        expect(page.get_by_role('button', name='Exit full screen', exact=True)).to_be_visible()
                        page.screenshot(path=str(self.artifacts / f'support-fullscreen-{theme}-{width}.png'), animations='disabled')
                page.get_by_role('button', name='Back to conversations', exact=True).click()
                expect(full.locator('.sc-inbox')).to_be_visible()
                page.locator(f'[data-session-link="{self.second.pk}"]').click()
                expect(full.locator('[data-name]')).to_have_text('Taylor')
                page.emulate_media(reduced_motion='reduce')
                self.assertEqual(page.locator('.sc-fullscreen').evaluate('el=>getComputedStyle(el).animationName'), 'none')
                page.keyboard.press('Escape')
                expect(full).to_have_count(0)
                expect(enter).to_be_focused()
                self.assertEqual(len(documents), 1)
                self.assertEqual(errors, [])
            finally:
                page.screenshot(path=str(self.artifacts / 'support-fullscreen-final.png'), animations='disabled')
                context.close(); browser.close()

    def test_feedback_and_dialog_spacing_in_both_themes(self):
        from playwright.sync_api import expect, sync_playwright
        from .test_support_chat import photo
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = self.context(browser, self.admin); page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(self.live_server_url + reverse('admin_chat_thread', args=[self.session.pk]))
                expect(page.locator('[data-message]')).to_have_count(50)
                page.locator('[data-file]').set_input_files({'name': 'shared-photo.png', 'mimeType': 'image/png', 'buffer': photo().read()})
                page.get_by_role('button', name='Send message', exact=True).click()
                expect(page.locator('.sc-message-photo')).to_have_count(1)
                # Feedback must not depend on another page's workspace stylesheet.
                self.assertEqual(page.locator('link[href*="admin_concerns_workspace.css"]').count(), 0)
                for theme in ('light', 'dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                    for width in (1440, 390):
                        page.set_viewport_size({'width': width, 'height': 700})
                        for kind in ('success', 'error'):
                            page.evaluate('(kind)=>AdminConfigurationFeedback.show(kind === "success" ? "Message unpinned." : "Could not save this change. Try again.", kind)', kind)
                            toast = page.locator('.cfg-toast')
                            expect(toast).to_be_visible()
                            page.wait_for_timeout(260)
                            styles = toast.evaluate('''el => {
                                const style = getComputedStyle(el), icon = getComputedStyle(el.querySelector('svg'));
                                return {background: style.backgroundColor, border: style.borderTopColor,
                                    color: getComputedStyle(el.querySelector('.cfg-toast-text')).color,
                                    fill: icon.fill, stroke: icon.stroke};
                            }''')
                            self.assertEqual(styles['background'], 'rgb(255, 255, 255)' if theme == 'light' else 'rgb(32, 32, 32)')
                            self.assertNotEqual(styles['color'], styles['background'])
                            self.assertNotEqual(styles['border'], styles['background'])
                            self.assertEqual(styles['fill'], 'none')
                            expected_stroke = {'light': {'success': 'rgb(24, 116, 71)', 'error': 'rgb(184, 53, 60)'},
                                               'dark': {'success': 'rgb(123, 212, 161)', 'error': 'rgb(241, 145, 145)'}}
                            self.assertEqual(styles['stroke'], expected_stroke[theme][kind])
                            bounds = toast.bounding_box()
                            self.assertGreaterEqual(bounds['x'], 0)
                            self.assertLessEqual(bounds['x'] + bounds['width'], width)
                            self.assertLess(bounds['y'], 100)
                            page.screenshot(path=str(self.artifacts / f'support-feedback-{theme}-{width}-{kind}.png'), animations='disabled')
                            toast.get_by_role('button', name='Dismiss notification').click()
                            expect(toast).to_be_hidden()
                        page.get_by_role('button', name='Conversation details', exact=True).click()
                        expect(page.locator('.sc-media-grid img')).to_have_count(1)
                        body = page.locator('[data-dialog-body]')
                        body.evaluate('el => el.scrollTop = el.scrollHeight')
                        footer = page.locator('[data-dialog-footer]')
                        button_bounds = footer.get_by_role('button', name='Done', exact=True).bounding_box()
                        body_bounds = body.bounding_box()
                        self.assertGreaterEqual(button_bounds['y'] - body_bounds['y'] - body_bounds['height'], 11)
                        page.screenshot(path=str(self.artifacts / f'support-dialog-footer-{theme}-{width}.png'), animations='disabled')
                        footer.get_by_role('button', name='Done', exact=True).click()
                        page.get_by_role('button', name='View attachment', exact=True).click()
                        download = page.get_by_role('link', name='Download image', exact=True)
                        expect(download).to_be_visible()
                        self.assertEqual(download.evaluate('el=>getComputedStyle(el).textDecorationLine'), 'none')
                        download.hover()
                        self.assertEqual(download.evaluate('el=>getComputedStyle(el).textDecorationLine'), 'none')
                        page.screenshot(path=str(self.artifacts / f'support-image-dialog-{theme}-{width}.png'), animations='disabled')
                        page.get_by_role('button', name='Close dialog', exact=True).click()
                self.assertEqual(errors, [])
            finally: context.close(); browser.close()

    def test_customer_mobile_themes_attachments_validation_draft_and_notification_link(self):
        from playwright.sync_api import expect, sync_playwright
        from .test_support_chat import photo
        image = photo().read()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = self.context(browser, self.customer); page = context.new_page(); errors = []; documents = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
            try:
                page.goto(self.live_server_url + reverse('client_chat_page'))
                expect(page.locator('#adminChatPanel')).to_be_visible()
                expect(page.locator('[data-message]')).to_have_count(50)
                for theme in ('light', 'dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                    page.get_by_role('button', name='Send message', exact=True).click()
                    expect(page.locator('[data-error]')).to_contain_text('Write a message')
                    self.assertEqual(page.locator('[data-error]').evaluate('(el)=>getComputedStyle(el).color'), 'rgb(217, 57, 69)' if theme == 'light' else 'rgb(251, 146, 146)')
                    own_text = page.locator('.sc-own .sc-message-text').last
                    self.assertEqual(own_text.evaluate('(el)=>getComputedStyle(el).color'), 'rgb(255, 255, 255)' if theme == 'light' else 'rgb(24, 24, 24)')
                    for width in (1440, 768, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 1000}); page.wait_for_timeout(100)
                        self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'), f'Customer overflow {theme}/{width}')
                        panel = page.locator('#adminChatPanel').bounding_box()
                        header = page.locator('.sc-room-head').bounding_box()
                        self.assertLess(abs(header['y'] - panel['y']), 5)
                        field = page.locator('.sc-compose-field').bounding_box()
                        self.assertGreater(field['width'], 180)
                        self.assertLess(field['y'] + field['height'], 1000)
                        page.screenshot(path=str(self.artifacts / f'support-customer-{theme}-{width}.png'), animations='disabled')
                page.locator('[data-file]').set_input_files({'name': 'bad.svg', 'mimeType': 'image/svg+xml', 'buffer': b'<svg/>'})
                expect(page.locator('[data-error]')).to_contain_text('Choose JPG')
                files = [{'name': f'image-{n}.png', 'mimeType': 'image/png', 'buffer': image} for n in range(4)]
                page.locator('[data-file]').set_input_files(files)
                expect(page.locator('.sc-attachment')).to_have_count(4)
                page.locator('[data-file]').set_input_files(files[:1])
                expect(page.locator('[data-error]')).to_contain_text('up to 4')
                expect(page.locator('.sc-attachment')).to_have_count(4)
                page.get_by_role('button', name='Remove image-0.png', exact=True).click()
                expect(page.locator('.sc-attachment')).to_have_count(3)
                page.get_by_label('Message', exact=True).fill('Keep this draft')
                page.get_by_role('button', name='Close admin chat', exact=True).click()
                page.get_by_role('button', name='Chat with admin', exact=True).click()
                expect(page.get_by_label('Message', exact=True)).to_have_value('Keep this draft')
                expect(page.locator('.sc-attachment')).to_have_count(3)
                page.get_by_role('button', name='Conversation details', exact=True).click()
                expect(page.locator('[data-dialog]')).to_be_visible()
                self.assertEqual(page.locator('[data-dialog-footer]').evaluate('el=>getComputedStyle(el).paddingTop'), '12px')
                page.get_by_role('button', name='Close dialog', exact=True).click()
                self.assertEqual(errors, [])
                # Only the notification's HTTP redirect navigated; chat operations did not.
                self.assertLessEqual(len(documents), 2)
            finally: context.close(); browser.close()
