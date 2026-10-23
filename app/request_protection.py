"""Shared request budgets and short-lived, transactional submission receipts."""
import hashlib
import ipaddress
import json
import math
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import RequestRateBucket, SubmissionReceipt


class RateLimited(Exception):
    def __init__(self, retry_after, scope='request', message=None):
        self.retry_after = max(1, math.ceil(retry_after))
        self.scope = scope
        super().__init__(message or f'Too many requests. Please try again in {self.retry_after} seconds.')


def bucket_key(scope, subject):
    return salted_hmac('request-protection', f'{scope}:{subject}', algorithm='sha256').hexdigest()


def client_ip(request):
    """Honor forwarding headers only when the direct peer is explicitly trusted."""
    try:
        peer = ipaddress.ip_address(request.META.get('REMOTE_ADDR', ''))
    except ValueError:
        return 'unknown'
    networks = [ipaddress.ip_network(value) for value in settings.RATE_LIMIT_TRUSTED_PROXY_CIDRS]
    if not any(peer in network for network in networks):
        return str(peer)
    chain = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')
    for value in reversed(chain):
        try:
            address = ipaddress.ip_address(value.strip())
        except ValueError:
            return str(peer)
        if not any(address in network for network in networks):
            return str(address)
    return str(peer)


def configured_rule(scope, subject, weight=1):
    limit, seconds = settings.REQUEST_RATE_LIMITS[scope]
    return scope, subject, int(limit), int(seconds), weight


def consume_rules(rules):
    """Reserve all budgets or none. Conditional SQL updates prevent lost increments."""
    if not settings.REQUEST_RATE_LIMITING_ENABLED:
        return
    now = timezone.now()
    with transaction.atomic():
        for scope, subject, limit, seconds, weight in sorted(rules, key=lambda item: bucket_key(item[0], item[1])):
            if limit <= 0 or seconds <= 0 or weight <= 0:
                continue
            key = bucket_key(scope, subject)
            expiry = now + timedelta(seconds=seconds)
            bucket, _ = RequestRateBucket.objects.select_for_update().get_or_create(
                key=key, defaults={'expires_at': expiry})
            if bucket.expires_at <= now:
                RequestRateBucket.objects.filter(pk=key, expires_at__lte=now).update(count=0, expires_at=expiry)
                bucket.refresh_from_db()
            reserved = RequestRateBucket.objects.filter(pk=key, count__lte=limit-weight).update(count=F('count') + weight)
            if not reserved:
                raise RateLimited((bucket.expires_at-now).total_seconds(), scope)


def limit_response(request, error, status=429):
    message = str(error)
    if (request.path.startswith('/api/') or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.content_type == 'application/json' or 'application/json' in request.headers.get('Accept', '')):
        response = JsonResponse({'success': False, 'error': message, 'message': message,
                                 'retry_after': error.retry_after}, status=status)
    else:
        response = render(request, 'errors/request_limit.html', {'message': message, 'retry_after': error.retry_after, 'oversized': status == 413}, status=status)
    response['Retry-After'] = str(error.retry_after)
    response['Cache-Control'] = 'no-store'
    return response


def submission_fingerprint(request):
    fields = sorted((key, values) for key, values in request.POST.lists() if key != 'csrfmiddlewaretoken')
    files = []
    for field, uploads in sorted(request.FILES.lists()):
        for upload in uploads:
            digest = hashlib.sha256()
            upload.seek(0)
            for chunk in upload.chunks():
                digest.update(chunk)
            upload.seek(0)
            files.append((field, upload.name, upload.size, digest.hexdigest()))
    # All representations share an operation lock, so switching AJAX/HTML cannot duplicate a booking.
    return bucket_key('submission', json.dumps([request.user.pk, request.path, fields, files], sort_keys=True))


def deduplicate_submission(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.method != 'POST' or not request.user.is_authenticated or request.user.role != 'customer':
            return view(request, *args, **kwargs)
        key = submission_fingerprint(request)
        with transaction.atomic():
            receipt, _ = SubmissionReceipt.objects.select_for_update().get_or_create(key=key, defaults={
                'expires_at': timezone.now() + timedelta(seconds=settings.SUBMISSION_REPLAY_SECONDS)})
            if receipt.status_code and receipt.expires_at > timezone.now():
                ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                stored_json = 'application/json' in receipt.headers.get('Content-Type', '')
                if view.__name__ == 'create_booking' and ajax != stored_json:
                    response = (JsonResponse({'success': True, 'message': 'Your booking has already been submitted.'})
                                if ajax else redirect('booking_page'))
                else:
                    location = receipt.headers.get('Location')
                    response = (HttpResponseRedirect(location, status=receipt.status_code)
                                if location and receipt.status_code in (301, 302, 303, 307, 308)
                                else HttpResponse(receipt.body, status=receipt.status_code))
                    for header, value in receipt.headers.items():
                        response[header] = value
                response['Idempotent-Replayed'] = 'true'
                return response
            request._submission_succeeded = False
            response = view(request, *args, **kwargs)
            if request._submission_succeeded:
                receipt.status_code = response.status_code
                receipt.body = response.content.decode(response.charset)
                receipt.headers = {key: value for key, value in response.items() if key.lower() in ('content-type', 'location')}
                receipt.expires_at = timezone.now() + timedelta(seconds=settings.SUBMISSION_REPLAY_SECONDS)
                receipt.save()
            else:
                receipt.delete()
            return response
    return wrapped
