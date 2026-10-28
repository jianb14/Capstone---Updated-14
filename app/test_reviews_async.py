import os
from datetime import date
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import Booking, Review, User


class AsyncReviewValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='async-reviews', password='Password!25', role='customer', email_verified=True)
        self.booking = Booking.objects.create(user=self.user, event_date=date(2026,1,1), event_location='Manila', status='completed', total_price=4799)
        self.client.force_login(self.user)

    def post(self, data):
        return self.client.post(reverse('submit_review',args=[self.booking.pk]),data,HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_json_validation_and_success_without_redirect_or_queued_flash(self):
        for data, field in (({'rating':'bad','comment':'Hello'},'rating'), ({'rating':5,'comment':'   '},'comment')):
            response = self.post(data)
            self.assertEqual(response.status_code,400)
            self.assertIn(field,response.json()['errors'])
        self.assertFalse(Review.objects.exists())
        response = self.post({'rating':5,'comment':' Wonderful setup '})
        self.assertEqual(response.status_code,201)
        self.assertEqual(Review.objects.get().comment,'Wonderful setup')
        self.assertNotIn('_messages',self.client.cookies)
        self.assertEqual(self.post({'rating':5,'comment':'Duplicate'}).status_code,400)
        self.assertEqual(Review.objects.count(),1)

    def test_completed_booking_and_ownership_rules_still_apply(self):
        self.booking.status = 'confirmed'
        self.booking.save(update_fields=['status'])
        self.assertEqual(self.post({'rating':5,'comment':'Hello'}).status_code,400)
        other = User.objects.create_user(username='other-reviewer',role='customer',email_verified=True)
        self.client.force_login(other)
        self.assertEqual(self.post({'rating':5,'comment':'Hello'}).status_code,404)
        self.assertFalse(Review.objects.exists())

    def test_empty_states_are_present_even_without_pending_or_published_reviews(self):
        self.booking.status = 'confirmed'
        self.booking.save(update_fields=['status'])
        response = self.client.get(reverse('my_reviews'))
        self.assertContains(response,'All caught up')
        self.assertContains(response,'No published reviews yet')
        self.assertContains(self.client.get(reverse('reviews')),'No reviews yet')


@skipUnless(os.environ.get('RUN_REVIEWS_BROWSER') == '1','Optional Playwright verification')
@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, REQUEST_RATE_LIMITING_ENABLED=False)
class AsyncReviewPageBrowserTests(StaticLiveServerTestCase):
    def test_empty_states_filters_likes_pagination_and_deletion_without_navigation(self):
        from playwright.sync_api import expect, sync_playwright

        user = User.objects.create_user(username='async-owner',first_name='Jamie',password='Password!25',role='customer',email_verified=True)
        other = User.objects.create_user(username='async-other',role='customer',email_verified=True)
        def booking(owner, pkg='Package 1-A'):
            return Booking.objects.create(user=owner,event_date=date(2026,1,1),event_location='Manila',status='completed',total_price=4799,package_type=pkg)
        reviews = [Review.objects.create(user=user,booking=booking(user),rating=5 if i==0 else 4,comment=f'Published review {i}') for i in range(7)]
        Review.objects.create(user=other,booking=booking(other,'Package 1-B'),rating=3,comment='Another customer review')
        for _ in range(7): booking(user)
        self.client.force_login(user)
        session = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        other_client = Client()
        other_client.force_login(other)
        other_session = other_client.cookies[settings.SESSION_COOKIE_NAME].value
        artifacts = Path(settings.BASE_DIR)/'.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context = browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':session,'url':self.live_server_url}])
            context.route('https://fonts.googleapis.com/**',lambda route:route.abort())
            sweetalert = artifacts/'sweetalert2.all.min.js'
            if sweetalert.exists(): context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11',lambda route:route.fulfill(content_type='application/javascript',body=sweetalert.read_text(encoding='utf-8')))
            page = context.new_page()
            errors = []
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.live_server_url+reverse('my_reviews'),wait_until='domcontentloaded')
                page.evaluate('window.reviewSentinel = "same-document"')
                page.locator('a[href="?page_published=2"]').first.click()
                expect(page.locator('.review-card')).to_have_count(2)
                self.assertEqual(page.evaluate('window.reviewSentinel'),'same-document')
                page.locator('a[href*="page_pending=2"]').first.click()
                expect(page.locator('.pending-review-card')).to_have_count(2)
                expect(page.locator('.review-card')).to_have_count(2)
                page.go_back(wait_until='domcontentloaded')
                expect(page.locator('.pending-review-card')).to_have_count(5)
                self.assertEqual(page.evaluate('window.reviewSentinel'),'same-document')

                page.goto(self.live_server_url+reverse('reviews'),wait_until='domcontentloaded')
                page.evaluate('window.reviewSentinel = "same-document"')
                expect(page.locator('.review-card:visible')).to_have_count(6)
                page.get_by_role('button',name='Load more reviews').click()
                expect(page.locator('.review-card:visible')).to_have_count(8)
                for theme in ('light','dark'):
                    for width in (1440,390):
                        page.set_viewport_size({'width':width,'height':1000 if width==1440 else 844})
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                        rating = page.get_by_role('button',name='Filter by rating')
                        rating.click()
                        page.get_by_role('option',name='1 Star',exact=True).click()
                        expect(page.locator('#review-filter-empty')).to_be_visible()
                        expect(page.locator('.review-card:visible')).to_have_count(0)
                        page.screenshot(path=str(artifacts/f'review-filter-empty-{theme}-{width}.png'))
                        page.get_by_role('button',name='Clear filters').click()
                        expect(page.locator('.review-card:visible')).to_have_count(6)
                        page.get_by_role('button',name='Sort reviews').click()
                        page.get_by_role('option',name='Highest Rated',exact=True).click()
                        expect(page.locator('.review-card:visible').first).to_have_attribute('data-rating','5')
                page.set_viewport_size({'width':1440,'height':1000})
                page.get_by_role('button',name='Filter by package').click()
                page.get_by_role('option',name='Package 1-B',exact=True).click()
                other_card = page.locator('.review-card:visible')
                other_card.locator('.like-btn').click()
                expect(other_card.locator('.like-count')).to_have_text('1')
                page.get_by_role('button',name='Filter by package').click()
                page.get_by_role('option',name='Package (All)',exact=True).click()
                # Edit the only 5-star review while the 5-star filter is active.
                page.get_by_role('button',name='Filter by rating').click()
                page.get_by_role('option',name='5 Stars',exact=True).click()
                page.get_by_role('button',name='Review options').click()
                page.get_by_role('menuitem',name='Edit review').click()
                page.locator('label[for="edit-star2"]').click()
                page.route('**/reviews/*/edit/',lambda route:route.fulfill(status=503,content_type='application/json',body='{"message":"Please try saving again."}'),times=1)
                page.get_by_role('button',name='Save Changes',exact=True).click()
                expect(page.locator('.review-form-server-error')).to_have_text('Please try saving again.')
                expect(page.locator('#editReviewModal')).to_be_visible()
                expect(page.locator('#edit-comment')).not_to_have_value('')
                expect(page.get_by_role('button',name='Save Changes',exact=True)).to_be_enabled()
                page.get_by_role('button',name='Save Changes',exact=True).click()
                expect(page.locator('#review-filter-empty')).to_be_visible()
                expect(page.locator('.review-card:visible')).to_have_count(0)
                expect(page.locator('#starDropdownText')).to_have_text('5 Stars')
                page.get_by_role('button',name='Clear filters').click()
                # Every delete refreshes the list and the final remaining review can be deleted too.
                page.evaluate('AppToast.confirm = async () => ({isConfirmed:true}); AppToast.fire = async () => ({})')
                for _ in range(7):
                    if _ == 0:
                        page.route('**/reviews/',lambda route:route.fulfill(status=503,body='Unavailable'),times=1)
                    trigger = page.get_by_role('button',name='Review options').first
                    trigger.click()
                    page.get_by_role('menuitem',name='Delete review').click()
                    if _ == 0:
                        expect(page.locator('.review-refresh-error')).to_be_visible()
                        page.get_by_role('button',name='Try again',exact=True).click()
                        expect(page.locator('.review-refresh-error')).to_have_count(0)
                    page.wait_for_function('!document.querySelector("[data-review-page-content][aria-busy]") && !document.querySelector(".review-dropdown.show")')
                    # Wait on the updated number of owner menus, not just the start of the request.
                    expect(page.locator('.review-options .options-btn')).to_have_count(6-_)
                self.assertEqual(page.evaluate('window.reviewSentinel'),'same-document')
                page.goto(self.live_server_url+reverse('my_reviews'),wait_until='domcontentloaded')
                expect(page.get_by_text('No published reviews yet',exact=True)).to_be_visible()
                expect(page.locator('.mr-stat-num').nth(1)).to_have_text('0')
                for theme in ('light','dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    page.screenshot(path=str(artifacts/f'review-published-empty-{theme}.png'))
                # Delete the last public review as its owner; the overall empty state updates in place.
                context.clear_cookies()
                context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':other_session,'url':self.live_server_url}])
                page.goto(self.live_server_url+reverse('reviews'),wait_until='domcontentloaded')
                page.evaluate('window.reviewSentinel = "last-review"; AppToast.confirm = async () => ({isConfirmed:true}); AppToast.fire = async () => ({})')
                page.get_by_role('button',name='Review options').click()
                page.get_by_role('menuitem',name='Delete review').click()
                expect(page.get_by_text('No reviews yet',exact=True)).to_be_visible()
                self.assertEqual(page.evaluate('window.reviewSentinel'),'last-review')
                for theme in ('light','dark'):
                    for width in (1440,390):
                        page.set_viewport_size({'width':width,'height':1000 if width==1440 else 844})
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                        page.screenshot(path=str(artifacts/f'review-overall-empty-{theme}-{width}.png'))
                self.assertEqual(errors,[])
            finally:
                context.close()
                browser.close()
