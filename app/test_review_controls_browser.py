"""Opt-in browser coverage for the shared review controls and real review editing."""
import io
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from .models import Booking, Review, ReviewImage, User


@skipUnless(os.environ.get('RUN_REVIEWS_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, REQUEST_RATE_LIMITING_ENABLED=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ReviewControlsBrowserTests(StaticLiveServerTestCase):
    def test_shared_forms_menu_photos_keyboard_upload_and_save(self):
        from playwright.sync_api import expect, sync_playwright

        user = User.objects.create_user(username='review-browser', first_name='Jamie', last_name='Rivera',
            email='reviews@example.com', password='ExistingPassword!25', role='customer', email_verified=True)
        def booking():
            return Booking.objects.create(user=user, event_date=date(2026, 1, 1), status='completed',
                event_type='Birthday', event_location='Manila', package_type='Package 1-A', total_price=4799)
        review = Review.objects.create(user=user, booking=booking(), rating=4, comment='Our original review')
        photo = ReviewImage.objects.create(review=review, image='review_images/browser-fixture.png')
        pending = booking()
        self.client.force_login(user)
        session = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        output = io.BytesIO()
        Image.new('RGB', (800, 1000), '#b69a76').save(output, 'PNG')
        fixture = output.getvalue()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width':1440, 'height':1000}, reduced_motion='reduce')
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': session, 'url': self.live_server_url}])
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            sweetalert = artifacts / 'sweetalert2.all.min.js'
            if sweetalert.exists():
                context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(
                    content_type='application/javascript', body=sweetalert.read_text(encoding='utf-8')))
            context.route('**/media/review_images/browser-fixture.png', lambda route: route.fulfill(content_type='image/png', body=fixture))
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def hover_color(theme):
                # Chrome versions serialize very low alpha values differently.
                return page.evaluate('''color => {
                    const probe = document.createElement('div');
                    probe.style.backgroundColor = color; document.body.append(probe);
                    const value = getComputedStyle(probe).backgroundColor; probe.remove(); return value;
                }''', 'rgba(0,0,0,.022)' if theme == 'light' else 'rgba(255,255,255,.035)')
            def drop_files(zone, names):
                transfer = page.evaluate_handle('''({bytes, names}) => {
                    const data = new DataTransfer();
                    names.forEach(name => data.items.add(new File([new Uint8Array(bytes)], name,
                        {type: name.endsWith('.txt') ? 'text/plain' : 'image/png'})));
                    return data;
                }''', {'bytes':list(fixture), 'names':names})
                zone.dispatch_event('dragenter', {'dataTransfer':transfer})
                expect(zone).to_have_class('review-upload-zone is-dragging')
                zone.dispatch_event('drop', {'dataTransfer':transfer})
                expect(zone).to_have_class('review-upload-zone')
                transfer.dispose()
            try:
                for route in ('my_reviews', 'reviews'):
                    page.goto(self.live_server_url + reverse(route), wait_until='domcontentloaded')
                    page.evaluate('window.reviewReloadSentinel = "preserved"')
                    if route == 'my_reviews':
                        for layout_theme in ('light','dark'):
                            for layout_width in (1440,768,390,320):
                                page.set_viewport_size({'width':layout_width,'height':1000 if layout_width==1440 else 844})
                                page.evaluate('(theme)=>{document.documentElement.dataset.theme=theme; window.scrollTo(0,0);}',layout_theme)
                                self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth + 1'))
                                for section in ('.mr-stats','#awaiting-reviews','.mr-published-section'):
                                    box = page.locator(section).bounding_box()
                                    self.assertGreaterEqual(box['x'],0)
                                    self.assertLessEqual(box['x']+box['width'],layout_width)
                                card = page.locator('.pending-review-card').first
                                button = card.get_by_role('button', name='Leave a Review')
                                border = 'rgb(229, 229, 229)' if layout_theme == 'light' else 'rgb(48, 48, 48)'
                                page.locator('.my-reviews-title').hover()
                                expect(card).to_have_css('border-color', border)
                                card.hover()
                                expect(card).to_have_css('border-color', 'rgb(206, 206, 206)' if layout_theme == 'light' else 'rgb(74, 74, 74)')
                                expect(card).to_have_css('box-shadow', 'none')
                                accents = ('rgb(148, 96, 0)', 'rgb(24, 116, 71)', 'rgb(40, 94, 175)') if layout_theme == 'light' else ('rgb(232, 188, 98)', 'rgb(123, 212, 161)', 'rgb(147, 180, 255)')
                                for stat, accent in zip(page.locator('.mr-stat').all(), accents):
                                    for element in ('.mr-stat-label', '.mr-stat-num', '.mr-stat-top svg'):
                                        expect(stat.locator(element)).to_have_css('color', accent)
                                button.hover()
                                expect(button).to_have_css('border-color', border)
                                expect(button).to_have_css('background-color', hover_color(layout_theme))
                                page.screenshot(path=str(artifacts/f'my-reviews-layout-{layout_theme}-{layout_width}.png'),full_page=True)
                    for theme in ('light', 'dark'):
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        for width, height in ((1440,1000), (390,844), (320,568), (640,360)):
                            page.set_viewport_size({'width':width,'height':height})
                            trigger = page.get_by_role('button', name='Review options', exact=True).first
                            trigger.click()
                            menu = page.get_by_role('menu', name='Review actions')
                            expect(menu).to_be_visible()
                            expect(trigger).to_have_attribute('aria-expanded','true')
                            menu_bounds = menu.bounding_box()
                            self.assertGreaterEqual(menu_bounds['x'],0)
                            self.assertLessEqual(menu_bounds['x']+menu_bounds['width'],width)
                            if width in (1440,390):
                                page.screenshot(path=str(artifacts / f'review-menu-{route}-{theme}-{width}.png'))
                            expect(menu.get_by_role('menuitem',name='Edit review')).to_be_focused()
                            page.keyboard.press('ArrowDown')
                            expect(menu.get_by_role('menuitem',name='Delete review')).to_be_focused()
                            page.keyboard.press('Escape')
                            expect(menu).not_to_be_visible()
                            expect(trigger).to_be_focused()
                            trigger.click()
                            menu.get_by_role('menuitem',name='Edit review').click()
                            dialog = page.locator('#editReviewModal')
                            expect(dialog).to_be_visible()
                            expect(page.locator('#edit-comment')).to_have_value('Our original review')
                            expect(page.locator('#edit-star4')).to_be_checked()
                            expect(page.locator('#edit-star-rating label.active')).to_have_count(4)
                            red = 'rgb(184, 53, 60)' if theme == 'light' else 'rgb(241, 145, 145)'
                            comment = page.locator('#edit-comment')
                            expect(dialog.locator('.review-required').first).to_have_css('color', red)
                            expect(dialog.locator('#editUploadHint')).to_contain_text('5MB per photo')
                            expect(dialog.locator('.review-optional')).to_have_text('(optional)')
                            comment.fill('   ')
                            expect(comment).to_have_attribute('aria-invalid', 'true')
                            expect(comment).to_have_css('border-color', red)
                            expect(comment).to_have_css('outline-color', 'rgba(184, 53, 60, 0.4)' if theme == 'light' else 'rgba(241, 145, 145, 0.4)')
                            expect(dialog.locator('#edit_review_comment_error')).to_have_css('color', red)
                            expect(dialog.locator('#edit_review_comment_error')).to_have_css('font-weight', '400')
                            comment.fill('Our original review')
                            expect(comment).to_have_attribute('aria-invalid', 'false')
                            expect(comment).to_have_css('outline-color', 'rgba(105, 105, 105, 0.4)' if theme == 'light' else 'rgba(153, 153, 153, 0.45)')
                            bounds = dialog.locator('.modal-card').bounding_box()
                            self.assertGreaterEqual(bounds['y'],0)
                            self.assertLessEqual(bounds['y']+bounds['height'],height)
                            self.assertLessEqual(bounds['x']+bounds['width'],width)
                            footer = dialog.locator('.review-dialog__actions').bounding_box()
                            self.assertLessEqual(footer['y']+footer['height'],height)
                            close_button = dialog.get_by_role('button',name='Close edit review')
                            close_button.hover()
                            expect(close_button).to_have_css('background-color', hover_color(theme))
                            if width in (1440,390):
                                page.screenshot(path=str(artifacts / f'review-upload-{route}-{theme}-{width}.png'))
                            self.assertEqual(page.evaluate('document.body.style.overflow'),'hidden')
                            for _ in range(12):
                                page.keyboard.press('Tab')
                                self.assertTrue(dialog.evaluate('el => el.contains(document.activeElement)'))
                            dialog.get_by_role('button',name='Close edit review').click()
                            expect(dialog).not_to_be_visible()
                            expect(trigger).to_be_focused()
                            self.assertNotEqual(page.evaluate('document.body.style.overflow'),'hidden')
                            image = page.locator('.review-uploaded-img').first
                            image.focus()
                            page.keyboard.press('Enter')
                            viewer = page.locator('#imageModal')
                            expect(viewer).to_be_visible()
                            expect(viewer.get_by_role('button',name='Close review photo')).to_be_focused()
                            expect(page.locator('#expandedImg')).to_have_attribute('src', self.live_server_url + photo.image.url)
                            page.wait_for_function('document.getElementById("expandedImg").complete && document.getElementById("expandedImg").naturalWidth > 0')
                            close_bounds = viewer.get_by_role('button',name='Close review photo').bounding_box()
                            viewer.get_by_role('button',name='Close review photo').hover()
                            expect(viewer.get_by_role('button',name='Close review photo')).to_have_css('background-color', hover_color(theme))
                            self.assertGreaterEqual(close_bounds['y'],0)
                            self.assertLessEqual(close_bounds['x']+close_bounds['width'],width)
                            if width in (1440,390):
                                page.screenshot(path=str(artifacts / f'review-photo-{route}-{theme}-{width}.png'))
                            page.keyboard.press('Escape')
                            expect(viewer).not_to_be_visible()
                            expect(image).to_be_focused()
                    page.set_viewport_size({'width':1440,'height':1000})
                    trigger.click()
                    menu.get_by_role('menuitem',name='Edit review').click()
                    page.locator('#edit_images_ui').set_input_files({'name':'oversized.png','mimeType':'image/png','buffer':b'x' * (5 * 1024 * 1024 + 1)})
                    expect(page.locator('#editReviewForm .review-upload-size-error')).to_be_visible()
                    expect(page.locator('#edit-unified-images-preview img')).to_have_count(1)
                    self.assertEqual(page.locator('#edit_images').evaluate('el => el.files.length'),0)
                    drop_files(page.locator('#editReviewForm [data-review-upload]'), ['new-photo.png','document.txt'])
                    expect(page.locator('#editReviewForm .review-upload-size-error')).to_be_hidden()
                    expect(page.locator('#edit-unified-images-preview img')).to_have_count(2)
                    expect(page.locator('#editReviewForm .review-upload-type-error')).to_be_visible()
                    page.locator('#edit-unified-images-preview .new-review-image button').click()
                    expect(page.locator('#edit-unified-images-preview img')).to_have_count(1)
                    self.assertEqual(page.locator('#edit_images').evaluate('el => el.files.length'),0)
                    with page.expect_file_chooser() as chooser:
                        page.get_by_role('button',name='Browse Files',exact=True).click()
                    chooser.value.set_files({'name':'picked-photo.png','mimeType':'image/png','buffer':fixture})
                    expect(page.locator('#editReviewForm .review-upload-type-error')).to_be_hidden()
                    expect(page.locator('#edit-unified-images-preview img')).to_have_count(2)
                    page.locator('#edit-unified-images-preview .new-review-image button').click()
                    page.locator('#edit-comment').fill('   ')
                    page.get_by_role('button',name='Save Changes',exact=True).click()
                    expect(page.locator('#edit_review_comment_error')).to_be_visible()
                    expect(page.locator('#edit-comment')).to_be_focused()
                    page.locator('#edit-comment').fill('Our original review')
                    page.locator('label[for="edit-star5"]').click()
                    expect(page.locator('#edit-star5')).to_be_checked()
                    expect(page.locator('#edit-star-rating label.active')).to_have_count(5)
                    self.assertEqual(page.locator('label[for="edit-star5"]').evaluate('el => getComputedStyle(el).color'),'rgb(245, 158, 11)')
                    page.screenshot(path=str(artifacts / f'review-edit-{route}.png'))
                    with page.expect_response('**/reviews/*/edit/') as response:
                        page.get_by_role('button',name='Save Changes',exact=True).click()
                    self.assertEqual(response.value.status,200)
                    expect(page.locator('#editReviewModal')).not_to_be_visible()
                    # Wait for the actual replacement card and ensure its controls still work.
                    expect(page.locator('.review-card').first).to_have_attribute('data-rating','5')
                    self.assertEqual(page.evaluate('window.reviewReloadSentinel'),'preserved')
                    page.get_by_role('button',name='Review options').first.click()
                    page.get_by_role('menuitem',name='Edit review').click()
                    expect(page.locator('#edit-star5')).to_be_checked()
                    page.keyboard.press('Escape')
                    # Reset the fixture's rating before inspecting the other page.
                    with ThreadPoolExecutor() as pool:
                        pool.submit(lambda: Review.objects.filter(pk=review.pk).update(rating=4)).result()

                page.goto(self.live_server_url + reverse('my_reviews'),wait_until='domcontentloaded')
                page.evaluate('window.reviewReloadSentinel = "preserved"')
                for theme in ('light','dark'):
                    page.evaluate('(theme) => document.documentElement.dataset.theme = theme',theme)
                    page.set_viewport_size({'width':390,'height':844})
                    page.get_by_role('button',name='Leave a Review').click()
                    page.locator('#reviewForm [data-review-upload]').evaluate('''zone => {
                        const data = new DataTransfer();
                        data.items.add(new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'oversized.png', {type:'image/png'}));
                        zone.dispatchEvent(new DragEvent('drop', {bubbles:true, cancelable:true, dataTransfer:data}));
                    }''')
                    expect(page.locator('#reviewForm .review-upload-size-error')).to_be_visible()
                    self.assertEqual(page.locator('#review_images').evaluate('el => el.files.length'),0)
                    page.get_by_role('button',name='Submit Review',exact=True).click()
                    expect(page.locator('#review_rating_error')).to_be_visible()
                    expect(page.locator('#review_comment_error')).to_be_visible()
                    page.locator('label[for="star4"]').click()
                    expect(page.locator('#star4')).to_be_checked()
                    page.locator('#review_comment').fill('Lovely setup for our celebration.')
                    expect(page.locator('#reviewForm .form-group.has-error')).to_have_count(0)
                    expect(page.locator('#review_comment')).not_to_have_class('has-error')
                    drop_files(page.locator('#reviewForm [data-review-upload]'), [f'photo-{i}.png' for i in range(5)])
                    expect(page.locator('#create-unified-images-preview img')).to_have_count(4)
                    expect(page.locator('#createImageLimitError')).to_be_visible()
                    page.screenshot(path=str(artifacts / f'review-create-{theme}-390.png'))
                    page.get_by_role('button',name='Cancel',exact=True).click()
                    page.get_by_role('button',name='Leave a Review').click()
                    expect(page.locator('#review_comment')).to_have_value('')
                    expect(page.locator('#reviewForm input:checked')).to_have_count(0)
                    expect(page.locator('#create-unified-images-preview img')).to_have_count(0)
                    page.keyboard.press('Escape')
                page.get_by_role('button',name='Leave a Review').click()
                page.locator('label[for="star5"]').click()
                page.locator('#review_comment').fill('Wonderful event setup.')
                page.get_by_role('button',name='Submit Review',exact=True).click()
                page.wait_for_url(self.live_server_url+reverse('my_reviews'))
                expect(page.locator('.review-content').filter(has_text='Wonderful event setup.')).to_be_visible()
                expect(page.get_by_text('All caught up',exact=True)).to_be_visible()
                self.assertEqual(page.evaluate('window.reviewReloadSentinel'),'preserved')
                self.assertEqual(errors,[])
            finally:
                context.close()
                browser.close()
