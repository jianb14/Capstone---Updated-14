"""Durable, owned AI requests. Network work always happens outside DB transactions."""
import hashlib
import io
import json
import logging
import secrets
import time
import uuid
from datetime import timedelta
from types import SimpleNamespace

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from . import services
from .ai_intent import is_revision, requests_information, wants_generation
from .ai_limits import reserve_admission, reserve_images
from .ai_catalog import package_catalog_reply
from .ai_text import ProviderFailure, provider_failure
from .ai_telemetry import collect_usage
from .models import AiGeneratedImage, AiRequest, ChatMessage, ChatSession, User
from .request_protection import RateLimited, bucket_key

logger = logging.getLogger(__name__)
ACTIVE = ('queued', 'running')
STAGES = {
    'queued': 'Waiting for the assistant…', 'preparing': 'Preparing your request…',
    'replying': 'Writing a reply…', 'analyzing': 'Analyzing your photo…',
    'generating': 'Creating your design…', 'editing': 'Applying your changes…',
    'saving': 'Saving your design…', 'finished': 'Ready',
    'checking': 'Checking the reply…',
}


class JobError(Exception):
    def __init__(self, message, status=400, *, active=None):
        self.status, self.active = status, active
        super().__init__(message)


def _admin():
    return (User.objects.filter(role='admin', is_active=True).first()
            or User.objects.filter(is_superuser=True, is_active=True).first())


def _fingerprint(text, session_id, intent, reference_id, upload, retry_of, source_photo_id=None):
    digest = ''
    if upload:
        hasher = hashlib.sha256()
        upload.seek(0)
        for chunk in upload.chunks():
            hasher.update(chunk)
        upload.seek(0)
        digest = hasher.hexdigest()
    values = [text, str(session_id or ''), intent, str(reference_id or ''), digest, str(retry_of or '')]
    if source_photo_id:
        values.append(str(source_photo_id))
    return bucket_key('ai-request', json.dumps(values, ensure_ascii=False))


def create_request(user, *, request_id=None, message='', session_id=None, intent='auto',
                   reference_id=None, upload=None, retry_of=None, legacy=False, source_photo_id=None):
    if user.role != 'customer' or not user.is_active:
        raise JobError('This assistant is available to customer accounts.', 403)
    if not isinstance(message, str) or len(message) > settings.AI_MAX_MESSAGE_CHARS:
        raise JobError(f'Please keep your message under {settings.AI_MAX_MESSAGE_CHARS} characters.')
    if intent not in ('auto', 'generate', 'advice', 'revise'):
        raise JobError('Choose a valid request type.')
    message = message.strip()
    retry = None
    if retry_of:
        try:
            retry = AiRequest.objects.select_related('user_message').get(pk=retry_of, user=user, state='failed')
        except (AiRequest.DoesNotExist, ValueError, TypeError, ValidationError):
            raise JobError('That request cannot be retried.', 404)
        if not retry.result.get('retry_available'):
            raise JobError('Please start a new message instead.')
        if not retry.session_id or not retry.user_message:
            raise JobError('This chat is no longer available. Start a new chat.', 404)
        from .ai_photo_edits import owned_photo
        if retry.kind.startswith('photo') and not (retry.user_message.image or owned_photo(retry)):
            raise JobError('Please attach your inspiration photo again.', 404)
        if retry.kind == 'revise' and not retry.reference_id:
            raise JobError('The original design is no longer available.', 404)
        if retry.result.get('retry_at') and timezone.now().timestamp() < retry.result['retry_at']:
            raise RateLimited(retry.result['retry_at'] - timezone.now().timestamp())
        message, session_id = retry.input_text, retry.session_id
        reference_id = retry.reference_id
        source_photo_id = retry.plan.get('source_photo_id')
        intent = 'generate' if retry.kind in ('generate', 'revise', 'photo_edit', 'photo_inspire') else 'advice'
    if not message and not upload and not retry and not source_photo_id:
        raise JobError('Type an idea or attach an inspiration photo.')
    if not message:
        from .ai_photo_edits import PHOTO_PLACEHOLDER
        message = PHOTO_PLACEHOLDER
    # A newly supplied file overrides a stale selection in the composer.
    if upload:
        reference_id, source_photo_id = None, None
    fingerprint = _fingerprint(message, session_id, intent, reference_id, upload, retry_of, source_photo_id)
    if not request_id and legacy:
        # Older streaming/classic clients can reconnect without creating two operations.
        recent = AiRequest.objects.filter(user=user, fingerprint=fingerprint,
            created_at__gte=timezone.now()-timedelta(seconds=30)).first()
        request_id = recent.pk if recent else uuid.uuid4()
    try:
        request_id = uuid.UUID(str(request_id))
    except (ValueError, TypeError):
        raise JobError('A valid request ID is required.')
    with transaction.atomic():
        # NO KEY UPDATE allows completion to insert message FKs while admission waits.
        users = User.objects.select_for_update(no_key=True) if connection.vendor == 'postgresql' else User.objects.select_for_update()
        users.get(pk=user.pk)
        existing = AiRequest.objects.filter(pk=request_id).first()
        if existing:
            if existing.user_id != user.pk:
                raise JobError('Request not found.', 404)
            if existing.fingerprint != fingerprint:
                raise JobError('This request ID is already attached to a different message.', 409)
            return existing, False
        active = AiRequest.objects.filter(user=user, state__in=ACTIVE).first()
        if active:
            raise JobError('The assistant is still working on your previous request.', 409, active=active)
        session = None
        if session_id:
            try:
                session = ChatSession.objects.get(pk=session_id, user=user, is_admin_support=False)
            except (ChatSession.DoesNotExist, ValueError, TypeError):
                raise JobError('This chat is no longer available. Start a new chat.', 404)
        source_photo = None
        if source_photo_id:
            from .ai_photo_edits import owned_photo
            source_photo = owned_photo(SimpleNamespace(plan={}, session_id=getattr(session, 'pk', None),
                user_id=user.pk), source_photo_id)
            if not source_photo:
                raise JobError('That photo is not available in this chat.', 404)
            reference_id = None
        reference = None
        if reference_id:
            try:
                reference = AiGeneratedImage.objects.select_related('request').get(
                    pk=reference_id, request__user=user, request__session=session)
            except (AiGeneratedImage.DoesNotExist, ValueError, TypeError, ValidationError):
                raise JobError('That design is not available in this chat.', 404)
        elif not upload and not source_photo and session and (intent == 'revise' or is_revision(message) or (
                not requests_information(message) and services._asks_for_new_image_variant(message))):
            reference = AiGeneratedImage.objects.filter(request__user=user,
                request__session=session).order_by('-created_at').first()
        photo = bool(upload or source_photo or (retry and retry.user_message and retry.user_message.image))
        reserve_admission(user, photo=photo)
        moderation = services.evaluate_chat_moderation(user, message)
        admin = _admin()
        if not admin:
            raise JobError('The assistant is temporarily unavailable. Please try again later.', 503)
        is_new = session is None
        if session is None:
            session = ChatSession.objects.create(user=user, title=message[:60])
        from .ai_photo_edits import edit_instruction, PHOTO_PLACEHOLDER
        generated = message != PHOTO_PLACEHOLDER and intent != 'advice' and (
            (photo and edit_instruction(message)) or wants_generation(message,
                explicit=intent in ('generate', 'revise'), has_reference=bool(reference) or photo))
        if intent == 'revise' and not reference and not photo and not moderation:
            raise JobError('Open the design you want to change, then try again.')
        kind = ('photo_edit' if generated else 'photo_advice') if photo else (
            'revise' if reference and generated and (intent == 'revise' or is_revision(message)) else 'generate' if generated else 'advice')
        # A deliberate retry keeps the original input bubble, including the stored photo.
        input_message = retry.user_message if retry else ChatMessage.objects.create(
            session=session, sender=user, receiver=admin, message=message,
            is_flagged=bool(moderation), image=upload if not moderation else None,
            image_original_name=(upload.name[:255] if upload and not moderation else ''))
        job = AiRequest.objects.create(id=request_id, user=user, session=session, user_message=input_message,
            input_text=message, fingerprint=fingerprint, kind=kind, reference=reference, retry_of=retry,
            seed=secrets.randbelow(2**31), result={'is_new_session': is_new},
            plan={'requested_intent': intent, 'explicit_reference': bool(reference_id)})
        if photo:
            job.plan['source_photo_id'] = source_photo.pk if source_photo else input_message.pk
            job.save(update_fields=['plan'])
        if moderation:
            complete_request(job.pk, None, moderation)
            job.refresh_from_db()
        else:
            from .ai_worker import start_ai_worker
            transaction.on_commit(start_ai_worker)
        return job, True


def _result(job, data):
    text = data.get('text', '')
    return {
        'response': text, 'is_warning': bool(data.get('is_warning')),
        'is_banned': bool(data.get('is_banned')),
        'ban_remaining_seconds': int(data.get('ban_remaining_seconds') or 0),
        'moderation_action': data.get('moderation_action', ''), 'strike_count': int(data.get('strike_count') or 0),
        'session_id': job.session_id, 'session_title': job.session.title,
        'is_new_session': job.result.get('is_new_session', False),
        'suggestions': data.get('suggestions') or services.suggested_followups(text),
        'retry_available': bool(data.get('retry_available')), 'retry_after': int(data.get('retry_after') or 0),
        'retry_at': data.get('retry_at'), 'images': data.get('images', []), 'gallery': data.get('gallery', []),
    }


def complete_request(job_id, token, data, *, failed=False, error_code='', assets=(), interrupted_only=False):
    with transaction.atomic():
        job = AiRequest.objects.select_for_update(of=('self',)).select_related('session', 'user_message').filter(pk=job_id).first()
        if not job or job.state not in ACTIVE or job.lease_token != token:
            return False
        if interrupted_only:
            now = timezone.now()
            if not _expired(job, now):
                return False
        if isinstance(job.plan.get('memory'), dict) and job.session_id:
            # A reset during inference increments the version, fencing stale memory.
            ChatSession.objects.filter(pk=job.session_id, user_id=job.user_id,
                design_brief_version=job.plan.get('brief_version')).update(design_brief=job.plan['memory'])
        for asset in assets:
            image = AiGeneratedImage.objects.create(request=job, parent_id=job.reference_id,
                image=asset['name'], prompt=asset['prompt'], seed=asset['seed'])
            data.setdefault('images', []).append({'id': str(image.pk), 'url': image.image.url})
        job.result = _result(job, data)
        # The receiver on the original input is the same assistant account.
        admin = job.user_message.receiver if job.user_message else _admin()
        if admin and job.session_id:
            job.assistant_message = ChatMessage.objects.create(session_id=job.session_id,
                sender=admin, receiver_id=job.user_id, message=job.result['response'],
                is_flagged=bool(data.get('is_warning') or data.get('is_banned')))
            ChatSession.objects.filter(pk=job.session_id).update(updated_at=timezone.now())
        job.state, job.stage, job.error_code = ('failed' if failed else 'succeeded'), 'finished', error_code
        job.finished_at, job.lease_expires_at = timezone.now(), None
        job.partial_text = ''
        job.save()
        return True


def serialize_request(job):
    result = dict(job.result) if job.state not in ACTIVE else {}
    if result.get('gallery'):
        from .ai_conversation import gallery_cards
        result['gallery'] = gallery_cards(ids=[card['id'] for card in result['gallery'] if isinstance(card, dict) and 'id' in card])
    if result.get('is_banned'):
        ban = services.get_current_ban_status(job.user)
        result['is_banned'], result['ban_remaining_seconds'] = ban['is_banned'], ban['ban_remaining_seconds']
    return {
        'id': str(job.pk), 'state': job.state, 'stage': job.stage,
        'retry_of': str(job.retry_of_id) if job.retry_of_id else None,
        'status': STAGES.get(job.stage, STAGES['preparing']), 'kind': job.kind,
        'session_id': job.session_id, 'input_text': job.input_text,
        'user_message_id': job.user_message_id, 'assistant_message_id': job.assistant_message_id,
        'input_image_url': job.user_message.image.url if job.user_message and job.user_message.image else '',
        'partial_text': job.partial_text, 'result': result, 'error_code': job.error_code,
        'has_design_brief': bool(job.session and job.session.design_brief),
        'status_url': f'/api/ai/requests/{job.pk}/',
    }


def claim_request():
    with transaction.atomic():
        query = AiRequest.objects.filter(state='queued').order_by('created_at')
        query = query.select_for_update(skip_locked=True) if connection.features.has_select_for_update_skip_locked else query.select_for_update()
        job = query.first()
        if not job:
            return None
        now = timezone.now()
        job.state, job.stage, job.started_at, job.lease_token = 'running', 'preparing', now, uuid.uuid4()
        job.lease_expires_at = now + timedelta(seconds=max(30, settings.AI_JOB_LEASE_SECONDS))
        job.save(update_fields=['state', 'stage', 'started_at', 'lease_token', 'lease_expires_at'])
        return job.pk, job.lease_token


def _text_expired(job, now):
    cutoff = now - timedelta(seconds=settings.AI_TEXT_JOB_TIMEOUT_SECONDS)
    return bool((job.kind == 'advice' and job.started_at and job.started_at <= cutoff) or
        (job.stage in ('replying', 'checking') and job.provider_started_at and job.provider_started_at <= cutoff))


def _expired(job, now):
    return (not job.lease_expires_at or job.lease_expires_at <= now or
        not job.started_at or job.started_at <= now-timedelta(seconds=settings.AI_JOB_TIMEOUT_SECONDS) or
        _text_expired(job, now))


def expire_interrupted_requests(job_id=None):
    now = timezone.now()
    stale = AiRequest.objects.filter(state='running').filter(
        Q(lease_expires_at__lte=now) |
        Q(started_at__lte=now-timedelta(seconds=settings.AI_JOB_TIMEOUT_SECONDS)) |
        Q(kind='advice', started_at__lte=now-timedelta(seconds=settings.AI_TEXT_JOB_TIMEOUT_SECONDS)) |
        Q(stage__in=('replying', 'checking'), provider_started_at__lte=now-timedelta(seconds=settings.AI_TEXT_JOB_TIMEOUT_SECONDS)))
    if job_id is not None:
        stale = stale.filter(pk=job_id)
    for job in stale[:100]:
        timeout = _text_expired(job, now)
        complete_request(job.pk, job.lease_token, {
            'text': 'The assistant took too long to respond. Please try again shortly.' if timeout else
                'Your request was interrupted. Select Try again to start a new attempt.',
            'retry_available': True, 'retry_after': 5 if timeout else 0,
            'retry_at': now.timestamp() + 5 if timeout else None},
            failed=True, error_code='provider_timeout' if timeout else 'interrupted', interrupted_only=True)


def _photo_bytes(job):
    from .ai_photo_edits import owned_photo
    message = owned_photo(job)
    if not message and not job.plan.get('source_photo_id'):
        message = job.user_message if job.user_message and job.user_message.image else None
    if not message:
        raise JobError('This photo is no longer available. Please attach it again.', 404)
    image = message.image
    with image.open('rb') as source:
        return source.read(5 * 1024 * 1024 + 1)


def execute_request(job_id, token):
    with collect_usage() as calls:
        try:
            _execute_request(job_id, token)
        finally:
            current = AiRequest.objects.filter(pk=job_id, lease_token=token).first()
            if current:
                metrics = dict(current.metrics)
                metrics['calls'] = list(calls)
                AiRequest.objects.filter(pk=job_id, lease_token=token).update(metrics=metrics)


def _execute_request(job_id, token):
    """Called by a worker; a disconnect never starts this work again."""
    job = AiRequest.objects.select_related('user', 'user_message', 'reference', 'session').filter(
        pk=job_id, state='running', lease_token=token).first()
    if not job:
        return
    assets = []
    entries = []
    information = ''
    gallery, suffix = [], ''

    def stage(value, **fields):
        updated = AiRequest.objects.filter(pk=job_id, state='running', lease_token=token).update(stage=value, **fields)
        if not updated:
            raise JobError('This request is no longer active.', 409)

    def reply(*, image_pending=False):
        stage('replying', provider_started_at=timezone.now())
        partial, final, last_publish = '', None, 0
        arguments = {'allow_images': False}
        if image_pending:
            arguments['image_pending'] = True
        for event in services.stream_chatbot_events(job.input_text, history, user=job.user, **arguments):
            if event.get('type') == 'delta':
                partial += event.get('text', '')
                if time.monotonic() - last_publish >= 0.7:
                    stage('replying', partial_text=services._strip_prompt_blocks(partial))
                    last_publish = time.monotonic()
            elif event.get('type') == 'final':
                final = event.get('data', {})
            elif event.get('type') == 'error':
                raise RuntimeError('The assistant is temporarily unavailable.')
        if final and final.get('service_error'):
            raise ProviderFailure.from_payload(final)
        if not final or not final.get('text'):
            raise RuntimeError('The assistant did not return a reply.')
        return final

    try:
        ban = services.get_current_ban_status(job.user)
        if ban['is_banned']:
            complete_request(job_id, token, {'text': services._ban_message(ban['ban_remaining_seconds']),
                'is_banned': True, 'ban_remaining_seconds': ban['ban_remaining_seconds']})
            return
        if services.detect_frustration(job.input_text):
            from .views.chat import _notify_admins_new_chat_request
            with transaction.atomic():
                session = ChatSession.objects.select_for_update().get(pk=job.session_id)
                session.is_admin_support, session.status = True, 'active_admin'
                session.assigned_admin = job.user_message.receiver
                session.last_client_message_at = timezone.now()
                session.save()
                _notify_admins_new_chat_request(session, job.user)
            complete_request(job_id, token, {'text': 'Our team has received your request. Open Support chat to continue with a team member.',
                'suggestions': ['How to book?', 'Our packages']})
            return
        from .ai_photo_edits import PHOTO_PLACEHOLDER, PHOTO_QUESTION
        if not settings.AI_SMART_ROUTING_ENABLED and job.kind.startswith('photo') and job.input_text == PHOTO_PLACEHOLDER:
            complete_request(job_id, token, {'text': PHOTO_QUESTION})
            return
        if job.kind == 'advice' and not settings.AI_SMART_ROUTING_ENABLED:
            catalog = package_catalog_reply(job.input_text)
            if catalog is not None:
                complete_request(job_id, token, {'text': catalog})
                return
        history = [{'role': 'user' if msg.sender_id == job.user_id else 'assistant', 'content': msg.message}
            for msg in reversed(list(ChatMessage.objects.filter(session_id=job.session_id,
                pk__lt=job.user_message_id).order_by('-sent_at', '-pk')[:8]))]
        prepared = None
        if settings.AI_SMART_ROUTING_ENABLED:
            from .ai_conversation import prepare_conversation
            prepared = prepare_conversation(job, history, stage)
            information, gallery, suffix = prepared['text'], prepared['gallery'], prepared['suffix']
            if prepared['final']:
                complete_request(job_id, token, {'text': information, 'gallery': gallery})
                return
        generating = job.kind in ('generate', 'revise', 'photo_edit', 'photo_inspire')
        count = services._detect_variation_count(job.input_text) if job.kind == 'generate' else 1
        visual_brief = prepared['visual'] if prepared else ''
        if generating and requests_information(job.input_text) and not prepared:
            details = reply(image_pending=True)
            information = services._strip_prompt_blocks(details['text'])
            visual_brief = details.get('image_prompt', '')
            stage('preparing', partial_text=information)
        if generating:
            reserve_images(job.user, count)
        stage('analyzing' if job.kind.startswith('photo') else 'preparing', provider_started_at=timezone.now())
        visible_intro, photo_prompt = '', ''
        if job.kind.startswith('photo') and job.kind != 'photo_edit':
            from PIL import Image
            photo = io.BytesIO(_photo_bytes(job))
            with Image.open(photo) as decoded:
                photo.content_type = Image.MIME.get(decoded.format, 'image/jpeg')
            photo.seek(0)
            analysis = services.analyze_inspiration_image(photo, job.input_text, generate=generating, strict=True)
            photo_prompt, intro, outro = services._extract_image_prompt_block(analysis)
            visible_intro = services._strip_prompt_blocks(analysis)
            if not generating:
                if prepared:
                    from .ai_conversation import verify_candidate
                    stage('replying', provider_started_at=timezone.now())
                    visible_intro, quality = verify_candidate(job, job.plan.get('memory', {}),
                        services.get_system_context(user_message=job.input_text, conversation_history=history, user=job.user)
                        +'\nRead-only tool facts: '+information+'\nPhoto analysis: '+visible_intro, visible_intro, stage,
                        time.monotonic()+settings.AI_TEXT_RESPONSE_TIMEOUT_SECONDS, history=history)
                    current_metrics = AiRequest.objects.get(pk=job_id).metrics
                    current_metrics['quality'] = quality
                    AiRequest.objects.filter(pk=job_id, state='running', lease_token=token).update(metrics=current_metrics)
                complete_request(job_id, token, {'text': visible_intro, 'gallery': gallery})
                return
        if generating:
            if services.InferenceClient is None or not settings.HUGGINGFACE_API_KEY:
                raise ProviderFailure('provider_config', 'The assistant is unavailable right now. Please contact our team for help.')
            client = services.InferenceClient(token=settings.HUGGINGFACE_API_KEY, timeout=services.AI_REQUEST_TIMEOUT)
            for index in range(count):
                seed = (job.seed + index) % (2**31)
                if job.kind in ('revise', 'photo_edit'):
                    stage('editing')
                    if job.reference:
                        with job.reference.image.open('rb') as source:
                            source_bytes = source.read(20 * 1024 * 1024 + 1)
                        prior_prompt = job.reference.prompt
                    else:
                        source_bytes, prior_prompt = _photo_bytes(job), photo_prompt
                    if len(source_bytes) > 20 * 1024 * 1024:
                        raise RuntimeError('The reference image is too large.')
                    from .ai_photo_edits import edit_prompt
                    prompt = edit_prompt(job.input_text, prior_prompt, suffix)
                    editing = services.InferenceClient(token=settings.HUGGINGFACE_API_KEY,
                        provider=settings.AI_IMAGE_EDIT_PROVIDER, timeout=services.AI_REQUEST_TIMEOUT)
                    # Read an owned storage object; no URL supplied by a customer is fetched.
                    image = editing.image_to_image(source_bytes, prompt=prompt, model=settings.AI_IMAGE_EDIT_MODEL_ID)
                else:
                    stage('generating')
                    context = services._recent_image_request_context(history, include_last_prompt=False)
                    prompt = services.build_image_generation_prompt(photo_prompt or visual_brief or job.input_text, context) + suffix
                    image = services._generate_image_with_fallback(client, prompt,
                        negative_prompt=services.build_image_negative_prompt(job.input_text),
                        requested_model=settings.HUGGINGFACE_IMAGE_MODEL_ID, seed=seed)
                stage('saving')
                name, url = services._save_generated_image(image, return_name=True)
                assets.append({'name': name, 'prompt': prompt, 'seed': seed})
                entries.append((url, prompt))
            intro = ('\n\n'.join(part for part in (information, visible_intro,
                'Sample AI backdrop concept:' if information else '') if part)
                or ('Here is your updated design.' if job.kind in ('revise', 'photo_edit') else ''))
            text = (services._image_success_reply_multi(entries, intro) if len(entries) > 1
                    else services._image_success_reply(entries[0][0], entries[0][1], intro))
            complete_request(job_id, token, {'text': text, 'gallery': gallery}, assets=assets)
            return
        complete_request(job_id, token, reply())
    except RateLimited as error:
        complete_request(job_id, token, {'text': '\n\n'.join(filter(None, (information, str(error)))), 'gallery': gallery, 'retry_available': True,
            'retry_after': error.retry_after, 'retry_at': timezone.now().timestamp() + error.retry_after},
            failed=True, error_code='rate_limited')
    except Exception as error:
        failure = provider_failure(error)
        logger.warning('AI request failed: request=%s category=%s', job_id, failure.code)
        message = failure.text
        if job.kind in ('revise', 'photo_edit') and failure.code != 'input_unavailable':
            message = 'We could not update this image right now. Your original image is still available.'
        if entries:
            message = services._image_success_reply_multi(entries,
                'These options were saved. We could not finish the remaining option.')
        elif information:
            message = 'We could not generate the sample image right now. Please try again.'
        message = '\n\n'.join(filter(None, (information, message)))
        retry_after = failure.after if failure.retry and not entries else 0
        complete_request(job_id, token, {'text': message, 'gallery': gallery, 'retry_available': failure.retry and not bool(entries),
            'retry_after': retry_after, 'retry_at': timezone.now().timestamp() + retry_after if retry_after else None},
            failed=True, error_code=failure.code, assets=assets)
