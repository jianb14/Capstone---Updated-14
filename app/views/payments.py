"""Payments: PayMongo checkout/webhooks, GCash config, receipts. (split from app/views.py)"""

from .common import *  # noqa: F401,F403


def _first_non_empty(*values):
    for value in values:
        if isinstance(value, str):
            value = value.strip()
        if value:
            return value
    return ""


def _extract_paymongo_payer_details(checkout_data=None, payment_data=None):
    checkout_attrs = ((checkout_data or {}).get("data") or {}).get("attributes") or {}
    payment_attrs = ((payment_data or {}).get("data") or {}).get("attributes") or {}

    checkout_billing = checkout_attrs.get("billing") or {}
    payment_billing = payment_attrs.get("billing") or {}
    payment_source = payment_attrs.get("source") or {}
    payment_source_attrs = payment_source.get("attributes") or {}
    payment_source_billing = payment_source_attrs.get("billing") or {}

    payer_name = _first_non_empty(
        checkout_billing.get("name"),
        payment_billing.get("name"),
        payment_source_billing.get("name"),
    )
    payer_phone = _first_non_empty(
        checkout_billing.get("phone"),
        payment_billing.get("phone"),
        payment_source_billing.get("phone"),
    )

    return payer_name, payer_phone


def _extract_paymongo_payment_reference(checkout_data=None, payment_data=None):
    checkout_attrs = ((checkout_data or {}).get("data") or {}).get("attributes") or {}
    payment_attrs = ((payment_data or {}).get("data") or {}).get("attributes") or {}

    checkout_payments = checkout_attrs.get("payments") or []
    if isinstance(checkout_payments, list):
        for item in checkout_payments:
            payment_id = (item or {}).get("id")
            if payment_id:
                return payment_id

    payment_id = ((payment_data or {}).get("data") or {}).get("id") or ""
    if payment_id:
        return payment_id

    source = payment_attrs.get("source") or {}
    source_id = source.get("id") or ""
    if source_id.startswith("pay_"):
        return source_id

    return ""


# -------------------------
# BOOKING PAGE (Calendar + Form)
# -------------------------

def _refresh_paymongo_payment_record(payment):
    if not payment.payment_method.startswith("paymongo_"):
        return payment
    if not payment.paymongo_checkout_session_id:
        return payment

    needs_refresh = (
        not payment.paymongo_payment_id
        or str(payment.paymongo_payment_id).startswith("pi_")
        or not payment.gcash_sender_name
        or not getattr(payment, "paymongo_contact_number", "")
    )
    if not needs_refresh:
        return payment

    checkout_data = retrieve_paymongo_checkout_session(payment.paymongo_checkout_session_id)
    if not checkout_data:
        return payment

    payer_name, payer_phone = _extract_paymongo_payer_details(checkout_data=checkout_data)
    actual_payment_id = _extract_paymongo_payment_reference(checkout_data=checkout_data)

    update_fields = []
    if actual_payment_id and payment.paymongo_payment_id != actual_payment_id:
        payment.paymongo_payment_id = actual_payment_id
        update_fields.append("paymongo_payment_id")
    if payer_name and payment.gcash_sender_name != payer_name:
        payment.gcash_sender_name = payer_name
        update_fields.append("gcash_sender_name")
    if payer_phone and getattr(payment, "paymongo_contact_number", "") != payer_phone:
        payment.paymongo_contact_number = payer_phone
        update_fields.append("paymongo_contact_number")

    if update_fields:
        payment.save(update_fields=update_fields)

    return payment


# =============================================================================
# DOWNLOAD PAYMENT RECEIPT PDF (Customer)
# =============================================================================

@login_required
def my_payments(request):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    check_booking_expirations()
    user = request.user
    allowed_tabs = {"action_required", "remaining_balances", "payment_history"}
    active_tab = request.GET.get("tab", "action_required").strip()
    if active_tab not in allowed_tabs:
        active_tab = "action_required"

    # Payment history filters
    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()

    # Include abandoned PayMongo attempts so failed/expired checkouts remain
    # visible in the customer's history as an audit trail (they are excluded
    # from every action queue and never block retries).
    payments_qs = (
        Payment.objects.filter(booking__user=user)
        .select_related("booking")
        .prefetch_related("booking__images", "booking__payments")
        .order_by("-created_at")
    )

    if search_query:
        payments_qs = payments_qs.filter(
            Q(transaction_ref__icontains=search_query)
            | Q(gcash_reference_number__icontains=search_query)
            | Q(booking__id__icontains=search_query)
        )
    if status_filter:
        payments_qs = payments_qs.filter(payment_status=status_filter)

    pending_count = Payment.objects.filter(
        booking__user=user, payment_status="pending"
    ).exclude(
        _abandoned_paymongo_payment_query()
    ).count()
    verified_count = Payment.objects.filter(
        booking__user=user, payment_status="verified"
    ).count()
    rejected_count = Payment.objects.filter(
        booking__user=user, payment_status="rejected"
    ).count()
    total_records = payments_qs.count()
    total_pending_payment_count = pending_count

    payments_paginator = Paginator(payments_qs, 6)
    payments_page_number = request.GET.get("payments_page", 1)
    payments_page_obj = payments_paginator.get_page(payments_page_number)

    # Attach booking/payment summary fields for detailed tables and modal
    for pay in payments_page_obj:
        booking_payments = list(pay.booking.payments.all())
        verified_payments = [
            p for p in booking_payments if p.payment_status == "verified"
        ]
        verified_paid = sum(
            (p.amount for p in verified_payments),
            Decimal("0.00"),
        )
        booking_total = pay.booking.total_price or Decimal("0.00")
        booking_remaining = booking_total - verified_paid
        if booking_remaining < Decimal("0.00"):
            booking_remaining = Decimal("0.00")

        pay.booking.time_range_display = get_booking_time_range(pay.booking)
        pay.booking.total_verified_paid = verified_paid
        pay.booking.booking_remaining = booking_remaining
        pay.booking.total_payment_records = len(booking_payments)
        pay.booking.cleaned_special_requests = remove_end_time_tag(pay.booking.special_requests or "")
        pay.pending_info_url = reverse("payment_page", kwargs={"booking_id": pay.booking.id})
        # Failed/expired PayMongo attempts stay in the history as an audit
        # trail, but never look like actionable "Pending" payments.
        pay.is_failed_attempt = _is_abandoned_paymongo_payment(pay)
        if pay.is_failed_attempt:
            pay.failed_label = (
                "Expired" if "expired" in (pay.notes or "").lower() else "Failed"
            )
        pay.show_pending_info_button = (
            pay.payment_status == "pending" and not pay.is_failed_attempt
        )

        # Per-booking payment journey for the client "Payment Activity"
        # timeline in the View Details modal (newest first, para nasa taas
        # ang pinakabagong record). Uses the already-prefetched booking
        # payments — no extra queries.
        activity_entries = []
        for p in sorted(booking_payments, key=lambda x: x.created_at, reverse=True):
            failed = _is_abandoned_paymongo_payment(p)
            if failed:
                status_display = (
                    "Expired" if "expired" in (p.notes or "").lower() else "Failed"
                )
            else:
                status_display = p.get_payment_status_display()
            activity_entries.append(
                {
                    "id": p.id,
                    "status": p.payment_status,
                    "status_display": status_display,
                    "failed": failed,
                    "amount": f"{p.amount:.2f}",
                    "type": p.get_payment_type_display(),
                    "method": p.get_payment_method_display(),
                    "date": timezone.localtime(p.created_at).strftime(
                        "%b %d, %Y %I:%M %p"
                    ),
                    "ref": p.transaction_ref or "",
                    "rejected": p.payment_status == "rejected",
                    "notes": p.notes or "",
                }
            )
        pay.booking.payments_json = json.dumps(activity_entries)

    # Action-required: approved bookings awaiting payment
    ar_search_query = request.GET.get("ar_search", "").strip()
    ar_action_filter = request.GET.get("ar_action", "").strip()

    all_action_bookings = (
        Booking.objects.filter(user=user, status__in=["pending_payment", "confirmed"])
        .prefetch_related("payments", "images")
        .order_by("-updated_at", "-id")
    )

    if ar_search_query:
        all_action_bookings = all_action_bookings.filter(
            Q(id__icontains=ar_search_query) | Q(event_type__icontains=ar_search_query)
        )

    # Filter bookings with remaining balance
    action_required_list = []
    partial_bookings = []  # Bookings with partial verified payments
    
    for b in all_action_bookings:
        booking_payments = [
            pay for pay in b.payments.all() if not _is_abandoned_paymongo_payment(pay)
        ]
        verified_payments = [p for p in booking_payments if p.payment_status == "verified"]
        verified_paid = sum((p.amount for p in verified_payments), Decimal("0.00"))
        remaining = (b.total_price or Decimal("0.00")) - verified_paid
        if remaining < Decimal("0.00"):
            remaining = Decimal("0.00")

        if remaining > Decimal("0.00"):
            b.time_range_display = get_booking_time_range(b)
            b.booking_remaining = remaining
            b.total_verified_paid = verified_paid
            b.total_payment_records = len(booking_payments)

            latest_payment = max(booking_payments, key=lambda p: p.created_at) if booking_payments else None
            latest_verified_payment = (
                max(
                    verified_payments,
                    key=lambda p: (p.paid_at or p.updated_at or p.created_at),
                )
                if verified_payments
                else None
            )

            if latest_verified_payment:
                b.latest_verified_paid_at = (
                    latest_verified_payment.paid_at
                    or latest_verified_payment.updated_at
                    or latest_verified_payment.created_at
                )
                b.latest_verified_paid_amount = latest_verified_payment.amount
            else:
                b.latest_verified_paid_at = None
                b.latest_verified_paid_amount = Decimal("0.00")

            b.last_payment_status_display = (
                latest_payment.get_payment_status_display()
                if latest_payment
                else "No Payment Yet"
            )
            b.last_payment_submitted_at = (
                latest_payment.created_at if latest_payment else None
            )

            # Attach latest payment details for modal
            if latest_payment:
                b.latest_pay_amount = latest_payment.amount
                b.latest_pay_type = latest_payment.get_payment_type_display()
                b.latest_pay_method = latest_payment.get_payment_method_display()
                b.latest_pay_status = latest_payment.get_payment_status_display()
                b.latest_pay_date = latest_payment.created_at
                b.latest_pay_ref = latest_payment.transaction_ref
                b.latest_pay_payment_id = latest_payment.paymongo_payment_id or ""
                b.latest_pay_sender = latest_payment.gcash_sender_name or ""
                b.latest_pay_checkout_session_id = latest_payment.paymongo_checkout_session_id or ""
                b.latest_pay_verified = latest_payment.paid_at
                b.latest_pay_notes = latest_payment.notes or ""
            else:
                b.latest_pay_amount = Decimal("0.00")
                b.latest_pay_status = ""

            # If customer already submitted a payment that is awaiting admin review,
            # this booking should no longer appear under "Action Required".
            if latest_payment and latest_payment.payment_status == "pending":
                if _is_incomplete_paymongo_payment(latest_payment):
                    is_partial = verified_paid > Decimal("0.00")
                    b.payment_action_display = (
                        "Continue Payment" if not is_partial else "Pay Balance"
                    )
                    b.payment_action_disabled = False
                    if is_partial:
                        partial_bookings.append(b)
                    else:
                        action_required_list.append(b)
                    b.cleaned_special_requests = remove_end_time_tag(
                        b.special_requests or ""
                    )
                    continue
                continue
                
            if latest_payment and latest_payment.payment_status == "rejected":
                b.payment_action_display = "Re-upload"
                b.payment_action_disabled = False
                action_required_list.append(b)
            else:
                is_partial = verified_paid > Decimal("0.00")
                b.payment_action_display = "Pay Balance" if is_partial else "Pay Now"
                b.payment_action_disabled = False
                
                if is_partial:
                    partial_bookings.append(b)
                else:
                    action_required_list.append(b)
            
            b.cleaned_special_requests = remove_end_time_tag(b.special_requests or "")

    action_required_total_count = len(action_required_list)
    partial_total_count = len(partial_bookings)

    ar_paginator = Paginator(action_required_list, 6)
    ar_page_number = request.GET.get("ar_page", 1)
    action_required_page_obj = ar_paginator.get_page(ar_page_number)

    # Paginate partial bookings (Remaining Balances)
    partial_paginator = Paginator(partial_bookings, 6)
    partial_page_number = request.GET.get("partial_page", 1)
    partial_page_obj = partial_paginator.get_page(partial_page_number)

    return render(
        request,
        "client/my_payments.html",
        {
            "pending_count": pending_count,
            "verified_count": verified_count,
            "rejected_count": rejected_count,
            "total_pending_payment_count": total_pending_payment_count,
            "action_required_total_count": action_required_total_count,
            "partial_total_count": partial_total_count,
            "partial_page_obj": partial_page_obj,
            "total_records": total_records,
            "search_query": search_query,
            "status_filter": status_filter,
            "ar_search_query": ar_search_query,
            "ar_action_filter": ar_action_filter,
            "action_required_page_obj": action_required_page_obj,
            "payments_page_obj": payments_page_obj,
            "active_tab": active_tab,
        },
    )


# =============================================================================
# ADMIN SERVICE MANAGEMENT
# =============================================================================

@login_required
def download_payment_receipt_pdf(request, payment_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as rl_canvas

    payment = get_object_or_404(Payment, id=payment_id)

    # Customers may only download their own receipts, and only for verified
    # payments (a pending/rejected payment is not an official billing record).
    # Admins/staff may download any receipt.
    if request.user.role == "customer":
        if payment.booking.user != request.user:
            return HttpResponseForbidden("Not allowed")
        if payment.payment_status != "verified":
            messages.error(
                request,
                "Receipts are only available once the payment has been verified.",
            )
            return redirect("my_payments")
    elif request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    buffer = io.BytesIO()
    p = rl_canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Logo
    from django.contrib.staticfiles import finders
    from django.conf import settings
    import os
    
    logo_path = finders.find('images/BalloorinaBlack.png')
    if not logo_path:
        # Fallback to direct path
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'images', 'BalloorinaBlack.png')
        
    if os.path.exists(logo_path):
        # Position logo at top right
        p.drawImage(logo_path, width - 180, height - 85, width=130, preserveAspectRatio=True, mask='auto')

    # Title
    p.setFont("Helvetica-Bold", 22)
    p.drawString(50, height - 55, "Payment Receipt")
    p.setFont("Helvetica", 10)
    p.setStrokeColorRGB(0.4, 0.4, 0.4)
    p.drawString(50, height - 72, "Balloorina.ph – Official Billing Statement")

    # Divider
    p.setLineWidth(1)
    p.line(50, height - 90, width - 50, height - 90)

    y = height - 120
    line_height = 22

    def draw_row(label, value):
        nonlocal y
        p.setFont("Helvetica-Bold", 11)
        p.drawString(50, y, f"{label}:")
        p.setFont("Helvetica", 11)
        p.drawString(220, y, str(value))
        y -= line_height

    draw_row("Receipt #", f"PAY-{payment.id:06d}")
    draw_row("Booking ID", f"#{payment.booking.id}")
    draw_row(
        "Customer",
        payment.booking.user.get_full_name() or payment.booking.user.username,
    )
    
    # Event Information
    draw_row("Event Type", payment.booking.event_type or "—")
    draw_row("Event Date", payment.booking.event_date.strftime("%B %d, %Y"))
    draw_row("Event Time", get_booking_time_range(payment.booking))
    if payment.booking.package_type:
        draw_row("Package", payment.booking.package_type)
    
    draw_row("Total Booking Price", f"PHP {payment.booking.total_price:,.2f}")
    draw_row("Amount Paid", f"PHP {payment.amount:,.2f}")
    draw_row("Payment Method", payment.get_payment_method_display())
    draw_row("Payment Type", payment.get_payment_type_display())
    draw_row("Status", payment.get_payment_status_display())
    draw_row("Transaction Ref", payment.transaction_ref or "—")
    if payment.gcash_reference_number:
        draw_row("GCash Reference #", payment.gcash_reference_number)
    if payment.gcash_sender_name:
        draw_row("GCash Sender Name", payment.gcash_sender_name)
    draw_row("Date Submitted", payment.created_at.strftime("%B %d, %Y %I:%M %p"))
    if payment.paid_at:
        draw_row("Date Verified", payment.paid_at.strftime("%B %d, %Y %I:%M %p"))

    y -= 30
    p.setDash(1, 2)
    p.setStrokeColorRGB(0.7, 0.7, 0.7)
    p.line(50, y + 20, width - 50, y + 20)
    p.setDash()
    
    p.setFont("Helvetica-Bold", 9)
    p.setFillColorRGB(0.2, 0.2, 0.2)
    p.drawString(50, y, "Terms and Conditions:")
    
    p.setFont("Helvetica", 8)
    p.setFillColorRGB(0.4, 0.4, 0.4)
    y -= 12
    p.drawString(50, y, "1. This receipt serves as an official acknowledgment of the payment amount stated above.")
    y -= 10
    p.drawString(50, y, "2. Payments are non-refundable but may be transferable subject to management approval.")
    y -= 10
    p.drawString(50, y, "3. Please keep this document for future reference and verification during ingress/egress.")
    
    y -= 20
    p.setFont("Helvetica-Oblique", 8)
    p.drawString(50, y, "Thank you for choosing Balloorina.ph! We look forward to making your event magical.")
    
    y -= 15
    p.setFont("Helvetica-Bold", 8)
    p.drawString(50, y, "Contact Us:")
    p.setFont("Helvetica", 8)
    p.drawString(105, y, "balloorina.ph@gmail.com | +63 967 233 6222")

    p.showPage()
    p.save()

    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="receipt_PAY{payment.id:06d}.pdf"'
    )
    return response


def _get_booking_payment_breakdown(booking):
    config = GCashConfig.objects.first()
    dp_percent = config.downpayment_percent if config else 20
    total_price = booking.total_price or Decimal("0.00")
    verified_paid = booking.payments.filter(payment_status="verified").aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")
    remaining_balance = total_price - verified_paid
    dp_amount = (total_price * Decimal(dp_percent) / Decimal(100)).quantize(
        Decimal("0.01")
    )
    return config, Decimal(dp_percent), total_price, verified_paid, remaining_balance, dp_amount


def _refresh_booking_payment_status(booking):
    total_paid = booking.payments.filter(payment_status="verified").aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")
    total_price = booking.total_price or Decimal("0.00")
    if total_paid >= total_price:
        booking.payment_status = "paid"
    elif total_paid > Decimal("0.00"):
        booking.payment_status = "partial"
    else:
        booking.payment_status = "pending"
    booking.save(update_fields=["payment_status"])
    return total_paid, total_price - total_paid


def _is_incomplete_paymongo_payment(payment):
    notes = (getattr(payment, "notes", "") or "").lower()
    non_resumable_markers = (
        "did not complete",
        "cancelled",
        "left the paymongo checkout",
        "expired",
        "failed",
    )
    return (
        bool(payment)
        and payment.payment_method.startswith("paymongo_")
        and payment.payment_status == "pending"
        and not payment.paymongo_payment_id
        and not any(marker in notes for marker in non_resumable_markers)
    )


def _is_abandoned_paymongo_payment(payment):
    notes = (getattr(payment, "notes", "") or "").lower()
    abandoned_markers = (
        "did not complete",
        "cancelled",
        "left the paymongo checkout",
        "expired",
        "failed",
    )
    return (
        bool(payment)
        and payment.payment_method.startswith("paymongo_")
        and payment.payment_status == "pending"
        and not payment.paymongo_payment_id
        and any(marker in notes for marker in abandoned_markers)
    )


def _abandoned_paymongo_payment_query():
    return (
        Q(payment_method__startswith="paymongo_")
        & Q(payment_status="pending")
        & Q(paymongo_payment_id="")
        & (
            Q(notes__icontains="did not complete")
            | Q(notes__icontains="cancelled")
            | Q(notes__icontains="left the paymongo checkout")
            | Q(notes__icontains="expired")
            | Q(notes__icontains="failed")
        )
    )


def _repair_legacy_auto_verified_paymongo():
    """
    Safety net:
    Legacy PayMongo flow could mark payments as verified before admin action.
    Any PayMongo payment with verified status but no verifying admin is treated as pending.
    """
    suspicious_ids = list(
        Payment.objects.filter(
            payment_method__startswith="paymongo_",
            payment_status="verified",
            verified_by__isnull=True,
        ).values_list("id", flat=True)
    )

    if not suspicious_ids:
        return

    affected_booking_ids = list(
        Payment.objects.filter(id__in=suspicious_ids)
        .values_list("booking_id", flat=True)
        .distinct()
    )

    Payment.objects.filter(id__in=suspicious_ids).update(
        payment_status="pending",
        paid_at=None,
    )

    for booking_id in affected_booking_ids:
        booking = Booking.objects.filter(id=booking_id).first()
        if booking:
            _refresh_booking_payment_status(booking)


@login_required
def payment_page(request, booking_id):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    check_booking_expirations()
    _repair_legacy_auto_verified_paymongo()

    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    if booking.status not in ["pending_payment", "confirmed"]:
        messages.warning(
            request, "This booking is not currently available for payment."
        )
        return redirect("customer_profile")

    payment_history = booking.payments.select_related("verified_by").order_by(
        "-created_at"
    )
    (
        config,
        dp_percent,
        total_price,
        total_paid,
        remaining_balance,
        dp_amount,
    ) = _get_booking_payment_breakdown(booking)

    has_downpayment = any(
        pay.payment_status == "verified" and pay.payment_type == "downpayment"
        for pay in payment_history
    )
    has_full_payment = any(
        pay.payment_status == "verified" and pay.payment_type == "full"
        for pay in payment_history
    )
    is_fully_paid = remaining_balance <= Decimal("0.00")

    incomplete_paymongo_payment = next(
        (pay for pay in payment_history if _is_incomplete_paymongo_payment(pay)),
        None,
    )
    pending_payment = next(
        (
            pay
            for pay in payment_history
            if pay.payment_status == "pending"
            and not _is_incomplete_paymongo_payment(pay)
            and not _is_abandoned_paymongo_payment(pay)
        ),
        None,
    )
    rejected_payment = next(
        (pay for pay in payment_history if pay.payment_status == "rejected"),
        None,
    )
    paymongo_method_types = ["gcash"] if settings.PAYMONGO_SECRET_KEY else []
    is_initial_payment = total_paid <= Decimal("0.00")
    downpayment_due = dp_amount if is_initial_payment else Decimal("0.00")
    full_amount_due = remaining_balance

    return render(
        request,
        "client/payment_upload.html",
        {
            "booking": booking,
            "is_fully_paid": is_fully_paid,
            "pending_payment": pending_payment,
            "pending_checkout_url": (
                incomplete_paymongo_payment.paymongo_checkout_url
                if incomplete_paymongo_payment
                else None
            ),
            "rejected_payment": rejected_payment,
            "failed_payment": None,
            "has_downpayment": has_downpayment,
            "has_full_payment": has_full_payment,
            "dp_percent": dp_percent,
            "dp_amount": dp_amount,
            "total_price": total_price,
            "total_paid": total_paid,
            "remaining_balance": remaining_balance,
            "paymongo_method_types": paymongo_method_types,
            "payment_history": payment_history,
            "config": config,
            "is_initial_payment": is_initial_payment,
            "downpayment_due": downpayment_due,
            "full_amount_due": full_amount_due,
        },
    )


@login_required
def submit_payment(request, booking_id):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    if booking.status not in ["pending_payment", "confirmed"]:
        messages.error(request, "This booking is not available for payment.")
        return redirect("customer_profile")

    if request.method != "POST":
        return redirect("payment_page", booking_id=booking_id)

    gcash_ref_number = request.POST.get("gcash_ref_number", "").strip()
    sender_name = request.POST.get("sender_name", "").strip()
    amount_str = request.POST.get("amount", "").strip()
    payment_option = request.POST.get("payment_option", "").strip().lower()
    refund_ack = request.POST.get("refund_ack")
    receipt_image = request.FILES.get("receipt_image")

    if not gcash_ref_number or not sender_name or not amount_str:
        messages.error(request, "Please fill in all required payment fields.")
        return redirect("payment_page", booking_id=booking_id)
    if not refund_ack:
        messages.error(
            request,
            "Please confirm the non-refundable payment reminder before submitting.",
        )
        return redirect("payment_page", booking_id=booking_id)

    try:
        amount = Decimal(amount_str)
        if amount <= 0:
            raise ValueError("Amount must be positive.")
    except (InvalidOperation, ValueError):
        messages.error(request, "Invalid payment amount. Please enter a valid number.")
        return redirect("payment_page", booking_id=booking_id)

    # Block duplicate pending submissions
    if booking.payments.filter(payment_status="pending").exists():
        messages.warning(
            request,
            "You already have a payment pending review. Please wait for it to be processed.",
        )
        return redirect("payment_page", booking_id=booking_id)

    (
        _config,
        _dp_percent,
        total_price,
        verified_paid,
        remaining_balance,
        dp_amount,
    ) = _get_booking_payment_breakdown(booking)

    if amount > remaining_balance:
        messages.error(
            request,
            f"Amount exceeds remaining balance of PHP {remaining_balance:,.2f}.",
        )
        return redirect("payment_page", booking_id=booking_id)

    expected_amount = Decimal("0.00")
    if verified_paid > Decimal("0.00"):
        payment_type = "balance"
        expected_amount = remaining_balance.quantize(Decimal("0.01"))
    else:
        if payment_option not in {"downpayment", "full"}:
            messages.error(request, "Please select Downpayment or Full Payment.")
            return redirect("payment_page", booking_id=booking_id)
        if payment_option == "downpayment":
            payment_type = "downpayment"
            expected_amount = dp_amount.quantize(Decimal("0.01"))
        else:
            payment_type = "full"
            expected_amount = total_price.quantize(Decimal("0.01"))

    if amount.quantize(Decimal("0.01")) != expected_amount:
        messages.error(
            request,
            f"Invalid amount for selected option. Expected PHP {expected_amount:,.2f}.",
        )
        return redirect("payment_page", booking_id=booking_id)

    if payment_type == "downpayment" and amount >= total_price:
        messages.error(
            request,
            "Downpayment amount cannot be the same as full payment amount.",
        )
        return redirect("payment_page", booking_id=booking_id)

    transaction_ref = str(uuid.uuid4()).replace("-", "")[:16].upper()

    payment = Payment(
        booking=booking,
        amount=amount,
        payment_method="gcash",
        payment_type=payment_type,
        payment_status="pending",
        transaction_ref=transaction_ref,
        gcash_reference_number=gcash_ref_number,
        gcash_sender_name=sender_name,
    )
    if receipt_image:
        payment.receipt_image = receipt_image
    payment.save()

    # Notify admin/staff of the new payment
    AdminNotification.objects.create(
        booking=booking,
        user=request.user,
        message=(
            f"New GCash payment submitted for Booking #{booking.id} "
            f"by {request.user.get_full_name() or request.user.username}. "
            f"Amount: PHP {amount:,.2f} | Ref: {gcash_ref_number}"
        ),
    )

    # Admin alert email (fail-safe)
    send_admin_alert_email(
        f"New Payment Proof — Booking #{booking.id}",
        (
            f"A customer submitted a payment proof.\n\n"
            f"Booking ID: #{booking.id}\n"
            f"Customer: {request.user.get_full_name() or request.user.username}\n"
            f"Amount: PHP {amount:,.2f} ({payment.get_payment_type_display()})\n"
            f"GCash Reference: {gcash_ref_number}\n\n"
            f"Verify it here: {request.build_absolute_uri('/staff/payments/')}"
        ),
    )

    log_action(
        request.user,
        f"Submitted GCash payment (txn: {transaction_ref}, ref: {gcash_ref_number}) for Booking #{booking.id}.",
    )
    messages.success(
        request, "Payment submitted successfully! We will verify it within 24 hours."
    )
    return redirect(f'{reverse("my_payments")}?tab=payment_history')


@login_required
def payment_success(request, booking_id):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    _repair_legacy_auto_verified_paymongo()

    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    payment_history = booking.payments.select_related("verified_by").order_by(
        "-created_at"
    )
    (
        config,
        dp_percent,
        total_price,
        total_paid,
        remaining_balance,
        dp_amount,
    ) = _get_booking_payment_breakdown(booking)

    has_downpayment = payment_history.filter(
        payment_status="verified", payment_type="downpayment"
    ).exists()
    has_full_payment = payment_history.filter(
        payment_status="verified", payment_type="full"
    ).exists()
    is_fully_paid = remaining_balance <= Decimal("0.00")

    pending_payment = next(
        (
            pay
            for pay in payment_history
            if pay.payment_status == "pending"
            and not _is_incomplete_paymongo_payment(pay)
            and not _is_abandoned_paymongo_payment(pay)
        ),
        None,
    )
    rejected_payment = (
        payment_history.filter(payment_status="rejected")
        .order_by("-updated_at")
        .first()
    )
    paymongo_method_types = ["gcash"] if settings.PAYMONGO_SECRET_KEY else []
    is_initial_payment = total_paid <= Decimal("0.00")
    downpayment_due = dp_amount if is_initial_payment else Decimal("0.00")
    full_amount_due = remaining_balance

    return render(
        request,
        "client/payment_upload.html",
        {
            "booking": booking,
            "is_fully_paid": is_fully_paid,
            "pending_payment": pending_payment,
            "pending_checkout_url": None,
            "rejected_payment": rejected_payment,
            "failed_payment": None,
            "has_downpayment": has_downpayment,
            "has_full_payment": has_full_payment,
            "dp_percent": dp_percent,
            "dp_amount": dp_amount,
            "total_price": total_price,
            "total_paid": total_paid,
            "remaining_balance": remaining_balance,
            "paymongo_method_types": paymongo_method_types,
            "payment_history": payment_history,
            "config": config,
            "payment_submitted": True,
            "is_initial_payment": is_initial_payment,
            "downpayment_due": downpayment_due,
            "full_amount_due": full_amount_due,
        },
    )


# =============================================================================
# ADMIN PAYMENT MANAGEMENT
# =============================================================================

@login_required
def payment_cancel(request, booking_id):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    check_booking_expirations()
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    messages.info(request, "Payment was cancelled. You can try again at any time.")
    return redirect("payment_page", booking_id=booking.id)


@login_required
def admin_payment_list(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    check_booking_expirations()
    _repair_legacy_auto_verified_paymongo()

    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()
    type_filter = request.GET.get("type", "").strip()

    # Pending payments now live in the action queue below, so a legacy
    # "pending" status filter (e.g. from the dashboard link) is ignored.
    if status_filter == "pending":
        status_filter = ""

    # ---- Payment history (verified + rejected) with search/filters ----
    history_qs = Payment.objects.filter(
        payment_status__in=["verified", "rejected"]
    ).select_related(
        "booking", "booking__user", "verified_by"
    ).order_by("-created_at")

    if search_query:
        history_qs = history_qs.filter(
            Q(transaction_ref__icontains=search_query)
            | Q(gcash_reference_number__icontains=search_query)
            | Q(gcash_sender_name__icontains=search_query)
            | Q(booking__user__first_name__icontains=search_query)
            | Q(booking__user__last_name__icontains=search_query)
            | Q(booking__user__username__icontains=search_query)
        )

    if status_filter:
        history_qs = history_qs.filter(payment_status=status_filter)

    if type_filter:
        history_qs = history_qs.filter(payment_type=type_filter)

    history_count = history_qs.count()

    # ---- Action queue: pending payments awaiting verification ----
    pending_qs = (
        Payment.objects.filter(payment_status="pending")
        .exclude(_abandoned_paymongo_payment_query())
        .select_related("booking", "booking__user", "verified_by")
        .order_by("-created_at")
    )
    pending_count = pending_qs.count()

    # Build booking lists: unpaid / partial (remaining balance) / fully paid
    gcash_config = GCashConfig.objects.first()
    dp_percent = gcash_config.downpayment_percent if gcash_config else 20

    all_active_bookings = (
        Booking.objects.filter(
            status__in=["pending_payment", "confirmed", "completed"]
        )
        .select_related("user")
        .prefetch_related("payments")
        .order_by("-id")
    )

    unpaid_bookings = []
    balance_bookings = []
    fully_paid_bookings = []
    for b in all_active_bookings:
        booking_payments = list(b.payments.all())
        latest_payment = (
            max(booking_payments, key=lambda pay: pay.created_at)
            if booking_payments
            else None
        )
        verified_paid = b.payments.filter(payment_status="verified").aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0.00")

        total_price = b.total_price or Decimal("0.00")
        required_downpayment = (
            total_price * Decimal(dp_percent) / Decimal(100)
        ).quantize(Decimal("0.01"))

        remaining_total_balance = total_price - verified_paid
        if remaining_total_balance < Decimal("0.00"):
            remaining_total_balance = Decimal("0.00")

        b.booking_id = b.id
        b.latest_payment_id = latest_payment.id if latest_payment else None
        b.customer_name = b.user.get_full_name() or b.user.username
        b.username = b.user.username
        b.total_paid = verified_paid
        b.total_price = total_price
        b.required_downpayment = required_downpayment
        b.remaining_balance = remaining_total_balance
        b.can_send_reminder = b.status in ("pending_payment", "confirmed")

        if verified_paid <= Decimal("0.00"):
            unpaid_bookings.append(b)
        elif remaining_total_balance > Decimal("0.00"):
            balance_bookings.append(b)
        else:
            fully_paid_bookings.append(b)

    unpaid_bookings_count = len(unpaid_bookings)
    balance_bookings_count = len(balance_bookings)
    fully_paid_count = len(fully_paid_bookings)
    bookings_with_balance_count = unpaid_bookings_count + balance_bookings_count

    # Pagination (6 items per page for every list)
    pending_page = Paginator(pending_qs, 6).get_page(
        request.GET.get("pending_page", 1)
    )
    payments_page = Paginator(history_qs, 6).get_page(request.GET.get("page", 1))
    unpaid_page = Paginator(unpaid_bookings, 6).get_page(
        request.GET.get("unpaid_page", 1)
    )
    balance_page = Paginator(balance_bookings, 6).get_page(
        request.GET.get("balance_page", 1)
    )
    paid_page = Paginator(fully_paid_bookings, 6).get_page(
        request.GET.get("paid_page", 1)
    )

    return render(
        request,
        "admin/payment/admin_payment_list.html",
        {
            "pending_count": pending_count,
            "pending_payments": pending_page,
            "history_payments": payments_page,
            "history_count": history_count,
            "fully_paid_count": fully_paid_count,
            "bookings_with_balance_count": bookings_with_balance_count,
            "unpaid_bookings_count": unpaid_bookings_count,
            "balance_bookings_count": balance_bookings_count,
            "unpaid_bookings": unpaid_page,
            "balance_bookings": balance_page,
            "fully_paid_bookings": paid_page,
            "search_query": search_query,
            "status_filter": status_filter,
            "type_filter": type_filter,
        },
    )


@login_required
def admin_payment_detail(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    check_booking_expirations()
    _repair_legacy_auto_verified_paymongo()

    payment = get_object_or_404(
        Payment.objects.select_related("booking__user", "verified_by"),
        id=id,
    )
    payment = _refresh_paymongo_payment_record(payment)
    booking = payment.booking

    payment_history = booking.payments.select_related("verified_by").order_by(
        "-created_at"
    )
    for history_payment in payment_history:
        history_payment.display_notes = format_payment_note_for_display(
            history_payment.notes
        )
        # Failed/expired PayMongo attempts: audit-trail entries that must not
        # look like actionable "Pending" payments in the timeline.
        history_payment.is_failed_attempt = _is_abandoned_paymongo_payment(
            history_payment
        )
        if history_payment.is_failed_attempt:
            history_payment.failed_label = (
                "Expired"
                if "expired" in (history_payment.notes or "").lower()
                else "Failed"
            )

    total_paid = payment_history.filter(payment_status="verified").aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")
    remaining_balance = (booking.total_price or Decimal("0.00")) - total_paid
    if remaining_balance < Decimal("0.00"):
        remaining_balance = Decimal("0.00")

    booking.time_range_display = get_booking_time_range(booking)
    booking.cleaned_special_requests = remove_end_time_tag(
        booking.special_requests or ""
    )
    booking.total_payment_records = payment_history.count()
    payment.display_notes = format_payment_note_for_display(payment.notes)
    # A failed/expired PayMongo attempt must never show the Approve/Reject bar.
    payment_is_actionable = (
        payment.payment_status == "pending"
        and not _is_abandoned_paymongo_payment(payment)
    )

    return render(
        request,
        "admin/payment/admin_payment_detail.html",
        {
            "payment": payment,
            "booking": booking,
            "total_paid": total_paid,
            "remaining_balance": remaining_balance,
            "payment_history": payment_history,
            "payment_is_actionable": payment_is_actionable,
        },
    )


@login_required
def admin_payment_action(request, id, action):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    # Where to land after the action. The payments list table passes
    # ?next=payments so the admin stays on the table instead of being
    # redirected to the payment detail page. The detail page actions
    # pass no parameter and land back on the detail page.
    next_target = request.POST.get("next") or request.GET.get("next")
    back_to_list = next_target == "payments"

    if request.method != "POST":
        if back_to_list:
            return redirect("admin_payment_list")
        return redirect("admin_payment_detail", id=id)

    payment = get_object_or_404(Payment, id=id)
    booking = payment.booking

    # Idempotency guard: only pending payments can be verified or rejected.
    # Prevents double-clicks or stale tabs from re-processing an action,
    # which would fire duplicate notifications or overwrite verification data.
    if payment.payment_status != "pending":
        messages.warning(
            request,
            f"Payment #{payment.id} is already marked as "
            f"{payment.get_payment_status_display()}. No further action is needed.",
        )
        if back_to_list:
            return redirect("admin_payment_list")
        return redirect("admin_payment_detail", id=id)

    if action == "verify":
        with transaction.atomic():
            payment.payment_status = "verified"
            payment.paid_at = timezone.now()
            payment.verified_by = request.user
            payment.save()

            # Recalculate booking payment status.
            # Business rule: once admin verifies any customer payment,
            # booking should be marked as confirmed immediately.
            total_paid = booking.payments.filter(payment_status="verified").aggregate(
                total=Sum("amount")
            )["total"] or Decimal("0.00")
            total_price = booking.total_price or Decimal("0.00")

            if total_paid >= total_price:
                booking.payment_status = "paid"
            else:
                booking.payment_status = "partial"
            old_booking_status = booking.status
            booking.status = "confirmed"
            booking.save()

            # Record the status transition in the booking's history timeline
            if old_booking_status != "confirmed":
                log_booking_status(
                    booking,
                    old_booking_status,
                    "confirmed",
                    changed_by=request.user,
                    notes="Payment verified by admin.",
                )

            # Notify the customer
            Notification.objects.create(
                user=booking.user,
                booking=booking,
                message=(
                    f"Your payment of PHP {payment.amount:,.2f} for Booking #{booking.id} "
                    f"has been verified. Thank you!"
                ),
            )

            log_action(
                request.user, f"Verified payment #{payment.id} for Booking #{booking.id}."
            )
        messages.success(
            request, f"Payment #{payment.id} has been verified successfully."
        )

    elif action == "reject":
        admin_notes = request.POST.get("admin_notes", "").strip()

        # Server-side validation: never reject a payment without a reason.
        if not admin_notes:
            messages.error(
                request, "A rejection reason is required before rejecting a payment."
            )
            if back_to_list:
                return redirect("admin_payment_list")
            return redirect("admin_payment_detail", id=id)

        with transaction.atomic():
            payment.payment_status = "rejected"
            payment.notes = admin_notes
            payment.save(update_fields=["payment_status", "notes", "updated_at"])

            # Keep booking in pending payment state when payment is rejected,
            # unless there are other verified payments already recorded.
            verified_total = booking.payments.filter(payment_status="verified").aggregate(
                total=Sum("amount")
            )["total"] or Decimal("0.00")
            total_price = booking.total_price or Decimal("0.00")
            old_booking_status = booking.status
            if verified_total <= Decimal("0.00"):
                booking.payment_status = "pending"
                booking.status = "pending_payment"
            elif verified_total >= total_price:
                booking.payment_status = "paid"
                booking.status = "confirmed"
            else:
                booking.payment_status = "partial"
                booking.status = "confirmed"
            booking.save(update_fields=["payment_status", "status", "updated_at"])

            # Record the status transition in the booking's history timeline
            if booking.status != old_booking_status:
                if booking.status == "pending_payment":
                    log_booking_status(
                        booking,
                        old_booking_status,
                        "pending_payment",
                        changed_by=request.user,
                        notes=f"Payment #{payment.id} rejected by admin. Awaiting new payment.",
                    )
                else:
                    log_booking_status(
                        booking,
                        old_booking_status,
                        "confirmed",
                        changed_by=request.user,
                        notes=f"Payment #{payment.id} rejected, but prior verified payments cover this booking.",
                    )

            # Notify the customer
            Notification.objects.create(
                user=booking.user,
                booking=booking,
                message=(
                    f"Your payment of PHP {payment.amount:,.2f} for Booking #{booking.id} "
                    f"was rejected. Reason: {admin_notes}"
                ),
            )

            log_action(
                request.user,
                f"Rejected payment #{payment.id} for Booking #{booking.id}. Reason: {admin_notes}",
            )
        messages.warning(request, f"Payment #{payment.id} has been rejected.")

    else:
        messages.error(
            request, f"Unknown action: '{action}'. Expected 'verify' or 'reject'."
        )

    if back_to_list:
        return redirect("admin_payment_list")
    return redirect("admin_payment_detail", id=id)


@login_required
def admin_gcash_config(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    config = GCashConfig.objects.first()
    if config is None:
        config = GCashConfig.objects.create()

    if request.method == "POST":
        config.gcash_number = request.POST.get(
            "gcash_number", config.gcash_number
        ).strip()
        config.gcash_name = request.POST.get("gcash_name", config.gcash_name).strip()

        try:
            dp_percent = int(
                request.POST.get("downpayment_percent", config.downpayment_percent)
            )
            if 1 <= dp_percent <= 100:
                config.downpayment_percent = dp_percent
            else:
                messages.warning(
                    request, "Downpayment percent must be between 1 and 100."
                )
        except (ValueError, TypeError):
            messages.warning(
                request,
                "Invalid downpayment percent value. Keeping the previous value.",
            )

        if request.FILES.get("qr_code_image"):
            config.qr_code_image = request.FILES["qr_code_image"]

        config.save()
        log_action(request.user, "Updated GCash configuration.")
        messages.success(request, "GCash configuration updated successfully.")
        return redirect("admin_gcash_config")

    return render(request, "admin/payment/admin_gcash_config.html", {"config": config})


PAYMENT_REMINDER_COOLDOWN_HOURS = 24


# =============================================================================
# PAYMONGO INTEGRATION VIEWS
# =============================================================================

@login_required
@require_POST
def admin_send_payment_reminder(request, booking_id):
    """
    Send a payment reminder to the customer for a booking with an outstanding
    balance. Creates an in-app Notification and emails the customer.
    Rate-limited to one reminder per PAYMENT_REMINDER_COOLDOWN_HOURS.
    """
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(
        Booking.objects.select_related("user"), id=booking_id
    )

    if booking.status not in ("pending_payment", "confirmed"):
        messages.error(
            request,
            f"Booking #{booking.id} is not awaiting payment (status: {booking.get_status_display()}).",
        )
        return redirect("admin_payment_list")

    # Anti-spam cooldown: check the last reminder notification
    last_reminder = (
        Notification.objects.filter(
            user=booking.user,
            booking=booking,
            message__icontains="payment reminder",
        )
        .order_by("-created_at")
        .first()
    )
    if last_reminder:
        hours_since = (timezone.now() - last_reminder.created_at).total_seconds() / 3600
        if hours_since < PAYMENT_REMINDER_COOLDOWN_HOURS:
            messages.warning(
                request,
                f"A payment reminder was already sent for booking #{booking.id} "
                f"{int(hours_since)} hour(s) ago. Please wait 24 hours before sending another.",
            )
            return redirect("admin_payment_list")

    gcash_config = GCashConfig.objects.first()
    dp_percent = gcash_config.downpayment_percent if gcash_config else 20
    verified_paid = booking.payments.filter(payment_status="verified").aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")
    remaining = (booking.total_price or Decimal("0.00")) - verified_paid
    if remaining < Decimal("0.00"):
        remaining = Decimal("0.00")

    reminder_message = (
        f"Payment Reminder: Booking #{booking.id} for {booking.event_date} "
        f"still has \u20b1{remaining:,.2f} outstanding. Please settle your payment "
        f"to secure your slot. Thank you!"
    )

    # In-app notification for the customer
    Notification.objects.create(
        user=booking.user,
        booking=booking,
        message=reminder_message,
    )

    # Email notification (fail-safe)
    customer_email = (booking.user.email or "").strip()
    email_status = "in-app only"
    if customer_email:
        try:
            send_mail(
                subject=f"Payment Reminder — Booking #{booking.id} | Balloorina",
                message=(
                    f"Hi {booking.user.get_full_name() or booking.user.username},\n\n"
                    f"{reminder_message}\n\n"
                    f"You can settle your payment through the My Payments page:\n"
                    f"{request.build_absolute_uri('/my-payments/')}\n\n"
                    f"— Balloorina Team"
                ),
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[customer_email],
                fail_silently=True,
            )
            email_status = "email sent"
        except Exception:
            logger.exception("Failed to send payment reminder email for booking #%s", booking.id)
            email_status = "email failed (in-app sent)"

    log_action(
        request.user,
        f"Sent payment reminder for booking #{booking.id} to "
        f"'{booking.user.username}' ({email_status}).",
    )
    messages.success(
        request,
        f"Payment reminder sent to {booking.user.username} for booking #{booking.id}.",
    )
    return redirect("admin_payment_list")


@login_required
def create_paymongo_checkout(request, booking_id):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    if booking.status not in ["pending_payment", "confirmed"]:
        messages.warning(request, "This booking is not available for payment.")
        return redirect("customer_profile")

    if request.method != "POST":
        return redirect("payment_page", booking_id=booking.id)

    if not settings.PAYMONGO_SECRET_KEY:
        messages.error(
            request,
            "PayMongo is not configured yet. Please contact support.",
        )
        return redirect("payment_page", booking_id=booking.id)

    payment_method_type = request.POST.get("payment_method", "gcash").strip().lower()
    amount_str = request.POST.get("amount", "").strip()
    payment_option = request.POST.get("payment_option", "").strip().lower()
    refund_ack = request.POST.get("refund_ack")
    allowed_method_types = {"gcash"}

    if payment_method_type not in allowed_method_types:
        messages.error(request, "Invalid PayMongo payment method.")
        return redirect("payment_page", booking_id=booking.id)

    if not amount_str:
        messages.error(request, "Please enter an amount.")
        return redirect("payment_page", booking_id=booking.id)

    try:
        amount = Decimal(amount_str)
        if amount <= 0:
            raise ValueError()
    except (ValueError, InvalidOperation):
        messages.error(request, "Invalid amount.")
        return redirect("payment_page", booking_id=booking.id)

    if not refund_ack:
        messages.error(
            request,
            "Please confirm the non-refundable payment reminder before continuing.",
        )
        return redirect("payment_page", booking_id=booking.id)

    blocking_pending = next(
        (
            pay
            for pay in booking.payments.filter(payment_status="pending").order_by("-created_at")
            if not _is_incomplete_paymongo_payment(pay)
            and not _is_abandoned_paymongo_payment(pay)
        ),
        None,
    )
    if blocking_pending:
        messages.warning(
            request,
            "You already have a payment pending review. Please wait for it to be processed.",
        )
        return redirect("payment_page", booking_id=booking.id)

    resumable_pending = next(
        (
            pay
            for pay in booking.payments.filter(payment_status="pending").order_by("-created_at")
            if _is_incomplete_paymongo_payment(pay)
            and pay.paymongo_checkout_url
        ),
        None,
    )
    if resumable_pending:
        return redirect(resumable_pending.paymongo_checkout_url)

    (
        _config,
        _dp_percent,
        total_price,
        verified_paid,
        remaining_balance,
        dp_amount,
    ) = _get_booking_payment_breakdown(booking)

    if amount > remaining_balance:
        messages.error(
            request,
            f"Amount exceeds remaining balance of PHP {remaining_balance:,.2f}.",
        )
        return redirect("payment_page", booking_id=booking.id)

    if verified_paid > Decimal("0.00"):
        payment_type = "balance"
        expected_amount = remaining_balance.quantize(Decimal("0.01"))
    else:
        if payment_option not in {"downpayment", "full"}:
            messages.error(request, "Please select Downpayment or Full Payment.")
            return redirect("payment_page", booking_id=booking.id)
        if payment_option == "downpayment":
            payment_type = "downpayment"
            expected_amount = dp_amount.quantize(Decimal("0.01"))
        else:
            payment_type = "full"
            expected_amount = total_price.quantize(Decimal("0.01"))

    if amount.quantize(Decimal("0.01")) != expected_amount:
        messages.error(
            request,
            f"Invalid amount for selected option. Expected PHP {expected_amount:,.2f}.",
        )
        return redirect("payment_page", booking_id=booking.id)

    if payment_type == "downpayment" and amount >= total_price:
        messages.error(
            request,
            "Downpayment amount cannot be the same as full payment amount.",
        )
        return redirect("payment_page", booking_id=booking.id)

    if payment_type == "full" and amount < total_price and verified_paid <= Decimal("0.00"):
            messages.error(
                request,
                "Full payment must match the total booking amount.",
            )
            return redirect("payment_page", booking_id=booking.id)

    amount_cents = int(amount * 100)
    success_url = request.build_absolute_uri(reverse("paymongo_success", kwargs={"booking_id": booking.id}))
    cancel_url = request.build_absolute_uri(reverse("paymongo_cancel", kwargs={"booking_id": booking.id}))

    paymongo_type = "gcash"
    checkout_session = create_paymongo_checkout_session(
        amount=amount_cents,
        booking_id=booking.id,
        success_url=success_url,
        cancel_url=cancel_url,
        payment_type=paymongo_type,
        description=f"Payment for Booking #{booking.id}",
    )

    if not checkout_session:
        messages.error(request, "Failed to create payment session. Please try again.")
        return redirect("payment_page", booking_id=booking.id)

    try:
        session_id = checkout_session["data"]["id"]
        checkout_url = checkout_session["data"]["attributes"]["checkout_url"]
    except (KeyError, TypeError):
        messages.error(request, "Invalid response from payment provider.")
        return redirect("payment_page", booking_id=booking.id)

    transaction_ref = str(uuid.uuid4()).replace("-", "")[:16].upper()
    Payment.objects.create(
        booking=booking,
        amount=amount,
        payment_method=f"paymongo_{payment_method_type}",
        payment_type=payment_type,
        payment_status="pending",
        transaction_ref=transaction_ref,
        paymongo_checkout_session_id=session_id,
        paymongo_checkout_url=checkout_url,
    )

    log_action(request.user, f"Created PayMongo checkout session for Booking #{booking.id}.")
    return redirect(checkout_url)


@login_required
def paymongo_success(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    pending_paymongo = (
        booking.payments.filter(
            payment_status="pending",
            payment_method__startswith="paymongo_",
            paymongo_checkout_session_id__gt="",
        )
        .order_by("-created_at")
        .first()
    )

    if not pending_paymongo:
        messages.info(
            request,
            "No pending PayMongo payment found. If you already paid, please wait for confirmation.",
        )
        return redirect("payment_page", booking_id=booking_id)

    checkout_data = retrieve_paymongo_checkout_session(
        pending_paymongo.paymongo_checkout_session_id
    )
    if not checkout_data:
        messages.info(
            request,
            "Payment is still processing. Please refresh this page in a moment.",
        )
        return redirect("payment_page", booking_id=booking_id)

    attrs = checkout_data.get("data", {}).get("attributes", {})
    checkout_status = (attrs.get("status") or "").lower()

    payment_intent = attrs.get("payment_intent") or {}
    payment_intent_id = payment_intent.get("id", "")
    payment_data = None
    payment_intent_status = (
        payment_intent.get("attributes", {}).get("status", "") or ""
    ).lower()
    if payment_intent_id and payment_intent_status not in {
        "succeeded",
        "paid",
        "failed",
        "cancelled",
    }:
        payment_data = retrieve_paymongo_payment(payment_intent_id)
        payment_intent_status = (
            payment_data.get("data", {}).get("attributes", {}).get("status", "")
            if payment_data
            else payment_intent_status
        )
        payment_intent_status = (payment_intent_status or "").lower()

    if checkout_status in {"paid", "succeeded"} or payment_intent_status in {
        "succeeded",
        "paid",
    }:
        actual_payment_id = _extract_paymongo_payment_reference(
            checkout_data=checkout_data,
            payment_data=payment_data,
        )
        payer_name, payer_phone = _extract_paymongo_payer_details(
            checkout_data=checkout_data,
            payment_data=payment_data,
        )
        pending_paymongo.paymongo_payment_id = actual_payment_id or payment_intent_id
        if payer_name:
            pending_paymongo.gcash_sender_name = payer_name
        if payer_phone:
            pending_paymongo.paymongo_contact_number = payer_phone
        # Only set fallback notes if the webhook hasn't already confirmed
        # this payment — never overwrite a webhook-written note.
        if "webhook" not in (pending_paymongo.notes or "").lower():
            pending_paymongo.notes = "Paid via PayMongo. Awaiting admin verification."
        pending_paymongo.save(
            update_fields=[
                "paymongo_payment_id",
                "gcash_sender_name",
                "paymongo_contact_number",
                "notes",
            ]
        )

        AdminNotification.objects.create(
            booking=booking,
            user=request.user,
            message=(
                f"New PayMongo payment submitted for Booking #{booking.id} "
                f"by {request.user.get_full_name() or request.user.username}. "
                f"Amount: PHP {pending_paymongo.amount:,.2f}"
            ),
        )

        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=(
                f"Your payment of PHP {pending_paymongo.amount:,.2f} for Booking "
                f"#{booking.id} was received and is now pending admin verification."
            ),
        )
        messages.success(
            request,
            "Payment received! It is now pending admin verification.",
        )
    elif checkout_status in {"failed", "expired", "cancelled"}:
        # Keep the record as an audit trail (marked as a failed attempt) instead
        # of deleting it. The marker notes exclude it from all action queues,
        # so it never blocks a retry or clutters the admin verification queue.
        if (
            pending_paymongo.payment_status == "pending"
            and not pending_paymongo.paymongo_payment_id
        ):
            pending_paymongo.notes = (
                f"PayMongo checkout {checkout_status} — did not complete. "
                "Customer may retry with a new checkout."
            )
            pending_paymongo.save(update_fields=["notes", "updated_at"])
        messages.warning(
            request,
            "Payment did not complete. Please try again.",
        )
    else:
        messages.info(
            request,
            "Payment is still pending confirmation. Please check again shortly.",
        )

    check_booking_expirations()
    return redirect("payment_page", booking_id=booking_id)


@login_required
def paymongo_cancel(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    pending_paymongo = (
        booking.payments.filter(
            payment_status="pending",
            payment_method__startswith="paymongo_",
            paymongo_checkout_session_id__gt="",
        )
        .order_by("-created_at")
        .first()
    )
    if pending_paymongo and pending_paymongo.payment_status == "pending":
        # Keep the record as an audit trail (marker notes exclude it from
        # every action queue, so cancelling never blocks a future retry).
        pending_paymongo.notes = (
            "PayMongo checkout cancelled — did not complete. "
            "Customer may retry with a new checkout."
        )
        pending_paymongo.save(update_fields=["notes", "updated_at"])
    messages.info(request, "Payment was cancelled. You can try again at any time.")
    return redirect("payment_page", booking_id=booking_id)


@csrf_exempt
@require_POST
def paymongo_webhook(request):
    payload = request.body.decode('utf-8')
    signature_header = request.headers.get('Paymongo-Signature', '')

    if not verify_paymongo_webhook_signature(payload, signature_header):
        return JsonResponse({"error": "Invalid signature"}, status=400)

    try:
        data = json.loads(payload)
        event_attrs = data.get("data", {}).get("attributes", {})
        event_type = (event_attrs.get("type") or "").strip()
        event_data = event_attrs.get("data", {}) or {}
        event_data_attrs = event_data.get("attributes", {}) or {}
        checkout_session_id = event_data.get("id") or event_data_attrs.get("id")

        if not checkout_session_id:
            return JsonResponse({"success": True})

        payment = Payment.objects.filter(
            paymongo_checkout_session_id=checkout_session_id
        ).first()
        if not payment:
            return JsonResponse({"success": True})

        if event_type == "checkout_session.payment.paid" and payment.payment_status == "pending":
            payment_ref = ""
            payments_arr = event_data_attrs.get("payments") or []
            if payments_arr and isinstance(payments_arr, list):
                payment_ref = payments_arr[0].get("id", "")

            payment_data = retrieve_paymongo_payment(payment_ref) if payment_ref else None
            payer_name, payer_phone = _extract_paymongo_payer_details(
                payment_data=payment_data
            )
            if payment_ref:
                payment.paymongo_payment_id = payment_ref
            if payer_name:
                payment.gcash_sender_name = payer_name
            if payer_phone:
                payment.paymongo_contact_number = payer_phone
            payment.notes = "Paid via PayMongo webhook. Awaiting admin verification."
            payment.save(
                update_fields=[
                    "paymongo_payment_id",
                    "gcash_sender_name",
                    "paymongo_contact_number",
                    "notes",
                ]
            )
        elif event_type in {"checkout_session.payment.failed", "checkout_session.expired"}:
            # Keep the record as an audit trail instead of deleting it. The
            # marker notes exclude it from all action queues (treated as an
            # abandoned attempt), so the customer can simply retry.
            if payment.payment_status == "pending" and not payment.paymongo_payment_id:
                failure_label = (
                    "payment failed" if "failed" in event_type else "checkout expired"
                )
                payment.notes = (
                    f"PayMongo {failure_label} — did not complete. "
                    "Customer may retry with a new checkout."
                )
                payment.save(update_fields=["notes", "updated_at"])

        return JsonResponse({"success": True})
    except Exception as e:
        print(f"PayMongo Webhook Error: {e}")
        return JsonResponse({"error": "Failed to process webhook"}, status=500)
