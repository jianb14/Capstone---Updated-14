"""Customer dashboard, profiles, reviews and account management. (split from app/views.py)"""

from .common import *  # noqa: F401,F403
from .admin import build_dashboard_context  # noqa: F401
from .common import _cleanup_legacy_booking_request_states  # noqa: F401
from django.db.models import Avg


@login_required
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
    }

    if request.method == "POST":
        category = (request.POST.get("category") or "").strip()
        subject = (request.POST.get("subject") or "").strip()
        message_text = (request.POST.get("message") or "").strip()
        other_category = (request.POST.get("other_category") or "").strip()

        form_data = {
            "category": category,
            "other_category": other_category,
            "subject": subject,
            "message": message_text,
        }

        valid_categories = {choice[0] for choice in ConcernTicket.CATEGORY_CHOICES}

        if category not in valid_categories:
            form_error_message = "Please select a valid category."
        elif category == "other" and not other_category:
            form_error_message = "Please specify your concern type."
        elif not subject:
            form_error_message = "Please enter a subject."
        elif not message_text:
            form_error_message = "Please enter your message."
        else:
            if category == "other" and other_category:
                subject = f"{subject} (Other: {other_category})"
            ticket = ConcernTicket.objects.create(
                user=request.user,
                category=category,
                subject=subject,
                message=message_text,
            )

            # Handle multiple images
            images = request.FILES.getlist("concern_images")
            for img in images[:4]:  # Limit to 4 images
                ConcernImage.objects.create(concern=ticket, image=img)

            log_action(request.user, f"Submitted concern ticket #{ticket.id}.")

            # Admin alert email (fail-safe)
            send_admin_alert_email(
                f"New Concern Ticket #{ticket.id}",
                (
                    f"A customer reported a concern.\n\n"
                    f"Ticket ID: #{ticket.id}\n"
                    f"Customer: {request.user.get_full_name() or request.user.username} ({request.user.email})\n"
                    f"Category: {ticket.get_category_display()}\n"
                    f"Subject: {ticket.subject}\n\n"
                    f"Message:\n{ticket.message}\n\n"
                    f"Review it here: {request.build_absolute_uri('/staff/concerns/')}"
                ),
            )

            messages.success(
                request, "Concern submitted. Our team will review it soon."
            )
            return redirect("report_concern")

    if form_error_message:
        form_error_toasts = [form_error_message]

    my_tickets = ConcernTicket.objects.filter(user=request.user).order_by(
        "-created_at"
    )[:20]
    return render(
        request,
        "client/report_concern.html",
        {
            "my_tickets": my_tickets,
            "form_data": form_data,
            "form_error_toasts": form_error_toasts,
        },
    )


@login_required
def dashboard(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    return render(request, "admin/dashboard.html", build_dashboard_context(request))


@login_required
def my_profile(request):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    user_bookings = Booking.objects.filter(user=request.user)
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
        },
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

    user_bookings = Booking.objects.filter(user=request.user)

    # Calculate Stats before filtering so overall stats remain correct
    total_bookings = user_bookings.count()
    pending_count = user_bookings.filter(status="pending").count()
    confirmed_count = user_bookings.filter(status="confirmed").count()
    completed_count = user_bookings.filter(status="completed").count()

    # Apply Search Filter (by ID or Event Type)
    if search_query:
        if search_query.isdigit():
            user_bookings = user_bookings.filter(
                Q(id=search_query) | Q(event_type__icontains=search_query)
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
        user_bookings = user_bookings.order_by("event_date")
    else:
        user_bookings = user_bookings.order_by("-event_date")

    # Pagination
    paginator = Paginator(user_bookings, 10)  # Show 10 bookings per page
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Attach formatted time range for the table/modal and check if reviewed
    for b in page_obj:
        b.time_range_display = get_booking_time_range(b)
        if b.status == "completed":
            b.has_reviewed = b.reviews.filter(user=request.user).exists()
        else:
            b.has_reviewed = False
        b.price_breakdown = get_booking_price_breakdown(b)

    # Get active packages, addons, additionals for the edit modal dropdown
    active_packages = Package.objects.filter(is_active=True)
    active_addons = AddOn.objects.filter(is_active=True)
    active_additionals = AdditionalOnly.objects.all()
    service_charge_config = get_service_charge_config()

    return render(
        request,
        "client/customer_profile.html",
        {
            "page_obj": page_obj,
            "user_bookings": page_obj,  # To maintain some backward compatibility for template logic, though page_obj is better
            "total_bookings": total_bookings,
            "pending_count": pending_count,
            "confirmed_count": confirmed_count,
            "completed_count": completed_count,
            "packages": active_packages,
            "active_addons": active_addons,
            "active_additionals": active_additionals,
            "global_service_charge": service_charge_config.amount,
            "global_service_charge_note": service_charge_config.notes,
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
            Sum("payments__amount", filter=Q(payments__payment_status="verified")),
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
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking, id=id, user=request.user)

    referer = request.META.get("HTTP_REFERER", "")
    fallback_redirect = "customer_profile"
    if "my-reviews" in referer or "my_reviews" in referer:
        fallback_redirect = "my_reviews"

    if booking.status != "completed":
        messages.error(request, "You can only review completed bookings.")
        return redirect(fallback_redirect)

    # Check if already reviewed
    if booking.reviews.filter(user=request.user).exists():
        messages.error(request, "You have already reviewed this booking.")
        return redirect(fallback_redirect)

    rating = request.POST.get("rating")
    comment = request.POST.get("comment")

    if rating and comment:
        # Validate rating range
        try:
            rating_val = int(rating)
        except (ValueError, TypeError):
            messages.error(request, "Invalid rating value.")
            return redirect(fallback_redirect)
        if rating_val < 1 or rating_val > 5:
            messages.error(request, "Rating must be between 1 and 5.")
            return redirect(fallback_redirect)

        images = request.FILES.getlist("images")

        if len(images) > 4:
            messages.error(request, "You can only upload a maximum of 4 pictures.")
            return redirect(fallback_redirect)

        review = Review.objects.create(
            user=request.user, booking=booking, rating=rating, comment=comment
        )

        for img in images:
            ReviewImage.objects.create(review=review, image=img)

        log_action(request.user, f"Submitted a review for booking #{booking.id}.")

        # Notify Admin
        AdminNotification.objects.create(
            booking=booking, user=request.user, message="submitted a new review."
        )

        messages.success(request, "Thank you for your review!")
        # On success, if they were in my_reviews, redirect them to my_reviews to see it immediately.
        # Otherwise redirect to the main reviews board.
        if fallback_redirect == "my_reviews":
            return redirect("my_reviews")
        return redirect("reviews")  # Redirect to the new reviews page
    else:
        messages.error(request, "Please provide both a rating and a comment.")

    return redirect(fallback_redirect)


@login_required
def admin_profile(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    return render(request, "admin/admin_profile.html")


# =============================================================================
# MY PAYMENTS (Customer)
# =============================================================================

@login_required
def update_my_profile(request):
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        phone_number = request.POST.get("phone_number", "").strip()

        user = request.user
        user.first_name = first_name
        user.last_name = last_name
        user.phone_number = phone_number
        user.save()
        log_action(user, "Updated their profile information.")
        messages.success(request, "Profile updated successfully.")
    return redirect("my_profile")
