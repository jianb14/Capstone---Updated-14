"""Shared helpers, constants and imports for the app.views package. (split from app/views.py)"""




import hashlib
import io
import json
import logging
import os
import re
import time
import uuid
from calendar import monthrange
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote, urlparse

import openpyxl
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
    update_session_auth_hash,
)
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.images import get_image_dimensions
from django.core.mail import send_mail
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.contrib.staticfiles import finders
from django.db import transaction
from django.db.models import Avg, Count, DecimalField, Exists, Max, OuterRef, Q, Subquery, Sum, Value, Model, QuerySet
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import get_template, render_to_string
from xhtml2pdf import pisa
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors

from ..models import (
    AboutContent,
    AboutJourneyItem,
    AboutValueItem,
    AdditionalOnly,
    AddOn,
    AdminNotification,
    AuditLog,
    Booking,
    BookingImage,
    BookingStatusLog,
    BlockedDate,
    CanvasAsset,
    CanvasCategory,
    CanvasLabel,
    ChatMessage,
    ChatNotification,
    ChatSession,
    ConcernTicket,
    ConcernImage,
    Design,
    GalleryCategory,
    GalleryImage,
    GCashConfig,
    GuidelineItem,
    GuidelinePageContent,
    HomeContent,
    HomeFaqItem,
    HomeFeatureItem,
    HomeHowItWorksStep,
    MessageReaction,
    Notification,
    Package,
    Payment,
    Review,
    ReviewImage,
    ReviewReply,
    Service,
    ServiceChargeConfig,
    ServiceContent,
    SiteSettings,
    User,
    UserDesign,
)
from ..services import (
    create_paymongo_checkout_session,
    get_current_ban_status,
    get_chatbot_response,
    retrieve_paymongo_checkout_session,
    retrieve_paymongo_payment,
    verify_paymongo_webhook_signature,
)

logger = logging.getLogger(__name__)

CHAT_IMAGE_MAX_BYTES = 5 * 1024 * 1024
CHAT_IMAGE_ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}
CHAT_IMAGE_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
CHAT_REACTION_EMOJIS = ("👍", "❤️", "😮", "😂", "😢")
CHAT_PRESENCE_ONLINE_SECONDS = 90
CHAT_TYPING_SECONDS = 8


def _is_admin_user(user):
    return (
        getattr(user, "is_authenticated", False)
        and (
            getattr(user, "role", None) in ["admin", "staff"]
            or getattr(user, "is_superuser", False)
        )
    )


def _get_primary_admin_user():
    return (
        User.objects.filter(role="admin").first()
        or User.objects.filter(is_superuser=True).first()
    )


def _increase_rate_limit_counter(key, timeout_seconds):
    if cache.add(key, 1, timeout=timeout_seconds):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=timeout_seconds)
        return 1


def _get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _format_wait_time(seconds):
    seconds = max(1, int(seconds))
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes, rem_seconds = divmod(seconds, 60)
    if minutes < 60:
        if rem_seconds:
            return f"{minutes} minute{'s' if minutes != 1 else ''} and {rem_seconds} second{'s' if rem_seconds != 1 else ''}"
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, rem_minutes = divmod(minutes, 60)
    if rem_minutes:
        return f"{hours} hour{'s' if hours != 1 else ''} and {rem_minutes} minute{'s' if rem_minutes != 1 else ''}"
    return f"{hours} hour{'s' if hours != 1 else ''}"


def _is_reset_request_rate_limited(request, email):
    client_ip = _get_client_ip(request)
    normalized_email = (email or "").strip().lower()
    email_hash = hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()
    now = int(time.time())

    cooldown_seconds = getattr(settings, "FORGOT_PASSWORD_COOLDOWN_SECONDS", 60)
    window_seconds = getattr(
        settings, "FORGOT_PASSWORD_RATE_LIMIT_WINDOW_SECONDS", 3600
    )
    ip_limit = getattr(settings, "FORGOT_PASSWORD_RATE_LIMIT_PER_IP", 5)
    email_limit = getattr(settings, "FORGOT_PASSWORD_RATE_LIMIT_PER_EMAIL", 3)

    cooldown_key = f"pwd-reset:cooldown:ip:{client_ip}"
    cooldown_until_key = f"{cooldown_key}:until"
    ip_count_key = f"pwd-reset:count:ip:{client_ip}"
    ip_window_until_key = f"{ip_count_key}:until"
    email_count_key = f"pwd-reset:count:email:{email_hash}"
    email_window_until_key = f"{email_count_key}:until"

    if cache.get(cooldown_key):
        cooldown_until = cache.get(cooldown_until_key) or (now + cooldown_seconds)
        wait_seconds = max(1, int(cooldown_until) - now)
        return (
            True,
            f"Please wait {_format_wait_time(wait_seconds)} before requesting another reset link.",
        )

    current_ip_count = cache.get(ip_count_key, 0)
    current_email_count = cache.get(email_count_key, 0)
    if current_ip_count >= ip_limit or current_email_count >= email_limit:
        ip_wait_seconds = 0
        email_wait_seconds = 0

        if current_ip_count >= ip_limit:
            ip_window_until = cache.get(ip_window_until_key) or (now + window_seconds)
            ip_wait_seconds = max(1, int(ip_window_until) - now)

        if current_email_count >= email_limit:
            email_window_until = cache.get(email_window_until_key) or (
                now + window_seconds
            )
            email_wait_seconds = max(1, int(email_window_until) - now)

        wait_seconds = max(ip_wait_seconds, email_wait_seconds, 1)
        return (
            True,
            f"Too many reset attempts. Please try again in {_format_wait_time(wait_seconds)}.",
        )

    cache.set(cooldown_key, 1, timeout=cooldown_seconds)
    cache.set(cooldown_until_key, now + cooldown_seconds, timeout=cooldown_seconds)
    cache.add(ip_window_until_key, now + window_seconds, timeout=window_seconds)
    cache.add(email_window_until_key, now + window_seconds, timeout=window_seconds)
    _increase_rate_limit_counter(ip_count_key, window_seconds)
    _increase_rate_limit_counter(email_count_key, window_seconds)
    return False, ""


def log_action(user, action):
    """Helper function to create an audit log entry."""
    AuditLog.objects.create(user=user, action=action)


def parse_non_negative_int(raw, default=0):
    """Safely parse a submitted form value into a non-negative integer.

    Blank, non-numeric, or negative values fall back to `default` so that
    PositiveIntegerField columns (order / display_order / sort_order) never
    receive an invalid number (which would raise a database error).
    """
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    if value < 0:
        return default
    return value


def send_admin_alert_email(subject, body):
    """
    Send an alert email to configured admin addresses (Site Settings).
    Fail-safe: never raises — logs the error instead.
    """
    try:
        site_settings = SiteSettings.load()
    except Exception:
        logger.exception("Failed to load Site Settings for admin alert email.")
        return False

    recipients = site_settings.admin_notification_emails()
    if not recipients:
        return False

    try:
        send_mail(
            subject=f"[Balloorina Admin] {subject}",
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=recipients,
            fail_silently=True,
        )
        return True
    except Exception:
        logger.exception("Failed to send admin alert email: %s", subject)
        return False


def log_booking_status(booking, old_status, new_status, changed_by=None, notes=""):
    """Record a status change for a booking's history timeline."""
    return BookingStatusLog.objects.create(
        booking=booking,
        old_status=old_status or "",
        new_status=new_status,
        changed_by=changed_by if (changed_by and getattr(changed_by, "is_authenticated", False)) else None,
        notes=notes or "",
    )


def _booking_time_bounds(booking):
    """Return (start_dt, end_dt) datetimes for a booking, defaulting to a 4-hour span."""
    start_dt = (
        datetime.combine(booking.event_date, booking.event_time)
        if booking.event_time
        else None
    )
    end_dt = None
    if start_dt:
        end_time_str = get_end_time_from_str(booking.special_requests or "")
        if end_time_str:
            try:
                end_dt = datetime.combine(
                    booking.event_date, datetime.strptime(end_time_str, "%H:%M").time()
                )
            except ValueError:
                end_dt = None
        if end_dt is None:
            end_dt = start_dt + timedelta(hours=4)
    return start_dt, end_dt


ACTIVE_BOOKING_STATUSES = ("pending_payment", "confirmed", "completed")


def find_active_booking_conflicts(booking):
    """
    Return active bookings (pending_payment/confirmed/completed) on the same
    event date whose time ranges overlap the given booking. Purely read-only —
    used for conflict warnings and badges.
    """
    if not booking.event_date:
        return Booking.objects.none()

    candidates = Booking.objects.filter(
        event_date=booking.event_date,
        status__in=ACTIVE_BOOKING_STATUSES,
    ).exclude(pk=booking.pk).select_related("user")

    if not booking.event_time:
        # No time info — treat any other active booking on the same date as a conflict.
        return candidates

    b_start, b_end = _booking_time_bounds(booking)
    if not b_start or not b_end:
        return candidates

    conflicts = []
    for candidate in candidates:
        if not candidate.event_time:
            conflicts.append(candidate)
            continue
        c_start, c_end = _booking_time_bounds(candidate)
        if c_start and c_end and b_start < c_end and b_end > c_start:
            conflicts.append(candidate)
    return conflicts


def get_service_charge_config():
    config, _ = ServiceChargeConfig.objects.get_or_create(
        id=1,
        defaults={
            "amount": Decimal("0.00"),
            "notes": "Includes styling fee, toll fees, fuel, crew meals, and ingress/egress logistics.",
        },
    )
    return config


def normalize_package_part(value):
    cleaned = re.sub(
        r"\s*\((add-on|additional|solo)\)\s*$", "", value or "", flags=re.IGNORECASE
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.lower()


def format_booking_selection(package_type):
    parts = [p.strip() for p in (package_type or "").split("+") if p.strip()]
    if not parts:
        return "Custom Booking"

    packages = []
    addons = []
    solo_addons = []
    additionals = []

    for part in parts:
        if re.search(r"\(solo\)\s*$", part, re.IGNORECASE):
            solo_addons.append(
                re.sub(r"\s*\(solo\)\s*$", "", part, flags=re.IGNORECASE).strip()
            )
        elif re.search(r"\(add-on\)\s*$", part, re.IGNORECASE):
            addons.append(
                re.sub(r"\s*\(add-on\)\s*$", "", part, flags=re.IGNORECASE).strip()
            )
        elif re.search(r"\(additional\)\s*$", part, re.IGNORECASE):
            additionals.append(
                re.sub(r"\s*\(additional\)\s*$", "", part, flags=re.IGNORECASE).strip()
            )
        else:
            packages.append(part)

    segments = []
    if packages:
        segments.append(f"Package: {', '.join(packages)}")
    if addons:
        segments.append(f"Add-on: {', '.join(addons)}")
    if solo_addons:
        segments.append(f"Solo Add-on: {', '.join(solo_addons)}")
    if additionals:
        segments.append(f"Additional: {', '.join(additionals)}")

    return " | ".join(segments) if segments else "Custom Booking"


def get_booking_price_breakdown(booking):
    parts = [p.strip() for p in (booking.package_type or "").split("+") if p.strip()]
    breakdown = []
    subtotal = Decimal("0.00")

    package_map = {
        normalize_package_part(pkg.name): pkg for pkg in Package.objects.all()
    }
    addon_map = {
        normalize_package_part(addon.name): addon for addon in AddOn.objects.all()
    }
    additional_map = {
        normalize_package_part(additional.name): additional
        for additional in AdditionalOnly.objects.all()
    }

    for raw_part in parts:
        is_solo = raw_part.endswith("(Solo)")
        part_name = raw_part.replace("(Solo)", "").strip() if is_solo else raw_part
        normalized_part_name = normalize_package_part(part_name)
        amount = None
        label = raw_part

        if is_solo:
            addon = addon_map.get(normalized_part_name)
            if addon and addon.solo_price is not None:
                amount = addon.solo_price
                label = f"{addon.name.strip()} (Solo)"
        else:
            package_obj = package_map.get(normalized_part_name)
            if package_obj:
                amount = package_obj.price
                label = package_obj.name.strip()
            else:
                addon = addon_map.get(normalized_part_name)
                if addon:
                    amount = addon.price
                    label = f"{addon.name.strip()} (Add-on)"
                else:
                    additional = additional_map.get(normalized_part_name)
                    if additional:
                        amount = additional.price
                        label = f"{additional.name.strip()} (Additional)"

        if amount is not None:
            subtotal += amount
            breakdown.append({"label": label, "amount": amount})

    service_charge = Decimal("0.00")
    if parts:
        service_charge = get_service_charge_config().amount or Decimal("0.00")

    computed_total = subtotal + service_charge
    return {
        "items": breakdown,
        "subtotal": subtotal,
        "service_charge": service_charge,
        "computed_total": computed_total,
        "stored_total": booking.total_price or Decimal("0.00"),
    }


def build_booking_snapshot(booking):
    return {
        "event_type": booking.event_type or "",
        "event_date": booking.event_date.isoformat() if booking.event_date else "",
        "event_time": booking.event_time.strftime("%H:%M")
        if booking.event_time
        else "",
        "event_location": booking.event_location or "",
        "package_type": booking.package_type or "",
        "special_requests": booking.special_requests or "",
        "total_price": str(booking.total_price or Decimal("0.00")),
    }


def apply_booking_snapshot(booking, snapshot):
    if not snapshot:
        return

    booking.event_type = snapshot.get("event_type", booking.event_type)
    event_date_raw = snapshot.get("event_date")
    event_time_raw = snapshot.get("event_time")
    total_price_raw = snapshot.get("total_price")

    if event_date_raw:
        try:
            booking.event_date = datetime.strptime(event_date_raw, "%Y-%m-%d").date()
        except ValueError:
            pass

    if event_time_raw:
        try:
            booking.event_time = datetime.strptime(event_time_raw, "%H:%M").time()
        except ValueError:
            booking.event_time = None
    else:
        booking.event_time = None

    booking.event_location = snapshot.get("event_location", booking.event_location)
    booking.package_type = snapshot.get("package_type", booking.package_type)
    booking.special_requests = snapshot.get(
        "special_requests", booking.special_requests
    )

    if total_price_raw:
        try:
            booking.total_price = Decimal(str(total_price_raw))
        except (InvalidOperation, TypeError):
            pass


def get_top_reviews():
    """Testimonials para sa Home/About — max 5, isa lang kada customer.

    Admin-picked testimonials (is_testimonial=True) muna; kapag kulang sa 5,
    pinupuno ng pinakamataas na published reviews (5-star muna, tapos pinakabago)
    para laging may maipapakita ang carousel hangga't may published review.
    """
    def _prepare(review):
        review.booking_selection_display = format_booking_selection(
            review.booking.package_type if review.booking else ""
        )
        return review

    seen_users = set()
    top_reviews = []

    # 1) Admin-picked testimonials muna (5-star muna, tapos pinakabago)
    for review in (
        Review.objects.filter(is_testimonial=True)
        .select_related("user", "booking")
        .order_by("-rating", "-created_at")
    ):
        if review.user_id in seen_users:
            continue
        seen_users.add(review.user_id)
        top_reviews.append(_prepare(review))

    # 2) Kung kulang sa 5, punuin ng pinakamataas na published reviews
    if len(top_reviews) < 5:
        for review in (
            Review.objects.exclude(is_testimonial=True)
            .select_related("user", "booking")
            .order_by("-rating", "-created_at")
        ):
            if review.user_id in seen_users:
                continue
            seen_users.add(review.user_id)
            top_reviews.append(_prepare(review))
            if len(top_reviews) >= 5:
                break

    return top_reviews


def _cleanup_legacy_booking_request_states():
    now = timezone.now()
    Booking.objects.filter(edit_requested=True).update(
        edit_requested=False,
        edit_allowed=False,
        edit_request_reason=None,
        edit_original_snapshot=None,
        updated_at=now,
    )
    Booking.objects.filter(status="cancel_requested").update(
        status="confirmed",
        cancel_request_reason=None,
        updated_at=now,
    )


def check_booking_expirations():
    """
    Expire stale bookings.

    Rules:
    - Pending bookings expire after their event date passes without admin approval.
    - Pending-payment bookings expire once the event date starts if no real payment
      was received before the cutoff.
    """
    today = timezone.localdate()
    now = timezone.now()

    expired_pending_bookings = Booking.objects.filter(
        status="pending", event_date__lt=today
    ).select_related("user")
    for booking in expired_pending_bookings:
        booking.status = "expired"
        booking.updated_at = now
        booking.save(update_fields=["status", "updated_at"])
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=(
                f"Your booking #{booking.id} for {booking.event_date} has expired "
                "because it was not confirmed in time."
            ),
        )

    unpaid_due_bookings = (
        Booking.objects.filter(status="pending_payment", event_date__lte=today)
        .select_related("user")
        .prefetch_related("payments")
    )

    for booking in unpaid_due_bookings:
        has_payment_before_cutoff = False
        for payment in booking.payments.all():
            if payment.payment_status == "verified":
                has_payment_before_cutoff = True
                break

            if payment.payment_status != "pending":
                continue

            # Manual GCash pending payments already represent a submitted proof.
            if payment.payment_method == "gcash":
                has_payment_before_cutoff = True
                break

            # PayMongo creates a pending row before checkout is actually paid.
            # Only treat it as a real submitted payment after PayMongo marks it received.
            if payment.payment_method.startswith("paymongo_") and (
                payment.paymongo_payment_id
                or "paid via paymongo" in (payment.notes or "").lower()
            ):
                has_payment_before_cutoff = True
                break

        if has_payment_before_cutoff:
            continue

        booking.status = "expired"
        booking.updated_at = now
        booking.save(update_fields=["status", "updated_at"])
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=(
                f"Your booking #{booking.id} for {booking.event_date} has expired "
                "because no payment was received before the event date."
            ),
        )


# Helper to format "HH:MM" or time object into readable 12-hour time.

def get_end_time_from_str(text):
    match = re.search(r"\(End Time: (\d{2}:\d{2})\)", text)
    if match:
        return match.group(1)
    return None


# Helper to remove existing End Time tag to prevent duplication

def format_time_12h(value):
    if not value:
        return ""
    try:
        if hasattr(value, "strftime"):
            return value.strftime("%I:%M %p").lstrip("0")
        parsed = datetime.strptime(str(value), "%H:%M")
        return parsed.strftime("%I:%M %p").lstrip("0")
    except (ValueError, TypeError):
        return str(value)


# Helper to format full time range string (e.g., "10:00 AM - 12:00 PM")

def remove_end_time_tag(text):
    if not text:
        return ""
    return re.sub(r"\s*\(End Time: \d{2}:\d{2}\)", "", text).strip()


def get_booking_time_range(booking):
    if not booking.event_time:
        return ""
    start_str = format_time_12h(booking.event_time)
    end_time_str = get_end_time_from_str(booking.special_requests or "")
    if end_time_str:
        try:
            end_time_obj = datetime.strptime(end_time_str, "%H:%M").time()
            end_str = format_time_12h(end_time_obj)
            return f"{start_str} - {end_str}"
        except ValueError:
            pass
    return start_str


def format_payment_note_for_display(note):
    note = (note or "").strip()
    if not note:
        return "-"

    try:
        payload = json.loads(note)
    except (TypeError, ValueError, json.JSONDecodeError):
        return note

    if not isinstance(payload, dict):
        return note

    provider = str(payload.get("provider", "")).strip().lower()
    if provider == "paymongo":
        session_status = str(payload.get("session_status", "")).strip()
        parts = ["PayMongo session metadata"]
        if session_status:
            parts.append(f"status: {session_status}")
        return " | ".join(parts)

    return note


BOOKING_TRACKER_ORDER = {
    "pending": 0,
    "pending_payment": 1,
    "confirmed": 2,
    "completed": 3,
}


def build_booking_tracker(booking, has_verified_payment=False):
    """Build the animated status tracker data for the booking details page.

    Returns (steps, message, message_state, failed) where steps is a list of
    dicts with key/label/icon/state/note, and state is one of
    "done", "current", "upcoming", "failed", or "skipped".
    """
    steps = [
        {
            "key": "requested",
            "label": "Requested",
            "icon": "fa-file-signature",
            "state": "upcoming",
            "note": booking.created_at.strftime("%b %d, %Y") if booking.created_at else "",
        },
        {
            "key": "payment",
            "label": "Payment",
            "icon": "fa-wallet",
            "state": "upcoming",
            "note": "Payment verified" if has_verified_payment else "Awaiting payment",
        },
        {
            "key": "confirmed",
            "label": "Confirmed",
            "icon": "fa-circle-check",
            "state": "upcoming",
            "note": "Date locked in",
        },
        {
            "key": "completed",
            "label": "Completed",
            "icon": "fa-cake-candles",
            "state": "upcoming",
            "note": booking.event_date.strftime("%b %d, %Y") if booking.event_date else "",
        },
    ]

    status = booking.status

    if status in BOOKING_TRACKER_ORDER:
        current = BOOKING_TRACKER_ORDER[status]
        for index, step in enumerate(steps):
            if index < current:
                step["state"] = "done"
            elif index == current:
                step["state"] = "current"
        if status == "pending":
            message = "We've received your booking! Our team will review it shortly."
            message_state = "info"
        elif status == "pending_payment":
            message = "Your date is reserved! Settle the payment to lock in your booking."
            message_state = "warn"
        elif status == "confirmed":
            message = "Payment confirmed — everything is set for your event!"
            message_state = "success"
        else:
            message = "Event delivered. Thank you for celebrating with us!"
            message_state = "success"
        if status in ("pending", "pending_payment", "confirmed") and booking.edit_requested:
            message += " An edit request is pending admin approval."
        return steps, message, message_state, False

    if status == "cancel_requested":
        current = 1 if has_verified_payment else 0
        for index, step in enumerate(steps):
            if index < current:
                step["state"] = "done"
            elif index == current:
                step["state"] = "current"
        message = "A cancellation request has been submitted and is awaiting admin approval."
        return steps, message, "warn", False

    # cancelled / expired — terminal (failed) states
    reached = 1 if has_verified_payment else 0
    for index, step in enumerate(steps):
        if index < reached:
            step["state"] = "done"
        elif index == reached:
            step["state"] = "failed"
        else:
            step["state"] = "skipped"
    if status == "expired":
        message = "This booking expired because the payment window closed before it was confirmed."
    else:
        message = "This booking has been cancelled."
        reason = booking.cancel_request_reason or booking.admin_denial_reason
        if reason:
            message += " Reason: " + reason
    return steps, message, "danger", True


def _pdf_link_callback(uri, rel):
    """
    Convert HTML static/media URIs to absolute filesystem paths so xhtml2pdf can find them.
    """
    s_url = settings.STATIC_URL
    s_root = settings.STATIC_ROOT
    m_url = settings.MEDIA_URL
    m_root = settings.MEDIA_ROOT

    path = None

    if uri.startswith(m_url):
        path = os.path.join(m_root, uri.replace(m_url, ""))
    elif uri.startswith(s_url):
        # Try finders first for static files
        rel_path = uri.replace(s_url, "")
        find_res = finders.find(rel_path)
        if find_res:
            if isinstance(find_res, (list, tuple)):
                path = find_res[0]
            else:
                path = find_res
        elif s_root:
            path = os.path.join(s_root, rel_path)
    
    if not path or not os.path.isfile(path):
        # Fallback to absolute path check if it's already a full path
        if os.path.isabs(uri) and os.path.isfile(uri):
            return uri
        return uri

    return path
