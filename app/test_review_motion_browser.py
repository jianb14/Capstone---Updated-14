"""Opt-in verification of review entrance motion and reduced-motion behavior."""
import os
from datetime import date
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import Booking, Review, User


@skipUnless(os.environ.get('RUN_REVIEWS_BROWSER') == '1','Optional Playwright verification')
@override_settings(SESSION_COOKIE_SECURE=False,CSRF_COOKIE_SECURE=False,REQUEST_RATE_LIMITING_ENABLED=False)
class ReviewMotionBrowserTests(StaticLiveServerTestCase):
    def test_entry_scroll_async_refresh_and_reduced_motion(self):
        from playwright.sync_api import expect, sync_playwright

        user = User.objects.create_user(username='review-motion',first_name='Jamie',role='customer',email_verified=True)
        for index in range(9):
            booking = Booking.objects.create(user=user,event_date=date(2026,1,index+1),event_location='Manila',
                event_type='Birthday',package_type='Package 1-A',total_price=4799,status='completed')
            if index < 7:
                Review.objects.create(user=user,booking=booking,rating=5,comment=f'Our celebration {index}')
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
            errors = []
            page.on('pageerror',lambda error:errors.append(str(error)))
            # Observe real animations without adding application hooks just for tests.
            page.add_init_script('''(() => {
                window.reviewEntrances = [];
                const animate = Element.prototype.animate;
                Element.prototype.animate = function(frames, options) {
                    if (options?.id === 'review-entry') window.reviewEntrances.push({className:this.className,
                        delay:options.delay, duration:options.duration, frames});
                    return animate.call(this,frames,options);
                };
            })();''')
            try:
                for route in ('my_reviews','reviews'):
                    for theme,width in (('light',1440),('dark',390)):
                        page.set_viewport_size({'width':width,'height':1000 if width==1440 else 844})
                        page.goto(self.live_server_url+reverse(route),wait_until='domcontentloaded')
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                        page.wait_for_function('window.reviewEntrances.length > 0')
                        entrances = page.evaluate('window.reviewEntrances')
                        self.assertTrue(any('mr-header-text' in item['className'] or 'reviews-title-wrap' in item['className'] for item in entrances))
                        self.assertTrue(all(item['duration']==480 and item['delay']<=225 for item in entrances))
                        if route=='my_reviews':
                            expect(page.locator('.mr-eyebrow')).to_have_count(0)
                            self.assertLessEqual(page.locator('.my-reviews-title').evaluate('el=>parseFloat(getComputedStyle(el).fontSize)'),34.5)
                        page.wait_for_function('!document.getAnimations().some(animation=>animation.id==="review-entry")')
                        page.screenshot(path=str(artifacts/f'review-motion-{route}-{theme}-{width}.png'))
                        # Scrolled-in cards are animated on arrival, not while still off-screen.
                        before = page.evaluate('window.reviewEntrances.length')
                        page.locator('.review-card').nth(4).scroll_into_view_if_needed()
                        page.wait_for_function('(before)=>window.reviewEntrances.length>before',arg=before)
                        page.wait_for_function('!document.getAnimations().some(animation=>animation.id==="review-entry")')
                        self.assertTrue(page.locator('.review-card').nth(4).evaluate('el=>getComputedStyle(el).transform==="none" && getComputedStyle(el).opacity==="1"'))
                        trigger = page.locator('.review-card').nth(4).get_by_role('button',name='Review options')
                        trigger.click()
                        expect(page.get_by_role('menu',name='Review actions')).to_be_visible()
                        page.keyboard.press('Escape')
                    # Refreshed sections use the same entrance, with no navigation.
                    page.evaluate('window.scrollTo(0,0); window.reviewMotionSentinel="preserved"')
                    before = page.evaluate('window.reviewEntrances.length')
                    page.evaluate('window.ReviewPage.refresh()')
                    page.wait_for_function('(before)=>window.reviewEntrances.length>before',arg=before)
                    self.assertEqual(page.evaluate('window.reviewMotionSentinel'),'preserved')
                    # Switching the OS/browser preference cancels all running effects.
                    page.emulate_media(reduced_motion='reduce')
                    page.wait_for_function('!document.getAnimations().some(animation=>animation.id==="review-entry")')
                    page.goto(self.live_server_url+reverse(route),wait_until='domcontentloaded')
                    self.assertEqual(page.evaluate('window.reviewEntrances.length'),0)
                    expect(page.locator('.review-card').first).to_have_css('opacity','1')
                    page.emulate_media(reduced_motion='no-preference')
                self.assertEqual(errors,[])
            finally:
                context.close()
                browser.close()
