"""Asynchronous customer support, kept separate from the AI conversation API."""
import hashlib
import json
import logging
import uuid
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from PIL import Image, UnidentifiedImageError

from ..models import ChatMessage, ChatNotification, ChatSession, MessageReaction, SubmissionReceipt, User
from ..request_protection import bucket_key
from .chat import _chat_message_json, _pinned_messages_json, _notify_admins_new_chat_request
from .common import _is_admin_user, CHAT_PRESENCE_ONLINE_SECONDS

log = logging.getLogger(__name__)
MAX_TEXT = 4000
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 5 * 1024 * 1024
REACTIONS = ('👍', '❤️', '😮', '😂', '😢')


def support_access(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Your session has expired. Sign in again to continue.'}, status=401)
        if not request.user.is_active or not (_is_admin_user(request.user) or request.user.role == 'customer'):
            return JsonResponse({'error': 'You cannot access support chat.'}, status=403)
        return view(request, *args, **kwargs)
    return never_cache(wrapped)


def failure(message, status=400, field=None):
    data = {'error': message}
    if field:
        data['field'] = field
    return JsonResponse(data, status=status)


def session_for(request, value, *, lock=False):
    try:
        session_id = int(value)
    except (ValueError, TypeError):
        return None
    qs = ChatSession.objects.filter(pk=session_id, is_admin_support=True).exclude(status='ai')
    if not _is_admin_user(request.user):
        qs = qs.filter(user=request.user)
    if lock:
        qs = qs.select_for_update()
    return qs.first()


def message_data(message, user):
    item = _chat_message_json(message, user)
    stamp = timezone.localtime(message.sent_at)
    item.update(own=message.sender_id == user.pk, sent_at=stamp.strftime('%b %d, %I:%M %p'),
                sent_iso=stamp.isoformat(), day=stamp.strftime('%B %d, %Y'),
                time=stamp.strftime('%I:%M %p').lstrip('0'))
    # Per-message receipts remain exact even when messages share a timestamp.
    # The legacy session timestamp is only an inbox activity hint.
    item['seen'] = message.is_read
    item['delivered'] = message.is_delivered or message.is_read
    if message.read_at:
        item['seen_at'] = timezone.localtime(message.read_at).strftime('%I:%M %p')
    return item


def session_data(session, user):
    admin = _is_admin_user(user)
    other = session.user if admin else session.assigned_admin
    active = session.client_last_active_at if admin else session.admin_last_active_at
    typing = session.client_typing_until if admin else session.admin_typing_until
    return {'id': session.pk, 'name': (other.get_full_name() or other.username) if admin else 'Admin Support',
            'email': session.user.email if admin else '', 'status': session.status,
            'online': bool(active and timezone.now() - active <= timedelta(seconds=CHAT_PRESENCE_ONLINE_SECONDS)),
            'typing': bool(typing and typing > timezone.now()),
            'url': reverse('admin_chat_thread', args=[session.pk])}


@support_access
@require_GET
def support_inbox(request):
    if not _is_admin_user(request.user):
        return failure('Admins only.', 403)
    query = request.GET.get('q', '').strip()[:150]
    status = request.GET.get('status', 'all')
    if status not in ('all', 'unread', 'pending_admin', 'active_admin', 'closed'):
        return failure('Choose a valid conversation filter.')
    try:
        page = max(1, int(request.GET.get('page', 1)))
    except ValueError:
        return failure('Choose a valid inbox page.')
    base = ChatSession.objects.filter(is_admin_support=True).exclude(status='ai')
    counts = dict(base.values_list('status').annotate(total=Count('id')))
    inbound = ChatMessage.objects.filter(session_id=OuterRef('pk'), sender_id=OuterRef('user_id'), is_read=False)
    base = base.annotate(unread=Exists(inbound))
    stats = {**counts, 'all': sum(counts.values()), 'unread': base.filter(unread=True).count()}
    if status == 'unread':
        base = base.filter(unread=True)
    elif status != 'all':
        base = base.filter(status=status)
    if query:
        matching = ChatMessage.objects.filter(session_id=OuterRef('pk'), is_deleted=False, message__icontains=query)
        base = base.annotate(matched=Exists(matching)).filter(
            Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query) |
            Q(user__username__icontains=query) | Q(user__email__icontains=query) | Q(matched=True))
    latest = ChatMessage.objects.filter(session_id=OuterRef('pk')).order_by('-pk')
    base = base.select_related('user').annotate(last_text=Subquery(latest.values('message')[:1]),
        last_image=Subquery(latest.values('image')[:1]), last_deleted=Subquery(latest.values('is_deleted')[:1]),
        last_time=Subquery(latest.values('sent_at')[:1])).order_by('-updated_at', '-pk')
    offset = (page - 1) * 30
    rows = list(base[offset:offset + 31])
    return JsonResponse({'sessions': [dict(id=s.pk, name=s.user.get_full_name() or s.user.username,
        email=s.user.email, status=s.status, unread=s.unread, url=reverse('admin_chat_thread', args=[s.pk]),
        preview=('Message deleted' if s.last_deleted else s.last_text or ('Photo attachment' if s.last_image else 'No messages yet'))[:130],
        time=timezone.localtime(s.last_time).strftime('%b %d · %I:%M %p') if s.last_time else '') for s in rows[:30]],
        'stats': stats, 'has_more': len(rows) > 30, 'page': page})


@support_access
@require_GET
def support_state(request):
    raw_id = request.GET.get('session_id')
    session = session_for(request, raw_id) if raw_id else None
    if raw_id and not session:
        return failure('Conversation not found or unavailable.', 404)
    if not raw_id and not _is_admin_user(request.user):
        session = ChatSession.objects.filter(user=request.user, is_admin_support=True).exclude(status='ai').order_by('-updated_at', '-pk').first()
    unread = ChatMessage.objects.filter(session__user=request.user, session__is_admin_support=True,
        receiver=request.user, is_read=False).exclude(sender=request.user).count() if not _is_admin_user(request.user) else 0
    if not session:
        return JsonResponse({'session': None, 'messages': [], 'unread': unread})
    if request.GET.get('summary') == '1':
        return JsonResponse({'session': session_data(session, request.user), 'unread': unread})
    qs = session.messages.select_related('sender', 'session', 'reply_to', 'reply_to__sender').prefetch_related('reactions')
    query = request.GET.get('q', '').strip()[:150]
    if query:
        qs = qs.filter(is_deleted=False, message__icontains=query)
    try:
        before = int(request.GET.get('before', 0))
        after = int(request.GET.get('after', 0))
        if before < 0 or after < 0 or before and after:
            raise ValueError
    except ValueError:
        return failure('Choose a valid message page.')
    if before:
        qs = qs.filter(pk__lt=before)
    if after:
        qs = qs.filter(pk__gt=after)
    rows = list(qs.order_by('pk' if after else '-pk')[:51])
    page = rows[:50] if after else list(reversed(rows[:50]))
    result = {'session': session_data(session, request.user), 'messages': [message_data(m, request.user) for m in page],
              'has_more': len(rows) > 50, 'more_new': bool(after and len(rows) > 50), 'oldest_id': page[0].pk if page else None,
              'pinned': _pinned_messages_json(session), 'unread': unread}
    if request.GET.get('media') == '1':
        result['media'] = [{'id': m.pk, 'url': m.image.url, 'name': m.image_original_name or 'Photo'} for m in
                           session.messages.filter(is_deleted=False).exclude(image='').exclude(image__isnull=True).order_by('-pk')[:100]]
    if request.GET.get('watch'):
        try:
            watched = [int(value) for value in request.GET['watch'].split(',')]
            if len(watched) > 50:
                raise ValueError
        except ValueError:
            return failure('Invalid message update request.')
        result['updates'] = [message_data(m, request.user) for m in
            session.messages.filter(pk__in=watched).select_related('sender', 'session', 'reply_to', 'reply_to__sender').prefetch_related('reactions')]
    return JsonResponse(result)


def validate_uploads(files):
    if len(files) > MAX_IMAGES:
        return 'You can attach up to 4 images per message.'
    for file in files:
        if file.size > MAX_IMAGE_BYTES:
            return 'Each image must be 5 MB or smaller.'
        if file.content_type not in ('image/jpeg', 'image/png', 'image/gif', 'image/webp') or file.name.rsplit('.', 1)[-1].lower() not in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
            return 'Choose JPG, PNG, GIF or WEBP images.'
        try:
            with Image.open(file) as image:
                if image.format not in ('JPEG', 'PNG', 'GIF', 'WEBP') or image.width * image.height > 40_000_000:
                    return 'Choose a valid image up to 40 megapixels.'
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            return 'This image could not be read. Choose another image.'
        finally:
            file.seek(0)
    return ''


def notify_offline(session, text):
    if session.client_last_active_at and timezone.now() - session.client_last_active_at <= timedelta(seconds=CHAT_PRESENCE_ONLINE_SECONDS):
        return
    ChatNotification.objects.create(user=session.user, session=session,
        message=text or 'You received a new image message from Balloorina support.')
    if session.user.email:
        try:
            send_mail(subject='New message from Balloorina support',
                message=f'Hi {session.user.first_name or session.user.username},\n\nYou have a new message from our support team:\n\n{text or "(Image attachment)"}\n\nOpen your chat to reply.\n\n— Balloorina',
                from_email=settings.DEFAULT_FROM_EMAIL, recipient_list=[session.user.email], fail_silently=False)
        except Exception:
            log.exception('Offline support email failed for conversation %s', session.pk)


@support_access
@require_POST
def support_send(request):
    text = request.POST.get('message', '').strip()
    files = request.FILES.getlist('image')
    if len(text) > MAX_TEXT:
        return failure('Keep your message to 4,000 characters or fewer.', field='message')
    if not text and not files:
        return failure('Write a message or attach an image.', field='message')
    error = validate_uploads(files)
    if error:
        return failure(error, field='image')
    try:
        token = str(uuid.UUID(request.POST.get('request_id', '')))
    except ValueError:
        return failure('This send request is invalid. Please try again.')
    key = bucket_key('support-send', f'{request.user.pk}:{token}')
    digest = hashlib.sha256()
    digest.update(json.dumps([text, request.POST.get('session_id'), request.POST.get('reply_to_id')]).encode())
    for file in files:
        file_digest = hashlib.sha256()
        for chunk in file.chunks():
            file_digest.update(chunk)
        digest.update(json.dumps([file.name, file.size, file_digest.hexdigest()]).encode())
        file.seek(0)
    fingerprint = digest.hexdigest()
    admin = _is_admin_user(request.user)
    created = False
    with transaction.atomic():
        # Serializes first-chat creation and retries from the same sender.
        User.objects.select_for_update().get(pk=request.user.pk)
        receipt = SubmissionReceipt.objects.filter(pk=key).first()
        if receipt:
            if receipt.headers.get('fingerprint') != fingerprint:
                return failure('This send request has already been used. Send your updated message again.', 409)
            return JsonResponse(json.loads(receipt.body))
        raw_id = request.POST.get('session_id')
        session = session_for(request, raw_id, lock=True) if raw_id else None
        if raw_id and not session or admin and not session:
            return failure('Conversation not found or unavailable.', 404)
        if not admin and not session:
            session = ChatSession.objects.select_for_update().filter(user=request.user, is_admin_support=True).exclude(status='ai').order_by('-updated_at', '-pk').first()
        receiver = session.user if admin else (session.assigned_admin if session else None)
        if not admin and (not receiver or not receiver.is_active or not _is_admin_user(receiver)):
            receiver = User.objects.filter(Q(role='admin') | Q(is_superuser=True), is_active=True).order_by('-is_superuser', 'pk').first()
        if not receiver:
            return failure('Support is unavailable right now. Please try again later.', 503)
        if not session and request.POST.get('reply_to_id'):
            return failure('The message you are replying to is no longer available.')
        if not session:
            session = ChatSession.objects.create(user=request.user, is_admin_support=True, status='active_admin',
                title='Admin support', assigned_admin=receiver)
            created = True
        reply = None
        if request.POST.get('reply_to_id'):
            try:
                reply = session.messages.filter(pk=int(request.POST['reply_to_id']), is_deleted=False).first()
            except ValueError:
                pass
            if not reply:
                return failure('The message you are replying to is no longer available.')
        rows = []
        if text:
            rows.append(ChatMessage.objects.create(session=session, sender=request.user, receiver=receiver, message=text, reply_to=reply))
        for file in files:
            rows.append(ChatMessage.objects.create(session=session, sender=request.user, receiver=receiver,
                image=file, image_original_name=file.name[:255], reply_to=reply if not text else None))
        now = timezone.now()
        session.status = 'active_admin'
        if admin:
            session.assigned_admin = request.user
            session.admin_last_active_at = now
            session.admin_typing_until = None
        else:
            session.assigned_admin = receiver
            session.last_client_message_at = now
            session.client_last_active_at = now
            session.client_typing_until = None
        session.save()
        body = {'success': True, 'session_id': session.pk, 'messages': [message_data(m, request.user) for m in rows]}
        SubmissionReceipt.objects.create(key=key, expires_at=now + timedelta(days=1), status_code=200,
            body=json.dumps(body), headers={'fingerprint': fingerprint})
    try:
        if created:
            _notify_admins_new_chat_request(session, request.user)
        elif admin:
            notify_offline(session, text)
    except Exception:
        # A notification failure must never turn a saved message into a failed send.
        log.exception('Support notification failed for conversation %s', session.pk)
    return JsonResponse(body)


@support_access
@require_POST
def support_action(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
    except (ValueError, TypeError):
        return failure('Invalid request. Please try again.')
    with transaction.atomic():
        session = session_for(request, data.get('session_id'), lock=True)
        if not session:
            return failure('Conversation not found or unavailable.', 404)
        action = data.get('action')
        admin = _is_admin_user(request.user)
        now = timezone.now()
        if action == 'activity':
            field = 'admin_last_active_at' if admin else 'client_last_active_at'
            setattr(session, field, now)
            typing_field = 'admin_typing_until' if admin else 'client_typing_until'
            setattr(session, typing_field, now + timedelta(seconds=8) if data.get('typing') is True else None)
            fields = [field, typing_field]
            incoming = session.messages.filter(sender_id=session.user_id) if admin else session.messages.exclude(sender_id=session.user_id)
            if data.get('read') is True:
                try:
                    last_id = int(data.get('last_id', 0))
                except (ValueError, TypeError):
                    return failure('Invalid read position.')
                read_messages = incoming.filter(pk__lte=last_id)
                last = read_messages.order_by('-sent_at', '-pk').first()
                read_messages.filter(is_read=False).update(is_read=True, read_at=now, is_delivered=True, delivered_at=now)
                if admin and last:
                    session.admin_last_read_at = max(session.admin_last_read_at, last.sent_at) if session.admin_last_read_at else last.sent_at
                    fields.append('admin_last_read_at')
            try:
                delivered_id = int(data.get('last_id', 0))
            except (ValueError, TypeError):
                return failure('Invalid delivery position.')
            incoming.filter(pk__lte=delivered_id, is_delivered=False).update(
                is_delivered=True, delivered_at=now)
            session.save(update_fields=fields)
            return JsonResponse({'success': True})
        if action in ('close', 'reopen'):
            if not admin:
                return failure('Admins only.', 403)
            session.status = 'closed' if action == 'close' else 'active_admin'
            session.save(update_fields=['status', 'updated_at'])
            return JsonResponse({'success': True, 'session': session_data(session, request.user)})
        try:
            message = session.messages.select_related('sender', 'session', 'reply_to', 'reply_to__sender').get(pk=int(data.get('message_id')))
        except (ValueError, TypeError, ChatMessage.DoesNotExist):
            return failure('Message not found.', 404)
        if message.is_deleted:
            return failure('This message has already been deleted.')
        if action in ('edit', 'delete'):
            if message.sender_id != request.user.pk:
                return failure('You can only change your own messages.', 403)
            if action == 'edit':
                text = data.get('message')
                if not isinstance(text, str) or not text.strip() or len(text.strip()) > MAX_TEXT:
                    return failure('Enter a message between 1 and 4,000 characters.', field='message')
                message.message = text.strip()
                message.is_edited = True
                message.edited_at = now
            else:
                message.is_deleted = True
                message.deleted_at = now
                message.is_pinned = False
                message.pinned_by = None
                message.pinned_at = None
                message.reactions.all().delete()
            message.save()
        elif action == 'pin':
            if message.is_pinned and message.pinned_by_id != request.user.pk:
                return failure('Only the person who pinned this message can unpin it.', 403)
            if not message.is_pinned:
                old = list(session.messages.filter(is_pinned=True).order_by('-pinned_at').values_list('pk', flat=True)[2:])
                session.messages.filter(pk__in=old).update(is_pinned=False, pinned_by=None, pinned_at=None)
            message.is_pinned = not message.is_pinned
            message.pinned_by = request.user if message.is_pinned else None
            message.pinned_at = now if message.is_pinned else None
            message.save(update_fields=['is_pinned', 'pinned_by', 'pinned_at'])
        elif action == 'react':
            emoji = data.get('emoji')
            if emoji not in REACTIONS:
                return failure('Choose a supported reaction.')
            mine = MessageReaction.objects.filter(message=message, user=request.user)
            remove = mine.filter(emoji=emoji).exists()
            mine.delete()
            if not remove:
                MessageReaction.objects.create(message=message, user=request.user, emoji=emoji)
        else:
            return failure('Choose a valid chat action.')
        return JsonResponse({'success': True, 'updated': message_data(message, request.user), 'pinned': _pinned_messages_json(session)})
