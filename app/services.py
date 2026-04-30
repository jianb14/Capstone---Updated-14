import base64
import hashlib
import hmac
import os
import re
import time
import uuid
from datetime import timedelta
from decimal import Decimal
from html import escape, unescape
from pathlib import Path
from contextlib import contextmanager

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Avg, Count, Sum
from django.utils import timezone

from .models import (
    AboutContent,
    AboutValueItem,
    AdditionalOnly,
    AddOn,
    Booking,
    CanvasAsset,
    CanvasCategory,
    ChatModerationEvent,
    ChatModerationState,
    ConcernTicket,
    GalleryCategory,
    GalleryImage,
    GCashConfig,
    HomeContent,
    HomeFeatureItem,
    Notification,
    Package,
    Payment,
    Review,
    Service,
    ServiceChargeConfig,
    ServiceContent,
    UserDesign,
)

try:
    from huggingface_hub import InferenceClient
except ImportError:
    InferenceClient = None


def get_paymongo_headers():
    """Helper to get PayMongo authentication headers."""
    if not settings.PAYMONGO_SECRET_KEY:
        return {}

    credentials = f"{settings.PAYMONGO_SECRET_KEY}:"
    encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/json",
        "accept": "application/json",
    }


def create_paymongo_checkout_session(
    amount,
    booking_id,
    success_url,
    cancel_url,
    payment_type="card",
    description="",
    billing=None,
):
    """
    Create a PayMongo checkout session.
    Amount should be in PHP cents (e.g., PHP100.00 -> 10000).
    """
    url = "https://api.paymongo.com/v1/checkout_sessions"
    headers = get_paymongo_headers()
    if not headers:
        return None

    payload = {
        "data": {
            "attributes": {
                "billing": billing or None,
                "send_email_receipt": True,
                "show_description": True,
                "show_line_items": True,
                "description": description or f"Payment for Booking #{booking_id}",
                "line_items": [
                    {
                        "currency": "PHP",
                        "amount": amount,
                        "name": f"Booking #{booking_id}",
                        "quantity": 1,
                    }
                ],
                "payment_method_types": [payment_type],
                "success_url": success_url,
                "cancel_url": cancel_url,
            }
        }
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"PayMongo Checkout Error: {e}")
        return None


def retrieve_paymongo_payment(payment_id):
    """Retrieve a PayMongo payment by ID to verify its status."""
    url = f"https://api.paymongo.com/v1/payments/{payment_id}"
    headers = get_paymongo_headers()
    if not headers:
        return None

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"PayMongo Retrieve Error: {e}")
        return None


def retrieve_paymongo_checkout_session(session_id):
    """Retrieve a PayMongo checkout session by ID."""
    url = f"https://api.paymongo.com/v1/checkout_sessions/{session_id}"
    headers = get_paymongo_headers()
    if not headers:
        return None

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"PayMongo Checkout Session Retrieve Error: {e}")
        return None


def verify_paymongo_webhook_signature(payload, signature_header):
    """Verify PayMongo webhook signature using the webhook secret."""
    if not settings.PAYMONGO_WEBHOOK_SECRET:
        return False

    try:
        if not signature_header:
            return False

        # PayMongo format:
        # t=1496734173,te=<test_signature>,li=<live_signature>
        parsed = {}
        for part in signature_header.split(","):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            parsed[key.strip()] = value.strip()

        timestamp = parsed.get("t")
        test_sig = parsed.get("te", "")
        live_sig = parsed.get("li", "")
        if not timestamp:
            return False

        secret = settings.PAYMONGO_WEBHOOK_SECRET.encode("utf-8")
        signed_payload = f"{timestamp}.{payload}".encode("utf-8")
        computed_signature = hmac.new(secret, signed_payload, hashlib.sha256).hexdigest()

        # Basic replay protection (5 minutes)
        try:
            ts_int = int(timestamp)
            if abs(int(time.time()) - ts_int) > 300:
                return False
        except (ValueError, TypeError):
            return False

        secret_key = settings.PAYMONGO_SECRET_KEY or ""
        expected_signature = live_sig if secret_key.startswith("sk_live_") else test_sig
        if not expected_signature:
            return False

        return hmac.compare_digest(computed_signature, expected_signature)
    except Exception as e:
        print(f"PayMongo Webhook Verification Error: {e}")
        return False


# Moderation configuration
ROLLING_VIOLATION_WINDOW_HOURS = 6
BAN_DURATION_HOURS = 1
MAX_STRIKES_BEFORE_BAN = 3

PROFANITY_TERMS = [
    # English
    "fuck",
    "fucking",
    "fucker",
    "motherfucker",
    "shit",
    "bullshit",
    "bitch",
    "asshole",
    "cunt",
    "dick",
    "pussy",
    "whore",
    "slut",
    "bastard",
    "nigga",
    "nigger",
    "retard",
    "retarded",
    # Tagalog
    "putangina",
    "putanginamo",
    "tangina",
    "tanginamo",
    "puta",
    "pota",
    "potangina",
    "gago",
    "gaga",
    "tanga",
    "bobo",
    "inutil",
    "tarantado",
    "tarantada",
    "ulol",
    "kupal",
    "ogag",
    "pakyu",
    "punyeta",
    "hinayupak",
    "leche",
    "letse",
    "tae",
    "burat",
    "kantot",
    "iyot",
    "puke",
    "pepe",
    "titi",
    "hayop",
]

LEET_CHAR_VARIANTS = {
    "a": ("a", "4", "@"),
    "b": ("b", "8"),
    "e": ("e", "3"),
    "g": ("g", "6", "9"),
    "i": ("i", "1", "!", "|", "l"),
    "l": ("l", "1", "!", "|", "i"),
    "o": ("o", "0"),
    "s": ("s", "5", "$"),
    "t": ("t", "7", "+"),
    "u": ("u", "v"),
    "y": ("y",),
}

EDUCATIONAL_CONTEXT_HINTS = {
    "what does",
    "what is the meaning",
    "meaning of",
    "definition",
    "define",
    "translate",
    "translation",
    "how do you spell",
    "spelling",
    "pronunciation",
    "for educational",
    "for research",
    "is this a bad word",
    "is this offensive",
    "offensive word",
    "profanity",
    "censored",
}

REPORTING_CONTEXT_HINTS = {
    "someone said",
    "someone called me",
    "they called me",
    "he called me",
    "she called me",
    "i was called",
    "i got called",
    "i was insulted",
    "quoted",
    "quote",
}

TOXIC_PATTERNS = [
    re.compile(r"\b(kill yourself|go die|die already|mamatay ka|magpakamatay ka)\b", re.IGNORECASE),
    re.compile(r"\b(you are useless|you're useless|wala kang kwenta|walang kwenta ka)\b", re.IGNORECASE),
    re.compile(r"\b(i hate you)\b", re.IGNORECASE),
    re.compile(r"\b(ang bobo mo|ang tanga mo)\b", re.IGNORECASE),
]

DIRECT_TARGET_PATTERN = re.compile(
    r"\b(you|u|your|ikaw|kayo|ka|mo|nyo|niyo)\b",
    re.IGNORECASE,
)

AGGRESSIVE_CUE_PATTERN = re.compile(
    r"([!?]{1,}|^stfu\b|\bshut up\b|\bbwesit\b|\bbwisit\b|\bwalang kwenta\b)",
    re.IGNORECASE,
)


def _char_pattern_for_letter(letter):
    chars = LEET_CHAR_VARIANTS.get(letter, (letter,))
    deduped = []
    for char in chars:
        if char not in deduped:
            deduped.append(char)
    escaped = "".join(re.escape(char) for char in deduped)
    return f"[{escaped}]"


def _build_obfuscated_pattern(term):
    normalized = re.sub(r"[^a-z]", "", (term or "").lower())
    if not normalized:
        return None
    joined = r"[\W_]*".join(_char_pattern_for_letter(ch) for ch in normalized)
    return re.compile(rf"(?<![a-z0-9]){joined}(?![a-z0-9])", re.IGNORECASE)


PROFANITY_PATTERNS = [
    (term, pattern)
    for term in PROFANITY_TERMS
    for pattern in [_build_obfuscated_pattern(term)]
    if pattern is not None
]


def _normalize_space(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _normalize_repeated_letters(text):
    lowered = str(text or "").lower()
    return re.sub(r"([a-z])\1+", r"\1", lowered)


def _moderation_excerpt(text, max_len=220):
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 3].rstrip() + "..."


def _token_count(text):
    return len(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _is_educational_or_reporting_context(text):
    normalized = _normalize_space(text)
    if any(hint in normalized for hint in EDUCATIONAL_CONTEXT_HINTS):
        return True
    if any(hint in normalized for hint in REPORTING_CONTEXT_HINTS):
        return True
    if re.search(r"\b(word|term|phrase)\b", normalized) and re.search(r"[\"'`].+[\"'`]", str(text or "")):
        return True
    if re.search(r"\b(called|said|told)\b.*\b(me|us)\b", normalized):
        return True
    return False


def _is_clearly_offensive_usage(text, matched_terms):
    normalized = _normalize_space(text)
    if DIRECT_TARGET_PATTERN.search(normalized):
        return True
    if AGGRESSIVE_CUE_PATTERN.search(normalized):
        return True
    if len(matched_terms) >= 2:
        return True
    if _token_count(normalized) <= 5:
        return True
    return False


def _detect_profanity_terms(text):
    normalized = _normalize_repeated_letters(text)
    matched = set()
    for term, pattern in PROFANITY_PATTERNS:
        if pattern.search(normalized):
            matched.add(term)
    return sorted(matched)


def _detect_toxic_terms(text):
    normalized = _normalize_space(text)
    matched = []
    for pattern in TOXIC_PATTERNS:
        match = pattern.search(normalized)
        if match:
            matched.append(match.group(1))
    return sorted(set(matched))


def analyze_text_for_moderation(text):
    message = str(text or "")
    profanity_matches = _detect_profanity_terms(message)
    if profanity_matches:
        if _is_educational_or_reporting_context(message):
            return {
                "is_violation": False,
                "violation_type": "",
                "matched_terms": profanity_matches,
                "reason": "non_offensive_context",
            }
        if _is_clearly_offensive_usage(message, profanity_matches):
            return {
                "is_violation": True,
                "violation_type": "profanity",
                "matched_terms": profanity_matches,
                "reason": "offensive_profanity",
            }
        return {
            "is_violation": False,
            "violation_type": "",
            "matched_terms": profanity_matches,
            "reason": "ambiguous_context",
        }

    toxic_matches = _detect_toxic_terms(message)
    if toxic_matches and not _is_educational_or_reporting_context(message):
        return {
            "is_violation": True,
            "violation_type": "toxicity",
            "matched_terms": toxic_matches,
            "reason": "toxic_behavior",
        }

    return {
        "is_violation": False,
        "violation_type": "",
        "matched_terms": [],
        "reason": "clean",
    }


def _start_of_local_day(now):
    localized = timezone.localtime(now)
    return localized.replace(hour=0, minute=0, second=0, microsecond=0)


def _moderation_window_start(now, state):
    window_start = now - timedelta(hours=ROLLING_VIOLATION_WINDOW_HOURS)
    daily_reset_start = _start_of_local_day(now)
    if daily_reset_start > window_start:
        window_start = daily_reset_start
    if state.last_ban_ended_at and state.last_ban_ended_at > window_start:
        window_start = state.last_ban_ended_at
    return window_start


def _format_human_duration(total_seconds):
    total_seconds = max(1, int(total_seconds))
    minutes, rem_seconds = divmod(total_seconds, 60)
    if minutes < 1:
        return f"{rem_seconds} second{'s' if rem_seconds != 1 else ''}"
    if minutes < 60:
        if rem_seconds:
            return f"{minutes} minute{'s' if minutes != 1 else ''} and {rem_seconds} second{'s' if rem_seconds != 1 else ''}"
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, rem_minutes = divmod(minutes, 60)
    if rem_minutes:
        return f"{hours} hour{'s' if hours != 1 else ''} and {rem_minutes} minute{'s' if rem_minutes != 1 else ''}"
    return f"{hours} hour{'s' if hours != 1 else ''}"


def _format_clock_countdown(total_seconds):
    total_seconds = max(1, int(total_seconds))
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _chat_response_payload(
    text,
    *,
    is_warning=False,
    is_banned=False,
    ban_remaining_seconds=0,
    moderation_action="",
    strike_count=0,
    should_save=True,
):
    return {
        "text": text,
        "is_warning": bool(is_warning),
        "is_banned": bool(is_banned),
        "ban_remaining_seconds": max(0, int(ban_remaining_seconds or 0)),
        "moderation_action": moderation_action or "",
        "strike_count": int(strike_count or 0),
        "should_save": bool(should_save),
    }


def _warning_message_for_strike(strike_count):
    if strike_count <= 1:
        return (
            "<div>"
            "<strong>Warning: Respectful language is required.</strong><br><br>"
            "Please avoid offensive or abusive wording. "
            "This is your first violation."
            "</div>"
        )

    return (
        "<div>"
        "<strong>Final warning issued.</strong><br><br>"
        "This is your second violation. "
        "One more violation will result in a temporary 1-hour ban."
        "</div>"
    )


def _ban_message(remaining_seconds):
    readable_time = _format_human_duration(remaining_seconds)
    clock_time = _format_clock_countdown(remaining_seconds)
    return (
        "<div>"
        "<strong>You are temporarily banned due to repeated violations.</strong><br><br>"
        f"You can chat again in {readable_time}.<br>"
        "Time remaining: "
        f"<span class='ai-ban-countdown' data-ban-seconds='{int(remaining_seconds)}'>{clock_time}</span>"
        "</div>"
    )


def contains_profanity(text):
    """
    Backward-compatible helper.
    Returns True only when offensive profanity usage is clearly detected.
    """
    analysis = analyze_text_for_moderation(text)
    return analysis["is_violation"] and analysis["violation_type"] == "profanity"


def evaluate_chat_moderation(user, user_message):
    """
    Enforce warning/strike/ban policy with:
    - rolling 6-hour strike window
    - daily reset at local day boundary
    - 1-hour ban at 3rd violation
    - strike reset after ban ends
    """
    if not user or not getattr(user, "is_authenticated", False):
        return None

    now = timezone.now()
    analysis = analyze_text_for_moderation(user_message)

    with transaction.atomic():
        state, _ = ChatModerationState.objects.select_for_update().get_or_create(user=user)

        # Automatic unban + strike reset after ban expiry.
        if state.banned_until and now >= state.banned_until:
            state.banned_until = None
            state.last_ban_ended_at = now
            state.save(update_fields=["banned_until", "last_ban_ended_at", "updated_at"])

        # Active ban: block input and show remaining countdown.
        if state.banned_until and now < state.banned_until:
            remaining_seconds = max(1, int((state.banned_until - now).total_seconds()))
            return _chat_response_payload(
                _ban_message(remaining_seconds),
                is_warning=True,
                is_banned=True,
                ban_remaining_seconds=remaining_seconds,
                moderation_action="ban_active",
                strike_count=MAX_STRIKES_BEFORE_BAN,
                should_save=False,
            )

        # No moderation hit: continue normal chatbot flow.
        if not analysis["is_violation"]:
            return None

        window_start = _moderation_window_start(now, state)
        current_strikes = ChatModerationEvent.objects.filter(
            user=user,
            created_at__gte=window_start,
        ).count()
        new_strike_count = current_strikes + 1

        ChatModerationEvent.objects.create(
            user=user,
            violation_type=analysis["violation_type"],
            matched_terms=", ".join(analysis["matched_terms"][:10]),
            message_excerpt=_moderation_excerpt(user_message),
            metadata={
                "reason": analysis["reason"],
                "matched_terms": analysis["matched_terms"][:10],
                "window_start": window_start.isoformat(),
            },
        )

        state.total_violations = int(state.total_violations or 0) + 1

        # Third strike inside the active window triggers an automatic 1-hour ban.
        if new_strike_count >= MAX_STRIKES_BEFORE_BAN:
            state.banned_until = now + timedelta(hours=BAN_DURATION_HOURS)
            state.total_bans = int(state.total_bans or 0) + 1
            state.save(update_fields=["banned_until", "total_violations", "total_bans", "updated_at"])

            remaining_seconds = max(1, int((state.banned_until - now).total_seconds()))
            return _chat_response_payload(
                _ban_message(remaining_seconds),
                is_warning=True,
                is_banned=True,
                ban_remaining_seconds=remaining_seconds,
                moderation_action="ban_applied",
                strike_count=MAX_STRIKES_BEFORE_BAN,
                should_save=False,
            )

        state.save(update_fields=["total_violations", "updated_at"])
        return _chat_response_payload(
            _warning_message_for_strike(new_strike_count),
            is_warning=True,
            is_banned=False,
            ban_remaining_seconds=0,
            moderation_action=f"warning_{new_strike_count}",
            strike_count=new_strike_count,
            should_save=False,
        )


def get_current_ban_status(user):
    """
    Read-only moderation status for UI restore after page reload.
    Returns dict with is_banned and remaining seconds.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return {"is_banned": False, "ban_remaining_seconds": 0}

    now = timezone.now()
    state, _ = ChatModerationState.objects.get_or_create(user=user)

    # Keep persisted moderation state in sync when UI polls status after expiry.
    if state.banned_until and now >= state.banned_until:
        state.banned_until = None
        state.last_ban_ended_at = now
        state.save(update_fields=["banned_until", "last_ban_ended_at", "updated_at"])

    if state.banned_until and now < state.banned_until:
        remaining_seconds = max(1, int((state.banned_until - now).total_seconds()))
        return {"is_banned": True, "ban_remaining_seconds": remaining_seconds}
    return {"is_banned": False, "ban_remaining_seconds": 0}


IMAGE_KEYWORDS = {
    "picture",
    "image",
    "photo",
    "design",
    "drawing",
    "illustration",
    "gawa ka",
    "gumawa",
    "igawa",
    "draw",
    "generate",
    "create",
    "make",
    "show me",
    "backdrop",
    "balloon",
    "cartoon",
    "anime",
    "character",
    "themed",
    "concept",
    "gawa ng",
    "pakita",
    "lagay",
    "theme",
    "themed",
}


def is_image_request(text):
    lowered = (text or "").lower()
    if not lowered.strip():
        return False

    request_verbs = {
        "add",
        "include",
        "insert",
        "change",
        "update",
        "revise",
        "regenerate",
        "again",
        "another",
        "gawa",
        "gumawa",
        "igawa",
        "generate",
        "create",
        "make",
        "draw",
        "show me",
        "pakita",
    }
    visual_terms = {
        "picture",
        "image",
        "photo",
        "drawing",
        "illustration",
        "design",
        "backdrop",
        "theme",
        "themed",
        "concept",
        "cartoon",
        "anime",
        "character",
    }

    has_request_verb = any(term in lowered for term in request_verbs)
    has_visual_term = any(term in lowered for term in visual_terms)
    if has_request_verb and has_visual_term:
        return True

    return any(
        phrase in lowered
        for phrase in [
            "generate image",
            "generate again",
            "create image",
            "make image",
            "draw image",
            "try again",
            "make another",
            "another version",
            "design concept",
            "backdrop design",
            "themed backdrop",
            "balloon backdrop",
        ]
    )


def _history_has_generated_image(conversation_history):
    if not conversation_history:
        return False
    for msg in reversed(conversation_history[-8:]):
        content = str(msg.get("content") or "")
        if "<img " in content or "/media/ai_generated/" in content or "Balloorina Design Concept" in content:
            return True
    return False


def _is_image_followup_request(text, conversation_history):
    if not _history_has_generated_image(conversation_history):
        return False

    lowered = (text or "").lower().strip()
    if not lowered:
        return False

    followup_terms = {
        "again",
        "regenerate",
        "retry",
        "another",
        "more",
        "add",
        "include",
        "insert",
        "change",
        "update",
        "revise",
        "replace",
        "remove",
        "adjust",
        "make it",
        "gawin",
        "lagyan",
        "dagdag",
        "palitan",
        "ulitin",
    }
    if any(term in lowered for term in followup_terms):
        return True

    taglish_followup_patterns = [
        r"^\s*(generate|gawa|gumawa|igawa|create|make)\b.*\bpa\b",
        r"^\s*(isa|one)\s+pa\b",
        r"\b(ulit|ulitin|ibang version|other version|another version)\b",
        r"\b(lagyan|dagdagan)\b.*\b(arch|flowers?|florals?|balloons?|ilaw|lights?)\b",
        r"\b(alisin|tanggalin|remove)\b.*\b(arch|flowers?|florals?|balloons?|ilaw|lights?)\b",
    ]
    return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in taglish_followup_patterns)


def _extract_recent_image_prompt(conversation_history):
    if not conversation_history:
        return ""

    prompt_patterns = [
        r'data-ai-prompt="([^"]+)"',
        r"data-ai-prompt='([^']+)'",
    ]
    for msg in reversed(conversation_history[-10:]):
        if msg.get("role") != "assistant":
            continue
        content = str(msg.get("content") or "")
        for pattern in prompt_patterns:
            match = re.search(pattern, content)
            if match:
                return _safe_text(unescape(match.group(1)))[:1000]
    return ""


def _recent_image_request_context(conversation_history, include_last_prompt=False):
    if not conversation_history:
        return ""

    recent_user_messages = []
    for msg in reversed(conversation_history[-8:]):
        role = msg.get("role")
        content = _safe_text(msg.get("content"))
        if not content:
            continue
        if role == "user":
            recent_user_messages.append(content)
            if is_image_request(content):
                break

    recent_user_messages.reverse()
    context_parts = []
    if include_last_prompt:
        recent_prompt = _extract_recent_image_prompt(conversation_history)
        if recent_prompt:
            context_parts.append(f"Previous generated image prompt: {recent_prompt}")
    if recent_user_messages:
        context_parts.append("Recent user image instructions: " + " ".join(recent_user_messages[-3:]))
    return " ".join(context_parts)


IMAGE_REQUEST_CLEANUP_PATTERNS = [
    r"\bgawa\s+(ka|mo)?\s*(nga|ng|nang|na)?\b",
    r"\bigawa\s+(mo|nyo)?\s*(ako|kami)?\b",
    r"\bgumawa\s+(ka|mo)?\s*(ng|nang)?\b",
    r"\b(generate|create|make|draw|show me|pakita)\b",
    r"\b(image|picture|photo|drawing|illustration|design|concept)\b",
    r"\b(backdrop|balloon|decoration|setup)\b",
    r"\b(can you|could you)\b",
    r"\b(me|for me)\b",
    r"\b(a|an|of)\b",
    r"\b(ng|nang|na)\b",
    r"\bplease|pls|po|nga|daw|sabi|can you|could you\b",
]

IMAGE_EVENT_HINTS = {
    "birthday": ("birthday", "debut", "1st birthday", "bday"),
    "wedding": ("wedding", "kasal"),
    "christening": ("christening", "baptism", "baptismal", "binyag"),
    "baby shower": ("baby shower",),
    "corporate event": ("corporate", "company", "office", "launch"),
    "gender reveal": ("gender reveal",),
}

IMAGE_COLOR_WORDS = {
    "black",
    "white",
    "gold",
    "silver",
    "blue",
    "pink",
    "red",
    "green",
    "yellow",
    "purple",
    "lavender",
    "orange",
    "cream",
    "beige",
    "brown",
    "pastel",
    "rose gold",
    "navy",
    "mint",
}

IMAGE_COLOR_ALIASES = {
    "asul": "blue",
    "berde": "green",
    "dilaw": "yellow",
    "ginto": "gold",
    "itim": "black",
    "kahel": "orange",
    "lila": "purple",
    "pilak": "silver",
    "pula": "red",
    "puti": "white",
    "rosas": "pink",
}


def _clean_image_theme_text(text):
    cleaned = _safe_text(text)
    cleaned = re.sub(r"https?://\S+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"[\[\]{}<>]", " ", cleaned)
    for pattern in IMAGE_REQUEST_CLEANUP_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,!?:;-")
    return cleaned[:220] if cleaned else "custom elegant celebration theme"


def _detect_image_event_type(text):
    lowered = (text or "").lower()
    for event_type, hints in IMAGE_EVENT_HINTS.items():
        if any(hint in lowered for hint in hints):
            return event_type
    return "celebration event"


def _detect_image_colors(text):
    lowered = (text or "").lower()
    colors = [color for color in IMAGE_COLOR_WORDS if re.search(rf"\b{re.escape(color)}\b", lowered)]
    colors.extend(
        color
        for alias, color in IMAGE_COLOR_ALIASES.items()
        if re.search(rf"\b{re.escape(alias)}\b", lowered)
    )
    if colors:
        return ", ".join(list(dict.fromkeys(colors))[:4])
    return "coordinated theme colors"


def _user_removes_arch(text):
    lowered = (text or "").lower()
    remove_terms = ("remove", "without", "no arch", "no entrance", "alisin", "tanggalin", "wala")
    arch_terms = ("arch", "entrance", "doorway", "archway")
    return any(term in lowered for term in remove_terms) and any(term in lowered for term in arch_terms)


def _user_wants_arch(text):
    lowered = (text or "").lower()
    if _user_removes_arch(lowered):
        return False
    return any(word in lowered for word in ["arch", "entrance", "doorway", "archway", "banderitas"])


def build_image_generation_prompt(user_message, model_prompt=""):
    """
    Build a reliable SDXL prompt from the user's exact request.
    The optional model_prompt is treated as extra detail, never as the source of truth.
    """
    source_text = f"{model_prompt} {user_message}".strip()
    previous_prompt_match = re.search(
        r"Previous generated image prompt:\s*(.*?)(?:Recent user image instructions:|$)",
        model_prompt or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    previous_prompt = _safe_text(previous_prompt_match.group(1))[:800] if previous_prompt_match else ""
    requested_update = _clean_image_theme_text(user_message)
    theme_text = _clean_image_theme_text(source_text)
    event_type = _detect_image_event_type(source_text)
    colors = _detect_image_colors(source_text)
    arch_direction = (
        "include a clear entrance arch only if it fits the requested theme"
        if _user_wants_arch(source_text)
        else "use balloon garlands, balloon clusters, cascading balloons, and organic side arrangements instead of a doorway arch"
    )

    prompt_parts = [
        "WIDE SHOT, full event backdrop center stage",
        (
            f"{event_type} styling, preserve this previous concept: {previous_prompt}"
            if previous_prompt
            else f"{event_type} styling for the theme: {theme_text}"
        ),
        f"requested update or new instruction: {requested_update}",
        f"color palette: {colors}",
        "premium balloon decoration for a real event venue",
        arch_direction,
        "large layered backdrop panels, round and rectangular panels, dessert table or plinths, themed props, soft fabric draping, floral accents, fairy lights",
        "balanced left and right composition, full setup visible from floor to top, no cropped decorations",
        "photorealistic event styling, clean professional venue lighting, realistic balloons, polished luxury finish",
    ]

    prompt_parts.append(
        "wide event styling, luxury balloon decoration setup, high quality, detailed, vibrant colors"
    )
    return ", ".join(prompt_parts)


def build_image_negative_prompt(user_message):
    negative = (
        "low quality, blurry, distorted, deformed, bad anatomy, bad lighting, ugly, messy, "
        "watermark, logo, readable text, misspelled text, random letters, captions, cropped, "
        "out of frame, close-up, portrait crop, empty stage, plain background, duplicate people"
    )
    if not _user_wants_arch(user_message):
        negative += (
            ", entrance arch, doorway arch, full balloon arch, archway, upside-down U-shape arch, "
            "foreground arch, structural arch over stage"
        )
    return negative


def _extract_image_prompt_block(reply_text):
    text = reply_text or ""
    if "[PROMPT]" not in text or "[/PROMPT]" not in text:
        return None, text.strip(), ""
    prompt_start = text.find("[PROMPT]") + len("[PROMPT]")
    prompt_end = text.find("[/PROMPT]")
    prompt = text[prompt_start:prompt_end].strip()
    intro = text[: text.find("[PROMPT]")].strip()
    outro = text[prompt_end + len("[/PROMPT]") :].strip()
    return prompt, intro, outro


def _save_generated_image(generated_image):
    ai_img_dir = os.path.join(settings.MEDIA_ROOT, "ai_generated")
    os.makedirs(ai_img_dir, exist_ok=True)

    filename = f"design_{timezone.now().strftime('%Y%m%d%H%M%S%f')}_{uuid.uuid4().hex[:12]}.png"
    filepath = os.path.join(ai_img_dir, filename)

    if isinstance(generated_image, (bytes, bytearray)):
        with open(filepath, "wb") as image_file:
            image_file.write(generated_image)
    else:
        generated_image.save(filepath, format="PNG")

    if not os.path.exists(filepath) or os.path.getsize(filepath) <= 0:
        raise ValueError("Generated image file was not saved correctly.")

    img_url = f"{settings.MEDIA_URL.rstrip('/')}/ai_generated/{filename}"
    expected_path = os.path.join(
        settings.MEDIA_ROOT,
        img_url.replace(settings.MEDIA_URL, "", 1).lstrip("/\\"),
    )
    if os.path.abspath(expected_path) != os.path.abspath(filepath):
        raise ValueError("Generated image URL does not match the saved file path.")

    return img_url


def _image_success_reply(img_url, prompt, intro_text=""):
    intro = intro_text or "Sige, ito ang Balloorina design concept based sa request mo:"
    return (
        f"{escape(intro)}<br><br>"
        f'<img src="{escape(img_url)}" alt="Balloorina Design Concept" '
        f'data-ai-prompt="{escape(prompt)}" '
        'style="max-width:100%; border-radius:8px; margin-top:6px; '
        'box-shadow:0 4px 12px rgba(0,0,0,0.5);">'
    )


def _image_unavailable_reply(prompt, intro_text="", error_message=""):
    intro = intro_text or "Na-prepare ko na yung design prompt, pero hindi nakapag-return ng usable image yung provider."
    provider_hint = ""
    if error_message:
        error_lower = error_message.lower()
        if "402" in error_lower or "quota" in error_lower or "credits" in error_lower:
            provider_hint = " Mukhang ubos o limited na yung AI provider quota."
        elif "401" in error_lower or "unauthorized" in error_lower:
            provider_hint = " Posibleng invalid or expired yung Hugging Face API key."
    return (
        f"{escape(intro)}{escape(provider_hint)}<br><br>"
        "<div style=\"padding:12px; background:#1a1a1a; border-radius:8px; border:1px solid #333;\">"
        "<em>Improved prompt na pwedeng i-regenerate:</em><br><br>"
        f"<strong>{escape(prompt)}</strong></div>"
    )


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "the",
    "to",
    "we",
    "what",
    "when",
    "where",
    "who",
    "why",
    "with",
    "yung",
    "saan",
    "ano",
    "ang",
    "ng",
    "sa",
    "na",
    "nang",
    "kasi",
    "din",
    "po",
    "ba",
    "ko",
    "mo",
    "siya",
}


INTENT_KEYWORDS = {
    "pricing": {
        "price",
        "pricing",
        "package",
        "packages",
        "addon",
        "add",
        "additional",
        "magkano",
        "cost",
        "bayad",
        "amount",
        "fee",
        "downpayment",
        "dp",
    },
    "booking": {
        "book",
        "booking",
        "pagbook",
        "paano",
        "step",
        "steps",
        "process",
        "reserve",
        "slot",
        "schedule",
        "calendar",
        "event",
        "cancel",
        "edit",
        "pending",
        "confirmed",
        "status",
    },
    "payment": {
        "payment",
        "gcash",
        "paymongo",
        "paypal",
        "card",
        "receipt",
        "balance",
        "verified",
        "rejected",
    },
    "account": {
        "account",
        "profile",
        "dashboard",
        "notification",
        "notifications",
        "login",
        "register",
        "password",
        "email",
        "review",
        "my",
    },
    "design": {
        "design",
        "canvas",
        "gallery",
        "asset",
        "theme",
        "backdrop",
        "image",
        "style",
        "color",
    },
    "system": {
        "system",
        "feature",
        "features",
        "flow",
        "process",
        "module",
        "admin",
        "staff",
        "report",
        "analytics",
    },
    "contact": {
        "contact",
        "email",
        "phone",
        "number",
        "call",
        "facebook",
        "instagram",
        "location",
        "address",
        "hours",
        "open",
        "schedule",
        "oras",
        "contactin",
        "makontak",
        "contact us",
    },
}


REFERENCE_DOC_FILES = [
    "QUICK_REFERENCE.md",
    "INTERACTION_FLOW.md",
    "IMPLEMENTATION_SUMMARY.md",
    "VISUAL_SUMMARY.md",
    "VISUAL_LAYOUT_GUIDE.md",
    "EDITOR_IMPROVEMENTS.md",
    "design-guide.md",
]

DOC_EXCERPT_CHARS = 1400
MAX_CONTEXT_CHARS = 12000
MAX_CONTEXT_CHUNKS = 14
DOC_CACHE_TTL_SECONDS = 300
_DOC_CACHE = {"loaded_at": 0, "chunks": []}


def _safe_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _env_truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _strip_markdown_headings(text):
    lines = []
    for line in (text or "").splitlines():
        cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        lines.append(cleaned)
    return "\n".join(lines)


def _normalize_reply_text(text):
    cleaned = (text or "").replace("\r\n", "\n").strip()
    cleaned = _strip_markdown_headings(cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _looks_truncated(text):
    stripped = (text or "").strip()
    if len(stripped) < 80:
        return False
    if stripped.endswith(("...", "…", ":", "-", "(", "/", ",")):
        return True
    if re.search(r"\b(and|or|but|with|for|to|our|your|the|a|an)\s*$", stripped, flags=re.IGNORECASE):
        return True
    return False


@contextmanager
def _without_dead_local_proxy():
    """
    Some local environments set HTTP(S)_PROXY to 127.0.0.1:9 (discard port),
    which causes all outbound requests to fail with connection refused.
    Temporarily remove only that broken proxy pattern.
    """
    proxy_keys = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]
    removed = {}
    try:
        for key in proxy_keys:
            value = os.environ.get(key, "")
            if "127.0.0.1:9" in value or "localhost:9" in value:
                removed[key] = value
                os.environ.pop(key, None)
        yield
    finally:
        for key, value in removed.items():
            os.environ[key] = value


def _short_text(value, max_len=220):
    text = _safe_text(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _format_money(value):
    if value is None:
        return "PHP 0.00"
    try:
        return f"PHP {Decimal(value):,.2f}"
    except Exception:
        return "PHP 0.00"


def _tokenize(text):
    raw_tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [tok for tok in raw_tokens if len(tok) > 1 and tok not in STOP_WORDS]


def _make_chunk(title, content, tags=None, priority=1.0, always=False):
    tags_set = set(tags or [])
    content_text = _safe_text(content)
    token_source = " ".join([title, content_text, " ".join(sorted(tags_set))])
    return {
        "title": title.strip(),
        "content": content.strip(),
        "tags": tags_set,
        "priority": float(priority),
        "always": bool(always),
        "search_tokens": set(_tokenize(token_source)),
    }


def _status_line(choices):
    return ", ".join(f"{value} ({label})" for value, label in choices)


def _recent_user_history_text(conversation_history, limit=4):
    if not conversation_history:
        return ""

    texts = []
    for item in reversed(conversation_history):
        if item.get("role") != "user":
            continue
        content = re.sub(r"<[^>]+>", " ", item.get("content", ""))
        clean = _safe_text(content)
        if clean:
            texts.append(clean)
        if len(texts) >= limit:
            break
    texts.reverse()
    return " ".join(texts)


def _derive_intents(tokens):
    token_set = set(tokens)
    intents = set()
    for intent, keywords in INTENT_KEYWORDS.items():
        if token_set & keywords:
            intents.add(intent)
    return intents


def _load_reference_doc_chunks():
    now = int(time.time())
    if _DOC_CACHE["chunks"] and now - _DOC_CACHE["loaded_at"] <= DOC_CACHE_TTL_SECONDS:
        return _DOC_CACHE["chunks"]

    chunks = []
    base_dir = Path(settings.BASE_DIR)
    for file_name in REFERENCE_DOC_FILES:
        path = base_dir / file_name
        if not path.exists():
            continue
        try:
            raw_text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        normalized = _safe_text(raw_text)
        if not normalized:
            continue
        excerpt = _short_text(normalized, DOC_EXCERPT_CHARS)
        chunks.append(
            _make_chunk(
                title=f"Internal Reference: {file_name}",
                content=excerpt,
                tags={"system", "docs", "flow", "feature"},
                priority=0.8,
            )
        )

    _DOC_CACHE["chunks"] = chunks
    _DOC_CACHE["loaded_at"] = now
    return chunks


def _strip_html_tags(value):
    return re.sub(r"<[^>]+>", " ", value or "")


def _load_footer_contact_chunk():
    footer_path = Path(settings.BASE_DIR) / "app" / "templates" / "components" / "footer.html"
    if not footer_path.exists():
        return None

    try:
        raw = footer_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    blocks = re.findall(
        r'<div class="contact-info">(.*?)</div>',
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )

    contact_lines = []
    label_map = {
        "email icon": "Email",
        "phone icon": "Phone",
        "calling": "Phone",
        "location icon": "Location",
        "clock icon": "Hours",
    }

    for block in blocks:
        alt_match = re.search(r'alt="([^"]+)"', block, flags=re.IGNORECASE)
        value_match = re.search(r"<p>(.*?)</p>", block, flags=re.IGNORECASE | re.DOTALL)
        if not value_match:
            continue
        value = _safe_text(_strip_html_tags(value_match.group(1)))
        if not value:
            continue

        label_key = _safe_text(alt_match.group(1).lower()) if alt_match else ""
        label = label_map.get(label_key, "Info")
        contact_lines.append(f"- {label}: {value}")

    facebook_match = re.search(
        r'<a href="([^"]+)"[^>]*>\s*<img[^>]*alt="Facebook"',
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    instagram_match = re.search(
        r'<a href="([^"]+)"[^>]*>\s*<img[^>]*alt="Instagram"',
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if facebook_match:
        contact_lines.append(f"- Facebook link: {facebook_match.group(1)}")
    if instagram_match:
        contact_lines.append(f"- Instagram link: {instagram_match.group(1)}")

    if not contact_lines:
        return None

    content = (
        "Use this as the source of truth for customer contact details shown in the website footer:\n"
        + "\n".join(contact_lines)
        + "\nIf a field is missing here, say it is not listed in the footer."
    )
    return _make_chunk(
        "Footer Contact Information",
        content,
        tags={"contact", "account", "system"},
        priority=2.4,
        always=True,
    )


def _build_core_chunks():
    scope_content = (
        "Balloorina assistant scope: answer using Balloorina system knowledge only. "
        "Supported topics include packages, pricing, booking workflow, booking and payment statuses, "
        "customer dashboard actions, design canvas, reviews, gallery, and account-related flows. "
        "If a requested detail is not present in the snapshot, clearly state that it is unavailable."
    )
    flow_content = (
        "Booking process (runtime behavior): "
        "(1) Customer starts at the Events Calendar first, then selects an available date to begin booking. "
        "(2) Customer picks a package/solo add-on plus optional add-ons/additionals. "
        "(3) Customer fills event details: event type, date, start/end time, location, optional notes, optional reference images (up to 4). "
        "(4) Validation rules: date cannot be in the past; if date is today, start time must be in the future; booking hours are 7:00 AM to 6:00 PM; end time must be later than start time; duration must be at least 2 hours; overlapping slots are blocked only against existing pending_payment/confirmed/completed bookings (pending bookings are not blocking yet). "
        "(5) Submit creates a pending booking. Admin approval moves it to pending_payment. After admin verifies payment, booking becomes confirmed; admin can later mark it completed. "
        "Customer change rules: pending bookings can still be edited or deleted by the customer before confirmation; confirmed bookings are final. "
        f"Booking statuses: {_status_line(Booking.STATUS_CHOICES)}. "
        f"Booking payment statuses: {_status_line(Booking.PAYMENT_STATUS_CHOICES)}."
    )
    return [
        _make_chunk(
            "Assistant Scope",
            scope_content,
            tags={"system", "feature"},
            priority=1.5,
            always=True,
        ),
        _make_chunk(
            "Booking Workflow and Status Rules",
            flow_content,
            tags={"booking", "system", "payment", "status"},
            priority=1.6,
            always=True,
        ),
    ]


def _build_catalog_chunks():
    chunks = []

    packages = Package.objects.filter(is_active=True).order_by("-is_featured", "name")
    package_lines = []
    for pkg in packages:
        features = [f.strip() for f in (pkg.feature_list() or []) if f.strip()]
        feature_text = ", ".join(features[:6]) if features else "No features listed"
        notes = _short_text(pkg.notes, 120) if pkg.notes else ""
        line = (
            f"- {pkg.name}: {_format_money(pkg.price)} | Service charge: {_format_money(pkg.service_charge)} "
            f"| Features: {feature_text}"
        )
        if notes:
            line += f" | Notes: {notes}"
        package_lines.append(line)
    if package_lines:
        chunks.append(
            _make_chunk(
                "Packages Catalog",
                "Active packages:\n" + "\n".join(package_lines),
                tags={"pricing", "booking", "package"},
                priority=1.7,
            )
        )

    addons = AddOn.objects.filter(is_active=True).order_by("name")
    addon_lines = []
    for addon in addons:
        features = [f.strip() for f in (addon.feature_list() or []) if f.strip()]
        feature_text = ", ".join(features[:5]) if features else "No features listed"
        solo_price = (
            _format_money(addon.solo_price) if addon.solo_price is not None else "N/A"
        )
        addon_lines.append(
            f"- {addon.name}: with package {_format_money(addon.price)} | Solo: {solo_price} | Features: {feature_text}"
        )
    if addon_lines:
        chunks.append(
            _make_chunk(
                "Add-On Catalog",
                "Active add-ons:\n" + "\n".join(addon_lines),
                tags={"pricing", "booking", "addon"},
                priority=1.6,
            )
        )

    additionals = AdditionalOnly.objects.filter(is_active=True).order_by("name")
    additional_lines = []
    for item in additionals:
        features = [f.strip() for f in (item.feature_list() or []) if f.strip()]
        feature_text = ", ".join(features[:4]) if features else "No features listed"
        notes = _short_text(item.notes, 110) if item.notes else ""
        line = f"- {item.name}: {_format_money(item.price)} | Features: {feature_text}"
        if notes:
            line += f" | Notes: {notes}"
        additional_lines.append(line)
    if additional_lines:
        chunks.append(
            _make_chunk(
                "Additional Items Catalog",
                "Active additional items:\n" + "\n".join(additional_lines),
                tags={"pricing", "booking", "additional"},
                priority=1.4,
            )
        )

    service_charge = ServiceChargeConfig.objects.first()
    gcash = GCashConfig.objects.first()
    paymongo_enabled = bool(getattr(settings, "PAYMONGO_SECRET_KEY", ""))
    payment_content_lines = [
        "Customer checkout method currently enabled: GCash only.",
        "Checkout form submits payment_method='gcash' and backend allowed methods are restricted to {'gcash'}.",
        (
            "PayMongo integration is enabled in settings, so customers pay through GCash via PayMongo checkout."
            if paymongo_enabled
            else "PayMongo integration is not configured. Customer online checkout is currently unavailable until PAYMONGO_SECRET_KEY is set."
        ),
        "Initial payment options: downpayment or full payment. After an initial verified payment, only balance payment is accepted.",
        f"Payment verification states: {_status_line(Payment.PAYMENT_STATUS_CHOICES)}.",
        "Do not claim card, PayPal, or GrabPay as currently available customer checkout methods unless backend checkout config changes.",
    ]
    if service_charge:
        payment_content_lines.append(
            f"Default service/logistics fee config: {_format_money(service_charge.amount)}. Notes: {_safe_text(service_charge.notes)}."
        )
    if gcash:
        payment_content_lines.append(
            f"Configured downpayment percentage: {gcash.downpayment_percent}%. GCash number/name may be configured in admin panel."
        )
    chunks.append(
        _make_chunk(
            "Payment Configuration and Rules",
            "\n".join(payment_content_lines),
            tags={"payment", "pricing", "booking"},
            priority=1.5,
        )
    )

    return chunks


def _build_content_chunks():
    chunks = []
    footer_contact_chunk = _load_footer_contact_chunk()
    if footer_contact_chunk:
        chunks.append(footer_contact_chunk)

    services = Service.objects.filter(is_active=True).order_by("display_order", "id")
    service_lines = []
    for service in services[:20]:
        title = _safe_text(service.title)
        description = _short_text(service.description, 140)
        service_lines.append(f"- {title}: {description}")
    if service_lines:
        chunks.append(
            _make_chunk(
                "Service Offerings",
                "Active service items:\n" + "\n".join(service_lines),
                tags={"feature", "system", "booking"},
                priority=1.2,
            )
        )

    home_content = HomeContent.objects.first()
    service_content = ServiceContent.objects.first()
    about_content = AboutContent.objects.first()

    overview_parts = []
    if home_content:
        overview_parts.append(
            f"Home hero title: {_safe_text(home_content.hero_title)}. "
            f"Subheadline: {_short_text(home_content.hero_subheadline, 200)}."
        )
        features = HomeFeatureItem.objects.filter(is_active=True).order_by("display_order")
        feature_titles = [f.title.strip() for f in features[:8] if f.title.strip()]
        if feature_titles:
            overview_parts.append(
                "Home feature highlights: " + ", ".join(feature_titles) + "."
            )

    if service_content:
        overview_parts.append(
            f"Services page hero: {_safe_text(service_content.hero_title)}. "
            f"Subtitle: {_short_text(service_content.hero_subtitle, 200)}."
        )

    if about_content:
        overview_parts.append(
            f"About hero: {_safe_text(about_content.hero_title)}. "
            f"Story title: {_safe_text(about_content.story_title)}. "
            f"Mission title: {_safe_text(about_content.mission_title)}."
        )
        values = AboutValueItem.objects.filter(is_active=True).order_by("display_order")
        value_titles = [v.title.strip() for v in values[:8] if v.title.strip()]
        if value_titles:
            overview_parts.append("About values: " + ", ".join(value_titles) + ".")

    if overview_parts:
        chunks.append(
            _make_chunk(
                "Website Content Snapshot",
                " ".join(overview_parts),
                tags={"feature", "system", "account"},
                priority=1.0,
            )
        )

    return chunks


def _build_platform_stats_chunk():
    booking_total = Booking.objects.count()
    pending_count = Booking.objects.filter(status="pending").count()
    pending_payment_count = Booking.objects.filter(status="pending_payment").count()
    confirmed_count = Booking.objects.filter(status="confirmed").count()
    completed_count = Booking.objects.filter(status="completed").count()

    review_agg = Review.objects.aggregate(avg=Avg("rating"), total=Count("id"))
    avg_rating = review_agg.get("avg") or 0
    review_total = review_agg.get("total") or 0

    gallery_categories = GalleryCategory.objects.count()
    gallery_images = GalleryImage.objects.filter(is_active=True).count()
    canvas_categories = CanvasCategory.objects.filter(is_active=True).count()
    canvas_assets = CanvasAsset.objects.filter(is_active=True).count()

    stat_lines = [
        f"Bookings total: {booking_total} | pending: {pending_count} | pending_payment: {pending_payment_count} | confirmed: {confirmed_count} | completed: {completed_count}.",
        f"Reviews total: {review_total} | average rating: {avg_rating:.2f}.",
        f"Gallery: {gallery_categories} categories, {gallery_images} active images.",
        f"Design canvas: {canvas_categories} active categories, {canvas_assets} active assets.",
    ]

    return _make_chunk(
        "System Inventory Snapshot",
        "\n".join(stat_lines),
        tags={"system", "feature", "admin", "design"},
        priority=1.1,
    )


def _build_user_chunk(user):
    if not user or not getattr(user, "is_authenticated", False):
        return None

    bookings_qs = Booking.objects.filter(user=user).order_by("-created_at")
    status_rows = (
        bookings_qs.values("status").annotate(total=Count("id")).order_by("-total")
    )
    status_summary = (
        ", ".join(f"{row['status']}={row['total']}" for row in status_rows)
        if status_rows
        else "No bookings yet"
    )

    upcoming = (
        bookings_qs.filter(event_date__gte=timezone.localdate())
        .order_by("event_date", "event_time")[:5]
    )
    upcoming_lines = []
    for booking in upcoming:
        event_time = booking.event_time.strftime("%H:%M") if booking.event_time else "TBD"
        event_type = booking.event_type or "Event"
        upcoming_lines.append(
            f"- Booking #{booking.id}: {event_type} on {booking.event_date.isoformat()} {event_time} | status={booking.status} | payment={booking.payment_status} | total={_format_money(booking.total_price)}"
        )
    if not upcoming_lines:
        upcoming_lines.append("- No upcoming bookings found.")

    user_payments = Payment.objects.filter(booking__user=user)
    verified_total = user_payments.filter(payment_status="verified").aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")
    pending_payments = user_payments.filter(payment_status="pending").count()
    rejected_payments = user_payments.filter(payment_status="rejected").count()

    unread_notifications = Notification.objects.filter(user=user, is_read=False).count()
    open_concerns = ConcernTicket.objects.filter(user=user).exclude(
        status="resolved"
    ).count()
    designs_count = UserDesign.objects.filter(user=user).count()
    reviews_count = Review.objects.filter(user=user).count()

    display_name = user.get_full_name().strip() if user.get_full_name() else user.username
    user_lines = [
        f"Current user: {display_name} (role={user.role}).",
        f"Your booking summary: total={bookings_qs.count()} | {status_summary}.",
        f"Your payment summary: verified_total={_format_money(verified_total)} | pending={pending_payments} | rejected={rejected_payments}.",
        f"Your unread notifications: {unread_notifications}.",
        f"Your open concern tickets: {open_concerns}.",
        f"Your saved canvas designs: {designs_count}. Your posted reviews: {reviews_count}.",
        "Upcoming bookings:",
        *upcoming_lines,
    ]

    return _make_chunk(
        "Current User Account Snapshot",
        "\n".join(user_lines),
        tags={"account", "booking", "payment", "notification", "system"},
        priority=2.0,
        always=True,
    )


def _build_knowledge_chunks(user=None):
    chunks = []
    chunks.extend(_build_core_chunks())
    chunks.extend(_build_catalog_chunks())
    chunks.extend(_build_content_chunks())
    chunks.append(_build_platform_stats_chunk())
    if _env_truthy(os.getenv("AI_INCLUDE_REFERENCE_DOCS")):
        chunks.extend(_load_reference_doc_chunks())

    user_chunk = _build_user_chunk(user)
    if user_chunk:
        chunks.append(user_chunk)

    return [chunk for chunk in chunks if chunk and _safe_text(chunk["content"])]


def _score_chunk(chunk, query_tokens, intents):
    token_set = set(query_tokens)
    overlap = len(token_set & chunk["search_tokens"])

    score = chunk["priority"] + (overlap * 1.6)
    if chunk["always"]:
        score += 2.5

    intent_overlap = intents & chunk["tags"]
    if intent_overlap:
        score += len(intent_overlap) * 1.3
    elif intents and not chunk["always"]:
        score -= 0.2

    return score, overlap


def _select_context_chunks(chunks, query_text):
    query_tokens = _tokenize(query_text)
    intents = _derive_intents(query_tokens)

    scored = []
    for chunk in chunks:
        score, overlap = _score_chunk(chunk, query_tokens, intents)
        scored.append((score, overlap, chunk))

    scored.sort(
        key=lambda item: (item[0], item[1], item[2]["priority"]),
        reverse=True,
    )

    selected = []
    char_count = 0
    selected_ids = set()

    def can_add(chunk):
        nonlocal char_count
        entry = f"{chunk['title']}\n{chunk['content']}\n"
        projected = char_count + len(entry)
        if projected > MAX_CONTEXT_CHARS and selected:
            return False
        char_count = projected
        return True

    for chunk in chunks:
        if not chunk["always"]:
            continue
        chunk_id = id(chunk)
        if chunk_id in selected_ids:
            continue
        if can_add(chunk):
            selected.append(chunk)
            selected_ids.add(chunk_id)

    for _, _, chunk in scored:
        if len(selected) >= MAX_CONTEXT_CHUNKS:
            break
        chunk_id = id(chunk)
        if chunk_id in selected_ids:
            continue
        if can_add(chunk):
            selected.append(chunk)
            selected_ids.add(chunk_id)

    if not selected and scored:
        selected.append(scored[0][2])

    return selected


def get_system_context(user_message="", conversation_history=None, user=None):
    """
    Build a focused system snapshot so the model can answer from live app data.
    """
    try:
        chunks = _build_knowledge_chunks(user=user)
        history_hint = _recent_user_history_text(conversation_history)
        query_text = f"{user_message or ''} {history_hint}".strip()
        selected = _select_context_chunks(chunks, query_text)

        generated_at = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S %Z")
        lines = [f"SYSTEM KNOWLEDGE SNAPSHOT (generated {generated_at})"]
        for index, chunk in enumerate(selected, start=1):
            lines.append(f"{index}. {chunk['title']}\n{chunk['content']}")
        return "\n\n".join(lines)
    except Exception as e:
        print(f"Error building system context: {e}")
        return (
            "SYSTEM KNOWLEDGE SNAPSHOT unavailable. "
            "Only answer from known Balloorina flows and clearly state uncertainty."
        )


def get_chatbot_response(user_message, conversation_history=None, user=None):
    """
    Sends a message to Hugging Face.
    Uses profanity filtering, retrieval-based context, and optional image generation.
    """
    try:
        moderation_result = evaluate_chat_moderation(user, user_message)
        if moderation_result is not None:
            return moderation_result

        if InferenceClient is None:
            print("Error: huggingface_hub library is not installed.")
            return _chat_response_payload(
                "System Error: AI library missing. Please install huggingface_hub.",
            )

        api_key = getattr(settings, "HUGGINGFACE_API_KEY", "")
        if not api_key:
            print("Error: HUGGINGFACE_API_KEY is not set in settings.py/.env")
            return _chat_response_payload("Configuration Error: API key missing.")

        with _without_dead_local_proxy():
            client = InferenceClient(token=api_key)
        model_id = getattr(settings, "HUGGINGFACE_MODEL_ID", "Qwen/Qwen2.5-72B-Instruct")
        image_followup_triggered = _is_image_followup_request(
            user_message,
            conversation_history,
        )
        image_triggered = is_image_request(user_message) or image_followup_triggered

        if image_triggered:
            image_context = _recent_image_request_context(
                conversation_history,
                include_last_prompt=image_followup_triggered,
            )
            img_prompt = build_image_generation_prompt(user_message, image_context)
            image_model = getattr(
                settings,
                "HUGGINGFACE_IMAGE_MODEL_ID",
                "stabilityai/stable-diffusion-xl-base-1.0",
            )
            try:
                with _without_dead_local_proxy():
                    generated_image = client.text_to_image(
                        prompt=img_prompt,
                        negative_prompt=build_image_negative_prompt(f"{image_context} {user_message}"),
                        model=image_model,
                    )

                img_url = _save_generated_image(generated_image)
                return _chat_response_payload(_image_success_reply(img_url, img_prompt))
            except Exception as image_error:
                print(f"Image Generation Error: {image_error}")
                return _chat_response_payload(
                    _image_unavailable_reply(
                        img_prompt,
                        error_message=str(image_error),
                    )
                )

        base_prompt = (
            "You are the official AI assistant of Balloorina, a balloon decoration and event styling company in the Philippines. "
            "Answer ONLY using the SYSTEM KNOWLEDGE SNAPSHOT and the conversation history. "
            "You can answer questions about services, pricing, booking flow, payment rules, platform features, and the current user's own account details when present in the snapshot. "
            "For contact details (email, phone, social links, location, business hours), use ONLY the 'Footer Contact Information' section from the snapshot. "
            "Never invent contact details or social handles. "
            "For payment methods, list ONLY methods explicitly marked as currently enabled for customer checkout in the snapshot. "
            "Never list disabled, legacy, or assumed payment methods. "
            "For booking process questions, give step-by-step instructions that match runtime behavior in the snapshot. "
            "If any previous assistant message conflicts with the snapshot, treat that old message as outdated and correct it. "
            "If details are missing in the snapshot, say it clearly and suggest checking the relevant page in the app. "
            "Do not invent prices, statuses, dates, or policies. "
            "Keep responses concise, direct, and friendly, but complete. "
            "Mirror the user's language. If the user writes in Filipino or Taglish, answer in natural friendly Taglish with simple words. "
            "Avoid stiff corporate English when the user is casual. "
            "Do NOT use markdown headings with #, ##, or ###. "
            "Prefer plain text and simple readable structure. Avoid unnecessary markdown decorations. "
            "When giving procedures, use clean labels like 'Step 1:', 'Step 2:' with short clear lines. "
            "For booking procedure specifically, always start from the calendar step first. "
            "Answer clearly so the user understands on first read. "
            "If user asks unrelated general-knowledge topics, politely redirect to Balloorina system questions."
        )

        system_context = get_system_context(
            user_message=user_message,
            conversation_history=conversation_history,
            user=user,
        )
        system_prompt = f"{base_prompt}\n\n{system_context}"

        messages = [{"role": "system", "content": system_prompt}]

        if conversation_history:
            for msg in conversation_history:
                role = msg.get("role")
                content = msg.get("content")
                if content and role in {"user", "assistant"}:
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_message})

        with _without_dead_local_proxy():
            response = client.chat_completion(
                messages=messages,
                model=model_id,
                max_tokens=720,
                temperature=0.6,
            )
        choice = response.choices[0]
        reply_text = (choice.message.content or "").strip()
        finish_reason = str(getattr(choice, "finish_reason", "") or "").lower()

        if not image_triggered and (finish_reason == "length" or _looks_truncated(reply_text)):
            continuation_messages = messages + [
                {"role": "assistant", "content": reply_text},
                {
                    "role": "user",
                    "content": (
                        "Continue from where you stopped. Do not repeat previous lines. "
                        "No markdown headings. Keep it clear and complete."
                    ),
                },
            ]
            with _without_dead_local_proxy():
                continuation = client.chat_completion(
                    messages=continuation_messages,
                    model=model_id,
                    max_tokens=360,
                    temperature=0.4,
                )
            cont_text = (continuation.choices[0].message.content or "").strip()
            if cont_text:
                reply_text = f"{reply_text}\n{cont_text}".strip()

        prompt_text, intro_text, outro_text = _extract_image_prompt_block(reply_text)
        if prompt_text:
            reply_text = f"{intro_text} {outro_text}".strip()

        return _chat_response_payload(_normalize_reply_text(reply_text))

    except Exception as e:
        print(f"Hugging Face Error: {e}")
        error_text = str(e).lower()
        if "402" in error_text or "depleted your monthly included credits" in error_text:
            return _chat_response_payload(
                (
                    "Your AI provider quota is currently exhausted (Hugging Face credits reached). "
                    "Please add credits or upgrade your Hugging Face plan, then try again."
                )
            )
        if "401" in error_text or "unauthorized" in error_text:
            return _chat_response_payload(
                "AI authentication failed. Please verify your HUGGINGFACE_API_KEY in .env."
            )
        return _chat_response_payload(
            "I'm sorry, I'm having trouble connecting to my service right now. Please try again later."
        )
