import io
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .ai_intent import is_advice_question, is_revision, requests_information, wants_generation
from .ai_jobs import claim_request, complete_request, create_request, execute_request, expire_interrupted_requests
from .ai_worker import run_once
from .models import AiGeneratedImage, AiRequest, ChatMessage, ChatModerationState, ChatSession, Package, RequestRateBucket, User
from .request_protection import bucket_key


def image_bytes(format='PNG'):
    buffer = io.BytesIO()
    Image.new('RGB', (16, 16), 'skyblue').save(buffer, format=format)
    return buffer.getvalue()


def upload():
    return SimpleUploadedFile('inspiration.png', image_bytes(), content_type='image/png')


LIMITS = {**settings.REQUEST_RATE_LIMITS, 'ai_chat_cooldown': (1, 0), 'ai_image_cooldown': (1, 0)}


class IntentTests(TestCase):
    def test_mixed_information_and_visual_requests(self):
        for text in (
            'ano ano yung mga package niyo at pwede ko bang makita yung example ng backdrop design ninyo?',
            'What are your packages and can I see an example backdrop design?',
            'List your packages. Show me a sample image.',
            'How much are the packages? Also generate a birthday backdrop.',
            'Compare packages and show example designs',
            'What are your packages? Can you give me a sample backdrop design?',
            'List packages and include a sample image',
        ):
            with self.subTest(text=text):
                self.assertTrue(wants_generation(text))
                self.assertTrue(requests_information(text))
                self.assertFalse(is_advice_question(text))

    def test_information_and_generation_instructions_do_not_spend_image_credits(self):
        for text in ('What are your packages?', 'Do packages include backdrop designs?',
                     'What is an image generator?', 'How do I generate a backdrop and save it?',
                     'List your packages and show an image, but no images for now.',
                     'Can you give me an image prompt?', 'Create a backdrop prompt for a birthday.',
                     "Don't generate an image; what packages are available?"):
            self.assertFalse(wants_generation(text), text)
        self.assertFalse(requests_information('Generate a backdrop for Package 1-A'))
        self.assertTrue(wants_generation('Generate an image using this backdrop prompt: pink balloons'))

    def test_advice_questions_never_trigger_generation(self):
        for text in ('What colors suit a wedding?', 'Anong theme ang bagay sa binyag?',
                     'How much does this backdrop cost?', 'Which design works in a small space?',
                     'Can you explain this design?', "Don't generate an image. Suggest colors instead."):
            with self.subTest(text=text):
                self.assertTrue(is_advice_question(text))
                self.assertFalse(wants_generation(text, explicit=True, has_reference=True))
        for text in ('How do I generate a design?', 'How can I create an image?', 'Paano mag-generate ng image?',
                     'Can you suggest colors for a wedding?', 'Text only, show some design ideas'):
            self.assertTrue(is_advice_question(text), text)
            self.assertFalse(wants_generation(text, has_reference=True), text)

    def test_direct_generation_and_revisions_are_recognized(self):
        for text in ('Generate a butterfly birthday backdrop', 'Can you create a wedding image?',
                     'Pakita ng birthday design', 'Birthday backdrop in pink and gold'):
            with self.subTest(text=text):
                self.assertTrue(wants_generation(text))
        self.assertTrue(is_revision('Change only the balloons to blue'))
        self.assertTrue(wants_generation('Change only the balloons to blue', has_reference=True))


@override_settings(REQUEST_RATE_LIMITS=LIMITS, HUGGINGFACE_API_KEY='hf_test', AI_WORKER_AUTOSTART=False)
class AiRequestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='ai-customer', role='customer')
        self.other = User.objects.create_user(username='ai-other', role='customer')
        self.admin = User.objects.create_user(username='ai-admin', role='admin')
        self.client.force_login(self.user)
        self.provider_patch = patch('app.services.InferenceClient')
        self.provider = self.provider_patch.start()
        self.addCleanup(self.provider_patch.stop)
        self.provider.return_value.text_to_image.return_value = image_bytes()
        self.provider.return_value.image_to_image.return_value = image_bytes()

    def post(self, *, path='ai_request_create', **fields):
        fields.setdefault('request_id', str(uuid.uuid4()))
        fields.setdefault('message', 'Generate a birthday backdrop with blue and silver balloons')
        if 'image' in fields:
            return self.client.post(reverse(path), fields)
        return self.client.post(reverse(path), json.dumps(fields), content_type='application/json')

    def process(self, response):
        self.assertEqual(response.status_code, 202, response.content)
        self.assertTrue(run_once(heartbeat=False))
        return AiRequest.objects.get(pk=response.json()['id'])

    def generated(self):
        job = self.process(self.post())
        self.assertEqual(job.state, 'succeeded', job.result)
        return job

    def test_package_catalog_replies_immediately_with_current_complete_inclusions(self):
        package = Package.objects.create(name='Package 1-A', price='4799.00', service_charge='150.00',
            features='\n'.join(f'Inclusion {n}' for n in range(1, 12)), notes='Setup included.')
        Package.objects.create(name='Hidden package', price='99', features='Hidden', is_active=False)
        with override_settings(HUGGINGFACE_API_KEY=''):
            job = self.process(self.post(message='Our packages'))
        self.assertEqual(job.state, 'succeeded', job.result)
        self.assertIn('PHP 4,799.00', job.result['response'])
        self.assertIn('Inclusion 11', job.result['response'])
        self.assertIn('Service charge: PHP 150.00', job.result['response'])
        self.assertNotIn('Hidden package', job.result['response'])
        self.provider.assert_not_called()
        package.price = '5000.00'
        package.save(update_fields=['price'])
        changed = self.process(self.post(message='Show me your packages'))
        self.assertIn('PHP 5,000.00', changed.result['response'])
        self.assertNotIn('4,799', changed.result['response'])

    def test_empty_package_catalog_is_honest_without_calling_a_provider(self):
        job = self.process(self.post(message='Our packages'))
        self.assertEqual(job.state, 'succeeded')
        self.assertIn('No packages are currently listed', job.result['response'])
        self.provider.assert_not_called()

    def test_unsupported_models_save_a_specific_error_without_a_retry_loop(self):
        from .test_ai_text import provider_error
        self.provider.return_value.chat_completion.side_effect = provider_error(400, 'model_not_supported private-provider-detail')
        job = self.process(self.post(message='What colors suit a wedding?'))
        self.assertEqual(job.state, 'failed')
        self.assertEqual(job.error_code, 'model_unavailable')
        self.assertFalse(job.result['retry_available'])
        self.assertNotIn('private-provider-detail', job.result['response'])
        self.assertEqual(self.post(message='', retry_of=str(job.pk)).status_code, 400)
        self.assertEqual(self.provider.return_value.chat_completion.call_count, 2)
        self.provider.return_value.text_to_image.assert_not_called()

    def test_transient_provider_limit_preserves_the_retry_delay(self):
        from .test_ai_text import provider_error
        self.provider.return_value.chat_completion.side_effect = provider_error(429, retry_after='17')
        job = self.process(self.post(message='What colors suit a wedding?'))
        self.assertEqual(job.error_code, 'provider_busy')
        self.assertEqual(job.result['retry_after'], 17)
        self.assertTrue(job.result['retry_available'])
        self.assertEqual(self.post(message='', retry_of=str(job.pk)).status_code, 429)
        self.assertEqual(self.provider.return_value.chat_completion.call_count, 1)

    def test_text_timeout_expires_a_healthy_lease_and_fences_late_completion(self):
        self.post(message='What colors suit a wedding?')
        job_id, token = claim_request()
        AiRequest.objects.filter(pk=job_id).update(started_at=timezone.now()-timedelta(seconds=61),
            lease_expires_at=timezone.now()+timedelta(seconds=60))
        expire_interrupted_requests()
        job = AiRequest.objects.get(pk=job_id)
        self.assertEqual(job.state, 'failed')
        self.assertEqual(job.error_code, 'provider_timeout')
        self.assertEqual(job.result['retry_after'], 5)
        self.assertFalse(complete_request(job_id, token, {'text': 'Late reply'}))
        self.assertEqual(ChatMessage.objects.filter(session_id=job.session_id).count(), 2)

    def test_generation_keeps_its_own_deadline_but_mixed_text_wait_is_bounded(self):
        self.post()
        job_id, token = claim_request()
        AiRequest.objects.filter(pk=job_id).update(started_at=timezone.now()-timedelta(seconds=61),
            lease_expires_at=timezone.now()+timedelta(seconds=60), stage='generating')
        expire_interrupted_requests()
        self.assertEqual(AiRequest.objects.get(pk=job_id).state, 'running')
        AiRequest.objects.filter(pk=job_id).update(stage='replying',
            provider_started_at=timezone.now()-timedelta(seconds=61))
        expire_interrupted_requests()
        self.assertEqual(AiRequest.objects.get(pk=job_id).error_code, 'provider_timeout')

    def test_duplicate_submission_and_recovery_spend_one_provider_call(self):
        request_id = str(uuid.uuid4())
        first = self.post(request_id=request_id)
        repeated = self.post(request_id=request_id)
        self.assertEqual(repeated.status_code, 202)
        self.assertEqual(repeated['Idempotent-Replayed'], 'true')
        self.assertEqual(AiRequest.objects.count(), 1)
        self.assertEqual(ChatMessage.objects.count(), 1)
        job = self.process(first)
        recovered = self.client.get(reverse('ai_request_status', args=[job.pk]))
        self.assertEqual(recovered.json()['state'], 'succeeded')
        self.assertEqual(recovered['Cache-Control'], 'no-store')
        self.assertEqual(self.post(request_id=request_id).json()['state'], 'succeeded')
        self.assertFalse(run_once(heartbeat=False))
        self.assertEqual(ChatMessage.objects.count(), 2)
        self.provider.return_value.text_to_image.assert_called_once()

    def test_packages_and_sample_use_one_text_reply_and_one_owned_image(self):
        message = 'ano ano yung mga package niyo at pwede ko bang makita yung example ng backdrop design ninyo?'
        details = '1. Package 1-A: PHP 4,799.\n   - One panel\n\n2. Package 1-B: PHP 5,799.'
        full = details + '\n[PROMPT]White and gold birthday balloon backdrop with one arch panel.[/PROMPT]'
        self.provider.return_value.chat_completion.return_value = [SimpleNamespace(choices=[
            SimpleNamespace(delta=SimpleNamespace(content=full), finish_reason='stop')])]
        request_id = str(uuid.uuid4())
        job = self.process(self.post(request_id=request_id, message=message))
        self.assertEqual(job.kind, 'generate')
        self.assertEqual(job.state, 'succeeded', job.result)
        self.assertIn('Package 1-A', job.result['response'])
        self.assertIn('Package 1-B', job.result['response'])
        self.assertIn('<img ', job.result['response'])
        self.assertIn('Sample AI backdrop concept', job.result['response'])
        self.assertNotIn('[PROMPT]', job.result['response'])
        self.assertEqual(job.images.count(), 1)
        self.assertEqual(job.assistant_message.message, job.result['response'])
        prompt = self.provider.return_value.text_to_image.call_args.kwargs['prompt']
        self.assertIn('gold', prompt.lower())
        self.assertNotIn('4,799', prompt)
        self.assertIn('separate image operation is pending',
            self.provider.return_value.chat_completion.call_args.kwargs['messages'][0]['content'])
        self.assertEqual(self.post(request_id=request_id, message=message).json()['state'], 'succeeded')
        self.provider.return_value.text_to_image.assert_called_once()
        self.assertEqual(self.provider.return_value.chat_completion.call_count, 1)

    def test_mixed_reply_keeps_package_details_when_image_fails(self):
        events = [{'type': 'final', 'data': {'text': 'Package 1-A: PHP 4,799.',
            'image_prompt': 'White and gold balloon backdrop.'}}]
        self.provider.return_value.text_to_image.side_effect = RuntimeError('Provider unavailable')
        with patch('app.services.stream_chatbot_events', return_value=iter(events)):
            job = self.process(self.post(message='List your packages and show me a sample backdrop image'))
        self.assertEqual(job.state, 'failed')
        self.assertIn('Package 1-A', job.result['response'])
        self.assertIn('could not generate the sample image', job.result['response'])
        self.assertNotIn('<img ', job.result['response'])
        self.assertTrue(job.result['retry_available'])
        self.assertEqual(job.images.count(), 0)

    def test_package_question_with_sample_does_not_edit_previous_image(self):
        original = self.generated()
        events = [{'type': 'final', 'data': {'text': 'Available package details.'}}]
        with patch('app.services.stream_chatbot_events', return_value=iter(events)):
            job = self.process(self.post(session_id=original.session_id,
                message='List your packages and include a sample image'))
        self.assertEqual(job.kind, 'generate')
        self.assertEqual(job.state, 'succeeded', job.result)
        self.assertIsNone(job.images.get().parent_id)
        self.provider.return_value.image_to_image.assert_not_called()

    def test_mixed_request_obeys_image_budget_and_still_returns_information(self):
        self.generated()
        events = [{'type': 'final', 'data': {'text': 'Package details from the catalog.'}}]
        with override_settings(REQUEST_RATE_LIMITS={**LIMITS, 'ai_image_daily': (1, 86400)}), patch(
                'app.services.stream_chatbot_events', return_value=iter(events)):
            job = self.process(self.post(message='What are your packages and show me a sample image'))
        self.assertEqual(job.state, 'failed')
        self.assertEqual(job.error_code, 'rate_limited')
        self.assertIn('Package details from the catalog.', job.result['response'])
        self.assertEqual(self.provider.return_value.text_to_image.call_count, 1)

    def test_id_reuse_with_changed_payload_is_rejected(self):
        request_id = str(uuid.uuid4())
        self.post(request_id=request_id)
        response = self.post(request_id=request_id, message='Generate a wedding backdrop')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(AiRequest.objects.count(), 1)

    def test_one_active_request_across_all_ai_routes(self):
        first = self.post()
        for path in ('chat_api', 'chat_api_stream', 'chat_analyze_image', 'ai_request_create'):
            with self.subTest(path=path):
                fields = {'image': upload()} if path == 'chat_analyze_image' else {}
                response = self.post(path=path, **fields)
                self.assertEqual(response.status_code, 409, response.content)
                self.assertEqual(response.json()['active_request']['id'], first.json()['id'])
        self.provider.assert_not_called()

    def test_photo_and_analysis_are_saved_to_history(self):
        with patch('app.services.analyze_inspiration_image', return_value='Blue balloons. [PROMPT]blue balloon backdrop[/PROMPT]'):
            job = self.process(self.post(image=upload()))
        self.assertEqual(job.state, 'succeeded', job.result)
        self.assertTrue(job.user_message.image)
        history = self.client.get(reverse('chat_history'), {'session_id': job.session_id}).json()['messages']
        self.assertEqual(len(history), 2)
        self.assertTrue(history[0]['image_url'])
        self.assertEqual(len(history[1]['ai_images']), 1)
        self.provider.return_value.image_to_image.assert_called_once()

    def test_photo_advice_does_not_generate_an_image(self):
        with patch('app.services.analyze_inspiration_image', return_value='The photo uses blue and white.') as analyze:
            job = self.process(self.post(message='What colors are in this photo?', image=upload()))
        self.assertEqual(job.kind, 'photo_advice')
        self.assertFalse(analyze.call_args.kwargs['generate'])
        self.provider.return_value.image_to_image.assert_not_called()
        self.provider.return_value.text_to_image.assert_not_called()
        self.assertFalse(AiGeneratedImage.objects.exists())

    def test_advice_never_spends_image_quota_even_if_model_emits_prompt(self):
        events = [{'type': 'delta', 'text': 'Try ivory and gold.'},
                  {'type': 'final', 'data': {'text': 'Try ivory and gold.'}}]
        with patch('app.services.stream_chatbot_events', return_value=iter(events)) as stream:
            job = self.process(self.post(message='What colors suit a wedding?'))
        self.assertEqual(job.kind, 'advice')
        self.assertFalse(stream.call_args.kwargs['allow_images'])
        self.assertFalse(RequestRateBucket.objects.filter(pk=bucket_key('ai_image_daily', f'user:{self.user.pk}')).exists())
        self.provider.return_value.text_to_image.assert_not_called()

    def test_revision_reads_owned_previous_image_and_preserves_parent(self):
        original = self.generated()
        image = original.images.get()
        response = self.post(session_id=original.session_id, message='Change only the balloons to pink', reference_id=str(image.pk))
        revised = self.process(response)
        self.assertEqual(revised.kind, 'revise')
        self.assertEqual(revised.images.get().parent_id, image.pk)
        arguments = self.provider.return_value.image_to_image.call_args
        self.assertEqual(arguments.args[0], image_bytes())
        self.assertIn('Preserve its composition', arguments.kwargs['prompt'])
        self.assertEqual(self.provider.return_value.text_to_image.call_count, 1)

    def test_implicit_revision_and_another_version_use_current_chat(self):
        original = self.generated()
        revised = self.process(self.post(session_id=original.session_id, message='Remove the flowers'))
        self.assertEqual(revised.kind, 'revise')
        variation = self.process(self.post(session_id=original.session_id, message='Another version'))
        self.assertEqual(variation.kind, 'generate')

    def test_selected_edit_accepts_short_color_instructions(self):
        original = self.generated()
        revised = self.process(self.post(session_id=original.session_id, intent='revise',
            reference_id=str(original.images.get().pk), message='Pink and gold'))
        self.assertEqual(revised.kind, 'revise')
        self.assertEqual(revised.images.get().parent_id, original.images.get().pk)
        self.assertEqual(self.provider.return_value.text_to_image.call_count, 1)

    def test_failed_edit_never_falls_back_to_a_new_layout(self):
        original = self.generated()
        self.provider.return_value.image_to_image.side_effect = RuntimeError('Editing provider unavailable')
        revised = self.process(self.post(session_id=original.session_id, message='Change only the balloons to pink'))
        self.assertEqual(revised.state, 'failed')
        self.assertIn('original image', revised.result['response'])
        self.assertEqual(original.images.count(), 1)
        self.assertEqual(self.provider.return_value.text_to_image.call_count, 1)

    def test_daily_image_budget_is_shared_and_blocks_provider(self):
        limits = {**LIMITS, 'ai_image_daily': (1, 86400)}
        with override_settings(REQUEST_RATE_LIMITS=limits):
            self.generated()
            cache.clear()
            second = self.process(self.post())
        self.assertEqual(second.state, 'failed')
        self.assertEqual(second.error_code, 'rate_limited')
        self.assertGreater(second.result['retry_after'], 0)
        self.assertEqual(self.provider.return_value.text_to_image.call_count, 1)

    def test_multiple_options_reserve_each_image(self):
        with patch('app.services._detect_variation_count', return_value=3):
            job = self.generated()
        self.assertEqual(job.images.count(), 3)
        self.assertEqual(RequestRateBucket.objects.get(pk=bucket_key('ai_image_daily', f'user:{self.user.pk}')).count, 3)

    def test_banned_photo_request_never_reaches_a_provider_or_stores_photo(self):
        ChatModerationState.objects.create(user=self.user, banned_until=timezone.now()+timedelta(minutes=5))
        response = self.post(image=upload())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['result']['is_banned'])
        self.assertFalse(AiRequest.objects.get().user_message.image)
        self.assertFalse(run_once(heartbeat=False))
        self.provider.assert_not_called()

    def test_duplicate_warning_adds_no_second_strike(self):
        request_id = str(uuid.uuid4())
        self.post(request_id=request_id, message='bobo')
        self.post(request_id=request_id, message='bobo')
        self.assertEqual(self.user.chat_moderation_events.count(), 1)

    def test_only_owner_can_recover_or_reference_an_image(self):
        job = self.generated()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('ai_request_status', args=[job.pk])).status_code, 404)
        other_session = ChatSession.objects.create(user=self.other)
        response = self.post(session_id=other_session.pk, reference_id=str(job.images.get().pk))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(AiRequest.objects.filter(user=self.other).exists())

    def test_invalid_photo_is_rejected_without_creating_work(self):
        response = self.post(image=SimpleUploadedFile('bad.png', b'not an image', content_type='image/png'))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AiRequest.objects.exists())
        self.provider.assert_not_called()

    def test_interrupted_work_is_not_requeued_or_executed_twice(self):
        response = self.post()
        job_id, token = claim_request()
        AiRequest.objects.filter(pk=job_id).update(lease_expires_at=timezone.now()-timedelta(seconds=1))
        expire_interrupted_requests()
        job = AiRequest.objects.get(pk=job_id)
        self.assertEqual(job.state, 'failed')
        self.assertEqual(job.error_code, 'interrupted')
        execute_request(job_id, token)
        self.assertFalse(complete_request(job_id, token, {'text': 'late result'}))
        self.provider.assert_not_called()

    def test_explicit_retry_reuses_saved_photo_and_input_bubble(self):
        self.provider.return_value.image_to_image.side_effect = RuntimeError('Unavailable')
        with patch('app.services.analyze_inspiration_image', return_value='Photo. [PROMPT]blue balloons[/PROMPT]'):
            failed = self.process(self.post(image=upload()))
            self.provider.return_value.image_to_image.side_effect = None
            self.assertEqual(self.post(message='', retry_of=str(failed.pk)).status_code, 429)
            failed.result.update(retry_at=timezone.now().timestamp()-1, retry_after=0)
            failed.save(update_fields=['result'])
            retried = self.process(self.post(message='', retry_of=str(failed.pk)))
        self.assertEqual(retried.state, 'succeeded', retried.result)
        self.assertEqual(retried.user_message_id, failed.user_message_id)
        self.assertEqual(ChatMessage.objects.filter(sender=self.user).count(), 1)

    def test_job_claim_and_terminal_state_are_single_use(self):
        response = self.post()
        job_id, token = claim_request()
        self.assertIsNone(claim_request())
        execute_request(job_id, token)
        execute_request(job_id, token)
        self.assertEqual(self.provider.return_value.text_to_image.call_count, 1)

    def test_partial_multiple_options_keep_already_generated_images(self):
        self.provider.return_value.text_to_image.side_effect = [image_bytes(), RuntimeError('Temporary failure')]
        with patch('app.services._detect_variation_count', return_value=3):
            job = self.process(self.post())
        self.assertEqual(job.state, 'failed')
        self.assertEqual(job.images.count(), 1)
        self.assertIn('<img ', job.result['response'])
        self.assertFalse(job.result['retry_available'])

    def test_fresh_lease_cannot_be_expired_by_a_stale_watchdog(self):
        self.post()
        job_id, token = claim_request()
        self.assertFalse(complete_request(job_id, token, {'text': 'Interrupted'},
            failed=True, interrupted_only=True))
        self.assertEqual(AiRequest.objects.get().state, 'running')

    def test_feedback_still_records_for_a_generated_image(self):
        job = self.generated()
        image = job.images.get()
        response = self.client.post(reverse('chat_image_feedback'),
            json.dumps({'image_url': image.image.url, 'rating': 1}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.user.ai_image_feedback.get().rating, 1)

    def test_cloud_storage_image_can_be_saved_and_feedback_is_owned(self):
        image = self.generated().images.get()
        url = 'https://res.cloudinary.com/demo/image/upload/v1/media/' + image.image.name
        with patch('app.ai_images.default_storage.url', return_value=url):
            response = self.client.post(reverse('chat_image_feedback'),
                json.dumps({'image_url': url, 'rating': 1}), content_type='application/json')
            self.assertEqual(response.status_code, 200, response.content)
            response = self.client.post(reverse('chat_save_design'),
                json.dumps({'image_url': url}), content_type='application/json')
            self.assertEqual(response.status_code, 200, response.content)
            self.client.force_login(self.other)
            response = self.client.post(reverse('chat_image_feedback'),
                json.dumps({'image_url': url, 'rating': 1}), content_type='application/json')
            self.assertEqual(response.status_code, 400)

    def test_save_rejects_a_path_outside_generated_images(self):
        with patch('app.views.chat.default_storage.open') as opened:
            response = self.client.post(reverse('chat_save_design'),
                json.dumps({'image_url': '/media/../.env'}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        opened.assert_not_called()


@override_settings(REQUEST_RATE_LIMITS=LIMITS, AI_WORKER_AUTOSTART=False)
class AiConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_parallel_identical_posts_create_one_input_and_reserve_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections, connections
        User.objects.create_user(username='ai-concurrent-admin', role='admin')
        user = User.objects.create_user(username='ai-concurrent-customer', role='customer')
        request_id = uuid.uuid4()
        gate = Barrier(4)

        def submit(_):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                job, created = create_request(user, request_id=request_id, message='Generate a birthday backdrop')
                return job.pk, created
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(submit, range(4)))
        self.assertEqual({job_id for job_id, _ in results}, {request_id})
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(ChatMessage.objects.count(), 1)
        self.assertEqual(RequestRateBucket.objects.get(pk=bucket_key('ai_chat', f'user:{user.pk}')).count, 1)

    @skipUnlessDBFeature('has_select_for_update_skip_locked')
    def test_parallel_workers_claim_each_request_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections, connections
        User.objects.create_user(username='ai-claim-admin', role='admin')
        for index in range(2):
            user = User.objects.create_user(username=f'ai-claim-{index}', role='customer')
            create_request(user, request_id=uuid.uuid4(), message='Generate a wedding backdrop')
        gate = Barrier(4)

        def claim(_):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                return claim_request()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = [claim for claim in pool.map(claim, range(4)) if claim]
        self.assertEqual(len(claims), 2)
        self.assertEqual(len({job_id for job_id, _ in claims}), 2)
