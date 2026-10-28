"""Customer dashboard, profiles, reviews and account management. (split from app/views.py)"""

from .common import *  # noqa: F401,F403
from .admin import build_dashboard_context  # noqa: F401
from .common import _cleanup_legacy_booking_request_states  # noqa: F401
from django.db.models import Avg
from django.utils.formats import date_format
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from PIL import Image
from ..booking_lifecycle import lifecycle_display
from ..booking_changes import eligibility
from ..profile_forms import EditProfileForm
from ..account_lists import account_page_size
from ..request_protection import deduplicate_submission


def _concern_data(ticket):
    return {
        'id': ticket.pk, 'number': f'#CON-{ticket.pk}', 'subject': ticket.subject,
        'message': ticket.message, 'category': ticket.get_category_display(),
        'status': ticket.status, 'status_label': ticket.get_status_display(),
        'created': date_format(timezone.localtime(ticket.created_at), 'M d, Y g:i A'),
        'updated': date_format(timezone.localtime(ticket.updated_at), 'M d, Y g:i A'),
        'admin_notes': ticket.admin_notes or '', 'can_cancel': ticket.can_cancel,
        'cancel_url': reverse('cancel_concern', args=[ticket.pk]),
        'images': [image.image.url for image in ticket.images.all()],
    }


def _concern_submitted(request, ticket):
    request._submission_succeeded = True
    text = 'Concern submitted. Our team will review it soon.'
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': text, 'ticket_id': ticket.pk,
                             'redirect_url': reverse('report_concern')})
    messages.success(request, text)
    return redirect('report_concern')


@login_required
@require_http_methods(['GET', 'POST'])
@deduplicate_submission
def report_concern(request):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    form_error_message = ""
    form_error_toasts = []
    form_data = {
        "category": "",
        "other_category": "",
        "subject": "",
        "message": "",
        "submission_key": str(uuid.uuid4()),
    }

    if request.method == "POST":
        category = (request.POST.get("category") or "").strip()
        subject = (request.POST.get("subject") or "").strip()
        message_text = (request.POST.get("message") or "").strip()
        other_category = (request.POST.get("other_category") or "").strip()
        raw_key = (request.POST.get('submission_key') or '').strip()
        submission_key = None
        if raw_key:
            try:
                submission_key = uuid.UUID(raw_key)
            except ValueError:
                form_error_message = 'Please try submitting the form again.'

        form_data = {
            "category": category,
            "other_category": other_category,
            "subject": subject,
            "message": message_text,
            "submission_key": str(submission_key or uuid.uuid4()),
        }

        valid_categories = {choice[0] for choice in ConcernTicket.CATEGORY_CHOICES}

        images = request.FILES.getlist('concern_images')
        stored_subject = f'{subject} (Other: {other_category})' if category == 'other' else subject
        if form_error_message:
            pass
        elif category not in valid_categories:
            form_error_message = "Please select a valid category."
        elif category == "other" and not other_category:
            form_error_message = "Please specify your concern type."
        elif not subject:
            form_error_message = "Please enter a subject."
        elif not message_text:
            form_error_message = "Please enter your message."
        elif len(stored_subject) > 150 or len(other_category) > 80:
            form_error_message = 'Please shorten the subject or concern type (150 characters combined).'
        elif len(images) > 4:
            form_error_message = 'You can attach up to 4 images.'
        elif any(image.size > 5 * 1024 * 1024 for image in images):
            form_error_message = 'Each image must be 5MB or smaller.'
        else:
            for image in images:
                try:
                    with Image.open(image) as decoded:
                        if decoded.format not in {'JPEG', 'PNG', 'WEBP'}:
                            raise ValueError('Unsupported image format')
                        decoded.verify()
                    image.seek(0)
                    width, height = get_image_dimensions(image)
                    if not width or not height:
                        raise ValueError('Invalid image')
                except (ValueError, OSError, TypeError):
                    form_error_message = 'Please attach valid image files.'
                    break
                finally:
                    image.seek(0)

        if not form_error_message:
            with transaction.atomic():
                # This also serializes retries whose fields changed after a lost response.
                User.objects.select_for_update().get(pk=request.user.pk)
                ticket = (ConcernTicket.objects.filter(user=request.user, submission_key=submission_key).first()
                          if submission_key else None)
                if ticket is None:
                    ticket = ConcernTicket.objects.create(user=request.user, category=category,
                        subject=stored_subject, message=message_text, submission_key=submission_key)
                    for image in images:
                        ConcernImage.objects.create(concern=ticket, image=image)
                    AdminNotification.objects.create(user=request.user, concern=ticket,
                        message=f'submitted concern #CON-{ticket.pk}: {ticket.subject}')
                    log_action(request.user, f'Submitted concern ticket #{ticket.id}.')
                    send_admin_alert_email(
                        f'New Concern Ticket #{ticket.id}',
                        f'A customer reported a concern.\n\nTicket ID: #{ticket.id}\n'
                        f'Customer: {request.user.get_full_name() or request.user.username} ({request.user.email})\n'
                        f'Category: {ticket.get_category_display()}\nSubject: {ticket.subject}\n\n'
                        f'Message:\n{ticket.message}\n\n'
                        f"Review it here: {request.build_absolute_uri(reverse('admin_concerns'))}?concern_id={ticket.pk}")
                return _concern_submitted(request, ticket)

    if form_error_message:
        form_error_toasts = [form_error_message]
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': form_error_message}, status=400)

    per_page = account_page_size(request)
    tickets = ConcernTicket.objects.filter(user=request.user)
    page_number = request.GET.get('page')
    if request.GET.get('concern_id'):
        try:
            concern_id = int(request.GET['concern_id'])
        except ValueError:
            raise Http404('Concern not found')
        selected = get_object_or_404(tickets, pk=concern_id)
        ahead = tickets.filter(Q(created_at__gt=selected.created_at)
            | Q(created_at=selected.created_at, pk__gt=selected.pk)).count()
        page_number = ahead // per_page + 1
    tickets_page = Paginator(tickets.prefetch_related('images').order_by('-created_at', '-pk'), per_page).get_page(page_number)
    my_tickets = tickets_page.object_list
    return render(
        request,
        "client/report_concern.html",
        {
            "my_tickets": my_tickets,
            "tickets_page": tickets_page,
            "per_page": per_page,
            "form_data": form_data,
            "form_error_toasts": form_error_toasts,
            "form_error_message": form_error_message,
            "ticket_data": [_concern_data(ticket) for ticket in my_tickets],
        },
    )


@login_required
@require_POST
def cancel_concern(request, id):
    if request.user.role != 'customer':
        return HttpResponseForbidden('Not allowed')
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        ticket = get_object_or_404(ConcernTicket.objects.select_for_update(), pk=id, user=request.user)
        if ticket.status == 'cancelled':
            success = True
        elif ticket.can_cancel:
            ticket.status = 'cancelled'
            ticket.save(update_fields=['status', 'updated_at'])
            log_action(request.user, f'Cancelled concern ticket #{ticket.pk}.')
            success = True
        else:
            success = False
        text = ('Concern cancelled. It will remain in your history.' if success else
                'This concern is already being handled and can no longer be cancelled.')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': success, 'message': text, 'ticket': _concern_data(ticket)},
                                status=200 if success else 409)
        (messages.success if success else messages.error)(request, text)
        return redirect('report_concern')


@login_required
@require_GET
def dashboard(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")
    from django.core.exceptions import ValidationError
    from ..dashboard_reporting import build_dashboard, dashboard_filters
    try:
        context = build_dashboard_context(request)
    except ValidationError as error:
        message = ' '.join(error.messages)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'error': message}, status=400)
        context = build_dashboard(dashboard_filters({}))
        context['filter_error'] = message
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        response = JsonResponse({
            'html': render_to_string('admin/dashboard/_results.html', context, request=request),
            'operations_html': render_to_string('admin/dashboard/_operations.html', context, request=request),
            'filters': context['filters'].params(),
            'analytics_url': context['analytics_url'],
            'updated': context['generated_at'].strftime('%I:%M %p').lstrip('0'),
        })
    else:
        response = render(request, 'admin/dashboard.html', context)
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@never_cache
def my_profile(request, *, profile_form=None):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    user_bookings = Booking.objects.filter(user=request.user).prefetch_related("design_deliveries")
    total_bookings = user_bookings.count()
    pending_count = user_bookings.filter(status="pending").count()
    confirmed_count = user_bookings.filter(status="confirmed").count()
    completed_count = user_bookings.filter(status="completed").count()

    # Recent Activity timeline — existing AuditLog entries ng user
    activity_logs = AuditLog.objects.filter(user=request.user)[:8]

    return render(
        request,
        "client/my_profile.html",
        {
            "total_bookings": total_bookings,
            "pending_count": pending_count,
            "confirmed_count": confirmed_count,
            "completed_count": completed_count,
            "activity_logs": activity_logs,
            "profile_form": profile_form if profile_form is not None else EditProfileForm(initial={
                'first_name': request.user.first_name,
                'last_name': request.user.last_name,
                'phone_number': request.user.phone_number,
            }),
        },
        status=400 if profile_form is not None and profile_form.is_bound else 200,
    )


@login_required
def my_reviews(request):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    reviews_list = (
        Review.objects.filter(user=request.user)
        .select_related("booking")
        .order_by("-created_at")
    )

    # Stats para sa page header (published count + average rating na binigay ng user)
    published_count = reviews_list.count()
    avg_rating = reviews_list.aggregate(v=Avg("rating"))["v"]

    # Pagination for published reviews (5 per page)
    paginator_published = Paginator(reviews_list, 5)
    page_published_number = request.GET.get("page_published", 1)
    try:
        reviews = paginator_published.page(page_published_number)
    except PageNotAnInteger:
        reviews = paginator_published.page(1)
    except EmptyPage:
        reviews = paginator_published.page(paginator_published.num_pages)

    # Check if the current user has liked each review (though they are their own reviews, just in case template expects it)
    for review in reviews:
        review.is_liked_by_user = review.likes.filter(id=request.user.id).exists()
        review.can_be_liked = False  # cannot like own review

        images_data = [
            {"id": img.id, "url": img.image.url} for img in review.images.all()
        ]
        review.images_json = json.dumps(images_data)

    # Fetch completed bookings without reviews
    pending_reviews_list = Booking.objects.filter(
        user=request.user, status="completed", reviews__isnull=True
    ).order_by("-event_date")

    # Pagination for pending reviews (5 per page)
    paginator_pending = Paginator(pending_reviews_list, 5)
    page_pending_number = request.GET.get("page_pending", 1)
    try:
        pending_reviews = paginator_pending.page(page_pending_number)
    except PageNotAnInteger:
        pending_reviews = paginator_pending.page(1)
    except EmptyPage:
        pending_reviews = paginator_pending.page(paginator_pending.num_pages)

    # Attach formatted time range
    for b in pending_reviews:
        b.time_range_display = get_booking_time_range(b)

    return render(
        request,
        "client/my_reviews.html",
        {
            "reviews": reviews,
            "published_page_obj": reviews,
            "pending_reviews": pending_reviews,
            "pending_page_obj": pending_reviews,
            "published_count": published_count,
            "avg_rating": avg_rating,
        },
    )


@login_required
def customer_profile(request):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    _cleanup_legacy_booking_request_states()
    _sync_customer_booking_payment_states(request.user)

    # Auto-expire pending bookings in the past
    check_booking_expirations()

    # Get filter parameters
    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "all")
    sort_date = request.GET.get("sort_date", "id_desc")
    if status_filter != 'all' and status_filter not in dict(Booking.STATUS_CHOICES):
        status_filter = 'all'
    if sort_date not in ('id_desc', 'id_asc', 'newest', 'oldest'):
        sort_date = 'id_desc'

    user_bookings = Booking.objects.filter(user=request.user).prefetch_related("design_deliveries", "images", "designs", "reviews", "payments", "change_requests__payments")

    # Calculate Stats before filtering so overall stats remain correct
    total_bookings = user_bookings.count()
    pending_count = user_bookings.filter(status="pending").count()
    confirmed_count = user_bookings.filter(status="confirmed").count()
    completed_count = user_bookings.filter(status="completed").count()

    # Apply Search Filter (by ID or Event Type)
    if search_query:
        identifier = search_query.removeprefix('#')
        if identifier.isascii() and identifier.isdecimal() and len(identifier) <= 19 and int(identifier) <= 9223372036854775807:
            user_bookings = user_bookings.filter(
                Q(id=int(identifier)) | Q(event_type__icontains=search_query)
            )
        else:
            user_bookings = user_bookings.filter(event_type__icontains=search_query)

    # Apply Status Filter
    if status_filter != "all":
        user_bookings = user_bookings.filter(status=status_filter)

    # Apply Sorting
    if sort_date == "id_desc":
        user_bookings = user_bookings.order_by("-id")
    elif sort_date == "id_asc":
        user_bookings = user_bookings.order_by("id")
    elif sort_date == "oldest":
        user_bookings = user_bookings.order_by("event_date", "id")
    else:
        user_bookings = user_bookings.order_by("-event_date", "-id")

    # Pagination
    per_page = account_page_size(request)
    paginator = Paginator(user_bookings, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Attach formatted time range for the table/modal and check if reviewed
    for b in page_obj:
        b.time_range_display = get_booking_time_range(b)
        b.lifecycle = lifecycle_display(b)
        if b.status == "completed":
            b.has_reviewed = any(review.user_id == request.user.id for review in b.reviews.all())
        else:
            b.has_reviewed = False
        b.schedule = get_booking_schedule(b)
        b.can_request_changes, b.change_unavailable_reason = eligibility(b)

    # Edit deep links must work outside the current list page/search/status filter.
    edit_link_booking = None
    edit_link_id = request.GET.get("open_edit", "")
    if edit_link_id:
        if not edit_link_id.isdigit():
            raise Http404("Booking not found")
        target = get_object_or_404(Booking.objects.prefetch_related("images", "designs"), pk=edit_link_id, user=request.user)
        if target.status != "pending" and not eligibility(target)[0]:
            messages.error(request, eligibility(target)[1])
        elif not any(b.pk == target.pk for b in page_obj):
            target.schedule = get_booking_schedule(target)
            edit_link_booking = target

    # Get active packages, addons, additionals for the edit modal dropdown
    active_packages = Package.objects.filter(is_active=True).prefetch_related("preview_images")
    active_addons = AddOn.objects.filter(is_active=True).prefetch_related("preview_images")
    active_additionals = AdditionalOnly.objects.all().prefetch_related("preview_images")
    service_charge_config = get_service_charge_config()
    lead_days, min_bookable_date = get_booking_lead_time_policy()

    # Edit-modal Preview (Step 2 mirror): name-keyed preview map para sa
    # renderEditPackagePreview() — walang bagong query, reuse ng prefetches.
    edit_preview_data = {
        str(p.name): [img.image.url for img in p.preview_images.all() if img.image][:2]
        for p in active_packages
    }
    for a in active_addons:
        edit_preview_data.setdefault(
            str(a.name),
            [img.image.url for img in a.preview_images.all() if img.image][:2],
        )
    for a in active_additionals:
        edit_preview_data.setdefault(
            str(a.name),
            [img.image.url for img in a.preview_images.all() if img.image][:2],
        )

    return render(
        request,
        "client/customer_profile.html",
        {
            "page_obj": page_obj,
            "per_page": per_page,
            "edit_link_booking": edit_link_booking,
            "user_bookings": page_obj,  # To maintain some backward compatibility for template logic, though page_obj is better
            "total_bookings": total_bookings,
            "pending_count": pending_count,
            "confirmed_count": confirmed_count,
            "completed_count": completed_count,
            "packages": active_packages,
            "active_addons": active_addons,
            "active_additionals": active_additionals,
            "edit_preview_data": edit_preview_data,
            "global_service_charge": service_charge_config.amount,
            "global_service_charge_note": service_charge_config.notes,
            "availability_data": get_booking_form_availability(),
            "logistics_config": get_booking_logistics_config(),
            "cavite_boundary": get_cavite_geometry(),
            "booking_lead_time_days": lead_days,
            "min_bookable_date": min_bookable_date.isoformat(),
            "search_query": search_query,
            "status_filter": status_filter,
            "sort_date": sort_date,
        },
    )


def _sync_customer_booking_payment_states(user):
    zero = Decimal("0.00")
    bookings = Booking.objects.filter(
        user=user, status__in=["pending_payment", "confirmed"]
    ).annotate(
        verified_total=Coalesce(
            Sum("payments__amount", filter=Q(payments__payment_status="verified", payments__applied_to_booking=True)),
            Decimal("0.00"),
        )
    )

    now = timezone.now()
    to_update = []
    status_transitions = []

    for booking in bookings:
        verified_total = booking.verified_total or zero
        total_price = booking.total_price or zero

        if verified_total >= total_price and total_price > zero:
            target_payment_status = "paid"
        elif verified_total > zero:
            target_payment_status = "partial"
        else:
            target_payment_status = "pending"

        old_status = booking.status
        target_status = booking.status
        if booking.status == "pending_payment" and verified_total > zero:
            target_status = "confirmed"

        if (
            booking.payment_status != target_payment_status
            or booking.status != target_status
        ):
            booking.payment_status = target_payment_status
            booking.status = target_status
            booking.updated_at = now
            to_update.append(booking)
            status_transitions.append((booking, old_status, target_status))

    if to_update:
        Booking.objects.bulk_update(
            to_update, ["payment_status", "status", "updated_at"]
        )

        # Record status transitions in each booking's history timeline
        for booking, old_status, new_status in status_transitions:
            if new_status != old_status:
                log_booking_status(
                    booking,
                    old_status,
                    new_status,
                    notes="Payment state synced after customer payment update.",
                )


@login_required
@require_POST
def submit_review(request, id):
    wants_json = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if request.user.role != "customer":
        return JsonResponse({'message': 'Not allowed.'}, status=403) if wants_json else HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking, id=id, user=request.user)
    referer = request.META.get("HTTP_REFERER", "")
    fallback_redirect = "my_reviews" if "my-reviews" in referer or "my_reviews" in referer else "customer_profile"

    def invalid(message, field=None):
        if wants_json:
            return JsonResponse({'message': message, 'errors': {field: message} if field else {}}, status=400)
        messages.error(request, message)
        return redirect(fallback_redirect)

    # Serialize concurrent submissions for the same booking.
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.status != "completed":
            return invalid("You can only review completed bookings.")
        if booking.reviews.filter(user=request.user).exists():
            return invalid("You have already reviewed this booking.")
        try:
            rating = int(request.POST.get('rating') or 0)
        except (ValueError, TypeError):
            rating = 0
        comment = (request.POST.get('comment') or '').strip()
        if not 1 <= rating <= 5:
            return invalid('Rating must be between 1 and 5.', 'rating')
        if not comment:
            return invalid('Please enter your review.', 'comment')
        images = request.FILES.getlist('images')
        if len(images) > 4:
            return invalid('You can only upload a maximum of 4 pictures.')
        review = Review.objects.create(user=request.user, booking=booking, rating=rating, comment=comment)
        for image in images:
            ReviewImage.objects.create(review=review, image=image)
        log_action(request.user, f"Submitted a review for booking #{booking.id}.")
        AdminNotification.objects.create(booking=booking, user=request.user, message="submitted a new review.")
    if wants_json:
        return JsonResponse({'status': 'success', 'message': 'Thank you for your review!', 'review_id': review.pk}, status=201)
    messages.success(request, 'Thank you for your review!')
    return redirect('my_reviews' if fallback_redirect == 'my_reviews' else 'reviews')


@never_cache
@login_required
@require_http_methods(['GET'])
def admin_profile(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")
    from ..admin_security import pending_challenge
    unverified = not request.user.email_verified
    return render(request, "admin/admin_profile.html", {
        'pending_security': pending_challenge(request, 'email') if unverified else {},
        'open_email_setup': unverified and (request.session.get('admin_email_setup_required')
                                            or request.GET.get('verify_email') == '1'),
        'recent_activity': AuditLog.objects.filter(user=request.user).order_by('-created_at', '-pk')[:5],
        'password_code_pending': bool(request.session.get('email_otp_change')),
    })


# =============================================================================
# MY PAYMENTS (Customer)
# =============================================================================

@login_required
def update_my_profile(request):
    if request.method == "POST":
        form = EditProfileForm(request.POST)
        if not form.is_valid():
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success':False,'message':'Please check your profile details.',
                    'errors':{name:list(errors) for name,errors in form.errors.items()}},status=400)
            return my_profile(request, profile_form=form)

        user = request.user
        user.first_name = form.cleaned_data['first_name']
        user.last_name = form.cleaned_data['last_name']
        user.phone_number = form.cleaned_data['phone_number']
        user.save(update_fields=['first_name', 'last_name', 'phone_number'])
        log_action(user, "Updated their profile information.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success':True,'message':'Profile updated successfully.',
                'redirect_url':reverse('my_profile')})
        messages.success(request, "Profile updated successfully.")
    return redirect("my_profile")
