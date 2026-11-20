import os
from unittest import skipUnless

from django.urls import reverse

from . import test_booking_form_feedback_browser as fixtures


@skipUnless(os.environ.get('RUN_BOOKING_FORM_FEEDBACK_BROWSER') == '1', 'Optional Playwright verification')
class BookingConfirmationBrowserTests(fixtures.BookingFormFeedbackBrowserTests):
    # Keep this suite limited to confirmation; inherited helpers share the setup.
    test_required_event_and_design_fields_scroll_and_focus_consistently = None
    test_map_status_colors_survive_light_and_dark_themes = None

    def test_create_confirmation_exact_copy_and_review_again_sends_nothing(self):
        from playwright.sync_api import expect
        with self.browser_page() as page:
            self.open_form(page, 'create')
            page.locator('#eventTypeCustomSelect .custom-select-trigger').click()
            page.locator('#eventTypeCustomSelect [data-value="Birthday"]').click()
            page.locator('#event_location').fill('Molino Bacoor Cavite venue')
            page.evaluate('''() => {
                for(const [name,value] of Object.entries({event_date:'2099-07-17',start_time:'07:00',end_time:'10:00',event_lat_input:'14.414',event_lng_input:'120.982'})){
                    const input=document.getElementById(name);input.value=value;input.dispatchEvent(new Event('change',{bubbles:true}));
                }
            }''')
            page.locator('#btnNextToSummary').click()
            page.locator('.package-card[data-package="Package 2"] .package-info').click()
            page.locator('#btnNextStep').click()
            page.locator('#designThemeChips [data-value="Princess"]').click()
            page.locator('#designPaletteSwatches [data-color="Pink"]').click()
            page.locator('#btnNextDesignToReview').click()
            endpoint = page.locator('#bookingForm').get_attribute('action')
            submissions=[]
            page.route(self.live_server_url+endpoint, lambda route: (submissions.append(route.request),route.fulfill(json={'success':False,'message':'Please review your event date.'})))
            page.locator('#btnSubmitBooking').click()
            dialog=page.locator('dialog.client-feedback-dialog')
            expect(dialog.get_by_role('heading')).to_have_text('Submit your booking request?')
            expect(dialog).to_contain_text('Please review your event details, venue pin, and selected items. Our team will review your request and notify you once it’s approved.')
            dialog.get_by_role('button',name='Review Again',exact=True).click()
            self.assertEqual(len(submissions),0)
            expect(page.locator('#step-4')).to_be_visible()
            page.locator('#btnSubmitBooking').click()
            dialog.get_by_role('button',name='Submit Request',exact=True).click()
            expect(page.locator('#btnSubmitBooking')).to_be_enabled()
            self.assertEqual(len(submissions),1)
