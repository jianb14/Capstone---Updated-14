"""Customer-admin chat system (sessions, messages, reactions, pins). (split from app/views.py)"""

import logging

from django.core.cache import cache
from django.db.models import Q
from django.http import StreamingHttpResponse

from .common import *  # noqa: F401,F403
from .common import _get_primary_admin_user, _is_admin_user  # noqa: F401
from ..services import (
    AI_REQUEST_TIMEOUT,
    DEFAULT_IMAGE_MODEL,
    InferenceClient,
    analyze_inspiration_image,
    build_image_generation_prompt,
    build_image_negative_prompt,
    detect_frustration,
    get_chatbot_response,
    stream_chatbot_events,
    suggested_followups,
)
from ..services import (  # noqa: F401  (private helpers used by image tools)
    _extract_image_prompt_block,
    _generate_image_with_fallback,
    _image_success_reply,
    _save_generated_image,
    _strip_prompt_blocks,
    _without_dead_local_proxy,
)

logger = logging.getLogger(__name__)

# Simple per-user throttle for the AI chat endpoint (seconds between messages).
# Prevents runaway request loops from draining HuggingFace quota/credits.
AI_CHAT_THROTTLE_SECONDS = 4


def _chat_object_reactions_json(message, current_user):
    """Summarize reactions on a message as {emoji: count} + my emojis."""
    counts = {}
    my_emojis = []
    for reaction in message.reactions.all():
        counts[reaction.emoji] = counts.get(reaction.emoji, 0) + 1
        if reaction.user_id == current_user.id:
            my_emojis.append(reaction.emoji)
    return counts, my_emojis


def _chat_reply_snippet(message):
    reply = getattr(message, "reply_to", None)
    if reply is None:
        return None
    return {
        "id": reply.id,
        "text": "" if reply.is_deleted else (reply.message or ""),
        "is_deleted": reply.is_deleted,
        "has_image": bool(reply.image),
        "sender_name": reply.sender.get_full_name() or reply.sender.username,
    }


def _get_client_chat_receiver(session):
    return session.assigned_admin or _get_primary_admin_user()


def _validate_chat_image(uploaded_file):
    if not uploaded_file:
        return ""
    if uploaded_file.size > CHAT_IMAGE_MAX_BYTES:
        return "Image must be 5MB or smaller."

    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    extension = os.path.splitext(uploaded_file.name or "")[1].lower()
    if content_type not in CHAT_IMAGE_ALLOWED_CONTENT_TYPES or extension not in CHAT_IMAGE_ALLOWED_EXTENSIONS:
        return "Only JPG, PNG, GIF, or WEBP images are allowed."

    try:
        position = uploaded_file.tell()
    except Exception:
        position = None

    try:
        width, height = get_image_dimensions(uploaded_file)
    except Exception:
        return "Upload a valid image file."
    finally:
        if position is not None:
            try:
                uploaded_file.seek(position)
            except Exception:
                pass

    if not width or not height:
        return "Upload a valid image file."
    return ""


def _chat_message_json(message, current_user):
    role = "user" if message.sender == current_user else "assistant"
    seen_at = None
    if getattr(message, "is_from_admin", False):
        # Admin messages are "seen" once the client marks them read in the widget.
        seen = bool(message.is_read)
        delivered = bool(message.is_delivered or message.is_read)
        if seen and message.read_at:
            seen_at = message.read_at
    else:
        # Client messages are "seen" once the admin opens the thread.
        admin_read = message.session.admin_last_read_at if message.session else None
        seen = bool(admin_read and message.sent_at <= admin_read)
        delivered = bool(message.is_delivered or message.is_read or seen)
        if seen:
            seen_at = admin_read

    reactions, my_reactions = _chat_object_reactions_json(message, current_user)

    return {
        "id": message.id,
        "role": role,
        "content": "" if message.is_deleted else message.message,
        "sender_name": message.sender.get_full_name() or message.sender.username,
        "is_from_admin": message.is_from_admin,
        "is_edited": message.is_edited,
        "edited_at": message.edited_at.strftime("%I:%M %p") if message.edited_at else "",
        "is_deleted": message.is_deleted,
        "deleted_at": message.deleted_at.strftime("%I:%M %p") if message.deleted_at else "",
        "delivered": delivered,
        "delivered_at": message.delivered_at.strftime("%I:%M %p") if message.delivered_at else "",
        "seen": seen,
        "seen_at": seen_at.strftime("%I:%M %p") if seen_at else "",
        "reactions": reactions,
        "my_reactions": my_reactions,
        "reply_to": _chat_reply_snippet(message),
        "image_url": message.image.url if message.image else "",
        "image_name": message.image_original_name if message.image else "",
        "is_pinned": bool(message.is_pinned),
        "sent_at": message.sent_at.strftime("%b %d, %I:%M %p"),
    }


def _get_chat_session_for_user(request, session_id):
    """
    Shared permission helper: the session owner (client) or an admin/staff
    may read a support session. Returns (session, error_response).
    """
    try:
        session = ChatSession.objects.get(id=session_id)
    except (ChatSession.DoesNotExist, ValueError, TypeError):
        return None, JsonResponse({"error": "Session not found"}, status=404)
    if session.user_id != request.user.id and not _is_admin_user(request.user):
        return None, JsonResponse({"error": "Forbidden"}, status=403)
    return session, None


def _pinned_messages_json(session):
    """
    Messenger-style pinned list: newest pin first, capped at 3. When the cap
    is exceeded the OLDEST pin is silently unpinned so the newest pin wins.
    """
    MAX_PINNED = 3
    pinned = list(
        session.messages.filter(is_pinned=True, is_deleted=False)
        .select_related("sender", "pinned_by")
        .order_by("-pinned_at")
    )
    if len(pinned) > MAX_PINNED:
        for stale in pinned[MAX_PINNED:]:
            stale.is_pinned = False
            stale.pinned_by = None
            stale.pinned_at = None
            stale.save(update_fields=["is_pinned", "pinned_by", "pinned_at"])
        pinned = pinned[:MAX_PINNED]
    return [
        {
            "id": msg.id,
            "snippet": (msg.message or "").strip()[:80],
            "has_image": bool(msg.image),
            "image_url": msg.image.url if msg.image else "",
            "sender_name": msg.sender.get_full_name() or msg.sender.username,
            "is_from_admin": msg.is_from_admin,
            "pinned_by": (
                msg.pinned_by.get_full_name() or msg.pinned_by.username
                if msg.pinned_by
                else ""
            ),
            "pinned_by_is_admin": (
                msg.pinned_by_id is not None and (
                    getattr(msg.pinned_by, "role", None) in ["admin", "staff"]
                    or getattr(msg.pinned_by, "is_superuser", False)
                )
            ),
            "pinned_at": (
                msg.pinned_at.strftime("%b %d, %I:%M %p") if msg.pinned_at else ""
            ),
        }
        for msg in pinned
    ]


def _media_files_json(session):
    """All image attachments in the session — newest first — for the info drawer gallery."""
    media = (
        session.messages.filter(is_deleted=False)
        .exclude(image="")
        .exclude(image__isnull=True)
        .select_related("sender")
        .order_by("-sent_at")
    )
    return [
        {
            "id": msg.id,
            "url": msg.image.url,
            "name": msg.image_original_name or "Chat image",
            "sender_name": msg.sender.get_full_name() or msg.sender.username,
            "sent_at": msg.sent_at.strftime("%b %d, %I:%M %p"),
        }
        for msg in media
    ]


def _admin_support_chat_sessions():
    latest_message = ChatMessage.objects.filter(session=OuterRef('pk')).order_by('-sent_at')
    return (
        ChatSession.objects.filter(is_admin_support=True)
        .exclude(status='ai')
        .annotate(
            last_msg_time=Subquery(latest_message.values('sent_at')[:1]),
            last_msg_text=Subquery(latest_message.values('message')[:1]),
            last_msg_id=Subquery(latest_message.values('pk')[:1]),
            message_count=Count('messages'),
            unread_admin_count=Count(
                'messages',
                filter=Q(messages__is_read=False)
                & ~Q(messages__sender__role__in=['admin', 'staff'])
                & ~Q(messages__sender__is_superuser=True),
            ),
        )
        .select_related('user', 'assigned_admin')
        .order_by('status', '-last_msg_time', '-updated_at')
    )


def _admin_support_chat_stats(sessions, admin_user):
    session_list = list(sessions)

    # Flag whether each session's latest message is an image (for "Image sent" preview)
    last_msg_ids = [s.last_msg_id for s in session_list if s.last_msg_id]
    image_msg_ids = set()
    if last_msg_ids:
        image_msg_ids = set(
            ChatMessage.objects.filter(pk__in=last_msg_ids)
            .exclude(image='')
            .exclude(image__isnull=True)
            .values_list('pk', flat=True)
        )
    for session in session_list:
        session.last_msg_has_image = session.last_msg_id in image_msg_ids
    return {
        'pending': sum(1 for session in session_list if session.status == 'pending_admin'),
        'active_admin': sum(1 for session in session_list if session.status == 'active_admin'),
        'assigned_to_me': sum(1 for session in session_list if session.assigned_admin_id == admin_user.id),
        'closed': sum(1 for session in session_list if session.status == 'closed'),
        'unread_total': sum(
            1 for session in session_list
            if session.status != 'closed' and session.has_unread_for_admin
        ),
        'total': len(session_list),
    }, session_list


@require_POST
def chat_api(request):
    """
    API endpoint for the chatbot.
    Expects JSON: { "message": "user message", "session_id": 123 }
    """
    try:
        uploaded_images = []
        if request.content_type and request.content_type.startswith("multipart/form-data"):
            data = request.POST
            uploaded_images = [f for f in request.FILES.getlist("image") if f]
        else:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse({"error": "Invalid JSON body"}, status=400)

        user_message = (data.get("message") or "").strip()
        session_id = data.get("session_id")

        if not user_message and not uploaded_images:
            return JsonResponse({"error": "Message or image is required"}, status=400)

        # Ensure user is authenticated to use sessions properly
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=403)

        # Handle ChatSession
        session = None
        is_new_session = False
        if session_id:
            try:
                session = ChatSession.objects.get(id=session_id, user=request.user)
            except ChatSession.DoesNotExist:
                pass  # If passed session_id is invalid, we will just create a new one

        if session and session.is_admin_support and session.status != "ai":
            if session.status == "closed":
                session.status = "active_admin"

            for uploaded_image in uploaded_images:
                image_error = _validate_chat_image(uploaded_image)
                if image_error:
                    return JsonResponse({"error": image_error}, status=400)

            receiver = _get_client_chat_receiver(session)
            if not receiver:
                return JsonResponse(
                    {"error": "System misconfiguration (no admin found)"}, status=500
                )

            now = timezone.now()
            reply_to_obj = None
            raw_reply_to = data.get("reply_to_id")
            if raw_reply_to:
                try:
                    reply_to_obj = session.messages.get(id=int(raw_reply_to))
                except (ValueError, ChatMessage.DoesNotExist):
                    reply_to_obj = None
            if user_message:
                ChatMessage.objects.create(
                    session=session,
                    sender=request.user,
                    receiver=receiver,
                    message=user_message,
                    reply_to=reply_to_obj,
                )
            for uploaded_image in uploaded_images:
                ChatMessage.objects.create(
                    session=session,
                    sender=request.user,
                    receiver=receiver,
                    message="",
                    image=uploaded_image,
                    image_original_name=uploaded_image.name[:255],
                )
            session.last_client_message_at = now
            session.client_last_active_at = now
            update_fields = ["status", "last_client_message_at", "client_last_active_at", "updated_at"]
            if session.title == "Admin support":
                title_source = user_message or (uploaded_images[0].name if uploaded_images else "Image attachment")
                session.title = title_source[:60] + ("..." if len(title_source) > 60 else "")
                update_fields.append("title")
            session.save(update_fields=update_fields)

            return JsonResponse(
                {
                    "response": "Message sent to admin.",
                    "awaiting_admin": True,
                    "session_id": session.id,
                    "is_new_session": False,
                    "session_title": session.title,
                    "new_status": session.status,
                }
            )

        if uploaded_images:
            return JsonResponse(
                {"error": "Images can only be attached in admin support chat."},
                status=400,
            )

        # Frustration / human-request auto-escalation → admin handoff.
        if detect_frustration(user_message):
            return _escalate_to_admin_support(request, session, user_message)

        # Cache-based throttle so the AI endpoint cannot be spammed.
        ai_throttle_key = f"ai_chat_throttle_{request.user.id}"
        if not cache.add(ai_throttle_key, "1", AI_CHAT_THROTTLE_SECONDS):
            return JsonResponse(
                {
                    "error": (
                        "You're sending messages too quickly. Please wait "
                        f"{AI_CHAT_THROTTLE_SECONDS} seconds and try again."
                    )
                },
                status=429,
            )

        # --- 1. FETCH CONTEXT (HISTORY) FIRST ---
        history = []
        if session:
            recent_msgs = ChatMessage.objects.filter(session=session).order_by("-sent_at")[
                :8
            ]

            # Reorder to chronological (oldest to newest) for the AI
            for msg in reversed(recent_msgs):
                role = "user" if msg.sender == request.user else "assistant"
                history.append({"role": role, "content": msg.message})

        # Get AI Response with History
        ai_result = get_chatbot_response(
            user_message,
            conversation_history=history,
            user=request.user,
        )

        # ai_result includes moderation metadata and response text.
        ai_text = ai_result.get("text", "")
        is_warning = ai_result.get("is_warning", False)
        is_banned = ai_result.get("is_banned", False)
        ban_remaining_seconds = int(ai_result.get("ban_remaining_seconds") or 0)
        moderation_action = ai_result.get("moderation_action", "")
        strike_count = int(ai_result.get("strike_count") or 0)
        should_save = ai_result.get("should_save", not is_warning)

        if should_save:
            # Default receiver for AI bot
            admin_user = _get_primary_admin_user()
            if not admin_user:
                return JsonResponse(
                    {"error": "System misconfiguration (no admin found)"}, status=500
                )

            if not session:
                title = (
                    user_message[:30] + "..." if len(user_message) > 30 else user_message
                )
                session = ChatSession.objects.create(user=request.user, title=title)
                is_new_session = True

            ChatMessage.objects.create(
                session=session,
                sender=request.user,
                receiver=admin_user,
                message=user_message,
                is_flagged=is_warning,
            )

            ChatMessage.objects.create(
                session=session,
                sender=admin_user,
                receiver=request.user,
                message=ai_text,
            )
            session.save(update_fields=["updated_at"])
        elif ai_text and session:
            # Persist moderation/system assistant messages in the active session so
            # chat history remains consistent after reload.
            admin_user = _get_primary_admin_user()
            if admin_user:
                ChatMessage.objects.create(
                    session=session,
                    sender=admin_user,
                    receiver=request.user,
                    message=ai_text,
                    is_flagged=True,
                )
                session.save(update_fields=["updated_at"])

        return JsonResponse(
            {
                "response": ai_text,
                "is_warning": is_warning,
                "is_banned": is_banned,
                "ban_remaining_seconds": ban_remaining_seconds,
                "moderation_action": moderation_action,
                "strike_count": strike_count,
                "session_id": session.id if session else None,
                "is_new_session": is_new_session,
                "session_title": session.title if session else "",
                "suggestions": suggested_followups(ai_text),
                "retry_available": (
                    "usable image" in ai_text.lower()
                    or "credits" in ai_text.lower()
                ),
            }
        )

    except Exception:
        logger.exception("Chat API Error")
        return JsonResponse(
            {"error": "Something went wrong on our end. Please try again later."},
            status=500,
        )


@login_required
@require_GET
def chat_sessions(request):
    """
    GET endpoint to fetch all chat sessions for the current user.
    """
    sessions = ChatSession.objects.filter(user=request.user)
    mode = (request.GET.get("mode") or "ai").strip().lower()
    if mode == "admin":
        sessions = sessions.filter(is_admin_support=True).exclude(status="ai")
    elif mode != "all":
        sessions = sessions.filter(status="ai", is_admin_support=False)
    sessions = sessions.order_by("-updated_at")
    # Client's device is polling sessions — admin messages have now been
    # received on their end, so mark them "Delivered" (not yet "Seen" until
    # the client actually opens the chat / marks them read).
    if mode == "admin":
        ChatMessage.objects.filter(
            session__user=request.user,
            session__is_admin_support=True,
            receiver=request.user,
            is_read=False,
            is_delivered=False,
        ).exclude(sender=request.user).update(
            is_delivered=True, delivered_at=timezone.now()
        )
    sessions_list = []
    for s in sessions:
        sessions_list.append(
            {
                "id": s.id,
                "title": s.title,
                "status": s.status,
                "status_label": s.get_status_display(),
                "assigned_admin": (
                    s.assigned_admin.get_full_name()
                    or s.assigned_admin.username
                    if s.assigned_admin
                    else ""
                ),
                "unread_count": ChatMessage.objects.filter(
                    session=s,
                    receiver=request.user,
                    is_read=False,
                ).exclude(sender=request.user).count(),
                "updated_at": s.updated_at.strftime("%b %d, %Y"),
            }
        )
    ban_status = get_current_ban_status(request.user)
    return JsonResponse(
        {
            "sessions": sessions_list,
            "is_banned": ban_status["is_banned"],
            "ban_remaining_seconds": ban_status["ban_remaining_seconds"],
        }
    )


@login_required
def chat_history(request):
    """
    GET endpoint to fetch recent chat messages for a specific session.
    Expects ?session_id=123
    """
    session_id = request.GET.get("session_id")

    ban_status = get_current_ban_status(request.user)

    if not session_id:
        return JsonResponse(
            {
                "messages": [],
                "is_banned": ban_status["is_banned"],
                "ban_remaining_seconds": ban_status["ban_remaining_seconds"],
            }
        )

    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    # The client's device is actively viewing this chat — mark them online
    # and stamp their last activity (used for presence + offline emails).
    now = timezone.now()
    session.client_last_active_at = now
    session.save(update_fields=["client_last_active_at", "updated_at"])

    recent_msgs = (
        ChatMessage.objects.filter(session=session)
        .select_related("sender", "reply_to", "reply_to__sender")
        .prefetch_related("reactions")
        .order_by("-sent_at")[:50]
    )

    # The messages reached the client's device — mark inbound (admin-sent)
    # messages as delivered. They become "Seen" once the client opens the
    # chat and the widget marks them read.
    ChatMessage.objects.filter(
        session=session,
        receiver=request.user,
        is_read=False,
        is_delivered=False,
    ).exclude(sender=request.user).update(
        is_delivered=True, delivered_at=timezone.now()
    )
    messages_list = []
    for msg in reversed(list(recent_msgs)):
        messages_list.append(_chat_message_json(msg, request.user))

    return JsonResponse(
        {
            "messages": messages_list,
            "pinned_messages": _pinned_messages_json(session),
            "media_count": len(_media_files_json(session)),
            "session": {
                "id": session.id,
                "admin_last_read_at": (
                    session.admin_last_read_at.isoformat() if session.admin_last_read_at else None
                ),
                "title": session.title,
                "status": session.status,
                "status_label": session.get_status_display(),
                "assigned_admin": (
                    session.assigned_admin.get_full_name()
                    or session.assigned_admin.username
                    if session.assigned_admin
                    else ""
                ),
                "admin_online": bool(
                    session.admin_last_active_at
                    and now - session.admin_last_active_at
                    <= timedelta(seconds=CHAT_PRESENCE_ONLINE_SECONDS)
                ),
                "admin_typing": bool(
                    session.admin_typing_until and session.admin_typing_until > now
                ),
                "admin_last_active_at": (
                    session.admin_last_active_at.isoformat() if session.admin_last_active_at else None
                ),
            },
            "is_banned": ban_status["is_banned"],
            "ban_remaining_seconds": ban_status["ban_remaining_seconds"],
        }
    )


# ────────────────────────────────────────────────────────────────
# CLIENT: Full chat page + session sidebar
# ────────────────────────────────────────────────────────────────

@login_required
@require_POST
def chat_clear(request):
    """
    POST endpoint to clear a specific chat session.
    Expects JSON: { "session_id": 123 }
    """
    try:
        data = json.loads(request.body)
        session_id = data.get("session_id")
        if session_id:
            ChatSession.objects.filter(
                id=session_id,
                user=request.user,
                is_admin_support=False,
            ).delete()
            return JsonResponse({"success": True})
        return JsonResponse({"error": "session_id required"}, status=400)
    except Exception as e:
        return JsonResponse({"error": "Something went wrong. Please try again later."}, status=500)


# ────────────────────────────────────────────────────────────────
# CLIENT API: Start or reopen a human admin support session
# ────────────────────────────────────────────────────────────────

@login_required
def client_chat_page(request):
    if request.user.role != 'customer':
        return HttpResponseForbidden("Customers only")
    return redirect('home')


# ────────────────────────────────────────────────────────────────
# CLIENT API: Mark admin-received messages as read in a session
# ────────────────────────────────────────────────────────────────

@login_required
@require_POST
def chat_request_admin(request):
    try:
        data = json.loads(request.body)
        session_id = data.get("session_id")
        admin_user = _get_primary_admin_user()
        created_support_session = False
        if session_id:
            session = get_object_or_404(ChatSession, id=session_id, user=request.user)
        else:
            # Reuse the client's most recent admin-support conversation so each
            # user only ever has one thread in the admin inbox (messenger-style).
            session = (
                ChatSession.objects.filter(user=request.user, is_admin_support=True)
                .exclude(status='ai')
                .order_by('-updated_at')
                .first()
            )
            if session is None:
                session = ChatSession.objects.create(
                    user=request.user,
                    title="Admin support",
                    status="active_admin",
                    is_admin_support=True,
                    assigned_admin=admin_user,
                    last_client_message_at=timezone.now(),
                    client_last_active_at=timezone.now(),
                )
                created_support_session = True

        if created_support_session or session.status in ['ai', 'closed', 'pending_admin']:
            session.status = 'active_admin'
            session.is_admin_support = True
            if not session.assigned_admin:
                session.assigned_admin = admin_user
            session.last_client_message_at = timezone.now()
            session.save(update_fields=[
                'status',
                'is_admin_support',
                'assigned_admin',
                'last_client_message_at',
                'updated_at',
            ])
            try:
                all_admins = []
                for admin in all_admins:
                    try:
                        Notification.objects.create(
                            user=admin,
                            title="New Admin Chat Request",
                            message=f"{(request.user.first_name or request.user.username)} needs help — \"{session.title[:50]}\"",
                            message_type='chat_request',
                            related_id=session.id,
                        )
                    except Exception:
                        continue
            except Exception:
                pass
            AdminNotification.objects.create(
                user=request.user,
                message=(
                    f"{request.user.get_full_name() or request.user.username} "
                    f"requested admin chat support: {session.title[:80]}"
                ),
            )
            return JsonResponse({
                "success": True,
                "new_status": "active_admin",
                "session_id": session.id,
                "message": "Admin support chat is ready."
            })
        return JsonResponse({
            "success": True,
            "new_status": session.status,
            "session_id": session.id,
            "message": "Existing admin support chat restored."
        })
    except Exception as e:
        return JsonResponse({"error": "Something went wrong. Please try again later."}, status=500)


# ────────────────────────────────────────────────────────────────
# CHAT API: Edit an own text message (admin or client)
# ────────────────────────────────────────────────────────────────

@login_required
@require_POST
def chat_mark_read(request):
    try:
        data = json.loads(request.body)
        session_id = data.get("session_id")
        if not session_id:
            return JsonResponse({"error": "session_id required"}, status=400)
        session = get_object_or_404(ChatSession, id=session_id, user=request.user)
        ChatMessage.objects.filter(
            session=session, is_read=False,
        ).exclude(sender=request.user).update(
            is_read=True,
            read_at=timezone.now(),
            is_delivered=True,
            delivered_at=timezone.now(),
        )
        return JsonResponse({"success": True})
    except Exception as e:
        return JsonResponse({"error": "Something went wrong. Please try again later."}, status=500)


# ────────────────────────────────────────────────────────────────
# CHAT API: Typing indicator ping (client OR admin)
# ────────────────────────────────────────────────────────────────

@login_required
@require_POST
def chat_edit_message(request):
    try:
        data = json.loads(request.body)
        message_id = data.get("message_id")
        new_text = (data.get("message") or "").strip()
        if not message_id:
            return JsonResponse({"error": "message_id required"}, status=400)
        if not new_text:
            return JsonResponse({"error": "Message cannot be empty"}, status=400)
        message = get_object_or_404(ChatMessage, id=message_id, sender=request.user)
        message.message = new_text
        message.is_edited = True
        message.edited_at = timezone.now()
        message.save(update_fields=["message", "is_edited", "edited_at"])
        return JsonResponse({
            "success": True,
            "updated": _chat_message_json(message, request.user),
        })
    except Http404:
        raise
    except Exception as e:
        return JsonResponse({"error": "Something went wrong. Please try again later."}, status=500)


# ────────────────────────────────────────────────────────────────
# CHAT API: Presence — who is online / typing right now
# ────────────────────────────────────────────────────────────────

@login_required
@require_POST
def chat_typing(request):
    try:
        data = json.loads(request.body)
        session_id = data.get("session_id")
        if not session_id:
            return JsonResponse({"error": "session_id required"}, status=400)
        session = get_object_or_404(ChatSession, id=session_id)
        is_admin = _is_admin_user(request.user)
        is_client = session.user_id == request.user.id
        if not (is_admin or is_client):
            return JsonResponse({"error": "Forbidden"}, status=403)
        session.client_last_active_at = timezone.now()
        if is_admin:
            session.admin_typing_until = timezone.now() + timedelta(seconds=CHAT_TYPING_SECONDS)
        else:
            session.client_typing_until = timezone.now() + timedelta(seconds=CHAT_TYPING_SECONDS)
        session.save(
            update_fields=[
                "client_last_active_at",
                "admin_typing_until" if is_admin else "client_typing_until",
                "updated_at",
            ]
        )
        return JsonResponse({"success": True})
    except Exception as e:
        return JsonResponse({"error": "Something went wrong. Please try again later."}, status=500)


# ────────────────────────────────────────────────────────────────
# CHAT API: Delete a message (soft delete — "This message was deleted")
# ────────────────────────────────────────────────────────────────

@login_required
def chat_presence(request):
    session_id = request.GET.get("session_id")
    if not session_id:
        return JsonResponse({"error": "session_id required"}, status=400)
    session = get_object_or_404(ChatSession, id=session_id)
    is_admin = _is_admin_user(request.user)
    is_client = session.user_id == request.user.id
    if not (is_admin or is_client):
        return JsonResponse({"error": "Forbidden"}, status=403)
    now = timezone.now()
    delta = timedelta(seconds=CHAT_PRESENCE_ONLINE_SECONDS)
    return JsonResponse(
        {
            "client_online": bool(session.client_last_active_at and now - session.client_last_active_at <= delta),
            "client_typing": bool(session.client_typing_until and session.client_typing_until > now),
            "admin_online": bool(session.admin_last_active_at and now - session.admin_last_active_at <= delta),
            "admin_typing": bool(session.admin_typing_until and session.admin_typing_until > now),
            "client_last_active_at": session.client_last_active_at.isoformat() if session.client_last_active_at else None,
            "admin_last_active_at": session.admin_last_active_at.isoformat() if session.admin_last_active_at else None,
        }
    )


# ────────────────────────────────────────────────────────────────
# CLIENT: Typing indicator ping
# ────────────────────────────────────────────────────────────────

@login_required
@require_POST
def chat_delete_message(request):
    try:
        data = json.loads(request.body)
        message_id = data.get("message_id")
        message = get_object_or_404(ChatMessage, id=message_id)
        is_admin = _is_admin_user(request.user)
        session = message.session
        allowed = (
            message.sender_id == request.user.id
            or (is_admin and session is not None and session.is_admin_support)
        )
        if not allowed:
            return JsonResponse({"error": "Forbidden"}, status=403)
        if not message.is_deleted:
            message.is_deleted = True
            message.deleted_at = timezone.now()
            message.save(update_fields=["is_deleted", "deleted_at"])
            # Unsent messages drop their reactions (Messenger behaviour).
            message.reactions.all().delete()
        return JsonResponse({"success": True})
    except Exception as e:
        return JsonResponse({"error": "Something went wrong. Please try again later."}, status=500)


# ────────────────────────────────────────────────────────────────
# CLIENT/ADMIN: Add or remove reaction on a message
# ────────────────────────────────────────────────────────────────

@login_required
@require_POST
def chat_typing_ping(request):
    """Update the typing timestamp for the current user in a session."""
    try:
        data = json.loads(request.body)
        session_id = data.get("session_id")
        is_typing = data.get("is_typing", True)
        if not session_id:
            return JsonResponse({"error": "session_id required"}, status=400)
        session = get_object_or_404(ChatSession, id=session_id)
        is_admin = _is_admin_user(request.user)
        is_client = session.user_id == request.user.id
        if not (is_admin or is_client):
            return JsonResponse({"error": "Forbidden"}, status=403)
        now = timezone.now()
        if is_client:
            if is_typing:
                session.client_typing_until = now + timedelta(seconds=CHAT_TYPING_SECONDS)
            else:
                session.client_typing_until = None
            session.client_last_active_at = now
            update_fields = ["client_last_active_at", "client_typing_until"]
            session.save(update_fields=update_fields)
        elif is_admin:
            if is_typing:
                session.admin_typing_until = now + timedelta(seconds=CHAT_TYPING_SECONDS)
            else:
                session.admin_typing_until = None
            session.admin_last_active_at = now
            update_fields = ["admin_last_active_at", "admin_typing_until"]
            session.save(update_fields=update_fields)
        return JsonResponse({"success": True})
    except Exception as e:
        return JsonResponse({"error": "Something went wrong. Please try again later."}, status=500)


# ────────────────────────────────────────────────────────────────
# ADMIN: Poll for new messages + presence (replaces full-page reload)
# ────────────────────────────────────────────────────────────────

@login_required
@require_POST
def chat_reaction(request):
    """Toggle a reaction on a message."""
    try:
        data = json.loads(request.body)
        message_id = data.get("message_id")
        emoji = data.get("emoji")
        if not message_id or not emoji:
            return JsonResponse({"error": "message_id and emoji required"}, status=400)
        if emoji not in CHAT_REACTION_EMOJIS:
            return JsonResponse({"error": "Invalid emoji"}, status=400)
        message = get_object_or_404(ChatMessage, id=message_id)
        session = message.session
        is_admin = _is_admin_user(request.user)
        is_client = session.user_id == request.user.id
        if not (is_admin or is_client):
            return JsonResponse({"error": "Forbidden"}, status=403)
        # Only ONE reaction per user per message (Messenger-style):
        # reacting with a different emoji replaces the previous one,
        # reacting with the same emoji removes it.
        mine = MessageReaction.objects.filter(message=message, user=request.user)
        if mine.filter(emoji=emoji).exists():
            mine.delete()
        else:
            mine.delete()
            MessageReaction.objects.create(
                message=message, user=request.user, emoji=emoji
            )
        counts, my = _chat_object_reactions_json(message, request.user)
        return JsonResponse({
            "success": True,
            "reactions": counts,
            "my_reactions": my,
        })
    except Exception as e:
        return JsonResponse({"error": "Something went wrong. Please try again later."}, status=500)


# ────────────────────────────────────────────────────────────────
# CHAT API: Toggle a reaction (👍 ❤️ 😮 …) on a message
# ────────────────────────────────────────────────────────────────

@login_required
def admin_chat_poll(request):
    """Return new messages and presence data for the admin thread."""
    if not _is_admin_user(request.user):
        return JsonResponse({"error": "Forbidden"}, status=403)
    session_id = request.GET.get("session_id")
    after_id = request.GET.get("after_id", 0)
    if not session_id:
        return JsonResponse({"error": "session_id required"}, status=400)
    session = get_object_or_404(ChatSession, id=session_id, is_admin_support=True)
    now = timezone.now()
    # Update admin presence
    session.admin_last_active_at = now
    session.save(update_fields=["admin_last_active_at"])
    # Fetch new messages
    new_messages = (
        session.messages.filter(id__gt=after_id)
        .select_related("sender", "reply_to", "reply_to__sender")
        .prefetch_related("reactions", "reactions__user")
        .order_by("sent_at")
    )
    messages_data = [_chat_message_json(msg, request.user) for msg in new_messages]
    # Presence data
    client_online = bool(
        session.client_last_active_at
        and now - session.client_last_active_at
        <= timedelta(seconds=CHAT_PRESENCE_ONLINE_SECONDS)
    )
    client_typing = bool(
        session.client_typing_until and session.client_typing_until > now
    )
    return JsonResponse({
        "messages": messages_data,
        "pinned_messages": _pinned_messages_json(session),
        "client_online": client_online,
        "client_typing": client_typing,
        "session_status": session.status,
    })


# ────────────────────────────────────────────────────────────────
# ADMIN: Chat Inbox — list all client chat sessions grouped by status
# ────────────────────────────────────────────────────────────────

@login_required
@require_POST
def chat_toggle_reaction(request):
    try:
        data = json.loads(request.body)
        message_id = data.get("message_id")
        emoji = (data.get("emoji") or "").strip()
        if not message_id:
            return JsonResponse({"error": "message_id required"}, status=400)
        if emoji not in CHAT_REACTION_EMOJIS:
            return JsonResponse({"error": "Invalid emoji"}, status=400)
        message = get_object_or_404(ChatMessage, id=message_id)
        # Only ONE reaction per user per message (Messenger-style):
        # reacting with a different emoji replaces the previous one,
        # reacting with the same emoji removes it.
        mine = MessageReaction.objects.filter(message=message, user=request.user)
        if mine.filter(emoji=emoji).exists():
            mine.delete()
        else:
            mine.delete()
            MessageReaction.objects.create(
                message=message, user=request.user, emoji=emoji
            )
        counts, my = _chat_object_reactions_json(message, request.user)
        return JsonResponse(
            {"success": True, "reactions": counts, "my_reactions": my}
        )
    except Exception as e:
        return JsonResponse({"error": "Something went wrong. Please try again later."}, status=500)


# ────────────────────────────────────────────────────────────────
# ADMIN: Chat Thread — view full conversation + post reply
# ────────────────────────────────────────────────────────────────

@login_required
def admin_chat_inbox(request):
    if not _is_admin_user(request.user):
        return HttpResponseForbidden("Admins only")
    stats, sessions = _admin_support_chat_stats(
        _admin_support_chat_sessions(), request.user
    )
    return render(request, 'admin/admin_chat_inbox.html', {
        'sessions': sessions,
        'stats': stats,
    })


# ────────────────────────────────────────────────────────────────
# ADMIN: Close / archive support chat without deleting history
# ────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────
# ADMIN: Close / Archive chat session
# ────────────────────────────────────────────────────────────────

@login_required
def admin_chat_thread(request, session_id):
    if not _is_admin_user(request.user):
        return HttpResponseForbidden("Admins only")
    session = get_object_or_404(
        ChatSession.objects.select_related('user', 'assigned_admin'),
        id=session_id,
        is_admin_support=True,
    )
    ChatMessage.objects.filter(
        session=session, sender=session.user, is_read=False
    ).update(
        is_read=True,
        read_at=timezone.now(),
        is_delivered=True,
        delivered_at=timezone.now(),
    )
    now = timezone.now()
    session.admin_last_read_at = now
    session.admin_last_active_at = now
    session.save(update_fields=['admin_last_read_at', 'admin_last_active_at'])

    if request.method == 'POST':
        reply_text = request.POST.get('message', '').strip()
        uploaded_images = [f for f in request.FILES.getlist('image') if f]
        for uploaded_image in uploaded_images:
            image_error = _validate_chat_image(uploaded_image)
            if image_error:
                messages.error(request, image_error)
                return redirect('admin_chat_thread', session_id=session.id)
        if reply_text or uploaded_images:
            reply_to_obj = None
            raw_reply_to = request.POST.get('reply_to_id', '')
            if raw_reply_to:
                try:
                    reply_to_obj = session.messages.get(id=int(raw_reply_to))
                except (ValueError, ChatMessage.DoesNotExist):
                    reply_to_obj = None
            if reply_text:
                ChatMessage.objects.create(
                    session=session,
                    sender=request.user,
                    receiver=session.user,
                    message=reply_text,
                    reply_to=reply_to_obj,
                    is_flagged=False,
                )
            for uploaded_image in uploaded_images:
                ChatMessage.objects.create(
                    session=session,
                    sender=request.user,
                    receiver=session.user,
                    message="",
                    image=uploaded_image,
                    image_original_name=uploaded_image.name[:255],
                    is_flagged=False,
                )
            if session.status in ['pending_admin', 'closed']:
                session.status = 'active_admin'
            session.assigned_admin = request.user
            session.admin_last_active_at = now
            session.save(update_fields=['status', 'assigned_admin', 'updated_at', 'admin_last_active_at'])

            # Notify an offline client (in-app ChatNotification + best-effort email).
            client_offline = not (
                session.client_last_active_at
                and now - session.client_last_active_at
                <= timedelta(seconds=CHAT_PRESENCE_ONLINE_SECONDS)
            )
            if client_offline:
                try:
                    ChatNotification.objects.create(
                        user=session.user,
                        session=session,
                        message=reply_text or "You received a new image message from Balloorina support.",
                    )
                except Exception:
                    pass
                if session.user.email:
                    try:
                        send_mail(
                            subject="New message from Balloorina support",
                            body=(
                                f"Hi {session.user.first_name or session.user.username},\n\n"
                                "You have a new message from our support team:\n\n"
                                f"{(reply_text or '(Image attachment)')}\n\n"
                                "Open your chat to reply.\n\n— Balloorina"
                            ),
                            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@balloorina.local"),
                            recipient_list=[session.user.email],
                            fail_silently=True,
                        )
                    except Exception:
                        pass
        return redirect('admin_chat_thread', session_id=session.id)

    chat_messages = list(
        session.messages.all()
        .select_related('sender', 'reply_to', 'reply_to__sender')
        .prefetch_related('reactions', 'reactions__user')
        .order_by('sent_at')
    )
    # Build reaction summaries for each message so the template can render a
    # single merged pill (emojis + total count) without extra queries.
    for message in chat_messages:
        counts = {}
        mine = []
        for reaction in message.reactions.all():
            counts[reaction.emoji] = counts.get(reaction.emoji, 0) + 1
            if reaction.user_id == request.user.id:
                mine.append(reaction.emoji)
        message.reaction_summary = [
            {"emoji": emoji, "count": count, "mine": emoji in mine}
            for emoji, count in counts.items()
        ]
        message.reaction_emojis = "".join(counts.keys())
        message.reaction_total = sum(counts.values())
        message.reaction_mine = mine[0] if mine else ""
    stats, all_sessions = _admin_support_chat_stats(
        _admin_support_chat_sessions(), request.user
    )
    return render(request, 'admin/admin_chat_thread.html', {
        'session': session,
        'chat_messages': chat_messages,
        'all_sessions': all_sessions,
        'stats': stats,
        'now': timezone.now(),
        'pinned_messages': _pinned_messages_json(session),
        'pinned_messages_json': json.dumps(_pinned_messages_json(session)),
        'media_messages': _media_files_json(session),
        'client_is_online': bool(
            session.client_last_active_at
            and now - session.client_last_active_at
            <= timedelta(seconds=CHAT_PRESENCE_ONLINE_SECONDS)
        ),
    })


# ────────────────────────────────────────────────────────────────
# CHAT API: Pin / unpin a message (Messenger-style) — client AND admin
# ────────────────────────────────────────────────────────────────

@login_required
@require_POST
def admin_chat_close(request, session_id):
    if not _is_admin_user(request.user):
        return JsonResponse({"error": "Forbidden"}, status=403)
    session = get_object_or_404(ChatSession, id=session_id, is_admin_support=True)
    session.status = 'closed'
    session.save(update_fields=['status', 'updated_at'])
    return redirect('admin_chat_inbox')


# ────────────────────────────────────────────────────────────────
# CHAT API: Pinned messages list for a session (client AND admin)
# ────────────────────────────────────────────────────────────────

@login_required
@require_POST
def chat_pin_message(request):
    try:
        data = json.loads(request.body)
        message_id = data.get("message_id")
        if not message_id:
            return JsonResponse({"error": "message_id required"}, status=400)
        message = get_object_or_404(
            ChatMessage.objects.select_related("session"), id=message_id
        )
        session = message.session
        if session is None:
            return JsonResponse({"error": "Message has no session"}, status=400)
        # Either side of the support chat may pin/unpin, like Messenger.
        if session.user_id != request.user.id and not _is_admin_user(request.user):
            return JsonResponse({"error": "Forbidden"}, status=403)
        if message.is_deleted:
            return JsonResponse({"error": "Deleted messages cannot be pinned"}, status=400)

        # Only the person who pinned a message can unpin it — kapag si admin
        # ang nag-pin, hindi ma-unpin ng client (at vice versa).
        if message.is_pinned and message.pinned_by_id != request.user.id:
            return JsonResponse(
                {"error": "Only the person who pinned this message can unpin it."},
                status=403,
            )

        if message.is_pinned:
            message.is_pinned = False
            message.pinned_by = None
            message.pinned_at = None
            message.save(update_fields=["is_pinned", "pinned_by", "pinned_at"])
        else:
            # Keep the pinned list capped at 3 — the oldest pin is dropped.
            MAX_PINNED = 3
            current_pins = list(
                session.messages.filter(is_pinned=True, is_deleted=False)
                .order_by("pinned_at")
            )
            while len(current_pins) >= MAX_PINNED:
                oldest = current_pins.pop(0)
                oldest.is_pinned = False
                oldest.pinned_by = None
                oldest.pinned_at = None
                oldest.save(update_fields=["is_pinned", "pinned_by", "pinned_at"])
            message.is_pinned = True
            message.pinned_by = request.user
            message.pinned_at = timezone.now()
            message.save(update_fields=["is_pinned", "pinned_by", "pinned_at"])

        return JsonResponse({
            "success": True,
            "message_id": message.id,
            "is_pinned": message.is_pinned,
            "pinned_messages": _pinned_messages_json(session),
        })
    except Exception as e:
        return JsonResponse({"error": "Something went wrong. Please try again later."}, status=500)


# ────────────────────────────────────────────────────────────────
# CHAT API: Media files sent in a session (client AND admin)
# ────────────────────────────────────────────────────────────────

@login_required
@require_GET
def chat_pinned_messages(request):
    session_id = request.GET.get("session_id")
    if not session_id:
        return JsonResponse({"error": "session_id required"}, status=400)
    session, error = _get_chat_session_for_user(request, session_id)
    if error:
        return error
    return JsonResponse({
        "session_id": session.id,
        "pinned_messages": _pinned_messages_json(session),
    })


# ────────────────────────────────────────────────────────────────
# ADMIN API: Poll unread / pending counts for topbar badge
# ────────────────────────────────────────────────────────────────

@login_required
@require_GET
def chat_media_files(request):
    session_id = request.GET.get("session_id")
    if not session_id:
        return JsonResponse({"error": "session_id required"}, status=400)
    session, error = _get_chat_session_for_user(request, session_id)
    if error:
        return error
    media = _media_files_json(session)
    return JsonResponse({
        "session_id": session.id,
        "media": media,
        "media_count": len(media),
    })


@login_required
@require_GET
def admin_chat_unread_poll(request):
    if not _is_admin_user(request.user):
        return JsonResponse({"error": "Forbidden"}, status=403)
    sessions = ChatSession.objects.filter(is_admin_support=True).exclude(status='ai')
    unread_count = sum(
        1 for s in sessions
        if s.status != 'closed' and s.has_unread_for_admin
    )
    pending_count = sessions.filter(status='pending_admin').count()
    return JsonResponse({
        'unread_total': unread_count,
        'pending_count': pending_count,
    })


# ────────────────────────────────────────────────────────────────
# AI CHAT: persistence + escalation + streaming + image tools
# ────────────────────────────────────────────────────────────────

def _persist_ai_exchange(user, session, user_message, ai_text, is_warning):
    """Save the user message + AI reply (same rules as chat_api)."""
    admin_user = _get_primary_admin_user()
    if not admin_user:
        return session, False
    created_new = False
    if not session:
        title = (
            user_message[:30] + "..." if len(user_message) > 30 else user_message
        )
        session = ChatSession.objects.create(user=user, title=title)
        created_new = True
    ChatMessage.objects.create(
        session=session,
        sender=user,
        receiver=admin_user,
        message=user_message,
        is_flagged=is_warning,
    )
    ChatMessage.objects.create(
        session=session,
        sender=admin_user,
        receiver=user,
        message=ai_text,
    )
    session.save(update_fields=["updated_at"])
    return session, created_new


def _notify_admins_new_chat_request(session, requester):
    try:
        admin_accounts = User.objects.filter(
            Q(role__in=["admin", "staff"]) | Q(is_superuser=True),
            is_active=True,
        ).distinct()
        for admin_account in admin_accounts:
            try:
                Notification.objects.create(
                    user=admin_account,
                    title="New Admin Chat Request",
                    message=(
                        f"{(requester.first_name or requester.username)} needs help — "
                        f"\"{session.title[:50]}\""
                    ),
                    message_type='chat_request',
                    related_id=session.id,
                )
            except Exception:
                continue
    except Exception:
        pass
    try:
        AdminNotification.objects.create(
            user=requester,
            message=(
                f"{requester.get_full_name() or requester.username} "
                f"requested admin chat support: {session.title[:80]}"
            ),
        )
    except Exception:
        pass


def _escalate_to_admin_support(request, session, user_message):
    """Auto-handoff when the user is frustrated or asks for a human."""
    admin_user = _get_primary_admin_user()
    if not admin_user:
        return JsonResponse(
            {"error": "System misconfiguration (no admin found)"}, status=500
        )

    if not session:
        session = ChatSession.objects.create(
            user=request.user,
            title="Admin support",
            status="active_admin",
            is_admin_support=True,
            assigned_admin=admin_user,
            last_client_message_at=timezone.now(),
            client_last_active_at=timezone.now(),
        )
    else:
        session.status = "active_admin"
        session.is_admin_support = True
        if not session.assigned_admin:
            session.assigned_admin = admin_user
        session.last_client_message_at = timezone.now()
        session.client_last_active_at = timezone.now()
        session.save(update_fields=[
            "status",
            "is_admin_support",
            "assigned_admin",
            "last_client_message_at",
            "client_last_active_at",
            "updated_at",
        ])

    ChatMessage.objects.create(
        session=session,
        sender=request.user,
        receiver=admin_user,
        message=user_message,
    )
    _notify_admins_new_chat_request(session, request.user)

    reply_text = (
        "I understand — let me connect you with a real person from the Balloorina "
        "team. Your chat has been passed to our admin, and they'll reply here shortly."
    )
    ChatMessage.objects.create(
        session=session,
        sender=admin_user,
        receiver=request.user,
        message=reply_text,
    )
    return JsonResponse({
        "response": reply_text,
        "awaiting_admin": True,
        "session_id": session.id,
        "is_new_session": False,
        "session_title": session.title,
        "new_status": session.status,
        "suggestions": [],
    })


@login_required
@require_POST
def chat_api_stream(request):
    """SSE endpoint: streams AI text replies token-by-token."""
    try:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

        user_message = (data.get("message") or "").strip()
        session_id = data.get("session_id")
        if not user_message:
            return JsonResponse({"error": "Message is required"}, status=400)
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=403)

        session = None
        if session_id:
            try:
                session = ChatSession.objects.get(id=session_id, user=request.user)
            except ChatSession.DoesNotExist:
                pass

        if session and session.is_admin_support and session.status != "ai":
            return JsonResponse(
                {"error": "This session is handled by an admin."}, status=400
            )

        ai_throttle_key = f"ai_chat_throttle_{request.user.id}"
        if not cache.add(ai_throttle_key, "1", AI_CHAT_THROTTLE_SECONDS):
            return JsonResponse(
                {
                    "error": (
                        "You're sending messages too quickly. Please wait "
                        f"{AI_CHAT_THROTTLE_SECONDS} seconds and try again."
                    )
                },
                status=429,
            )

        history = []
        if session:
            recent_msgs = ChatMessage.objects.filter(session=session).order_by(
                "-sent_at"
            )[:8]
            for msg in reversed(recent_msgs):
                role = "user" if msg.sender == request.user else "assistant"
                history.append({"role": role, "content": msg.message})

        def sse(payload):
            return "data: %s\n\n" % json.dumps(payload)

        def event_stream():
            is_warning = False
            final_data = None
            saved_session = session
            created_new = False
            try:
                for event in stream_chatbot_events(
                    user_message,
                    conversation_history=history,
                    user=request.user,
                ):
                    if event.get("type") == "final":
                        final_data = event.get("data") or {}
                        is_warning = bool(final_data.get("is_warning"))
                        continue
                    yield sse(event)

                if final_data is None:
                    final_data = {"text": "", "should_save": False}
                should_save = final_data.get("should_save", not is_warning)
                ai_text = final_data.get("text", "")

                if should_save and ai_text:
                    saved_session, created_new = _persist_ai_exchange(
                        request.user, session, user_message, ai_text, is_warning
                    )
                elif is_warning and session and ai_text:
                    admin_user = _get_primary_admin_user()
                    if admin_user:
                        ChatMessage.objects.create(
                            session=session,
                            sender=admin_user,
                            receiver=request.user,
                            message=ai_text,
                            is_flagged=True,
                        )
                        session.save(update_fields=["updated_at"])

                reply_lower = (ai_text or "").lower()
                yield sse({
                    "type": "final",
                    "data": {
                        "response": ai_text,
                        "is_warning": bool(final_data.get("is_warning")),
                        "is_banned": bool(final_data.get("is_banned")),
                        "ban_remaining_seconds": int(
                            final_data.get("ban_remaining_seconds") or 0
                        ),
                        "moderation_action": final_data.get("moderation_action", ""),
                        "strike_count": int(final_data.get("strike_count") or 0),
                        "session_id": saved_session.id if saved_session else None,
                        "is_new_session": created_new,
                        "session_title": saved_session.title if saved_session else "",
                        "suggestions": suggested_followups(ai_text),
                        "retry_available": (
                            "usable image" in reply_lower
                            or "credits" in reply_lower
                        ),
                    },
                })
            except Exception:
                logger.exception("Chat Stream Error")
                yield sse({
                    "type": "error",
                    "message": "Something went wrong on our end. Please try again later.",
                })

        response = StreamingHttpResponse(
            event_stream(), content_type="text/event-stream"
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
    except Exception:
        logger.exception("Chat Stream API Error")
        return JsonResponse(
            {"error": "Something went wrong on our end. Please try again later."},
            status=500,
        )


@login_required
@require_POST
def chat_image_feedback(request):
    """Record like/dislike feedback for an AI-generated design image."""
    try:
        data = json.loads(request.body)
        image_url = (data.get("image_url") or "").strip()
        prompt = str(data.get("prompt") or "")[:1000]
        try:
            rating = int(data.get("rating") or 0)
        except (TypeError, ValueError):
            rating = 0
        if not image_url or rating not in (-1, 1):
            return JsonResponse(
                {"error": "image_url and rating (-1 or 1) are required"}, status=400
            )
        if not image_url.startswith(settings.MEDIA_URL):
            return JsonResponse({"error": "Invalid image reference"}, status=400)
        AiImageFeedback.objects.update_or_create(
            user=request.user,
            image_url=image_url,
            defaults={"prompt": prompt, "rating": rating},
        )
        return JsonResponse({"success": True})
    except Exception:
        logger.exception("Chat Image Feedback Error")
        return JsonResponse({"error": "Something went wrong."}, status=500)


@login_required
@require_POST
def chat_save_design(request):
    """Save an AI-generated chat image into the user's My Designs page."""
    if request.user.role != "customer":
        return JsonResponse({"error": "Not allowed"}, status=403)
    try:
        import uuid

        from django.core.files.base import ContentFile

        data = json.loads(request.body)
        image_url = (data.get("image_url") or "").strip()
        prompt = str(data.get("prompt") or "")[:1000]
        if not image_url or not image_url.startswith(settings.MEDIA_URL):
            return JsonResponse({"error": "Invalid image reference"}, status=400)

        rel_path = image_url[len(settings.MEDIA_URL):].lstrip("/\\")
        source_path = os.path.join(settings.MEDIA_ROOT, *rel_path.split("/"))
        if not os.path.exists(source_path):
            return JsonResponse({"error": "Image not found"}, status=404)

        with open(source_path, "rb") as fh:
            image_bytes = fh.read()

        short_prompt = prompt[:40] + ("..." if len(prompt) > 40 else "")
        design_name = f"AI Design — {short_prompt or 'Balloorina concept'}"
        design = UserDesign.objects.create(
            user=request.user,
            name=design_name[:255],
            canvas_json=json.dumps({
                "source": "ai_chat",
                "prompt": prompt,
                "objects": [],
                "background": "#ffffff",
            }),
        )
        design.thumbnail.save(
            f"ai_design_{uuid.uuid4().hex[:10]}.png",
            ContentFile(image_bytes),
            save=True,
        )
        return JsonResponse({
            "success": True,
            "design_id": design.id,
            "message": "Saved to My Designs!",
        })
    except Exception:
        logger.exception("Chat Save Design Error")
        return JsonResponse({"error": "Something went wrong."}, status=500)


# Marker phrases produced by analyze_inspiration_image() when the vision
# model is unavailable (no provider, quota, auth or read failure).
_VISION_FAILURE_MARKERS = (
    "couldn't analyze that photo",
    "photo analysis is temporarily unavailable",
    "ai authentication failed",
    "configuration error",
    "couldn't read that image",
)


def _looks_like_vision_failure(text):
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _VISION_FAILURE_MARKERS)


@login_required
@require_POST
def chat_analyze_image(request):
    """Analyze an uploaded inspiration photo and (when possible) generate a
    matching Balloorina design right away."""
    if request.user.role != "customer":
        return JsonResponse({"error": "Not allowed"}, status=403)
    try:
        uploaded = request.FILES.get("image")
        if not uploaded:
            return JsonResponse({"error": "Image file is required"}, status=400)
        image_error = _validate_chat_image(uploaded)
        if image_error:
            return JsonResponse({"error": image_error}, status=400)

        note = request.POST.get("note") or ""
        reply_text = analyze_inspiration_image(uploaded, note)

        # If the vision model produced an image prompt, generate the design
        # immediately so the user gets a full analyze → design experience.
        prompt_text, _intro_text, _outro_text = _extract_image_prompt_block(reply_text)
        if not prompt_text and _looks_like_vision_failure(reply_text):
            note_stripped = note.strip()
            if note_stripped:
                # Vision analysis is unavailable (e.g. no vision provider on
                # the account). Fall back to the user's typed note through
                # the normal chat pipeline so they still get a design (or a
                # clear explanation) instead of a dead end.
                fallback = get_chatbot_response(
                    note_stripped, conversation_history=[], user=request.user
                )
                fallback_text = fallback.get("text", "") if isinstance(fallback, dict) else str(fallback)
                return JsonResponse({
                    "response": fallback_text,
                    "suggestions": suggested_followups(fallback_text),
                })
            return JsonResponse({
                "response": (
                    "I can't view photos right now because our AI photo-analysis service "
                    "is temporarily unavailable. Please type what design you'd like "
                    "(event type, colors, theme) and I'll create it for you!"
                ),
                "suggestions": ["Suggest a design", "Our packages"],
            })
        if prompt_text:
            try:
                enhanced_prompt = build_image_generation_prompt(prompt_text, "")
                api_key = getattr(settings, "HUGGINGFACE_API_KEY", "")
                if api_key:
                    with _without_dead_local_proxy():
                        try:
                            client = InferenceClient(
                                token=api_key, timeout=AI_REQUEST_TIMEOUT
                            )
                        except TypeError:
                            client = InferenceClient(token=api_key)
                    image_model = getattr(
                        settings,
                        "HUGGINGFACE_IMAGE_MODEL_ID",
                        DEFAULT_IMAGE_MODEL,
                    )
                    generated_image = _generate_image_with_fallback(
                        client,
                        enhanced_prompt,
                        negative_prompt=build_image_negative_prompt(prompt_text),
                        requested_model=image_model,
                    )
                    img_url = _save_generated_image(generated_image)
                    visible_text = _strip_prompt_blocks(reply_text)
                    reply_text = (
                        f"{visible_text}\n\n"
                        f"{_image_success_reply(img_url, enhanced_prompt)}".strip()
                    )
            except Exception as image_error:
                print(f"Analyze Image Generation Error: {image_error}")

        return JsonResponse({
            "response": reply_text,
            "suggestions": ["Our packages", "How to book?"],
        })
    except Exception:
        logger.exception("Chat Analyze Image Error")
        return JsonResponse({"error": "Something went wrong."}, status=500)
