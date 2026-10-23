import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from .ai_text import ProviderFailure, provider_failure, text_completion


def provider_error(status, detail='Provider error', retry_after='17'):
    error = RuntimeError(detail)
    error.response = SimpleNamespace(status_code=status, headers={'Retry-After': retry_after})
    return error


@override_settings(HUGGINGFACE_API_KEY='hf_test', HUGGINGFACE_MODEL_ID='primary',
    HUGGINGFACE_TEXT_FALLBACK_MODELS=('fallback',), HUGGINGFACE_TEXT_PROVIDER='auto',
    HUGGINGFACE_TEXT_TIMEOUT=1, AI_TEXT_RESPONSE_TIMEOUT_SECONDS=2)
class TextProviderTests(SimpleTestCase):
    def test_permanent_errors_do_not_offer_retries_or_expose_provider_details(self):
        cases = ((400, 'model_not_supported secret-token', 'model_unavailable'),
            (404, 'Missing model', 'model_unavailable'), (401, 'Bad key', 'provider_auth'),
            (403, 'Forbidden', 'provider_auth'), (402, 'No credits', 'provider_credits'),
            (422, 'Invalid request', 'provider_request'))
        for status, detail, code in cases:
            with self.subTest(status=status):
                failure = provider_failure(provider_error(status, detail))
                self.assertEqual(failure.code, code)
                self.assertFalse(failure.retry)
                self.assertNotIn(detail, failure.text)
                self.assertTrue(failure.payload()['service_error'])

    def test_temporary_failures_have_a_retry_delay(self):
        rate = provider_failure(provider_error(429))
        self.assertTrue(rate.retry)
        self.assertEqual(rate.after, 17)
        self.assertEqual(rate.code, 'provider_busy')
        self.assertEqual(provider_failure(TimeoutError()).code, 'provider_timeout')
        self.assertEqual(provider_failure(provider_error(503)).after, 5)

    def test_unsupported_model_falls_back_before_output(self):
        first, second = Mock(), Mock()
        first.chat_completion.side_effect = provider_error(400, 'model_not_supported')
        second.chat_completion.return_value = iter(['hello', ' world'])
        factory = Mock(side_effect=[first, second])
        output = list(text_completion(factory, model='primary', messages=[], stream=True))
        self.assertEqual(output, ['hello', ' world'])
        self.assertEqual(first.chat_completion.call_args.kwargs['model'], 'primary')
        self.assertEqual(second.chat_completion.call_args.kwargs['model'], 'fallback')
        self.assertEqual(factory.call_args.kwargs['provider'], 'auto')

    def test_all_unsupported_models_fail_without_an_endless_retry(self):
        client = Mock()
        client.chat_completion.side_effect = provider_error(400, 'model_not_supported')
        factory = Mock(return_value=client)
        with self.assertRaises(ProviderFailure) as caught:
            list(text_completion(factory, model='primary', messages=[], stream=True))
        self.assertEqual(factory.call_count, 2)
        self.assertEqual(caught.exception.code, 'model_unavailable')
        self.assertFalse(caught.exception.retry)

    def test_auth_quota_and_timeout_never_start_a_fallback_call(self):
        for error in (provider_error(401), provider_error(402), provider_error(429), TimeoutError()):
            client = Mock()
            client.chat_completion.side_effect = error
            factory = Mock(return_value=client)
            with self.assertRaises(ProviderFailure):
                list(text_completion(factory, model='primary', messages=[], stream=True))
            self.assertEqual(factory.call_count, 1)

    def test_failed_partial_stream_never_switches_models_or_duplicates_output(self):
        def chunks():
            yield 'First sentence.'
            raise provider_error(400, 'model_not_supported')
        client = Mock()
        client.chat_completion.return_value = chunks()
        factory = Mock(return_value=client)
        output = text_completion(factory, model='primary', messages=[], stream=True)
        self.assertEqual(next(output), 'First sentence.')
        with self.assertRaises(ProviderFailure):
            next(output)
        self.assertEqual(factory.call_count, 1)

    def test_deadline_stops_waiting_even_if_transport_has_not_returned(self):
        release, stopped = threading.Event(), threading.Event()
        client = Mock()
        def blocked(**kwargs):
            try:
                release.wait(2)
                return iter(['too late'])
            finally:
                stopped.set()
        client.chat_completion.side_effect = blocked
        factory = Mock(return_value=client)
        start = time.monotonic()
        try:
            with self.assertRaises(ProviderFailure) as caught:
                list(text_completion(factory, model='primary', deadline=start+0.08, messages=[], stream=True))
            self.assertEqual(caught.exception.code, 'provider_timeout')
            self.assertLess(time.monotonic()-start, 1)
            self.assertEqual(factory.call_count, 1)
        finally:
            release.set()
            self.assertTrue(stopped.wait(2))

    def test_capacity_and_expired_deadlines_do_not_launch_more_network_work(self):
        factory = Mock()
        with patch('app.ai_text._slots', threading.BoundedSemaphore(0)), self.assertRaises(ProviderFailure) as caught:
            list(text_completion(factory, model='primary', messages=[], stream=True))
        self.assertEqual(caught.exception.code, 'provider_busy')
        with self.assertRaises(ProviderFailure):
            list(text_completion(factory, model='primary', deadline=time.monotonic()-1, messages=[], stream=True))
        factory.assert_not_called()

    def test_non_streamed_continuation_uses_the_same_bounded_transport(self):
        client = Mock()
        client.chat_completion.return_value = 'Final sentence.'
        self.assertEqual(list(text_completion(Mock(return_value=client), model='primary', messages=[])), ['Final sentence.'])
