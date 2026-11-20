"""Real-page error feedback regressions; RUN_USER_ERROR_BROWSER=1 opts in."""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from .email_otp import digest
from .models import AdminInvitation, Booking, ConcernImage, ConcernTicket, Review, User, UserDesign
from .test_concerns import photo


@skipUnless(os.environ.get('RUN_USER_ERROR_BROWSER') == '1', 'Optional user-error browser verification')
@override_settings(
    SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
    REQUEST_RATE_LIMITING_ENABLED=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class UserErrorFeedbackBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='error-browser', role='customer', email_verified=True)
        self.client.force_login(self.user)
        self.enterContext(patch('app.views.profiles.send_admin_alert_email', return_value=True))
        self.artifacts = Path(settings.BASE_DIR) / '.booking-followup-check/error-copy-implementation/browser'
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.browser = None
        self.page_errors = []

    def tearDown(self):
        self.assertEqual(self.page_errors, [])

    def db(self, operation):
        # Playwright owns an event loop on the test thread; Django queries run separately.
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(operation).result()

    def page_for(self, client=None, anonymous=False):
        from playwright.sync_api import sync_playwright

        if self.browser is None:
            self.playwright = sync_playwright().start()
            self.addCleanup(self.playwright.stop)
            self.browser = self.playwright.chromium.launch(
                executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            self.addCleanup(self.browser.close)
        context = self.browser.new_context(viewport={'width': 1366, 'height': 900}, reduced_motion='reduce')
        self.addCleanup(context.close)
        context.route('**/*', lambda route: route.continue_()
            if route.request.url.startswith(self.live_server_url + '/') else route.abort())
        if not anonymous:
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': (client or self.client).cookies[settings.SESSION_COOKIE_NAME].value,
                'url': self.live_server_url}])
        page = context.new_page()
        page.on('pageerror', lambda error: self.page_errors.append(str(error)))
        return page

    def failure(self, mode, payload=None):
        def respond(route):
            if mode == 'network':
                route.abort('failed')
            elif mode == 'malformed':
                route.fulfill(status=200, content_type='application/json', body='{"broken":')
            elif mode == 'incomplete':
                route.fulfill(status=200, content_type='application/json', body='{}')
            elif mode == 'html':
                route.fulfill(status=503, content_type='text/html', body='<html>Temporary failure</html>')
            else:
                route.fulfill(status=503, content_type='application/json', body=json.dumps(
                    payload or {'success': False, 'status': 'error', 'message': 'Failed to fetch', 'error': 'Failed to fetch'}))
        return respond

    def fill_concern(self, page):
        page.locator('#category').select_option('bug', force=True)
        page.locator('#subject').fill('Submission connection interrupted')
        page.locator('#message').fill('Please keep these details while I check My Concerns.')
        page.locator('#concern_images').set_input_files({
            'name': 'proof.png', 'mimeType': 'image/png', 'buffer': photo().read()})
        return page.locator('input[name="submission_key"]').input_value()

    def assert_concern_draft(self, page, key):
        from playwright.sync_api import expect

        expect(page.locator('#subject')).to_have_value('Submission connection interrupted')
        expect(page.locator('#message')).to_have_value('Please keep these details while I check My Concerns.')
        expect(page.locator('input[name="submission_key"]')).to_have_value(key)
        self.assertEqual(page.locator('#concern_images').evaluate('input => input.files.length'), 1)
        expect(page.locator('#concernImagePreview img')).to_have_count(1)

    def assert_toast(self, page, message):
        from playwright.sync_api import expect

        toast = page.locator('.client-feedback-toast[data-kind="error"]')
        expect(toast).to_contain_text(message)
        expect(toast).not_to_contain_text('Failed to fetch')
        expect(toast).not_to_contain_text('Unexpected')

    def dismiss_toast(self, page):
        from playwright.sync_api import expect

        page.get_by_role('button', name='Dismiss notification', exact=True).click()
        expect(page.locator('.client-feedback-toast')).to_have_count(0)
        # Repeated actions must outlast the toast's intentional rapid-message cooldown.
        page.wait_for_timeout(1600)

    def test_concern_submission_failures_are_friendly_and_keep_the_draft(self):
        from playwright.sync_api import expect

        for mode in ('network', 'malformed', 'technical', 'incomplete', 'html'):
            with self.subTest(mode=mode):
                page = self.page_for()
                page.goto(self.live_server_url + reverse('report_concern'))
                key = self.fill_concern(page)
                handler = self.failure(mode)
                page.route('**/report-concern/', handler, times=1)
                page.locator('#concernSubmit').click()
                friendly = "We couldn't confirm your submission. Check My Concerns before trying again."
                expect(page.locator('#concernSubmitStatus')).to_have_text(friendly)
                self.assert_toast(page, friendly)
                self.assert_concern_draft(page, key)
                expect(page.locator('#concernSubmit')).to_be_enabled()
                expect(page.locator('#concernSubmit')).to_have_text('Try again')
                page.screenshot(path=str(self.artifacts / f'concern-submit-{mode}.png'))
                page.close()
        self.assertEqual(self.db(lambda: ConcernTicket.objects.count()), 0)

    def test_committed_concern_with_lost_response_retries_without_duplicates(self):
        from playwright.sync_api import expect

        page = self.page_for()
        page.goto(self.live_server_url + reverse('report_concern'))
        key = self.fill_concern(page)
        posts = []

        def lose_first_response(route):
            if route.request.method != 'POST':
                route.continue_()
                return
            posts.append(route.request.url)
            if len(posts) == 1:
                response = route.fetch()
                self.assertEqual(response.status, 200)
                route.abort('failed')
            else:
                route.continue_()

        page.route('**/report-concern/', lose_first_response)
        page.evaluate("() => { for (let i=0; i<10; i++) document.querySelector('#concernForm').requestSubmit(); }")
        friendly = "We couldn't confirm your submission. Check My Concerns before trying again."
        expect(page.locator('#concernSubmitStatus')).to_have_text(friendly)
        self.assert_toast(page, friendly)
        self.assert_concern_draft(page, key)
        self.assertEqual(len(posts), 1)
        self.assertEqual(self.db(lambda: ConcernTicket.objects.count()), 1)
        self.dismiss_toast(page)
        page.get_by_role('button', name='Try again', exact=True).click()
        expect(page.locator('.concern-history-panel tbody tr')).to_have_count(1)
        expect(page.locator('.client-feedback-toast[data-kind="success"]')).to_contain_text('Concern submitted')
        expect(page.locator('#subject')).to_have_value('')
        self.assertEqual(len(posts), 2)
        self.assertNotEqual(page.locator('input[name="submission_key"]').input_value(), key)
        self.assertEqual(self.db(lambda: ConcernTicket.objects.count()), 1)
        self.assertEqual(self.db(lambda: ConcernImage.objects.count()), 1)

    def test_concern_cancellation_failures_keep_status_and_unsent_draft_then_retry(self):
        from playwright.sync_api import expect

        for mode in ('network', 'malformed', 'technical', 'incomplete', 'html'):
            with self.subTest(mode=mode):
                ticket = self.db(lambda: ConcernTicket.objects.create(user=self.user,
                    category='bug', subject=f'Cancel this concern {mode}', message='Original concern details.'))
                page = self.page_for()
                page.goto(self.live_server_url + reverse('report_concern'))
                key = self.fill_concern(page)
                page.get_by_role('button', name=f'View concern #CON-{ticket.pk}', exact=True).click()
                page.locator('#modalCancel').click()
                cancel_url = page.locator('#cancelConcernForm').get_attribute('action')
                handler = self.failure(mode)
                page.route('**' + cancel_url, handler, times=1)
                page.locator('#confirmCancelConcern').click()
                friendly = "We couldn't confirm the cancellation. Check your concern's status before trying again."
                expect(page.locator('#cancelConcernFeedback')).to_have_text(friendly)
                self.assert_toast(page, friendly)
                expect(page.locator('#concernCancelModal')).to_be_visible()
                expect(page.locator('#modalStatus')).to_have_text('New')
                self.assert_concern_draft(page, key)
                self.assertEqual(self.db(lambda: ConcernTicket.objects.get(pk=ticket.pk).status), 'new')
                page.screenshot(path=str(self.artifacts / f'concern-cancel-{mode}.png'))
                self.dismiss_toast(page)
                page.unroute('**' + cancel_url, handler)
                page.locator('#confirmCancelConcern').click()
                expect(page.locator('#modalStatus')).to_have_text('Cancelled')
                expect(page.locator('#concernCancelModal')).not_to_be_visible()
                expect(page.locator('.client-feedback-toast[data-kind="success"]')).to_contain_text('cancelled')
                page.keyboard.press('Escape')
                self.assert_concern_draft(page, key)
                self.assertEqual(self.db(lambda: ConcernTicket.objects.get(pk=ticket.pk).status), 'cancelled')
                page.close()

    def test_design_rename_and_delete_failures_preserve_design_then_succeed(self):
        from playwright.sync_api import expect

        design = UserDesign.objects.create(user=self.user, name='Original design', canvas_json='{"objects": []}')
        page = self.page_for()
        page.goto(self.live_server_url + reverse('my_designs'))
        page.locator('.menu-dots-btn').click()
        page.get_by_role('menuitem', name='Rename', exact=True).click()
        page.locator('#renameInput').fill('   ')
        page.get_by_role('button', name='Save Name', exact=True).click()
        expect(page.locator('#renameNameError')).to_have_text('Please enter a design name.')
        expect(page.locator('#renameInput')).to_have_attribute('aria-invalid', 'true')
        page.locator('#renameInput').fill('Renamed celebration')
        rename_url = f'**/my-designs/rename/{design.pk}/'
        for mode in ('network', 'malformed', 'technical', 'incomplete', 'html'):
            with self.subTest(action='rename', mode=mode):
                handler = self.failure(mode)
                page.route(rename_url, handler, times=1)
                page.get_by_role('button', name='Save Name', exact=True).click()
                friendly = "We couldn't confirm the new name. Check My Designs before trying again."
                expect(page.locator('#renameRequestError')).to_have_text(friendly)
                self.assert_toast(page, friendly)
                expect(page.locator('#renameInput')).to_have_value('Renamed celebration')
                expect(page.locator('.design-title')).to_have_text('Original design')
                expect(page.get_by_role('button', name='Save Name', exact=True)).to_be_enabled()
                self.dismiss_toast(page)
                page.unroute(rename_url, handler)
        page.screenshot(path=str(self.artifacts / 'design-rename-error.png'))
        page.get_by_role('button', name='Save Name', exact=True).click()
        expect(page.locator('#renameModal')).not_to_be_visible()
        expect(page.locator('.design-title')).to_have_text('Renamed celebration')
        expect(page.locator('.client-feedback-toast[data-kind="success"]')).to_contain_text('renamed')
        self.dismiss_toast(page)
        self.assertEqual(self.db(lambda: UserDesign.objects.get(pk=design.pk).name), 'Renamed celebration')
        delete_url = f'**/my-designs/delete/{design.pk}/'
        for mode in ('network', 'malformed', 'technical', 'incomplete', 'html'):
            with self.subTest(action='delete', mode=mode):
                handler = self.failure(mode)
                page.route(delete_url, handler, times=1)
                page.locator('.menu-dots-btn').click()
                page.get_by_role('menuitem', name='Delete', exact=True).click()
                page.get_by_role('button', name='Delete design', exact=True).click()
                self.assert_toast(page, "We couldn't confirm whether this design was deleted. Check My Designs before trying again.")
                expect(page.locator('.design-title')).to_have_text('Renamed celebration')
                self.assertTrue(self.db(lambda: UserDesign.objects.filter(pk=design.pk).exists()))
                self.dismiss_toast(page)
                page.unroute(delete_url, handler)
        page.locator('.menu-dots-btn').click()
        page.get_by_role('menuitem', name='Delete', exact=True).click()
        page.get_by_role('button', name='Delete design', exact=True).click()
        expect(page.locator('.design-card')).to_have_count(0)
        expect(page.locator('.client-feedback-toast[data-kind="success"]')).to_contain_text('deleted')
        self.assertFalse(self.db(lambda: UserDesign.objects.filter(pk=design.pk).exists()))

    def booking(self, user=None):
        return Booking.objects.create(user=user or self.user, event_date=date(2026, 1, 1), status='completed',
            event_type='Birthday', event_location='Manila', package_type='Package 1-A', total_price=4799)

    def test_review_save_preserves_validation_and_draft_and_reports_saved_after_refresh_failure(self):
        from playwright.sync_api import expect

        review = Review.objects.create(user=self.user, booking=self.booking(), rating=4, comment='Original review')
        page = self.page_for()
        page.goto(self.live_server_url + reverse('my_reviews'))
        page.get_by_role('button', name='Review options', exact=True).click()
        page.get_by_role('menuitem', name='Edit review', exact=True).click()
        page.locator('#edit-comment').fill('   ')
        page.get_by_role('button', name='Save Changes', exact=True).click()
        expect(page.locator('#edit_review_comment_error')).to_have_text('Please enter your review.')
        expect(page.locator('#edit-comment')).to_have_attribute('aria-invalid', 'true')
        page.locator('#edit-comment').fill('A review draft worth preserving')
        page.locator('label[for="edit-star5"]').click()
        page.locator('#edit_images_ui').set_input_files({
            'name': 'review-proof.png', 'mimeType': 'image/png', 'buffer': photo().read()})
        url = f'**/reviews/{review.pk}/edit/'
        for mode in ('network', 'malformed', 'technical', 'incomplete', 'html'):
            with self.subTest(mode=mode):
                handler = self.failure(mode)
                page.route(url, handler, times=1)
                page.get_by_role('button', name='Save Changes', exact=True).click()
                expect(page.locator('.review-form-server-error')).to_have_text(
                    "We couldn't confirm whether your review was saved. Check My Reviews before trying again.")
                expect(page.locator('#editReviewModal')).to_be_visible()
                expect(page.locator('#edit-comment')).to_have_value('A review draft worth preserving')
                expect(page.locator('#edit-star5')).to_be_checked()
                self.assertEqual(page.locator('#edit_images').evaluate('input => input.files.length'), 1)
                expect(page.get_by_role('button', name='Save Changes', exact=True)).to_be_enabled()
                page.unroute(url, handler)
        validation = self.failure('technical', {'status': 'error', 'message': 'Please enter your review.'})
        page.route(url, validation, times=1)
        page.get_by_role('button', name='Save Changes', exact=True).click()
        expect(page.locator('.review-form-server-error')).to_have_text('Please enter your review.')
        page.unroute(url, validation)
        page.screenshot(path=str(self.artifacts / 'review-save-error.png'))
        page.route('**/my-reviews/**', lambda route: route.abort('failed'))
        page.get_by_role('button', name='Save Changes', exact=True).click()
        expect(page.locator('#editReviewModal')).not_to_be_visible()
        expect(page.locator('.review-refresh-error')).to_be_visible()
        expect(page.locator('.client-feedback-toast[data-kind="success"]')).to_contain_text('Review')
        expect(page.locator('.review-content')).to_have_text('Original review')
        self.assertEqual(self.db(lambda: Review.objects.get(pk=review.pk).comment), 'A review draft worth preserving')
        self.assertEqual(self.db(lambda: Review.objects.get(pk=review.pk).rating), 5)
        self.assertEqual(self.db(lambda: Review.objects.count()), 1)
        page.screenshot(path=str(self.artifacts / 'review-saved-refresh-failed.png'))

    def test_review_like_errors_keep_count_then_normal_like_succeeds(self):
        from playwright.sync_api import expect

        author = User.objects.create_user(username='other-reviewer', role='customer', email_verified=True)
        review = Review.objects.create(user=author, booking=self.booking(author), rating=5, comment='Another customer review')
        page = self.page_for()
        page.goto(self.live_server_url + reverse('reviews'))
        like = page.locator(f'.like-btn[data-id="{review.pk}"]')
        url = f'**/reviews/{review.pk}/like/'
        for mode in ('network', 'malformed', 'technical', 'incomplete', 'html'):
            with self.subTest(mode=mode):
                handler = self.failure(mode)
                page.route(url, handler, times=1)
                like.click()
                self.assert_toast(page, "We couldn't update your like. Please try again.")
                expect(like.locator('.like-count')).to_have_text('0')
                expect(like).to_be_enabled()
                self.assertNotIn('liked', (like.get_attribute('class') or '').split())
                self.dismiss_toast(page)
                page.unroute(url, handler)
        like.click()
        expect(like.locator('.like-count')).to_have_text('1')
        self.assertIn('liked', like.get_attribute('class').split())
        self.assertTrue(self.db(lambda: review.likes.filter(pk=self.user.pk).exists()))

    def test_admin_concern_failures_keep_current_list_and_update_draft_then_save(self):
        from playwright.sync_api import expect

        ticket = ConcernTicket.objects.create(user=self.user, category='bug', subject='Admin error regression', message='Help needed.')
        admin = User.objects.create_user(username='error-browser-admin', role='admin', email_verified=True, is_staff=True)
        admin_client = Client()
        admin_client.force_login(admin)
        page = self.page_for(admin_client)
        page.goto(self.live_server_url + reverse('admin_concerns'))
        expect(page.locator('.btn-view-concern')).to_have_count(1)
        for mode in ('network', 'malformed', 'technical', 'incomplete', 'html'):
            with self.subTest(action='list', mode=mode):
                handler = self.failure(mode)
                page.route('**/staff/concerns/?**', handler, times=1)
                with page.expect_request('**/staff/concerns/?**'):
                    page.get_by_role('searchbox', name='Search concerns', exact=True).fill('Admin ' + mode)
                expect(page.locator('#adminConcernResults[aria-busy]')).to_have_count(0)
                expect(page.locator('#acListFeedback')).to_contain_text("We couldn't load the concerns. Please try again.")
                expect(page.locator('#adminConcernResults')).to_contain_text('Admin error regression')
                expect(page.locator('.btn-view-concern')).to_have_count(1)
                expect(page.get_by_role('searchbox', name='Search concerns', exact=True)).to_have_value('Admin ' + mode)
                page.unroute('**/staff/concerns/?**', handler)
        page.locator('.btn-view-concern').click()
        expect(page.locator('#concernUpdateForm')).to_be_visible()
        page.get_by_role('button', name='Concern status: New', exact=True).click()
        page.get_by_role('option', name='In Progress', exact=True).click()
        page.locator('#acUpdateNotes').fill('Keep this customer update draft.')
        url = '**' + page.locator('#concernUpdateForm').get_attribute('action')
        for mode in ('network', 'malformed', 'technical', 'incomplete', 'html'):
            with self.subTest(action='write', mode=mode):
                handler = self.failure(mode)
                page.route(url, handler, times=1)
                page.locator('#acUpdateSubmit').click()
                friendly = "We couldn't confirm the change. Check this concern's latest status before trying again."
                expect(page.locator('#acUpdateFeedback')).to_have_text(friendly)
                expect(page.locator('.cfg-toast[data-kind="error"]')).to_contain_text(friendly)
                expect(page.locator('#acUpdateNotes')).to_have_value('Keep this customer update draft.')
                expect(page.locator('#acUpdateStatus')).to_have_value('in_progress')
                expect(page.locator('#acUpdateSubmit')).to_be_enabled()
                expect(page.locator('#adminConcernResults')).to_contain_text('Admin error regression')
                self.assertEqual(self.db(lambda: ConcernTicket.objects.get(pk=ticket.pk).status), 'new')
                page.unroute(url, handler)
        page.screenshot(path=str(self.artifacts / 'admin-concern-update-error.png'))
        page.route(re.compile(r'/staff/concerns/(?:\?.*)?$'), lambda route: route.abort('failed'))
        page.locator('#acUpdateSubmit').click()
        expect(page.locator('#acDetailStatus')).to_have_text('In Progress')
        expect(page.locator('#acUpdateFeedback')).to_have_attribute('data-kind', 'success')
        expect(page.locator('.cfg-toast[data-kind="success"]')).to_be_visible()
        expect(page.locator('#acListFeedback')).to_contain_text("We couldn't load the concerns. Please try again.")
        expect(page.locator('#acUpdateFeedback')).not_to_contain_text("couldn't confirm")
        self.assertEqual(self.db(lambda: ConcernTicket.objects.get(pk=ticket.pk).status), 'in_progress')
        self.assertEqual(self.db(lambda: ConcernTicket.objects.get(pk=ticket.pk).admin_notes), 'Keep this customer update draft.')
        page.screenshot(path=str(self.artifacts / 'admin-concern-saved-refresh-failed.png'))

    def test_invitation_page_loads_error_helper_and_keeps_passwords_on_failures(self):
        from playwright.sync_api import expect

        owner = User.objects.create_superuser(username='error-invite-owner', role='admin',
            email='owner@example.com', password='Owner!Password234', email_verified=True)
        token = 'b' * 43
        invitation = AdminInvitation.objects.create(email='invited@example.com', first_name='Jamie', last_name='Rivera',
            phone_number='09171234567', created_by=owner, creator_email=owner.email,
            creator_password_digest=digest('admin-password', owner.password), token_digest=digest('admin-invite', token),
            expires_at=timezone.now() + timedelta(days=1))
        page = self.page_for(anonymous=True)
        page.goto(self.live_server_url + reverse('admin_invitation_open', args=[invitation.pk, token]))
        expect(page.locator('[data-invitation-accept]')).to_be_visible()
        self.assertEqual(page.evaluate('typeof window.AppErrors?.message'), 'function')
        page.locator('#invitationPassword').fill('Customer!Password234')
        page.locator('#invitationConfirm').fill('Different!Password234')
        page.get_by_role('button', name='Create my admin account', exact=True).click()
        expect(page.locator('#invitationConfirmError')).to_have_text('Passwords do not match.')
        page.locator('#invitationConfirm').fill('Customer!Password234')
        for mode in ('network', 'malformed', 'technical', 'incomplete', 'html'):
            with self.subTest(mode=mode):
                handler = self.failure(mode)
                page.route('**/admin-invitation/accept/', handler, times=1)
                page.get_by_role('button', name='Create my admin account', exact=True).click()
                expect(page.locator('[data-invitation-feedback]')).to_have_text(
                    "We couldn't confirm whether your account was created. Try signing in before submitting again.")
                expect(page.locator('#invitationPassword')).to_have_value('Customer!Password234')
                expect(page.locator('#invitationConfirm')).to_have_value('Customer!Password234')
                expect(page.get_by_role('button', name='Create my admin account', exact=True)).to_be_enabled()
                page.unroute('**/admin-invitation/accept/', handler)
        self.assertFalse(self.db(lambda: User.objects.filter(email='invited@example.com').exists()))
        self.assertEqual(self.db(lambda: AdminInvitation.objects.get(pk=invitation.pk).status), 'pending')

    def test_admin_booking_incomplete_response_keeps_current_results(self):
        from playwright.sync_api import expect

        self.booking()
        admin = User.objects.create_user(username='booking-error-admin', role='admin', email_verified=True)
        client = Client()
        client.force_login(admin)
        page = self.page_for(client)
        page.goto(self.live_server_url + reverse('admin_booking_list'))
        results = page.locator('[data-workspace-content]')
        original = results.inner_text()
        page.route('**/staff/bookings/?**', self.failure('incomplete'), times=1)
        page.locator('[data-booking-filters]').evaluate('form => form.requestSubmit()')
        expect(page.locator('[data-load-error]')).to_contain_text("We couldn't load the bookings.")
        expect(results).to_have_text(original, use_inner_text=True)
