"""AI design canvas and user design management. (split from app/views.py)"""

from .common import *  # noqa: F401,F403
from django.core.exceptions import RequestDataTooBig
from ..design_admin import configure_canvas_availability, render_canvas_form
from ..models import DesignOffer
from ..design_validation import EvaluationCatalog, design_card_status
from ..design_previews import preview_bytes, preview_version
from ..design_limits import DesignLimitReached, create_saved_design, saved_design_usage
from ..canvas_builtins import STYRO_NAME, BUILTIN_MESSAGE
from ..design_validation import (KINDS, selection_groups, design_offer, offer_is_ready, offer_payload, eligible_assets, asset_payload, evaluate_design, evaluate_saved_design, evaluation_message, restore_catalog_metadata)


@login_required
def select_design_type(request):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    existing_design_id = request.GET.get('design_id', '')
    if existing_design_id:
        get_object_or_404(UserDesign, pk=existing_design_id, user=request.user)
    else:
        usage = saved_design_usage(request.user)
        if usage['at_limit']:
            messages.warning(request, str(DesignLimitReached(usage)))
            return redirect('my_designs')

    # Get active packages to display as options
    active_packages = Package.objects.filter(is_active=True).order_by("price")

    return render(
        request, "client/select_design_type.html", {"packages": active_packages, "design_groups": selection_groups(), "existing_design_id": existing_design_id}
    )


@login_required
def my_designs_page(request):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    # Order by updated_at descending so newest are first
    designs_list = UserDesign.objects.filter(user=request.user).select_related('base_package').order_by("-updated_at")

    # Search by design name (?q=)
    search_query = request.GET.get("q", "").strip()
    if search_query:
        designs_list = designs_list.filter(name__icontains=search_query)

    # Sort (?sort=): newest (default) | oldest | name
    sort_filter = request.GET.get("sort", "newest").strip()
    valid_sorts = {
        "newest": "-updated_at",
        "oldest": "updated_at",
        "name": "name",
    }
    designs_list = designs_list.order_by(valid_sorts.get(sort_filter, "-updated_at"))

    paginator = Paginator(designs_list, 8)  # Show 8 designs per page
    page_number = request.GET.get("page")
    designs = paginator.get_page(page_number)

    catalog = EvaluationCatalog(designs)
    for design in designs:
        design.display_offer = design_offer(design, catalog)
        design.eligibility = evaluate_saved_design(design, catalog)
        design.card_status = design_card_status(design.eligibility)
        if not design.display_offer or not offer_is_ready(design.display_offer, catalog):
            design.card_status = {'message': 'Choose an available starting point in the editor before booking.', 'items': [], 'more': False}
        design.preview_version = preview_version(design.thumbnail.name) if design.thumbnail else ''

    # Get active packages for the "Create New Design" modal
    active_packages = Package.objects.filter(is_active=True).order_by("price")

    # Stats bar (bottom of page) — computed from ALL designs, hindi lang
    # ang nasa current page para tama ang counters
    all_designs = UserDesign.objects.filter(user=request.user)
    month_start = timezone.localtime().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    stats = all_designs.aggregate(total=Count('pk'), month=Count('pk', filter=Q(created_at__gte=month_start)), last=Max('updated_at'))

    return render(
        request,
        "client/my_designs.html",
        {
            "designs": designs,
            "packages": active_packages,
            "design_groups": selection_groups(catalog),
            "search_query": search_query,
            "sort_filter": sort_filter,
            "total_designs": stats['total'],
            "design_usage": saved_design_usage(request.user, total=stats['total']),
            "created_this_month": stats['month'],
            "last_edited": {'updated_at': stats['last']} if stats['last'] else None,
        },
    )


@login_required
@require_GET
def user_design_preview(request, id):
    from django.http import HttpResponseNotModified
    from django.utils.cache import patch_vary_headers
    from PIL import UnidentifiedImageError, Image
    if request.user.role != 'customer':
        return HttpResponseForbidden('Not allowed')
    design = get_object_or_404(UserDesign.objects.only('thumbnail', 'user_id'), pk=id, user=request.user)
    if not design.thumbnail:
        raise Http404('No preview available')
    etag = '"' + preview_version(design.thumbnail.name) + '"'
    if request.headers.get('If-None-Match') == etag:
        response = HttpResponseNotModified()
    else:
        try:
            response = HttpResponse(preview_bytes(design.thumbnail), content_type='image/webp')
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            raise Http404('No preview available')
    response['ETag'] = etag
    response['Cache-Control'] = 'private, max-age=86400'
    response['X-Content-Type-Options'] = 'nosniff'
    patch_vary_headers(response, ['Cookie'])
    return response


@login_required
@require_POST
def save_user_design(request):
    if request.user.role != "customer":
        return JsonResponse({"status": "error", "message": "Not allowed"}, status=403)

    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            return JsonResponse({"status": "error", "message": "Invalid design data."}, status=400)
        design_id = data.get("id")
        name = data.get("name", "Untitled Design")
        canvas_json = data.get("canvas_json")
        if isinstance(canvas_json, dict):
            canvas_json = json.dumps(canvas_json)
        thumbnail_data = data.get("thumbnail")  # Base64 string
        base_package_id = data.get("base_package_id")

        if not canvas_json:
            return JsonResponse(
                {"status": "error", "message": "Canvas data is required"}, status=400
            )

        offer = None
        if data.get("design_offer_id"):
            offer = get_object_or_404(DesignOffer, pk=data["design_offer_id"])
        elif base_package_id:
            offer = DesignOffer.objects.filter(package_id=base_package_id).first()
        elif design_id:
            existing = get_object_or_404(UserDesign, id=design_id, user=request.user)
            offer = design_offer(existing)
        evaluation = evaluate_design(canvas_json, offer)
        if evaluation["invalid_items"] == ["Canvas data is invalid."]:
            return JsonResponse({"status": "error", "message": "Canvas data is invalid."}, status=400)

        # Handle thumbnail image (Base64)
        import base64
        import uuid

        from django.core.files.base import ContentFile

        image_file = None
        if thumbnail_data and "," in thumbnail_data:
            format, imgstr = thumbnail_data.split(";base64,")
            ext = format.split("/")[-1]
            image_file = ContentFile(
                base64.b64decode(imgstr), name=f"{uuid.uuid4().hex}.{ext}"
            )

        if design_id:
            # Update existing
            design = get_object_or_404(UserDesign, id=design_id, user=request.user)
            if name:
                design.name = name
            design.canvas_json = canvas_json
            if offer:
                design.design_offer = offer
                design.base_package = offer.package if offer.kind == "package" else None
            if image_file:
                design.thumbnail = image_file
            
            # Maintain or update base package
            if base_package_id and not offer:
                try:
                    design.base_package = Package.objects.get(id=base_package_id)
                except Package.DoesNotExist:
                    pass
            
            design.save()
            log_action(request.user, f"Updated custom design #{design.id}.")
        else:
            # Create new
            base_package = None
            if base_package_id and not offer:
                try:
                    base_package = Package.objects.get(id=base_package_id)
                except Package.DoesNotExist:
                    pass

            design = create_saved_design(
                user=request.user,
                name=name,
                canvas_json=canvas_json,
                thumbnail=image_file,
                base_package=offer.package if offer and offer.kind == "package" else base_package,
                design_offer=offer,
            )
            log_action(request.user, f"Created new custom design #{design.id}.")

        return JsonResponse(
            {
                "status": "success",
                "id": design.id,
                "message": "Design saved successfully",
                "evaluation": evaluation,
                "can_book": evaluation["can_book"],
            }
        )
    except DesignLimitReached as exc:
        return JsonResponse({'status': 'error', 'code': 'design_limit_reached', 'message': str(exc),
                             'design_usage': exc.usage}, status=409)
    except Http404:
        return JsonResponse({"status": "error", "message": "Design or offer not found."}, status=404)
    except (ValueError, TypeError):
        return JsonResponse({"status": "error", "message": "Invalid design data."}, status=400)
    except RequestDataTooBig:
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "This design exceeds the save size limit. "
                    "Try smaller uploaded images or fewer image copies, then save again."
                ),
            },
            status=413,
        )
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
@require_POST
def rename_user_design(request, id):
    if request.user.role != "customer":
        return JsonResponse({"status": "error", "message": "Not allowed"}, status=403)

    try:
        design = get_object_or_404(UserDesign, id=id, user=request.user)
        data = json.loads(request.body)
        new_name = data.get("name")

        if not new_name or not new_name.strip():
            return JsonResponse(
                {"status": "error", "message": "Name cannot be empty"}, status=400
            )

        design.name = new_name.strip()
        design.save()
        log_action(
            request.user, f"Renamed custom design #{design.id} to '{design.name}'."
        )
        return JsonResponse({"status": "success", "name": design.name})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
@require_POST
def delete_user_design(request, id):
    if request.user.role != "customer":
        return JsonResponse({"status": "error", "message": "Not allowed"}, status=403)

    try:
        design = get_object_or_404(UserDesign, id=id, user=request.user)
        design_id_val = design.id
        design.delete()
        log_action(request.user, f"Deleted custom design #{design_id_val}.")
        return JsonResponse(
            {"status": "success", "message": "Design deleted successfully"}
        )
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


# =========================================
# ADMIN GALLERY MANAGEMENT
# =========================================

@login_required
def design_canvas_page(request):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    context = {}
    design_id = request.GET.get("id")
    offer_id = request.GET.get("design_offer_id")
    offer = None
    design = None
    if design_id:
        design = get_object_or_404(UserDesign, id=design_id, user=request.user)
        context["design"] = design
        offer = design_offer(design)
    else:
        usage = saved_design_usage(request.user)
        if usage['at_limit']:
            messages.warning(request, str(DesignLimitReached(usage)))
            return redirect('my_designs')
    if offer_id:
        offer = get_object_or_404(DesignOffer, pk=offer_id)
        if not offer_is_ready(offer):
            messages.warning(request, "This design offer is temporarily unavailable.")
            return redirect("select_design_type")
    elif not design and request.GET.get("package_id"):
        offer = get_object_or_404(DesignOffer, package_id=request.GET["package_id"])
        if not offer_is_ready(offer):
            messages.warning(request, "This design offer is temporarily unavailable.")
            return redirect("select_design_type")
    elif not design and request.GET.get("custom") != "true":
        return redirect("select_design_type")

    ready_packages = [o for o in DesignOffer.objects.filter(kind="package", is_enabled=True).select_related("package") if offer_is_ready(o)]
    all_quotas = {}
    for candidate in ready_packages:
        all_quotas[candidate.package_id] = {
            r.category.name.lower(): r.maximum if r.maximum is not None else 999
            for r in candidate.requirements.select_related("category")
        }
        if candidate.max_balloon_colors:
            all_quotas[candidate.package_id]["balloon_color_limit"] = candidate.max_balloon_colors
    context.update({
        "base_package": offer, "base_package_id": offer.package_id if offer and offer.kind == "package" else "",
        "design_offer_payload": offer_payload(offer) if offer else None,
        "all_design_offers": {str(o.package_id): offer_payload(o) for o in ready_packages},
        "all_packages": [o.package for o in ready_packages] if not offer or offer.kind == "package" else [],
        "all_packages_data": [{"id": str(o.package_id), "name": o.name, "price": str(o.price)} for o in ready_packages] if not offer or offer.kind == "package" else [],
        "all_package_quotas": json.dumps(all_quotas), "addon_prices": "{}",
        "package_quotas": json.dumps({r.category.name.lower(): r.maximum if r.maximum is not None else 999 for r in offer.requirements.select_related("category")} if offer else {}),
        "saved_canvas_state": restore_catalog_metadata(design.canvas_json, offer) if design else None,
    })
    if offer and offer.max_balloon_colors:
        quotas = json.loads(context["package_quotas"])
        quotas["balloon_color_limit"] = offer.max_balloon_colors
        context["package_quotas"] = json.dumps(quotas)
    assets = list(eligible_assets(offer).select_related("category").order_by("category__order", "sort_order", "id")) if offer else []
    # Load all categories for this type so changing a package can reveal its assets.
    category_ids = {a.category_id for a in assets}
    categories = list(CanvasCategory.objects.filter(pk__in=category_ids).order_by("order", "name"))
    payload = {}
    for category in categories:
        category.design_assets = [a for a in assets if a.category_id == category.pk and a.builtin_key != STYRO_NAME]
        payload[category.name.lower().strip()] = [asset_payload(a) for a in assets if a.category_id == category.pk]
    context["canvas_categories"] = [category for category in categories if category.design_assets]
    context["canvas_assets_payload_obj"] = payload
    context["canvas_assets_payload"] = json.dumps(payload)
    context["styro_asset"] = next((a for a in assets if a.builtin_key == STYRO_NAME), None)

    return render(request, "client/design_canvas.html", context)


@login_required
def admin_canvas_assets(request):
    from ..catalog_admin import catalog_workspace
    return catalog_workspace(request, 'canvas')


@login_required
@configure_canvas_availability(False)
def admin_canvas_category_create(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        order = request.POST.get("order", 1)
        is_active = request.POST.get("is_active") == "on"
        if not name:
            messages.warning(request, "Please enter a category name before saving.")
            return render_canvas_form(request, "admin/canvas/canvas_category_form.html")
        CanvasCategory.objects.create(
            name=name, order=parse_non_negative_int(order, 1), is_active=is_active, is_balloon=request.POST.get("is_balloon") == "on", **request.canvas_availability
        )
        log_action(request.user, f"Created canvas category '{name}'.")
        messages.success(request, "Canvas category created successfully.")
        return redirect("admin_canvas_assets")
    return render_canvas_form(request, "admin/canvas/canvas_category_form.html")


@login_required
@configure_canvas_availability(False)
def admin_canvas_category_edit(request, id):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")
    category = get_object_or_404(CanvasCategory, id=id)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        order = request.POST.get("order", 1)
        is_active = request.POST.get("is_active") == "on"
        if not name:
            messages.warning(request, "Please enter a category name before saving.")
            return render_canvas_form(
                request,
                "admin/canvas/canvas_category_form.html",
                {"category": category},
            )
        category.name = name
        category.order = parse_non_negative_int(order, 1)
        category.is_active = is_active
        for field, value in request.canvas_availability.items():
            setattr(category, field, value)
        if "balloon_category_present" in request.POST:
            category.is_balloon = request.POST.get("is_balloon") == "on"
        category.save()
        log_action(request.user, f"Updated canvas category '{name}'.")
        messages.success(request, "Canvas category updated successfully.")
        return redirect("admin_canvas_assets")
    return render_canvas_form(
        request, "admin/canvas/canvas_category_form.html", {"category": category}
    )


@login_required
def admin_canvas_category_delete(request, id):
    from ..catalog_admin import legacy_catalog_delete
    return legacy_catalog_delete(request, 'canvas-category', id)


@login_required
@configure_canvas_availability(True)
def admin_canvas_asset_create(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    categories = CanvasCategory.objects.order_by("order", "name")
    if request.method == "POST":
        category_id = request.POST.get("category")
        label = request.POST.get("label", "").strip()
        static_path = ""
        item_type = "image"
        image = request.FILES.get("image")
        width = request.POST.get("width", "150")
        height = request.POST.get("height", "150")
        is_active = request.POST.get("is_active") == "on"

        if not category_id:
            messages.warning(request, "Please select a category for this asset.")
            return render_canvas_form(
                request,
                "admin/canvas/canvas_asset_form.html",
                {"categories": categories},
            )

        if not label:
            messages.warning(request, "Please enter an asset name before saving.")
            return render_canvas_form(
                request,
                "admin/canvas/canvas_asset_form.html",
                {"categories": categories},
            )

        if not image:
            messages.warning(request, "Please upload an image file for this asset.")
            return render_canvas_form(
                request,
                "admin/canvas/canvas_asset_form.html",
                {"categories": categories},
            )

        try:
            width_val = int(width)
            height_val = int(height)
        except ValueError:
            messages.warning(
                request, "Default width and height must be valid whole numbers."
            )
            return render_canvas_form(
                request,
                "admin/canvas/canvas_asset_form.html",
                {"categories": categories},
            )

        if width_val < 1:
            messages.warning(request, "Default width must be at least 1.")
            return render_canvas_form(
                request,
                "admin/canvas/canvas_asset_form.html",
                {"categories": categories},
            )

        if height_val < 1:
            messages.warning(request, "Default height must be at least 1.")
            return render_canvas_form(
                request,
                "admin/canvas/canvas_asset_form.html",
                {"categories": categories},
            )

        category = CanvasCategory.objects.filter(id=category_id).first()
        if not category:
            messages.warning(
                request,
                "Selected category could not be found. Please choose another category.",
            )
            return render_canvas_form(
                request,
                "admin/canvas/canvas_asset_form.html",
                {"categories": categories},
            )

        next_sort = (
            CanvasAsset.objects.filter(category=category).aggregate(max_sort=Max("sort_order"))[
                "max_sort"
            ]
            or 0
        ) + 1
        CanvasAsset.objects.create(
            category=category,
            label=label,
            subgroup="",
            static_path=static_path,
            item_type=item_type,
            image=image,
            width=width_val,
            height=height_val,
            sort_order=next_sort,
            is_active=is_active, **request.canvas_availability,
        )
        log_action(request.user, f"Added canvas asset '{label}' to '{category.name}'.")
        messages.success(request, "Canvas asset added successfully.")
        return redirect("admin_canvas_assets")

    return render_canvas_form(
        request,
        "admin/canvas/canvas_asset_form.html",
        {"categories": categories},
    )


@login_required
@configure_canvas_availability(True)
def admin_canvas_asset_edit(request, id):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    canvas_asset = get_object_or_404(CanvasAsset, id=id)
    categories = CanvasCategory.objects.order_by("order", "name")
    next_url = request.GET.get("next") or request.POST.get("next") or ""
    scroll_target = (
        request.GET.get("scroll_target") or request.POST.get("scroll_target") or ""
    )

    if request.method == "POST":
        category_id = request.POST.get("category")
        label = request.POST.get("label", "").strip()
        static_path = canvas_asset.static_path or ""
        item_type = canvas_asset.item_type or "image"
        new_image = request.FILES.get("image")
        width = request.POST.get("width", "150")
        height = request.POST.get("height", "150")
        is_active = request.POST.get("is_active") == "on"

        if not category_id:
            messages.warning(request, "Please select a category for this asset.")
            return render_canvas_form(
                request,
                "admin/canvas/canvas_asset_form.html",
                {
                    "canvas_asset": canvas_asset,
                    "categories": categories,
                    "next_url": next_url,
                    "scroll_target": scroll_target,
                },
            )

        if not label:
            messages.warning(request, "Please enter an asset name before saving.")
            return render_canvas_form(
                request,
                "admin/canvas/canvas_asset_form.html",
                {
                    "canvas_asset": canvas_asset,
                    "categories": categories,
                    "next_url": next_url,
                    "scroll_target": scroll_target,
                },
            )

        if not new_image and not canvas_asset.image and not canvas_asset.static_path and canvas_asset.item_type != 'i-text':
            messages.warning(request, "Please upload an image file for this asset.")
            return render_canvas_form(
                request,
                "admin/canvas/canvas_asset_form.html",
                {
                    "canvas_asset": canvas_asset,
                    "categories": categories,
                    "next_url": next_url,
                    "scroll_target": scroll_target,
                },
            )

        try:
            width_val = int(width)
            height_val = int(height)
        except ValueError:
            messages.warning(
                request, "Default width and height must be valid whole numbers."
            )
            return render_canvas_form(
                request,
                "admin/canvas/canvas_asset_form.html",
                {
                    "canvas_asset": canvas_asset,
                    "categories": categories,
                    "next_url": next_url,
                    "scroll_target": scroll_target,
                },
            )

        if width_val < 1:
            messages.warning(request, "Default width must be at least 1.")
            return render_canvas_form(
                request,
                "admin/canvas/canvas_asset_form.html",
                {
                    "canvas_asset": canvas_asset,
                    "categories": categories,
                    "next_url": next_url,
                    "scroll_target": scroll_target,
                },
            )

        if height_val < 1:
            messages.warning(request, "Default height must be at least 1.")
            return render_canvas_form(
                request,
                "admin/canvas/canvas_asset_form.html",
                {
                    "canvas_asset": canvas_asset,
                    "categories": categories,
                    "next_url": next_url,
                    "scroll_target": scroll_target,
                },
            )

        category = CanvasCategory.objects.filter(id=category_id).first()
        if not category:
            messages.warning(
                request,
                "Selected category could not be found. Please choose another category.",
            )
            return render_canvas_form(
                request,
                "admin/canvas/canvas_asset_form.html",
                {
                    "canvas_asset": canvas_asset,
                    "categories": categories,
                    "next_url": next_url,
                    "scroll_target": scroll_target,
                },
            )

        canvas_asset.category = category
        canvas_asset.label = label
        canvas_asset.subgroup = ""
        canvas_asset.static_path = static_path
        canvas_asset.item_type = item_type
        canvas_asset.width = width_val
        canvas_asset.height = height_val
        canvas_asset.is_active = is_active
        if new_image:
            canvas_asset.image = new_image
        for field, value in request.canvas_availability.items():
            setattr(canvas_asset, field, value)
        canvas_asset.save()

        log_action(request.user, f"Updated canvas asset #{canvas_asset.id}.")
        messages.success(request, "Canvas asset updated successfully.")
        if next_url.startswith("/"):
            if scroll_target:
                separator = "&" if "?" in next_url else "?"
                return redirect(f"{next_url}{separator}scroll={scroll_target}")
            return redirect(next_url)
        return redirect("admin_canvas_assets")

    return render_canvas_form(
        request,
        "admin/canvas/canvas_asset_form.html",
        {
            "canvas_asset": canvas_asset,
            "categories": categories,
            "next_url": next_url,
            "scroll_target": scroll_target,
        },
    )


@login_required
def admin_canvas_asset_detail(request, id):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Not allowed")

    canvas_asset = get_object_or_404(
        CanvasAsset.objects.select_related("category"), id=id
    )
    next_url = (
        request.GET.get("next")
        or "/staff/canvas-assets/?scroll=canvas-assets-list-section"
    )
    scroll_target = request.GET.get("scroll_target") or "canvas-assets-list-section"
    if not str(next_url).startswith("/"):
        next_url = "/staff/canvas-assets/?scroll=canvas-assets-list-section"
    if scroll_target and "scroll=" not in next_url:
        separator = "&" if "?" in next_url else "?"
        next_url = f"{next_url}{separator}scroll={scroll_target}"

    return render(
        request,
        "admin/canvas/canvas_asset_detail.html",
        {
            "canvas_asset": canvas_asset,
            "next_url": next_url,
        },
    )


# =============================================================================
# PROFILE UPDATE
# =============================================================================

@login_required
def admin_canvas_asset_delete(request, id):
    from ..catalog_admin import legacy_catalog_delete
    return legacy_catalog_delete(request, 'canvas-asset', id)


@login_required
@require_POST
def evaluate_user_design(request):
    if request.user.role != "customer":
        return JsonResponse({"message": "Not allowed"}, status=403)
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            return JsonResponse({"message": "Invalid design data."}, status=400)
        offer = get_object_or_404(DesignOffer, pk=data.get("design_offer_id")) if data.get("design_offer_id") else None
        return JsonResponse(evaluate_design(data.get("canvas_json"), offer))
    except RequestDataTooBig:
        return JsonResponse({"message": "Design evaluation is too large."}, status=413)
    except (ValueError, TypeError):
        return JsonResponse({"message": "Invalid design data."}, status=400)
