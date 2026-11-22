"""Verify the invitation's timing and the real launcher without AI inference."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import User


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class AIInviteBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright

        user = User.objects.create_user(username='ai-invite-customer', role='customer', email_verified=True)
        self.client.force_login(user)
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
        self.browser = self.playwright.chromium.launch(executable_path=str(executable), headless=True)
        self.addCleanup(self.browser.close)
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.context.add_init_script("sessionStorage.setItem('balloorina-welcome-seen', '1')")
        self.context.add_cookies([{
            'name': settings.SESSION_COOKIE_NAME,
            'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            'url': self.live_server_url,
        }])
        self.posts, self.errors = [], []

        def api(route):
            if route.request.method == 'POST':
                self.posts.append(route.request.url)
            route.fulfill(json={'sessions': [], 'messages': [], 'request': None})

        self.context.route('**/api/chat/**', api)
        self.context.route('**/api/ai/**', api)
        for domain in ('fonts.googleapis.com', 'fonts.gstatic.com', 'cdnjs.cloudflare.com'):
            self.context.route(f'https://{domain}/**', lambda route: route.abort())
        self.page = self.context.new_page()
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        instant = datetime(2026, 11, 20, tzinfo=timezone.utc)
        self.page.clock.install(time=instant)
        self.page.clock.pause_at(instant + timedelta(seconds=1))

    def open_home(self):
        self.page.goto(self.live_server_url + reverse('home'), wait_until='domcontentloaded')
        self.invite = self.page.locator('#ai-fab .ai-fab-invite')
        self.text = self.page.locator('#ai-fab .ai-fab-invite-text')

    def test_typing_hold_deletion_gaps_and_minute_rest(self):
        from playwright.sync_api import expect

        self.open_home()
        expect(self.invite).to_have_count(1)
        icon = self.page.locator('#ai-fab > svg').bounding_box()
        self.page.clock.run_for(999)
        expect(self.text).to_have_text('')
        self.page.clock.run_for(1)
        expect(self.text).to_have_text('t')
        for cycle in range(3):
            self.page.clock.run_for(1700)
            expect(self.text).to_have_text('Try AI for your event')
            self.page.clock.run_for(1999)
            expect(self.text).to_have_text('Try AI for your event')
            self.page.clock.run_for(1)
            expect(self.text).to_have_text('ry AI for your event')
            if cycle == 0:
                self.page.locator('#ai-fab').hover(force=True)
                self.page.clock.run_for(10000)
                expect(self.text).to_have_text('ry AI for your event')
                self.page.mouse.move(0, 0)
            self.page.clock.run_for(600)
            expect(self.text).to_have_text('')
            expect(self.invite).to_have_css('pointer-events', 'none')
            pause = 60000 if cycle == 2 else 8000
            self.page.clock.run_for(pause - 1)
            expect(self.text).to_have_text('')
            self.page.clock.run_for(1)
            expect(self.text).to_have_text('t')
        self.assertEqual(self.page.locator('#ai-fab > svg').bounding_box(), icon)
        self.assertEqual(self.posts, [])
        self.assertEqual(self.errors, [])

    def test_interaction_reduced_motion_themes_and_mobile_fit(self):
        from playwright.sync_api import expect

        self.open_home()
        expect(self.invite).to_have_count(1)
        self.page.clock.run_for(1200)
        expect(self.text).to_have_text('ent')
        self.page.locator('#ai-fab').hover(force=True)
        expect(self.text).to_have_text('ent')
        self.page.clock.run_for(90000)
        expect(self.text).to_have_text('ent')
        button = self.page.locator('#ai-fab').bounding_box()
        self.page.mouse.move(button['x'] - 5, button['y'] + button['height'] / 2, steps=5)
        expect(self.text).to_have_text('ent')
        self.page.mouse.move(0, 0)
        self.page.clock.run_for(54)
        expect(self.text).to_have_text('ent')
        self.page.clock.run_for(1)
        expect(self.text).to_have_text('vent')
        self.page.clock.run_for(1445)
        expect(self.text).to_have_text('Try AI for your event')
        self.page.locator('#ai-fab').hover(force=True)
        self.page.mouse.move(button['x'] - 5, button['y'] + button['height'] / 2, steps=5)
        self.invite.click(force=True)
        expect(self.page.locator('#ai-widget')).to_have_class('ai-widget-container active')
        expect(self.invite).to_have_css('pointer-events', 'none')
        self.page.clock.run_for(90000)
        expect(self.text).to_have_text('')
        self.page.locator('#ai-close').click(force=True)
        expect(self.page.locator('#ai-fab')).to_be_focused()
        expect(self.text).to_have_text('')
        self.page.mouse.move(0, 0)
        self.page.locator('#ai-fab').evaluate('el => el.blur()')
        self.page.clock.run_for(7999)
        expect(self.text).to_have_text('')
        self.page.clock.run_for(1)
        expect(self.text).to_have_text('t')
        self.page.evaluate("Object.defineProperty(document, 'hidden', {configurable: true, value: true}); document.dispatchEvent(new Event('visibilitychange'))")
        expect(self.text).to_have_text('')
        self.page.clock.run_for(90000)
        expect(self.text).to_have_text('')
        self.page.evaluate("delete document.hidden; document.dispatchEvent(new Event('visibilitychange'))")
        self.page.clock.run_for(7999)
        expect(self.text).to_have_text('')
        self.page.clock.run_for(1)
        expect(self.text).to_have_text('t')
        self.page.emulate_media(reduced_motion='reduce')
        expect(self.text).to_have_text('Try AI for your event')
        self.page.clock.run_for(180000)
        expect(self.text).to_have_text('Try AI for your event')
        self.page.evaluate("document.documentElement.setAttribute('data-welcome-active', '')")
        expect(self.text).to_have_text('')
        self.page.evaluate("document.documentElement.removeAttribute('data-welcome-active')")
        expect(self.text).to_have_text('Try AI for your event')
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        for theme in ('light', 'dark'):
            self.page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
            for width in (320, 390, 768, 1440):
                self.page.set_viewport_size({'width': width, 'height': 900})
                self.page.clock.run_for(300)
                box = self.invite.bounding_box()
                self.assertGreaterEqual(box['x'], 8)
                self.assertLessEqual(box['x'] + box['width'], width - 8)
                self.assertGreaterEqual(box['y'], 0)
                self.assertLessEqual(box['y'] + box['height'], 900)
                self.page.screenshot(path=str(artifacts / f'ai-invite-{theme}-{width}.png'))
        self.assertEqual(self.posts, [])
        self.assertEqual(self.errors, [])

    def test_bubble_fits_each_typed_prefix_and_shrinks_when_erasing(self):
        from io import BytesIO
        from PIL import Image
        from playwright.sync_api import expect

        self.open_home()
        expect(self.invite.locator('svg')).to_have_count(0)
        icon = self.page.locator('#ai-fab').bounding_box()
        clip = {'x': icon['x'] - 200, 'y': icon['y'] - 12,
                'width': icon['width'] + 212, 'height': icon['height'] + 24}
        frames, durations = [], []

        def record_frame(duration):
            frames.append(Image.open(BytesIO(self.page.screenshot(clip=clip))).convert('RGB'))
            durations.append(duration)

        self.page.clock.run_for(1000)
        expect(self.text).to_have_text('t')
        record_frame(85)
        self.page.clock.run_for(85)
        expect(self.text).to_have_text('nt')
        record_frame(85)
        short = self.invite.bounding_box()
        text_width = self.text.bounding_box()['width']
        self.assertAlmostEqual(short['width'], text_width + 26, delta=1)
        self.assertLess(short['width'], 65)
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        self.page.screenshot(path=str(artifacts / 'ai-invite-two-letters.png'))
        last_glyph = '''el => {
            const range = document.createRange();
            range.setStart(el.firstChild, el.textContent.length - 1);
            range.setEnd(el.firstChild, el.textContent.length);
            return range.getBoundingClientRect().x;
        }'''
        first_glyph_x = self.text.evaluate(last_glyph)
        for character in range(19):
            self.page.clock.run_for(85)
            record_frame(2000 if character == 18 else 85)
        expect(self.text).to_have_text('Try AI for your event')
        full = self.invite.bounding_box()
        self.assertGreater(full['width'], short['width'] + 60)
        self.assertAlmostEqual(short['x'] + short['width'], full['x'] + full['width'], delta=1)
        self.assertAlmostEqual(self.text.evaluate(last_glyph), first_glyph_x, delta=1)
        self.page.screenshot(path=str(artifacts / 'ai-invite-full-text.png'))
        self.page.clock.run_for(2000)
        record_frame(30)
        for _ in range(18):
            self.page.clock.run_for(30)
            record_frame(30)
        expect(self.text).to_have_text('nt')
        erased = self.invite.bounding_box()
        self.assertAlmostEqual(erased['width'], short['width'], delta=1)
        self.assertAlmostEqual(erased['x'], short['x'], delta=1)
        for duration in (30, 8000):
            self.page.clock.run_for(30)
            record_frame(duration)
        frames[0].save(artifacts / 'ai-invite-keystrokes.gif', save_all=True,
                       append_images=frames[1:], duration=durations, loop=0)
        strip = Image.new('RGB', (frames[0].width, frames[0].height * 6))
        for row, frame in enumerate((0, 1, 5, 10, 20, 38)):
            strip.paste(frames[frame], (0, row * frames[0].height))
        strip.save(artifacts / 'ai-invite-keystrokes-sequence.png')
        self.assertEqual(self.posts, [])
        self.assertEqual(self.errors, [])

    def test_invitation_follows_hidden_launcher_across_customer_surfaces(self):
        from playwright.sync_api import expect

        # Isolate visibility rules from the independently tested typing timers.
        self.page.set_content('<button type="button" id="ai-fab" class="ai-fab" '
                              'style="position:fixed;right:24px;bottom:24px;width:46px;height:46px">AI'
                              '<span class="ai-fab-invite is-visible"><span class="ai-fab-invite-copy">'
                              '<span class="ai-fab-invite-text">Try AI for your event</span></span></span></button>')
        self.invite = self.page.locator('#ai-fab .ai-fab-invite')
        for name in ('ai_chat.css', 'booking_form_components.css', 'customer_booking_details.css', 'canvas_mobile.css'):
            self.page.add_style_tag(path=str(Path(settings.BASE_DIR) / 'static/css' / name))
        self.page.evaluate('''() => {
            for (const id of ['bookingModalOverlay', 'editBookingModal']) {
                const overlay = document.createElement('div');
                overlay.id = id;
                document.body.append(overlay);
            }
        }''')
        fab = self.page.locator('#ai-fab')
        for theme in ('light', 'dark'):
            self.page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
            for width in (390, 1440):
                self.page.set_viewport_size({'width': width, 'height': 900})
                for motion in ('no-preference', 'reduce'):
                    self.page.emulate_media(reduced_motion=motion)
                    self.page.clock.run_for(10000)
                    cases = [
                        ("document.querySelector('#bookingModalOverlay').classList.add('show')",
                         "document.querySelector('#bookingModalOverlay').classList.remove('show')"),
                        ("document.querySelector('#editBookingModal').classList.add('show')",
                         "document.querySelector('#editBookingModal').classList.remove('show')"),
                        ("document.body.classList.add('customer-booking-scroll-locked')",
                         "document.body.classList.remove('customer-booking-scroll-locked')"),
                        ("document.querySelector('#ai-fab').style.visibility = 'hidden'",
                         "document.querySelector('#ai-fab').style.removeProperty('visibility')"),
                    ]
                    if width == 390:
                        cases.append(("document.body.classList.add('canvas-mobile-active')",
                                      "document.body.classList.remove('canvas-mobile-active')"))
                    for hide, show in cases:
                        with self.subTest(theme=theme, width=width, motion=motion, hide=hide):
                            # Check the exact frame a modal opens, then a later frame too.
                            fab.focus()
                            self.invite.evaluate("el => el.classList.add('is-visible')")
                            expect(self.invite).to_be_visible()
                            self.page.evaluate(hide)
                            expect(fab).to_be_hidden()
                            self.assertTrue(self.invite.is_hidden(), 'Invitation escaped its hidden launcher')
                            self.page.clock.run_for(10000)
                            expect(self.invite).to_be_hidden()
                            self.invite.evaluate("el => el.classList.add('is-visible')")
                            self.page.evaluate(show)
                            expect(fab).to_be_visible()
                            expect(self.invite).to_be_visible()
        self.assertEqual(self.posts, [])
        self.assertEqual(self.errors, [])

    def test_real_booking_wizard_hides_and_restores_invitation(self):
        from playwright.sync_api import expect

        self.page.emulate_media(reduced_motion='reduce')
        self.page.goto(self.live_server_url + reverse('booking_page') +
                       '?from=estimate&event_date=2099-07-16', wait_until='domcontentloaded')
        modal = self.page.locator('#bookingModalOverlay')
        fab = self.page.locator('#ai-fab')
        invite = fab.locator('.ai-fab-invite')
        expect(modal).to_be_visible()
        expect(fab).to_be_hidden()
        expect(invite).to_be_hidden()
        self.page.clock.run_for(90000)
        expect(invite).to_be_hidden()
        self.page.locator('#closeModalBtn').click(force=True)
        expect(fab).to_be_visible()
        expect(invite).to_be_visible()
        self.assertEqual(self.posts, [])

    def test_admin_tooltip_also_hides_with_its_focused_launcher(self):
        self.page.clock.resume()
        self.page.set_content('<div class="admin-chat-float sc-client">'
                              '<button id="adminChatToggle" aria-label="Chat with admin">Support</button></div>')
        for name in ('client_admin_chat_widget.css', 'booking_form_components.css', 'customer_booking_details.css'):
            self.page.add_style_tag(path=str(Path(settings.BASE_DIR) / 'static/css' / name))
        for theme in ('light', 'dark'):
            self.page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
            for motion in ('no-preference', 'reduce'):
                self.page.emulate_media(reduced_motion=motion)
                for surface in ('bookingModalOverlay', 'editBookingModal', 'booking-details'):
                    with self.subTest(theme=theme, motion=motion, surface=surface):
                        self.page.keyboard.press('Tab')
                        self.page.locator('#adminChatToggle').focus()
                        self.page.wait_for_timeout(250)
                        self.assertEqual(self.page.locator('#adminChatToggle').evaluate(
                            "el => getComputedStyle(el, '::after').visibility"), 'visible')
                        state = self.page.evaluate('''surface => {
                            if (surface === 'booking-details') {
                                document.body.classList.add('customer-booking-scroll-locked');
                            } else {
                                const overlay = document.createElement('div');
                                overlay.id = surface;
                                overlay.classList.add('show');
                                document.body.append(overlay);
                            }
                            const button = document.querySelector('#adminChatToggle');
                            return [getComputedStyle(button).visibility,
                                getComputedStyle(button, '::before').visibility,
                                getComputedStyle(button, '::after').visibility];
                        }''', surface)
                        self.assertEqual(state, ['hidden', 'hidden', 'hidden'])
                        self.page.evaluate('''surface => {
                            document.body.classList.remove('customer-booking-scroll-locked');
                            document.getElementById(surface)?.remove();
                        }''', surface)
