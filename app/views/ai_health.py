"""Read-only AI operations report. Never render customer prompts or replies."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from math import ceil
from statistics import mean

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import CharField, Count, Q
from django.db.models.functions import Cast, TruncDate
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_GET

from .common import _is_admin_user
from ..models import AiRequest


SAMPLE_LIMIT = 500
STATES = dict(AiRequest._meta.get_field('state').choices)
KINDS = {
    'advice': 'Chat advice', 'generate': 'Image generation', 'revise': 'Design revision',
    'photo_advice': 'Photo advice', 'photo_edit': 'Photo edit', 'photo_inspire': 'Photo inspiration',
}
ERROR_LABELS = {
    'model_unavailable': 'Model unavailable', 'provider_auth': 'Provider authorization',
    'provider_credits': 'Provider credits', 'provider_request': 'Provider request rejected',
    'provider_config': 'Provider configuration', 'provider_timeout': 'Provider timeout',
    'rate_limited': 'Rate limit', 'interrupted': 'Interrupted request',
}


def _token_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _quality(metrics):
    value = metrics.get('quality') if isinstance(metrics, dict) else None
    return value if isinstance(value, dict) else {}


@login_required
@require_GET
def ai_health(request):
    if not _is_admin_user(request.user):
        return HttpResponseForbidden('Admin access required')
    days_raw = request.GET.get('days', '7')
    days = int(days_raw) if days_raw in ('1', '7', '30') else 7
    state = request.GET.get('state', '')
    if state not in STATES:
        state = ''
    query = request.GET.get('q', '').strip()[:80]
    per_page = 4 if request.GET.get('per_page') == '4' else 8
    now = timezone.now()
    start = now - timedelta(days=days)
    base = AiRequest.objects.filter(created_at__gte=start, created_at__lte=now)
    counts = dict(base.values('state').annotate(n=Count('id')).values_list('state', 'n'))
    total = sum(counts.values())
    success, failed = counts.get('succeeded', 0), counts.get('failed', 0)
    sample = list(base.order_by('-created_at', '-id').values(
        'metrics', 'started_at', 'finished_at', 'state')[:SAMPLE_LIMIT])
    durations = sorted(
        (row['finished_at'] - row['started_at']).total_seconds()
        for row in sample
        if row['state'] in ('succeeded', 'failed') and row['finished_at'] and row['started_at']
        and start <= row['started_at'] <= row['finished_at'] <= now
    )
    known_in = known_out = known_calls = calls_count = priced = repaired = quality_failed = checked = 0
    estimate = Decimal(0)
    for row in sample:
        metrics = row['metrics'] if isinstance(row['metrics'], dict) else {}
        quality = _quality(metrics)
        checked += quality.get('checked') is True
        repaired += isinstance(quality.get('repairs'), int) and quality['repairs'] > 0
        quality_failed += quality.get('passed') is False
        calls = metrics.get('calls', [])
        for call in calls if isinstance(calls, list) else []:
            if not isinstance(call, dict):
                continue
            calls_count += 1
            if _token_count(call.get('input_tokens')) and _token_count(call.get('output_tokens')):
                known_calls += 1
                known_in += call['input_tokens']
                known_out += call['output_tokens']
                try:
                    cost = Decimal(str(call.get('estimated_usd')))
                except (InvalidOperation, ValueError):
                    continue
                if cost.is_finite() and cost >= 0:
                    estimate += cost
                    priced += 1

    errors = list(base.filter(state='failed').exclude(error_code='').values('error_code')
                  .annotate(n=Count('id')).order_by('-n', 'error_code'))
    for error in errors:
        error['label'] = ERROR_LABELS.get(error['error_code'], error['error_code'].replace('_', ' ').capitalize())
    unknown_failures = base.filter(state='failed', error_code='').count()
    if unknown_failures:
        errors.append({'label': 'Unspecified failure', 'error_code': 'not_recorded', 'n': unknown_failures})
    permanent = {'model_unavailable', 'provider_auth', 'provider_credits', 'provider_request', 'provider_config'}
    alerts = []
    if any(row['error_code'] in permanent for row in errors):
        alerts.append('Provider or account errors were recorded. Check the error categories and your provider configuration.')
    if failed >= 3 and failed / max(success + failed, 1) >= .1:
        alerts.append('At least 10% of finished requests failed. Review recent errors and provider timeouts.')
    if base.filter(state='queued', created_at__lt=now - timedelta(seconds=60)).exists():
        alerts.append('Some requests have been queued for over a minute. Check that the AI worker is running.')

    daily_counts = {}
    for row in base.annotate(day=TruncDate('created_at')).values('day', 'state').annotate(n=Count('id')):
        daily_counts.setdefault(row['day'], {})[row['state']] = row['n']
    daily, day, end_day = [], timezone.localdate(start), timezone.localdate(now)
    while day <= end_day:
        values = daily_counts.get(day, {})
        daily.append({'day': day, 'n': sum(values.values()), 'succeeded': values.get('succeeded', 0),
                      'failed': values.get('failed', 0), 'active': values.get('queued', 0) + values.get('running', 0)})
        day += timedelta(days=1)
    peak = max((row['n'] for row in daily), default=0) or 1
    for row in daily:
        row['height'] = round(row['n'] / peak * 100, 2)
        row['success_height'] = round(row['succeeded'] / max(row['n'], 1) * 100, 2)
        row['failed_height'] = round(row['failed'] / max(row['n'], 1) * 100, 2)
        row['active_height'] = round(row['active'] / max(row['n'], 1) * 100, 2)
    for index, row in enumerate(daily):
        row['show_label'] = index % max(1, ceil(len(daily) / 6)) == 0 or index == len(daily) - 1

    requests = base
    if state:
        requests = requests.filter(state=state)
    if query:
        requests = requests.annotate(request_key=Cast('id', CharField())).filter(
            Q(request_key__icontains=query) | Q(error_code__icontains=query) | Q(kind__icontains=query)
            | Q(kind__in=[kind for kind, label in KINDS.items() if query.lower() in label.lower()]))
    page = Paginator(requests.order_by('-created_at', '-id').values(
        'id', 'created_at', 'kind', 'state', 'error_code', 'metrics'), per_page).get_page(request.GET.get('page'))
    recent = []
    for row in page:
        quality = _quality(row.pop('metrics'))
        row.update(kind_label=KINDS.get(row['kind'], 'Other action'), state_label=STATES.get(row['state'], row['state']),
                   quality_label=('Clarification fallback' if quality.get('passed') is False else
                                  'Repair attempted' if isinstance(quality.get('repairs'), int) and quality['repairs'] > 0 else
                                  'Checked' if quality.get('checked') is True else 'Not recorded'))
        recent.append(row)
    context = {
        'days': days, 'state_filter': state, 'search_query': query, 'per_page': per_page, 'page': page,
        'total': total, 'success': success, 'failed': failed,
        'queued': counts.get('queued', 0), 'running': counts.get('running', 0),
        'active': counts.get('queued', 0) + counts.get('running', 0),
        'success_rate': round(success / (success + failed) * 100, 1) if success + failed else None,
        'average_seconds': round(mean(durations), 1) if durations else None,
        'duration_count': len(durations),
        'p95': round(durations[ceil(len(durations) * .95) - 1], 1) if durations else None,
        'sample_count': len(sample), 'sample_limit': SAMPLE_LIMIT, 'input_tokens': known_in, 'output_tokens': known_out,
        'known_calls': known_calls, 'calls_count': calls_count, 'priced_calls': priced,
        'estimate': f'{estimate:.6f}' if priced else None, 'repairs': repaired, 'quality_failed': quality_failed, 'checked': checked,
        'errors': errors, 'alerts': alerts, 'daily': daily, 'recent': recent,
        'model': settings.HUGGINGFACE_MODEL_ID, 'provider': settings.HUGGINGFACE_TEXT_PROVIDER,
        'checked_at': now, 'period_start': start,
    }
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        response = JsonResponse({
            'summary_html': render_to_string('admin/ai_health/_summary.html', context, request=request),
            'results_html': render_to_string('admin/ai_health/_requests.html', context, request=request),
            'filters': {'days': str(days), 'state': state, 'q': query, 'per_page': str(per_page), 'page': str(page.number)},
            'checked_at': timezone.localtime(now).strftime('%b %d, %I:%M %p'),
        })
    else:
        response = render(request, 'admin/ai_health.html', context)
    response['Cache-Control'] = 'no-store'
    response['Vary'] = 'X-Requested-With, Cookie'
    return response
