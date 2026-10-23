"""Customer-only, idempotent AI request submission and recovery endpoints."""
import json
import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import OperationalError
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.db.models import F

from ..ai_jobs import ACTIVE, JobError, create_request, serialize_request
from ..models import AiRequest, ChatSession
from ..request_protection import RateLimited, limit_response


def _customer(request):
    return request.user.is_authenticated and request.user.role == 'customer'


@require_http_methods(['GET', 'DELETE'])
def ai_design_brief(request, session_id):
    if not _customer(request):
        return JsonResponse({'error': 'Authentication required.'}, status=403)
    session = ChatSession.objects.filter(pk=session_id, user=request.user, is_admin_support=False).first()
    if not session:
        return JsonResponse({'error': 'Chat not found.'}, status=404)
    if request.method == 'DELETE':
        ChatSession.objects.filter(pk=session.pk, user=request.user).update(
            design_brief={}, design_brief_version=F('design_brief_version')+1)
        session.refresh_from_db()
    response = JsonResponse({'brief': session.design_brief, 'version': session.design_brief_version})
    response['Cache-Control'] = 'no-store'
    return response


def _data(request):
    if request.content_type == 'multipart/form-data':
        return request.POST
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise JobError('Please submit a valid message.')
    if not isinstance(data, dict):
        raise JobError('Please submit a valid message.')
    return data


def submit(request, *, legacy=False):
    if not _customer(request):
        raise JobError('Please sign in with a customer account to use the assistant.', 403)
    data = _data(request)
    image = request.FILES.get('image')
    if image:
        from .chat import _validate_chat_image
        error = _validate_chat_image(image)
        if error:
            raise JobError(error)
        if len(request.FILES.getlist('image')) != 1:
            raise JobError('Please attach one inspiration photo at a time.')
    return create_request(request.user, request_id=data.get('request_id'),
        message=data.get('message', data.get('note', '')), session_id=data.get('session_id'),
        intent=data.get('intent', 'auto'), reference_id=data.get('reference_id'),
        upload=image, retry_of=data.get('retry_of'), legacy=legacy, source_photo_id=data.get('source_photo_id'))


def _error(request, error):
    if isinstance(error, RateLimited):
        return limit_response(request, error)
    if isinstance(error, OperationalError):
        return limit_response(request, RateLimited(5,
            message='The assistant is temporarily unavailable. Please try again shortly.'), status=503)
    payload = {'error': str(error), 'success': False}
    if isinstance(error, JobError) and error.active:
        payload['active_request'] = serialize_request(error.active)
    return JsonResponse(payload, status=getattr(error, 'status', 400))


@require_POST
def ai_request_create(request):
    try:
        job, created = submit(request)
        response = JsonResponse(serialize_request(job), status=202 if job.state in ACTIVE else 200)
        response['Cache-Control'] = 'no-store'
        response['Idempotent-Replayed'] = 'false' if created else 'true'
        return response
    except (JobError, RateLimited, ValidationError, OperationalError) as error:
        return _error(request, error)


@require_GET
def ai_request_status(request, request_id):
    if not _customer(request):
        return JsonResponse({'error': 'Authentication required.'}, status=403)
    job = AiRequest.objects.select_related('session', 'user_message').filter(pk=request_id, user=request.user).first()
    if not job:
        return JsonResponse({'error': 'Request not found.'}, status=404)
    if job.state == 'running':
        from ..ai_jobs import expire_interrupted_requests
        # Recovery must not wait for a busy worker to notice a crashed worker's lease.
        expire_interrupted_requests(job.pk)
        job.refresh_from_db()
    response = JsonResponse(serialize_request(job))
    response['Cache-Control'] = 'no-store'
    return response


@require_GET
def ai_request_active(request):
    if not _customer(request):
        return JsonResponse({'error': 'Authentication required.'}, status=403)
    job = AiRequest.objects.select_related('session', 'user_message').filter(user=request.user, state__in=ACTIVE).first()
    response = JsonResponse({'request': serialize_request(job) if job else None})
    response['Cache-Control'] = 'no-store'
    return response


def legacy_ai_response(request, *, stream=False):
    """Legacy routes share the same queue, bans, budgets and request identity."""
    try:
        job, created = submit(request, legacy=True)
    except (JobError, RateLimited, ValidationError, OperationalError) as error:
        return _error(request, error)

    def events():
        from django.db import close_old_connections
        previous = ''
        deadline = time.monotonic() + 95
        while time.monotonic() < deadline:
            close_old_connections()
            current = AiRequest.objects.select_related('session', 'user_message').filter(pk=job.pk, user=request.user).first()
            if not current:
                yield 'data: ' + json.dumps({'type': 'error', 'message': 'This chat was removed.'}) + '\n\n'
                return
            if current.state not in ACTIVE:
                yield 'data: ' + json.dumps({'type': 'final', 'data': current.result}) + '\n\n'
                return
            partial = current.partial_text
            if partial.startswith(previous) and len(partial) > len(previous):
                yield 'data: ' + json.dumps({'type': 'delta', 'text': partial[len(previous):]}) + '\n\n'
                previous = partial
            time.sleep(0.5)
        yield 'data: ' + json.dumps({'type': 'pending', 'request_id': str(job.pk),
            'status_url': f'/api/ai/requests/{job.pk}/'}) + '\n\n'

    if stream:
        response = StreamingHttpResponse(events(), content_type='text/event-stream')
        response['X-Accel-Buffering'] = 'no'
    elif job.state not in ACTIVE:
        response = JsonResponse(job.result)
    else:
        # New clients poll the saved request instead of starting a second generation.
        response = JsonResponse({**serialize_request(job), 'request_id': str(job.pk)}, status=202)
    response['Cache-Control'] = 'no-store'
    response['X-AI-Request-ID'] = str(job.pk)
    return response
