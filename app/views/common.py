"""Shared helpers, constants and imports for the app.views package. (split from app/views.py)"""




import hashlib
import io
import json
import logging
import math
import os
import re
import time
import uuid
from functools import lru_cache
from pathlib import Path
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
from django.core.files.storage import default_storage
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
from ..geocoding import GeocodingUnavailable, search_places, valid_coordinates
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors

from ..models import (
    AboutContent,
    AboutJourneyItem,
    AboutValueItem,
    AdditionalOnly,
    AdditionalOnlyPreviewImage,
    AddOn,
    AddOnPreviewImage,
    AdminNotification,
    AuditLog,
    Booking,
    BookingDesignDelivery,
    BookingImage,
    BookingStatusLog,
    BlockedDate,
    CanvasAsset,
    CanvasCategory,
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
    PackagePreviewImage,
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
            getattr(user, "role", None) == 'admin'
            or getattr(user, "is_superuser", False)
        )
    )


def _get_primary_admin_user():
    return (
        User.objects.filter(role="admin").first()
        or User.objects.filter(is_superuser=True).first()
    )


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


def _email_request_limit(request, email, prefix, setting_prefix, label):
    from django.db import OperationalError
    from ..request_protection import RateLimited, client_ip, consume_rules
    ip = client_ip(request)
    window = getattr(settings, setting_prefix + '_RATE_LIMIT_WINDOW_SECONDS', 3600)
    rules = [
        (prefix + ':cooldown', ip, 1, getattr(settings, setting_prefix + '_COOLDOWN_SECONDS', 60), 1),
        (prefix + ':email-cooldown', (email or '').strip().casefold(), 1,
         getattr(settings, setting_prefix + '_COOLDOWN_SECONDS', 60), 1),
        (prefix + ':ip', ip, getattr(settings, setting_prefix + '_RATE_LIMIT_PER_IP', 5), window, 1),
        (prefix + ':email', (email or '').strip().casefold(), getattr(settings, setting_prefix + '_RATE_LIMIT_PER_EMAIL', 3), window, 1),
    ]
    try:
        consume_rules(rules, force=True)
    except OperationalError:
        request._email_retry_after = 5
        request._email_limit_status = 503
        return True, 'Request protection is temporarily unavailable. Please try again in 5 seconds.'
    except RateLimited as exc:
        request._email_retry_after = exc.retry_after
        wait = _format_wait_time(exc.retry_after)
        if exc.scope.endswith((':cooldown', ':email-cooldown')):
            return True, f'Please wait {wait} before requesting another {label}.'
        subject = 'reset attempts' if prefix == 'pwd-reset' else 'verification email requests'
        return True, f'Too many {subject}. Please try again in {wait}.'
    return False, ''


def _is_reset_request_rate_limited(request, email):
    return _email_request_limit(request, email, 'pwd-reset', 'FORGOT_PASSWORD', 'reset code')


def _is_verification_resend_rate_limited(request, email):
    return _email_request_limit(request, email, 'verify-resend', 'VERIFICATION_RESEND', 'verification email')


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
        sent = send_mail(
            subject=f"[Balloorina Admin] {subject}",
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=recipients,
            fail_silently=False,
        )
        return sent == 1
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
    """Return (start_dt, end_dt) datetimes for a booking.

    Priority: bagong event_end_date/event_end_time snapshot → legacy
    "(End Time: HH:MM)" tag sa special_requests → +4-hour default.
    Kapag ang end ay hindi higit sa start (overnight), +1 day sa end date.
    """
    start_dt = (
        datetime.combine(booking.event_date, booking.event_time)
        if booking.event_time
        else None
    )
    end_dt = None
    if start_dt:
        # 1) Stored snapshot (bagong fields)
        if booking.event_end_time:
            end_date = booking.event_end_date or booking.event_date
            end_dt = datetime.combine(end_date, booking.event_end_time)
        # 2) Legacy tag sa special_requests
        if end_dt is None:
            end_time_str = get_end_time_from_str(booking.special_requests or "")
            if end_time_str:
                try:
                    end_dt = datetime.combine(
                        booking.event_date,
                        datetime.strptime(end_time_str, "%H:%M").time(),
                    )
                except ValueError:
                    end_dt = None
        # 3) Default span
        if end_dt is None:
            end_dt = start_dt + timedelta(hours=4)
        # Overnight: end <= start → susunod na araw
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
    return start_dt, end_dt


# -----------------------------
# ⏱️ Duration & overtime policy (SiteSettings-driven)
# -----------------------------
def get_booking_duration_policy():
    """Shared duration/overtime policy (SiteSettings).

    Returns dict: min_hours, included_hours, overtime_rate, max_hours.
    Single source of truth para sa create/edit validation, price breakdown,
    at booking-page JS payload — hindi na kailangang i-duplicate ang defaults.
    """
    try:
        s = SiteSettings.load()
        return {
            "min_hours": int(s.booking_min_duration_hours or 2),
            "included_hours": int(s.booking_included_hours or 3),
            "overtime_rate": Decimal(str(s.booking_overtime_rate or Decimal("0"))),
            "max_hours": int(s.booking_max_duration_hours or 24),
        }
    except Exception:
        # Defensive: kahit may maling settings row, buhay pa rin ang defaults.
        return {
            "min_hours": 2,
            "included_hours": 3,
            "overtime_rate": Decimal("500"),
            "max_hours": 24,
        }


def get_booking_form_availability():
    """Shared picker data for edit forms, including overnight conflicts and self-exclusion."""
    today = timezone.localdate()
    records = []
    for booking in Booking.objects.filter(
        event_date__gte=today - timedelta(days=1),
        status__in=["pending_payment", "confirmed", "completed"],
    ):
        start, end = _booking_time_bounds(booking)
        if not start or not end:
            continue
        cursor = start.date()
        while cursor <= end.date():
            day = datetime.combine(cursor, datetime.min.time())
            lower, upper = max(start, day), min(end, day + timedelta(days=1))
            if upper > lower:
                records.append({"bookingId": booking.pk, "date": cursor.isoformat(),
                    "start": int((lower - day).total_seconds() // 60),
                    "end": int((upper - day).total_seconds() // 60)})
            cursor += timedelta(days=1)
    from ..booking_changes import live_holds
    for hold in live_holds():
        start, end = timezone.localtime(hold.hold_start).replace(tzinfo=None), timezone.localtime(hold.hold_end).replace(tzinfo=None)
        cursor = start.date()
        while cursor <= end.date():
            day = datetime.combine(cursor, datetime.min.time())
            lower, upper = max(start, day), min(end, day + timedelta(days=1))
            if upper > lower:
                records.append({'bookingId':hold.booking_id, 'date':cursor.isoformat(), 'start':int((lower-day).total_seconds()//60), 'end':int((upper-day).total_seconds()//60), 'temporaryHold':True})
            cursor += timedelta(days=1)
    policy = get_booking_duration_policy()
    ranges = {}
    for row in records:
        ranges.setdefault(row["date"], []).append([row["start"], row["end"]])
    return {
        "blockedDates": [{"date": row.date.isoformat(), "reason": row.reason or ""} for row in BlockedDate.objects.filter(date__gte=today)],
        "rangeRecords": records, "bookedRanges": ranges, "todayIso": today.isoformat(),
        "leadDays": SiteSettings.load().booking_lead_time_days or 0,
        "minDurationHours": policy["min_hours"], "includedHours": policy["included_hours"],
        "maxDurationHours": policy["max_hours"], "overtimeRate": str(policy["overtime_rate"]),
    }


def get_booking_logistics_config():
    config = get_service_charge_config()
    origin = get_logistics_origin(config)
    return {"base": str(config.amount or "0"),
        "shopLat": origin[0] if origin else None, "shopLng": origin[1] if origin else None,
        "freeRadius": str(config.free_radius_km or "0"), "perKm": str(config.per_km_rate or "0"),
        "maxCap": str(config.max_fee_cap or "0")}


def get_booking_schedule(booking):
    start, end = _booking_time_bounds(booking)
    minutes = booking.duration_minutes
    if minutes is None and start and end:
        minutes = int((end - start).total_seconds() // 60)
    return {"end_time": end.strftime("%H:%M") if end else "",
        "end_date": end.date().isoformat() if end else "",
        "duration_label": f"{minutes // 60}h {minutes % 60}m" if minutes is not None else "—"}


def compute_overtime(start_time, end_time, start_date=None, policy=None):
    """Compute duration + overtime mula sa start/end (dict result).

    Overnight-aware: kapag end_time <= start_time, +1 day ang end.
    Rules: duration < min_hours → error ('...' sa key na 'error');
           duration <= included_hours → overtime_hours = 0;
           lampas → ceil((duration - included) / 1h) × overtime_rate.

    Returns: {
        duration_minutes, duration_hours, overtime_hours, overtime_fee,
        included_until (HH:MM str | None), error (str, '' kapag okay)
    }
    """
    policy = policy or get_booking_duration_policy()
    result = {
        "duration_minutes": 0,
        "duration_hours": Decimal("0"),
        "overtime_hours": 0,
        "overtime_fee": Decimal("0.00"),
        "included_until": None,
        "error": "",
    }
    if not start_time or not end_time:
        result["error"] = "Start and end time are required."
        return result
    try:
        st = datetime.strptime(str(start_time), "%H:%M").time()
        et = datetime.strptime(str(end_time), "%H:%M").time()
    except (ValueError, TypeError):
        result["error"] = "Invalid time format."
        return result

    base_date = start_date or timezone.localdate()
    start_dt = datetime.combine(base_date, st)
    end_dt = datetime.combine(base_date, et)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)  # overnight / next-day end

    duration = end_dt - start_dt
    duration_minutes = int(duration.total_seconds() // 60)
    result["duration_minutes"] = duration_minutes
    result["duration_hours"] = (duration / timedelta(hours=1))

    included_until_dt = start_dt + timedelta(hours=policy["included_hours"])
    result["included_until"] = included_until_dt.strftime("%H:%M")

    if duration_minutes < policy["min_hours"] * 60:
        result["error"] = (
            f"Please choose an end time that is at least "
            f"{policy['min_hours']} hours after the start time."
        )
        return result

    max_minutes = policy["max_hours"] * 60
    if duration_minutes > max_minutes:
        result["error"] = (
            f"Maximum booking duration is {policy['max_hours']} hours only."
        )
        return result

    if duration_minutes > policy["included_hours"] * 60:
        overtime_minutes = duration_minutes - (policy["included_hours"] * 60)
        # Ceil per hour: 3h01m → 1 billable hour
        billable_hours = -(-overtime_minutes // 60)
        result["overtime_hours"] = billable_hours
        result["overtime_fee"] = (
            Decimal(billable_hours) * policy["overtime_rate"]
        ).quantize(Decimal("0.01"))
    return result



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
        event_date__range=(booking.event_date - timedelta(days=1), booking.event_date + timedelta(days=1)),
        status__in=ACTIVE_BOOKING_STATUSES,
    ).exclude(pk=booking.pk).select_related("user")

    if not booking.event_time:
        # No time info — treat any other active booking on the same date as a conflict.
        from ..booking_changes import hold_conflicts
        return list(candidates.filter(event_date=booking.event_date)) + [h.booking for h in hold_conflicts(booking)]

    b_start, b_end = _booking_time_bounds(booking)
    if not b_start or not b_end:
        return candidates

    conflicts = []
    for candidate in candidates:
        if not candidate.event_time:
            day = datetime.combine(candidate.event_date, datetime.min.time())
            if b_start < day + timedelta(days=1) and b_end > day:
                conflicts.append(candidate)
            continue
        c_start, c_end = _booking_time_bounds(candidate)
        if c_start and c_end and b_start < c_end and b_end > c_start:
            conflicts.append(candidate)
    from ..booking_changes import hold_conflicts
    return conflicts + [h.booking for h in hold_conflicts(booking)]


def get_service_charge_config():
    config, _ = ServiceChargeConfig.objects.get_or_create(
        id=1,
        defaults={
            "amount": Decimal("0.00"),
            "notes": "Includes styling fee, toll fees, fuel, crew meals, and ingress/egress logistics.",
        },
    )
    return config


def haversine_km(lat1, lng1, lat2, lng2):
    """Straight-line distance sa kilometers (Haversine formula — libre, walang API key)."""
    try:
        lat1, lng1, lat2, lng2 = map(float, (lat1, lng1, lat2, lng2))
    except (TypeError, ValueError):
        return None
    if not valid_coordinates(lat1, lng1) or not valid_coordinates(lat2, lng2):
        return None
    radius_km = 6371.0088  # mean Earth radius
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    a = max(0, min(1, a))
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@lru_cache(maxsize=1)
def get_cavite_geometry():
    return json.loads((Path(settings.BASE_DIR) / "app/data/cavite.geojson").read_text(encoding="utf-8"))["geometry"]


def is_cavite_location(lat, lng):
    if not valid_coordinates(lat, lng):
        return False
    lat, lng = float(lat), float(lng)

    def in_ring(ring):
        inside = False
        for first, second in zip(ring, ring[1:] + ring[:1]):
            x1, y1 = first[:2]
            x2, y2 = second[:2]
            # Include locations exactly on the provincial boundary.
            cross = (lng - x1) * (y2 - y1) - (lat - y1) * (x2 - x1)
            if abs(cross) < 1e-12 and min(x1, x2) <= lng <= max(x1, x2) and min(y1, y2) <= lat <= max(y1, y2):
                return True
            if (y1 > lat) != (y2 > lat) and lng < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                inside = not inside
        return inside

    geometry = get_cavite_geometry()
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return any(in_ring(polygon[0]) and not any(in_ring(hole) for hole in polygon[1:]) for polygon in polygons)


def get_logistics_origin(config=None):
    config = config or get_service_charge_config()
    if valid_coordinates(config.shop_lat, config.shop_lng):
        return float(config.shop_lat), float(config.shop_lng)
    address = (SiteSettings.load().address or "").strip()
    if not address:
        return None
    key = "booking-shop-origin:" + hashlib.sha256(address.encode()).hexdigest()
    saved = cache.get(key)
    if saved is not None:
        return saved or None
    try:
        places = search_places(address)
    except GeocodingUnavailable:
        cache.set(key, False, 60)
        return None
    origin = (places[0]["lat"], places[0]["lon"]) if places else None
    cache.set(key, origin or False, 86400 if origin else 60)
    return origin


def compute_logistics_quote(venue_lat, venue_lng):
    """Buong logistics quote para sa venue pin.

    Returns dict:
      base        – Cavite base fee (ServiceChargeConfig.amount)
      distance_km – Haversine km mula shop (None kapag hindi makompute)
      extra       – distance surcharge outside Cavite (0 for Cavite venues)
      total       – base + extra (naka-cap kung may max_fee_cap)
      capped      – True kapag binawas ng cap ang extra
    Cavite venues use the base fee. Outside Cavite: base + billable kilometers
    beyond the configured included distance, with at least one billable kilometer.
    """
    config = get_service_charge_config()
    base = Decimal(config.amount or Decimal("0.00"))
    quote = {
        "base": base,
        "distance_km": None,
        "extra": Decimal("0.00"),
        "total": base,
        "capped": False,
        "in_cavite": None,
        "configured": False,
    }

    if not valid_coordinates(venue_lat, venue_lng):
        return quote
    quote["in_cavite"] = is_cavite_location(venue_lat, venue_lng)
    origin = get_logistics_origin(config)
    if not origin:
        quote["configured"] = quote["in_cavite"]
        return quote
    distance = haversine_km(*origin, venue_lat, venue_lng)
    if distance is None:
        return quote

    quote["distance_km"] = Decimal(str(round(distance, 2)))
    quote["configured"] = True
    free_radius = Decimal(config.free_radius_km or Decimal("0"))
    per_km = Decimal(config.per_km_rate or Decimal("0"))

    if not quote["in_cavite"]:
        extra_km = max(1, math.ceil(distance - float(free_radius)))
        quote["extra"] = Decimal(extra_km) * per_km

    total = base + quote["extra"]
    cap = Decimal(config.max_fee_cap or Decimal("0"))
    if cap > 0 and total > cap:
        quote["capped"] = True
        quote["extra"] = max(cap - base, Decimal("0.00"))
        total = base + quote["extra"]
    quote["total"] = total
    return quote


def get_booking_logistics_fee(booking):
    """Kinuhang logistics fee ng booking — pagkakabahagi ng priority:
    admin override > stored snapshot > live compute mula sa pin > base fee."""
    if booking.logistics_fee_override is not None:
        return booking.logistics_fee_override, booking.logistics_distance_km
    if booking.logistics_fee is not None:
        return booking.logistics_fee, booking.logistics_distance_km

    # Legacy bookings (bago ang snapshot) — compute on the fly.
    quote = compute_logistics_quote(booking.event_lat, booking.event_lng)
    return quote["total"], quote["distance_km"]


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
    logistics_distance_km = None
    if parts:
        # Distance-based logistics: admin override > stored snapshot >
        # live compute mula sa map pin > flat base fee.
        service_charge, logistics_distance_km = get_booking_logistics_fee(booking)

    # ⏱️ Overtime — stored snapshot fee (kinuha sa create/edit at hindi na
    # nagbabago kung i-edit ang SiteSettings rate mamaya).
    overtime_fee = booking.overtime_fee or Decimal("0.00")
    computed_total = subtotal + service_charge + overtime_fee
    result = {
        "items": breakdown,
        "subtotal": subtotal,
        "service_charge": service_charge,
        "logistics_distance_km": logistics_distance_km,
        "overtime_fee": overtime_fee,
        "overtime_hours": booking.overtime_hours or 0,
        "computed_total": computed_total,
        "stored_total": booking.total_price or Decimal("0.00"),
    }
    result.update(get_booking_fee_explanations(booking, service_charge))
    return result


def capture_booking_fee_policy(booking, quote=None, refresh_logistics=True):
    """Store explanation inputs with the quote; viewing a booking never reprices it."""
    config = get_service_charge_config()
    policy = get_booking_duration_policy()
    snapshot = dict(booking.fee_policy_snapshot or {})
    if refresh_logistics or "logistics_base" not in snapshot:
        snapshot.update({
            "logistics_base": str(quote["base"] if quote else config.amount),
            "logistics_notes": config.notes or "",
            "logistics_capped": bool(quote and quote["capped"]),
            "logistics_in_cavite": quote["in_cavite"] if quote else None,
        })
    snapshot.update({"included_hours": policy["included_hours"], "overtime_rate": str(policy["overtime_rate"])})
    snapshot['catalog_items'] = [{'label':i['label'], 'amount':str(i['amount'])} for i in get_booking_price_breakdown(booking)['items']]
    booking.fee_policy_snapshot = snapshot


def get_booking_fee_explanations(booking, logistics_total):
    snapshot = booking.fee_policy_snapshot or {}
    config = get_service_charge_config()
    policy = get_booking_duration_policy()
    base = Decimal(str(snapshot.get("logistics_base", config.amount or 0)))
    extra = max(logistics_total - base, Decimal("0.00"))
    money = lambda value: f"₱{value:,.2f}"
    notes = snapshot.get("logistics_notes", config.notes) or ""
    in_cavite = snapshot.get("logistics_in_cavite")
    if in_cavite is None and valid_coordinates(booking.event_lat, booking.event_lng):
        in_cavite = is_cavite_location(booking.event_lat, booking.event_lng)
    if booking.logistics_fee_override is not None:
        logistics_note = f"Logistics fee: {money(logistics_total)} · Confirmed by our team."
    elif logistics_total == 0:
        logistics_note = "No logistics charge."
    elif base > logistics_total:
        logistics_note = f"Logistics fee: {money(logistics_total)} · Saved booking fee."
    elif extra > 0:
        label = "outside-Cavite distance fee" if in_cavite is False else "distance fee"
        logistics_note = f"Logistics fee: {money(logistics_total)} · {money(base)} base + {money(extra)} {label}."
    elif in_cavite:
        logistics_note = f"Logistics fee: {money(logistics_total)} · Within Cavite, base fee only."
    else:
        logistics_note = f"Logistics fee: {money(logistics_total)} · {money(base)} base; no additional distance fee."
    if snapshot.get("logistics_capped") and booking.logistics_fee_override is None:
        logistics_note += " Maximum logistics fee applied."

    hours = booking.overtime_hours or 0
    rate = (booking.overtime_fee or Decimal("0")) / hours if hours else Decimal(str(snapshot.get("overtime_rate", policy["overtime_rate"])))
    included = snapshot.get("included_hours")
    if included is None and hours:
        duration = booking.duration_minutes
        if duration is None and (booking.event_end_time or get_end_time_from_str(booking.special_requests or "")):
            start, end = _booking_time_bounds(booking)
            if start and end:
                duration = int((end - start).total_seconds() // 60)
        if duration is not None:
            inferred = -(-duration // 60) - hours
            included = inferred if inferred > 0 else None
    rate_label = f"{rate:,.2f}".rstrip("0").rstrip(".")
    if hours and included:
        overtime_note = f"{hours} hr(s) beyond the {included}-hour package × ₱{rate_label}/hr."
    elif hours:
        overtime_note = f"{hours} billable overtime hr(s) × ₱{rate_label}/hr."
    else:
        overtime_note = "No overtime charge."
    return {"logistics_base": base, "logistics_extra": extra, "logistics_notes": notes,
        "logistics_explanation": logistics_note, "overtime_explanation": overtime_note,
        "included_hours": included, "overtime_rate": rate}


def get_booking_display_breakdown(booking):
    """Show recorded totals even if the current catalog prices have changed."""
    breakdown = get_booking_price_breakdown(booking)
    stored_subtotal = breakdown["stored_total"] - breakdown["service_charge"] - breakdown["overtime_fee"]
    saved_items = (booking.fee_policy_snapshot or {}).get('catalog_items', [])
    if saved_items and sum((Decimal(str(i['amount'])) for i in saved_items), Decimal('0')) == stored_subtotal:
        breakdown['items'] = [{'label':i['label'], 'amount':Decimal(str(i['amount']))} for i in saved_items]
        breakdown['subtotal'] = stored_subtotal
        breakdown['computed_total'] = breakdown['stored_total']
        return breakdown
    if breakdown["stored_total"] > 0 and stored_subtotal >= 0 and breakdown["computed_total"] != breakdown["stored_total"]:
        breakdown["items"] = [{"label": f"{booking.package_type or 'Package and extras'} (booked price)", "amount": stored_subtotal}]
        breakdown["subtotal"] = stored_subtotal
        breakdown["computed_total"] = breakdown["stored_total"]
    return breakdown


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
    """Shared deadline policy, also run every minute without page visits."""
    from ..booking_lifecycle import process_booking_deadlines
    return process_booking_deadlines()


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
    # Priority: bagong end snapshot → legacy "(End Time: HH:MM)" tag.
    end_time_obj = None
    if booking.event_end_time:
        end_time_obj = booking.event_end_time
        if booking.event_end_date and booking.event_end_date > booking.event_date:
            # Overnight: may +1 day marker sa dulo ng range.
            return f"{start_str} - {format_time_12h(end_time_obj)} (+1 day)"
    else:
        end_time_str = get_end_time_from_str(booking.special_requests or "")
        if end_time_str:
            try:
                end_time_obj = datetime.strptime(end_time_str, "%H:%M").time()
            except ValueError:
                end_time_obj = None
    if end_time_obj:
        return f"{start_str} - {format_time_12h(end_time_obj)}"
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


def get_booking_lead_time_policy():
    """Shared lead-time policy (SiteSettings.booking_lead_time_days).

    Returns (lead_days, min_bookable_date) where min date = today + lead_days.
    Single source of truth para sa create/edit/API guards — hindi na kailangang
    ulitin ang SiteSettings.load() sa bawat view.
    """
    try:
        lead_days = SiteSettings.load().booking_lead_time_days or 0
    except Exception:
        lead_days = 0
    try:
        lead_days = max(0, int(lead_days))
    except (TypeError, ValueError):
        lead_days = 0
    today = timezone.localdate()
    return lead_days, today + timedelta(days=lead_days)


def get_lead_time_violation_message(booking_date, lead_days=None, min_date=None):
    """User-friendly message kapag rush ang napiling petsa (kasama earliest date)."""
    if lead_days is None or min_date is None:
        lead_days, min_date = get_booking_lead_time_policy()
    return (
        f"Bookings must be made at least {lead_days} day(s) in advance. "
        f"Please choose a date on or after {min_date.strftime('%B %d, %Y')}."
    )
