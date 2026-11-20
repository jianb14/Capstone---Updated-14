"""Public errors preserve useful recovery steps and keep diagnostics private."""
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from . import services
from .ai_jobs import JobError, create_request
from .ai_images import owned_image_name
from .design_validation import evaluate_design
from .models import User
from .offer_editor import validate_rows
from .payment_forms import GCashProofForm, clean_payment_image
from .request_protection import RateLimited, limit_response
from .views import ai, chat, designs, notifications, payments, public
from .views.common import compute_overtime, _email_request_limit


DESIGN_READ_ERROR = "We couldn't read this design. Keep this page open and try again, or contact our team for help."
QUIZ_UNAVAILABLE = "We couldn't create a theme suggestion right now. Please try again later or contact our team for help."


class PublicErrorMessagesTests(SimpleTestCase):
    @patch('app.request_protection.consume_rules', side_effect=OperationalError('private database detail'))
    def test_email_request_limit_store_failure_keeps_retry_without_technical_copy(self, consume):
        request = RequestFactory().post('/')
        limited, message = _email_request_limit(request, 'customer@example.com', 'verify', 'EMAIL_VERIFY', 'verification')
        self.assertTrue(limited)
        self.assertEqual(message, "We can't complete this action right now. Please try again in 5 seconds.")
        self.assertEqual(request._email_retry_after, 5)
        self.assertEqual(request._email_limit_status, 503)

    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_authenticated=True, role='customer', id=1)

    def request(self, payload=None):
        request = self.factory.post('/', json.dumps(payload or {}), content_type='application/json')
        request.user = self.user
        return request

    def payload(self, response):
        return json.loads(response.content)

    @patch('app.views.designs.create_saved_design', side_effect=OperationalError('secret database host password=private'))
    def test_design_save_failure_hides_exception_and_logs_it(self, create):
        with self.assertLogs('app.views.designs', level='ERROR') as logs:
            response = designs.save_user_design(self.request({'canvas_json': {'objects': []}}))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.payload(response)['message'], "We couldn't confirm whether your design was saved. Check My Designs before trying again.")
        self.assertNotIn('private', response.content.decode())
        self.assertIn('secret database host', '\n'.join(logs.output))

    @patch('app.views.designs.get_object_or_404')
    def test_design_rename_failure_hides_exception_and_logs_it(self, get_design):
        get_design.return_value.save.side_effect = OperationalError('private SQL details')
        with self.assertLogs('app.views.designs', level='ERROR'):
            response = designs.rename_user_design(self.request({'name': 'New name'}), 42)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.payload(response)['message'], "We couldn't confirm the new name. Check your designs before trying again.")

    @patch('app.views.designs.get_object_or_404')
    def test_design_delete_failure_hides_exception_and_logs_it(self, get_design):
        get_design.return_value.delete.side_effect = OperationalError('private storage credentials')
        with self.assertLogs('app.views.designs', level='ERROR'):
            response = designs.delete_user_design(self.request(), 42)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.payload(response)['message'], "We couldn't confirm whether this design was deleted. Check My Designs before trying again.")

    def test_unreadable_canvas_is_rejected_without_losing_save_guard(self):
        for payload in ([], {'canvas_json': 'not-json'}, {'canvas_json': {'objects': 'wrong'}}):
            with self.subTest(payload=payload):
                request = self.request()
                request._body = json.dumps(payload).encode()
                response = designs.save_user_design(request)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.payload(response)['message'], DESIGN_READ_ERROR)
        self.assertEqual(evaluate_design('not-json', None)['invalid_items'], [DESIGN_READ_ERROR])

    def test_design_permission_denial_still_blocks_all_write_endpoints(self):
        self.user.role = 'admin'
        for endpoint, args in ((designs.save_user_design, ()), (designs.rename_user_design, (42,)), (designs.delete_user_design, (42,))):
            with self.subTest(endpoint=endpoint.__name__):
                response = endpoint(self.request(), *args)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.payload(response)['message'], "You don't have permission to change this design. Sign in with the account that owns it.")

    @patch('app.views.designs.log_action')
    @patch('app.views.designs.get_object_or_404')
    def test_design_rename_success_and_required_name_are_preserved(self, get_design, log):
        design = Mock()
        get_design.return_value = design
        response = designs.rename_user_design(self.request({'name': '  Birthday  '}), 42)
        self.assertEqual(self.payload(response), {'status': 'success', 'name': 'Birthday'})
        design.save.assert_called_once_with()
        response = designs.rename_user_design(self.request({'name': ' '}), 42)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.payload(response)['message'], 'Name cannot be empty')

    def test_rate_limit_preserves_dynamic_wait_and_header(self):
        response = limit_response(self.request(), RateLimited(6.2))
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['Retry-After'], '7')
        self.assertIn('Please wait 7 seconds before trying again.', response.content.decode())

    def test_bad_booking_time_explains_which_fields_to_use(self):
        result = compute_overtime('not-time', '12:00', policy={'included_hours': 3})
        self.assertEqual(result['error'], 'Choose the start and end times using the time fields.')

    def test_invalid_offer_row_explains_recovery(self):
        rows, errors = validate_rows(['broken row'], [])
        self.assertFalse(rows)
        self.assertEqual(errors['0']['name'], ["We couldn't read this inclusion. Remove it and add it again."])

    def test_unreadable_notification_ack_hides_parser_details(self):
        request = self.request()
        request._body = b'{bad json'
        response = notifications.ack_customer_update_bar(request)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.payload(response)['message'], "We couldn't update your notifications. Refresh the list and try again.")

    def test_catalog_and_content_json_permission_denials_remain_forbidden(self):
        from . import catalog_admin, content_admin
        for endpoint, args in ((catalog_admin.catalog_workspace, ('packages',)), (content_admin.content_workspace, ('home',))):
            with self.subTest(endpoint=endpoint.__name__):
                request = self.factory.get('/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                request.user = self.user
                response = endpoint(request, *args)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.payload(response)['message'], "You don't have permission to make this change.")

    @patch('app.views.payments.messages.info')
    @patch('app.views.payments.get_object_or_404')
    def test_leaving_checkout_keeps_payment_pending_and_review_required(self, get_booking, info):
        payment = SimpleNamespace(payment_status='pending', payment_method='paymongo_gcash',
            paymongo_checkout_session_id='checkout', paymongo_payment_id='', received_at=None,
            notes='', save=Mock())
        get_booking.return_value.payments.filter.return_value.order_by.return_value.first.return_value = payment
        response = payments.paymongo_cancel(self.request(), 42)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(payment.payment_status, 'pending')
        self.assertIn("We haven't confirmed the previous payment attempt yet.", payment.notes)
        self.assertNotIn('did not complete', payment.notes)
        self.assertTrue(payments._is_abandoned_paymongo_payment(payment))
        self.assertFalse(payments._is_incomplete_paymongo_payment(payment))
        self.assertIs(payments._unresolved_legacy_checkout([payment]), payment)

    def test_invalid_payment_image_and_help_explain_size_and_resolution(self):
        upload = SimpleUploadedFile('broken.png', b'not an image', content_type='image/png')
        with self.assertRaises(ValidationError) as caught:
            clean_payment_image(upload)
        self.assertIn('crop it or choose a smaller image', str(caught.exception))
        self.assertIn('12 megapixels', GCashProofForm().fields['receipt_image'].help_text)
        content = io.BytesIO()
        Image.new('RGB', (2, 2)).save(content, 'PNG')
        valid = clean_payment_image(SimpleUploadedFile('proof.png', content.getvalue(), content_type='image/png'))
        self.assertEqual(valid.content_type, 'image/png')

    def test_ai_role_denial_and_missing_legacy_message_use_public_copy(self):
        self.user.role = 'admin'
        response = ai.ai_request_active(self.factory_request('get'))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.payload(response)['error'], 'Please sign in again to use the assistant.')
        self.user.role = 'customer'
        response = chat.chat_reaction(self.request())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.payload(response)['error'], "We couldn't find the selected message. Reopen the conversation and try again.")

    def test_malformed_ai_image_url_has_safe_recovery_message(self):
        with self.assertRaises(ValueError) as caught:
            owned_image_name(self.user, 'https://[invalid')
        self.assertEqual(str(caught.exception), "We couldn't find this image. Reopen it from your chat and try again.")

    def factory_request(self, method):
        request = getattr(self.factory, method)('/')
        request.user = self.user
        return request

    @patch('app.services.evaluate_chat_moderation', return_value=None)
    def test_missing_ai_configuration_is_a_service_error(self, moderate):
        for client, api_key in ((None, 'test'), (Mock(), '')):
            with self.subTest(client=client), patch('app.services.InferenceClient', client), override_settings(HUGGINGFACE_API_KEY=api_key):
                payload = services.get_chatbot_response('Suggest a birthday theme')
                self.assertTrue(payload['service_error'])
                self.assertFalse(payload['should_save'])
                self.assertEqual(payload['text'], QUIZ_UNAVAILABLE)

    def test_legacy_image_error_never_exposes_provider_configuration(self):
        for diagnostic in ('402 credits exhausted', '401 unauthorized key=private', 'timeout'):
            with self.subTest(diagnostic=diagnostic):
                text = services._image_unavailable_reply('balloons', error_message=diagnostic)
                self.assertNotIn('Hugging', text)
                self.assertNotIn('credits', text)
                self.assertIn("We couldn't create the sample image right now.", text)


class QuizAndRequestErrorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='public-error-test', role='customer')
        self.factory = RequestFactory()

    def quiz_request(self, payload):
        request = self.factory.post('/', json.dumps(payload), content_type='application/json')
        request.user = self.user
        return request

    @patch('app.views.public.cache.add', return_value=True)
    @patch('app.views.public.get_chatbot_response')
    def test_quiz_returns_service_failure_as_unavailable_not_recommendation(self, chatbot, add):
        chatbot.return_value = services._chat_response_payload(QUIZ_UNAVAILABLE, service_error=True, should_save=False)
        response = public.theme_quiz_api(self.quiz_request({'event_type': 'Birthday', 'vibe': 'Garden'}))
        self.assertEqual(response.status_code, 502)
        self.assertEqual(json.loads(response.content), {'success': False, 'error': QUIZ_UNAVAILABLE})

    @patch('app.views.public.cache.add', return_value=True)
    @patch('app.views.public.get_chatbot_response', return_value={'text': '**Garden Glow**'})
    def test_quiz_success_still_returns_recommendation(self, chatbot, add):
        response = public.theme_quiz_api(self.quiz_request({'event_type': 'Birthday', 'vibe': 'Garden'}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {'success': True, 'response': '**Garden Glow**'})

    def test_quiz_malformed_selections_have_recovery_message(self):
        response = public.theme_quiz_api(self.quiz_request([]))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)['error'], "We couldn't read your selections. Choose your event type and preferred style again.")

    def test_invalid_ai_request_identity_never_exposes_internal_id_terms(self):
        with self.assertRaises(JobError) as caught:
            create_request(self.user, request_id='not-uuid', message='What colors suit a birthday?')
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(str(caught.exception), "We couldn't send this message. Reopen the chat, check whether it was sent, and try again if needed.")
