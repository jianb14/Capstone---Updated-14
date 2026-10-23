"""Bounded text inference with safe model fallback and actionable error categories."""
import logging
import queue
import threading
import time

from django.conf import settings
from .ai_telemetry import usage_recorder, usage_values

logger = logging.getLogger(__name__)
# A broken transport cannot accumulate unlimited abandoned inference threads.
_slots = threading.BoundedSemaphore(2)


class ProviderFailure(Exception):
    def __init__(self, code, text, *, retry=False, after=0):
        super().__init__(text)
        self.code, self.text, self.retry, self.after = code, text, retry, after

    def payload(self):
        return {'text': self.text, 'service_error': True, 'error_code': self.code,
            'retry_available': self.retry, 'retry_after': self.after}

    @classmethod
    def from_payload(cls, data):
        return cls(data.get('error_code') or 'provider_unavailable', data['text'],
            retry=bool(data.get('retry_available', True)), after=int(data.get('retry_after') or 5))


def provider_failure(error):
    if isinstance(error, ProviderFailure):
        return error
    response = getattr(error, 'response', None)
    status = getattr(response, 'status_code', None)
    detail = str(error).lower()
    # Log categories only; never send provider responses, URLs or tokens to customers.
    if ('model_not_supported' in detail or 'not supported by any provider' in detail or status == 404 or
            ('model' in detail and ('not supported' in detail or 'not available' in detail))):
        return ProviderFailure('model_unavailable', 'The assistant is unavailable right now. Please contact our team for help.')
    if status in (401, 403) or 'unauthorized' in detail:
        return ProviderFailure('provider_auth', 'The assistant is unavailable right now. Please contact our team for help.')
    if status == 402 or 'depleted your monthly included credits' in detail:
        return ProviderFailure('provider_credits', 'The assistant is unavailable right now. Please contact our team for help.')
    if status in (400, 422):
        return ProviderFailure('provider_request', 'The assistant could not process this request. Please contact our team for help.')
    if status == 429:
        try:
            after = max(5, min(300, int((getattr(response, 'headers', None) or {}).get('Retry-After', 30))))
        except (ValueError, TypeError):
            after = 30
        return ProviderFailure('provider_busy', 'The assistant is busy. Please try again shortly.', retry=True, after=after)
    if status in (408, 504) or 'timeout' in type(error).__name__.lower() or 'timed out' in detail:
        return ProviderFailure('provider_timeout', 'The assistant took too long to respond. Please try again shortly.', retry=True, after=5)
    return ProviderFailure('provider_unavailable', 'The assistant could not connect right now. Please try again shortly.', retry=True, after=5)


def text_completion(client_factory, *, model, deadline=None, purpose='answer', **arguments):
    """Yield chunks (or one non-streamed result), stopping at a wall-clock deadline.

    Model fallback is allowed only for an unsupported model before the first chunk.
    Timeouts, quota failures and partial streams never trigger another paid call.
    """
    if deadline is None:
        deadline = time.monotonic() + settings.AI_TEXT_RESPONSE_TIMEOUT_SECONDS
    if deadline <= time.monotonic():
        raise provider_failure(TimeoutError())
    slots = _slots
    if not slots.acquire(blocking=False):
        raise ProviderFailure('provider_busy', 'The assistant is busy. Please try again shortly.', retry=True, after=10)
    events = queue.Queue(maxsize=32)
    cancelled = threading.Event()
    recorder = usage_recorder()

    def publish(kind, value):
        while not cancelled.is_set():
            try:
                events.put((kind, value), timeout=0.1)
                return
            except queue.Full:
                continue

    def produce():
        try:
            models = list(dict.fromkeys([model, *settings.HUGGINGFACE_TEXT_FALLBACK_MODELS]))
            for index, candidate in enumerate(models):
                client, stream, emitted = None, None, False
                began, usage, error_code = time.monotonic(), {}, ''
                terminal, retry_model = ('done', None), False
                try:
                    if cancelled.is_set() or time.monotonic() >= deadline:
                        raise TimeoutError()
                    client = client_factory(token=settings.HUGGINGFACE_API_KEY,
                        provider=settings.HUGGINGFACE_TEXT_PROVIDER,
                        timeout=max(0.1, min(settings.HUGGINGFACE_TEXT_TIMEOUT, deadline - time.monotonic())))
                    stream = client.chat_completion(model=candidate, **arguments)
                    if arguments.get('stream'):
                        for chunk in stream:
                            if cancelled.is_set():
                                return
                            emitted = True
                            usage.update(usage_values(chunk))
                            publish('chunk', chunk)
                    else:
                        usage.update(usage_values(stream))
                        publish('chunk', stream)
                except Exception as error:
                    failure = provider_failure(error)
                    error_code = failure.code
                    logger.warning('AI text provider failure: category=%s model=%s', failure.code, candidate)
                    if not emitted and failure.code == 'model_unavailable' and index + 1 < len(models):
                        retry_model = True
                    terminal = ('error', failure)
                finally:
                    if recorder:
                        recorder({'model': candidate, 'provider': settings.HUGGINGFACE_TEXT_PROVIDER,
                            'purpose': purpose, 'seconds': round(time.monotonic()-began, 3),
                            'error_code': error_code, **usage})
                    for resource in (stream, client):
                        close = getattr(resource, 'close', None)
                        if callable(close):
                            try:
                                close()
                            except Exception:
                                pass
                # Usage is finalized before the consumer can mark the job complete.
                if retry_model:
                    continue
                publish(*terminal)
                return
        finally:
            slots.release()

    threading.Thread(target=produce, name='ai-text-inference', daemon=True).start()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise provider_failure(TimeoutError())
            try:
                kind, value = events.get(timeout=remaining)
            except queue.Empty:
                raise provider_failure(TimeoutError()) from None
            if kind == 'error':
                raise value
            if kind == 'done':
                return
            yield value
    finally:
        cancelled.set()
