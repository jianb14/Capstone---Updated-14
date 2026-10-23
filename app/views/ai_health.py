"""Aggregate AI operations dashboard. Customer prompts are never rendered here."""
from datetime import timedelta
from decimal import Decimal
from statistics import mean

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils import timezone

from .common import _is_admin_user
from ..models import AiRequest


@login_required
def ai_health(request):
    if not _is_admin_user(request.user):
        return HttpResponseForbidden('Staff access required')
    days = int(request.GET.get('days', '7')) if request.GET.get('days', '7') in ('1', '7', '30') else 7
    now = timezone.now()
    base = AiRequest.objects.filter(created_at__gte=now-timedelta(days=days))
    counts = {row['state']: row['n'] for row in base.values('state').annotate(n=Count('id'))}
    total, success, failed = sum(counts.values()), counts.get('succeeded', 0), counts.get('failed', 0)
    sample = list(base.order_by('-created_at')[:500])
    durations = sorted((row.finished_at-row.started_at).total_seconds() for row in sample if row.finished_at and row.started_at)
    known_in = known_out = known_calls = calls_count = priced = repaired = quality_failed = 0
    estimate = Decimal(0)
    for row in sample:
        quality = row.metrics.get('quality', {})
        repaired += bool(quality.get('repairs'))
        quality_failed += quality.get('passed') is False
        for call in row.metrics.get('calls', []):
            calls_count += 1
            if isinstance(call.get('input_tokens'), int) and isinstance(call.get('output_tokens'), int):
                known_calls += 1
                known_in += call['input_tokens']
                known_out += call['output_tokens']
            if call.get('estimated_usd') is not None:
                estimate += Decimal(call['estimated_usd'])
                priced += 1
    errors = list(base.exclude(error_code='').values('error_code').annotate(n=Count('id')).order_by('-n'))
    permanent = {'model_unavailable', 'provider_auth', 'provider_credits', 'provider_request', 'provider_config'}
    alerts = []
    if any(row['error_code'] in permanent for row in errors):
        alerts.append('Configuration or account failures were recorded in this period. Review the error categories and provider settings.')
    if failed >= 3 and failed / max(success+failed, 1) >= .1:
        alerts.append('The recorded failure rate is elevated. Check provider availability and recent timeouts.')
    if base.filter(state='queued', created_at__lt=now-timedelta(seconds=60)).exists():
        alerts.append('Requests have waited in the queue for more than a minute. Check that an AI worker is running.')
    daily = list(base.annotate(day=TruncDate('created_at')).values('day').annotate(n=Count('id')).order_by('day'))
    peak = max((row['n'] for row in daily), default=1)
    for row in daily:
        row['height'] = max(3, round(row['n'] / peak * 100))
    response = render(request, 'admin/ai_health.html', {
        'days': days, 'total': total, 'success': success, 'failed': failed,
        'active': counts.get('queued', 0)+counts.get('running', 0),
        'success_rate': round(success / (success+failed)*100, 1) if success+failed else None,
        'average_seconds': round(mean(durations), 1) if durations else None,
        'p95': round(durations[min(len(durations)-1, int(len(durations)*.95))], 1) if durations else None,
        'sample_count': len(sample), 'input_tokens': known_in, 'output_tokens': known_out,
        'known_calls': known_calls, 'calls_count': calls_count, 'priced_calls': priced,
        'estimate': f'{estimate:.6f}' if priced else None, 'repairs': repaired, 'quality_failed': quality_failed,
        'errors': errors, 'alerts': alerts, 'daily': daily, 'recent': sample[:30],
        'model': settings.HUGGINGFACE_MODEL_ID, 'provider': settings.HUGGINGFACE_TEXT_PROVIDER,
        'checked_at': now,
    })
    response['Cache-Control'] = 'no-store'
    return response
