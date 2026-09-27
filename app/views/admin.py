"""Admin: dashboard, content mgmt, users, analytics, gallery, reviews. (split from app/views.py)"""

from .common import *  # noqa: F401,F403
from .common import _cleanup_legacy_booking_request_states, _pdf_link_callback  # noqa: F401


# Helper to extract End Time from special_requests string

@login_required
def admin_site_settings(request):
    """Central site settings page (admin role only)."""
    if request.user.role != "admin":
        return HttpResponseForbidden("Admins only")

    settings_obj = SiteSettings.load()

    if request.method == "POST":
        site_name = (request.POST.get("site_name") or "").strip()[:150]
        contact_email = (request.POST.get("contact_email") or "").strip()[:255]
        contact_phone = (request.POST.get("contact_phone") or "").strip()[:50]
        address = (request.POST.get("address") or "").strip()[:255]
        facebook_link = (request.POST.get("facebook_link") or "").strip()[:200]
        instagram_link = (request.POST.get("instagram_link") or "").strip()[:200]
        admin_emails_raw = (request.POST.get("admin_emails_for_notifications") or "").strip()[:500]
        email_notifications_enabled = request.POST.get("email_notifications_enabled") == "on"

        lead_time_raw = (request.POST.get("booking_lead_time_days") or "0").strip()
        try:
            booking_lead_time_days = max(0, int(lead_time_raw))
        except ValueError:
            booking_lead_time_days = 0

        if not site_name:
            messages.error(request, "Site name is required.")
        else:
            settings_obj.site_name = site_name
            settings_obj.contact_email = contact_email
            settings_obj.contact_phone = contact_phone
            settings_obj.address = address
            settings_obj.facebook_link = facebook_link
            settings_obj.instagram_link = instagram_link
            settings_obj.booking_lead_time_days = booking_lead_time_days
            settings_obj.admin_emails_for_notifications = ", ".join(
                e for e in (x.strip() for x in admin_emails_raw.split(",")) if e
            )
            settings_obj.email_notifications_enabled = email_notifications_enabled
            settings_obj.updated_by = request.user
            settings_obj.save()

            log_action(request.user, "Updated site settings.")
            messages.success(request, "Site settings saved successfully.")

        return redirect("admin_site_settings")

    return render(
        request,
        "admin/settings/admin_site_settings.html",
        {"settings": settings_obj},
    )


@login_required
def admin_user_list(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    # 1. Kunin lahat ng users
    users_list = User.objects.all().order_by("username")

    # 2. Role Filter
    role_filter = request.GET.get("role")
    if role_filter and role_filter in ["admin", "customer"]:
        users_list = users_list.filter(role=role_filter)

    # 2A. Status Filter (active/inactive)
    status_filter = request.GET.get("status", "").strip()
    if status_filter == "active":
        users_list = users_list.filter(is_active=True)
    elif status_filter == "inactive":
        users_list = users_list.filter(is_active=False)

    # 3. Search Logic
    search_query = request.GET.get("search")
    if search_query:
        users_list = users_list.filter(
            Q(username__icontains=search_query)
            | Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
            | Q(email__icontains=search_query)
        )

    # 4. Summary cards (mirrors admin booking summary grid)
    all_users = User.objects.all()
    user_summary = {
        "total": all_users.count(),
        "active": all_users.filter(is_active=True).count(),
        "inactive": all_users.filter(is_active=False).count(),
        "admins": all_users.filter(role="admin").count(),
        "staff": all_users.filter(role="staff").count(),
        "customers": all_users.filter(role="customer").count(),
    }

    # 5. Pagination Logic (10 items per page)
    paginator = Paginator(users_list, 10)
    page_number = request.GET.get("page")
    users = paginator.get_page(page_number)

    return render(
        request,
        "admin/user/admin_user_list.html",
        {"users": users, "user_summary": user_summary},
    )


@login_required
def admin_user_edit(request, id):
    if request.user.role != "admin":
        return HttpResponseForbidden("Admins only")

    user_obj = get_object_or_404(User, id=id)

    # ❌ bawal i-edit ang sarili
    if user_obj == request.user:
        messages.error(request, "You cannot edit your own account.")
        return redirect("admin_user_list")

    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip()
        phone_number = request.POST.get("phone_number", "").strip()
        role = request.POST.get("role", "").strip()

        user_obj.first_name = first_name
        user_obj.last_name = last_name
        user_obj.email = email
        user_obj.phone_number = phone_number
        user_obj.role = role

        if not first_name:
            messages.error(request, "First name is required.")
            return render(request, "admin/user/admin_user_edit.html", {"u": user_obj})

        if not last_name:
            messages.error(request, "Last name is required.")
            return render(request, "admin/user/admin_user_edit.html", {"u": user_obj})

        if not email:
            messages.error(request, "Email is required.")
            return render(request, "admin/user/admin_user_edit.html", {"u": user_obj})

        if not phone_number:
            messages.error(request, "Phone number is required.")
            return render(request, "admin/user/admin_user_edit.html", {"u": user_obj})

        valid_roles = {"admin", "customer"}
        if role not in valid_roles:
            messages.error(request, "Role is required.")
            return render(request, "admin/user/admin_user_edit.html", {"u": user_obj})

        log_action(request.user, f"Edited user profile for '{user_obj.username}'.")
        user_obj.save()
        messages.success(request, "User updated successfully.")
        return redirect("admin_user_list")

    return render(request, "admin/user/admin_user_edit.html", {"u": user_obj})


@login_required
def admin_user_detail(request, id):
    """Detailed profile view for a single user: bookings, payments, reviews."""
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    user_obj = get_object_or_404(User, id=id)

    user_bookings = (
        Booking.objects.filter(user=user_obj)
        .prefetch_related("payments")
        .order_by("-created_at")
    )
    for b in user_bookings[:20]:
        b.time_range_display = get_booking_time_range(b)

    booking_count = user_bookings.count()
    total_spent = (
        user_bookings.filter(status__in=["confirmed", "completed"])
        .aggregate(total=Sum("total_price"))["total"]
        or Decimal("0.00")
    )

    user_payments = Payment.objects.filter(booking__user=user_obj).select_related(
        "booking"
    ).order_by("-created_at")[:20]

    user_reviews = Review.objects.filter(user=user_obj).select_related("booking").order_by(
        "-created_at"
    )[:20]

    context = {
        "u": user_obj,
        "user_bookings": user_bookings[:20],
        "booking_count": booking_count,
        "total_spent": total_spent,
        "user_payments": user_payments,
        "user_reviews": user_reviews,
    }
    return render(request, "admin/user/admin_user_detail.html", context)


@login_required
@require_POST
def admin_user_reset_password(request, id):
    """Send a password reset link to a user's email address."""
    if request.user.role != "admin":
        return HttpResponseForbidden("Admins only")

    user_obj = get_object_or_404(User, id=id)

    if user_obj.role == "admin":
        messages.error(
            request,
            "Password reset is not available for administrator accounts.",
        )
        return redirect("admin_user_detail", id=user_obj.id)

    if not user_obj.email:
        messages.error(request, f"User '{user_obj.username}' has no email address on file.")
        return redirect("admin_user_detail", id=user_obj.id)

    token = default_token_generator.make_token(user_obj)
    uid = urlsafe_base64_encode(force_bytes(user_obj.pk))
    reset_link = request.build_absolute_uri(
        reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})
    )

    try:
        send_mail(
            subject="Password Reset Request | Balloorina",
            message=(
                f"Hi {user_obj.get_full_name() or user_obj.username},\n\n"
                "An administrator requested a password reset for your Balloorina account.\n"
                "Click the link below to set a new password (valid for 30 minutes):\n\n"
                f"{reset_link}\n\n"
                "If you did not expect this, you can safely ignore this email.\n\n"
                "— Balloorina Team"
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[user_obj.email],
            fail_silently=False,
        )
        log_action(
            request.user,
            f"Sent password reset email to '{user_obj.username}'.",
        )
        messages.success(
            request,
            f"Password reset link sent to {user_obj.email}.",
        )
    except Exception:
        logger.exception("Failed to send password reset email to user #%s", user_obj.id)
        messages.error(
            request,
            "Could not send the password reset email right now. Please try again later.",
        )

    return redirect("admin_user_detail", id=user_obj.id)


@login_required
def admin_user_toggle_active(request, id):
    if request.user.role != "admin":
        return HttpResponseForbidden("Admins only")

    user_obj = get_object_or_404(User, id=id)

    if user_obj == request.user:
        messages.error(request, "You cannot deactivate yourself.")
        return redirect("admin_user_list")

    user_obj.is_active = not user_obj.is_active
    user_obj.save()

    status = "activated" if user_obj.is_active else "deactivated"
    log_action(
        request.user, f"User account for '{user_obj.username}' has been {status}."
    )
    messages.success(
        request, f"User '{user_obj.username}' has been {status} successfully."
    )
    return redirect("admin_user_list")


@login_required
def admin_user_delete(request, id):
    if request.user.role != "admin":
        return HttpResponseForbidden("Admins only")

    user_obj = get_object_or_404(User, id=id)

    if user_obj == request.user:
        messages.error(request, "You cannot delete yourself.")
        return redirect("admin_user_list")

    username = user_obj.username
    user_obj.delete()
    log_action(request.user, f"Deleted user account for '{username}'.")
    messages.success(request, "User deleted.")
    return redirect("admin_user_list")


@login_required
def admin_audit_log_list(request):
    if request.user.role not in ["admin"]:
        return HttpResponseForbidden("Admins only")

    log_list = AuditLog.objects.select_related("user").all()

    # Filters
    search_query = request.GET.get("search", "").strip()
    role_filter = request.GET.get("role", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    if search_query:
        log_list = log_list.filter(
            Q(action__icontains=search_query)
            | Q(user__username__icontains=search_query)
            | Q(user__email__icontains=search_query)
        )

    if role_filter:
        log_list = log_list.filter(user__role=role_filter)

    if date_from:
        try:
            log_list = log_list.filter(created_at__date__gte=date_from)
        except (ValueError, ValidationError):
            pass

    if date_to:
        try:
            log_list = log_list.filter(created_at__date__lte=date_to)
        except (ValueError, ValidationError):
            pass

    # Pagination Logic (15 items per page)
    paginator = Paginator(log_list, 15)
    page_number = request.GET.get("page")
    logs = paginator.get_page(page_number)

    return render(
        request,
        "admin/audit_log_list.html",
        {
            "logs": logs,
            "search_query": search_query,
            "role_filter": role_filter,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@login_required
def admin_package_create(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST":
        features = request.POST.get("features", "").strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render(request, "admin/package/package_form.html")

        try:
            price = Decimal(request.POST.get("price", ""))
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(request, "admin/package/package_form.html")

        MAX_PRICE = Decimal("99999999.99")
        if price < 0 or price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(request, "admin/package/package_form.html")

        package = Package.objects.create(
            name=request.POST.get("name"),
            image=request.FILES.get("image"),
            description=request.POST.get("description"),
            features=features,
            price=price,
            notes=request.POST.get("notes"),
            is_featured=bool(request.POST.get("is_featured")),
        )

        log_action(request.user, f"Created new package: '{package.name}'.")
        messages.success(request, "Package created successfully!")
        return redirect("admin_package_list")

    return render(request, "admin/package/package_form.html")


@login_required
def admin_package_edit(request, id):
    package = get_object_or_404(Package, id=id)

    if request.method == "POST":
        features = request.POST.get("features", "").strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render(
                request, "admin/package/package_form.html", {"package": package}
            )

        try:
            package.price = Decimal(request.POST.get("price", ""))
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(
                request, "admin/package/package_form.html", {"package": package}
            )

        MAX_PRICE = Decimal("99999999.99")
        if package.price < 0 or package.price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(
                request, "admin/package/package_form.html", {"package": package}
            )

        package.name = request.POST.get("name")
        package.description = request.POST.get("description")
        package.features = features
        package.notes = request.POST.get("notes")
        package.is_featured = bool(request.POST.get("is_featured"))

        if request.FILES.get("image"):
            package.image = request.FILES.get("image")

        package.save()
        log_action(request.user, f"Edited package: '{package.name}'.")
        messages.success(request, "Package updated successfully!")
        return redirect("admin_package_list")

    return render(request, "admin/package/package_form.html", {"package": package})


@login_required
def admin_package_list(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    # Featured packages first, then others, newest first
    packages = Package.objects.all().order_by("-is_featured", "-created_at")
    addons = AddOn.objects.all().order_by("-created_at")
    additionals = AdditionalOnly.objects.all().order_by("-created_at")
    service_charge_config = get_service_charge_config()

    return render(
        request,
        "admin/package/package_list.html",
        {
            "packages": packages,
            "addons": addons,
            "additionals": additionals,
            "service_charge_config": service_charge_config,
        },
    )


@login_required
def admin_service_charge_update(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    if request.method != "POST":
        return redirect("admin_package_list")

    config = get_service_charge_config()
    amount_raw = request.POST.get("service_charge_amount", "").strip()
    notes = request.POST.get("service_charge_notes", "").strip()

    if not notes:
        messages.error(request, "Service charge notes are required.")
        return redirect("admin_package_list")

    if not amount_raw:
        messages.error(request, "Service charge amount is required.")
        return redirect("admin_package_list")

    try:
        amount = Decimal(amount_raw)
    except InvalidOperation:
        messages.error(request, "Invalid service charge amount.")
        return redirect("admin_package_list")

    max_price = Decimal("99999999.99")
    if amount < 0 or amount > max_price:
        messages.error(request, "Service charge must be between 0 and 99,999,999.99.")
        return redirect("admin_package_list")

    config.amount = amount
    config.notes = notes
    config.save()

    log_action(request.user, f"Updated global service charge to {config.amount}.")
    messages.success(request, "Service charge settings updated.")
    return redirect("admin_package_list")


@login_required
def admin_package_detail(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    package = get_object_or_404(Package, id=id)

    return render(request, "admin/package/package_detail.html", {"package": package})


@login_required
def admin_package_delete(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    package = get_object_or_404(Package, id=id)
    package_name = package.name
    package.delete()
    log_action(request.user, f"Deleted package: '{package_name}'.")
    messages.success(request, "Package deleted successfully!")
    return redirect("admin_package_list")


def package(request):
    packages = Package.objects.all().order_by("-is_featured", "-created_at")
    addons = AddOn.objects.filter(is_active=True).order_by("-created_at")
    additionals = AdditionalOnly.objects.filter(is_active=True).order_by("-created_at")
    service_charge_config = get_service_charge_config()

    return render(
        request,
        "client/package.html",
        {
            "packages": packages,
            "addons": addons,
            "additionals": additionals,
            "service_charge_amount": service_charge_config.amount,
            "service_charge_notes": service_charge_config.notes,
        },
    )


from decimal import Decimal, InvalidOperation


@login_required
def admin_addon_create(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST":
        features = request.POST.get("features", "").strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render(request, "admin/package/addon_form.html")

        solo_raw = request.POST.get("solo_price", "").strip()
        if not solo_raw:
            messages.error(request, "Solo price is required.")
            return render(request, "admin/package/addon_form.html")

        try:
            price = Decimal(request.POST.get("price", ""))
            solo_price = Decimal(solo_raw)
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(request, "admin/package/addon_form.html")

        MAX_PRICE = Decimal("99999999.99")
        if price < 0 or price > MAX_PRICE or solo_price < 0 or solo_price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(request, "admin/package/addon_form.html")

        addon = AddOn.objects.create(
            name=request.POST.get("name"),
            image=request.FILES.get("image"),
            price=price,
            solo_price=solo_price,
            features=features,
        )

        log_action(request.user, f"Created new add-on: '{addon.name}'.")
        messages.success(request, "Add-on created successfully!")
        return redirect("admin_package_list")

    return render(request, "admin/package/addon_form.html")


@login_required
def admin_addon_detail(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    addon = get_object_or_404(AddOn, id=id)

    return render(request, "admin/package/addon_detail.html", {"addon": addon})


@login_required
def admin_addon_edit(request, id):
    addon = get_object_or_404(AddOn, id=id)

    if request.method == "POST":
        features = request.POST.get("features", "").strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render(request, "admin/package/addon_form.html", {"addon": addon})

        solo_raw = request.POST.get("solo_price", "").strip()
        if not solo_raw:
            messages.error(request, "Solo price is required.")
            return render(request, "admin/package/addon_form.html", {"addon": addon})

        try:
            addon.price = Decimal(request.POST.get("price", ""))
            addon.solo_price = Decimal(solo_raw)
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(request, "admin/package/addon_form.html", {"addon": addon})

        MAX_PRICE = Decimal("99999999.99")
        if (
            addon.price < 0
            or addon.price > MAX_PRICE
            or addon.solo_price < 0
            or addon.solo_price > MAX_PRICE
        ):
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(request, "admin/package/addon_form.html", {"addon": addon})

        addon.name = request.POST.get("name")
        addon.features = features

        if request.FILES.get("image"):
            addon.image = request.FILES.get("image")

        addon.save()

        log_action(request.user, f"Edited add-on: '{addon.name}'.")
        messages.success(request, "Add-on updated successfully!")
        return redirect("admin_package_list")

    return render(request, "admin/package/addon_form.html", {"addon": addon})


@login_required
def admin_addon_delete(request, id):
    addon = get_object_or_404(AddOn, id=id)
    addon_name = addon.name
    addon.delete()
    log_action(request.user, f"Deleted add-on: '{addon_name}'.")
    messages.success(request, "Add-on deleted successfully!")
    return redirect("admin_package_list")


@login_required
def admin_additional_create(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST":
        features = request.POST.get("features", "").strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render(request, "admin/package/additional_form.html")

        try:
            price = Decimal(request.POST.get("price", ""))
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(request, "admin/package/additional_form.html")

        MAX_PRICE = Decimal("99999999.99")
        if price < 0 or price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(request, "admin/package/additional_form.html")

        additional = AdditionalOnly.objects.create(
            name=request.POST.get("name"),
            image=request.FILES.get("image"),
            price=price,
            features=features,
            notes=request.POST.get("notes"),
        )

        log_action(request.user, f"Created new additional item: '{additional.name}'.")
        messages.success(request, "Additional created successfully!")
        return redirect("admin_package_list")

    return render(request, "admin/package/additional_form.html")


@login_required
def admin_additional_edit(request, id):
    additional = get_object_or_404(AdditionalOnly, id=id)

    if request.method == "POST":
        features = request.POST.get("features", "").strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render(
                request,
                "admin/package/additional_form.html",
                {"additional": additional},
            )

        try:
            additional.price = Decimal(request.POST.get("price", ""))
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(
                request,
                "admin/package/additional_form.html",
                {"additional": additional},
            )

        MAX_PRICE = Decimal("99999999.99")
        if additional.price < 0 or additional.price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(
                request,
                "admin/package/additional_form.html",
                {"additional": additional},
            )

        additional.name = request.POST.get("name")
        additional.features = features
        additional.notes = request.POST.get("notes")

        if request.FILES.get("image"):
            additional.image = request.FILES.get("image")

        additional.save()

        log_action(request.user, f"Edited additional item: '{additional.name}'.")
        messages.success(request, "Additional updated successfully!")
        return redirect("admin_package_list")

    return render(
        request, "admin/package/additional_form.html", {"additional": additional}
    )


@login_required
def admin_additional_detail(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    additional = get_object_or_404(AdditionalOnly, id=id)

    return render(
        request, "admin/package/additional_detail.html", {"additional": additional}
    )


# -----------------------------
# 13️⃣ Service Page Admin
# -----------------------------

@login_required
def admin_additional_delete(request, id):
    additional = get_object_or_404(AdditionalOnly, id=id)
    additional_name = additional.name
    additional.delete()
    log_action(request.user, f"Deleted additional item: '{additional_name}'.")
    messages.success(request, "Additional deleted successfully!")
    return redirect("admin_package_list")


@login_required
def admin_service_content(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    content = ServiceContent.objects.first()
    if content is None:
        content = ServiceContent.objects.create(
            hero_label="Balloorina Services",
            hero_title="Our Services",
            hero_subtitle="Balloon styling and event decoration services for all types of events."
        )

    # Siguraduhing may laman ang CMS fields at Services table
    # (kapareho ng defaults na ipinapakita ng client services page).
    _seed_service_defaults(content)

    if request.method == "POST":
        content.hero_label = request.POST.get("hero_label", content.hero_label).strip()
        content.hero_title = request.POST.get("hero_title", content.hero_title).strip()
        content.hero_subtitle = request.POST.get("hero_subtitle", content.hero_subtitle).strip()
        content.save()
        
        log_action(request.user, "Updated Service page content.")
        messages.success(request, "Service content updated successfully.")
        return redirect("admin_service_content")

    services = Service.objects.all()
    return render(
        request,
        "admin/content/service_content.html",
        {
            "content": content,
            "services": services,
        },
    )


@login_required
def admin_service_item_create(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        is_active = request.POST.get("is_active") == "on"

        display_order = parse_non_negative_int(request.POST.get("display_order", 0), 0)

        if not title:
            messages.error(request, "Title is required.")
            return render(
                request,
                "admin/content/service_item_form.html",
                {
                    "action": "Create",
                    "feature": {},
                    "post_data": request.POST,
                },
            )

        service = Service.objects.create(
            title=title,
            description=description,
            features=request.POST.get("features", "").strip(),
            best_for=request.POST.get("best_for", "").strip(),
            display_order=display_order,
            is_active=is_active,
        )
        
        if request.FILES.get("image"):
            service.image = request.FILES["image"]
            service.save()

        log_action(request.user, f"Created service item '{title}'.")
        messages.success(request, "Service item created successfully.")
        return redirect("admin_service_content")

    return render(request, "admin/content/service_item_form.html", {"action": "Create", "feature": {}, "post_data": {}})


@login_required
def admin_service_item_edit(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    service = get_object_or_404(Service, id=id)

    if request.method == "POST":
        service.title = request.POST.get("title", service.title).strip()
        service.description = request.POST.get("description", service.description).strip()
        service.features = request.POST.get("features", "").strip()
        service.best_for = request.POST.get("best_for", "").strip()
        service.is_active = request.POST.get("is_active") == "on"

        service.display_order = parse_non_negative_int(
            request.POST.get("display_order", service.display_order),
            service.display_order,
        )
        remove_image = request.POST.get("remove_image") == "1"
        if remove_image and service.image:
            service.image.delete(save=False)
            service.image = None

        if request.FILES.get("image"):
            service.image = request.FILES["image"]

        service.save()
        log_action(request.user, f"Updated service item '{service.title}' (ID #{service.id}).")

        messages.success(request, "Service item updated successfully.")
        return redirect("admin_service_content")

    return render(
        request,
        "admin/content/service_item_form.html",
        {
            "action": "Edit",
            "feature": service,
            "post_data": {},
        },
    )


# =========================
# ADMIN REPORTS
# =========================

@login_required
def admin_service_item_delete(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    service = get_object_or_404(Service, id=id)
    service_title = service.title
    service.delete()
    log_action(request.user, f"Deleted service item '{service_title}' (ID #{id}).")
    messages.success(request, "Service item deleted successfully.")
    return redirect("admin_service_content")


def _get_reporting_date_range(request):
    filter_preset = request.GET.get("filter_preset")
    today = timezone.now().date()
    
    if filter_preset == "today":
        start_date = today
        end_date = today
    elif filter_preset == "7days":
        start_date = today - timedelta(days=6)
        end_date = today
    elif filter_preset == "month":
        start_date = today.replace(day=1)
        _, last_day = monthrange(today.year, today.month)
        end_date = today.replace(day=last_day)
    elif filter_preset == "all":
        start_date = datetime(2000, 1, 1).date()
        end_date = today
    else:
        start_date_str = request.GET.get("start_date")
        end_date_str = request.GET.get("end_date")

        if not start_date_str or not end_date_str:
            end_date = today
            start_date = end_date - timedelta(days=30)
        else:
            try:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            except ValueError:
                end_date = today
                start_date = end_date - timedelta(days=30)

    if not start_date or not end_date:
        end_date = today
        start_date = end_date - timedelta(days=30)

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    return start_date, end_date


def _status_distribution_from_queryset(filtered_bookings):
    status_colors_map = {
        "completed": "#10b981",
        "confirmed": "#3b82f6",
        "pending": "#f59e0b",
        "pending_payment": "#fbbf24",
        "cancelled": "#ef4444",
        "expired": "#9ca3af",
    }
    status_dist_qs = (
        filtered_bookings.values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    )
    status_distribution = []
    for item in status_dist_qs:
        status_raw = item["status"]
        status_distribution.append(
            {
                "status": status_raw,
                "label": status_raw.title(),
                "count": item["count"],
                "color": status_colors_map.get(status_raw.lower(), "#6b7280"),
            }
        )
    return status_distribution


def _get_trend_bucket_mode(date_range_days):
    if date_range_days <= 31:
        return "day"
    if date_range_days <= 180:
        return "week"
    return "month"


def _build_trend_spans_and_labels(start_date, end_date, bucket_mode):
    spans = []
    labels = []
    cursor = start_date

    while cursor <= end_date:
        if bucket_mode == "day":
            bucket_end = cursor
            label = cursor.strftime("%b %d")
        elif bucket_mode == "week":
            bucket_end = min(cursor + timedelta(days=6), end_date)
            label = f"{cursor.strftime('%b %d')} - {bucket_end.strftime('%b %d')}"
        else:
            month_end_day = monthrange(cursor.year, cursor.month)[1]
            natural_month_end = datetime(
                cursor.year, cursor.month, month_end_day
            ).date()
            bucket_end = min(natural_month_end, end_date)
            if cursor.day == 1 and bucket_end.day == month_end_day:
                label = cursor.strftime("%b %Y")
            else:
                label = f"{cursor.strftime('%b %d')} - {bucket_end.strftime('%b %d')}"

        spans.append((bucket_end - cursor).days + 1)
        labels.append(label)
        cursor = bucket_end + timedelta(days=1)

    return spans, labels


def _aggregate_trend_series(bookings_qs, range_start, bucket_spans):
    bucket_index_by_day = {}
    cursor = range_start
    for idx, span_days in enumerate(bucket_spans):
        for _ in range(span_days):
            bucket_index_by_day[cursor] = idx
            cursor += timedelta(days=1)

    bookings_series = [0] * len(bucket_spans)
    revenue_series = [0.0] * len(bucket_spans)

    for event_date, booking_total, status in bookings_qs.values_list(
        "event_date", "total_price", "status"
    ):
        bucket_idx = bucket_index_by_day.get(event_date)
        if bucket_idx is None:
            continue
        bookings_series[bucket_idx] += 1
        if status == "completed":
            revenue_series[bucket_idx] += float(booking_total or 0)

    return bookings_series, revenue_series


def build_dashboard_context(request):
    _cleanup_legacy_booking_request_states()
    start_date, end_date = _get_reporting_date_range(request)
    date_range_days = (end_date - start_date).days + 1

    event_type_options = list(
        Booking.objects.exclude(event_type__isnull=True)
        .exclude(event_type__exact="")
        .values_list("event_type", flat=True)
        .distinct()
        .order_by("event_type")
    )
    # Ensure event_type is not an empty string or invalid
    selected_event_type = (request.GET.get("event_type") or "all").strip()
    if not selected_event_type or (selected_event_type != "all" and selected_event_type not in event_type_options):
        selected_event_type = "all"

    filtered_bookings = Booking.objects.filter(
        event_date__gte=start_date, event_date__lte=end_date
    )
    if selected_event_type != "all":
        filtered_bookings = filtered_bookings.filter(event_type=selected_event_type)

    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=max(date_range_days - 1, 0))
    previous_period_bookings = Booking.objects.filter(
        event_date__gte=previous_start, event_date__lte=previous_end
    )
    if selected_event_type != "all":
        previous_period_bookings = previous_period_bookings.filter(
            event_type=selected_event_type
        )

    status_distribution = _status_distribution_from_queryset(filtered_bookings)
    today = timezone.localdate()

    pending_approvals = filtered_bookings.filter(status="pending").count()
    action_queue_total = pending_approvals

    upcoming_deadline_bookings_qs = Booking.objects.filter(
        status="pending",
        event_date__gte=today,
        event_date__lte=today + timedelta(days=3),
    )
    if selected_event_type != "all":
        upcoming_deadline_bookings_qs = upcoming_deadline_bookings_qs.filter(event_type=selected_event_type)
    
    upcoming_deadline_bookings = list(
        upcoming_deadline_bookings_qs
        .select_related("user")
        .order_by("event_date")[:6]
    )
    for booking in upcoming_deadline_bookings:
        booking.days_left = (booking.event_date - today).days

    total_revenue = (
        filtered_bookings.filter(status="completed").aggregate(
            rev=Coalesce(Sum("total_price"), Value(Decimal("0.00"), output_field=DecimalField()))
        )["rev"]
    ) or Decimal("0.00")
    total_bookings = filtered_bookings.count()
    completed_count = filtered_bookings.filter(status="completed").count()
    cancelled_count = filtered_bookings.filter(status="cancelled").count()
    pending_count = filtered_bookings.filter(status="pending").count()
    confirmed_count = filtered_bookings.filter(status="confirmed").count()

    avg_booking_value = (
        filtered_bookings.filter(status="completed").aggregate(
            avg_val=Coalesce(Avg("total_price"), Value(Decimal("0.00"), output_field=DecimalField()))
        )["avg_val"]
    ) or Decimal("0.00")
    completion_rate = (
        round((completed_count / total_bookings) * 100, 1) if total_bookings else 0
    )
    cancellation_rate = (
        round((cancelled_count / total_bookings) * 100, 1) if total_bookings else 0
    )

    prev_period_bookings = previous_period_bookings.count()
    period_delta = total_bookings - prev_period_bookings
    period_delta_pct = (
        round((period_delta / prev_period_bookings) * 100, 1)
        if prev_period_bookings > 0
        else (100.0 if total_bookings > 0 else 0.0)
    )
    prev_completed_revenue = (
        previous_period_bookings.filter(status="completed").aggregate(
            rev=Coalesce(Sum("total_price"), Value(Decimal("0.00"), output_field=DecimalField()))
        )["rev"]
    ) or Decimal("0.00")
    revenue_delta = total_revenue - prev_completed_revenue
    revenue_delta_pct = (
        round((revenue_delta / prev_completed_revenue) * 100, 1)
        if prev_completed_revenue
        else (100.0 if total_revenue > 0 else 0.0)
    )

    revenue_by_event = list(
        filtered_bookings.filter(status="completed")
        .values("event_type")
        .annotate(
            count=Count("id"),
            revenue=Coalesce(Sum("total_price"), Value(Decimal("0.00"), output_field=DecimalField())),
            avg_value=Coalesce(Avg("total_price"), Value(Decimal("0.00"), output_field=DecimalField()))
        )
        .order_by("-revenue")
    )
    top_event_label = "No completed bookings yet"
    top_event_revenue = 0
    if revenue_by_event:
        top_event_label = revenue_by_event[0]["event_type"]
        top_event_revenue = revenue_by_event[0]["revenue"] or 0

    package_counts = {}
    completed_with_packages = filtered_bookings.filter(status="completed").values_list(
        "package_type", flat=True
    )
    for package_type in completed_with_packages:
        if not package_type:
            continue
        first_part = str(package_type).split("+")[0].strip()
        if first_part:
            package_counts[first_part] = package_counts.get(first_part, 0) + 1
    top_package_name = "No package data"
    top_package_count = 0
    if package_counts:
        top_package_name, top_package_count = max(
            package_counts.items(), key=lambda item: item[1]
        )

    package_rows = []
    package_revenue = {}
    completed_with_package_revenue = filtered_bookings.filter(
        status="completed"
    ).values_list("package_type", "total_price")
    for package_type, booking_total in completed_with_package_revenue:
        if not package_type:
            continue
        package_name = str(package_type).split("+")[0].strip()
        if not package_name:
            continue
        package_revenue[package_name] = package_revenue.get(
            package_name, Decimal("0.00")
        ) + (booking_total or Decimal("0.00"))

    for package_name, count in sorted(
        package_counts.items(), key=lambda item: item[1], reverse=True
    )[:8]:
        package_rows.append(
            {
                "package_name": package_name,
                "count": count,
                "revenue": package_revenue.get(package_name, Decimal("0.00")),
            }
        )

    # Top customers ranked by revenue from COMPLETED bookings only so this
    # table stays consistent with total_revenue and revenue_by_event.
    top_customers = list(
        filtered_bookings.filter(status="completed")
        .values("user__first_name", "user__last_name", "user__username", "user__email")
        .annotate(
            booking_count=Count("id"),
            total_spent=Coalesce(Sum("total_price"), Value(Decimal("0.00"), output_field=DecimalField()))
        )
        .order_by("-total_spent", "-booking_count")[:8]
    )
    for customer in top_customers:
        customer['name'] = f"{customer['user__first_name']} {customer['user__last_name']}".strip() or customer['user__username']

    status_table = [
        {
            "label": item["label"],
            "count": item["count"],
            "color": item["color"],
            "share_pct": round((item["count"] / total_bookings) * 100, 1)
            if total_bookings
            else 0,
        }
        for item in status_distribution
    ]

    recent_audit_logs = AuditLog.objects.select_related("user").order_by("-created_at")[
        :6
    ]
    recent_bookings = filtered_bookings.select_related("user").order_by("-created_at")[
        :15
    ]

    trend_bucket_mode = _get_trend_bucket_mode(date_range_days)
    trend_bucket_spans, chart_labels = _build_trend_spans_and_labels(
        start_date, end_date, trend_bucket_mode
    )
    bookings_trend, revenue_trend = _aggregate_trend_series(
        filtered_bookings, start_date, trend_bucket_spans
    )

    prev_bookings_trend, prev_revenue_trend = _aggregate_trend_series(
        previous_period_bookings,
        previous_start,
        trend_bucket_spans,
    )

    trend_title_map = {
        "day": "Daily Trend",
        "week": "Weekly Trend",
        "month": "Monthly Trend",
    }
    trend_bucket_label_map = {
        "day": "Daily buckets",
        "week": "Weekly buckets",
        "month": "Monthly buckets",
    }

    queue_breakdown = {
        "labels": ["Pending Approvals"],
        "values": [pending_approvals],
        "colors": ["#f59e0b"],
    }

    # Busiest days of the week
    busiest_days_data = (
        filtered_bookings.exclude(event_date__isnull=True)
        .values("event_date__week_day")
        .annotate(count=Count("id"))
        .order_by("event_date__week_day")
    )
    
    # Map Django's week_day (1=Sunday, 7=Saturday) to labels
    day_map = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
    busiest_days_labels = [day_map.get(item["event_date__week_day"], "Unknown") for item in busiest_days_data]
    busiest_days_values = [item["count"] for item in busiest_days_data]

    # Customer Retention (Returning vs New)
    # Define returning as someone who has more than 1 booking ever
    all_time_customer_counts = (
        Booking.objects.values("user")
        .annotate(count=Count("id"))
    )
    returning_user_ids = [item["user"] for item in all_time_customer_counts if item["count"] > 1 and item["user"] is not None]
    
    new_customers_count = filtered_bookings.exclude(user_id__in=returning_user_ids).values("user").distinct().count()
    returning_customers_count = filtered_bookings.filter(user_id__in=returning_user_ids).values("user").distinct().count()
    
    total_customers = new_customers_count + returning_customers_count
    new_customers_pct = round((new_customers_count / total_customers * 100), 1) if total_customers > 0 else 0
    returning_customers_pct = round((returning_customers_count / total_customers * 100), 1) if total_customers > 0 else 0

    # Peak Season Heatmap: bookings per month, current year vs previous year
    today_for_heat = timezone.localdate()
    heatmap_current_year = today_for_heat.year
    heatmap_prev_year = heatmap_current_year - 1
    heatmap_months = []
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    all_heatmap_bookings = Booking.objects.exclude(event_date__isnull=True)
    heatmap_current_counts = {
        item["event_date__month"]: item["count"]
        for item in all_heatmap_bookings.filter(
            event_date__year=heatmap_current_year
        ).values("event_date__month").annotate(count=Count("id"))
    }
    heatmap_prev_counts = {
        item["event_date__month"]: item["count"]
        for item in all_heatmap_bookings.filter(
            event_date__year=heatmap_prev_year
        ).values("event_date__month").annotate(count=Count("id"))
    }
    max_heatmap_count = 0
    for m in range(1, 13):
        cur = heatmap_current_counts.get(m, 0)
        prev = heatmap_prev_counts.get(m, 0)
        max_heatmap_count = max(max_heatmap_count, cur, prev)
        heatmap_months.append(
            {
                "label": month_names[m - 1],
                "current": cur,
                "prev": prev,
            }
        )

    # Conversion: registered customers vs customers with at least one booking
    registered_customers = User.objects.filter(role="customer").count()
    booked_customer_ids = set(
        Booking.objects.values_list("user_id", flat=True).distinct()
    )
    booked_customers = (
        User.objects.filter(role="customer", id__in=booked_customer_ids).count()
    )
    conversion_rate_pct = (
        round((booked_customers / registered_customers * 100), 1)
        if registered_customers > 0
        else 0
    )

    return {
        "filter_preset": request.GET.get("filter_preset", ""),
        "start_date": start_date,
        "end_date": end_date,
        "selected_event_type": selected_event_type,
        "event_type_options": event_type_options,
        "active_users": User.objects.filter(role="customer", is_active=True).count(),
        "pending_approvals": pending_approvals,
        "action_queue_total": action_queue_total,
        "upcoming_deadline_bookings": upcoming_deadline_bookings,
        "period_delta": period_delta,
        "period_delta_pct": period_delta_pct,
        "total_revenue": total_revenue,
        "avg_booking_value": avg_booking_value,
        "completion_rate": completion_rate,
        "cancellation_rate": cancellation_rate,
        "completed_count": completed_count,
        "cancelled_count": cancelled_count,
        "pending_bookings": pending_count,
        "confirmed_bookings": confirmed_count,
        "completed_bookings": completed_count,
        "cancelled_bookings": cancelled_count,
        "avg_booking_price": avg_booking_value,
        "total_bookings": total_bookings,
        "revenue_delta": revenue_delta,
        "revenue_delta_pct": revenue_delta_pct,
        "top_event_label": top_event_label,
        "top_event_revenue": top_event_revenue,
        "top_package_name": top_package_name,
        "top_package_count": top_package_count,
        "top_customers": top_customers,
        "status_table": status_table,
        "package_rows": package_rows,
        "revenue_by_event": revenue_by_event,
        "date_range_days": date_range_days,
        "recent_audit_logs": recent_audit_logs,
        "recent_bookings": recent_bookings,
        "trend_title": trend_title_map.get(trend_bucket_mode, "Trend"),
        "trend_bucket_label": trend_bucket_label_map.get(
            trend_bucket_mode, "Trend buckets"
        ),
        "dashboard_trend_labels": chart_labels,
        "dashboard_bookings_trend": bookings_trend,
        "dashboard_revenue_trend": revenue_trend,
        "dashboard_prev_bookings_trend": prev_bookings_trend,
        "dashboard_prev_revenue_trend": prev_revenue_trend,
        "queue_breakdown": queue_breakdown,
        "dashboard_status_labels": [item["label"] for item in status_distribution],
        "dashboard_status_values": [item["count"] for item in status_distribution],
        "dashboard_status_colors": [item["color"] for item in status_distribution],
        "dashboard_busiest_days_labels": busiest_days_labels,
        "dashboard_busiest_days_values": busiest_days_values,
        "new_customers_count": new_customers_count,
        "returning_customers_count": returning_customers_count,
        "new_customers_pct": new_customers_pct,
        "returning_customers_pct": returning_customers_pct,
        "heatmap_months": heatmap_months,
        "heatmap_current_year": heatmap_current_year,
        "heatmap_prev_year": heatmap_prev_year,
        "max_heatmap_count": max_heatmap_count,
        "registered_customers": registered_customers,
        "booked_customers": booked_customers,
        "conversion_rate_pct": conversion_rate_pct,
    }


def build_concerns_context(request):
    start_date, end_date = _get_reporting_date_range(request)
    concern_base_qs = (
        ConcernTicket.objects.select_related("user")
        .filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
        .order_by("-created_at")
    )

    status_filter = (request.GET.get("concern_status") or "").strip()
    valid_statuses = {choice[0] for choice in ConcernTicket.STATUS_CHOICES}
    if status_filter and status_filter in valid_statuses:
        concern_filtered_qs = concern_base_qs.filter(status=status_filter)
    else:
        status_filter = ""
        concern_filtered_qs = concern_base_qs

    recent_admin_notifications = (
        AdminNotification.objects.select_related("user", "booking")
        .filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
        .order_by("-created_at")[:20]
    )

    concern_count = concern_base_qs.count()
    new_count = concern_base_qs.filter(status="new").count()
    in_progress_count = concern_base_qs.filter(status="in_progress").count()
    resolved_count = concern_base_qs.filter(status="resolved").count()

    concerns_paginator = Paginator(concern_filtered_qs, 8)
    concerns_page = concerns_paginator.get_page(request.GET.get("page"))

    return {
        "filter_preset": request.GET.get("filter_preset", ""),
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "date_range_days": (end_date - start_date).days + 1,
        "concern_rows": concerns_page,
        "concerns_page": concerns_page,
        "concern_status_filter": status_filter,
        "concern_records_count": concern_filtered_qs.count(),
        "total_concerns": concern_count,
        "new_concerns": new_count,
        "in_progress_concerns": in_progress_count,
        "resolved_concerns": resolved_count,
        "admin_notifications": recent_admin_notifications,
    }


@login_required
@login_required
@require_POST
def admin_concern_update(request, id):
    if request.user.role != "admin":
        return HttpResponseForbidden("Admins only")

    ticket = get_object_or_404(ConcernTicket, id=id)
    next_url = request.POST.get("next") or reverse("admin_concerns")

    raw_status = (request.POST.get("status") or "").strip()
    valid_statuses = {choice[0] for choice in ConcernTicket.STATUS_CHOICES}
    if raw_status not in valid_statuses:
        messages.error(request, "Invalid concern status selected.")
        return redirect(next_url)

    ticket.status = raw_status
    ticket.admin_notes = (request.POST.get("admin_notes") or "").strip()
    ticket.save(update_fields=["status", "admin_notes", "updated_at"])

    log_action(
        request.user,
        f"Updated concern #{ticket.id} to '{ticket.get_status_display()}'.",
    )
    messages.success(
        request, f"Concern #{ticket.id} updated to {ticket.get_status_display()}."
    )
    return redirect(next_url)


@login_required
def admin_gallery(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    categories = GalleryCategory.objects.all()
    selected_image_category = request.GET.get("image_category", "all")
    gallery_images = GalleryImage.objects.select_related("category").all()

    if selected_image_category != "all":
        try:
            category_id = int(selected_image_category)
            gallery_images = gallery_images.filter(category_id=category_id)
        except (TypeError, ValueError):
            selected_image_category = "all"

    paginator = Paginator(gallery_images, 5)
    page_number = request.GET.get("page")
    gallery_images = paginator.get_page(page_number)

    return render(
        request,
        "admin/gallery/admin_gallery.html",
        {
            "categories": categories,
            "gallery_images": gallery_images,
            "selected_image_category": selected_image_category,
        },
    )


@login_required
def admin_gallery_category_create(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        order = request.POST.get("order", 0)
        if not name:
            messages.error(request, "Category name is required.")
            return render(request, "admin/gallery/gallery_category_form.html")
        GalleryCategory.objects.create(name=name, order=parse_non_negative_int(order, 0))
        log_action(request.user, f"Created gallery category '{name}'.")
        messages.success(request, "Category created successfully.")
        return redirect("admin_gallery")
    return render(request, "admin/gallery/gallery_category_form.html")


@login_required
def admin_gallery_category_edit(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    category = get_object_or_404(GalleryCategory, id=id)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        order = request.POST.get("order", 0)
        if not name:
            messages.error(request, "Category name is required.")
            return render(
                request,
                "admin/gallery/gallery_category_form.html",
                {"category": category},
            )
        category.name = name
        category.order = parse_non_negative_int(order, 0)
        category.save()
        log_action(request.user, f"Updated gallery category '{name}'.")
        messages.success(request, "Category updated successfully.")
        return redirect("admin_gallery")
    return render(
        request, "admin/gallery/gallery_category_form.html", {"category": category}
    )


@login_required
def admin_gallery_category_delete(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    category = get_object_or_404(GalleryCategory, id=id)
    cat_name = category.name
    category.delete()
    log_action(request.user, f"Deleted gallery category '{cat_name}'.")
    messages.success(request, "Category deleted successfully.")
    return redirect("admin_gallery")


@login_required
def admin_gallery_image_create(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    categories = GalleryCategory.objects.all()
    if request.method == "POST":
        category_id = request.POST.get("category")
        caption = request.POST.get("caption", "").strip()
        image = request.FILES.get("image")
        if not category_id or not image:
            messages.error(request, "Category and image are required.")
            return render(
                request,
                "admin/gallery/gallery_image_form.html",
                {"categories": categories},
            )
        category = get_object_or_404(GalleryCategory, id=category_id)
        GalleryImage.objects.create(category=category, image=image, caption=caption)
        log_action(request.user, f"Added gallery image to '{category.name}'.")
        messages.success(request, "Image added successfully.")
        return redirect("admin_gallery")
    return render(
        request, "admin/gallery/gallery_image_form.html", {"categories": categories}
    )


@login_required
def admin_gallery_image_edit(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    gallery_image = get_object_or_404(GalleryImage, id=id)
    categories = GalleryCategory.objects.all()
    next_url = request.GET.get("next") or request.POST.get("next") or ""
    scroll_target = (
        request.GET.get("scroll_target") or request.POST.get("scroll_target") or ""
    )
    if request.method == "POST":
        category_id = request.POST.get("category")
        caption = request.POST.get("caption", "").strip()
        new_image = request.FILES.get("image")
        is_active = request.POST.get("is_active") == "on"
        if not category_id:
            messages.error(request, "Category is required.")
            return render(
                request,
                "admin/gallery/gallery_image_form.html",
                {
                    "gallery_image": gallery_image,
                    "categories": categories,
                    "next_url": next_url,
                    "scroll_target": scroll_target,
                },
            )
        gallery_image.category = get_object_or_404(GalleryCategory, id=category_id)
        gallery_image.caption = caption
        gallery_image.is_active = is_active
        if new_image:
            gallery_image.image = new_image
        gallery_image.save()
        log_action(request.user, f"Updated gallery image #{gallery_image.id}.")
        messages.success(request, "Image updated successfully.")
        if next_url.startswith("/"):
            if scroll_target:
                separator = "&" if "?" in next_url else "?"
                return redirect(f"{next_url}{separator}scroll={scroll_target}")
            return redirect(next_url)
        return redirect("admin_gallery")
    return render(
        request,
        "admin/gallery/gallery_image_form.html",
        {
            "gallery_image": gallery_image,
            "categories": categories,
            "next_url": next_url,
            "scroll_target": scroll_target,
        },
    )


@login_required
def admin_gallery_image_detail(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    gallery_image = get_object_or_404(
        GalleryImage.objects.select_related("category"), id=id
    )
    next_url = (
        request.GET.get("next") or "/staff/gallery/?scroll=gallery-images-section"
    )
    scroll_target = request.GET.get("scroll_target") or "gallery-images-section"
    if not str(next_url).startswith("/"):
        next_url = "/staff/gallery/?scroll=gallery-images-section"
    if scroll_target and "scroll=" not in next_url:
        separator = "&" if "?" in next_url else "?"
        next_url = f"{next_url}{separator}scroll={scroll_target}"

    return render(
        request,
        "admin/gallery/gallery_image_detail.html",
        {
            "gallery_image": gallery_image,
            "next_url": next_url,
        },
    )


# =========================================
# ADMIN CANVAS ASSET MANAGEMENT
# =========================================

@login_required
def admin_gallery_image_delete(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    gallery_image = get_object_or_404(GalleryImage, id=id)
    img_id = gallery_image.id
    gallery_image.image.delete()  # Delete file from storage
    gallery_image.delete()
    log_action(request.user, f"Deleted gallery image #{img_id}.")
    messages.success(request, "Image deleted successfully.")
    return redirect("admin_gallery")


@login_required
def admin_service_list(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    services = Service.objects.order_by("display_order")
    return render(
        request, "admin/service/admin_service_list.html", {"services": services}
    )


@login_required
def admin_service_create(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        features = request.POST.get("features", "").strip()
        is_active = request.POST.get("is_active") == "on"
        image = request.FILES.get("image")

        display_order = parse_non_negative_int(request.POST.get("display_order", 0), 0)

        if not title or not description:
            messages.error(request, "Title and description are required.")
            return render(
                request,
                "admin/service/admin_service_form.html",
                {
                    "action": "Create",
                    "post_data": request.POST,
                },
            )

        service = Service(
            title=title,
            description=description,
            features=features,
            display_order=display_order,
            is_active=is_active,
        )
        if image:
            service.image = image
        service.save()

        log_action(
            request.user, f"Created service '{service.title}' (ID #{service.id})."
        )
        messages.success(request, f"Service '{service.title}' created successfully.")
        return redirect("admin_service_list")

    return render(
        request, "admin/service/admin_service_form.html", {"action": "Create"}
    )


@login_required
def admin_service_edit(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    service = get_object_or_404(Service, id=id)

    if request.method == "POST":
        service.title = request.POST.get("title", service.title).strip()
        service.description = request.POST.get(
            "description", service.description
        ).strip()
        service.features = request.POST.get("features", service.features).strip()
        service.is_active = request.POST.get("is_active") == "on"

        service.display_order = parse_non_negative_int(
            request.POST.get("display_order", service.display_order),
            service.display_order,
        )

        if request.FILES.get("image"):
            service.image = request.FILES["image"]

        service.save()
        log_action(
            request.user, f"Updated service '{service.title}' (ID #{service.id})."
        )
        messages.success(request, f"Service '{service.title}' updated successfully.")
        return redirect("admin_service_list")

    return render(
        request,
        "admin/service/admin_service_form.html",
        {
            "action": "Edit",
            "service": service,
        },
    )


@login_required
def admin_service_detail(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    service = get_object_or_404(Service, id=id)
    return render(
        request, "admin/service/admin_service_detail.html", {"service": service}
    )


# =============================================================================
# ADMIN HOME CONTENT MANAGEMENT
# =============================================================================

@login_required
def admin_service_delete(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    service = get_object_or_404(Service, id=id)
    service_title = service.title
    service.delete()
    log_action(request.user, f"Deleted service '{service_title}' (ID #{id}).")
    messages.success(request, f"Service '{service_title}' deleted successfully.")
    return redirect("admin_service_list")


def _seed_home_defaults(content):
    """Prefill HomeContent fields with the same defaults the client home page
    falls back to, and seed the default feature cards / How It Works steps /
    FAQs so the admin tables (and the client page) show real data.

    Only fills BLANK fields and EMPTY tables, so admin-entered content is
    never overwritten."""
    defaults = {
        "hero_label": "Balloon Styling & Event Design",
        "hero_title": "Turning Moments Into Elegant Celebrations.",
        "hero_subheadline": "Balloon styling tailored to your space, theme, and budget, set up before your celebration begins.",
        "stat_events_styled": "500",
        "stat_rating": "5",
        "stat_satisfaction": "100",
        "stat_response_time": "24",
        "why_choose_title": "Why Choose Balloorina.ph?",
        "why_choose_subtitle": "We style events based on your theme, budget, and venue. Our goal is simple: make your celebration look beautiful and feel special.",
        "occasion_chips": "Birthdays, Weddings, Corporate Events, Christenings, Graduation",
        "how_it_works_label": "How It Works",
        "how_it_works_title": "Start Planning Your Event in",
        "how_it_works_title_accent": "4 Simple Steps",
        "faq_title": "Frequently Asked Questions",
        "faq_subtitle": "Quick answers to the questions we get asked the most. Can't find yours? Send us a message!",
        "cta_title": "Ready to Make Your Celebration Unforgettable?",
        "cta_subtitle": "Let's bring your dream setup to life. Book your event today and leave the styling to us.",
    }

    updated = False
    for field, value in defaults.items():
        if not getattr(content, field).strip():
            setattr(content, field, value)
            updated = True
    if updated:
        content.save()


    if not HomeFeatureItem.objects.exists():
        HomeFeatureItem.objects.bulk_create(
            [
                HomeFeatureItem(
                    home_content=content,
                    title="Premium Materials",
                    description="We use high quality balloons and materials from trusted suppliers for clean and lasting setups.",
                    icon_class="fas fa-gem",
                    display_order=1,
                ),
                HomeFeatureItem(
                    home_content=content,
                    title="Professional Styling",
                    description="Expert creative team that transforms your vision into stunning balloon installations.",
                    icon_class="fas fa-palette",
                    display_order=2,
                ),
                HomeFeatureItem(
                    home_content=content,
                    title="On-Time Setup",
                    description="We arrive early, set up on schedule, and handle the details so you can enjoy the event.",
                    icon_class="fas fa-clock",
                    display_order=3,
                ),
                HomeFeatureItem(
                    home_content=content,
                    title="My Designs",
                    description="Bespoke designs tailored to your color palette, theme, and venue aesthetics.",
                    icon_class="fas fa-wand-magic-sparkles",
                    display_order=4,
                ),
                HomeFeatureItem(
                    home_content=content,
                    title="Full Consultation",
                    description="We guide you from planning to setup so the final design matches what you want.",
                    icon_class="fas fa-comments",
                    display_order=5,
                ),
                HomeFeatureItem(
                    home_content=content,
                    title="Eco-Friendly",
                    description="We use biodegradable balloons and responsible practices whenever possible.",
                    icon_class="fas fa-leaf",
                    display_order=6,
                ),
            ]
        )

    if not HomeHowItWorksStep.objects.exists():
        HomeHowItWorksStep.objects.bulk_create(
            [
                HomeHowItWorksStep(
                    home_content=content,
                    title="Choose a Package",
                    description="Browse our ready-made balloon styling packages and pick the one that fits your celebration.",
                    icon_class="fas fa-box",
                    display_order=1,
                ),
                HomeHowItWorksStep(
                    home_content=content,
                    title="Customize Your Design",
                    description="Personalize colors, themes, and styles using our design canvas to match your vision.",
                    icon_class="fas fa-palette",
                    display_order=2,
                ),
                HomeHowItWorksStep(
                    home_content=content,
                    title="Book & Pay via GCash",
                    description="Secure your date with an easy and safe online downpayment through GCash.",
                    icon_class="fas fa-mobile-alt",
                    display_order=3,
                ),
                HomeHowItWorksStep(
                    home_content=content,
                    title="We Set Up On Your Day",
                    description="Our team arrives early and handles everything so your celebration is stress-free.",
                    icon_class="fas fa-calendar-alt",
                    display_order=4,
                ),
            ]
        )



    if not HomeFaqItem.objects.exists():
        HomeFaqItem.objects.bulk_create(
            [
                HomeFaqItem(
                    home_content=content,
                    question="How far in advance should I book?",
                    answer="We recommend booking at least 2-4 weeks ahead, especially for weekends and holidays. Rush bookings may still be accommodated depending on schedule.",
                    display_order=1,
                ),
                HomeFaqItem(
                    home_content=content,
                    question="What areas do you serve?",
                    answer="We primarily serve Metro Manila and nearby areas. For events outside our usual coverage, just send us a message and we'll see how we can help.",
                    display_order=2,
                ),
                HomeFaqItem(
                    home_content=content,
                    question="How does the GCash downpayment work?",
                    answer="After booking, you'll receive GCash payment details. A downpayment secures your date, and the balance is settled before or on your event day.",
                    display_order=3,
                ),
                HomeFaqItem(
                    home_content=content,
                    question="Can I customize an existing package?",
                    answer="Yes! You can add addons, adjust colors and themes, and use our design canvas to visualize your setup before confirming your booking.",
                    display_order=4,
                ),
                HomeFaqItem(
                    home_content=content,
                    question="What happens if it rains or the venue changes?",
                    answer="Let us know as early as possible and we'll work with you on rescheduling or adjusting the setup to fit your new venue or indoor alternatives.",
                    display_order=5,
                ),
                HomeFaqItem(
                    home_content=content,
                    question="What is your cancellation policy?",
                    answer="Cancellations made at least 7 days before the event are eligible for a refund of the downpayment minus processing fees. Check our Terms & Conditions for full details.",
                    display_order=6,
                ),
            ]
        )


_ABOUT_DEFAULTS = {
    "hero_label": "About Balloorina.ph",
    "hero_title": "Celebrating Moments, | The Balloorina Way",
    "hero_subtitle": "We create clean and elegant event setups through professional balloon styling.",
    "story_label": "OUR STORY",
    "story_title": "From Passion to Premium",
    "story_paragraph_1": "Balloorina.ph empowers people to celebrate life's biggest moments through premium, custom balloon styling. What started in 2020 as a small home studio has grown into a trusted team serving clients across Metro Manila.",
    "story_paragraph_2": "From birthdays and weddings to corporate launches, every arch, centerpiece, and installation is crafted to look stunning in person and in photos.",
    "story_points": "Professional balloon styling for all events\nFast and reliable setup team\nCustom designs for birthdays, weddings, and corporate events\nAffordable packages without compromising quality",
    "story_stat_number": "1,000+",
    "story_stat_text": "People trust Balloorina.ph.",
    "values_title": "More Than Just Balloons.",
    "values_subtitle": "Every celebration we style carries the heart, hustle, and high standards we're known for.",
    "journey_title": "The Story Behind Balloorina.ph",
    "journey_subtitle": "Discover the journey behind Balloorina.ph and our mission to make every celebration memorable.",
}


def _seed_about_defaults(content):
    """Prefill AboutContent fields with the same defaults the client about page
    falls back to, and seed the default Core Value cards so the admin table
    (and the client page) show real data.

    Only fills BLANK fields and EMPTY tables, so admin-entered content is
    never overwritten."""
    updated = False
    for field, value in _ABOUT_DEFAULTS.items():
        if not (getattr(content, field) or "").strip():
            setattr(content, field, value)
            updated = True
    if updated:
        content.save()

    if not AboutValueItem.objects.exists():
        AboutValueItem.objects.bulk_create(
            [
                AboutValueItem(
                    about_content=content,
                    title="Excellence",
                    description="We keep high standards in materials, styling, and setup quality.",
                    icon_class="fas fa-trophy",
                    display_order=1,
                ),
                AboutValueItem(
                    about_content=content,
                    title="Creativity",
                    description="Every event is a unique canvas. We bring fresh, custom ideas that reflect your personal style.",
                    icon_class="fas fa-palette",
                    display_order=2,
                ),
                AboutValueItem(
                    about_content=content,
                    title="Integrity",
                    description="We provide clear pricing, realistic timelines, and transparent updates.",
                    icon_class="fas fa-shield-alt",
                    display_order=3,
                ),
                AboutValueItem(
                    about_content=content,
                    title="Customer Focus",
                    description="Your celebration is our priority. We listen, understand, and deliver exactly what you envision.",
                    icon_class="fas fa-heart",
                    display_order=4,
                ),
                AboutValueItem(
                    about_content=content,
                    title="Professionalism",
                    description="On time, every time. Reliable service from first consultation to final breakdown.",
                    icon_class="far fa-clock",
                    display_order=5,
                ),
                AboutValueItem(
                    about_content=content,
                    title="Sustainability",
                    description="We use biodegradable materials and responsible styling practices when possible.",
                    icon_class="fas fa-leaf",
                    display_order=6,
                ),
            ]
        )


_SERVICE_DEFAULTS = {
    "hero_label": "Balloorina Event Styling",
    "hero_title": "Crafted for Every Occasion",
    "hero_subtitle": (
        "From intimate birthdays to grand weddings, our balloon styling and "
        "event decoration services bring every celebration to life."
    ),
}


def _seed_service_defaults(content):
    """Prefill ServiceContent fields with the same defaults the client services
    page falls back to, and seed the 3 default services (Birthday / Wedding /
    Corporate) so the admin table and the client page comparison table show
    real data.

    Only fills BLANK fields and an EMPTY table, so admin-entered content is
    never overwritten."""
    updated = False
    for field, value in _SERVICE_DEFAULTS.items():
        if not (getattr(content, field) or "").strip():
            setattr(content, field, value)
            updated = True
    if updated:
        content.save()

    if not Service.objects.exists():
        Service.objects.bulk_create(
            [
                Service(
                    title="Birthday Balloon Styling",
                    description=(
                        "We design birthday setups for kids, teens, and adults — from playful "
                        "pastel wonderlands to bold, themed celebrations. Every detail is "
                        "customized around your theme, color palette, and venue, so whether it "
                        "is an intimate home party or a grand banquet hall, we create a setup "
                        "that feels personal, festive, and picture-perfect from the entrance "
                        "arch down to the cake table."
                    ),
                    features=(
                        "Custom balloon arch at the entrance\n"
                        "Themed table centerpieces and cake table styling\n"
                        "Pastel or bold color palettes to match your theme"
                    ),
                    best_for="Kids parties, birthdays, and milestone celebrations",
                    display_order=1,
                ),
                Service(
                    title="Wedding Balloon Installations",
                    description=(
                        "We style wedding venues with elegant balloon designs that match your "
                        "motif — soft, romantic palettes, organic garlands, and refined "
                        "installs that elevate every corner of your celebration. We also "
                        "coordinate closely with your other suppliers for a smooth, "
                        "stress-free setup from ceremony to reception."
                    ),
                    features=(
                        "Elegant entrance arches and backdrops\n"
                        "Organic garlands and refined installs\n"
                        "Supplier-coordinated, stress-free setup"
                    ),
                    best_for="Weddings, receptions, and proposals",
                    display_order=2,
                ),
                Service(
                    title="Corporate Event Styling",
                    description=(
                        "We provide clean and professional balloon setups for product launches, "
                        "conferences, team events, and company celebrations. From "
                        "brand-aligned color schemes to logo displays and stage styling, we "
                        "make sure your brand stands out while keeping the look polished, "
                        "modern, and corporate-friendly."
                    ),
                    features=(
                        "Brand-aligned color schemes\n"
                        "Logo displays and stage styling\n"
                        "Polished, modern, corporate-friendly look"
                    ),
                    best_for="Product launches, conferences, and company events",
                    display_order=3,
                ),
            ]
        )


@login_required
def admin_home_content(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    content = HomeContent.objects.first()
    if content is None:
        content = HomeContent.objects.create()

    if request.method == "POST":
        content.hero_label = request.POST.get("hero_label", content.hero_label).strip()
        content.hero_title = request.POST.get("hero_title", content.hero_title).strip()
        content.hero_subheadline = request.POST.get(
            "hero_subheadline", content.hero_subheadline
        ).strip()
        content.stat_events_styled = request.POST.get(
            "stat_events_styled", content.stat_events_styled
        ).strip()
        content.stat_rating = request.POST.get(
            "stat_rating", content.stat_rating
        ).strip()
        content.stat_satisfaction = request.POST.get(
            "stat_satisfaction", content.stat_satisfaction
        ).strip()
        content.stat_response_time = request.POST.get(
            "stat_response_time", content.stat_response_time
        ).strip()
        content.why_choose_title = request.POST.get(
            "why_choose_title", content.why_choose_title
        ).strip()
        content.why_choose_subtitle = request.POST.get(
            "why_choose_subtitle", content.why_choose_subtitle
        ).strip()
        content.occasion_chips = request.POST.get(
            "occasion_chips", content.occasion_chips
        ).strip()
        content.how_it_works_label = request.POST.get(
            "how_it_works_label", content.how_it_works_label
        ).strip()
        content.how_it_works_title = request.POST.get(
            "how_it_works_title", content.how_it_works_title
        ).strip()
        content.how_it_works_title_accent = request.POST.get(
            "how_it_works_title_accent", content.how_it_works_title_accent
        ).strip()
        content.faq_title = request.POST.get("faq_title", content.faq_title).strip()
        content.faq_subtitle = request.POST.get(
            "faq_subtitle", content.faq_subtitle
        ).strip()
        content.cta_title = request.POST.get("cta_title", content.cta_title).strip()
        content.cta_subtitle = request.POST.get(
            "cta_subtitle", content.cta_subtitle
        ).strip()

        content.save()
        log_action(request.user, "Updated Home page content.")
        messages.success(request, "Home content updated successfully.")
        return redirect("admin_home_content")

    _seed_home_defaults(content)

    features = HomeFeatureItem.objects.all()
    hiw_steps = HomeHowItWorksStep.objects.all()
    faqs = HomeFaqItem.objects.all()
    return render(
        request,
        "admin/content/home_content.html",
        {
            "content": content,
            "features": features,
            "hiw_steps": hiw_steps,
            "faqs": faqs,
        },
    )


@login_required
def admin_home_feature_create(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    content = HomeContent.objects.first()
    if content is None:
        content = HomeContent.objects.create()

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        icon_class = request.POST.get("icon_class", "fas fa-star").strip()
        is_active = request.POST.get("is_active") == "on"

        display_order = parse_non_negative_int(request.POST.get("display_order", 0), 0)

        if not title:
            if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
                return JsonResponse({"ok": False, "message": "Title is required."}, status=400)
            messages.error(request, "Title is required.")
            return render(
                request,
                "admin/content/home_feature_form.html",
                {
                    "action": "Create",
                    "feature": {},
                    "post_data": request.POST,
                },
            )

        HomeFeatureItem.objects.create(
            home_content=content,
            title=title,
            description=description,
            icon_class=icon_class,
            display_order=display_order,
            is_active=is_active,
        )
        log_action(request.user, f"Created home feature item '{title}'.")
        
        if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
            return JsonResponse({"ok": True, "message": "Feature item created successfully."})
        
        messages.success(request, "Feature item created successfully.")
        return redirect("admin_home_content")

    return render(request, "admin/content/home_feature_form.html", {"action": "Create", "feature": {}, "post_data": {}})


@login_required
def admin_home_feature_edit(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    feature = get_object_or_404(HomeFeatureItem, id=id)

    if request.method == "POST":
        feature.title = request.POST.get("title", feature.title).strip()
        feature.description = request.POST.get(
            "description", feature.description
        ).strip()
        feature.icon_class = request.POST.get("icon_class", feature.icon_class).strip()
        feature.is_active = request.POST.get("is_active") == "on"

        feature.display_order = parse_non_negative_int(
            request.POST.get("display_order", feature.display_order),
            feature.display_order,
        )

        feature.save()
        log_action(
            request.user,
            f"Updated home feature item '{feature.title}' (ID #{feature.id}).",
        )
        
        if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
            return JsonResponse({"ok": True, "message": "Feature item updated successfully."})
        
        messages.success(request, "Feature item updated successfully.")
        return redirect("admin_home_content")

    return render(
        request,
        "admin/content/home_feature_form.html",
        {
            "action": "Edit",
            "feature": feature,
            "post_data": {},
        },
    )


@login_required
def admin_home_feature_delete(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    feature = get_object_or_404(HomeFeatureItem, id=id)
    feature_title = feature.title
    feature.delete()
    log_action(request.user, f"Deleted home feature item '{feature_title}' (ID #{id}).")
    messages.success(request, "Feature item deleted successfully.")
    return redirect("admin_home_content")


@login_required
def admin_hiw_step_create(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    content = HomeContent.objects.first()
    if content is None:
        content = HomeContent.objects.create()

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        icon_class = request.POST.get("icon_class", "fas fa-star").strip()
        is_active = request.POST.get("is_active") == "on"

        display_order = parse_non_negative_int(request.POST.get("display_order", 0), 0)

        if not title:
            if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
                return JsonResponse({"ok": False, "message": "Title is required."}, status=400)
            messages.error(request, "Title is required.")
            return render(
                request,
                "admin/content/home_step_form.html",
                {
                    "action": "Create",
                    "step": {},
                    "post_data": request.POST,
                },
            )

        HomeHowItWorksStep.objects.create(
            home_content=content,
            title=title,
            description=description,
            icon_class=icon_class,
            display_order=display_order,
            is_active=is_active,
        )
        log_action(request.user, f"Created 'How It Works' step '{title}'.")

        if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
            return JsonResponse({"ok": True, "message": "Step created successfully."})

        messages.success(request, "Step created successfully.")
        return redirect("admin_home_content")

    return render(request, "admin/content/home_step_form.html", {"action": "Create", "step": {}, "post_data": {}})


@login_required
def admin_hiw_step_edit(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    step = get_object_or_404(HomeHowItWorksStep, id=id)

    if request.method == "POST":
        step.title = request.POST.get("title", step.title).strip()
        step.description = request.POST.get("description", step.description).strip()
        step.icon_class = request.POST.get("icon_class", step.icon_class).strip()
        step.is_active = request.POST.get("is_active") == "on"

        step.display_order = parse_non_negative_int(
            request.POST.get("display_order", step.display_order),
            step.display_order,
        )

        step.save()
        log_action(
            request.user,
            f"Updated 'How It Works' step '{step.title}' (ID #{step.id}).",
        )

        if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
            return JsonResponse({"ok": True, "message": "Step updated successfully."})

        messages.success(request, "Step updated successfully.")
        return redirect("admin_home_content")

    return render(
        request,
        "admin/content/home_step_form.html",
        {
            "action": "Edit",
            "step": step,
            "post_data": {},
        },
    )


@login_required
def admin_hiw_step_delete(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    step = get_object_or_404(HomeHowItWorksStep, id=id)
    step_title = step.title
    step.delete()
    log_action(request.user, f"Deleted 'How It Works' step '{step_title}' (ID #{id}).")
    messages.success(request, "Step deleted successfully.")
    return redirect("admin_home_content")


@login_required
def admin_faq_create(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    content = HomeContent.objects.first()
    if content is None:
        content = HomeContent.objects.create()

    if request.method == "POST":
        question = request.POST.get("question", "").strip()
        answer = request.POST.get("answer", "").strip()
        is_active = request.POST.get("is_active") == "on"

        display_order = parse_non_negative_int(request.POST.get("display_order", 0), 0)

        if not question:
            if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
                return JsonResponse({"ok": False, "message": "Question is required."}, status=400)
            messages.error(request, "Question is required.")
            return render(
                request,
                "admin/content/home_faq_form.html",
                {
                    "action": "Create",
                    "faq": {},
                    "post_data": request.POST,
                },
            )

        HomeFaqItem.objects.create(
            home_content=content,
            question=question,
            answer=answer,
            display_order=display_order,
            is_active=is_active,
        )
        log_action(request.user, f"Created home FAQ item '{question}'.")

        if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
            return JsonResponse({"ok": True, "message": "FAQ item created successfully."})

        messages.success(request, "FAQ item created successfully.")
        return redirect("admin_home_content")

    return render(request, "admin/content/home_faq_form.html", {"action": "Create", "faq": {}, "post_data": {}})


@login_required
def admin_faq_edit(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    faq = get_object_or_404(HomeFaqItem, id=id)

    if request.method == "POST":
        faq.question = request.POST.get("question", faq.question).strip()
        faq.answer = request.POST.get("answer", faq.answer).strip()
        faq.is_active = request.POST.get("is_active") == "on"

        faq.display_order = parse_non_negative_int(
            request.POST.get("display_order", faq.display_order),
            faq.display_order,
        )

        faq.save()
        log_action(
            request.user,
            f"Updated home FAQ item '{faq.question}' (ID #{faq.id}).",
        )

        if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
            return JsonResponse({"ok": True, "message": "FAQ item updated successfully."})

        messages.success(request, "FAQ item updated successfully.")
        return redirect("admin_home_content")

    return render(
        request,
        "admin/content/home_faq_form.html",
        {
            "action": "Edit",
            "faq": faq,
            "post_data": {},
        },
    )


# =============================================================================
# ADMIN ABOUT CONTENT MANAGEMENT
# =============================================================================

@login_required
def admin_faq_delete(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    faq = get_object_or_404(HomeFaqItem, id=id)
    faq_question = faq.question
    faq.delete()
    log_action(request.user, f"Deleted home FAQ item '{faq_question}' (ID #{id}).")
    messages.success(request, "FAQ item deleted successfully.")
    return redirect("admin_home_content")


@login_required
def admin_about_content(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    content = AboutContent.objects.first()
    if content is None:
        content = AboutContent.objects.create()

    # Siguraduhing may laman ang CMS fields at Core Values table
    # (kapareho ng defaults na ipinapakita ng client about page).
    _seed_about_defaults(content)

    if request.method == "POST":
        content.hero_label = request.POST.get(
            "hero_label", content.hero_label
        ).strip()
        content.hero_title = request.POST.get("hero_title", content.hero_title).strip()
        content.hero_subtitle = request.POST.get(
            "hero_subtitle", content.hero_subtitle
        ).strip()
        content.story_label = request.POST.get(
            "story_label", content.story_label
        ).strip()
        content.story_title = request.POST.get(
            "story_title", content.story_title
        ).strip()
        content.story_paragraph_1 = request.POST.get(
            "story_paragraph_1", content.story_paragraph_1
        ).strip()
        content.story_paragraph_2 = request.POST.get(
            "story_paragraph_2", content.story_paragraph_2
        ).strip()
        content.story_stat_number = request.POST.get(
            "story_stat_number", content.story_stat_number
        ).strip()
        content.story_stat_text = request.POST.get(
            "story_stat_text", content.story_stat_text
        ).strip()
        content.story_points = request.POST.get(
            "story_points", content.story_points
        ).strip()
        content.mission_label = request.POST.get(
            "mission_label", content.mission_label
        ).strip()
        content.mission_title = request.POST.get(
            "mission_title", content.mission_title
        ).strip()
        content.mission_paragraph_1 = request.POST.get(
            "mission_paragraph_1", content.mission_paragraph_1
        ).strip()
        content.mission_paragraph_2 = request.POST.get(
            "mission_paragraph_2", content.mission_paragraph_2
        ).strip()
        content.values_title = request.POST.get(
            "values_title", content.values_title
        ).strip()
        content.values_subtitle = request.POST.get(
            "values_subtitle", content.values_subtitle
        ).strip()
        content.journey_title = request.POST.get(
            "journey_title", content.journey_title
        ).strip()
        content.journey_subtitle = request.POST.get(
            "journey_subtitle", content.journey_subtitle
        ).strip()

        if request.FILES.get("story_image"):
            content.story_image = request.FILES["story_image"]
        if request.FILES.get("mission_image"):
            content.mission_image = request.FILES["mission_image"]

        content.save()
        log_action(request.user, "Updated About page content.")
        messages.success(request, "About content updated successfully.")
        return redirect("admin_about_content")

    values = AboutValueItem.objects.all()
    journey_items = AboutJourneyItem.objects.all()
    return render(
        request,
        "admin/content/about_content.html",
        {
            "content": content,
            "values": values,
            "journey_items": journey_items,
        },
    )


GUIDELINE_PAGE_KEYS = [
    GuidelinePageContent.PAGE_GUIDELINES,
    GuidelinePageContent.PAGE_TERMS,
    GuidelinePageContent.PAGE_PRIVACY,
]

# Public page (URL name) per policy page key — used for links in the
# client email notification when policy content is updated.
POLICY_PAGE_URL_NAMES = {
    GuidelinePageContent.PAGE_GUIDELINES: "guidelines",
    GuidelinePageContent.PAGE_TERMS: "terms_conditions",
    GuidelinePageContent.PAGE_PRIVACY: "data_privacy",
}

POLICY_PAGE_DISPLAY_NAMES = {
    GuidelinePageContent.PAGE_GUIDELINES: "Booking Guidelines",
    GuidelinePageContent.PAGE_TERMS: "Terms & Conditions",
    GuidelinePageContent.PAGE_PRIVACY: "Privacy Policy",
}


def _notify_clients_policy_update(request, changed_keys):
    """Email active clients that the Guidelines/Terms/Privacy pages changed.

    Sends one individual email per client (never exposes other clients'
    addresses). Returns (sent_count, failed_count). Never raises — SMTP
    failures are swallowed so a broken mail connection can never block
    saving policy content.
    """
    recipients = sorted(
        set(
            User.objects.filter(role="customer", is_active=True)
            .exclude(email="")
            .values_list("email", flat=True)
        )
    )
    if not recipients:
        return 0, 0

    lines = [
        "Hello!",
        "",
        "We have recently updated the following pages on Balloorina:",
        "",
    ]
    for key in changed_keys:
        page_url = request.build_absolute_uri(
            reverse(POLICY_PAGE_URL_NAMES[key])
        )
        lines.append(f"  • {POLICY_PAGE_DISPLAY_NAMES[key]}: {page_url}")
    lines.extend(
        [
            "",
            "We encourage you to review the changes so you stay up to date with",
            "our booking guidelines, terms and conditions, and privacy practices.",
            "",
            "If you have any questions, feel free to reach out through our",
            "in-app chat support.",
            "",
            "— Balloorina Team",
        ]
    )

    subject = "Updated Guidelines, Terms & Privacy | Balloorina"
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@balloorina.local")

    sent = 0
    failed = 0
    for email_address in recipients:
        try:
            send_mail(
                subject=subject,
                message="\n".join(lines),
                from_email=from_email,
                recipient_list=[email_address],
                fail_silently=False,
            )
            sent += 1
        except Exception:
            failed += 1
    return sent, failed


@login_required
def admin_guidelines_content(request):
    """Manage Guidelines, Terms & Conditions, and Privacy Policy page content."""
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    pages = []
    for key in GUIDELINE_PAGE_KEYS:
        content, _created = GuidelinePageContent.objects.prefetch_related(
            "items"
        ).get_or_create(page_key=key)
        pages.append(
            {
                "obj": content,
                "items": list(content.items.order_by("display_order", "id")),
            }
        )

    if request.method == "POST":
        changed_keys = []
        for key in GUIDELINE_PAGE_KEYS:
            content = GuidelinePageContent.objects.filter(page_key=key).first()
            if content is None:
                continue

            before_title = content.title
            before_intro = content.intro
            before_label = content.attachment_label
            before_url = content.attachment_url

            content.title = request.POST.get(f"{key}_title", content.title).strip()
            content.intro = request.POST.get(f"{key}_intro", content.intro).strip()
            content.attachment_label = request.POST.get(
                f"{key}_attachment_label", content.attachment_label
            ).strip()
            content.attachment_url = request.POST.get(
                f"{key}_attachment_url", content.attachment_url
            ).strip()

            page_changed = (
                content.title != before_title
                or content.intro != before_intro
                or content.attachment_label != before_label
                or content.attachment_url != before_url
            )

            for item in content.items.all():
                if request.POST.get(f"item_delete_{item.id}"):
                    item.delete()
                    page_changed = True
                    continue

                before_heading = item.heading
                before_body = item.body
                before_order = item.display_order
                before_active = item.is_active

                item.heading = request.POST.get(
                    f"item_heading_{item.id}", item.heading
                ).strip()
                item.body = request.POST.get(f"item_body_{item.id}", item.body).strip()
                item.display_order = parse_non_negative_int(
                    request.POST.get(f"item_order_{item.id}", item.display_order),
                    item.display_order,
                )
                item.is_active = request.POST.get(f"item_active_{item.id}") == "on"

                if (
                    item.heading != before_heading
                    or item.body != before_body
                    or item.display_order != before_order
                    or item.is_active != before_active
                ):
                    page_changed = True
                item.save()

            new_heading = request.POST.get(f"new_heading_{key}", "").strip()
            new_body = request.POST.get(f"new_body_{key}", "").strip()
            if new_heading or new_body:
                new_order = parse_non_negative_int(
                    request.POST.get(f"new_order_{key}", ""),
                    content.items.count() + 1,
                )
                GuidelineItem.objects.create(
                    page_content=content,
                    heading=new_heading,
                    body=new_body,
                    display_order=new_order,
                    is_active=True,
                )
                page_changed = True

            content.save()

            if page_changed:
                changed_keys.append(key)

        log_action(request.user, "Updated Guidelines, Terms & Privacy content.")

        # Optional opt-in: email active clients about this update.
        if request.POST.get("notify_clients") == "on":
            if not changed_keys:
                messages.info(
                    request,
                    "No policy content changed, so no client emails were sent.",
                )
            else:
                sent_count, failed_count = _notify_clients_policy_update(
                    request, changed_keys
                )
                if sent_count:
                    log_action(
                        request.user,
                        f"Emailed a policy update notice to {sent_count} client(s).",
                    )
                    messages.success(
                        request,
                        f"Update notice emailed to {sent_count} client(s).",
                    )
                elif failed_count == 0:
                    messages.warning(
                        request,
                        "No active clients with an email address were found, "
                        "so no update notice was sent.",
                    )
                if failed_count:
                    messages.warning(
                        request,
                        f"{failed_count} email(s) failed to send. "
                        "Please check the email configuration.",
                    )

        messages.success(request, "Policies content updated successfully.")
        return redirect("admin_guidelines_content")

    return render(
        request,
        "admin/content/guidelines_content.html",
        {"pages": pages},
    )


@login_required
def admin_about_value_create(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    content = AboutContent.objects.first()
    if content is None:
        content = AboutContent.objects.create()

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        icon_class = request.POST.get("icon_class", "fas fa-star").strip()
        is_active = request.POST.get("is_active") == "on"

        display_order = parse_non_negative_int(request.POST.get("display_order", 0), 0)

        if not title:
            if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
                return JsonResponse({"ok": False, "message": "Title is required."}, status=400)
            messages.error(request, "Title is required.")
            return render(
                request,
                "admin/content/about_value_form.html",
                {
                    "action": "Create",
                    "post_data": request.POST,
                },
            )

        AboutValueItem.objects.create(
            about_content=content,
            title=title,
            description=description,
            icon_class=icon_class,
            display_order=display_order,
            is_active=is_active,
        )
        log_action(request.user, f"Created about value item '{title}'.")
        
        if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
            return JsonResponse({"ok": True, "message": "Value item created successfully."})
        
        messages.success(request, "Value item created successfully.")
        return redirect("admin_about_content")

    return render(request, "admin/content/about_value_form.html", {"action": "Create"})


@login_required
def admin_about_value_edit(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    value_item = get_object_or_404(AboutValueItem, id=id)

    if request.method == "POST":
        value_item.title = request.POST.get("title", value_item.title).strip()
        value_item.description = request.POST.get(
            "description", value_item.description
        ).strip()
        value_item.icon_class = request.POST.get(
            "icon_class", value_item.icon_class
        ).strip()
        value_item.is_active = request.POST.get("is_active") == "on"

        value_item.display_order = parse_non_negative_int(
            request.POST.get("display_order", value_item.display_order),
            value_item.display_order,
        )

        value_item.save()
        log_action(
            request.user,
            f"Updated about value item '{value_item.title}' (ID #{value_item.id}).",
        )
        
        if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
            return JsonResponse({"ok": True, "message": "Value item updated successfully."})
        
        messages.success(request, "Value item updated successfully.")
        return redirect("admin_about_content")

    return render(
        request,
        "admin/content/about_value_form.html",
        {
            "action": "Edit",
            "value_item": value_item,
        },
    )


@login_required
def admin_about_value_delete(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    value_item = get_object_or_404(AboutValueItem, id=id)
    item_title = value_item.title
    value_item.delete()
    log_action(request.user, f"Deleted about value item '{item_title}' (ID #{id}).")
    messages.success(request, "Value item deleted successfully.")
    return redirect("admin_about_content")


@login_required
def admin_about_journey_create(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    content = AboutContent.objects.first()
    if content is None:
        content = AboutContent.objects.create()

    if request.method == "POST":
        caption = request.POST.get("caption", "").strip()
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        is_active = request.POST.get("is_active") == "on"

        display_order = parse_non_negative_int(request.POST.get("display_order", 0), 0)

        if not title:
            if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
                return JsonResponse({"ok": False, "message": "Title is required."}, status=400)
            messages.error(request, "Title is required.")
            return render(
                request,
                "admin/content/about_journey_form.html",
                {
                    "action": "Create",
                    "post_data": request.POST,
                },
            )

        AboutJourneyItem.objects.create(
            about_content=content,
            caption=caption,
            title=title,
            description=description,
            display_order=display_order,
            is_active=is_active,
        )
        log_action(request.user, f"Created about journey item '{title}'.")
        messages.success(request, "Journey step created successfully.")
        return redirect("admin_about_content")

    return render(request, "admin/content/about_journey_form.html", {"action": "Create"})


@login_required
def admin_about_journey_edit(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    journey_item = get_object_or_404(AboutJourneyItem, id=id)

    if request.method == "POST":
        journey_item.caption = request.POST.get(
            "caption", journey_item.caption
        ).strip()
        journey_item.title = request.POST.get("title", journey_item.title).strip()
        journey_item.description = request.POST.get(
            "description", journey_item.description
        ).strip()
        journey_item.is_active = request.POST.get("is_active") == "on"

        journey_item.display_order = parse_non_negative_int(
            request.POST.get("display_order", journey_item.display_order),
            journey_item.display_order,
        )

        journey_item.save()
        log_action(
            request.user,
            f"Updated about journey item '{journey_item.title}' (ID #{journey_item.id}).",
        )
        messages.success(request, "Journey step updated successfully.")
        return redirect("admin_about_content")

    return render(
        request,
        "admin/content/about_journey_form.html",
        {
            "action": "Edit",
            "journey_item": journey_item,
        },
    )


# =============================================================================
# ADMIN REVIEWS
# =============================================================================

@login_required
def admin_about_journey_delete(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    journey_item = get_object_or_404(AboutJourneyItem, id=id)
    item_title = journey_item.title
    journey_item.delete()
    log_action(request.user, f"Deleted about journey item '{item_title}' (ID #{id}).")
    messages.success(request, "Journey step deleted successfully.")
    return redirect("admin_about_content")


@login_required
def admin_reviews(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    search_query = request.GET.get("search", "").strip()
    rating_filter = request.GET.get("rating", "").strip()
    sort_filter = request.GET.get("sort", "-created_at").strip()

    reviews_qs = Review.objects.select_related("user", "booking").prefetch_related(
        "images"
    )

    if search_query:
        reviews_qs = reviews_qs.filter(
            Q(user__first_name__icontains=search_query)
            | Q(user__last_name__icontains=search_query)
            | Q(user__username__icontains=search_query)
            | Q(comment__icontains=search_query)
        )

    if rating_filter:
        try:
            reviews_qs = reviews_qs.filter(rating=int(rating_filter))
        except (ValueError, TypeError):
            pass

    valid_sorts = ["-created_at", "created_at", "-rating", "rating"]
    if sort_filter not in valid_sorts:
        sort_filter = "-created_at"
    reviews_qs = reviews_qs.order_by(sort_filter)

    total_reviews = Review.objects.count()
    avg_rating_data = Review.objects.aggregate(avg=Avg("rating"))
    avg_rating = round(avg_rating_data["avg"] or 0, 1)
    featured_count = Review.objects.filter(is_testimonial=True).count()

    # Star rating distribution (5★ → 1★)
    rating_distribution = []
    rating_counts_raw = (
        Review.objects.values("rating")
        .annotate(count=Count("id"))
    )
    rating_counts_map = {row["rating"]: row["count"] for row in rating_counts_raw}
    for star in range(5, 0, -1):
        count = rating_counts_map.get(star, 0)
        pct = round((count / total_reviews) * 100, 1) if total_reviews else 0
        rating_distribution.append({"star": star, "count": count, "pct": pct})

    paginator = Paginator(reviews_qs, 10)
    page_number = request.GET.get("page", 1)
    reviews_page = paginator.get_page(page_number)

    return render(
        request,
        "admin/admin_reviews.html",
        {
            "total_reviews": total_reviews,
            "avg_rating": avg_rating,
            "featured_count": featured_count,
            "rating_distribution": rating_distribution,
            "search_query": search_query,
            "rating_filter": rating_filter,
            "sort_filter": sort_filter,
            "reviews": reviews_page,
        },
    )


@login_required
def admin_review_detail(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    review = get_object_or_404(Review.objects.select_related("user", "booking"), id=id)
    try:
        reply = review.reply
    except ReviewReply.DoesNotExist:
        reply = None
    return render(
        request,
        "admin/admin_review_detail.html",
        {"review": review, "reply": reply},
    )


@login_required
@require_POST
def admin_review_reply(request, id):
    """Create or update the official admin reply to a review."""
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    review = get_object_or_404(Review, id=id)
    reply_text = (request.POST.get("reply_text") or "").strip()

    if not reply_text:
        messages.error(request, "Reply text is required.")
        return redirect("admin_review_detail", id=review.id)

    if len(reply_text) > 2000:
        messages.error(request, "Reply is too long (max 2000 characters).")
        return redirect("admin_review_detail", id=review.id)

    try:
        existing_reply = review.reply
    except ReviewReply.DoesNotExist:
        existing_reply = None
    if existing_reply:
        existing_reply.reply_text = reply_text
        existing_reply.admin = request.user
        existing_reply.save()
        log_action(
            request.user,
            f"Updated admin reply to review #{review.id}.",
        )
        messages.success(request, "Reply updated successfully.")
    else:
        ReviewReply.objects.create(
            review=review,
            admin=request.user,
            reply_text=reply_text,
        )
        log_action(
            request.user,
            f"Posted an admin reply to review #{review.id}.",
        )
        messages.success(request, "Reply posted successfully.")

    return redirect("admin_review_detail", id=review.id)


# =============================================================================
# ADMIN CONCERNS
# =============================================================================

@login_required
def admin_review_toggle_testimonial(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    review = get_object_or_404(Review, id=id)
    
    # If enabling testimonial, check if already 4
    if not review.is_testimonial:
        featured_count = Review.objects.filter(is_testimonial=True).count()
        if featured_count >= 4:
            messages.error(request, "You can only select up to 4 reviews as testimonials.")
            return redirect("admin_reviews")
    
    review.is_testimonial = not review.is_testimonial
    review.save()

    status_label = (
        "featured as testimonial"
        if review.is_testimonial
        else "removed from testimonials"
    )
    log_action(request.user, f"Review #{review.id} {status_label}.")
    messages.success(request, f"Review #{review.id} {status_label}.")
    return redirect("admin_reviews")


# =============================================================================
# ADMIN ANALYTICS
# =============================================================================

@login_required
def admin_concerns(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    context = build_concerns_context(request)
    return render(request, "admin/admin_concerns.html", context)


@login_required
def admin_analytics(request):
    if request.user.role != "admin":
        return HttpResponseForbidden("Not allowed")
    return render(request, "admin/admin_analytics.html", build_dashboard_context(request))


@login_required
def admin_analytics_export_excel(request):
    if request.user.role != "admin":
        return HttpResponseForbidden("Not allowed")

    _cleanup_legacy_booking_request_states()
    from openpyxl.styles import Alignment, Font, PatternFill

    start_date, end_date = _get_reporting_date_range(request)
    selected_event_type = (request.GET.get("event_type") or "all").strip()

    bookings = Booking.objects.select_related("user").filter(
        created_at__date__gte=start_date, created_at__date__lte=end_date
    )
    if selected_event_type != "all":
        bookings = bookings.filter(event_type=selected_event_type)
    bookings = bookings.order_by("-created_at")

    payments = Payment.objects.select_related("booking").filter(
        created_at__date__gte=start_date, created_at__date__lte=end_date
    )
    if selected_event_type != "all":
        payments = payments.filter(booking__event_type=selected_event_type)
    payments = payments.order_by("-created_at")

    reviews = Review.objects.select_related("user").filter(
        created_at__date__gte=start_date, created_at__date__lte=end_date
    )
    if selected_event_type != "all":
        reviews = reviews.filter(booking__event_type=selected_event_type)
    reviews = reviews.order_by("-created_at")

    wb = openpyxl.Workbook()

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(
        start_color="4F46E5", end_color="4F46E5", fill_type="solid"
    )
    center_align = Alignment(horizontal="center")

    # ── Sheet 1: Bookings Summary ──────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Bookings Summary"

    booking_headers = [
        "Booking ID",
        "Customer",
        "Event Type",
        "Event Date",
        "Status",
        "Total Price (PHP)",
        "Payment Status",
    ]
    for col_idx, h in enumerate(booking_headers, 1):
        cell = ws1.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align

    for row_idx, booking in enumerate(bookings, 2):
        ws1.cell(row=row_idx, column=1, value=booking.id)
        ws1.cell(
            row=row_idx,
            column=2,
            value=booking.user.get_full_name() or booking.user.username,
        )
        ws1.cell(row=row_idx, column=3, value=booking.event_type or "—")
        ws1.cell(
            row=row_idx,
            column=4,
            value=str(booking.event_date) if booking.event_date else "—",
        )
        ws1.cell(row=row_idx, column=5, value=booking.status)
        ws1.cell(row=row_idx, column=6, value=float(booking.total_price or 0))
        ws1.cell(row=row_idx, column=7, value=booking.payment_status or "—")

    for col in ws1.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws1.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

    # ── Sheet 2: Revenue Data ──────────────────────────────────────────────
    ws2 = wb.create_sheet(title="Revenue Data")

    rev_headers = [
        "Payment ID",
        "Booking ID",
        "Amount (PHP)",
        "Method",
        "Type",
        "Status",
        "Date Submitted",
    ]
    for col_idx, h in enumerate(rev_headers, 1):
        cell = ws2.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align

    for row_idx, pay in enumerate(payments, 2):
        ws2.cell(row=row_idx, column=1, value=pay.id)
        ws2.cell(row=row_idx, column=2, value=pay.booking.id)
        ws2.cell(row=row_idx, column=3, value=float(pay.amount or 0))
        ws2.cell(row=row_idx, column=4, value=pay.get_payment_method_display())
        ws2.cell(row=row_idx, column=5, value=pay.get_payment_type_display())
        ws2.cell(row=row_idx, column=6, value=pay.get_payment_status_display())
        ws2.cell(
            row=row_idx,
            column=7,
            value=pay.created_at.strftime("%Y-%m-%d %H:%M") if pay.created_at else "—",
        )

    for col in ws2.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws2.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

    # ── Sheet 3: Reviews Summary ───────────────────────────────────────────
    ws3 = wb.create_sheet(title="Reviews")

    review_headers = [
        "Review ID",
        "Customer",
        "Rating",
        "Comment",
        "Is Testimonial",
        "Date",
    ]
    for col_idx, h in enumerate(review_headers, 1):
        cell = ws3.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align

    for row_idx, rev in enumerate(reviews, 2):
        ws3.cell(row=row_idx, column=1, value=rev.id)
        ws3.cell(
            row=row_idx, column=2, value=rev.user.get_full_name() or rev.user.username
        )
        ws3.cell(row=row_idx, column=3, value=rev.rating)
        ws3.cell(row=row_idx, column=4, value=rev.comment[:200] if rev.comment else "")
        ws3.cell(row=row_idx, column=5, value="Yes" if rev.is_testimonial else "No")
        ws3.cell(
            row=row_idx,
            column=6,
            value=rev.created_at.strftime("%Y-%m-%d")
            if hasattr(rev, "created_at") and rev.created_at
            else "—",
        )

    for col in ws3.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws3.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"analytics_export_{timezone.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    log_action(request.user, "Exported analytics data to Excel.")
    return response


# =============================================================================
# PAYMENT PAGE (Customer – GCash upload flow)
# =============================================================================

@login_required
def admin_analytics_export_pdf(request):
    if request.user.role != "admin":
        return HttpResponseForbidden("Not allowed")

    _cleanup_legacy_booking_request_states()
    context = build_dashboard_context(request)
    
    # ULTIMATE DATA CLEANER: Force everything to be a safe type for ReportLab
    def to_str(val, default="—"):
        if val is None: return default
        return str(val)

    def to_float_str(val):
        try:
            if val is None: return "0.00"
            return "{:,.2f}".format(float(val))
        except:
            return "0.00"

    def to_int(val):
        try:
            if val is None: return 0
            return int(float(val))
        except:
            return 0

    # Pre-format all top-level stats
    pdf_context = {
        "now": timezone.now().strftime("%B %d, %Y %I:%M %p"),
        "start_date_str": context.get("start_date").strftime("%b %d, %Y") if context.get("start_date") else "All Time",
        "end_date_str": context.get("end_date").strftime("%b %d, %Y") if context.get("end_date") else "Now",
        "selected_event_type": to_str(context.get("selected_event_type"), "all").title(),
        "total_bookings": to_int(context.get("total_bookings")),
        "total_revenue": to_float_str(context.get("total_revenue")),
        "completion_rate": to_float_str(context.get("completion_rate")),
        "cancellation_rate": to_float_str(context.get("cancellation_rate")),
        "avg_booking_value": to_float_str(context.get("avg_booking_value")),
        "active_users": to_int(context.get("active_users")),
        "completed_count": to_int(context.get("completed_count")),
        "cancelled_count": to_int(context.get("cancelled_count")),
        "pending_approvals": to_int(context.get("pending_approvals")),
        "action_queue_total": to_int(context.get("action_queue_total")),
        "new_customers_count": to_int(context.get("new_customers_count")),
        "returning_customers_count": to_int(context.get("returning_customers_count")),
        "new_customers_pct": to_float_str(context.get("new_customers_pct")),
        "returning_customers_pct": to_float_str(context.get("returning_customers_pct")),
    }

    # Pre-format Status Table
    pdf_context["status_table"] = []
    for item in context.get("status_table", []):
        pdf_context["status_table"].append({
            "label": to_str(item.get("label"), "Unknown"),
            "count": to_int(item.get("count")),
            "share_pct": to_float_str(item.get("share_pct"))
        })

    # Pre-format Revenue by Event
    pdf_context["revenue_by_event"] = []
    for item in context.get("revenue_by_event", []):
        pdf_context["revenue_by_event"].append({
            "event_type": to_str(item.get("event_type"), "Other").title(),
            "count": to_int(item.get("count")),
            "revenue": to_float_str(item.get("revenue")),
            "avg_value": to_float_str(item.get("avg_value"))
        })

    # Pre-format Packages
    pdf_context["package_rows"] = []
    for item in context.get("package_rows", []):
        pdf_context["package_rows"].append({
            "package_name": to_str(item.get("package_name"), "Unnamed Package"),
            "count": to_int(item.get("count")),
            "revenue": to_float_str(item.get("revenue"))
        })

    # Pre-format Top Customers
    pdf_context["top_customers"] = []
    for item in context.get("top_customers", []):
        pdf_context["top_customers"].append({
            "name": to_str(item.get("name"), "Guest"),
            "booking_count": to_int(item.get("booking_count") or item.get("count")),
            "total_spent": to_float_str(item.get("total_spent"))
        })

    # Pre-format Deadlines
    pdf_context["upcoming_deadline_bookings"] = []
    for item in context.get("upcoming_deadline_bookings", []):
        display_name = "Unknown"
        if hasattr(item, 'user') and item.user:
            display_name = item.user.get_full_name() or item.user.username or "Unknown"
            
        pdf_context["upcoming_deadline_bookings"].append({
            "event_date_str": item.event_date.strftime("%b %d, %Y") if hasattr(item, 'event_date') and item.event_date else "—",
            "customer_name": display_name,
            "event_type": to_str(getattr(item, 'event_type', ""), "Other").title(),
            "days_left": to_int(getattr(item, 'days_left', 0))
        })

    # Report highlights: short, human-readable interpretation of the figures
    # so the PDF reads like a standard business report.
    summary_notes = []
    if pdf_context["total_bookings"] == 0:
        summary_notes.append(
            "No bookings were recorded within the selected reporting period."
        )
    else:
        summary_notes.append(
            "A total of {t} booking(s) were scheduled within the period "
            "({c} completed, {x} cancelled).".format(
                t=pdf_context["total_bookings"],
                c=pdf_context["completed_count"],
                x=pdf_context["cancelled_count"],
            )
        )
        if pdf_context["completed_count"] > 0:
            summary_notes.append(
                "Completed bookings generated PHP {r} in revenue, with an "
                "average booking value of PHP {a}.".format(
                    r=pdf_context["total_revenue"],
                    a=pdf_context["avg_booking_value"],
                )
            )
        else:
            summary_notes.append(
                "No completed bookings were recorded in this period, so "
                "revenue figures are PHP 0.00. Revenue is computed from "
                "completed bookings only."
            )
        if pdf_context["pending_approvals"] > 0:
            summary_notes.append(
                "{n} booking(s) are awaiting approval as of the report date.".format(
                    n=pdf_context["pending_approvals"]
                )
            )
    pdf_context["summary_notes"] = summary_notes

    html = render_to_string("admin/analytics_pdf_template.html", pdf_context)
    buffer = io.BytesIO()
    
    try:
        pisa_status = pisa.CreatePDF(html, dest=buffer, link_callback=_pdf_link_callback)
    except Exception as e:
        logger.error(f"PDF Generation Error: {str(e)}", exc_info=True)
        return HttpResponse(f"Critical PDF Error: {str(e)}", status=500)

    if pisa_status.err:
        return HttpResponse("Conversion Error. <pre>" + html + "</pre>")

    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="analytics_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
    
    log_action(request.user, "Exported analytics data to PDF.")
    return response
