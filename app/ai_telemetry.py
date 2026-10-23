"""Usage is recorded only when returned by the provider; costs remain estimates."""
import contextvars
import json
import threading
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

from django.conf import settings

_recorder = contextvars.ContextVar('ai_usage_recorder', default=None)


def usage_recorder():
    return _recorder.get()


def _number(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def usage_values(value):
    usage = getattr(value, 'usage', None)
    if usage is None and isinstance(value, dict):
        usage = value.get('usage')
    def get(name):
        return usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
    prompt = _number(get('prompt_tokens'))
    completion = _number(get('completion_tokens'))
    return {'input_tokens': prompt, 'output_tokens': completion} if prompt is not None and completion is not None else {}


def estimated_cost(call):
    if call.get('input_tokens') is None or call.get('output_tokens') is None:
        return None
    try:
        rates = json.loads(settings.AI_TEXT_PRICING_JSON).get(call['model'], {})
        incoming, outgoing = Decimal(str(rates['input_per_million'])), Decimal(str(rates['output_per_million']))
        if min(incoming, outgoing) < 0 or not incoming.is_finite() or not outgoing.is_finite():
            return None
        return str((incoming * call['input_tokens'] + outgoing * call['output_tokens']) / Decimal(1000000))
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
        return None


@contextmanager
def collect_usage():
    calls, lock = [], threading.Lock()
    def record(call):
        with lock:
            if len(calls) < 16:
                calls.append({**call, 'estimated_usd': estimated_cost(call)})
    token = _recorder.set(record)
    try:
        yield calls
    finally:
        _recorder.reset(token)
