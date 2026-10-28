import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import User


@skipUnless(os.environ.get('RUN_ACCOUNT_MENU_BROWSER') == '1','Optional Playwright verification')
@override_settings(SESSION_COOKIE_SECURE=False,CSRF_COOKIE_SECURE=False,REQUEST_RATE_LIMITING_ENABLED=False)
class AccountMenuBrowserTests(StaticLiveServerTestCase):
    def test_layout_keyboard_single_navigation_and_same_page_selection(self):
        from playwright.sync_api import expect, sync_playwright

        user = User.objects.create_user(username='account-menu',first_name='Jamie',last_name='Rivera',
            email='jamie.with.a.long.email.address@example.com',role='customer',email_verified=True)
        self.client.force_login(user)
        session = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        artifacts = Path(settings.BASE_DIR)/'.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context = browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='no-preference')
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':session,'url':self.live_server_url}])
            context.route('https://fonts.googleapis.com/**',lambda route:route.abort())
            sweetalert = artifacts/'sweetalert2.all.min.js'
            if sweetalert.exists(): context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11',lambda route:route.fulfill(content_type='application/javascript',body=sweetalert.read_text(encoding='utf-8')))
            page = context.new_page()
            errors, documents = [], []
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request: documents.append(request.url) if request.resource_type=='document' else None)
            page.add_init_script('''(() => {
                window.accountReviewEntrances = [];
                const animate = Element.prototype.animate;
                Element.prototype.animate = function(frames, options) {
                    if (options?.id === 'review-entry') window.accountReviewEntrances.push(this.className);
                    return animate.call(this,frames,options);
                };
            })();''')
            try:
                page.goto(self.live_server_url+reverse('reviews'),wait_until='domcontentloaded')
                button = page.get_by_role('button',name='Profile menu',exact=True)
                menu = page.locator('#clientAccountMenu')
                for theme in ('light','dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    for width,height in ((1440,1000),(969,900),(968,900),(768,900),(390,844),(320,568),(640,360)):
                        page.set_viewport_size({'width':width,'height':height})
                        button.click()
                        expect(menu).to_be_visible()
                        page.wait_for_function('!document.getElementById("clientAccountMenu").getAnimations().some(animation=>animation.playState==="running")')
                        expect(button).to_have_attribute('aria-expanded','true')
                        expect(menu.get_by_role('link')).to_have_count(6 if width<=968 else 2)
                        expect(menu.get_by_role('link',name='My Account',exact=True)).to_be_hidden() if width<=968 else expect(menu.get_by_role('link',name='My Account',exact=True)).to_be_visible()
                        for name in ('My Profile','My Bookings','My Payments','My Reviews','Report Concern'):
                            expect(menu.get_by_role('link',name=name,exact=True)).to_be_visible() if width<=968 else expect(menu.get_by_role('link',name=name,exact=True)).to_be_hidden()
                        box = menu.bounding_box()
                        self.assertGreaterEqual(box['x'],0)
                        self.assertGreaterEqual(box['y'],0)
                        self.assertLessEqual(box['x']+box['width'],width)
                        self.assertLessEqual(box['y']+box['height'],height)
                        self.assertFalse(menu.evaluate('el=>el.scrollWidth>el.clientWidth+1'))
                        self.assertEqual(menu.locator('svg').first.evaluate('el=>getComputedStyle(el).strokeWidth'),'1.5px')
                        self.assertTrue(menu.evaluate('el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.right-18,r.bottom-18));}'))
                        page.screenshot(path=str(artifacts/f'account-menu-{theme}-{width}.png'))
                        page.keyboard.press('Escape')
                        expect(menu).to_be_hidden()
                        expect(button).to_have_attribute('aria-expanded','false')
                        expect(button).to_be_focused()
                for width,first in ((1440,'My Account'),(390,'My Profile')):
                    page.set_viewport_size({'width':width,'height':844})
                    button.press('ArrowDown')
                    expect(menu.get_by_role('link',name=first,exact=True)).to_be_focused()
                    page.keyboard.press('End')
                    expect(menu.get_by_role('link',name='Log Out',exact=True)).to_be_focused()
                    page.keyboard.press('Home')
                    expect(menu.get_by_role('link',name=first,exact=True)).to_be_focused()
                    page.keyboard.press('Escape')
                button.press('ArrowDown')
                page.set_viewport_size({'width':1440,'height':1000})
                expect(menu).to_be_hidden()
                expect(button).to_be_focused()
                button.click()
                page.mouse.click(8,120)
                expect(menu).to_be_hidden()
                button.click()
                page.locator('#notif-bell').click()
                expect(menu).to_be_hidden()
                expect(button).to_have_attribute('aria-expanded','false')
                page.mouse.click(8,120)
                page.set_viewport_size({'width':1440,'height':1000})
                documents.clear()
                button.click()
                menu.get_by_role('link',name='My Account',exact=True).click()
                page.wait_for_url(self.live_server_url+reverse('my_profile'))
                page.locator('[data-account-key="my_reviews"]').click()
                page.wait_for_url(self.live_server_url+reverse('my_reviews'))
                page.wait_for_function('!window.AccountNavigation.navigating')
                self.assertEqual(documents,[self.live_server_url+reverse('my_profile')])
                page.wait_for_function('window.accountReviewEntrances.some(name=>name.includes("mr-header-text"))')
                self.assertEqual(page.evaluate('window.accountReviewEntrances.filter(name=>name.includes("mr-header-text")).length'),1)
                page.locator('[data-account-key="my_profile"]').click()
                page.wait_for_function('!window.AccountNavigation.navigating')
                page.evaluate('window.accountMenuSentinel="same-document"')
                button.click()
                expect(menu.get_by_role('link',name='My Account',exact=True)).to_have_attribute('aria-current','page')
                menu.get_by_role('link',name='My Account',exact=True).click()
                expect(menu).to_be_hidden()
                self.assertEqual(page.evaluate('window.accountMenuSentinel'),'same-document')
                self.assertEqual(len(documents),1)
                self.assertEqual(errors,[])
            finally:
                context.close()
                browser.close()
