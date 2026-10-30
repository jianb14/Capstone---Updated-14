"""Customer proposals and team quotes; separate from direct pending-booking edits."""
from .common import *
from ..request_protection import deduplicate_submission
from ..models import BookingChangeImage, BookingChangeRequest
from ..booking_changes import (apply_change, audit, change_payment_summary, check_current, eligibility,
    expire_change, issue_quote, notify, pending_proof, prepare_proposal, proposed_booking, schedule_atomic, snapshot)
from ..booking_lifecycle import process_booking, payment_was_received


def _locked_change(request, booking_id, change_id, as_admin=False):
    booking = get_object_or_404(Booking.objects.select_for_update(), pk=booking_id)
    if (as_admin and request.user.role != 'admin') or (not as_admin and (request.user.role != 'customer' or booking.user_id != request.user.pk)):
        raise PermissionError()
    change = get_object_or_404(BookingChangeRequest.objects.select_for_update(), pk=change_id, booking=booking)
    change.booking = booking
    expire_change(change)
    return change


@login_required
@deduplicate_submission
@schedule_atomic
def request_booking_change(request, booking_id):
    booking = get_object_or_404(Booking.objects.select_for_update(), pk=booking_id, user=request.user)
    if request.user.role != 'customer':
        return HttpResponseForbidden('Not allowed')
    process_booking(booking.pk)
    booking.refresh_from_db()
    allowed, reason = eligibility(booking)
    if request.method == 'GET':
        if not allowed:
            messages.error(request, reason)
            return redirect('customer_profile')
        return redirect(f'{reverse("customer_profile")}?open_edit={booking.pk}')
    if request.method != 'POST':
        return HttpResponse(status=405)
    try:
        if not allowed:
            raise ValidationError(reason)
        reason = request.POST.get('change_reason', '').strip()
        if not 10 <= len(reason) <= 2000:
            raise ValidationError('Explain your requested changes in 10–2,000 characters.')
        if pending_proof(booking):
            raise ValidationError('Your payment is being verified. Please wait for verification before requesting a new price.')
        proposed = prepare_proposal(booking, request.POST)
        uploads = request.FILES.getlist('reference_images')
        if request.FILES.get('reference_image'):
            uploads.append(request.FILES['reference_image'])
        removals = request.POST.getlist('remove_images[]')
        existing = {str(i.pk) for i in booking.images.all()}
        if booking.reference_image:
            existing.add('legacy')
        removals = list(set(removals) & existing)
        if len(existing) - len(removals) + len(uploads) > 4:
            raise ValidationError('Keep a maximum of four reference images.')
        from .bookings import _validate_design_delivery_image
        for upload in uploads:
            error = _validate_design_delivery_image(upload)
            if error:
                raise ValidationError(error)
        original, proposal = snapshot(booking), snapshot(proposed)
        if proposal == original and not uploads and not removals:
            raise ValidationError('Change at least one booking detail before submitting a request.')
        proposal['_remove_images'] = removals
        proposal['_design_changed'] = bool(uploads or removals or any(original.get(key) != proposal.get(key)
            for key in ('package_type', 'design_theme', 'color_palette', 'motto_text')) or
            remove_end_time_tag(original.get('special_requests') or '') != remove_end_time_tag(proposal.get('special_requests') or ''))
        change = BookingChangeRequest.objects.create(booking=booking, reason=reason, original=original,
            proposed=proposal, original_total=booking.total_price, quoted_total=proposed.total_price)
        for upload in uploads:
            BookingChangeImage.objects.create(change_request=change, image=upload)
        audit(change, 'Customer submitted proposed changes. Original reservation unchanged.', request.user)
        notify(change, 'A customer submitted proposed changes. Review the original details and revised quote.', admin=True)
    except ValidationError as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success':False, 'message':' '.join(exc.messages)}, status=400)
        messages.error(request, ' '.join(exc.messages))
        return redirect(f'{reverse("customer_profile")}?open_edit={booking.pk}')
    request._submission_succeeded = True
    notice = 'Change request submitted. Your original booking stays reserved while our team reviews it.'
    url = f'{reverse("customer_profile")}?booking_id={booking.pk}&modal=details'
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success':True, 'redirect':url, 'message':notice})
    messages.success(request,notice)
    return redirect(url)


@login_required
@require_POST
@schedule_atomic
def admin_booking_change_action(request, booking_id, change_id, action):
    from .booking_workspace import booking_feedback, is_async
    try:
        change = _locked_change(request, booking_id, change_id, as_admin=True)
    except PermissionError:
        return HttpResponseForbidden('Not allowed')
    try:
        if len(request.POST.get('admin_notes', '').strip()) > 4000:
            raise ValidationError('Keep your message to 4,000 characters or fewer.')
        if action == 'quote':
            issue_quote(change, request.user, request.POST.get('admin_notes', ''), request.POST.get('downgrade_ack') == 'on')
            booking_feedback(request, 'success', 'Quote sent. The customer must accept before any changes become final.')
        elif action == 'reject':
            notes = request.POST.get('admin_notes', '').strip()
            if not notes:
                raise ValidationError('A reason is required to decline a change request.')
            if change.status not in BookingChangeRequest.ACTIVE_STATUSES:
                raise ValidationError('This change request is already closed.')
            if any(payment_was_received(p) for p in change.payments.all()):
                raise ValidationError('A change payment has been received. Resolve it with the customer before closing this request; no automatic refund is available.')
            change.status, change.admin_notes = 'rejected', notes
            change.hold_start = change.hold_end = None
            change.save()
            audit(change, f'Declined: {notes}', request.user)
            notify(change, f'The requested change was declined: {notes}. Your original booking is unchanged.')
            booking_feedback(request, 'success', 'Request declined. Original booking retained.')
        elif action == 'resolve':
            notes = request.POST.get('admin_notes', '').strip()
            if change.status != 'manual_review' or not notes or request.POST.get('resolution_ack') != 'on':
                raise ValidationError('Document the manual payment resolution and acknowledge it before closing this request.')
            if any(p.payment_status == 'pending' and payment_was_received(p) for p in change.payments.all()):
                raise ValidationError('Verify or reject the received payment first so its financial record is resolved before closing this request.')
            change.status, change.admin_notes = 'withdrawn', notes
            change.hold_start = change.hold_end = None
            change.save()
            audit(change, f'Manually resolved by team; original booking retained. {notes}', request.user)
            notify(change, f'Our team resolved this request directly: {notes}. Your original booking is retained.')
            booking_feedback(request, 'success', 'Manual resolution recorded. No system refund or credit was issued.')
        else:
            raise ValidationError('Unknown change request action.')
    except ValidationError as exc:
        booking_feedback(request, 'error', ' '.join(exc.messages))
    if is_async(request):
        success, message = request._booking_notice
        return JsonResponse({'success': success, 'message': message}, status=200 if success else 400)
    from .change_management import request_review_url
    return redirect(request_review_url(request, change))


@login_required
@require_POST
@schedule_atomic
def customer_booking_change_action(request, booking_id, change_id, action):
    wants_json = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    notice = ''
    def success(text):
        nonlocal notice
        notice = text
        if not wants_json:
            messages.success(request,text)
    try:
        change = _locked_change(request, booking_id, change_id)
    except PermissionError:
        return HttpResponseForbidden('Not allowed')
    try:
        if action == 'accept':
            if change.status != 'quoted':
                raise ValidationError('This quote is no longer available for acceptance.')
            if request.POST.get('accept_quote') != 'on':
                raise ValidationError('Confirm that you accept the final quote and payment terms.')
            check_current(change)
            # Paying the original booking after review changes the required top-up.
            from ..booking_changes import verified_paid
            amounts = change_payment_summary(change)
            reviewed_excess = Decimal(change.quote.get('non_refundable_excess', '0'))
            if ((verified_paid(change.booking) > 0 and Decimal(change.quote.get('verified_paid_at_review', '0')) == 0)
                    or amounts['change_excess_payment'] != reviewed_excess):
                change.status = 'pending_review'
                change.hold_start = change.hold_end = None
                change.expires_at = None
                change.quote = {}
                change.save()
                notify(change, 'The payment amounts or excess-payment terms need a fresh review before this quote can be accepted. Review the payment difference and send an updated quote.', admin=True)
                raise ValidationError('Your payment amounts need an updated quote. Our team will review it before you accept.')
            if reviewed_excess > 0 and request.POST.get('accept_nonrefundable_excess') != 'on':
                raise ValidationError(f'Confirm that you understand the PHP {reviewed_excess:,.2f} excess payment will not be refunded under the existing payment policy before accepting this lower-priced booking.')
            change.accepted_at = timezone.now()
            if reviewed_excess > 0:
                change.quote['customer_nonrefund_accepted_at'] = change.accepted_at.isoformat()
                audit(change, f'Customer accepted the non-refundable excess of PHP {reviewed_excess:,.2f} under the existing payment policy.', request.user)
            if change.additional_due > 0:
                change.status = 'awaiting_payment'
                change.save()
                audit(change, 'Customer accepted quote; awaiting verified additional payment.', request.user)
                success('Quote accepted. Submit the additional payment before the deadline to finalize your changes.')
            else:
                apply_change(change, request.user)
                success('Your accepted changes have been applied.')
        elif action == 'withdraw':
            if change.status not in BookingChangeRequest.ACTIVE_STATUSES:
                raise ValidationError('This request is already closed.')
            if any(payment_was_received(p) for p in change.payments.all()):
                raise ValidationError('A change payment has been submitted. Contact our team to resolve it before withdrawing.')
            change.status = 'withdrawn'
            change.hold_start = change.hold_end = None
            change.save()
            audit(change, 'Withdrawn by customer; original booking retained.', request.user)
            success('Request withdrawn. Your original booking is unchanged.')
        else:
            raise ValidationError('Unknown request action.')
    except ValidationError as exc:
        if wants_json:
            return JsonResponse({'success':False,'message':' '.join(exc.messages)},status=400)
        messages.error(request, ' '.join(exc.messages))
    if wants_json:
        return JsonResponse({'success':True,'message':notice,
            'redirect':f'{reverse("customer_profile")}?booking_id={booking_id}&modal=details'})
    return redirect(f'{reverse("customer_profile")}?booking_id={booking_id}&modal=details')


@login_required
@deduplicate_submission
@schedule_atomic
def booking_change_payment(request, booking_id, change_id):
    try:
        change = _locked_change(request, booking_id, change_id)
    except PermissionError:
        return HttpResponseForbidden('Not allowed')
    booking = change.booking
    pending = next((p for p in change.payments.all() if p.payment_status == 'pending' and payment_was_received(p)), None)
    error = ''
    eligible = False
    try:
        if change.status != 'awaiting_payment' or not change.accepted_at:
            raise ValidationError('This quote is not awaiting additional payment.')
        check_current(change)
        eligible = True
        if request.method == 'POST':
            if pending:
                raise ValidationError('Your additional payment is awaiting verification. Please wait for our team.')
            if not request.POST.get('refund_ack'):
                raise ValidationError('Acknowledge the payment terms before continuing.')
            if not change.expires_at or timezone.now() >= change.expires_at:
                raise ValidationError('The payment deadline has passed.')
            if request.POST.get('method') == 'paymongo':
                if not settings.PAYMONGO_SECRET_KEY:
                    raise ValidationError('Online payment is unavailable. Please contact our team for assistance.')
                from .payments import _is_abandoned_paymongo_payment, _is_incomplete_paymongo_payment
                resumable = next((payment for payment in change.payments.filter(payment_status='pending', received_at__isnull=True).exclude(paymongo_checkout_url='')
                    if _is_incomplete_paymongo_payment(payment) and not _is_abandoned_paymongo_payment(payment)), None)
                if resumable:
                    request._submission_succeeded = True
                    return redirect(resumable.paymongo_checkout_url)
                checkout = create_paymongo_checkout_session(amount=int(change.additional_due*100), booking_id=booking.pk,
                    success_url=request.build_absolute_uri(reverse('paymongo_success', kwargs={'booking_id':booking.pk})+f'?change_request={change.pk}'),
                    cancel_url=request.build_absolute_uri(reverse('booking_change_payment', kwargs={'booking_id':booking.pk, 'change_id':change.pk})),
                    payment_type='gcash', description=f'Booking #{booking.pk} change request #{change.pk}')
                try:
                    session_id, checkout_url = checkout['data']['id'], checkout['data']['attributes']['checkout_url']
                except (KeyError, TypeError):
                    raise ValidationError('Unable to start online payment. Please try again or contact our team.')
                Payment.objects.create(booking=booking, change_request=change, applied_to_booking=False,
                    amount=change.additional_due, payment_type='change_balance', payment_method='paymongo_gcash',
                    transaction_ref=uuid.uuid4().hex[:16].upper(), paymongo_checkout_session_id=session_id, paymongo_checkout_url=checkout_url)
                request._submission_succeeded = True
                return redirect(checkout_url)
            reference, sender = request.POST.get('gcash_reference_number','').strip(), request.POST.get('gcash_sender_name','').strip()
            receipt = request.FILES.get('receipt_image')
            if not reference or len(reference) > 100 or not sender or len(sender) > 255 or not receipt:
                raise ValidationError('Provide the GCash reference, sender name, and receipt image.')
            from .bookings import _validate_design_delivery_image
            error = _validate_design_delivery_image(receipt)
            if error:
                raise ValidationError(error)
            if Payment.objects.filter(gcash_reference_number=reference).exclude(payment_status='rejected').exists():
                raise ValidationError('This GCash reference has already been submitted.')
            payment = Payment.objects.create(booking=booking, change_request=change, applied_to_booking=False,
                amount=change.additional_due, payment_type='change_balance', payment_method='gcash',
                transaction_ref=uuid.uuid4().hex[:16].upper(), received_at=timezone.now(),
                gcash_reference_number=reference, gcash_sender_name=sender, receipt_image=receipt)
            notify(change, f'Additional payment #{payment.pk} submitted. Verify it to finalize the accepted changes.', admin=True)
            messages.success(request, 'Additional payment submitted. Your original booking remains until verification is complete.')
            request._submission_succeeded = True
            return redirect(f'{reverse("customer_profile")}?booking_id={booking_id}&modal=details')
    except ValidationError as exc:
        error = ' '.join(exc.messages)
    # Initial, balance and change payments share one customer checkout template.
    # The amendment endpoint still owns validation and charges the saved quote.
    from .payments import _is_abandoned_paymongo_payment, _is_incomplete_paymongo_payment
    history = list(change.payments.order_by('-created_at', '-pk'))
    unfinished = next((p for p in history if _is_incomplete_paymongo_payment(p)
        and not _is_abandoned_paymongo_payment(p)), None)
    online = bool(settings.PAYMONGO_SECRET_KEY)
    displayed_booking = proposed_booking(change)
    displayed_booking.time_range_display = get_booking_time_range(displayed_booking)
    return render(request, 'client/payment_upload.html', {
        'booking':booking, 'payment_booking':displayed_booking, 'change':change,
        'is_change_payment':True, 'is_initial_payment':False, 'is_fully_paid':False,
        'pending_payment':pending, 'payment_error':error, 'payment_history':history,
        'payment_unavailable':not eligible or (not online and not pending),
        'checkout_action':reverse('booking_change_payment', args=[booking.pk, change.pk]),
        'pending_checkout_url':unfinished.paymongo_checkout_url if unfinished else None,
        'rejected_payment':next((p for p in history if p.payment_status == 'rejected'), None),
        'remaining_balance':change.additional_due, 'total_price':booking.total_price,
        **change_payment_summary(change),
    }, status=400 if error and request.method == 'POST' else 200)


def verify_change_payment(request, payment, action):
    """Called inside the admin verification transaction, under the schedule lock."""
    change = BookingChangeRequest.objects.select_for_update().select_related('booking').get(pk=payment.change_request_id)
    if action not in ('verify', 'reject'):
        messages.error(request, 'Unknown payment action.')
        return
    if action == 'reject':
        notes = request.POST.get('admin_notes', '').strip()
        if not notes:
            messages.error(request, 'A rejection reason is required.')
            return
        payment.payment_status, payment.notes = 'rejected', notes
        payment.save(update_fields=['payment_status','notes','updated_at'])
        notify(change, f'Your additional payment was rejected: {notes}. Resubmit before the quote deadline or contact our team.')
        expire_change(change)
        messages.warning(request, 'Change payment rejected. Original booking unchanged.')
        return
    if not payment_was_received(payment):
        messages.error(request, 'No successful payment or receipt has been received for this checkout.')
        return
    existing_verified = change.payments.filter(payment_status='verified').exclude(pk=payment.pk).exists()
    payment.payment_status, payment.verified_by, payment.paid_at = 'verified', request.user, timezone.now()
    payment.save(update_fields=['payment_status','verified_by','paid_at','updated_at'])
    try:
        received_at = payment.received_at or payment.created_at
        if existing_verified or change.status != 'awaiting_payment' or not change.expires_at or received_at > change.expires_at:
            raise ValidationError('This payment arrived after the quote closed or expired.')
        from ..booking_lifecycle import event_start_at
        from ..booking_changes import proposed_booking
        if min(event_start_at(change.booking), event_start_at(proposed_booking(change))) <= timezone.now():
            raise ValidationError('The event has started. Resolve the payment and schedule directly with the customer.')
        # A savepoint ensures a failed finalization cannot partially amend a booking.
        with transaction.atomic():
            apply_change(change, request.user)
        messages.success(request, 'Additional payment verified and accepted changes applied.')
    except ValidationError as exc:
        if change.status != 'applied':
            change.status = 'manual_review'
            change.hold_start = change.hold_end = None
            change.save(update_fields=['status','hold_start','hold_end','updated_at'])
        notify(change, 'Your payment is recorded, but the change needs manual review. Our team will contact you.')
        notify(change, f'Payment #{payment.pk} recorded separately; original booking unchanged. {" ".join(exc.messages)}', admin=True)
        messages.warning(request, 'Payment recorded for manual review. Original booking unchanged; no automatic refund or credit was issued.')
