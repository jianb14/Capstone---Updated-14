"""Booking creation, editing, tracking and admin booking management. (split from app/views.py)"""

from .common import *  # noqa: F401,F403
from .common import _booking_time_bounds, _cleanup_legacy_booking_request_states  # noqa: F401
from .payments import _is_abandoned_paymongo_payment  # noqa: F401


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
        try:
            prefilled_design = UserDesign.objects.select_related('base_package').get(id=design_id, user=request.user)
        except UserDesign.DoesNotExist:
            pass

    # Prepare Calendar Events (Client side: ONLY show approved, confirmed, or completed bookings)
    all_bookings = Booking.objects.filter(
        event_date__gte=timezone.now().date(),
        status__in=["pending_payment", "confirmed", "completed"]
    )
    calendar_events = []

    # Get active packages and optionals for the stepper
    active_packages = Package.objects.filter(is_active=True)
    active_addons = AddOn.objects.filter(is_active=True)
    active_additionals = AdditionalOnly.objects.all()
    service_charge_config = get_service_charge_config()

    # Admin-blocked dates: ipapasa bilang listahan sa template — sa MONTH view
    # ang buong day cell na mismo ang magiging pula (JS/CSS), at nakatago ang
    # pill. Iniwan pa rin bilang events para may makita sa WEEK view (timeGrid).
    blocked_rows = BlockedDate.objects.filter(date__gte=timezone.now().date())
    blocked_dates_payload = [
        {
            "date": blocked.date.isoformat(),
            "reason": blocked.reason or "",
        }
        for blocked in blocked_rows
    ]
    for blocked in blocked_rows:
        calendar_events.append(
            {
                "title": "Unavailable",
                "start": blocked.date.isoformat(),
                "end": None,
                "color": "#7f1d1d",
            }
        )

    for b in all_bookings:
        start_dt = (
            datetime.combine(b.event_date, b.event_time) if b.event_time else None
        )
        end_time_str = get_end_time_from_str(b.special_requests or "")
        end_dt = None
        if end_time_str:
            try:
                end_time_obj = datetime.strptime(end_time_str, "%H:%M").time()
                end_dt = datetime.combine(b.event_date, end_time_obj)
            except ValueError:
                pass

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

    return render(
        request,
        "client/booking/booking_page.html",
        {
            "calendar_events": calendar_events,
            "blocked_dates": blocked_dates_payload,
            "today_iso": timezone.localdate().isoformat(),
            "packages": active_packages,
            "active_addons": active_addons,
            "active_additionals": active_additionals,
            "global_service_charge": service_charge_config.amount,
            "global_service_charge_note": service_charge_config.notes,
            "prefilled_design": prefilled_design,
        },
    )


@login_required
def admin_calendar(request):
    if request.user.role not in ["admin", "staff"]:
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
        end_time_str = get_end_time_from_str(b.special_requests or "")
        end_dt = None
        if end_time_str:
            try:
                end_time_obj = datetime.strptime(end_time_str, "%H:%M").time()
                end_dt = datetime.combine(b.event_date, end_time_obj)
            except ValueError:
                pass

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
            "today_iso": timezone.localdate().isoformat(),
            "blocked_dates": blocked_dates,
        },
    )


@login_required
@require_POST
def admin_blocked_date_create(request):
    """Create a blockout date that clients cannot book."""
    if request.user.role not in ["admin", "staff"]:
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

    if Booking.objects.filter(
        event_date=blocked_date, status__in=ACTIVE_BOOKING_STATUSES
    ).exists():
        messages.error(
            request,
            f"Cannot block {blocked_date.strftime('%B %d, %Y')} — there is already an active booking on this date. Cancel or complete it first.",
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
            + " for bookings.",
        )
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
    if request.user.role not in ["admin", "staff"]:
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

@login_required
def create_booking(request):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    is_ajax = request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest"

    if request.method == "POST":
        start_time = request.POST.get("start_time")
        end_time = request.POST.get("end_time")
        event_date = request.POST.get("event_date")
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

            # 1B. Booking Lead Time Check (Site Settings)
            site_settings = SiteSettings.load()
            lead_days = site_settings.booking_lead_time_days or 0
            if lead_days > 0 and booking_date < today + timedelta(days=lead_days):
                error_msg = (
                    f"Bookings must be made at least {lead_days} day(s) in advance. "
                    f"Please choose a date on or after "
                    f"{(today + timedelta(days=lead_days)).strftime('%B %d, %Y')}."
                )
                if is_ajax:
                    return JsonResponse({"success": False, "message": error_msg})
                messages.error(request, error_msg)
                return redirect("booking_page")

            # 2. Past Time Check (If booking is Today)
            if booking_date == today and start_time:
                booking_time = datetime.strptime(start_time, "%H:%M").time()
                if booking_time < now.time():
                    error_msg = "The selected start time has already passed. Please choose a future time."
                    if is_ajax:
                        return JsonResponse({"success": False, "message": error_msg})
                    messages.error(request, error_msg)
                    return redirect("booking_page")

            # 3. Minimum Duration Check (2 hours)
            if start_time and end_time:
                booking_start_dt = datetime.combine(
                    today, datetime.strptime(start_time, "%H:%M").time()
                )
                booking_end_dt = datetime.combine(
                    today, datetime.strptime(end_time, "%H:%M").time()
                )

                # Handle cases where end time is crossing midnight (though forms usually restrict this)
                if booking_end_dt <= booking_start_dt:
                    booking_end_dt += timedelta(days=1)

                duration = booking_end_dt - booking_start_dt
                if duration < timedelta(hours=2):
                    error_msg = "Please choose an end time that is at least 2 hours after the start time."
                    if is_ajax:
                        return JsonResponse({"success": False, "message": error_msg})
                    messages.error(request, error_msg)
                    return redirect("booking_page")

            # 3A. Validate Time Between 7:00 AM and 6:00 PM
            if start_time and end_time:
                start_dt = datetime.strptime(start_time, "%H:%M")
                end_dt = datetime.strptime(end_time, "%H:%M")
                
                start_hour = start_dt.hour
                start_minute = start_dt.minute
                end_hour = end_dt.hour
                end_minute = end_dt.minute
                
                if start_hour < 7 or start_hour >= 18:
                    error_msg = "Booking hours are 7:00 AM to 6:00 PM only. Please choose a start time within this range."
                    if is_ajax:
                        return JsonResponse({"success": False, "message": error_msg})
                    messages.error(request, error_msg)
                    return redirect("booking_page")
            
                if end_hour < 7 or end_hour > 18 or (end_hour == 18 and end_minute != 0):
                    error_msg = "Booking hours are 7:00 AM to 6:00 PM only. End time must be between 7:00 AM and 6:00 PM."
                    if is_ajax:
                        return JsonResponse({"success": False, "message": error_msg})
                    messages.error(request, error_msg)
                    return redirect("booking_page")

                # Check for midnight crossing / reversed range after hours validation
                crosses_midnight = (end_hour < start_hour) or (end_hour == start_hour and end_minute <= start_minute)
                if crosses_midnight:
                    error_msg = "End time must be later than start time on the same day."
                    if is_ajax:
                        return JsonResponse({"success": False, "message": error_msg})
                    messages.error(request, error_msg)
                    return redirect("booking_page")

            # 4. Double Booking / Overlap Check
            if start_time and end_time:
                new_start = datetime.combine(
                    booking_date, datetime.strptime(start_time, "%H:%M").time()
                )
                new_end = datetime.combine(
                    booking_date, datetime.strptime(end_time, "%H:%M").time()
                )

                # Get active bookings for this date (Approved, confirmed, or completed bookings block new bookings)
                existing_bookings = Booking.objects.filter(
                    event_date=booking_date,
                    status__in=["pending_payment", "confirmed", "completed"]
                )

                for b in existing_bookings:
                    if not b.event_time:
                        continue

                    b_start = datetime.combine(booking_date, b.event_time)
                    # Extract end time from stored string or default to +4 hours
                    b_end_str = get_end_time_from_str(b.special_requests)
                    if b_end_str:
                        b_end = datetime.combine(
                            booking_date, datetime.strptime(b_end_str, "%H:%M").time()
                        )
                    else:
                        b_end = b_start + timedelta(
                            hours=4
                        )  # Default duration assumption

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

        # 4. Validate total_price
        try:
            total_price_val = Decimal(request.POST.get("total_price", "0"))
        except InvalidOperation:
            error_msg = "Invalid price format."
            if is_ajax:
                return JsonResponse({"success": False, "message": error_msg})
            messages.error(request, error_msg)
            return redirect("booking_page")
        if total_price_val <= 0:
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

        booking = Booking.objects.create(
            user=request.user,
            event_type=request.POST.get("event_type"),
            event_date=event_date,
            event_time=start_time,  # Save start time to event_time field
            event_location=request.POST.get("event_location"),
            package_type=request.POST.get("package_type"),
            special_requests=special_requests,
            reference_image=request.FILES.get("reference_image"),
            total_price=total_price_val,
        )

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
                    price_estimate=total_price_val,
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
        send_admin_alert_email(
            f"New Booking #{booking.id}",
            (
                f"A new booking was submitted.\n\n"
                f"Booking ID: #{booking.id}\n"
                f"Customer: {request.user.get_full_name() or request.user.username} ({request.user.email})\n"
                f"Event: {booking.event_type or '—'} on {booking.event_date}"
                f"{' ' + get_booking_time_range(booking) if booking.event_time else ''}\n"
                f"Location: {booking.event_location or '—'}\n"
                f"Total Price: PHP {booking.total_price:,.2f}\n\n"
                f"Review it here: {request.build_absolute_uri(f'/staff/bookings/{booking.id}/view/')}"
            ),
        )

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
def view_booking(request, id):
    check_booking_expirations()
    booking = get_object_or_404(Booking, id=id)

    if request.user != booking.user:
        return HttpResponseForbidden("Not allowed")

    booking.time_range_display = get_booking_time_range(booking)
    payment_history = [
        pay
        for pay in booking.payments.select_related("verified_by").order_by("-created_at")
        if not _is_abandoned_paymongo_payment(pay)
    ]
    # payment_history ay Python list (filtered na), kaya hindi pwedeng
    # gamitin ang .filter() — i-sum na lang direkta ang verified amounts
    total_verified_paid = sum(
        (pay.amount for pay in payment_history if pay.payment_status == "verified"),
        Decimal("0.00"),
    )
    remaining_balance = (booking.total_price or Decimal("0.00")) - total_verified_paid
    cleaned_requests = remove_end_time_tag(booking.special_requests or "")
    source = (request.GET.get("from") or "").strip().lower()
    if source == "my_payments":
        back_url = reverse("my_payments")
        back_label = "Back to My Payments"
    else:
        back_url = reverse("customer_profile")
        back_label = "Back to Dashboard"
    tracker_steps, tracker_message, tracker_message_state, tracker_failed = build_booking_tracker(
        booking, has_verified_payment=total_verified_paid > 0
    )

    return render(
        request,
        "client/booking/booking_detail.html",
        {
            "booking": booking,
            "payment_history": payment_history,
            "total_verified_paid": total_verified_paid,
            "remaining_balance": remaining_balance,
            "cleaned_requests": cleaned_requests,
            "back_url": back_url,
            "back_label": back_label,
            "tracker_steps": tracker_steps,
            "tracker_message": tracker_message,
            "tracker_message_state": tracker_message_state,
            "tracker_failed": tracker_failed,
        },
    )


# -------------------------
# DELETE BOOKING
# -------------------------

@login_required
def edit_booking(request, id):
    booking = get_object_or_404(Booking, id=id)

    if request.user != booking.user:
        return HttpResponseForbidden("Not allowed")

    # Confirmed bookings are final. Only pending bookings can still be edited.
    if booking.status != "pending":
        messages.error(
            request,
            "Confirmed bookings can no longer be edited. Please review details before submission.",
        )
        return redirect("customer_profile")

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
            messages.error(request, "Invalid event date format.")
            return redirect("edit_booking", id=id)

        # Validate time formats (prevents 500 on malformed input)
        for time_value in (start_time, end_time):
            if time_value:
                try:
                    datetime.strptime(time_value, "%H:%M")
                except (ValueError, TypeError):
                    messages.error(request, "Invalid time format.")
                    return redirect("edit_booking", id=id)

        # Validate total price (same as create)
        try:
            total_price_val = Decimal(request.POST.get("total_price", "0"))
        except (InvalidOperation, TypeError, ValueError):
            messages.error(request, "Invalid price format.")
            return redirect("edit_booking", id=id)
        if total_price_val <= 0:
            messages.error(request, "Total price must be greater than 0.")
            return redirect("edit_booking", id=id)
        MAX_PRICE = Decimal("99999999.99")
        if total_price_val > MAX_PRICE:
            messages.error(request, "Total price exceeds the maximum allowed value.")
            return redirect("edit_booking", id=id)

        if booking_date < today:
            messages.error(request, "Cannot change to a past date.")
            return redirect("edit_booking", id=id)

        if start_time and end_time:
            new_start = datetime.combine(
                booking_date, datetime.strptime(start_time, "%H:%M").time()
            )
            new_end = datetime.combine(
                booking_date, datetime.strptime(end_time, "%H:%M").time()
            )

            # Handle cases where end time is crossing midnight
            booking_end_dt_calc = new_end
            if booking_end_dt_calc <= new_start:
                booking_end_dt_calc += timedelta(days=1)

            if (booking_end_dt_calc - new_start) < timedelta(hours=2):
                messages.error(
                    request,
                    "Please choose an end time that is at least 2 hours after the start time.",
                )
                return redirect("edit_booking", id=id)

            existing_bookings = (
                Booking.objects.filter(event_date=booking_date)
                .exclude(id=booking.id)
                .filter(status__in=["pending_payment", "confirmed", "completed"])
            )
            for b in existing_bookings:
                b_start = datetime.combine(booking_date, b.event_time)
                b_end_str = get_end_time_from_str(b.special_requests)
                b_end = (
                    datetime.combine(
                        booking_date, datetime.strptime(b_end_str, "%H:%M").time()
                    )
                    if b_end_str
                    else b_start + timedelta(hours=4)
                )

                if new_start < b_end and new_end > b_start:
                    existing_start = format_time_12h(b_start.time())
                    existing_end = format_time_12h(b_end.time())
                    messages.error(
                        request,
                        f"This time slot is already booked ({existing_start} to {existing_end}). "
                        f"Please choose a different time.",
                    )
                    return redirect("edit_booking", id=id)
        # -----------------------------------------

        if end_time:
            special_requests = f"{special_requests}\n(End Time: {end_time})".strip()

        booking.event_type = request.POST.get("event_type")
        booking.event_date = request.POST.get("event_date")
        booking.event_time = start_time
        booking.event_location = request.POST.get("event_location")
        booking.package_type = request.POST.get("package_type")
        booking.special_requests = special_requests
        booking.total_price = total_price_val

        if request.FILES.get("reference_image"):
            booking.reference_image = request.FILES.get("reference_image")

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

        booking.save()

        log_action(request.user, f"Edited booking #{booking.id}.")
        messages.success(request, "Booking updated successfully!")
        return redirect("customer_profile")

    return render(request, "client/booking/booking_form.html", {"booking": booking})


# -------------------------
# ADMIN APPROVE/DENY BOOKING
# -------------------------

@login_required
def delete_booking(request, id):
    booking = get_object_or_404(Booking, id=id)

    if request.user != booking.user:
        return HttpResponseForbidden("Not allowed")

    if booking.status != "pending":
        messages.error(request, "Only pending bookings can be deleted.")
        return redirect("customer_profile")

    if request.method == "POST":
        booking_id = booking.id
        booking.delete()
        log_action(request.user, f"Deleted booking #{booking_id}.")
        messages.success(request, "Booking deleted successfully!")
        return redirect("customer_profile")

    return render(
        request, "client/booking/booking_delete_confirm.html", {"booking": booking}
    )


@login_required
def admin_booking_list(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    # Auto-expire pending bookings in the past
    check_booking_expirations()
    _cleanup_legacy_booking_request_states()

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
    bookings = Booking.objects.order_by("-created_at")

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
        },
    )


@login_required
def admin_booking_detail(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    check_booking_expirations()
    _cleanup_legacy_booking_request_states()
    booking = get_object_or_404(Booking, id=id)

    # Add formatted time range
    booking.time_range_display = get_booking_time_range(booking)

    # Clean up special requests for display to hide the end time tag
    cleaned_requests = remove_end_time_tag(booking.special_requests or "")
    price_breakdown = get_booking_price_breakdown(booking)

    # Status history timeline
    status_logs = booking.status_logs.select_related("changed_by").all()

    return render(
        request,
        "admin/booking/admin_booking_detail.html",
        {
            "booking": booking,
            "cleaned_requests": cleaned_requests,
            "price_breakdown": price_breakdown,
            "status_logs": status_logs,
        },
    )


# =========================
# ADMIN USER MANAGEMENT
# =========================

@login_required
def admin_booking_action(request, id, action):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking, id=id)

    if action == "approve":
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
                f"Please proceed to payment to confirm your slot."
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
