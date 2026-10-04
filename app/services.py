import base64
import hashlib
import hmac
import io
import logging
import os
import random
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
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Avg, Count, Sum
from django.utils import timezone

from .models import (
    AboutContent,
    AboutValueItem,
    AdditionalOnly,
    AddOn,
    BlockedDate,
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
BAN_DURATION_MINUTES = 10
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
        "One more violation will result in a temporary 10-minute ban."
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
    - 10-minute ban at 3rd violation
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

        # Third strike inside the active window triggers an automatic 10-minute ban.
        if new_strike_count >= MAX_STRIKES_BEFORE_BAN:
            state.banned_until = now + timedelta(minutes=BAN_DURATION_MINUTES)
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

    # Pricing/procedural questions must be answered as text even when they
    # mention visual words (e.g. "magkano ang themed backdrop niyo?" is a
    # pricing question, not an image request).
    question_guards = (
        "magkano",
        "how much",
        "price",
        "presyo",
        "paano",
        "how to",
        "how do",
        "how can",
        "what time",
        "schedule",
        "saan",
        "where",
    )
    explicit_media_words = (
        "picture",
        "image",
        "photo",
        "drawing",
        "illustration",
        "generate",
        "draw me",
        "pakita",
        "patingin",
    )
    if any(g in lowered for g in question_guards) and not any(
        m in lowered for m in explicit_media_words
    ):
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
        "patingin",
        "sample",
        "peg",
        "idea",
        "suggest",
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
        "layout",
        "styling",
        "decoration",
    }

    has_request_verb = any(term in lowered for term in request_verbs)
    # A recognized character/franchise theme (spiderman, unicorn, ...) counts
    # as a visual term too — "gawa ka ng spiderman" is a design request even
    # without an explicit design word.
    has_visual_term = any(term in lowered for term in visual_terms) or bool(
        _detect_image_theme(lowered)
    )
    if has_request_verb and has_visual_term:
        return True

    # Theme-only phrasing ("birthday theme pink and gold", "wedding concept
    # blue and silver") describes a design without an explicit request verb —
    # treat it as an image request so the user never gets a text-only reply.
    if has_visual_term and _has_design_theme_context(lowered):
        return True

    # Bare theme descriptions ("kasal na may ginto at puti") have no design
    # word at all, but naming BOTH an event type and a color palette is a
    # strong enough signal that the user wants a design concept.
    if _has_event_and_color_context(lowered):
        return True

    # Check for "generate ka pa" or similar without explicit visual terms
    if any(verb in lowered for verb in ["generate", "gawa", "create", "make"]) and any(suffix in lowered for suffix in ["pa", "more", "ulit", "another"]):
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
            "suggest design",
            "suggest a design",
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

    # Pricing/procedural follow-ups ("magkano pa?", "how much more?") must not
    # be mistaken for image regeneration requests.
    if any(
        g in lowered
        for g in ("magkano", "how much", "price", "presyo", "paano", "how to")
    ):
        return False

    followup_terms = {
        "again",
        "regenerate",
        "retry",
        "another",
        "another one",
        "more",
        "one more",
        "next",
        "sunod",
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
        "same theme",
        "same prompt",
        "example",
        "sample",
        "peg",
        "idea",
        "ganyan",
        "pangalawa",
        "pangatlo",
        "pang-2",
        "pang 2",
        "pang-ilan",
        "pang ilan",
    }
    if any(term in lowered for term in followup_terms):
        return True

    taglish_followup_patterns = [
        r"^\s*(generate|gawa|gumawa|igawa|create|make)\b.*\bpa\b",
        r"^\s*(generate|gawa|gumawa|igawa|create|make)\b.*kapa\b",
        r"^\s*(isa|one)\s+pa\b",
        r"^\s*(sunod|next)\b",
        r"\b(one|isa)\s+more\b",
        r"\b(example|sample|peg)\b",
        r"\b(second|third|fourth|fifth|2nd|3rd|4th|5th)\b",
        r"\b(pang|ika)[-\s]?(2|3|4|5|dalawa|tatlo|apat|lima|anim|pito|walo|siyam|sampu|ilan)\b",
        r"\b(ulit|ulitin|ibang version|other version|another version)\b",
        r"\b(lagyan|dagdagan)\b.*\b(arch|flowers?|florals?|balloons?|ilaw|lights?)\b",
        r"\b(alisin|tanggalin|remove)\b.*\b(arch|flowers?|florals?|balloons?|ilaw|lights?)\b",
    ]
    return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in taglish_followup_patterns)


def _asks_for_new_image_variant(text):
    lowered = (text or "").lower()
    variant_terms = (
        "again",
        "regenerate",
        "another",
        "another one",
        "one more",
        "next",
        "sunod",
        "new",
        "new one",
        "other version",
        "ibang version",
        "pangalawa",
        "pangatlo",
        "pang ilan",
        "pang-ilan",
        "example",
        "sample",
        "peg",
    )
    return any(term in lowered for term in variant_terms)


def _is_retryable_image_error(error_message):
    lowered = (error_message or "").lower()
    retryable_markers = (
        "503",
        "timeout",
        "timed out",
        "temporarily unavailable",
        "temporarily overloaded",
        "model is currently loading",
        "try again",
        "connection reset",
        "connection aborted",
        "inference timeout",
    )
    return any(marker in lowered for marker in retryable_markers)


def _is_prompt_limit_image_error(error_message):
    lowered = (error_message or "").lower()
    limit_markers = (
        "413",
        "422",
        "payload too large",
        "too long",
        "prompt is too long",
        "max length",
        "maximum context length",
        "input too long",
    )
    return any(marker in lowered for marker in limit_markers)


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
    r"\b(generate|create|make|draw|show me|pakita|suggest)\b",
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

# Character/character-franchise theme library: maps popular client themes to
# rich visual descriptors + a default palette so the image model actually
# renders the requested theme (Spiderman, unicorn, jungle safari, ...) instead
# of collapsing into the same generic luxury balloon backdrop every time.
# Motifs are described generically ("web pattern", not brand logos) so the
# negative prompt's "logo, brand mark" suppression does not fight the theme.
# Order matters: more specific themes are checked before generic ones.
IMAGE_THEME_LIBRARY = {
    "spiderman": {
        "aliases": (
            "spiderman", "spider man", "spider-man", "spiderman theme",
        ),
        "look": (
            "bold superhero spider theme backdrop, red and royal blue balloons with "
            "black spider web pattern accents, comic book action burst cutouts, "
            "city skyline silhouette backdrop panel, web-draped balloon clusters"
        ),
        "palette": "bold red, royal blue and black",
    },
    "superhero": {
        "aliases": (
            "superhero", "super hero", "marvel", "avengers", "batman", "superman",
            "iron man", "captain america", "hulk", "hero theme",
        ),
        "look": (
            "comic book superhero theme backdrop, action burst cutouts, city skyline "
            "silhouette panels, lightning bolt and shield shaped accents, dynamic "
            "pow-style star bursts among the balloons"
        ),
        "palette": "bold red, blue and yellow accents",
    },
    "princess": {
        "aliases": (
            "princess", "prinsesa", "reyna", "tiara", "royal ball", "castle theme",
            "cinderella",
        ),
        "look": (
            "royal princess theme backdrop, castle silhouette backdrop panel, golden "
            "crown and tiara accents, satin drape swags, carriage cutout, pearl and "
            "glitter details, ornate gilded frames"
        ),
        "palette": "soft pink, lavender and gold",
    },
    "unicorn": {
        "aliases": ("unicorn", "rainbow unicorn", "pony theme"),
        "look": (
            "magical pastel unicorn theme backdrop, rainbow mane balloon garland "
            "accents, golden horn cutout, fluffy cloud props, shooting star accents, "
            "glitter and iridescent finish"
        ),
        "palette": "pastel rainbow with white and gold",
    },
    "jungle_safari": {
        "aliases": (
            "jungle", "safari", "zoo theme", "wild animals", "lion king",
            "king of the jungle",
        ),
        "look": (
            "lush jungle safari theme backdrop, tropical palm and monstera leaves, "
            "leopard and zebra print pattern accents, animal silhouette standees, "
            "wooden crate and explorer net props, vine garlands"
        ),
        "palette": "safari green, khaki and warm orange",
    },
    "dinosaur": {
        "aliases": (
            "dinosaur", "dino theme", "trex", "t-rex", "jurassic", "dinos",
        ),
        "look": (
            "prehistoric dinosaur theme backdrop, volcano backdrop cutout, dinosaur "
            "silhouette standees, tropical fern plants, cracked egg props, rocky "
            "terrain accents, foot print decals"
        ),
        "palette": "leaf green, earth brown and volcano orange",
    },
    "space_galaxy": {
        "aliases": (
            "space", "outer space", "galaxy", "astronaut", "rocket", "planet theme",
            "solar system", "milky way", "cosmos",
        ),
        "look": (
            "deep space galaxy theme backdrop, dark nebula backdrop panel, glowing "
            "star accents, rocket ship cutout, astronaut and planet props, dangling "
            "planet lanterns, LED star lights"
        ),
        "palette": "deep navy, purple nebula and silver",
    },
    "under_the_sea": {
        "aliases": (
            "mermaid", "under the sea", "undersea", "little mermaid", "ocean theme",
            "sea creatures", "seashell theme",
        ),
        "look": (
            "underwater mermaid theme backdrop, seashell and pearl accents, fish and "
            "coral cutouts, iridescent scale pattern panels, bubble balloon garlands, "
            "flowing teal tulle like water, treasure chest prop"
        ),
        "palette": "aqua teal, coral pink and pearl white",
    },
    "frozen_winter": {
        "aliases": (
            "frozen", "elsa", "winter wonderland", "snowflake", "snow theme",
            "winter theme",
        ),
        "look": (
            "icy winter wonderland theme backdrop, sparkling snowflake accents, "
            "frosted crystal balloon garlands, shimmering ice covered backdrop "
            "panels, white faux snow base, cool glitter finish"
        ),
        "palette": "ice blue, white and silver",
    },
    "racing_cars": {
        "aliases": (
            "race car", "racing", "hot wheels", "mcqueen", "lightning mcqueen",
            "race track", "cars theme",
        ),
        "look": (
            "high energy racing theme backdrop, checkered flag pattern accents, race "
            "track road backdrop panel, tire stack props, trophy and finish line "
            "cutouts, speed stripe details"
        ),
        "palette": "racing red, black and checkered white",
    },
    "basketball": {
        "aliases": (
            "basketball", "nba theme", "sports theme", "hoops theme",
        ),
        "look": (
            "sports arena basketball theme backdrop, basketball hoop cutout, court "
            "floor graphic backdrop panel, jersey number standees, trophy props, "
            "orange basketball garland accents"
        ),
        "palette": "orange, black and white",
    },
    "enchanted_garden": {
        "aliases": (
            "garden", "enchanted garden", "fairy garden", "floral theme",
            "flowers theme", "botanical",
        ),
        "look": (
            "enchanted garden theme backdrop, lush greenery walls, oversized blooming "
            "paper flowers, butterfly accents, vine wrapped panels, warm fairy "
            "lights, rustic wooden accents"
        ),
        "palette": "blush pink, sage green and cream",
    },
    "twinkle_star": {
        "aliases": (
            "twinkle", "twinkle twinkle", "moon and stars", "star theme",
            "celestial", "moon theme",
        ),
        "look": (
            "celestial twinkle theme backdrop, giant crescent moon centerpiece "
            "panel, scattered glowing star accents, dangling star garlands, soft "
            "cloud props, warm shimmering glow"
        ),
        "palette": "midnight navy, gold and white",
    },
    "teddy_bear": {
        "aliases": ("teddy", "teddy bear", "bear theme"),
        "look": (
            "cute teddy bear theme backdrop, plush bear props, honey pot accents, "
            "soft burlap and gingham textures, wooden name blocks, cozy cloud "
            "balloon clusters"
        ),
        "palette": "warm brown, cream and soft beige",
    },
    "wizard_magic": {
        "aliases": (
            "harry potter", "wizard", "magic theme", "hogwarts", "sorcerer",
            "wizard school",
        ),
        "look": (
            "mystical wizard magic theme backdrop, spell book and potion bottle "
            "props, golden star sparkles, floating candle lights, castle silhouette "
            "backdrop panel, vintage parchment banners"
        ),
        "palette": "deep purple, midnight blue and antique gold",
    },
    "rainbow": {
        "aliases": ("rainbow", "rainbow theme"),
        "look": (
            "cheerful rainbow theme backdrop, layered rainbow arch of balloons, "
            "fluffy cloud props, smiling sun cutout, pastel multicolor garlands, "
            "confetti accents"
        ),
        "palette": "full pastel rainbow spectrum",
    },
    "nautical_sailor": {
        "aliases": (
            "sailor", "nautical", "anchor theme", "ship theme", "boat theme",
        ),
        "look": (
            "nautical sailor theme backdrop, navy and white stripe pattern accents, "
            "anchor cutouts, rope and life ring props, paper boat accents, "
            "helm wheel decor"
        ),
        "palette": "navy, white and rope tan",
    },
    "cowboy_western": {
        "aliases": (
            "cowboy", "western", "rodeo", "farm theme", "wild west",
        ),
        "look": (
            "rustic cowboy western theme backdrop, hay bale and wooden crate props, "
            "bandana pattern accents, cowboy hat props, star sheriff cutouts, warm "
            "barn wood backdrop panel"
        ),
        "palette": "warm earth brown, denim blue and barn red",
    },
    "cocomelon": {
        "aliases": ("cocomelon", "nursery rhymes theme"),
        "look": (
            "playful nursery cartoon theme backdrop, cheerful watermelon slice "
            "cutouts, bright primary color balloons, cute musical note accents, "
            "rainbow and cloud props, playful rounded panels"
        ),
        "palette": "bright red, green, blue and yellow",
    },
}


def _detect_image_theme(text):
    """Return the matched theme library key for the text, or "" if none.

    Keyword matching over the theme library (English + common Taglish words),
    using word boundaries so short aliases never match inside longer words.
    """
    lowered = (text or "").lower()
    if not lowered.strip():
        return ""
    for theme_key, theme_data in IMAGE_THEME_LIBRARY.items():
        for alias in theme_data["aliases"]:
            if re.search(rf"\b{re.escape(alias.lower())}\b", lowered):
                return theme_key
    return ""


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
    # Collect matches with their position so colors come out in the order the
    # user actually said them ("pink and gold" -> "pink, gold"), instead of
    # arbitrary set-iteration order that made prompts nondeterministic.
    found = {}
    for color in IMAGE_COLOR_WORDS:
        match = re.search(rf"\b{re.escape(color)}\b", lowered)
        if match:
            found[match.start()] = color
    for alias, color in IMAGE_COLOR_ALIASES.items():
        match = re.search(rf"\b{re.escape(alias)}\b", lowered)
        if match:
            found[match.start()] = color
    if found:
        ordered = [found[pos] for pos in sorted(found)]
        return ", ".join(list(dict.fromkeys(ordered))[:4])
    return "coordinated theme colors"


def _mentions_event_type(text):
    lowered = (text or "").lower()
    return any(
        hint in lowered
        for hints in IMAGE_EVENT_HINTS.values()
        for hint in hints
    )


def _mentions_theme_color(text):
    lowered = (text or "").lower()
    if any(re.search(rf"\b{re.escape(color)}\b", lowered) for color in IMAGE_COLOR_WORDS):
        return True
    return any(re.search(rf"\b{re.escape(alias)}\b", lowered) for alias in IMAGE_COLOR_ALIASES)


def _has_design_theme_context(text):
    """True when the text names a concrete event type or color palette.

    Used to catch theme-only design requests like "birthday theme pink and
    gold" that lack an explicit request verb ("gawa", "generate", etc.) but
    clearly describe a design the user wants to see.
    """
    lowered = (text or "").lower()
    return _mentions_event_type(lowered) or _mentions_theme_color(lowered)


def _has_event_and_color_context(text):
    """True when the text names BOTH an event type and a color palette.

    Stronger signal than _has_design_theme_context: used to catch bare
    theme descriptions like "kasal na may ginto at puti" that have no
    design/backdrop word at all.
    """
    lowered = (text or "").lower()
    return _mentions_event_type(lowered) and _mentions_theme_color(lowered)


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


# Randomized composition blueprints: even an identical request now produces a
# visibly different design each generation instead of near-duplicates.
IMAGE_COMPOSITION_VARIATIONS = (
    "asymmetric arrangement with the tallest backdrop panel offset to the left and a cascading balloon garland sweeping from the top left down to the bottom right",
    "symmetrical arrangement with one large round central panel flanked by two smaller hexagon panels and mirrored garlands on both sides",
    "layered trio of tall rectangular panels at the center with a lush garland hugging both bottom corners of the setup",
    "oversized circular panel placed slightly right of center with floating balloons drifting upward along the left side",
    "wide layered panel wall with a scalloped garland draped across the top edge and dense balloon clusters at both base corners",
    "two tall organic-shaped panels side by side with a low flower bed in front and balloons rising between them",
    "single towering round panel with a spiral garland winding around its frame from base to top",
    "stepped arrangement of three round panels in descending sizes with balloon sprays bursting from behind each panel",
    "arched curtain frame with balloons hugging only the outer edges and a wide open center for the focal prop",
    "diagonal flow arrangement with the garland entering from the top right and pooling at the bottom left corner",
)

# Randomized focal-point options: keeps the center of the design different
# from one generation to the next (chair, no furniture, plinths, etc.).
IMAGE_FOCAL_VARIATIONS = (
    "plush accent chair centered in front as the only central furniture",
    "elegant throne chair placed slightly off-center with a tall floral pedestal beside it",
    "no furniture at all, an open foreground with a moss carpet and loose flower petals",
    "small round cake table tucked far to the side corner with the center left open for photos",
    "a pair of slim pedestal plinths with floral bouquets at both sides and an open center",
    "a low seabed of mixed balloon bubbles across the floor with no furniture",
)

# Randomized decor emphasis: changes which decorations dominate the design so
# two generations of the same request visibly differ in styling.
IMAGE_DECOR_EMPHASIS_VARIATIONS = (
    "abundant giant paper flowers and lush mixed fresh florals as the dominant decoration",
    "extra dense balloon clusters and floating balloon accents as the dominant decoration with only a few florals",
    "cascading greenery and leafy vines as the dominant decoration accented with white blooms",
    "flowing fabric drapes and satin ribbon accents with fairy light strands as the dominant decoration",
    "themed standees and cutout props flanking the backdrop as the dominant decoration",
    "hanging crystal bead strands, fairy lights and Edison bulbs as the dominant decoration",
)

# Randomized lighting mood for further visual separation between generations.
IMAGE_LIGHTING_VARIATIONS = (
    "warm golden uplighting",
    "soft neutral white spotlighting",
    "romantic warm fairy-light glow",
    "bright clean daylight venue lighting",
    "cozy amber evening lighting",
)

# Randomized backdrop STRUCTURE: the physical shape of the setup itself changes
# per generation (previously this core structure was a fixed sentence, which is
# why every generation looked like the same backdrop with different accents).
IMAGE_STRUCTURE_VARIATIONS = (
    "tall round backdrop panels layered at different heights as the main structure",
    "rectangular standee backdrop panels arranged in a stepped trio",
    "hexagon backdrop panels clustered at the center with open airy sides",
    "soft fabric curtain wall with one grand circular center panel",
    "organic free-form backdrop shapes with wavy sculpted edges",
    "arched backdrop frame with a tall narrow center panel",
)

# Randomized garland styling: how the balloons flow across the structure.
IMAGE_GARLAND_VARIATIONS = (
    "organic balloon garland with mixed balloon sizes flowing asymmetrically",
    "tight clustered balloon garland with metallic chrome balloon pops",
    "spiral balloon garland winding around the backdrop frame",
    "cascading balloon garland pooling lushly at the base corners",
    "floating balloon clusters rising like clouds with ribbon tails",
    "double garland lines crossing in an X pattern across the backdrop",
)

# Anti-repeat memory: last few variation signatures per request text, so
# regenerating the same request (or building a mood board of options) never
# produces the same combination twice in a row. In-memory only — single-server
# deployment, no persistence needed.
_RECENT_VARIATION_MEMORY = 6
_recent_variation_signatures = {}


def _roll_image_variations(anti_repeat_key, pinned_decor=None):
    """Pick one entry from every variation axis, avoiding recently used combos.

    anti_repeat_key keys the memory (normalized request text): repeated
    generation of the same request re-rolls a visibly different combination.
    pinned_decor (optional index) pins the decor axis — used by the mood board
    so each labeled option leans into a distinct dominant decoration.
    """
    memory = _recent_variation_signatures.setdefault(anti_repeat_key, [])
    combo = {}
    for _ in range(10):
        decor_pool = IMAGE_DECOR_EMPHASIS_VARIATIONS
        decor = (
            decor_pool[pinned_decor % len(decor_pool)]
            if pinned_decor is not None
            else random.choice(decor_pool)
        )
        combo = {
            "structure": random.choice(IMAGE_STRUCTURE_VARIATIONS),
            "composition": random.choice(IMAGE_COMPOSITION_VARIATIONS),
            "focal": random.choice(IMAGE_FOCAL_VARIATIONS),
            "decor": decor,
            "garland": random.choice(IMAGE_GARLAND_VARIATIONS),
            "lighting": random.choice(IMAGE_LIGHTING_VARIATIONS),
        }
        signature = (
            combo["structure"], combo["composition"], combo["focal"],
            combo["decor"], combo["garland"],
        )
        if signature not in memory:
            memory.append(signature)
            del memory[:-_RECENT_VARIATION_MEMORY]
            return combo
    # All 10 re-rolls collided (practically impossible with ~23k combos):
    # accept the last roll rather than fail generation.
    return combo


def build_image_generation_prompt(user_message, model_prompt=""):
    """
    Build a reliable SDXL prompt from the user's exact request.
    The optional model_prompt is treated as extra detail, never as the source of truth.
    """
    # Strip conversation context markers (Previous generated image prompt /
    # Recent user image instructions) so a previous prompt never leaks into
    # the new theme detection — leaking it made every regeneration look
    # almost identical to the last one.
    contextless_model_prompt = re.sub(
        r"Previous generated image prompt:.*?(?:Recent user image instructions:.*?$|$)",
        " ",
        model_prompt or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    source_text = f"{_safe_text(contextless_model_prompt)} {user_message}".strip()
    previous_prompt_match = re.search(
        r"Previous generated image prompt:\s*(.*?)(?:Recent user image instructions:|$)",
        model_prompt or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    previous_prompt = _safe_text(previous_prompt_match.group(1))[:800] if previous_prompt_match else ""
    requested_update = _clean_image_theme_text(user_message)
    theme_text = _clean_image_theme_text(source_text)
    event_type = _detect_image_event_type(source_text)
    # Character/franchise theme detection (Spiderman, unicorn, ...): when a
    # library theme matches, its descriptor block leads the prompt and its
    # palette becomes the default (explicit user colors still win).
    theme_key = _detect_image_theme(source_text)
    theme_entry = IMAGE_THEME_LIBRARY.get(theme_key) if theme_key else None
    user_theme_key = _detect_image_theme(_safe_text(user_message))
    colors = _detect_image_colors(source_text)
    has_explicit_colors = colors != "coordinated theme colors"
    palette = (
        colors
        if has_explicit_colors
        else (theme_entry["palette"] if theme_entry else "coordinated theme colors")
    )
    # Anti-repeat key: repeated generation of the same request (and each
    # mood-board option built from it) must re-roll a different combination.
    anti_repeat_key = (
        re.sub(r"\s+", " ", _safe_text(user_message)).lower().strip()[:120]
        or "default"
    )
    variation_combo = _roll_image_variations(anti_repeat_key)
    arch_direction = (
        "include a clear entrance arch only if it fits the requested theme"
        if _user_wants_arch(source_text)
        else "use balloon garlands, balloon clusters, cascading balloons, and organic side arrangements instead of a doorway arch"
    )
    # A brand-new design request (mentions its own event type or palette, or is
    # a full description) must NOT inherit the previous concept — only short
    # tweaks like "lagyan ng arch" keep the previous design as the base.
    user_text = _safe_text(user_message)
    is_fresh_theme_request = (
        _detect_image_event_type(user_text) != "celebration event"
        or _detect_image_colors(user_text) != "coordinated theme colors"
        or bool(user_theme_key)
        or len(user_text.split()) >= 8
    )
    preserve_previous = bool(previous_prompt) and not is_fresh_theme_request
    needs_new_variant = bool(previous_prompt) and (
        _asks_for_new_image_variant(user_message) or is_fresh_theme_request
    )

    prompt_parts = [
        "FRONT VIEW, eye-level, complete event backdrop design setup as the hero subject",
    ]
    if theme_entry:
        # Theme block leads the prompt: FLUX/SDXL weight the earliest tokens
        # heaviest, so the requested theme never gets drowned out again.
        prompt_parts.append(theme_entry["look"])
    prompt_parts.append(
        f"{event_type} styling, preserve this previous concept: {previous_prompt}"
        if preserve_previous
        else f"{event_type} backdrop design inspired by the theme: {theme_text}"
    )
    prompt_parts.append(f"requested update or new instruction: {requested_update}")
    prompt_parts.append(f"color palette: {palette}")
    # Structure + composition + focal + decor + garland + lighting all come
    # from the anti-repeat roller, so the setup shape itself changes every
    # generation instead of only the accents around one fixed backdrop.
    prompt_parts.append(variation_combo["structure"])
    prompt_parts.append(variation_combo["composition"])
    prompt_parts.append(f"focal point: {variation_combo['focal']}")
    prompt_parts.append(f"dominant decoration: {variation_combo['decor']}")
    prompt_parts.append(variation_combo["garland"])
    prompt_parts.append(variation_combo["lighting"])
    prompt_parts.append(arch_direction)
    prompt_parts.append(
        "richly decorated setup, full setup visible from floor to top, "
        "no cropped decorations, clean empty foreground"
    )
    prompt_parts.append(
        "photorealistic professional event styling portfolio photo, "
        "polished luxury finish, sharp focus"
    )

    if needs_new_variant:
        prompt_parts.append(
            "create a clearly different variation from the previous output: change layout flow, balloon grouping, focal arrangement, prop placement, and backdrop layering while keeping the same event theme"
        )

    prompt_parts.append(
        "wide event styling, high quality, detailed, vibrant colors"
    )
    return ", ".join(prompt_parts)


def build_image_negative_prompt(user_message):
    negative = (
        "low quality, blurry, distorted, deformed, bad anatomy, bad lighting, ugly, messy, "
        "watermark, logo, readable text, misspelled text, random letters, captions, cropped, "
        "out of frame, close-up, portrait crop, empty stage, plain background, duplicate people, "
        "plain, bare, sparse, minimal, undecorated, half-empty setup, "
        "large table in the center, big table, long table, table as the centerpiece, "
        "table in front of the backdrop, banquet setup, "
        "dining tables, banquet tables, table centerpieces, guests, people, crowd, "
        "ballroom interior, chandeliers, ceiling drapes, wide empty room, "
        "signature, typography, lettering, brand mark, brand name, stamp, photographer mark, "
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
    """Persist a generated image through Django's storage and return its URL.

    On production MediaCloudinaryStorage uploads the file to Cloudinary at
    save time, so the returned URL works on the deployed site (a plain
    "/media/..." path 404s there because no /media/ route is mounted when
    Cloudinary is configured). Locally FileSystemStorage keeps writing into
    MEDIA_ROOT/ai_generated/, whose /media/ URL the DEBUG route serves.
    """
    filename = f"design_{timezone.now().strftime('%Y%m%d%H%M%S%f')}_{uuid.uuid4().hex[:12]}.png"

    if isinstance(generated_image, (bytes, bytearray)):
        content = ContentFile(bytes(generated_image), name=filename)
    else:
        # PIL Image (InferenceClient.text_to_image) -- serialize to PNG
        # bytes in memory instead of touching the local filesystem.
        buffer = io.BytesIO()
        generated_image.save(buffer, format="PNG")
        content = ContentFile(buffer.getvalue(), name=filename)

    saved_name = default_storage.save(f"ai_generated/{filename}", content)
    img_url = default_storage.url(saved_name)
    if not img_url:
        raise ValueError("Generated image could not be resolved to a URL.")
    return img_url


def _image_success_reply(img_url, prompt, intro_text=""):
    intro = intro_text or "Here's the Balloorina design concept based on your request:"
    return (
        # NOTE: plain text lang dito — HINDI naka-escape. Ang frontend na
        # (formatMarkdown) ang nag-e-escape ng lahat ng HTML para sa XSS guard.
        # Kung i-e-escape dito, dobleng escape sa frontend (magiging literal
        # na "&#x27;" sa chat ang apostrophe).
        f"{intro}\n\n"
        f'<img src="{escape(img_url)}" alt="Balloorina Design Concept" '
        f'data-ai-prompt="{escape(prompt)}" '
        'style="max-width:100%; border-radius:8px; margin-top:6px;">'
    )


def _image_unavailable_reply(prompt, intro_text="", error_message=""):
    intro = (
        intro_text
        or "I've prepared the design prompt, but the image provider didn't return a usable image."
    )
    provider_hint = ""
    if error_message:
        error_lower = error_message.lower()
        if "402" in error_lower or "quota" in error_lower or "credits" in error_lower:
            provider_hint = (
                " The monthly AI image credits for this app's Hugging Face account are"
                " currently used up, so no image provider is available right now."
                " Image generation should work again once the credits reset next month"
                " (or if credits are added to the account)."
            )
        elif "401" in error_lower or "unauthorized" in error_lower:
            provider_hint = " The Hugging Face API key may be invalid or expired."
    return (
        f"{intro}{provider_hint}\n\n"
        "You can tap Try Again below, or pick a suggestion to continue."
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

# ── AI provider safety settings ──────────────────────────────────────────────
# Timeout (seconds) for HuggingFace calls — prevents hung requests from
# stalling Django worker threads and freezing the whole site.
AI_REQUEST_TIMEOUT = int(getattr(settings, "HUGGINGFACE_TIMEOUT", 90) or 90)
# Cache-based anti-spam throttles for image generation (protects HF credits).
AI_IMAGE_COOLDOWN_SECONDS = int(os.getenv("AI_IMAGE_COOLDOWN_SECONDS", "15"))
AI_IMAGE_DAILY_LIMIT = int(os.getenv("AI_IMAGE_DAILY_LIMIT", "30"))
# Public knowledge chunks (packages, content, stats) are DB-derived but rarely
# change, so cache them briefly instead of re-querying on every chat message.
KNOWLEDGE_CACHE_TTL_SECONDS = 60
_KNOWLEDGE_CACHE = {"loaded_at": 0.0, "chunks": []}


def _check_image_throttle(user):
    """
    Cache-based anti-spam guard for AI image generation.
    Returns a chatbot payload reply when throttled, otherwise None.
    """
    user_id = getattr(user, "id", None)
    if not user_id:
        return None

    cooldown_key = f"ai_image_cooldown_{user_id}"
    if not cache.add(cooldown_key, "1", AI_IMAGE_COOLDOWN_SECONDS):
        return _chat_response_payload(
            (
                "I can generate one design image at a time to keep the service fast for everyone. "
                f"Please try again in {AI_IMAGE_COOLDOWN_SECONDS} seconds."
            )
        )

    day_key = f"ai_image_daily_{user_id}_{timezone.localtime().strftime('%Y%m%d')}"
    used = int(cache.get(day_key) or 0)
    if used >= AI_IMAGE_DAILY_LIMIT:
        return _chat_response_payload(
            (
                f"You've reached the daily limit of {AI_IMAGE_DAILY_LIMIT} AI design images for today. "
                "Please come back tomorrow so our AI credits don't run out. Thanks for understanding!"
            )
        )
    cache.set(day_key, used + 1, 60 * 60 * 24)
    return None


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


def _strip_generated_image_markup(text):
    content = str(text or "")
    # Remove generated image + download action markup so the LLM does not echo old image URLs.
    content = re.sub(r"<img\b[^>]*>", "", content, flags=re.IGNORECASE)
    content = re.sub(r"<a\b[^>]*class=\"ai-action-btn\"[^>]*>.*?</a>", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<a\b[^>]*download=[^>]*>.*?</a>", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<[^>]+>", " ", content)
    content = unescape(content)
    content = re.sub(r"\s+", " ", content).strip()
    return content


def _random_image_seed():
    # Stable int range for providers that expect 32-bit signed seeds.
    return int((time.time_ns() + uuid.uuid4().int) % 2_147_483_647)


# Image model fallback chain. The default SDXL model routes to a paid
# provider once the HuggingFace monthly credits run out (HTTP 402 Payment
# Required), so generation walks down this chain to a model that is still
# served by a provider with remaining free quota.
IMAGE_MODEL_FALLBACK_CHAIN = (
    "black-forest-labs/FLUX.1-schnell",
    "stabilityai/stable-diffusion-xl-base-1.0",
    "black-forest-labs/FLUX.1-dev",
)

DEFAULT_IMAGE_MODEL = "black-forest-labs/FLUX.1-schnell"


def _is_payment_image_error(error_message):
    lowered = (error_message or "").lower()
    return any(
        marker in lowered
        for marker in (
            "402",
            "payment required",
            "monthly included credits",
            "purchase pre-paid credits",
        )
    )


def _generate_image_with_fallback(client, prompt, negative_prompt="", requested_model=None):
    """
    Generate an image, walking down the model fallback chain when the
    provider reports a payment/quota error (HTTP 402). Non-payment errors
    are raised immediately so the caller's own retry logic handles them.
    """
    models = []
    if requested_model:
        models.append(requested_model)
    models.extend(m for m in IMAGE_MODEL_FALLBACK_CHAIN if m not in models)

    last_error = None
    for model_id in models:
        kwargs = {"model": model_id, "seed": _random_image_seed()}
        # FLUX models on the router do not accept negative prompts.
        if negative_prompt and "flux" not in model_id.lower():
            kwargs["negative_prompt"] = negative_prompt
        try:
            with _without_dead_local_proxy():
                return client.text_to_image(prompt=prompt, **kwargs)
        except Exception as image_error:
            last_error = image_error
            print(f"Image model '{model_id}' failed: {image_error}")
            if not _is_payment_image_error(str(image_error)):
                raise
    raise last_error or RuntimeError("Image generation failed for all fallback models.")


# ---------------------------------------------------------------------------
# Live availability snapshot — lets the AI answer "is this date open?"
# ---------------------------------------------------------------------------
ACTIVE_BOOKING_STATUSES = ("pending_payment", "confirmed", "completed")


def build_availability_snapshot(days_ahead=14):
    """Return a text snapshot of the next N days' booking availability."""
    today = timezone.localdate()
    end_date = today + timedelta(days=days_ahead - 1)

    booked = set(
        Booking.objects.filter(
            event_date__gte=today,
            event_date__lte=end_date,
            status__in=ACTIVE_BOOKING_STATUSES,
        ).values_list("event_date", flat=True)
    )
    blocked = set(
        BlockedDate.objects.filter(
            date__gte=today, date__lte=end_date
        ).values_list("date", flat=True)
    )

    lines = [f"UPCOMING AVAILABILITY (live data, next {days_ahead} days):"]
    for offset in range(days_ahead):
        day = today + timedelta(days=offset)
        if day in blocked:
            status = "UNAVAILABLE (blocked by admin)"
        elif day in booked:
            status = "FULLY BOOKED"
        else:
            status = "AVAILABLE"
        lines.append(f"- {day.strftime('%A, %B %d, %Y')}: {status}")
    lines.append(
        "Use this list to answer date availability questions. If a requested date "
        "is FULLY BOOKED or UNAVAILABLE, suggest the next AVAILABLE date. Always "
        "remind the user to complete the booking form to lock the slot."
    )
    return "\n".join(lines)


PRICING_ESTIMATOR_DIRECTIVE = (
    "PRICE ESTIMATING RULES:\n"
    "When the user asks for a price estimate for a specific setup, build a clear "
    "breakdown from the snapshot data only: start from the matching package base "
    "price, then add each requested add-on's listed price. Show each line as "
    "'Label: PHP amount' and end with 'Estimated Total: PHP amount'. "
    "Always end with one short reminder that the final quote is confirmed by the "
    "admin during booking. Never invent prices that are not in the snapshot."
)


def _detect_variation_count(text):
    """Return 3 when the user asks for multiple design options, else 1."""
    lowered = (text or "").lower()
    multi_markers = (
        "mood board", "moodboard", "mood-board", "options", "variations",
        "3 designs", "three designs", "3 versions", "three versions",
        "3 concepts", "three concepts", "3 options", "iba-iba", "pumili",
        "a few designs", "few options",
    )
    if any(marker in lowered for marker in multi_markers):
        return 3
    return 1


FRUSTRATION_PHRASES = (
    "talk to human", "talk to a human", "speak to human", "speak to a human",
    "real person", "human agent", "actual person", "customer service",
    "tao po", "ibang tao", "taong tao", "hindi ka tao", "totoong tao",
    "useless", "stupid bot", "waste of time", "walang kwenta",
    "kakainis", "ayaw gumana", "hindi gumagana",
)


def detect_frustration(user_message):
    """True when the user clearly wants a human or is expressing frustration."""
    lowered = (user_message or "").lower()
    return any(phrase in lowered for phrase in FRUSTRATION_PHRASES)


def suggested_followups(reply_text):
    """Heuristic follow-up chips based on the reply content."""
    lowered = (reply_text or "").lower()
    if "<img" in lowered:
        return ["Another version", "Book this design", "Our packages"]
    if "usable image" in lowered or "credits" in lowered:
        return ["Try again", "Our packages", "How to book?"]
    if "php" in lowered or "₱" in reply_text or "package" in lowered or "price" in lowered:
        return ["Check date availability", "Book now", "Suggest design"]
    if "step 1" in lowered or "how to" in lowered or "paano" in lowered:
        return ["Book now", "Our packages", "Suggest design"]
    if "available" in lowered or "slot" in lowered:
        return ["Book now", "Our packages", "Suggest design"]
    return ["Suggest design", "Our packages", "How to book?"]


def _image_success_reply_multi(image_entries, intro_text=""):
    """Build a reply containing several generated images as labeled options."""
    intro = intro_text or (
        "Here are 3 Balloorina design concepts based on your request — pick your favorite:"
    )
    parts = [f"{intro}\n\n"]
    for index, (img_url, prompt) in enumerate(image_entries, start=1):
        parts.append(f"Option {index}:\n")
        parts.append(
            f'<img src="{escape(img_url)}" alt="Balloorina Design Concept" '
            f'data-ai-prompt="{escape(prompt)}" '
            'style="max-width:100%; border-radius:8px; margin-top:6px;">'
        )
        parts.append("\n\n")
    return "".join(parts)


def analyze_inspiration_image(image_file, user_note=""):
    """Describe an uploaded inspiration photo and map it to Balloorina styling."""
    api_key = getattr(settings, "HUGGINGFACE_API_KEY", "")
    if not api_key:
        return "Configuration Error: API key missing."
    image_bytes = image_file.read()
    if not image_bytes:
        return "I couldn't read that image file. Please try another photo."
    if len(image_bytes) > 5 * 1024 * 1024:
        return "That photo is too large (max 5MB). Please upload a smaller one."
    content_type = getattr(image_file, "content_type", "") or "image/jpeg"
    data_url = "data:%s;base64,%s" % (
        content_type,
        base64.b64encode(image_bytes).decode("ascii"),
    )
    # Vision models that work on free-tier HuggingFace accounts, tried in
    # order. (Qwen2.5-VL returns "model_not_supported" on accounts without a
    # vision provider, so gemma-3-4b-it — which serves images fine — is tried
    # first.) The configured model always goes first when explicitly set.
    configured_vision = getattr(settings, "HUGGINGFACE_VISION_MODEL_ID", "")
    vision_chain = [m for m in (configured_vision, "google/gemma-3-4b-it", "Qwen/Qwen2.5-VL-7B-Instruct") if m]
    seen_models = set()
    vision_chain = [m for m in vision_chain if not (m in seen_models or seen_models.add(m))]
    note = _safe_text(user_note)[:300] or "Analyze this event design inspiration photo."
    vision_messages = [
        {
            "role": "system",
            "content": (
                "You are Balloorina's design consultant. Describe the uploaded photo's "
                "backdrop/design elements in short bullet points (colors, balloons, props, "
                "florals, layout), then add one line on how Balloorina can recreate the same "
                "vibe. End with: [PROMPT]detailed English image prompt to recreate this style "
                "as a Balloorina backdrop[/PROMPT] so the app can generate a matching design. "
                "Mirror the user's language."
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": note},
            ],
        },
    ]
    with _without_dead_local_proxy():
        try:
            client = InferenceClient(token=api_key, timeout=AI_REQUEST_TIMEOUT)
        except TypeError:
            client = InferenceClient(token=api_key)
    last_error_text = ""
    for vision_model in vision_chain:
        try:
            with _without_dead_local_proxy():
                response = client.chat_completion(
                    messages=vision_messages,
                    model=vision_model,
                    max_tokens=450,
                )
            reply = (response.choices[0].message.content or "").strip()
            return reply or "I couldn't analyze that photo. Please try a clearer one."
        except Exception as vision_error:
            last_error_text = str(vision_error)
            print(f"Vision Analysis Error ({vision_model}): {vision_error}")
            continue
    error_text = last_error_text.lower()
    if "402" in error_text or "credits" in error_text:
        return (
            "Photo analysis is temporarily unavailable because the AI provider's monthly "
            "credits are used up. Please try again after the credits reset."
        )
    if "401" in error_text or "unauthorized" in error_text:
        return "AI authentication failed. Please verify the HUGGINGFACE_API_KEY in .env."
    return "I couldn't analyze that photo right now. Please try again later."


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

    # Public chunks (core rules, catalog, content, stats) hit the DB on every
    # build but rarely change — serve them from a short-lived cache. The
    # per-user chunk is always built fresh.
    now_ts = time.time()
    cached_chunks = _KNOWLEDGE_CACHE["chunks"]
    if cached_chunks and (now_ts - _KNOWLEDGE_CACHE["loaded_at"]) < KNOWLEDGE_CACHE_TTL_SECONDS:
        chunks.extend(cached_chunks)
    else:
        public_chunks = [
            *_build_core_chunks(),
            *_build_catalog_chunks(),
            *_build_content_chunks(),
            _build_platform_stats_chunk(),
        ]
        if _env_truthy(os.getenv("AI_INCLUDE_REFERENCE_DOCS")):
            public_chunks.extend(_load_reference_doc_chunks())
        public_chunks = [
            chunk for chunk in public_chunks if chunk and _safe_text(chunk["content"])
        ]
        if public_chunks:
            _KNOWLEDGE_CACHE["chunks"] = public_chunks
            _KNOWLEDGE_CACHE["loaded_at"] = now_ts
        chunks.extend(public_chunks)

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
        lines.append(build_availability_snapshot())
        lines.append(PRICING_ESTIMATOR_DIRECTIVE)
        return "\n\n".join(lines)
    except Exception as e:
        print(f"Error building system context: {e}")
        return (
            "SYSTEM KNOWLEDGE SNAPSHOT unavailable. "
            "Only answer from known Balloorina flows and clearly state uncertainty."
        )


CHATBOT_BASE_PROMPT = (
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
    "If user asks unrelated general-knowledge topics, politely redirect to Balloorina system questions. "
    "\n\nIMAGE GENERATION CAPABILITY:\n"
    "You CAN generate design concepts, backdrop ideas, and event styling images. "
    "If the user asks to see a design, generate an image, or requests a visual concept, you MUST trigger the image generator. "
    "To trigger it, include a detailed English image prompt wrapped in [PROMPT] and [/PROMPT] tags at the end of your response. "
    "If you are unsure whether the user wants to see a design, ALWAYS include the [PROMPT] block anyway — "
    "never reply with text alone when the user's message mentions a design, backdrop, theme, "
    "color palette, or event styling. "
    "Example: 'Narito ang isang sample design para sa binyag. [PROMPT]photorealistic baptism backdrop, white and gold balloons...[/PROMPT]'. "
    "The prompt inside [PROMPT] should be descriptive, photorealistic, and in English, "
    "and it must describe the backdrop DESIGN itself (backdrop panels, balloon garlands, "
    "props, florals, colors, signage theme), not the venue room or furniture. "
    "If you are generating a follow-up or a variation, make the prompt reflect the changes the user asked for."
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
            try:
                client = InferenceClient(token=api_key, timeout=AI_REQUEST_TIMEOUT)
            except TypeError:
                # Older huggingface_hub versions may not accept the timeout kwarg.
                client = InferenceClient(token=api_key)
        model_id = getattr(settings, "HUGGINGFACE_MODEL_ID", "Qwen/Qwen2.5-72B-Instruct")

        image_followup_triggered = _is_image_followup_request(
            user_message,
            conversation_history,
        )
        image_triggered = is_image_request(user_message) or image_followup_triggered

        # Anti-spam guard before spending expensive image-generation credits.
        if image_triggered and getattr(user, "is_authenticated", False):
            throttle_reply = _check_image_throttle(user)
            if throttle_reply is not None:
                return throttle_reply

        if image_triggered:
            image_context = _recent_image_request_context(
                conversation_history,
                include_last_prompt=image_followup_triggered,
            )
            img_prompt = build_image_generation_prompt(user_message, image_context)
            fallback_prompt = build_image_generation_prompt(user_message, "")
            image_model = getattr(
                settings,
                "HUGGINGFACE_IMAGE_MODEL_ID",
                DEFAULT_IMAGE_MODEL,
            )

            # Mood board mode: generate several labeled options in one reply.
            variation_count = _detect_variation_count(user_message)
            if variation_count > 1:
                try:
                    entries = []
                    for _ in range(variation_count):
                        # Rebuild the prompt per option: the anti-repeat roller
                        # inside build_image_generation_prompt guarantees each
                        # option gets a different structure/decor combination
                        # (previously all options reused one identical prompt
                        # and differed only by random seed, so they looked like
                        # near-duplicates).
                        option_prompt = build_image_generation_prompt(
                            user_message, image_context
                        )
                        generated_image = _generate_image_with_fallback(
                            client,
                            option_prompt,
                            negative_prompt=build_image_negative_prompt(
                                f"{image_context} {user_message}"
                            ),
                            requested_model=image_model,
                        )
                        entries.append(
                            (_save_generated_image(generated_image), option_prompt)
                        )
                    return _chat_response_payload(
                        _image_success_reply_multi(entries)
                    )
                except Exception as variation_error:
                    print(f"Variation Image Generation Error: {variation_error}")
                    return _chat_response_payload(
                        _image_unavailable_reply(
                            img_prompt,
                            error_message=str(variation_error),
                        )
                    )

            try:
                attempts = [
                    {"prompt": img_prompt, "label": "primary"},
                    {"prompt": fallback_prompt, "label": "fallback"},
                ]
                seen_prompts = set()
                last_error = None

                for attempt in attempts:
                    attempt_prompt = (attempt.get("prompt") or "").strip()
                    if not attempt_prompt or attempt_prompt in seen_prompts:
                        continue
                    seen_prompts.add(attempt_prompt)

                    max_retries = 2 if attempt.get("label") == "primary" else 1
                    for retry_index in range(max_retries):
                        try:
                            generated_image = _generate_image_with_fallback(
                                client,
                                attempt_prompt,
                                negative_prompt=build_image_negative_prompt(f"{image_context} {user_message}"),
                                requested_model=image_model,
                            )
                            img_url = _save_generated_image(generated_image)
                            return _chat_response_payload(_image_success_reply(img_url, attempt_prompt))
                        except Exception as attempt_error:
                            last_error = attempt_error
                            error_text = str(attempt_error)

                            should_retry = retry_index < (max_retries - 1) and _is_retryable_image_error(error_text)
                            if should_retry:
                                time.sleep(1.1)
                                continue

                            if attempt.get("label") == "primary" and _is_prompt_limit_image_error(error_text):
                                # Try the shorter fallback prompt next.
                                break
                            # If primary prompt fails for any other reason, still try fallback once.
                            if attempt.get("label") == "primary":
                                break
                            # Fallback attempt failed; stop.
                            raise

                raise last_error or RuntimeError("Image generation failed with unknown provider error.")
            except Exception as image_error:
                print(f"Image Generation Error: {image_error}")
                return _chat_response_payload(
                    _image_unavailable_reply(
                        img_prompt,
                        error_message=str(image_error),
                    )
                )

        base_prompt = CHATBOT_BASE_PROMPT

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
                    if role == "assistant":
                        content = _strip_generated_image_markup(content)
                    else:
                        content = _safe_text(content)
                    if content:
                        messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_message})

        with _without_dead_local_proxy():
            response = client.chat_completion(
                messages=messages,
                model=model_id,
                max_tokens=1400,
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
            # AI model decided to generate an image. Let's do it.
            # I-enhance muna ang raw LLM prompt gamit ang parehong backdrop-focused
            # builder na ginagamit ng fast path, para consistent ang Balloorina style.
            image_model = getattr(
                settings,
                "HUGGINGFACE_IMAGE_MODEL_ID",
                DEFAULT_IMAGE_MODEL,
            )
            enhanced_prompt = build_image_generation_prompt(prompt_text, "")
            try:
                generated_image = _generate_image_with_fallback(
                    client,
                    enhanced_prompt,
                    negative_prompt=build_image_negative_prompt(f"{prompt_text} {user_message}"),
                    requested_model=image_model,
                )
                img_url = _save_generated_image(generated_image)
                # Combine the AI's intro/outro with the generated image
                final_reply = f"{intro_text}\n\n{_image_success_reply(img_url, enhanced_prompt)}\n\n{outro_text}".strip()
                return _chat_response_payload(final_reply)
            except Exception as image_error:
                print(f"Late Image Generation Error: {image_error}")
                # Never fall back to a silent text-only reply — tell the user
                # what happened and give them the enhanced prompt to retry.
                return _chat_response_payload(
                    _image_unavailable_reply(
                        enhanced_prompt,
                        error_message=str(image_error),
                    )
                )

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


def _build_ai_messages(user_message, conversation_history=None, user=None):
    """Shared system prompt + history assembly (normal + streaming paths)."""
    system_context = get_system_context(
        user_message=user_message,
        conversation_history=conversation_history,
        user=user,
    )
    system_prompt = f"{CHATBOT_BASE_PROMPT}\n\n{system_context}"
    messages = [{"role": "system", "content": system_prompt}]
    if conversation_history:
        for msg in conversation_history:
            role = msg.get("role")
            content = msg.get("content")
            if content and role in {"user", "assistant"}:
                if role == "assistant":
                    content = _strip_generated_image_markup(content)
                else:
                    content = _safe_text(content)
                if content:
                    messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": _safe_text(user_message)})
    return messages


_PROMPT_BLOCK_RE = re.compile(r"\[PROMPT\].*?\[/PROMPT\]", flags=re.DOTALL)


def _strip_prompt_blocks(text):
    """Remove complete and trailing-partial [PROMPT] blocks from streamed text."""
    visible = _PROMPT_BLOCK_RE.sub("", text or "")
    partial_index = visible.find("[PROMPT]")
    if partial_index != -1:
        visible = visible[:partial_index]
    return visible.strip()


def stream_chatbot_events(user_message, conversation_history=None, user=None):
    """
    Yield streaming events for the AI chat SSE endpoint.

    Event shapes:
      {"type": "delta",  "text": str}    — streamed reply text
      {"type": "status", "message": str} — long-running step notice
      {"type": "final",  "data": dict}   — same payload shape as chat_api
      {"type": "error",  "message": str}
    """
    moderation_result = evaluate_chat_moderation(user, user_message)
    if moderation_result is not None:
        yield {"type": "final", "data": moderation_result}
        return

    if InferenceClient is None:
        yield {
            "type": "final",
            "data": _chat_response_payload(
                "System Error: AI library missing. Please install huggingface_hub."
            ),
        }
        return

    api_key = getattr(settings, "HUGGINGFACE_API_KEY", "")
    if not api_key:
        yield {
            "type": "final",
            "data": _chat_response_payload("Configuration Error: API key missing."),
        }
        return

    image_followup_triggered = _is_image_followup_request(
        user_message, conversation_history
    )
    if is_image_request(user_message) or image_followup_triggered:
        # Image requests keep the full non-streaming pipeline (retries,
        # throttling, fallback models). The frontend already shows its own
        # "Creating your image..." status UI, so no duplicate status event here.
        result = get_chatbot_response(
            user_message,
            conversation_history=conversation_history,
            user=user,
        )
        yield {"type": "final", "data": result}
        return

    with _without_dead_local_proxy():
        try:
            client = InferenceClient(token=api_key, timeout=AI_REQUEST_TIMEOUT)
        except TypeError:
            client = InferenceClient(token=api_key)
    model_id = getattr(
        settings, "HUGGINGFACE_MODEL_ID", "Qwen/Qwen2.5-72B-Instruct"
    )
    messages = _build_ai_messages(user_message, conversation_history, user)

    full_text = ""
    sent_text = ""
    finish_reason = ""
    try:
        with _without_dead_local_proxy():
            stream = client.chat_completion(
                messages=messages,
                model=model_id,
                # 1400 tokens: long price/package breakdowns were getting cut
                # off at the old 720 cap (finish_reason="length").
                max_tokens=1400,
                temperature=0.6,
                stream=True,
            )
        for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content
            except (AttributeError, IndexError, TypeError):
                delta = None
            try:
                chunk_finish = str(
                    getattr(chunk.choices[0], "finish_reason", "") or ""
                ).lower()
            except (AttributeError, IndexError, TypeError):
                chunk_finish = ""
            if chunk_finish:
                finish_reason = chunk_finish
            if not delta:
                continue
            full_text += delta
            visible = _strip_prompt_blocks(full_text)
            # Only forward smooth growth — [PROMPT] blocks temporarily shrink
            # the visible text, so never resend corrected prefixes.
            if len(visible) > len(sent_text) and visible.startswith(sent_text):
                yield {"type": "delta", "text": visible[len(sent_text) :]}
                sent_text = visible

        # A stream that hit the token cap ends mid-sentence ("putol"). Finish
        # it with a continuation call, streamed as one extra delta.
        if finish_reason == "length" or _looks_truncated(full_text):
            continuation_messages = messages + [
                {"role": "assistant", "content": full_text},
                {
                    "role": "user",
                    "content": (
                        "Continue from exactly where you stopped. Do not repeat "
                        "previous lines. Keep the same formatting and finish the "
                        "reply completely."
                    ),
                },
            ]
            try:
                with _without_dead_local_proxy():
                    continuation = client.chat_completion(
                        messages=continuation_messages,
                        model=model_id,
                        max_tokens=500,
                        temperature=0.4,
                    )
                cont_text = (
                    continuation.choices[0].message.content or ""
                ).strip()
                if cont_text:
                    full_text = f"{full_text}\n{cont_text}".strip()
                    visible = _strip_prompt_blocks(full_text)
                    if len(visible) > len(sent_text) and visible.startswith(sent_text):
                        yield {"type": "delta", "text": visible[len(sent_text) :]}
                        sent_text = visible
            except Exception as cont_error:
                print(f"Streaming Continuation Error: {cont_error}")

        # After streaming: handle a trailing [PROMPT] block (late image path).
        prompt_text, intro_text, _outro_text = _extract_image_prompt_block(full_text)
        if prompt_text:
            # The frontend already shows its own "Creating your image..." UI —
            # emitting another status message duplicated the indicator.
            image_model = getattr(
                settings,
                "HUGGINGFACE_IMAGE_MODEL_ID",
                DEFAULT_IMAGE_MODEL,
            )
            enhanced_prompt = build_image_generation_prompt(prompt_text, "")
            try:
                generated_image = _generate_image_with_fallback(
                    client,
                    enhanced_prompt,
                    negative_prompt=build_image_negative_prompt(
                        f"{prompt_text} {user_message}"
                    ),
                    requested_model=image_model,
                )
                img_url = _save_generated_image(generated_image)
                yield {
                    "type": "final",
                    "data": _chat_response_payload(
                        f"{_normalize_reply_text(intro_text)}\n\n"
                        f"{_image_success_reply(img_url, enhanced_prompt)}".strip()
                    ),
                }
                return
            except Exception as image_error:
                print(f"Streamed Late Image Generation Error: {image_error}")
                yield {
                    "type": "final",
                    "data": _chat_response_payload(
                        _image_unavailable_reply(
                            enhanced_prompt,
                            error_message=str(image_error),
                        )
                    ),
                }
                return

        yield {
            "type": "final",
            "data": _chat_response_payload(_normalize_reply_text(full_text)),
        }
    except Exception as stream_error:
        print(f"Streaming Chat Error: {stream_error}")
        error_text = str(stream_error).lower()
        if "402" in error_text or "depleted your monthly included credits" in error_text:
            yield {
                "type": "final",
                "data": _chat_response_payload(
                    "Your AI provider quota is currently exhausted (Hugging Face credits reached). "
                    "Please add credits or upgrade your Hugging Face plan, then try again."
                ),
            }
            return
        if "401" in error_text or "unauthorized" in error_text:
            yield {
                "type": "final",
                "data": _chat_response_payload(
                    "AI authentication failed. Please verify your HUGGINGFACE_API_KEY in .env."
                ),
            }
            return
        yield {
            "type": "final",
            "data": _chat_response_payload(
                "I'm sorry, I'm having trouble connecting to my service right now. "
                "Please try again later."
            ),
        }
