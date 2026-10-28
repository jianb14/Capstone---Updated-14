"""Opt-in browser checks for the review workspace without document reloads."""
import io
import os
from datetime import time
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import Booking, Review, ReviewImage, User


@skipUnless(os.environ.get('RUN_ADMIN_REVIEWS_BROWSER')=='1','Optional review browser verification')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminReviewBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        admin=User.objects.create_user(username='reviews-browser-admin',role='admin',email_verified=True)
        customer=User.objects.create_user(username='reviews-browser-customer',role='customer',first_name='Jamie',last_name='Rivera',email='jamie@example.com',email_verified=True)
        booking=Booking.objects.create(user=customer,event_date=timezone.localdate(),event_time=time(9),event_type='Birthday',
            event_location='Venue',package_type='Package 1-A + Entrance A + Stand A',total_price=6000,status='completed')
        for i in range(25):
            review=Review.objects.create(user=customer,booking=booking,rating=i%5+1,
                comment=f'Celebration feedback {i}. Thank you for making our day special!',is_testimonial=i==24)
        self.target=review
        output=io.BytesIO();Image.new('RGB',(600,420),'#cba36b').save(output,format='PNG')
        ReviewImage.objects.create(review=review,image=SimpleUploadedFile('review.png',output.getvalue(),content_type='image/png'))
        self.client.force_login(admin);self.url=self.live_server_url+reverse('admin_reviews')
        self.artifacts=Path(settings.BASE_DIR)/'.booking-followup-check'

    def browser(self, playwright):
        browser=playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1000})
        context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
        context.add_init_script("localStorage.setItem('balloorina-theme','light')")
        context.route('https://fonts.googleapis.com/**',lambda route:route.abort())
        context.route('https://cdnjs.cloudflare.com/**',lambda route:route.abort())
        context.route('https://cdn.jsdelivr.net/**',lambda route:route.fulfill(status=200,content_type='application/javascript',body='window.Swal={mixin:()=>({fire:()=>{}})};'))
        return browser,context

    def test_filters_pagination_feature_reply_and_photo_are_async(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[];documents=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            try:
                page.goto(self.url)
                expect(page.locator('.cfg-toast')).to_be_hidden()
                expect(page.locator('[data-review-row]')).to_have_count(8)
                page.get_by_label('Search reviews').fill('missing-search')
                expect(page.get_by_text('No matching reviews',exact=True)).to_be_visible()
                expect(page.locator('.cfg-toast')).to_be_hidden()
                expect(page.locator('.rv-table thead')).to_have_count(0)
                expect(page.locator('[data-list-footer]')).to_have_count(0)
                page.screenshot(path=str(self.artifacts/'admin-reviews-empty.png'),full_page=True,animations='disabled')
                page.get_by_role('button',name='Clear search',exact=True).click()
                expect(page.locator('[data-review-row]')).to_have_count(8)
                page.get_by_role('button',name='Rating: All ratings',exact=True).click()
                page.get_by_role('option',name='2 stars',exact=True).click()
                expect(page.locator('[data-review-row]')).to_have_count(5)
                expect(page.locator('[data-review-stat="total"]')).to_have_text('25')
                page.get_by_role('button',name='Rating: 2 stars',exact=True).click()
                page.get_by_role('option',name='All ratings',exact=True).click()
                expect(page.locator('[data-review-row]')).to_have_count(8)
                page.get_by_role('button',name='Rows per page: 8',exact=True).click()
                page.get_by_role('option',name='4',exact=True).click()
                expect(page.locator('[data-review-row]')).to_have_count(4)
                page.get_by_role('link',name='Page 2',exact=True).click()
                expect(page.locator('.account-pagination [aria-current="page"]')).to_have_text('2')
                page.go_back();expect(page.locator('.account-pagination [aria-current="page"]')).to_have_text('1')
                # A testimonial filter becoming empty must not leave stale headers or counts.
                page.get_by_role('button',name='Testimonial: All testimonials',exact=True).click()
                page.get_by_role('option',name='Featured',exact=True).click()
                expect(page.locator('[data-review-row]')).to_have_count(1)
                page.get_by_role('button',name=f'Unfeature review #REV-{self.target.pk}',exact=True).click()
                expect(page.locator('[data-review-stat="featured"]')).to_have_text('0 / 4')
                expect(page.get_by_text('No matching reviews',exact=True)).to_be_visible()
                toast=page.locator('.cfg-toast')
                expect(toast).to_contain_text('Review removed from featured testimonials.')
                expect(toast).to_have_attribute('data-kind','success')
                self.assertLess(toast.bounding_box()['y'],100)
                self.assertGreater(toast.bounding_box()['x'],900)
                toast.get_by_role('button',name='Dismiss notification').click()
                expect(toast).to_be_hidden()
                page.get_by_role('button',name='Clear filters',exact=True).click()
                expect(page.locator('[data-review-row]')).to_have_count(4)
                page.get_by_role('link',name=f'View review #REV-{self.target.pk}',exact=True).click()
                modal=page.locator('#reviewDetailModal');expect(modal).to_be_visible()
                expect(modal.locator('.rv-full-comment')).to_contain_text('Celebration feedback 24')
                page.screenshot(path=str(self.artifacts/'admin-review-modal-normal.png'),animations='disabled')
                page.get_by_role('button',name='Open review photo 1',exact=True).click()
                expect(page.locator('#reviewImageModal')).to_be_visible()
                page.get_by_role('button',name='Close review photo',exact=True).click()
                reply=page.get_by_label('Admin reply',exact=True)
                reply_requests=[]
                page.on('request',lambda request:reply_requests.append(request.url) if request.method=='POST' and request.url.endswith('/reply/') else None)
                for draft in ('', '   '):
                    reply.fill(draft)
                    page.get_by_role('button',name='Post Reply',exact=True).click()
                    expect(modal.locator('[data-reply-error]')).to_have_text('Reply text is required.')
                    expect(reply).to_have_attribute('aria-invalid','true')
                    expect(reply).to_be_focused()
                    expect(modal.locator('.rv-action-feedback')).to_be_empty()
                    expect(toast).to_be_hidden()
                self.assertEqual(reply_requests,[])
                reply.fill('Thank you for celebrating with us!')
                expect(modal.locator('[data-reply-error]')).to_be_hidden()
                expect(reply).not_to_have_attribute('aria-invalid','true')
                page.get_by_role('button',name='Post Reply',exact=True).click()
                expect(modal.locator('.rv-action-feedback')).to_contain_text('Reply posted successfully.')
                expect(toast).to_contain_text('Reply posted successfully.')
                self.assertTrue(toast.evaluate("el=>el.matches(':popover-open')"))
                page.get_by_label('Admin reply',exact=True).fill('Thank you! We look forward to your next celebration.')
                page.get_by_role('button',name='Update Reply',exact=True).click()
                expect(toast).to_contain_text('Reply updated successfully.')
                page.get_by_label('Admin reply',exact=True).fill('A draft reply to keep')
                page.get_by_role('button',name='Feature review',exact=True).click()
                expect(page.get_by_label('Admin reply',exact=True)).to_have_value('A draft reply to keep')
                expect(page.locator('[data-review-stat="featured"]')).to_have_text('1 / 4')
                expect(toast).to_contain_text('Review featured on Home and About.')
                page.get_by_role('button',name='Remove Reply',exact=True).click()
                expect(modal.locator('[data-remove-confirm]')).to_be_visible()
                page.get_by_role('button',name='Keep reply',exact=True).click()
                expect(modal.locator('[data-remove-confirm]')).to_be_hidden()
                page.get_by_role('button',name='Remove Reply',exact=True).click()
                page.get_by_role('button',name='Remove reply',exact=True).last.click()
                expect(modal.locator('.rv-action-feedback')).to_contain_text('Reply removed successfully.')
                expect(toast).to_contain_text('Reply removed successfully.')
                expect(page.get_by_role('button',name='Post Reply',exact=True)).to_be_visible()
                page.get_by_role('button',name='Post Reply',exact=True).click()
                expect(modal.locator('[data-reply-error]')).to_have_text('Reply text is required.')
                expect(modal.locator('.rv-action-feedback')).to_be_empty()
                page.get_by_role('button',name='Close review details',exact=True).click()
                expect(modal).to_be_hidden()
                self.assertEqual(len(documents),1);self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_failed_reply_keeps_draft_and_success_survives_failed_queue_refresh(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();documents=[];errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            try:
                page.goto(self.url+f'?review_id={self.target.pk}')
                reply=page.get_by_label('Admin reply',exact=True)
                reply.fill('Keep this reply until it has been saved.')
                page.route('**'+reverse('admin_review_reply',args=[self.target.pk]),lambda route:
                    route.fulfill(status=503,content_type='application/json',body='{"message":"Reply could not be saved. Please try again."}'),times=1)
                page.get_by_role('button',name='Post Reply',exact=True).click()
                toast=page.locator('.cfg-toast')
                expect(toast).to_have_attribute('data-kind','error')
                expect(toast).to_contain_text('Reply could not be saved')
                expect(reply).to_have_value('Keep this reply until it has been saved.')
                expect(page.get_by_role('button',name='Post Reply',exact=True)).to_be_enabled()
                page.evaluate("document.documentElement.dataset.theme='dark'")
                page.set_viewport_size({'width':390,'height':844})
                # Saving succeeds even if the subsequent list refresh is offline.
                page.route('**/staff/reviews/?**',lambda route:route.abort())
                page.get_by_role('button',name='Post Reply',exact=True).click()
                expect(page.locator('#reviewListFeedback')).not_to_be_empty()
                expect(page.get_by_role('button',name='Update Reply',exact=True)).to_be_enabled()
                expect(toast).to_have_attribute('data-kind','success')
                expect(toast).to_contain_text('Reply posted successfully.')
                expect(reply).to_have_value('Keep this reply until it has been saved.')
                self.assertTrue(toast.evaluate("el=>el.matches(':popover-open')"))
                self.assertLess(toast.bounding_box()['y'],100)
                self.assertGreaterEqual(toast.bounding_box()['x'],0)
                self.assertLessEqual(toast.bounding_box()['x']+toast.bounding_box()['width'],390)
                self.assertEqual(toast.evaluate('el=>getComputedStyle(el).backgroundColor'),'rgb(22, 22, 22)')
                page.screenshot(path=str(self.artifacts/'admin-review-feedback-mobile-dark.png'),animations='disabled')
                self.assertEqual(len(documents),1);self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_themes_responsive_long_content_focus_and_deep_link(self):
        from playwright.sync_api import expect,sync_playwright
        Review.objects.filter(pk=self.target.pk).update(comment='longword'*200+'\nA second paragraph.')
        Booking.objects.filter(pk=self.target.booking_id).update(package_type='Averylongpackagename'*12)
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.live_server_url+reverse('admin_review_detail',args=[self.target.pk]))
                expect(page.locator('#reviewDetailModal')).to_be_visible()
                expect(page).to_have_url(self.url+f'?review_id={self.target.pk}')
                for theme in ('light','dark'):
                    page.evaluate('(value)=>document.documentElement.dataset.theme=value',theme)
                    for width in (1440,768,390,320):
                        page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(200)
                        self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'),f'Page overflow {theme}/{width}')
                        self.assertFalse(page.locator('#reviewModalBody').evaluate('(node)=>node.scrollWidth>node.clientWidth'),f'Modal overflow {theme}/{width}')
                        page.get_by_role('button',name='Post Reply',exact=True).click()
                        field_error=page.locator('[data-reply-error]')
                        expect(field_error).to_have_text('Reply text is required.')
                        dimensions=field_error.evaluate('''node=>{
                            const field=document.getElementById('replyText');
                            return {gap:node.getBoundingClientRect().top-field.getBoundingClientRect().bottom,
                                color:getComputedStyle(node).color, expected:getComputedStyle(document.querySelector('.rv-workspace')).getPropertyValue('--ac-red').trim()};
                        }''')
                        self.assertGreaterEqual(dimensions['gap'],3)
                        self.assertLessEqual(dimensions['gap'],7)
                        expected_color=page.evaluate('value=>{const node=document.createElement("div");node.style.color=value;document.body.append(node);const color=getComputedStyle(node).color;node.remove();return color;}',dimensions['expected'])
                        self.assertEqual(dimensions['color'],expected_color)
                        page.screenshot(path=str(self.artifacts/f'admin-review-modal-{theme}-{width}.png'),animations='disabled')
                    page.get_by_label('Admin reply',exact=True).focus()
                    self.assertEqual(page.get_by_label('Admin reply',exact=True).evaluate('(node)=>getComputedStyle(node).outlineStyle'),'solid')
                    page.get_by_role('button',name='Close review details',exact=True).click()
                    for width in (1440,768,390,320):
                        page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(200)
                        self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'),f'List overflow {theme}/{width}')
                        page.get_by_label('Search reviews').focus()
                        self.assertEqual(page.get_by_label('Search reviews').evaluate('(node)=>getComputedStyle(node).outlineStyle'),'solid')
                        page.screenshot(path=str(self.artifacts/f'admin-reviews-{theme}-{width}.png'),full_page=True,animations='disabled')
                    page.get_by_role('link',name=f'View review #REV-{self.target.pk}',exact=True).click()
                    expect(page.locator('#reviewDetailContent .rv-detail')).to_be_visible()
                page.emulate_media(reduced_motion='reduce')
                self.assertEqual(page.locator('.rv-dialog').evaluate('(node)=>getComputedStyle(node).animationName'),'none')
                self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_stale_requests_network_failure_and_capacity_feedback(self):
        from playwright.sync_api import expect,sync_playwright
        ids=list(Review.objects.exclude(pk=self.target.pk).order_by('pk').values_list('pk',flat=True)[:3])
        Review.objects.filter(pk__in=ids).update(is_testimonial=True)
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();documents=[];errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            try:
                page.goto(self.url)
                page.locator('[data-review-feature] button[aria-pressed="false"]').first.click()
                expect(page.locator('#reviewListFeedback')).to_contain_text('All 4 testimonial slots are in use.')
                expect(page.locator('.cfg-toast')).to_have_attribute('data-kind','error')
                expect(page.locator('.cfg-toast')).to_contain_text('All 4 testimonial slots are in use.')
                expect(page.locator('[data-review-row]')).to_have_count(8)
                page.evaluate("""() => {
                    const original=window.fetch;
                    window.fetch=(...args)=>original(...args).then(async response=>{
                        if(String(args[0]).includes('search=missing')) await new Promise(resolve=>setTimeout(resolve,600));
                        return response;
                    });
                }""")
                search=page.get_by_label('Search reviews')
                search.fill('missing');page.wait_for_timeout(350);search.fill('Jamie Rivera')
                expect(page.locator('[data-review-row]')).to_have_count(8)
                page.wait_for_timeout(1000)
                expect(page.locator('[data-review-row]')).to_have_count(8)
                page.route('**/staff/reviews/?**',lambda route:route.abort())
                search.fill('network-down')
                expect(page.locator('#reviewListFeedback')).not_to_be_empty()
                expect(page.locator('[data-review-row]')).to_have_count(8)
                page.unroute('**/staff/reviews/?**')
                search.fill('');page.get_by_role('button',name='Clear search',exact=True).click() if page.get_by_role('button',name='Clear search',exact=True).is_visible() else None
                page.get_by_role('button',name='Sort reviews: Newest first',exact=True).click()
                page.get_by_role('option',name='Oldest first',exact=True).click()
                expect(page.locator('[data-review-row]').first).not_to_have_attribute('data-review-row',str(self.target.pk))
                self.assertEqual(len(documents),1);self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_direct_page_and_empty_page_size_survive_async_actions(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page()
            try:
                page.goto(self.url+'?page=2')
                expect(page.locator('.account-pagination [aria-current="page"]')).to_have_text('2')
                page.locator('[data-review-feature] button[aria-pressed="false"]').first.click()
                expect(page.locator('[data-review-stat="featured"]')).to_have_text('2 / 4')
                expect(page.locator('.account-pagination [aria-current="page"]')).to_have_text('2')
                page.goto(self.url+'?search=missing&per_page=4')
                expect(page.get_by_text('No matching reviews',exact=True)).to_be_visible()
                page.get_by_role('button',name='Clear search',exact=True).click()
                expect(page.locator('[data-review-row]')).to_have_count(4)
                expect(page.get_by_role('button',name='Rows per page: 4',exact=True)).to_be_visible()
            finally:context.close();browser.close()
