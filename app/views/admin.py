from ..logistics_settings import LogisticsSettingsForm
from ..site_settings_form import SiteSettingsForm
from ..admin_configuration import render_settings, settings_saved
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from ..home_statistics import get_customers_served, get_home_statistics
from ..package_catalog import ordered_packages
from ..design_admin import configure_design_offer, render_offer_form, store_offer_config
from ..design_limits import DesignSettingsForm
"""Admin: dashboard, content mgmt, users, analytics, gallery, reviews. (split from app/views.py)"""

from .common import *  # noqa: F401,F403
from .common import _cleanup_legacy_booking_request_states, _pdf_link_callback  # noqa: F401


# Booking Step 2 preview images: hanggang 2 bawat package/add-on/additional
PREVIEW_IMAGE_MAX = 2


def _handle_preview_images(request, preview_manager):
    """Tanggalin ang mga id sa remove_preview_ids at magdagdag ng bago (max 2)."""
    remove_raw = request.POST.get("remove_preview_ids", "")
    remove_ids = [v for v in (part.strip() for part in remove_raw.split(",")) if v]
    if remove_ids:
        preview_manager.filter(id__in=remove_ids).delete()

    uploads = request.FILES.getlist("preview_images")
    if not uploads:
        return

    slots = max(PREVIEW_IMAGE_MAX - preview_manager.count(), 0)
    for upload in uploads[:slots]:
        preview_manager.create(image=upload, order=preview_manager.count())

    if len(uploads) > slots:
        messages.warning(
            request,
            f"Only {PREVIEW_IMAGE_MAX} preview images are allowed — some uploads were skipped.",
        )


# Helper to extract End Time from special_requests string

@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def admin_site_settings(request):
    """Central site settings page (admin role only)."""
    if request.user.role != "admin":
        return HttpResponseForbidden("Admins only")

    settings_obj = SiteSettings.load()
    service_charge_config = get_service_charge_config()
    design_settings_form = DesignSettingsForm(instance=settings_obj)
    logistics_settings_form = LogisticsSettingsForm(instance=service_charge_config)

    if request.method == 'POST' and request.POST.get('settings_section') == 'all':
        from django.db import transaction
        site_form = SiteSettingsForm(request.POST, instance=settings_obj)
        design_settings_form = DesignSettingsForm(request.POST, instance=settings_obj)
        logistics_settings_form = LogisticsSettingsForm(request.POST, instance=service_charge_config)
        valid = [form.is_valid() for form in (site_form, design_settings_form, logistics_settings_form)]
        if all(valid):
            with transaction.atomic():
                settings_obj.updated_by = request.user
                settings_obj.save()
                config = logistics_settings_form.save(commit=False)
                config.shop_lat = site_form.cleaned_data['shop_lat']
                config.shop_lng = site_form.cleaned_data['shop_lng']
                config.save()
                log_action(request.user, 'Updated site settings, design allowance, and logistics rates.')
            response = settings_saved(request, settings_obj, 'All site settings saved successfully.')
            if response is not None:
                return response
            messages.success(request, 'All site settings saved successfully.')
            return redirect('admin_site_settings')
        return render_settings(request, {
            'settings': settings_obj, 'shop_origin': (request.POST.get('shop_lat', ''), request.POST.get('shop_lng', '')),
            'site_form': site_form, 'design_settings_form': design_settings_form,
            'logistics_settings_form': logistics_settings_form,
        }, status=400)

    if request.method == 'POST' and request.POST.get('settings_section') == 'logistics':
        logistics_settings_form = LogisticsSettingsForm(request.POST, instance=service_charge_config)
        if logistics_settings_form.is_valid():
            config = logistics_settings_form.save(commit=False)
            config.save(update_fields=[*LogisticsSettingsForm.Meta.fields, 'updated_at'])
            log_action(request.user, f'Updated logistics rates: base {config.amount}, per km {config.per_km_rate}.')
            response = settings_saved(request, settings_obj, 'Logistics settings saved successfully.')
            if response is not None:
                return response
            messages.success(request, 'Logistics settings saved successfully.')
            return redirect(reverse('admin_site_settings') + '#logistics-settings')
        return render_settings(request, {
            'settings': settings_obj, 'shop_origin': get_logistics_origin(service_charge_config),
            'design_settings_form': design_settings_form, 'logistics_settings_form': logistics_settings_form,
        }, status=400)


    if request.method == 'POST' and request.POST.get('settings_section') == 'design':
        design_settings_form = DesignSettingsForm(request.POST, instance=settings_obj)
        if design_settings_form.is_valid():
            settings_obj.max_saved_designs = design_settings_form.cleaned_data['max_saved_designs']
            settings_obj.updated_by = request.user
            settings_obj.save(update_fields=['max_saved_designs', 'updated_by', 'updated_at'])
            log_action(request.user, f'Updated saved design limit to {settings_obj.max_saved_designs} per customer.')
            response = settings_saved(request, settings_obj, 'Design settings saved successfully.')
            if response is not None:
                return response
            messages.success(request, 'Design settings saved successfully.')
            return redirect(reverse('admin_site_settings') + '#design-settings')
        return render_settings(request, {
            'settings': settings_obj, 'shop_origin': get_logistics_origin(service_charge_config),
            'design_settings_form': design_settings_form, 'logistics_settings_form': logistics_settings_form,
        }, status=400)

    if request.method == "POST":
        site_name = (request.POST.get("site_name") or "").strip()[:150]
        contact_email = (request.POST.get("contact_email") or "").strip()[:255]
        contact_phone = (request.POST.get("contact_phone") or "").strip()[:50]
        address = (request.POST.get("address") or "").strip()[:255]
        old_address = settings_obj.address
        posted_shop_lat = request.POST.get("shop_lat")
        posted_shop_lng = request.POST.get("shop_lng")
        if (posted_shop_lat or posted_shop_lng) and not valid_coordinates(posted_shop_lat, posted_shop_lng):
            messages.error(request, "Invalid shop pin. Select the address from suggestions or pin the shop on the map.")
            return redirect("admin_site_settings")
        facebook_link = (request.POST.get("facebook_link") or "").strip()[:200]
        instagram_link = (request.POST.get("instagram_link") or "").strip()[:200]
        admin_emails_raw = (request.POST.get("admin_emails_for_notifications") or "").strip()[:500]
        email_notifications_enabled = request.POST.get("email_notifications_enabled") == "on"

        lead_time_raw = (request.POST.get("booking_lead_time_days") or "0").strip()
        try:
            booking_lead_time_days = max(0, int(lead_time_raw))
        except ValueError:
            booking_lead_time_days = 0  # ⏱️ see overtime policy block below

        # ⏱️ Duration & overtime policy — admin-tunable (min/included/rate/max).
        def _pos_int(raw, fallback, minimum=1):
            try:
                return max(minimum, int(str(raw).strip()))
            except (ValueError, TypeError):
                return fallback

        booking_min_duration_hours = _pos_int(
            request.POST.get("booking_min_duration_hours"), 2
        )
        booking_included_hours = _pos_int(
            request.POST.get("booking_included_hours"), 3
        )
        booking_max_duration_hours = _pos_int(
            request.POST.get("booking_max_duration_hours"), 24
        )
        payment_window = min(720, _pos_int(request.POST.get('booking_payment_window_hours'), settings_obj.booking_payment_window_hours))
        design_lead = min(720, _pos_int(request.POST.get('booking_design_lead_hours'), settings_obj.booking_design_lead_hours))
        change_cutoff = min(720, _pos_int(request.POST.get('booking_change_cutoff_hours'), settings_obj.booking_change_cutoff_hours))
        try:
            booking_overtime_rate = max(
                Decimal("0"),
                Decimal(str(request.POST.get("booking_overtime_rate") or "500").strip()),
            )
        except (InvalidOperation, ValueError, TypeError):
            booking_overtime_rate = Decimal("500")


        if not site_name:
            messages.error(request, "Site name is required.")
        else:
            settings_obj.site_name = site_name
            settings_obj.contact_email = contact_email
            settings_obj.contact_phone = contact_phone
            settings_obj.address = address
            settings_obj.facebook_link = facebook_link
            settings_obj.instagram_link = instagram_link
            settings_obj.booking_lead_time_days = booking_lead_time_days  # ⏱️ + duration policy below
            settings_obj.booking_min_duration_hours = booking_min_duration_hours
            settings_obj.booking_included_hours = booking_included_hours
            settings_obj.booking_max_duration_hours = booking_max_duration_hours
            settings_obj.booking_overtime_rate = booking_overtime_rate
            settings_obj.booking_payment_window_hours = payment_window
            settings_obj.booking_design_lead_hours = design_lead
            settings_obj.booking_change_cutoff_hours = change_cutoff


            settings_obj.admin_emails_for_notifications = ", ".join(
                e for e in (x.strip() for x in admin_emails_raw.split(",")) if e
            )
            settings_obj.email_notifications_enabled = email_notifications_enabled
            settings_obj.updated_by = request.user
            settings_obj.save()
            if "shop_lat" in request.POST or "shop_lng" in request.POST:
                service_charge_config.shop_lat = Decimal(posted_shop_lat) if posted_shop_lat else None
                service_charge_config.shop_lng = Decimal(posted_shop_lng) if posted_shop_lng else None
                service_charge_config.save(update_fields=["shop_lat", "shop_lng", "updated_at"])
            elif address != old_address:
                # An old exact pin must never survive an address-only relocation.
                service_charge_config.shop_lat = service_charge_config.shop_lng = None
                service_charge_config.save(update_fields=["shop_lat", "shop_lng", "updated_at"])

            log_action(request.user, "Updated site settings.")
            messages.success(request, "Site settings saved successfully.")

        return redirect("admin_site_settings")

    return render_settings(
        request,
        {"settings": settings_obj, "shop_origin": get_logistics_origin(service_charge_config), "design_settings_form": design_settings_form, "logistics_settings_form": logistics_settings_form},
    )


# Account management is read-only except for explicit, email-backed access changes.
from .users import (admin_user_list, admin_user_detail, admin_user_toggle_active,
                    admin_user_edit, admin_user_delete, admin_user_reset_password)


@login_required
@require_GET
def admin_audit_log_list(request):
    if request.user.role not in ["admin"]:
        return HttpResponseForbidden("Admins only")

    from ..account_lists import account_page_size
    from django.utils.dateparse import parse_date
    log_list = AuditLog.objects.select_related('user').order_by('-created_at', '-pk')

    # Filters
    search_query = request.GET.get("search", "").strip()[:150]
    role_filter = request.GET.get("role", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    if search_query:
        match = (Q(action__icontains=search_query) | Q(user__username__icontains=search_query)
                 | Q(user__email__icontains=search_query) | Q(user__first_name__icontains=search_query)
                 | Q(user__last_name__icontains=search_query))
        key = re.sub(r'^(?:#?LOG-?|#)', '', search_query, flags=re.I)
        if key.isdecimal() and len(key) < 19:
            match |= Q(pk=int(key))
        log_list = log_list.filter(match)
    if role_filter == 'system':
        log_list = log_list.filter(user__isnull=True)
    elif role_filter in ('admin', 'customer'):
        log_list = log_list.filter(user__role=role_filter)
    else:
        role_filter = ''

    error = ''
    if date_from or date_to:
        try:
            first, last = parse_date(date_from), parse_date(date_to)
        except (ValueError, TypeError):
            first = last = None
        if not first or not last:
            error = 'Choose both a valid start date and end date.'
        elif first > last:
            error = 'The end date must be on or after the start date.'
        else:
            log_list = log_list.filter(created_at__date__range=(first, last))

    per_page = account_page_size(request)
    logs = Paginator(log_list, per_page).get_page(request.GET.get('page'))
    context = {'logs': logs, 'per_page': per_page, 'search_query': search_query,
        'role_filter': role_filter, 'date_from': date_from, 'date_to': date_to,
        'filter_error': error, 'has_filters': bool(search_query or role_filter or date_from or date_to)}
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        response = JsonResponse({'html': render_to_string('admin/audit/_list.html', context, request),
            'page': logs.number, 'per_page': per_page, 'error': error}, status=400 if error else 200)
    else:
        response = render(request, 'admin/audit_log_list.html', context)
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@configure_design_offer('package')
def admin_package_create(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST":
        features = request.POST.get("features", "").strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render_offer_form(request, "admin/package/package_form.html")

        try:
            price = Decimal(request.POST.get("price", ""))
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render_offer_form(request, "admin/package/package_form.html")

        MAX_PRICE = Decimal("99999999.99")
        if price < 0 or price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render_offer_form(request, "admin/package/package_form.html")

        package = Package.objects.create(
            name=request.POST.get("name"),
            description=request.POST.get("description"),
            features=features,
            price=price,
            notes=request.POST.get("notes"),
            is_featured=bool(request.POST.get("is_featured")),
        )

        store_offer_config(request, package, 'package')

        _handle_preview_images(request, package.preview_images)

        log_action(request.user, f"Created new package: '{package.name}'.")
        messages.success(request, "Package created successfully!")
        return redirect("admin_package_list")

    return render_offer_form(request, "admin/package/package_form.html")


@login_required
@configure_design_offer('package')
def admin_package_edit(request, id):
    package = get_object_or_404(Package, id=id)

    if request.method == "POST":
        features = request.POST.get("features", "").strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render_offer_form(
                request, "admin/package/package_form.html", {"package": package}
            )

        try:
            package.price = Decimal(request.POST.get("price", ""))
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render_offer_form(
                request, "admin/package/package_form.html", {"package": package}
            )

        MAX_PRICE = Decimal("99999999.99")
        if package.price < 0 or package.price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render_offer_form(
                request, "admin/package/package_form.html", {"package": package}
            )

        package.name = request.POST.get("name")
        package.description = request.POST.get("description")
        package.features = features
        package.notes = request.POST.get("notes")
        package.is_featured = bool(request.POST.get("is_featured"))

        package.save()
        store_offer_config(request, package, 'package')
        _handle_preview_images(request, package.preview_images)

        log_action(request.user, f"Edited package: '{package.name}'.")
        messages.success(request, "Package updated successfully!")
        return redirect("admin_package_list")

    return render_offer_form(request, "admin/package/package_form.html", {"package": package})


@login_required
def admin_package_list(request):
    from ..catalog_admin import catalog_workspace
    return catalog_workspace(request, 'packages')


@login_required
def admin_service_charge_update(request):
    # Keep the old form URL working while all editing lives in Site Settings.
    if request.user.role != 'admin':
        return HttpResponseForbidden('Admins only')
    if request.method != 'POST':
        return redirect(reverse('admin_site_settings') + '#logistics-settings')
    posted = request.POST.copy()
    posted['settings_section'] = 'logistics'
    posted['amount'] = posted.get('service_charge_amount', '')
    posted['notes'] = posted.get('service_charge_notes', '')
    request.POST = posted
    return admin_site_settings(request)


@login_required
def admin_package_detail(request, id):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    package = get_object_or_404(Package, id=id)

    return render(request, "admin/package/package_detail.html", {"package": package})


@login_required
def admin_package_delete(request, id):
    from ..catalog_admin import legacy_catalog_delete
    return legacy_catalog_delete(request, 'package', id)


def package(request):
    packages = ordered_packages()
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
            "logistics_config": service_charge_config,
        },
    )


from decimal import Decimal, InvalidOperation


@login_required
@configure_design_offer('entrance')
def admin_addon_create(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST":
        features = request.POST.get("features", "").strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render_offer_form(request, "admin/package/addon_form.html")

        solo_raw = request.POST.get("solo_price", "").strip()
        if not solo_raw:
            messages.error(request, "Solo price is required.")
            return render_offer_form(request, "admin/package/addon_form.html")

        try:
            price = Decimal(request.POST.get("price", ""))
            solo_price = Decimal(solo_raw)
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render_offer_form(request, "admin/package/addon_form.html")

        MAX_PRICE = Decimal("99999999.99")
        if price < 0 or price > MAX_PRICE or solo_price < 0 or solo_price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render_offer_form(request, "admin/package/addon_form.html")

        addon = AddOn.objects.create(
            name=request.POST.get("name"),
            price=price,
            solo_price=solo_price,
            features=features,
        )

        store_offer_config(request, addon, 'entrance')

        _handle_preview_images(request, addon.preview_images)

        log_action(request.user, f"Created new add-on: '{addon.name}'.")
        messages.success(request, "Add-on created successfully!")
        return redirect("admin_package_list")

    return render_offer_form(request, "admin/package/addon_form.html")


@login_required
def admin_addon_detail(request, id):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    addon = get_object_or_404(AddOn, id=id)

    return render(request, "admin/package/addon_detail.html", {"addon": addon})


@login_required
@configure_design_offer('entrance')
def admin_addon_edit(request, id):
    addon = get_object_or_404(AddOn, id=id)

    if request.method == "POST":
        features = request.POST.get("features", "").strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render_offer_form(request, "admin/package/addon_form.html", {"addon": addon})

        solo_raw = request.POST.get("solo_price", "").strip()
        if not solo_raw:
            messages.error(request, "Solo price is required.")
            return render_offer_form(request, "admin/package/addon_form.html", {"addon": addon})

        try:
            addon.price = Decimal(request.POST.get("price", ""))
            addon.solo_price = Decimal(solo_raw)
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render_offer_form(request, "admin/package/addon_form.html", {"addon": addon})

        MAX_PRICE = Decimal("99999999.99")
        if (
            addon.price < 0
            or addon.price > MAX_PRICE
            or addon.solo_price < 0
            or addon.solo_price > MAX_PRICE
        ):
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render_offer_form(request, "admin/package/addon_form.html", {"addon": addon})

        addon.name = request.POST.get("name")
        addon.features = features

        addon.save()
        store_offer_config(request, addon, 'entrance')

        _handle_preview_images(request, addon.preview_images)

        log_action(request.user, f"Edited add-on: '{addon.name}'.")
        messages.success(request, "Add-on updated successfully!")
        return redirect("admin_package_list")

    return render_offer_form(request, "admin/package/addon_form.html", {"addon": addon})


@login_required
def admin_addon_delete(request, id):
    from ..catalog_admin import legacy_catalog_delete
    return legacy_catalog_delete(request, 'entrance', id)


@login_required
@configure_design_offer('stand')
def admin_additional_create(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST":
        features = request.POST.get("features", "").strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render_offer_form(request, "admin/package/additional_form.html")

        try:
            price = Decimal(request.POST.get("price", ""))
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render_offer_form(request, "admin/package/additional_form.html")

        MAX_PRICE = Decimal("99999999.99")
        if price < 0 or price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render_offer_form(request, "admin/package/additional_form.html")

        additional = AdditionalOnly.objects.create(
            name=request.POST.get("name"),
            price=price,
            features=features,
            notes=request.POST.get("notes"),
        )

        store_offer_config(request, additional, 'stand')

        _handle_preview_images(request, additional.preview_images)

        log_action(request.user, f"Created new additional item: '{additional.name}'.")
        messages.success(request, "Additional created successfully!")
        return redirect("admin_package_list")

    return render_offer_form(request, "admin/package/additional_form.html")


@login_required
@configure_design_offer('stand')
def admin_additional_edit(request, id):
    additional = get_object_or_404(AdditionalOnly, id=id)

    if request.method == "POST":
        features = request.POST.get("features", "").strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render_offer_form(
                request,
                "admin/package/additional_form.html",
                {"additional": additional},
            )

        try:
            additional.price = Decimal(request.POST.get("price", ""))
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render_offer_form(
                request,
                "admin/package/additional_form.html",
                {"additional": additional},
            )

        MAX_PRICE = Decimal("99999999.99")
        if additional.price < 0 or additional.price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render_offer_form(
                request,
                "admin/package/additional_form.html",
                {"additional": additional},
            )

        additional.name = request.POST.get("name")
        additional.features = features
        additional.notes = request.POST.get("notes")

        additional.save()
        store_offer_config(request, additional, 'stand')

        _handle_preview_images(request, additional.preview_images)

        log_action(request.user, f"Edited additional item: '{additional.name}'.")
        messages.success(request, "Additional updated successfully!")
        return redirect("admin_package_list")

    return render_offer_form(
        request, "admin/package/additional_form.html", {"additional": additional}
    )


@login_required
def admin_additional_detail(request, id):
    if request.user.role != 'admin':
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
    from ..catalog_admin import legacy_catalog_delete
    return legacy_catalog_delete(request, 'stand', id)


@login_required
def admin_service_content(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    if request.method == 'GET':
        from ..content_admin import content_workspace
        return content_workspace(request, 'services')

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
    from ..content_admin import content_action
    return content_action(request, 'services', 'services', 'create', 0)



@login_required
def admin_service_item_edit(request, id):
    from ..content_admin import content_action
    return content_action(request, 'services', 'services', 'edit', id)



# =========================
# ADMIN REPORTS
# =========================

@login_required
def admin_service_item_delete(request, id):
    from ..content_admin import content_action
    return content_action(request, 'services', 'services', 'delete', id)



def _get_reporting_date_range(request):
    filter_preset = request.GET.get("filter_preset")
    today = timezone.localdate()
    
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


def build_dashboard_context(request):
    from ..dashboard_reporting import build_dashboard, dashboard_filters
    return build_dashboard(dashboard_filters(request.GET))


def build_concerns_context(request):
    from ..admin_notifications import concern_counts
    from ..account_lists import account_page_size
    from django.utils.dateparse import parse_date
    counts = concern_counts()
    tickets = ConcernTicket.objects.select_related('user').order_by('-created_at', '-pk')
    status = (request.GET.get('concern_status') or '').strip()
    category = (request.GET.get('category') or '').strip()
    search = (request.GET.get('q') or '').strip()[:150]
    start, end = request.GET.get('start_date', ''), request.GET.get('end_date', '')
    error = ''
    if start or end:
        try:
            first, last = parse_date(start), parse_date(end)
            if not first or not last:
                raise ValueError('Choose both a valid start date and end date.')
            if first > last:
                raise ValueError('The end date must be on or after the start date.')
            tickets = tickets.filter(created_at__date__range=(first, last))
        except (ValueError, TypeError) as exc:
            error = str(exc) or 'Choose a valid date range.'
    if status in dict(ConcernTicket.STATUS_CHOICES):
        tickets = tickets.filter(status=status)
    else:
        status = ''
    if category in dict(ConcernTicket.CATEGORY_CHOICES):
        tickets = tickets.filter(category=category)
    else:
        category = ''
    if search:
        match = Q(subject__icontains=search) | Q(message__icontains=search) | Q(user__email__icontains=search)
        match |= Q(user__username__icontains=search) | Q(user__first_name__icontains=search) | Q(user__last_name__icontains=search)
        key = re.sub(r'^(?:#?CON-?|#)', '', search, flags=re.I)
        if key.isdecimal() and len(key) < 19:
            match |= Q(pk=int(key))
        tickets = tickets.filter(match)
    per_page = account_page_size(request)
    page = Paginator(tickets, per_page).get_page(request.GET.get('page'))
    return {'concern_rows': page, 'concerns_page': page, 'per_page': per_page,
        'concern_status_filter': status, 'category_filter': category, 'search_query': search,
        'start_date': start, 'end_date': end, 'filter_error': error, 'counts': counts,
        'concern_records_count': page.paginator.count, 'total_concerns': counts['total'],
        'new_concerns': counts['new'], 'new_concerns_count': counts['new'], 'in_progress_concerns': counts['in_progress'],
        'resolved_concerns': counts['resolved'], 'has_filters': bool(status or category or search or start or end)}


def _admin_concern_data(ticket):
    return {'id': ticket.pk, 'number': f'#CON-{ticket.pk}', 'subject': ticket.subject,
        'message': ticket.message, 'category': ticket.get_category_display(),
        'status': ticket.status, 'status_label': ticket.get_status_display(),
        'name': ticket.user.get_full_name() or ticket.user.username, 'email': ticket.user.email,
        'created': timezone.localtime(ticket.created_at).strftime('%b %d, %Y · %I:%M %p'),
        'updated': timezone.localtime(ticket.updated_at).strftime('%b %d, %Y · %I:%M %p'),
        'admin_notes': ticket.admin_notes,
        'images': [{'url': image.image.url} for image in ticket.images.all()],
        'update_url': reverse('admin_concern_update', args=[ticket.pk])}


@login_required
@require_GET
def admin_concern_details(request, id):
    if request.user.role != 'admin':
        return HttpResponseForbidden('Not allowed')
    ticket = get_object_or_404(ConcernTicket.objects.select_related('user').prefetch_related('images'), pk=id)
    response = JsonResponse({'ticket': _admin_concern_data(ticket), 'can_update': request.user.role == 'admin'})
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_POST
def admin_concern_update(request, id):
    if request.user.role != "admin":
        return HttpResponseForbidden("Admins only")

    from django.utils.http import url_has_allowed_host_and_scheme
    next_url = request.POST.get("next") or reverse("admin_concerns")
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
        next_url = reverse('admin_concerns')
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def reject(message, status=400):
        if is_ajax:
            return JsonResponse({'success': False, 'message': message}, status=status)
        messages.error(request, message)
        return redirect(next_url)

    raw_status = (request.POST.get("status") or "").strip()
    valid_statuses = {'new', 'in_progress', 'resolved'}
    if raw_status not in valid_statuses:
        return reject('Choose a valid concern status.')
    notes = (request.POST.get('admin_notes') or '').strip()
    if len(notes) > 10000:
        return reject('Keep the customer update within 10,000 characters.')

    with transaction.atomic():
        # Match customer cancellation/account-removal lock order. Do not hold a
        # ticket lock while waiting for its customer's account lock.
        owner_id = get_object_or_404(ConcernTicket.objects.only('user_id'), id=id).user_id
        User.objects.select_for_update().get(pk=owner_id)
        ticket = get_object_or_404(ConcernTicket.objects.select_for_update(), id=id)
        if ticket.status == 'cancelled':
            return reject('This concern was cancelled by the customer and cannot be updated.', 409)
        previous_status = ticket.status
        ticket.status = raw_status
        ticket.admin_notes = notes
        if ticket.processing_started_at is None and (raw_status != 'new' or ticket.admin_notes):
            ticket.processing_started_at = timezone.now()
        ticket.save(update_fields=['status', 'admin_notes', 'processing_started_at', 'updated_at'])
        if previous_status != ticket.status:
            updates = {
                'in_progress': f'Concern #CON-{ticket.id} is now In Progress. Our team is reviewing it.',
                'resolved': f'Concern #CON-{ticket.id} has been resolved. View the update.',
                'new': f'Concern #CON-{ticket.id} status changed to New. View the latest update.',
            }
            Notification.objects.create(user_id=ticket.user_id, concern=ticket, message=updates[ticket.status])
        log_action(request.user, f"Updated concern #{ticket.id} to '{ticket.get_status_display()}'.")
    if is_ajax:
        from ..admin_notifications import concern_counts
        return JsonResponse({'success': True, 'message': 'Concern updated. Changes are visible to the customer.',
            'ticket': _admin_concern_data(ticket), 'counts': concern_counts()})
    messages.success(
        request, f"Concern #{ticket.id} updated to {ticket.get_status_display()}."
    )
    return redirect(next_url)


@login_required
def admin_gallery(request):
    from ..catalog_admin import catalog_workspace
    return catalog_workspace(request, 'gallery')


@login_required
def admin_gallery_category_create(request):
    if request.user.role != 'admin':
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
    if request.user.role != 'admin':
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
    from ..catalog_admin import legacy_catalog_delete
    return legacy_catalog_delete(request, 'gallery-category', id)


GALLERY_CAPTION_MAX_LENGTH = GalleryImage._meta.get_field('caption').max_length


def _render_gallery_image_form(request, categories, gallery_image=None, errors=None,
                               next_url='', scroll_target=''):
    bound = request.method == 'POST'
    return render(request, 'admin/gallery/gallery_image_form.html', {
        'categories': categories,
        'gallery_image': gallery_image,
        'caption_max_length': GALLERY_CAPTION_MAX_LENGTH,
        'caption_value': request.POST.get('caption', '') if bound else (gallery_image.caption if gallery_image else ''),
        'selected_category_id': str(request.POST.get('category', '')) if bound else str(gallery_image.category_id if gallery_image else ''),
        'form_is_active': request.POST.get('is_active') == 'on' if bound else (gallery_image.is_active if gallery_image else True),
        'errors': errors or {},
        'upload_needs_reselect': bound and bool(request.FILES.get('image')) and bool(errors),
        'next_url': next_url,
        'scroll_target': scroll_target,
    })


@login_required
def admin_gallery_image_create(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")
    categories = GalleryCategory.objects.all()
    if request.method == "POST":
        category_id = request.POST.get("category")
        caption = request.POST.get("caption", "").strip()
        image = request.FILES.get("image")
        errors = {}
        if not category_id:
            errors['category'] = 'Category is required.'
        if not image:
            errors['image'] = 'Image is required.'
        if len(caption) > GALLERY_CAPTION_MAX_LENGTH:
            errors['caption'] = f'Use {GALLERY_CAPTION_MAX_LENGTH} characters or fewer for the caption.'
        if errors:
            return _render_gallery_image_form(request, categories, errors=errors)
        category = get_object_or_404(GalleryCategory, id=category_id)
        GalleryImage.objects.create(category=category, image=image, caption=caption)
        log_action(request.user, f"Added gallery image to '{category.name}'.")
        messages.success(request, "Image added successfully.")
        return redirect("admin_gallery")
    return _render_gallery_image_form(request, categories)


@login_required
def admin_gallery_image_edit(request, id):
    if request.user.role != 'admin':
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
        errors = {}
        if not category_id:
            errors['category'] = 'Category is required.'
        if len(caption) > GALLERY_CAPTION_MAX_LENGTH:
            errors['caption'] = f'Use {GALLERY_CAPTION_MAX_LENGTH} characters or fewer for the caption.'
        if errors:
            return _render_gallery_image_form(request, categories, gallery_image,
                errors=errors, next_url=next_url, scroll_target=scroll_target)
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
    return _render_gallery_image_form(request, categories, gallery_image,
        next_url=next_url, scroll_target=scroll_target)


@login_required
def admin_gallery_image_detail(request, id):
    if request.user.role != 'admin':
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
    from ..catalog_admin import legacy_catalog_delete
    return legacy_catalog_delete(request, 'gallery-image', id)


@login_required
def admin_service_list(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")
    services = Service.objects.order_by("display_order")
    return render(
        request, "admin/service/admin_service_list.html", {"services": services}
    )


@login_required
def admin_service_create(request):
    if request.user.role != 'admin':
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
    if request.user.role != 'admin':
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
    if request.user.role != 'admin':
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
    if request.user.role != 'admin':
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
    page falls back to, and seed the 3 default services (Birthday / Baptism /
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
                    title="Baptism & Christening Balloon Styling",
                    description=(
                        "We style baptism and christening celebrations with soft, "
                        "heartfelt balloon designs — gentle pastel palettes, "
                        "elegant backdrops, and tasteful installs that honor your "
                        "little one's special day. From the church entrance to the "
                        "reception, we coordinate closely with your family and "
                        "suppliers for a smooth, stress-free setup."
                    ),
                    features=(
                        "Styled backdrop panels with styrofoam name\n"
                        "Balloons in your chosen color motif\n"
                        "Cake table, celebrant chair, and souvenir rack setup"
                    ),
                    best_for="Baptisms, christenings, and baby celebrations",
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
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    if request.method == 'GET':
        from ..content_admin import content_workspace
        return content_workspace(request, 'home')

    content = HomeContent.objects.first()
    if content is None:
        content = HomeContent.objects.create()

    if request.method == "POST":
        if 'support_hours' in request.POST:
            try:
                support_hours = int(request.POST.get('support_hours', '').strip())
                if not 1 <= support_hours <= 24:
                    raise ValueError
            except (ValueError, TypeError):
                messages.error(request, 'Support hours must be a whole number from 1 to 24 hours per day.')
                return redirect('admin_home_content')
            content.support_hours = support_hours
        content.hero_label = request.POST.get("hero_label", content.hero_label).strip()
        content.hero_title = request.POST.get("hero_title", content.hero_title).strip()
        content.hero_subheadline = request.POST.get(
            "hero_subheadline", content.hero_subheadline
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
            "home_stats": get_home_statistics(),
            "features": features,
            "hiw_steps": hiw_steps,
            "faqs": faqs,
        },
    )


@login_required
def admin_home_feature_create(request):
    from ..content_admin import content_action
    return content_action(request, 'home', 'features', 'create', 0)



@login_required
def admin_home_feature_edit(request, id):
    from ..content_admin import content_action
    return content_action(request, 'home', 'features', 'edit', id)



@login_required
def admin_home_feature_delete(request, id):
    from ..content_admin import content_action
    return content_action(request, 'home', 'features', 'delete', id)



@login_required
def admin_hiw_step_create(request):
    from ..content_admin import content_action
    return content_action(request, 'home', 'steps', 'create', 0)



@login_required
def admin_hiw_step_edit(request, id):
    from ..content_admin import content_action
    return content_action(request, 'home', 'steps', 'edit', id)



@login_required
def admin_hiw_step_delete(request, id):
    from ..content_admin import content_action
    return content_action(request, 'home', 'steps', 'delete', id)



@login_required
def admin_faq_create(request):
    from ..content_admin import content_action
    return content_action(request, 'home', 'faqs', 'create', 0)



@login_required
def admin_faq_edit(request, id):
    from ..content_admin import content_action
    return content_action(request, 'home', 'faqs', 'edit', id)



# =============================================================================
# ADMIN ABOUT CONTENT MANAGEMENT
# =============================================================================

@login_required
def admin_faq_delete(request, id):
    from ..content_admin import content_action
    return content_action(request, 'home', 'faqs', 'delete', id)



@login_required
def admin_about_content(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    if request.method == 'GET':
        from ..content_admin import content_workspace
        return content_workspace(request, 'about')

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
            "customers_served": get_customers_served(),
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
    addresses). Returns (sent_count, failed_count). Never raises — email
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
            accepted = send_mail(
                subject=subject,
                message="\n".join(lines),
                from_email=from_email,
                recipient_list=[email_address],
                fail_silently=False,
            )
            sent += int(accepted == 1)
            failed += int(accepted != 1)
        except Exception:
            failed += 1
            logger.exception("Failed to send policy update email.")
    return sent, failed


@login_required
def admin_guidelines_content(request):
    """Manage Guidelines, Terms & Conditions, and Privacy Policy page content."""
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    if request.method == 'GET':
        from ..content_admin import content_workspace
        return content_workspace(request, 'policies')

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
    from ..content_admin import content_action
    return content_action(request, 'about', 'values', 'create', 0)



@login_required
def admin_about_value_edit(request, id):
    from ..content_admin import content_action
    return content_action(request, 'about', 'values', 'edit', id)



@login_required
def admin_about_value_delete(request, id):
    from ..content_admin import content_action
    return content_action(request, 'about', 'values', 'delete', id)



@login_required
def admin_about_journey_create(request):
    from ..content_admin import content_action
    return content_action(request, 'about', 'journey', 'create', 0)



@login_required
def admin_about_journey_edit(request, id):
    from ..content_admin import content_action
    return content_action(request, 'about', 'journey', 'edit', id)



# =============================================================================
# ADMIN REVIEWS
# =============================================================================

@login_required
def admin_about_journey_delete(request, id):
    from ..content_admin import content_action
    return content_action(request, 'about', 'journey', 'delete', id)



def _review_detail_context(review):
    try:
        reply = review.reply
    except ReviewReply.DoesNotExist:
        reply = None
    return {"review": review, "reply": reply}


def _review_json(request, review, message=""):
    from ..review_management import review_summary
    context = _review_detail_context(review)
    response = JsonResponse({
        "success": True, "id": review.pk, "is_testimonial": review.is_testimonial,
        "message": message,
        "html": render_to_string("admin/reviews/_detail.html", context, request=request),
        "summary_html": render_to_string("admin/reviews/_summary.html", review_summary(), request=request),
    })
    response['Cache-Control'] = 'no-store'
    return response


def _review_action_result(request, review, message, error=False, status=400):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        if error:
            return JsonResponse({'success': False, 'message': message}, status=status)
        return _review_json(request, review, message)
    (messages.error if error else messages.success)(request, message)
    return redirect('admin_review_detail', id=review.pk)


@login_required
@require_GET
def admin_reviews(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")
    from ..review_management import build_review_context
    context = build_review_context(request.GET)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        response = JsonResponse({
            'html': render_to_string('admin/reviews/_queue.html', context, request=request),
            'summary_html': render_to_string('admin/reviews/_summary.html', context, request=request),
            'page': context['reviews'].number,
        })
    else:
        response = render(request, 'admin/admin_reviews.html', context)
    response['Cache-Control'] = 'no-store'
    return response


@login_required
@require_GET
def admin_review_detail(request, id):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")
    review = get_object_or_404(Review.objects.select_related('user', 'booking', 'reply').prefetch_related('images'), pk=id)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return _review_json(request, review)
    from ..review_management import build_review_context
    context = build_review_context(request.GET)
    context.update(_review_detail_context(review))
    context['initial_review_id'] = review.pk
    response = render(request, 'admin/admin_review_detail.html', context)
    response['Cache-Control'] = 'no-store'
    return response


@login_required
@require_POST
def admin_review_reply(request, id):
    """Create or update the official, public response to a review."""
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")
    review = get_object_or_404(Review, pk=id)
    reply_text = (request.POST.get('reply_text') or '').strip()
    if not reply_text:
        return _review_action_result(request, review, 'Reply text is required.', error=True)
    if len(reply_text) > 2000:
        return _review_action_result(request, review, 'Reply is too long (max 2000 characters).', error=True)
    with transaction.atomic():
        review = get_object_or_404(Review.objects.select_for_update(), pk=id)
        _, created = ReviewReply.objects.update_or_create(review=review, defaults={'admin': request.user, 'reply_text': reply_text})
        log_action(request.user, f"{'Posted' if created else 'Updated'} an admin reply to review #{review.pk}.")
    return _review_action_result(request, review, 'Reply posted successfully.' if created else 'Reply updated successfully.')


@login_required
@require_POST
def admin_review_delete_reply(request, id):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")
    with transaction.atomic():
        review = get_object_or_404(Review.objects.select_for_update(), pk=id)
        removed, _ = ReviewReply.objects.filter(review=review).delete()
        if removed:
            log_action(request.user, f'Removed admin reply from review #{review.pk}.')
    return _review_action_result(request, review, 'Reply removed successfully.' if removed else 'No admin reply to remove.')


@login_required
@require_POST
def admin_review_toggle_testimonial(request, id):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")
    from ..review_management import FEATURED_REVIEW_LIMIT
    requested = request.POST.get('is_testimonial')
    if requested not in (None, '0', '1'):
        return JsonResponse({'success': False, 'message': 'Choose a valid testimonial action.'}, status=400)
    with transaction.atomic():
        # All admin feature changes share a lock, including requests from different admins.
        # Lock before counting so simultaneous requests cannot exceed the four slots.
        User.objects.select_for_update(no_key=True).filter(role='admin').order_by('pk').first()
        review = get_object_or_404(Review.objects.select_for_update(), pk=id)
        desired = (not review.is_testimonial) if requested is None else requested == '1'
        if desired and not review.is_testimonial and Review.objects.filter(is_testimonial=True).count() >= FEATURED_REVIEW_LIMIT:
            return _review_action_result(request, review, 'All 4 testimonial slots are in use. Remove a featured review before adding another.', error=True, status=409)
        if desired != review.is_testimonial:
            review.is_testimonial = desired
            review.save(update_fields=['is_testimonial'])
            log_action(request.user, f"Review #{review.pk} {'featured as testimonial' if desired else 'removed from testimonials'}.")
    return _review_action_result(request, review, 'Review featured on Home and About.' if desired else 'Review removed from featured testimonials.')


# =============================================================================
# ADMIN ANALYTICS
# =============================================================================

@login_required
def admin_concerns(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")
    context = build_concerns_context(request)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        response = JsonResponse({'html': render_to_string('admin/concerns/_queue.html', context, request),
            'counts': context['counts'], 'page': context['concerns_page'].number,
            'error': context['filter_error']}, status=400 if context['filter_error'] else 200)
    else:
        response = render(request, 'admin/admin_concerns.html', context)
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_GET
def admin_analytics(request):
    if request.user.role != "admin":
        return HttpResponseForbidden("Not allowed")
    from django.core.exceptions import ValidationError
    from ..analytics_reporting import build_report, resolve_filters
    asynchronous = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    try:
        context = build_report(resolve_filters(request.GET))
    except ValidationError as error:
        message = ' '.join(error.messages)
        if asynchronous:
            response = JsonResponse({'error': message}, status=400)
        else:
            context = build_report(resolve_filters({}))
            context['filter_error'] = message
            response = render(request, 'admin/admin_analytics.html', context, status=400)
    else:
        if asynchronous:
            response = JsonResponse({'html': render_to_string('admin/analytics/_results.html', context, request),
                'filters': context['filters'].params(), 'export_url': context['export_url'], 'excel_url': context['excel_url']})
        else:
            response = render(request, 'admin/admin_analytics.html', context)
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_GET
def admin_analytics_export_excel(request):
    if request.user.role != "admin":
        return HttpResponseForbidden("Not allowed")

    from openpyxl.styles import Alignment, Font, PatternFill
    from django.core.exceptions import ValidationError
    from ..analytics_reporting import build_report, resolve_filters, selected_bookings, REPORT_ZONE
    from ..analytics_insights import selected_collections
    try:
        filters = resolve_filters(request.GET)
    except ValidationError as error:
        return HttpResponse(' '.join(error.messages), status=400)
    cohort = selected_bookings(filters)
    bookings = cohort.select_related('user').order_by('-created_at')
    payments = Payment.objects.select_related('booking').filter(booking__in=cohort,
        payment_status='verified', applied_to_booking=True).order_by('-created_at')
    reviews = Review.objects.select_related('user').filter(booking__in=cohort).order_by('-created_at')

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
        "Submitted (Philippine time)",
        "Selected Setup",
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
        ws1.cell(row=row_idx, column=8, value=timezone.localtime(booking.created_at, REPORT_ZONE).strftime('%Y-%m-%d %H:%M'))
        ws1.cell(row=row_idx, column=9, value=booking.package_type or '')

    for col in ws1.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws1.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

    # ── Sheet 2: Verified collections for the same booking cohort ──────────
    ws2 = wb.create_sheet(title="Verified Collections")

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
            value=timezone.localtime(pay.created_at, REPORT_ZONE).strftime("%Y-%m-%d %H:%M") if pay.created_at else "—",
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
        ws3.cell(row=row_idx, column=4, value=rev.comment or "")
        ws3.cell(row=row_idx, column=5, value="Yes" if rev.is_testimonial else "No")
        ws3.cell(
            row=row_idx,
            column=6,
            value=timezone.localtime(rev.created_at, REPORT_ZONE).strftime("%Y-%m-%d %H:%M")
            if hasattr(rev, "created_at") and rev.created_at
            else "—",
        )

    for col in ws3.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws3.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)

    report = build_report(filters)
    insights = report['insights']
    receipts = wb.create_sheet(title='Collections Received')
    receipts.append(['Payment ID', 'Booking ID', 'Amount (PHP)', 'Method', 'Recorded Date (Philippine time)', 'Date Source'])
    for pay in selected_collections(filters).order_by('report_received_at', 'pk'):
        receipts.append([pay.pk, pay.booking_id, float(pay.amount), pay.get_payment_method_display(),
            timezone.localtime(pay.report_received_at, REPORT_ZONE).strftime('%Y-%m-%d %H:%M'),
            'Receipt / submission' if pay.received_at else 'Verification fallback'])
    facts = wb.create_sheet(title='Business Insights')
    facts.append(['Metric', 'Value'])
    for label, value in [('Remaining balance', insights['remaining_balance']),
            ('Payable booking value', insights['payable_value']), ('Collections received', insights['collections']['value']),
            ('Expired bookings', insights['expired']), ('Expired booking rate (%)', insights['expired_rate']),
            ('First-time customers', insights['customers']['new']), ('Returning customers', insights['customers']['returning']),
            ('Valid reviews', insights['customers']['reviews']), ('Average rating', insights['customers']['average_rating']),
            ('Review coverage (%)', insights['customers']['review_coverage']),
            ('Receipt timestamp missing, verification fallback (period)', insights['collections']['fallback_count']),
            ('No payment timestamp (all dates, same event filter)', insights['collections']['undated_count'])]:
        facts.append([label, float(value) if isinstance(value, Decimal) else value])
    for row in insights['payment_progress']:
        facts.append([row['label']+' bookings', row['count']])
    demand = wb.create_sheet(title='Offer Demand')
    demand.append(['Category', 'Offer', 'Booking selections', 'Completed whole-booking value (overlapping, PHP)'])
    for group in ('packages', 'arches', 'stands'):
        for row in insights['offers'][group]:
            demand.append([group, row['label'], row['count'], float(row['completed_value'])])

    metadata = wb.create_sheet(title='Report Definitions')
    metadata.append(['Definition', 'Value'])
    for row in [('Date basis', filters.basis_label), ('Period', filters.period_label),
            ('Comparison', filters.comparison_label),
            ('Event type', filters.event_type), ('Time zone', 'Asia/Manila'),
            ('Collections', 'Verified payments applied to selected bookings, regardless of payment date; not net of refunds.'),
            ('Collections Received', 'Independent receipt-date period, same event filter. Receipt/submission timestamp, then verification timestamp fallback; undated payments excluded.'),
            ('Payable balances', 'Approved or completed bookings only; pending quotations, cancelled and expired bookings excluded. Credit capped per booking.'),
            ('Returning customers', 'Completed events up to today; customer had a completed event on an earlier event date before this cohort.'),
            ('Offer value', 'Whole completed booking totals containing each offer; overlapping, not item revenue.'),
            ('Booking value', 'Total price is booking value, not proof of a received payment.')]:
        metadata.append(row)
    from ..analytics_exports import add_analytics_sheets, style_workbook
    add_analytics_sheets(wb, report)
    style_workbook(wb)
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"analytics_export_{report['generated_at'].strftime('%Y%m%d_%H%M%S')}.xlsx"
    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response['Cache-Control'] = 'private, no-store'
    log_action(request.user, "Exported analytics data to Excel.")
    return response


# =============================================================================
# PAYMENT PAGE (Customer – GCash upload flow)
# =============================================================================

@login_required
@require_GET
def admin_analytics_export_pdf(request):
    if request.user.role != "admin":
        return HttpResponseForbidden("Not allowed")

    from django.core.exceptions import ValidationError
    from ..analytics_reporting import build_report, resolve_filters
    try:
        report = build_report(resolve_filters(request.GET))
    except ValidationError as error:
        return HttpResponse(' '.join(error.messages), status=400)
    filters = report['filters']
    pdf_context = {
        'now': report['generated_at'].strftime('%B %d, %Y %I:%M %p'),
        'start_date_str': filters.start.strftime('%b %d, %Y'),
        'end_date_str': filters.end.strftime('%b %d, %Y'),
        'date_basis': filters.basis_label,
        'selected_event_type': 'All' if filters.event_type == 'all' else filters.event_type or 'Unspecified event',
        'total_bookings': report['total_bookings'],
        'total_revenue': f"{report['completed_value']:,.2f}",
        'verified_collections': f"{report['verified_collections']:,.2f}",
        'completion_rate': f"{report['completion_rate']:.2f}",
        'cancellation_rate': f"{report['cancellation_rate']:.2f}",
        'avg_booking_value': f"{report['average_completed_value']:,.2f}",
        'active_users': report['customer_count'],
        'completed_count': report['completed_count'],
        'cancelled_count': report['cancelled_count'],
        'status_table': report['statuses'],
        'event_rows': [{**row, 'value': f"{row['value']:,.2f}", 'collections': f"{row['collections']:,.2f}"} for row in report['event_rows']],
        'setup_rows': report['setup_rows'],
        'report_insights': report['insights'],
        'report_filters': filters,
        'comparison_label': filters.comparison_label,
        'report_comparison': report['comparison'],
        'summary_notes': [
            f"{report['total_bookings']} booking{'s' if report['total_bookings'] != 1 else ''} match{'es' if report['total_bookings'] == 1 else ''} this period and event filter: {report['completed_count']} completed and {report['cancelled_count']} cancelled.",
            f"Completed booking value is PHP {report['completed_value']:,.2f}; verified collections credited to these bookings total PHP {report['verified_collections']:,.2f}.",
        ],
    }

    from ..analytics_exports import trend_rows, receipt_rows, comparison_rows
    pdf_context['booking_trend_rows'] = trend_rows(report)
    pdf_context['receipt_trend_rows'] = receipt_rows(report)
    pdf_context['comparison_rows'] = comparison_rows(report)

    html = render_to_string("admin/analytics_pdf_template.html", pdf_context)
    buffer = io.BytesIO()
    
    try:
        pisa_status = pisa.CreatePDF(html, dest=buffer, link_callback=_pdf_link_callback)
    except Exception as e:
        logger.error(f"PDF Generation Error: {str(e)}", exc_info=True)
        return HttpResponse("Unable to generate this report. Please try again.", status=500)

    if pisa_status.err:
        return HttpResponse("Unable to generate this report. Please try again.", status=500)

    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="analytics_report_{report["generated_at"].strftime("%Y%m%d_%H%M%S")}.pdf"'
    
    response["Cache-Control"] = "private, no-store"
    log_action(request.user, "Exported analytics data to PDF.")
    return response
