from ..design_validation import evaluate_saved_design, evaluation_message, design_offer
"""Booking creation, editing, tracking and admin booking management. (split from app/views.py)"""

from .common import *  # noqa: F401,F403
from ..request_protection import deduplicate_submission
from django.http import FileResponse
from PIL import Image, UnidentifiedImageError
from requests.exceptions import RequestException
from .common import _booking_time_bounds, _cleanup_legacy_booking_request_states  # noqa: F401
from .payments import _is_abandoned_paymongo_payment  # noqa: F401
from ..geocoding import GeocodingUnavailable, reverse_place, search_places, valid_coordinates
from ..booking_lifecycle import event_start_at, lifecycle_display, process_booking, set_approval_deadlines
from ..booking_changes import change_context, eligibility, schedule_atomic, ensure_available


@login_required
@require_GET
def booking_place_search(request):
    query = (request.GET.get("q") or "").strip()[:255]
    if len(query) < 3:
        return JsonResponse({"results": []})
    try:
        return JsonResponse({"results": search_places(query)})
    except GeocodingUnavailable:
        return JsonResponse({"error": "Place search is unavailable. Please pin the venue on the map."}, status=503)


@login_required
@require_GET
def booking_place_reverse(request):
    lat, lng = request.GET.get("lat"), request.GET.get("lng")
    if not valid_coordinates(lat, lng):
        return JsonResponse({"error": "Invalid map coordinates."}, status=400)
    try:
        return JsonResponse({"results": reverse_place(float(lat), float(lng))})
    except GeocodingUnavailable:
        return JsonResponse({"error": "Address lookup is unavailable. Your pin is saved; type the venue address."}, status=503)


# -------------------------
# ADMIN CALENDAR PAGE
# -------------------------

@login_required
def booking_page(request):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    design_id = request.GET.get('design_id')
    prefilled_design = None
    if design_id:
        prefilled_design = get_object_or_404(UserDesign, id=design_id, user=request.user)
        evaluation = evaluate_saved_design(prefilled_design)
        if not evaluation['can_book']:
            messages.warning(request, evaluation_message(evaluation))
            return redirect(reverse('design_canvas') + f'?id={prefilled_design.pk}')

    # Prepare Calendar Events (Client side: ONLY show approved, confirmed, or completed bookings)
    all_bookings = Booking.objects.filter(
        event_date__gte=timezone.now().date(),
        status__in=["pending_payment", "confirmed", "completed"]
    )
    calendar_events = []
    booked_ranges = {}

    # Get active packages and optionals for the stepper
    active_packages = Package.objects.filter(is_active=True).prefetch_related("preview_images")
    active_addons = AddOn.objects.filter(is_active=True).prefetch_related("preview_images")
    active_additionals = AdditionalOnly.objects.all().prefetch_related("preview_images")
    service_charge_config = get_service_charge_config()
    logistics_origin = get_logistics_origin(service_charge_config)

    # Admin-blocked dates: ipapasa bilang listahan sa template — ang buong day
    # cell ay magiging gray na "Unavailable" + ban icon (booking-day-blocked),
    # kapareho ng lead-time-blocked na walang event. WALA nang pulang
    # "Unavailable" event pill sa calendar — ang day-cell styling na lang ang
    # nagmamarka ng blocked dates (buo pa rin ang blocked_dates payload).
    blocked_rows = BlockedDate.objects.filter(date__gte=timezone.now().date())
    blocked_dates_payload = [
        {
            "date": blocked.date.isoformat(),
            "reason": blocked.reason or "",
        }
        for blocked in blocked_rows
    ]

    for b in all_bookings:
        start_dt = (
            datetime.combine(b.event_date, b.event_time) if b.event_time else None
        )
        end_dt = None
        if start_dt:
            # Priority: bagong end snapshot → legacy "(End Time: HH:MM)" tag →
            # +4h default. Overnight: +1 day kapag end <= start.
            if b.event_end_time:
                end_date = b.event_end_date or b.event_date
                end_dt = datetime.combine(end_date, b.event_end_time)
            else:
                _legacy_end_str = get_end_time_from_str(b.special_requests or "")
                if _legacy_end_str:
                    try:
                        _legacy_end_obj = datetime.strptime(_legacy_end_str, "%H:%M").time()
                        end_dt = datetime.combine(b.event_date, _legacy_end_obj)
                    except ValueError:
                        end_dt = None
                if end_dt is None:
                    end_dt = start_dt + timedelta(hours=4)
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)

        # Define event color (Client side: All blocked slots appear blue)
        event_color = "#3b82f6"  # Blue for confirmed, completed, and pending_payment

        calendar_events.append(
            {
                "title": get_booking_time_range(b),
                "start": start_dt.isoformat() if start_dt else b.event_date.isoformat(),
                "end": end_dt.isoformat() if end_dt else None,
                "color": event_color,
            }
        )

        # Server-side booked ranges para sa decoupled availability module
        # (static/js/booking_availability.js) — mirror ng client-side na
        # getBookedRangesForDate: iki-clip sa 07:00-18:00, walang end time ay
        # +240 min default gaya ng server overlap check. Overnight bookings
        # (end <= start) ay humahati: [start → 18:00] ngayong araw +
        # [07:00 → end] sa susunod na araw.
        if b.event_date:
            date_key = b.event_date.isoformat()
            if b.event_time:
                start_minutes = b.event_time.hour * 60 + b.event_time.minute
                end_minutes = None
                if b.event_end_time:
                    end_minutes = b.event_end_time.hour * 60 + b.event_end_time.minute
                else:
                    _legacy_str = get_end_time_from_str(b.special_requests or "")
                    if _legacy_str:
                        try:
                            end_parsed = datetime.strptime(_legacy_str, "%H:%M").time()
                            end_minutes = end_parsed.hour * 60 + end_parsed.minute
                        except ValueError:
                            end_minutes = None
                if end_minutes is None:
                    end_minutes = start_minutes + 240
                overnight = end_minutes <= start_minutes

                if overnight:
                    # Span sa petsa ng booking: start → 18:00 (clipped)
                    clipped_start = max(start_minutes, 7 * 60)
                    if 18 * 60 > clipped_start:
                        booked_ranges.setdefault(date_key, []).append(
                            [clipped_start, 18 * 60]
                        )
                    # Span sa susunod na araw: 07:00 → end (clipped)
                    next_date_key = (b.event_date + timedelta(days=1)).isoformat()
                    clipped_end = min(end_minutes, 18 * 60)
                    if clipped_end > 7 * 60:
                        booked_ranges.setdefault(next_date_key, []).append(
                            [7 * 60, clipped_end]
                        )
                else:
                    clipped_start = max(start_minutes, 7 * 60)
                    clipped_end = min(end_minutes, 18 * 60)
                    if clipped_end > clipped_start:
                        booked_ranges.setdefault(date_key, []).append(
                            [clipped_start, clipped_end]
                        )

    # Booking Step 2 preview images — kung ano ang makikita ng client
    # depende sa package/add-on/additional na pinili nya sa Step 1.
    preview_data = {
        "packages": {
            str(p.id): [img.image.url for img in p.preview_images.all() if img.image][:2]
            for p in active_packages
        },
        "addons": {
            str(a.id): [img.image.url for img in a.preview_images.all() if img.image][:2]
            for a in active_addons
        },
        "additionals": {
            str(a.id): [img.image.url for img in a.preview_images.all() if img.image][:2]
            for a in active_additionals
        },
    }

    # ⏱️ Duration/overtime policy — ipinapasa sa JS (inline sa availability
    # payload) para ma-label ang End dropdown at ma-compute ang overtime fee.
    duration_policy = get_booking_duration_policy()
    availability_data = get_booking_form_availability()

    from ..booking_changes import live_holds
    for hold in live_holds():
        calendar_events.append({'title':'Temporarily reserved', 'start':timezone.localtime(hold.hold_start).isoformat(),
            'end':timezone.localtime(hold.hold_end).isoformat(), 'color':'#b88742'})

    return render(
        request,
        "client/booking/booking_page.html",
        {
            "calendar_events": calendar_events,
            "blocked_dates": blocked_dates_payload,
            "availability_data": availability_data,
            "today_iso": timezone.localdate().isoformat(),
            "packages": active_packages,
            "preview_data": preview_data,
            "active_addons": active_addons,
            "active_additionals": active_additionals,
            "global_service_charge": service_charge_config.amount,
            "global_service_charge_note": service_charge_config.notes,
            "logistics_config": {
                "base": str(service_charge_config.amount or "0"),
                "shop_lat": str(logistics_origin[0]) if logistics_origin else "",
                "shop_lng": str(logistics_origin[1]) if logistics_origin else "",
                "free_radius_km": str(service_charge_config.free_radius_km or "0"),
                "per_km_rate": str(service_charge_config.per_km_rate or "0"),
                "max_fee_cap": str(service_charge_config.max_fee_cap or "0"),
            },
            "prefilled_design": prefilled_design,
            "prefilled_offer": design_offer(prefilled_design) if prefilled_design else None,
            "duration_policy": duration_policy,
            "cavite_boundary": get_cavite_geometry(),
        },
    )


@login_required
def admin_calendar(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    _cleanup_legacy_booking_request_states()

    # Show ALL bookings regardless of status or date
    all_bookings = Booking.objects.select_related("user").all()
    calendar_events = []

    # Color mapping per status
    status_colors = {
        "confirmed": "#3b82f6",  # Blue
        "pending": "#d97706",  # Yellow/Amber
        "pending_payment": "#f59e0b",  # Amber
        "completed": "#22c55e",  # Green
        "expired": "#6b7280",  # Gray
        "cancelled": "#ef4444",  # Red
    }

    for b in all_bookings:
        start_dt = (
            datetime.combine(b.event_date, b.event_time) if b.event_time else None
        )
        # Priority: bagong end snapshot → legacy "(End Time: HH:MM)" tag →
        # +4h default. Overnight: +1 day kapag end <= start.
        end_dt = None
        if start_dt:
            if b.event_end_time:
                end_date = b.event_end_date or b.event_date
                end_dt = datetime.combine(end_date, b.event_end_time)
            else:
                end_time_str = get_end_time_from_str(b.special_requests or "")
                if end_time_str:
                    try:
                        end_time_obj = datetime.strptime(end_time_str, "%H:%M").time()
                        end_dt = datetime.combine(b.event_date, end_time_obj)
                    except ValueError:
                        end_dt = None
                if end_dt is None:
                    end_dt = start_dt + timedelta(hours=4)
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)

        # Include client name and time range in the title
        client_name = b.user.first_name or b.user.username
        time_range = get_booking_time_range(b)
        event_title = f"{client_name} — {time_range}" if time_range else client_name

        # Clean special requests for display
        cleaned_requests = remove_end_time_tag(b.special_requests or "")

        calendar_events.append(
            {
                "title": event_title,
                "start": start_dt.isoformat() if start_dt else b.event_date.isoformat(),
                "end": end_dt.isoformat() if end_dt else None,
                "color": status_colors.get(b.status, "#3b82f6"),
                "booking_id": b.id,
                "client_name": f"{b.user.first_name} {b.user.last_name}".strip()
                or b.user.username,
                "event_type": b.event_type or "—",
                "event_location": b.event_location or "—",
                "package_type": b.package_type or "—",
                "status": b.get_status_display(),
                "status_raw": b.status,
                "time_range": time_range or "—",
                "event_date": b.event_date.strftime("%B %d, %Y"),
                "total_price": str(b.total_price),
            }
        )

    from ..booking_changes import live_holds
    for hold in live_holds():
        start, end = timezone.localtime(hold.hold_start), timezone.localtime(hold.hold_end)
        calendar_events.append({'title':f'Change request #{hold.pk} · Temporarily reserved',
            'start':start.isoformat(), 'end':end.isoformat(), 'color':'#b88742', 'booking_id':hold.booking_id,
            'client_name':hold.booking.user.get_full_name() or hold.booking.user.username,
            'event_type':'Proposed booking change', 'event_location':hold.proposed.get('event_location',''),
            'package_type':hold.proposed.get('package_type',''), 'status':'Temporary hold', 'status_raw':'temporary_hold',
            'time_range':f'{start:%I:%M %p} – {end:%I:%M %p}', 'event_date':start.strftime('%B %d, %Y'),
            'total_price':str(hold.quoted_total)})

    # Blocked dates appear as red "Unavailable" events
    blocked_dates = BlockedDate.objects.select_related("created_by").all()
    for blocked in blocked_dates:
        calendar_events.append(
            {
                "title": f"🚫 Unavailable{f' — {blocked.reason}' if blocked.reason else ''}",
                "start": blocked.date.isoformat(),
                "end": None,
                "color": "#7f1d1d",
                "booking_id": None,
                "client_name": "—",
                "event_type": "Blocked Date",
                "event_location": "—",
                "package_type": "—",
                "status": "Unavailable",
                "status_raw": "blocked",
                "time_range": "—",
                "event_date": blocked.date.strftime("%B %d, %Y"),
                "total_price": "—",
                "reason": blocked.reason or "Unavailable",
            }
        )

    return render(
        request,
        "admin/admin_calendar.html",
        {
            "calendar_events": calendar_events,
            "booking_conflict_counts": {
                row["event_date"].isoformat(): row["total"]
                for row in (
                    Booking.objects.filter(event_date__gte=timezone.localdate())
                    .exclude(status__in=["cancelled", "expired"])
                    .values("event_date")
                    .annotate(total=Count("id"))
                )
            },
            "today_iso": timezone.localdate().isoformat(),
            "blocked_dates": blocked_dates,
        },
    )


@login_required
@require_POST
@schedule_atomic
def admin_blocked_date_create(request):
    """Create a blockout date that clients cannot book."""
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    raw_date = (request.POST.get("date") or "").strip()
    reason = (request.POST.get("reason") or "").strip()[:255]

    if not raw_date:
        messages.error(request, "Please choose a date to block.")
        return redirect("admin_calendar")

    try:
        blocked_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, "Invalid date format.")
        return redirect("admin_calendar")

    if blocked_date < timezone.localdate():
        messages.error(request, "Cannot block a date in the past.")
        return redirect("admin_calendar")

    from ..booking_changes import live_holds
    if any(timezone.localtime(hold.hold_start).date() <= blocked_date <= timezone.localtime(hold.hold_end - timedelta(microseconds=1)).date() for hold in live_holds()):
        messages.error(request, 'This date has a temporary hold for an approved change quote. Resolve the quote before blocking this date.')
        return redirect('admin_calendar')

    # 🔴 OPTION A — Conflict-aware block: pinapayagan nang i-block ang date na
    # may laman BASTA may explicit confirmation ("Block Anyway") ng admin.
    # Hindi nagagalaw ang existing bookings — nakikita pa rin sila sa calendar
    # (dimmed + conflict indicator); tanging bagong bookings ang haharangin.
    existing_bookings = (
        Booking.objects.filter(event_date=blocked_date)
        .exclude(status__in=["cancelled", "expired"])
        .select_related("user")
        .order_by("event_time")
    )
    conflict_count = existing_bookings.count()
    confirmed_conflicts = (request.POST.get("confirm_conflicts") or "").strip() == "1"

    if conflict_count and not confirmed_conflicts:
        conflict_summary = ", ".join(
            f"#{b.id} {b.user.username} ({b.get_status_display()})"
            for b in existing_bookings[:5]
        )
        messages.warning(
            request,
            f"Cannot block {blocked_date.strftime('%B %d, %Y')} yet — this date "
            f"already has {conflict_count} booking(s) ({conflict_summary}). "
            "Blocking will prevent NEW bookings, but the existing bookings will "
            "remain visible on the calendar. Click Block Date again and press "
            '"Block Anyway" to proceed.',
        )
        log_action(
            request.user,
            f"Attempted to block {blocked_date.isoformat()} with "
            f"{conflict_count} existing bookings (no confirmation)",
        )
        return redirect("admin_calendar")

    blocked, created = BlockedDate.objects.get_or_create(
        date=blocked_date,
        defaults={"reason": reason, "created_by": request.user},
    )
    if created:
        log_action(
            request.user,
            f"Blocked date {blocked_date.isoformat()}"
            + (f" ({reason})" if reason else "")
            + " for bookings."
            + (
                f" {conflict_count} existing booking(s) remain on this date (confirmed)."
                if conflict_count
                else ""
            ),
        )
        if conflict_count:
            messages.success(
                request,
                f"{blocked_date.strftime('%B %d, %Y')} is now unavailable for NEW "
                f"bookings. The {conflict_count} existing booking(s) remain on "
                "this date and are still visible on the calendar.",
            )
        else:
            messages.success(
                request, f"{blocked_date.strftime('%B %d, %Y')} is now unavailable for booking."
            )
    else:
        messages.info(request, "That date is already blocked.")

    return redirect("admin_calendar")


@login_required
@require_POST
def admin_blocked_date_delete(request, id):
    """Remove a blockout date, making it bookable again."""
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    blocked = get_object_or_404(BlockedDate, id=id)
    blocked_str = blocked.date.isoformat()
    blocked.delete()
    log_action(request.user, f"Unblocked date {blocked_str} for bookings.")
    messages.success(request, f"{blocked_str} is now available for booking again.")
    return redirect("admin_calendar")


# -------------------------
# VIEW BOOKING
# -------------------------

def _parse_optional_coord(value):
    """Step 3 map pin coords — blank/invalid input → None.

    Text location ang required; ang coords ay laging optional kaya walang
    pagkakataong mablock ang booking dito (graceful degradation guard).
    """
    raw = "" if value is None else str(value).strip()
    if not raw:
        return None
    try:
        parsed = Decimal(raw)
        return parsed if parsed.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _clean_optional_field(value, max_length):
    """Trim + hard-cap na haba ng bagong optional na field (walang rejection)."""
    return (value or "").strip()[:max_length]


# Step 4 required rules: theme + palette (max 3 colors). Ginagamit ng
# create_booking (strict) at edit_booking (kapag nasa POST ang keys —
# wipe-guard buhay pa rin).
MAX_PALETTE_COLORS = 3


def _parse_palette_colors(value):
    """Comma-separated palette string → listahan ng trimmed color names."""
    return [c.strip() for c in (value or "").split(",") if c.strip()]


def _validate_design_preferences(theme, palette):
    """Balik error message kapag blank ang theme/palette o sobra sa max."""
    theme = (theme or "").strip()
    colors = _parse_palette_colors(palette)
    if not theme:
        return "Please choose a theme."
    if not colors:
        return "Please pick at least 1 color (up to 3)."
    if len(colors) > MAX_PALETTE_COLORS:
        return "Maximum 3 colors only."
    return ""


@login_required
@deduplicate_submission
@schedule_atomic
def create_booking(request):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    is_ajax = request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest"

    if request.method == "POST":
        selected_design = None
        selected_offer = None
        if request.POST.get("user_design_id"):
            try:
                selected_design = UserDesign.objects.select_for_update().get(pk=request.POST["user_design_id"], user=request.user)
            except (UserDesign.DoesNotExist, ValueError, TypeError):
                if is_ajax:
                    return JsonResponse({"success": False, "message": "Design not found."}, status=404)
                raise Http404("Design not found")
            evaluation = evaluate_saved_design(selected_design)
            if not evaluation["can_book"]:
                if is_ajax:
                    return JsonResponse({"success": False, "message": evaluation_message(evaluation), "evaluation": evaluation}, status=400)
                messages.error(request, evaluation_message(evaluation))
                return redirect(reverse('design_canvas') + f'?id={selected_design.pk}')
            selected_offer = design_offer(selected_design)
            # The linked design determines the booked offer and catalog price.
            request.POST = request.POST.copy()
            request.POST['package_type'] = selected_offer.booking_label
            request.POST['total_price'] = str(selected_offer.price)

        start_time = request.POST.get("start_time")
        end_time = request.POST.get("end_time")
        event_date = request.POST.get("event_date")
        booking_date = None
        special_requests = request.POST.get("special_requests", "")
        special_requests = remove_end_time_tag(special_requests)  # Clean up

        # Combine notes if end_time is provided (since model might only have event_time)
        if end_time:
            special_requests = f"{special_requests}\n(End Time: {end_time})".strip()

        # 0. Validate date/time formats first (prevents 500 on malformed input)
        if event_date:
            try:
                datetime.strptime(event_date, "%Y-%m-%d")
            except (ValueError, TypeError):
                error_msg = "Invalid event date format."
                if is_ajax:
                    return JsonResponse({"success": False, "message": error_msg})
                messages.error(request, error_msg)
                return redirect("booking_page")

        for time_value in (start_time, end_time):
            if time_value:
                try:
                    datetime.strptime(time_value, "%H:%M")
                except (ValueError, TypeError):
                    error_msg = "Invalid time format."
                    if is_ajax:
                        return JsonResponse({"success": False, "message": error_msg})
                    messages.error(request, error_msg)
                    return redirect("booking_page")

        # Validation for past dates/times
        now = timezone.localtime(timezone.now())
        today = now.date()
        overtime_info = None  # ma-i-init bago ang date block (kapag walang date)

        if event_date:
            booking_date = datetime.strptime(event_date, "%Y-%m-%d").date()

            # 1. Past Date Check
            if booking_date < today:
                error_msg = "Cannot book a date in the past."
                if is_ajax:
                    return JsonResponse({"success": False, "message": error_msg})
                messages.error(request, error_msg)
                return redirect("booking_page")

            # 1A. Admin Blocked Date Check
            if BlockedDate.objects.filter(date=booking_date).exists():
                blocked = BlockedDate.objects.filter(date=booking_date).first()
                blocked_reason = f" Reason: {blocked.reason}" if blocked.reason else ""
                error_msg = (
                    f"Sorry, {booking_date.strftime('%B %d, %Y')} is not available "
                    f"for booking.{blocked_reason} Please choose a different date."
                )
                if is_ajax:
                    return JsonResponse({"success": False, "message": error_msg})
                messages.error(request, error_msg)
                return redirect("booking_page")

            # 1B. Booking Lead Time Check (Site Settings — shared policy helper)
            lead_days, min_bookable_date = get_booking_lead_time_policy()
            if lead_days > 0 and booking_date < min_bookable_date:
                error_msg = get_lead_time_violation_message(
                    booking_date, lead_days=lead_days, min_date=min_bookable_date
                )
                if is_ajax:
                    return JsonResponse({"success": False, "message": error_msg})
                messages.error(request, error_msg)
                return redirect("booking_page")

            # 2. Past Time Check (If booking is Today)
            # Manila wall-clock ang basehan (TIME_ZONE = Asia/Manila) para hindi
            # makalusot ang tapos nang oras ngayong araw (hal. 5PM na, 1PM-3PM).
            # Bawal ang start/end na tapos na o kasalukuyang minuto.
            if booking_date == today and (start_time or end_time):
                _now_dt = datetime.combine(today, now.time())
                for _value, _past_msg in (
                    (start_time, "The selected start time has already passed. Please choose a future time."),
                    (end_time, "The selected end time has already passed. Please choose a future time."),
                ):
                    if not _value:
                        continue
                    _booking_time = datetime.strptime(_value, "%H:%M").time()
                    if datetime.combine(booking_date, _booking_time) <= _now_dt:
                        if is_ajax:
                            return JsonResponse({"success": False, "message": _past_msg})
                        messages.error(request, _past_msg)
                        return redirect("booking_page")

            # 3. Duration & overtime policy (SiteSettings-driven):
            #    min 2h (default), included 3h (default), lampas → +rate/hr,
            #    max 24h (overnight allowed — end pwedeng lumagpas ng 6:00 PM).
            overtime_info = None
            if start_time and end_time:
                overtime_info = compute_overtime(
                    start_time, end_time, start_date=booking_date
                )
                if overtime_info["error"]:
                    error_msg = overtime_info["error"]
                    if is_ajax:
                        return JsonResponse({"success": False, "message": error_msg})
                    messages.error(request, error_msg)
                    return redirect("booking_page")

            # 3A. Start window: 7:00 AM – 6:00 PM (operating hours).
            #     Ang END ay hindi na binobound sa 6:00 PM — pwedeng overnight
            #     basta't hindi lalampas sa max duration (na-check sa itaas).
            if start_time:
                start_dt = datetime.strptime(start_time, "%H:%M")

                if start_dt.hour < 7 or start_dt.hour >= 18:
                    error_msg = "Booking hours are 7:00 AM to 6:00 PM only. Please choose a start time within this range."
                    if is_ajax:
                        return JsonResponse({"success": False, "message": error_msg})
                    messages.error(request, error_msg)
                    return redirect("booking_page")


            # 4. Double Booking / Overlap Check (overnight-aware)
            if start_time and end_time:
                new_start = datetime.combine(
                    booking_date, datetime.strptime(start_time, "%H:%M").time()
                )
                new_end = datetime.combine(
                    booking_date, datetime.strptime(end_time, "%H:%M").time()
                )
                if new_end <= new_start:
                    new_end += timedelta(days=1)  # overnight booking

                # Kasama ang bookings sa susunod na araw — pwedeng masakop
                # ng overnight booking ang madaling-araw ng katabing petsa.
                existing_bookings = Booking.objects.filter(
                    event_date__in=[booking_date, booking_date + timedelta(days=1)],
                    status__in=["pending_payment", "confirmed", "completed"]
                )

                for b in existing_bookings:
                    if not b.event_time:
                        continue

                    # Galing sa shared helper: nasusundan ang stored end
                    # snapshot + overnight (+1 day) rule.
                    b_start, b_end = _booking_time_bounds(b)
                    if not b_start or not b_end:
                        continue

                    # Check for Overlap: (StartA < EndB) and (EndA > StartB)
                    if new_start < b_end and new_end > b_start:
                        existing_start = format_time_12h(b.event_time)
                        existing_end = format_time_12h(b_end.time())
                        error_msg = (
                            f"This time slot is already booked ({existing_start} to {existing_end}). "
                            f"Please choose a different time."
                        )
                        if is_ajax:
                            return JsonResponse(
                                {"success": False, "message": error_msg}
                            )
                        messages.error(request, error_msg)
                        return redirect("booking_page")

        if booking_date and start_time and end_time:
            try:
                candidate = Booking(event_date=booking_date, event_time=datetime.strptime(start_time, '%H:%M').time(), event_end_time=datetime.strptime(end_time, '%H:%M').time())
                ensure_available(candidate)
            except ValidationError as exc:
                if is_ajax:
                    return JsonResponse({'success':False, 'message':' '.join(exc.messages)})
                messages.error(request, ' '.join(exc.messages))
                return redirect('booking_page')

        # 4. Validate total_price
        try:
            total_price_val = Decimal(request.POST.get("total_price", "0"))
        except InvalidOperation:
            error_msg = "Invalid price format."
            if is_ajax:
                return JsonResponse({"success": False, "message": error_msg})
            messages.error(request, error_msg)
            return redirect("booking_page")
        if total_price_val <= 0 and not selected_offer:
            error_msg = "Total price must be greater than 0."
            if is_ajax:
                return JsonResponse({"success": False, "message": error_msg})
            messages.error(request, error_msg)
            return redirect("booking_page")
        MAX_PRICE = Decimal("99999999.99")
        if total_price_val > MAX_PRICE:
            error_msg = "Total price exceeds the maximum allowed value."
            if is_ajax:
                return JsonResponse({"success": False, "message": error_msg})
            messages.error(request, error_msg)
            return redirect("booking_page")

        # Step 3 map coords (SMART-REQUIRED: kailangan may pin kapag buhay
        # ang map — anti-tamper laban sa DevTools bypass ng frontend gate.
        # Kapag patay ang map (map_available=0), tuloy sa base + admin review.)
        event_lat = _parse_optional_coord(request.POST.get("event_lat"))
        event_lng = _parse_optional_coord(request.POST.get("event_lng"))
        if (event_lat is None) != (event_lng is None):
            event_lat = event_lng = None
        if event_lat is not None and not Decimal("-90") <= event_lat <= Decimal("90"):
            event_lat = None
        if event_lng is not None and not Decimal("-180") <= event_lng <= Decimal("180"):
            event_lng = None

        # 📍 Smart-required pin (backend gate): kapag buhay ang map pero
        # walang pin, i-reject — hindi pwedeng i-bypass sa DevTools.
        # Kapag map_available=0 (CDN fail), tuloy sa base + admin review.
        map_available = (request.POST.get("map_available") or "1").strip()
        if (event_lat is None or event_lng is None) and map_available != "0":
            error_msg = "Please drop a pin or pick from search so we can compute your exact logistics fee."
            if is_ajax:
                return JsonResponse({"success": False, "message": error_msg})
            messages.error(request, error_msg)
            return redirect("booking_page")

        # Step 3 strength (smart-required pin sa itaas): address min 10 chars para
        # hindi makalusot ang one-word entries tulad ng "QC".
        event_location = (request.POST.get("event_location") or "").strip()
        if len(event_location) < 10:
            error_msg = "Please enter a complete venue address (at least 10 characters)."
            if is_ajax:
                return JsonResponse({"success": False, "message": error_msg})
            messages.error(request, error_msg)
            return redirect("booking_page")

        # Step 4 required: theme + palette (max 3 colors). Motto optional pa rin.
        design_theme = _clean_optional_field(request.POST.get("design_theme"), 100)
        color_palette = _clean_optional_field(request.POST.get("color_palette"), 100)
        design_error = _validate_design_preferences(design_theme, color_palette)
        if design_error:
            if is_ajax:
                return JsonResponse({"success": False, "message": design_error})
            messages.error(request, design_error)
            return redirect("booking_page")

        quote = compute_logistics_quote(event_lat, event_lng)
        if quote["in_cavite"] is False and not quote["configured"]:
            error_msg = "We couldn't calculate logistics for this venue location. Please contact our team before continuing."
            if is_ajax:
                return JsonResponse({"success": False, "message": error_msg})
            messages.error(request, error_msg)
            return redirect("booking_page")

        # ⏱️ I-parse ang event_date string → date object BAGO ang create.
        # Django coerces ito sa DB write, pero ang Python-side attribute ay
        # nananatiling string hangga't hindi nire-refresh mula sa DB — kaya
        # kailangan itong date object para sa date-vs-date comparisons
        # (hal. get_booking_time_range: event_end_date > event_date).
        _event_date_obj = None
        if event_date:
            try:
                _event_date_obj = datetime.strptime(event_date, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                _event_date_obj = None

        booking = Booking.objects.create(
            user=request.user,
            event_type=request.POST.get("event_type"),
            event_date=_event_date_obj or event_date,
            event_time=start_time,  # Save start time to event_time field
            event_location=event_location,
            package_type=request.POST.get("package_type"),
            special_requests=special_requests,
            reference_image=request.FILES.get("reference_image"),
            total_price=total_price_val,
            # 📍 Step 3 (location extras) + 🎨 Step 4 (design preferences)
            event_lat=event_lat,
            event_lng=event_lng,
            venue_landmark=_clean_optional_field(request.POST.get("venue_landmark"), 255),
            design_theme=design_theme,
            color_palette=color_palette,
            motto_text=_clean_optional_field(request.POST.get("motto_text"), 150),
        )

        # ⏱️ Duration/overtime snapshot — galing sa validated compute_overtime
        # (lahat ng validation sa itaas ay pumasa kung umabot dito). Ang
        # _event_date_obj ay na-parse na bago ang create sa itaas.
        if overtime_info is None and start_time and end_time:
            overtime_info = compute_overtime(
                start_time, end_time, start_date=_event_date_obj
            )

        # 🚚 Logistics quote (distance-based) — i-snapshot sa booking para
        # hindi na magbago kung i-edit ni admin ang fee config mamaya.
        booking.logistics_distance_km = quote["distance_km"]
        booking.logistics_fee = quote["total"]

        # ⏱️ Overtime snapshot + end datetime (overnight-aware)
        if overtime_info and not overtime_info["error"]:
            booking.duration_minutes = overtime_info["duration_minutes"]
            booking.overtime_hours = overtime_info["overtime_hours"]
            booking.overtime_fee = overtime_info["overtime_fee"]
            if end_time:
                _start_time_obj = (
                    datetime.strptime(start_time, "%H:%M").time()
                    if start_time else None
                )
                _end_time_obj = datetime.strptime(end_time, "%H:%M").time()
                booking.event_end_time = _end_time_obj
                if _event_date_obj and _start_time_obj is not None:
                    booking.event_end_date = _event_date_obj + (
                        timedelta(days=1) if _end_time_obj <= _start_time_obj
                        else timedelta(days=0)
                    )

        # 🔒 Server-side total recompute (anti-tamper): kapag na-parse ang
        # package parts, ang backend computation ang masusunod — hindi ang
        # total na galing sa JS/DevTools. Fallback: posted total (custom
        # bookings na walang kilalang package name).
        capture_booking_fee_policy(booking, quote)
        breakdown = get_booking_price_breakdown(booking)
        if selected_offer or breakdown["subtotal"] > 0:
            booking.total_price = breakdown["computed_total"]
        booking.save(update_fields=[
            "logistics_distance_km", "logistics_fee", "total_price",
            "duration_minutes", "overtime_hours", "overtime_fee",
            "event_end_date", "event_end_time",
            "fee_policy_snapshot",
        ])

        # Initial status history entry
        log_booking_status(
            booking,
            "",
            booking.status,
            changed_by=request.user,
            notes="Booking submitted by customer.",
        )

        # Associate with UserDesign if provided
        user_design_id = request.POST.get("user_design_id")
        if user_design_id:
            try:
                user_design = UserDesign.objects.get(id=user_design_id, user=request.user)
                # If you want to create a permanent Design record for this booking:
                Design.objects.create(
                    booking=booking,
                    style=user_design.name,
                    color_palette="Custom",
                    image=user_design.thumbnail, # Use the thumbnail as the design image
                    price_estimate=booking.total_price,
                    status='finalized'
                )
            except UserDesign.DoesNotExist:
                pass

        # Save multiple images (up to 4)
        images = request.FILES.getlist("reference_images")

        # Fallback if the form only sent single 'reference_image'
        if not images and request.FILES.get("reference_image"):
            images = [request.FILES.get("reference_image")]

        for img in images[:4]:
            BookingImage.objects.create(booking=booking, image=img)

        log_action(request.user, f"Created a new booking #{booking.id}.")

        # Admin alert email (fail-safe)
        alert_design_lines = ""
        if booking.venue_landmark:
            alert_design_lines += f"Landmark: {booking.venue_landmark}\n"
        if booking.design_theme:
            alert_design_lines += f"Design Theme: {booking.design_theme}\n"
        if booking.color_palette:
            alert_design_lines += f"Color Palette: {booking.color_palette}\n"
        if booking.motto_text:
            alert_design_lines += f"Motto: {booking.motto_text}\n"
        if booking.event_lat is not None and booking.event_lng is not None:
            alert_design_lines += f"Map Pin: {booking.event_lat}, {booking.event_lng}\n"

        send_admin_alert_email(
            f"New Booking #{booking.id}",
            (
                f"A new booking was submitted.\n\n"
                f"Booking ID: #{booking.id}\n"
                f"Customer: {request.user.get_full_name() or request.user.username} ({request.user.email})\n"
                f"Event: {booking.event_type or '—'} on {booking.event_date}"
                f"{' ' + get_booking_time_range(booking) if booking.event_time else ''}\n"
                f"Location: {booking.event_location or '—'}\n"
                f"{alert_design_lines}"
                f"Total Price: PHP {booking.total_price:,.2f}\n\n"
                f"Review it here: {request.build_absolute_uri(f'/staff/bookings/{booking.id}/view/')}"
            ),
        )

        request._submission_succeeded = True
        if is_ajax:
            # Build event data so frontend can add to calendar dynamically
            event_title = (
                f"{start_time} - {end_time} | {request.POST.get('event_type', '')}"
            )
            event_start = f"{event_date}T{start_time}:00" if start_time else event_date
            event_end = f"{event_date}T{end_time}:00" if end_time else None
            return JsonResponse(
                {
                    "success": True,
                    "message": "Your booking has been successfully submitted! Please wait for admin confirmation.",
                }
            )
        messages.success(request, "Booking created successfully!")
        return redirect("booking_page")

    return redirect("booking_page")


# -------------------------
# EDIT BOOKING
# -------------------------

@login_required
@require_GET
def view_booking(request, id):
    """Compatibility URL: customer booking details live only in My Bookings modals."""
    booking = get_object_or_404(Booking, id=id)
    if request.user != booking.user:
        return HttpResponseForbidden("Not allowed")
    mode = "design" if request.GET.get("modal") == "design" else "details"
    return redirect(f"{reverse('customer_profile')}?booking_id={booking.id}&modal={mode}")


@login_required
@require_GET
def booking_modal_content(request, id):
    """The single customer details/design renderer. Never reprice on read."""
    booking = get_object_or_404(Booking, id=id)
    if request.user.role != "customer" or request.user != booking.user:
        return HttpResponseForbidden("Not allowed")
    section = request.GET.get("section", "details")
    if section not in ("details", "design"):
        return HttpResponse("Unknown booking section.", status=400)
    from .profiles import _sync_customer_booking_payment_states
    _sync_customer_booking_payment_states(request.user)
    check_booking_expirations()
    booking = Booking.objects.prefetch_related("images", "designs", "design_deliveries", "payments", "change_requests__payments").get(pk=booking.pk)
    booking.time_range_display = get_booking_time_range(booking)
    booking.schedule = get_booking_schedule(booking)
    booking.price_breakdown = get_booking_display_breakdown(booking)
    payment_history = [
        pay
        for pay in booking.payments.all()
        if not _is_abandoned_paymongo_payment(pay)
    ]
    # payment_history ay Python list (filtered na), kaya hindi pwedeng
    # gamitin ang .filter() — i-sum na lang direkta ang verified amounts
    total_verified_paid = sum(
        (pay.amount for pay in payment_history if pay.payment_status == "verified" and pay.applied_to_booking),
        Decimal("0.00"),
    )
    remaining_balance = (booking.total_price or Decimal("0.00")) - total_verified_paid
    cleaned_requests = remove_end_time_tag(booking.special_requests or "")
    tracker_steps, tracker_message, tracker_message_state, tracker_failed = build_booking_tracker(
        booking, has_verified_payment=total_verified_paid > 0
    )
    lifecycle = lifecycle_display(booking)
    if booking.status == 'pending_payment' and lifecycle['awaiting_verification']:
        tracker_message = 'Your payment has been submitted. Our team is verifying it.'
        tracker_message_state = 'info'
        tracker_steps[1]['note'] = 'Awaiting verification'

    response = render(
        request,
        "client/booking/_details_content.html" if section == "details" else "client/booking/_event_design.html",
        {
            "booking": booking,
            "payment_history": payment_history,
            "total_verified_paid": total_verified_paid,
            "remaining_balance": remaining_balance,
            "overpaid_amount": max(-remaining_balance, Decimal("0.00")),
            "cleaned_requests": cleaned_requests,
            "tracker_steps": tracker_steps,
            "tracker_message": tracker_message,
            "tracker_message_state": tracker_message_state,
            "tracker_failed": tracker_failed,
            "lifecycle": lifecycle,
            **change_context(booking),
        },
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def booking_design_download(request, id, design_id):
    booking = get_object_or_404(Booking, id=id)
    if request.user != booking.user:
        return HttpResponseForbidden("Not allowed")
    delivery = get_object_or_404(BookingDesignDelivery, id=design_id, booking=booking)
    if not delivery.image:
        raise Http404("Design image is no longer available.")
    image_file = None
    try:
        image_file = delivery.image.open("rb")
        image_format = Image.open(image_file).format
        extension, content_type = {
            "JPEG": ("jpg", "image/jpeg"),
            "PNG": ("png", "image/png"),
            "WEBP": ("webp", "image/webp"),
        }[image_format]
        image_file.seek(0)
    except FileNotFoundError:
        if image_file:
            image_file.close()
        raise Http404("Design image is no longer available.")
    except (OSError, RequestException, UnidentifiedImageError, KeyError):
        if image_file:
            image_file.close()
        logger.warning("Design download unavailable for delivery %s", delivery.id)
        return HttpResponse("This design is temporarily unavailable. Please try again later.", status=503)
    response = FileResponse(image_file, as_attachment=True,
        filename=f"booking-{booking.id}-event-design-{delivery.id}.{extension}", content_type=content_type)
    response["Cache-Control"] = "private, no-store"
    return response


# -------------------------
# DELETE BOOKING
# -------------------------

def _booking_edit_error(request, id, message, *, profile=False):
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success':False,'message':message},status=400)
    messages.error(request,message)
    return redirect('customer_profile') if profile else redirect('edit_booking',id=id)


@login_required
@schedule_atomic
def edit_booking(request, id):
    booking = get_object_or_404(Booking, id=id)

    if request.user != booking.user:
        return HttpResponseForbidden("Not allowed")

    if booking.status in ('pending_payment', 'confirmed'):
        if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success':False,'message':'This booking now requires a change request. Reopen Request Changes from your booking list.'},status=409)
        return redirect('request_booking_change', booking_id=booking.pk)
    # Pending bookings retain direct editing; approved bookings use proposals.
    if booking.status != "pending":
        return _booking_edit_error(request, id, "Confirmed bookings can no longer be edited. Please review details before submission.", profile=True)

    if request.method == "POST":
        start_time = request.POST.get("start_time")
        end_time = request.POST.get("end_time")
        special_requests = request.POST.get("special_requests", "")
        special_requests = remove_end_time_tag(
            special_requests
        )  # Clean up before appending

        # --- Validation Logic (Same as Create) ---
        now = timezone.localtime(timezone.now())
        today = now.date()

        # Validate event date format (prevents 500 on malformed/missing input)
        try:
            booking_date = datetime.strptime(
                request.POST.get("event_date", ""), "%Y-%m-%d"
            ).date()
        except (ValueError, TypeError):
            return _booking_edit_error(request, id, "Invalid event date format.")

        # Validate time formats (prevents 500 on malformed input)
        for time_value in (start_time, end_time):
            if time_value:
                try:
                    datetime.strptime(time_value, "%H:%M")
                except (ValueError, TypeError):
                    return _booking_edit_error(request, id, "Invalid time format.")

        # Validate total price (same as create)
        try:
            total_price_val = Decimal(request.POST.get("total_price", "0"))
        except (InvalidOperation, TypeError, ValueError):
            return _booking_edit_error(request, id, "Invalid price format.")
        if not total_price_val.is_finite():
            return _booking_edit_error(request, id, "Invalid price format.")
        if total_price_val <= 0:
            return _booking_edit_error(request, id, "Total price must be greater than 0.")
        MAX_PRICE = Decimal("99999999.99")
        if total_price_val > MAX_PRICE:
            return _booking_edit_error(request, id, "Total price exceeds the maximum allowed value.")

        if booking_date < today:
            return _booking_edit_error(request, id, "Cannot change to a past date.")

        # Booking Lead Time Check (Site Settings): hindi pwedeng i-reschedule
        # sa rush date. Pati parehong araw na inuurong lang ang oras, sakop —
        # booking_date < today + lead_days pa rin ang check (walang exception
        # kapag rush ang petsa, kahit hindi ito binago).
        lead_days, min_bookable_date = get_booking_lead_time_policy()
        if lead_days > 0 and booking_date < min_bookable_date:
            return _booking_edit_error(request, id, get_lead_time_violation_message(
                    booking_date,
                    lead_days=lead_days,
                    min_date=min_bookable_date,
                ))

        # Same-day past-time guard (Manila wall-clock): bawal ang start/end na
        # tapos na o kasalukuyang minuto ngayong araw (hal. 5PM na, 1PM-3PM).
        if booking_date == today and (start_time or end_time):
            _now_dt = datetime.combine(today, now.time())
            for _value, _msg in (
                (start_time, "The selected start time has already passed. Please choose a future time."),
                (end_time, "The selected end time has already passed. Please choose a future time."),
            ):
                if not _value:
                    continue
                if datetime.combine(booking_date, datetime.strptime(_value, "%H:%M").time()) <= _now_dt:
                    return _booking_edit_error(request, id, _msg)

        if start_time and end_time:
            # ⏱️ Duration & overtime policy (same rules sa create_booking):
            # min/included/max hours + rate galing sa SiteSettings. Ang END
            # ay hindi na bound sa 6:00 PM — pwedeng overnight hanggang max.
            overtime_info = compute_overtime(
                start_time, end_time, start_date=booking_date
            )
            if overtime_info["error"]:
                return _booking_edit_error(request, id, overtime_info["error"])

            # Start window: 7:00 AM – 6:00 PM (operating hours).
            start_dt_obj = datetime.strptime(start_time, "%H:%M")
            if start_dt_obj.hour < 7 or start_dt_obj.hour >= 18:
                return _booking_edit_error(request, id, "Booking hours are 7:00 AM to 6:00 PM only. Please choose a start time within this range.")

            new_start = datetime.combine(booking_date, start_dt_obj.time())
            new_end = datetime.combine(
                booking_date, datetime.strptime(end_time, "%H:%M").time()
            )
            if new_end <= new_start:
                new_end += timedelta(days=1)  # overnight

            # Kasama ang bookings sa susunod na araw (overnight overlap).
            existing_bookings = (
                Booking.objects.filter(
                    event_date__in=[booking_date, booking_date + timedelta(days=1)]
                )
                .exclude(id=booking.id)
                .filter(status__in=["pending_payment", "confirmed", "completed"])
            )
            for b in existing_bookings:
                if not b.event_time:
                    continue
                b_start, b_end = _booking_time_bounds(b)
                if not b_start or not b_end:
                    continue

                if new_start < b_end and new_end > b_start:
                    existing_start = format_time_12h(b.event_time)
                    existing_end = format_time_12h(b_end.time())
                    return _booking_edit_error(request, id, f"This time slot is already booked ({existing_start} to {existing_end}). "
                        f"Please choose a different time.")

        if end_time:
            special_requests = f"{special_requests}\n(End Time: {end_time})".strip()

        event_type = (request.POST.get('event_type') or '').strip()
        if not event_type or len(event_type) > 50:
            return _booking_edit_error(request, id, 'Enter an event type with at most 50 characters.')
        booking.event_type = event_type
        booking.event_date = request.POST.get("event_date")
        booking.event_time = start_time
        event_location = (request.POST.get("event_location") or "").strip()
        if len(event_location) < 10:
            return _booking_edit_error(request, id, "Please enter a complete venue address (at least 10 characters).")
        if len(event_location) > 255:
            return _booking_edit_error(request, id, 'Use at most 255 characters for the venue address.')
        booking.event_location = event_location
        booking.package_type = request.POST.get("package_type")
        booking.special_requests = special_requests
        booking.total_price = total_price_val

        # ⏱️ Overtime + end snapshot (kahit grandfather/legacy submit — laging
        # na-recompute mula sa napiling start/end, overnight-aware).
        if start_time and end_time and not overtime_info["error"]:
            booking.duration_minutes = overtime_info["duration_minutes"]
            booking.overtime_hours = overtime_info["overtime_hours"]
            booking.overtime_fee = overtime_info["overtime_fee"]
            _start_t = datetime.strptime(start_time, "%H:%M").time()
            _end_t = datetime.strptime(end_time, "%H:%M").time()
            booking.event_end_time = _end_t
            booking.event_end_date = booking_date + (
                timedelta(days=1) if _end_t <= _start_t else timedelta(days=0)
            )

        # 📍🎨 Bagong Step 3/4 fields — INA-UPDATE LAMANG kapag kasama sa POST.
        # Partial POSTs must preserve existing optional map/design fields.
        if "venue_landmark" in request.POST:
            booking.venue_landmark = _clean_optional_field(
                request.POST.get("venue_landmark"), 255
            )
        # Step 4 strict (grandfather rule sa legacy): kapag nasa POST ang
        # theme/palette keys (edit modal), required + max 3 colors.
        if "design_theme" in request.POST or "color_palette" in request.POST:
            new_theme = _clean_optional_field(request.POST.get("design_theme"), 100)
            new_palette = _clean_optional_field(request.POST.get("color_palette"), 100)
            design_error = _validate_design_preferences(new_theme, new_palette)
            if design_error:
                return _booking_edit_error(request, id, design_error)
            booking.design_theme = new_theme
            booking.color_palette = new_palette
        if "motto_text" in request.POST:
            booking.motto_text = _clean_optional_field(
                request.POST.get("motto_text"), 150
            )
        if "event_lat" in request.POST or "event_lng" in request.POST:
            new_lat = _parse_optional_coord(request.POST.get("event_lat"))
            new_lng = _parse_optional_coord(request.POST.get("event_lng"))
            if (new_lat is None) != (new_lng is None):
                new_lat = new_lng = None
            if new_lat is not None and not Decimal("-90") <= new_lat <= Decimal("90"):
                new_lat = None
            if new_lng is not None and not Decimal("-180") <= new_lng <= Decimal("180"):
                new_lng = None
            booking.event_lat = new_lat
            booking.event_lng = new_lng
            # 📍 Smart-required pin (edit gate): kapag binubuksan ang edit
            # gamit ang bagong modal (may event_lat/lng keys) pero tinanggal
            # ang pin, i-reject — legacy form na walang keys ay hindi apektado.
            edit_map_flag = (request.POST.get("map_available") or "1").strip()
            if (new_lat is None or new_lng is None) and edit_map_flag != "0":
                return _booking_edit_error(request, id, "Please drop a pin or pick from search so we can compute your exact logistics fee.")

        if "event_lat" in request.POST or "event_lng" in request.POST:
            quote = compute_logistics_quote(booking.event_lat, booking.event_lng)
            if quote["in_cavite"] is False and not quote["configured"]:
                return _booking_edit_error(request, id, "We couldn't calculate logistics for this venue location. Please contact our team before continuing.")

        if request.FILES.get("reference_image"):
            booking.reference_image = request.FILES.get("reference_image")

        try:
            ensure_available(booking)
        except ValidationError as exc:
            return _booking_edit_error(request, id, ' '.join(exc.messages))

        # Remove deleted images
        remove_images = request.POST.getlist("remove_images[]")
        if remove_images:
            if "legacy" in remove_images:
                if booking.reference_image:
                    booking.reference_image.delete(save=False)
                remove_images.remove("legacy")
            if remove_images:
                try:
                    remove_ids = [int(i) for i in remove_images if i.isdigit()]
                    if remove_ids:
                        BookingImage.objects.filter(
                            id__in=remove_ids, booking=booking
                        ).delete()
                except ValueError:
                    pass

        # Add new images
        new_images = request.FILES.getlist("reference_images")
        current_img_count = booking.images.count()
        if booking.reference_image:
            current_img_count += 1

        allowed_new = max(0, 4 - current_img_count)

        for img in new_images[:allowed_new]:
            BookingImage.objects.create(booking=booking, image=img)

        # 🔒 Server-side total recompute (anti-tamper — pareho ng create):
        # subtotal + logistics + overtime ang masusunod, hindi ang posted total.
        if "event_lat" in request.POST or "event_lng" in request.POST:
            quote = compute_logistics_quote(booking.event_lat, booking.event_lng)
            booking.logistics_distance_km = quote["distance_km"]
            booking.logistics_fee = quote["total"]
        capture_booking_fee_policy(booking,
            quote if "event_lat" in request.POST or "event_lng" in request.POST else None,
            refresh_logistics="event_lat" in request.POST or "event_lng" in request.POST)
        breakdown = get_booking_price_breakdown(booking)
        if breakdown["subtotal"] > 0:
            booking.total_price = breakdown["computed_total"]

        booking.save()

        log_action(request.user, f"Edited booking #{booking.id}.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success':True,'message':'Booking updated successfully!'})
        messages.success(request, "Booking updated successfully!")
        return redirect("customer_profile")

    return redirect(f"{reverse('customer_profile')}?open_edit={booking.pk}")


# -------------------------
# ADMIN APPROVE/DENY BOOKING
# -------------------------

@login_required
def delete_booking(request, id):
    booking = get_object_or_404(Booking, id=id)

    if request.user != booking.user:
        return HttpResponseForbidden("Not allowed")

    if booking.status != "pending":
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success':False,'message':'Only pending bookings can be deleted.'},status=409)
        messages.error(request, "Only pending bookings can be deleted.")
        return redirect("customer_profile")

    if request.method == "POST":
        booking_id = booking.id
        booking.delete()
        log_action(request.user, f"Deleted booking #{booking_id}.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success':True,'message':'Booking deleted successfully!'})
        messages.success(request, "Booking deleted successfully!")
        return redirect("customer_profile")

    return render(
        request, "client/booking/booking_delete_confirm.html", {"booking": booking}
    )


@login_required
def admin_booking_list(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    # Auto-expire pending bookings in the past
    check_booking_expirations()
    _cleanup_legacy_booking_request_states()

    from .change_management import change_queue_summary, request_list_context
    change_summary = change_queue_summary()
    if request.GET.get('tab') == 'requests':
        response = render(request, 'admin/booking/admin_booking_list.html', request_list_context(request, change_summary))
        response['Cache-Control'] = 'private, no-store'
        return response

    booking_summary = {
        "total": Booking.objects.count(),
        "pending": Booking.objects.filter(status="pending").count(),
        "pending_payment": Booking.objects.filter(status="pending_payment").count(),
        "confirmed": Booking.objects.filter(status="confirmed").count(),
        "cancelled": Booking.objects.filter(status="cancelled").count(),
        "completed": Booking.objects.filter(status="completed").count(),
        "expired": Booking.objects.filter(status="expired").count(),
    }

    status_filter = request.GET.get("status")
    bookings = Booking.objects.order_by("-created_at").prefetch_related('payments', 'design_deliveries', 'change_requests')

    if status_filter:
        bookings = bookings.filter(status=status_filter)

    # Date Range Filter (event date)
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    date_from_valid = date_to_valid = False
    if date_from:
        try:
            parsed_from = datetime.strptime(date_from, "%Y-%m-%d").date()
            bookings = bookings.filter(event_date__gte=parsed_from)
            date_from_valid = True
        except ValueError:
            date_from = ""
    if date_to:
        try:
            parsed_to = datetime.strptime(date_to, "%Y-%m-%d").date()
            bookings = bookings.filter(event_date__lte=parsed_to)
            date_to_valid = True
        except ValueError:
            date_to = ""

    # Search Logic
    search_query = request.GET.get("search")
    if search_query:
        if search_query.startswith("#") and search_query[1:].isdigit():
            # If search query looks like #123, search by ID
            bookings = bookings.filter(id=search_query[1:])
        else:
            bookings = bookings.filter(
                Q(user__username__icontains=search_query)
                | Q(user__email__icontains=search_query)
                | Q(event_type__icontains=search_query)
                | Q(status__icontains=search_query)
                | Q(id__icontains=search_query)
            )

    # Pagination Logic (10 items per page)
    paginator = Paginator(bookings, 10)
    page_number = request.GET.get("page")
    bookings_page = paginator.get_page(page_number)

    # Attach formatted time range for display
    for b in bookings_page:
        b.time_range_display = get_booking_time_range(b)
        b.lifecycle = lifecycle_display(b)

    # Conflict badges: check page rows against active bookings (pending_payment/
    # confirmed/completed) on the same dates with overlapping time ranges.
    page_booking_ids = [b.id for b in bookings_page]
    conflicts_by_booking = {}
    if page_booking_ids:
        page_dates = {b.event_date for b in bookings_page if b.event_date}
        active_candidates = (
            Booking.objects.filter(
                event_date__in=page_dates, status__in=ACTIVE_BOOKING_STATUSES
            )
            .exclude(id__in=page_booking_ids)
            .select_related("user")
        )
        active_by_date = {}
        for candidate in active_candidates:
            active_by_date.setdefault(candidate.event_date, []).append(candidate)

        for b in bookings_page:
            conflicts = []
            if not b.event_date:
                b.has_conflict = False
                continue
            b_start, b_end = _booking_time_bounds(b)
            for candidate in active_by_date.get(b.event_date, []):
                if not b.event_time or not candidate.event_time:
                    conflicts.append(candidate)
                    continue
                c_start, c_end = _booking_time_bounds(candidate)
                if c_start and c_end and b_start and b_end and b_start < c_end and b_end > c_start:
                    conflicts.append(candidate)
            b.has_conflict = bool(conflicts)
            conflicts_by_booking[b.id] = conflicts[:3]

    return render(
        request,
        "admin/booking/admin_booking_list.html",
        {
            "bookings": bookings_page,
            "search_query": search_query or "",
            "status_filter": status_filter or "",
            "date_from": date_from,
            "date_to": date_to,
            "booking_summary": booking_summary,
            "active_tab": "bookings",
            "change_summary": change_summary,
        },
    )


@login_required
def admin_booking_detail(request, id):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    check_booking_expirations()
    _cleanup_legacy_booking_request_states()
    booking = get_object_or_404(Booking, id=id)

    # Add formatted time range
    booking.time_range_display = get_booking_time_range(booking)

    # Clean up special requests for display to hide the end time tag
    cleaned_requests = remove_end_time_tag(booking.special_requests or "")
    price_breakdown = get_booking_display_breakdown(booking)
    original_logistics_fee = (booking.logistics_fee if booking.logistics_fee is not None
        else compute_logistics_quote(booking.event_lat, booking.event_lng)["total"])

    # Status history timeline
    status_logs = booking.status_logs.select_related("changed_by").all()
    request_context = change_context(booking)
    if request_context['change_request']:
        from .change_management import decorate_change
        active_request = decorate_change(request_context['change_request'])
        request_context['change_status_label'] = active_request.admin_status_label

    return render(
        request,
        "admin/booking/admin_booking_detail.html",
        {
            "booking": booking,
            "cleaned_requests": cleaned_requests,
            "price_breakdown": price_breakdown,
            "original_logistics_fee": original_logistics_fee,
            "status_logs": status_logs,
            "lifecycle": lifecycle_display(booking),
            **request_context,
        },
    )


# =========================
# ADMIN — LOGISTICS FEE OVERRIDE (toll/traffic edge case)
# =========================
@login_required
@require_POST
@transaction.atomic
def admin_booking_logistics_override(request, id):
    """Admin manual logistics fee — override/clear + recompute ng total."""
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking.objects.select_for_update(), id=id)
    previous_fee, _ = get_booking_logistics_fee(booking)
    if booking.change_requests.filter(status__in=('pending_review', 'quoted', 'awaiting_payment', 'manual_review')).exists():
        messages.error(request, 'Resolve the active change request before changing the logistics fee, so its accepted quote stays accurate.')
        return redirect('admin_booking_detail', id=booking.pk)
    raw = (request.POST.get("logistics_fee_override") or "").strip()
    clearing = request.POST.get("action") == "reset" or not raw
    if clearing:
        booking.logistics_fee_override = None
        action_note = "cleared the logistics fee override"
    else:
        try:
            override = Decimal(raw)
        except (InvalidOperation, ValueError, TypeError):
            messages.error(request, "Invalid logistics fee.")
            return redirect("admin_booking_detail", id=booking.id)
        if not override.is_finite() or override < 0 or override > Decimal("99999999.99") or override != override.quantize(Decimal("0.01")):
            messages.error(request, "Logistics fee must be between 0 and 99,999,999.99.")
            return redirect("admin_booking_detail", id=booking.id)
        booking.logistics_fee_override = override
        action_note = f"set the logistics fee override to PHP {override:,.2f}"

    current_fee, _ = get_booking_logistics_fee(booking)
    booking.total_price = booking.total_price - previous_fee + current_fee
    booking.save(update_fields=["logistics_fee_override", "total_price"])
    log_action(request.user, f"{request.user.username} {action_note} for booking #{booking.id}.")
    log_booking_status(
        booking, booking.status, booking.status,
        changed_by=request.user, notes=f"Logistics fee override updated ({action_note}).",
    )
    messages.success(request, f"Override removed. Logistics fee restored to ₱{current_fee:,.2f}." if clearing else "Logistics fee updated.")
    return redirect("admin_booking_detail", id=booking.id)


# =========================
# ADMIN — BACKDROP DESIGN DELIVERY (admin → customer, post-payment)
# =========================
DESIGN_DELIVERY_MAX_BYTES = 5 * 1024 * 1024  # 5MB (kapareho ng chat images)
DESIGN_DELIVERY_MAX_IMAGES = 3
DESIGN_DELIVERY_ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}
DESIGN_DELIVERY_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _validate_design_delivery_image(uploaded_file):
    """Balik error message kapag invalid ang design delivery image, else ''."""
    if not uploaded_file:
        return "Please choose a design image to upload."

    if uploaded_file.size > DESIGN_DELIVERY_MAX_BYTES:
        return "Image must be 5MB or smaller."

    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    extension = os.path.splitext(uploaded_file.name or "")[1].lower()
    if (
        content_type not in DESIGN_DELIVERY_ALLOWED_CONTENT_TYPES
        or extension not in DESIGN_DELIVERY_ALLOWED_EXTENSIONS
    ):
        return "Only JPG, PNG, or WEBP images are allowed."

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


@login_required
@require_POST
def admin_booking_design_upload(request, id):
    """Admin → mag-upload ng backdrop design MATAGAL na bayad
    (status confirmed/completed lang, hindi pa-confirmed na pending)."""
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking, id=id)

    if booking.status not in ("confirmed", "completed"):
        messages.error(
            request,
            "Design can only be uploaded once the booking is paid/confirmed.",
        )
        return redirect("admin_booking_detail", id=booking.id)

    if booking.design_deliveries.count() >= DESIGN_DELIVERY_MAX_IMAGES:
        messages.error(
            request,
            f"Maximum of {DESIGN_DELIVERY_MAX_IMAGES} design images per booking. "
            "Delete one first to replace it.",
        )
        return redirect("admin_booking_detail", id=booking.id)

    uploaded = request.FILES.get("design_image")
    error = _validate_design_delivery_image(uploaded)
    if error:
        messages.error(request, error)
        return redirect("admin_booking_detail", id=booking.id)

    caption = (request.POST.get("caption") or "").strip()[:255]
    delivery = BookingDesignDelivery.objects.create(
        booking=booking,
        image=uploaded,
        caption=caption,
        uploaded_by=request.user,
    )

    # Audit + status log + notify customer na may design na siya
    log_action(
        request.user,
        f"Uploaded backdrop design for booking #{booking.id} (design #{delivery.id}).",
    )
    log_booking_status(
        booking,
        booking.status,
        booking.status,
        changed_by=request.user,
        notes="Backdrop design uploaded and delivered to customer.",
    )
    Notification.objects.create(
        user=booking.user,
        booking=booking,
        message=(
            f"Your backdrop design for booking #{booking.id} is ready! "
            "Open your booking details to view and download it. 🎨"
        ),
    )

    messages.success(request, "Backdrop design uploaded and sent to the customer.")
    return redirect("admin_booking_detail", id=booking.id)


@login_required
@require_POST
def admin_booking_design_delete(request, id, design_id):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking, id=id)
    delivery = get_object_or_404(
        BookingDesignDelivery, id=design_id, booking=booking
    )

    image_name = delivery.image.name if delivery.image else ""
    delivery.delete()
    # Burahin din ang file sa storage (Cloudinary/media) para hindi bakante.
    if image_name:
        try:
            delivery_image_storage = default_storage
            if delivery_image_storage.exists(image_name):
                delivery_image_storage.delete(image_name)
        except Exception:
            pass

    log_action(
        request.user,
        f"Deleted backdrop design #{design_id} from booking #{booking.id}.",
    )
    messages.success(request, "Design image deleted.")
    return redirect("admin_booking_detail", id=booking.id)


# =========================
# ADMIN USER MANAGEMENT
# =========================

@login_required
@transaction.atomic
@schedule_atomic
def admin_booking_action(request, id, action):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking.objects.select_for_update(), id=id)
    process_booking(booking.pk)
    booking.refresh_from_db()

    if action == "approve":
        if event_start_at(booking) <= timezone.now():
            messages.error(request, "This event has already started. Review or reschedule it before approval.")
            return redirect('admin_booking_detail', id=booking.id)
        if booking.status != "pending":
            messages.error(request, "Only pending bookings can be approved.")
            return redirect("admin_booking_list")

        # CONFLICT DETECTION: block approval if an ACTIVE booking
        # (pending_payment / confirmed / completed) already occupies this
        # date and overlapping time range.
        active_conflicts = list(find_active_booking_conflicts(booking))
        if active_conflicts:
            conflict_ids = ", ".join(f"#{c.id}" for c in active_conflicts[:3])
            messages.error(
                request,
                f"Cannot approve booking #{booking.id}: it conflicts with "
                f"active booking(s) {conflict_ids} on {booking.event_date}. "
                "Resolve the schedule conflict first.",
            )
            return redirect("admin_booking_list")

        old_status = booking.status
        booking.status = "pending_payment"
        set_approval_deadlines(booking)
        booking.admin_denial_reason = None
        booking.save()
        log_booking_status(
            booking,
            old_status,
            booking.status,
            changed_by=request.user,
            notes="Approved by admin.",
        )

        # Auto-cancel other PENDING bookings on the same date that OVERLAP in time
        potential_conflicts = Booking.objects.filter(
            event_date=booking.event_date,
            status="pending",
        ).exclude(id=booking.id)

        b_start, b_end = _booking_time_bounds(booking)

        cancelled_count = 0
        for conflict in potential_conflicts:
            should_cancel = False
            reason = (
                "Another booking was approved for this date. "
                "Please choose a different date."
            )
            # Check for overlap if both have times
            if b_start and b_end and conflict.event_time:
                c_start, c_end = _booking_time_bounds(conflict)
                if c_start and c_end and b_start < c_end and b_end > c_start:
                    should_cancel = True
                    reason = (
                        "Another booking was approved for this time slot. "
                        "Please choose a different time or date."
                    )
            else:
                # If either doesn't have time, we assume they conflict (old behavior for safety)
                should_cancel = True

            if should_cancel:
                conflict_old_status = conflict.status
                conflict.status = "cancelled"
                conflict.admin_denial_reason = reason
                conflict.save()
                log_booking_status(
                    conflict,
                    conflict_old_status,
                    conflict.status,
                    changed_by=request.user,
                    notes=f"Auto-cancelled: booking #{booking.id} was approved for this slot.",
                )
                Notification.objects.create(
                    user=conflict.user,
                    booking=conflict,
                    message=(
                        f"We're sorry, but your booking #{conflict.id} on "
                        f"{conflict.event_date} was not approved because another "
                        f"booking was already confirmed for that time slot. "
                        f"Please book a different time or date."
                    ),
                )
                cancelled_count += 1

        # Notify the approved customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=(
                f"Great news! Your booking #{booking.id} has been approved! 🎉 "
                f"Please proceed to payment by {timezone.localtime(booking.payment_due_at):%b %d, %Y at %I:%M %p} to confirm your slot."
            ),
        )

        # Admin notification
        AdminNotification.objects.create(
            booking=booking,
            user=booking.user,
            message=(
                f"Booking #{booking.id} approved by {request.user.get_full_name() or request.user.username}."
                + (
                    f" {cancelled_count} conflicting booking(s) auto-cancelled."
                    if cancelled_count
                    else ""
                )
            ),
        )

        log_action(
            request.user,
            f"Approved booking #{booking.id} for '{booking.user.username}'."
            + (
                f" Auto-cancelled {cancelled_count} conflicting booking(s)."
                if cancelled_count
                else ""
            ),
        )
        messages.success(
            request,
            f"Booking #{booking.id} approved! Customer has been notified to proceed with payment."
            + (
                f" {cancelled_count} conflicting booking(s) were auto-cancelled."
                if cancelled_count
                else ""
            ),
        )

    elif action == "confirm":
        if booking.status not in ('pending_payment', 'confirmed') or not booking.payments.filter(payment_status='verified', applied_to_booking=True, amount__gt=0).exists():
            messages.error(request, "A verified payment is required. Expired or cancelled bookings cannot be confirmed automatically.")
            return redirect('admin_booking_detail', id=booking.id)
        old_status = booking.status
        booking.status = "confirmed"
        booking.admin_denial_reason = None
        booking.save()
        log_booking_status(
            booking,
            old_status,
            booking.status,
            changed_by=request.user,
            notes="Confirmed by admin.",
        )
        log_action(
            request.user,
            f"Confirmed booking #{booking.id} for '{booking.user.username}'.",
        )

        # Notify Customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=f"Hooray! Your booking #{booking.id} is now CONFIRMED! See you soon! 🎉",
        )
        messages.success(request, "Booking confirmed!")
    elif action == "deny":
        if request.method != "POST":
            messages.error(request, "Please provide a denial reason.")
            return redirect("admin_booking_list")

        deny_reason = request.POST.get("deny_reason", "").strip()
        if not deny_reason:
            messages.error(request, "Denial reason is required.")
            return redirect("admin_booking_list")

        old_status = booking.status
        booking.status = "cancelled"
        booking.admin_denial_reason = deny_reason
        booking.save()
        log_booking_status(
            booking,
            old_status,
            booking.status,
            changed_by=request.user,
            notes=f"Denied. Reason: {deny_reason}",
        )

        # Notify Customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=f"We're sorry, but your booking #{booking.id} was NOT approved. Reason: {deny_reason}",
        )
        log_action(
            request.user, f"Denied booking #{booking.id} for '{booking.user.username}'."
        )
        messages.success(request, "Booking denied!")
    elif action == "complete":
        old_status = booking.status
        booking.status = "completed"
        booking.admin_denial_reason = None
        booking.save()
        log_booking_status(
            booking,
            old_status,
            booking.status,
            changed_by=request.user,
            notes="Marked as completed by admin.",
        )

        # Notify Customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=f"Thank you for trusting us! Your booking #{booking.id} is now COMPLETED. We hope you enjoyed our service! ❤️ Please feel free to leave a review about your experience! 😊",
        )
        log_action(
            request.user,
            f"Marked booking #{booking.id} as completed for '{booking.user.username}'.",
        )
        messages.success(request, "Booking marked as completed!")

    return redirect("admin_booking_list")
