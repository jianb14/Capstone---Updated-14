"""AI design canvas and user design management. (split from app/views.py)"""

from .common import *  # noqa: F401,F403


@login_required
def select_design_type(request):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    # Get active packages to display as options
    active_packages = Package.objects.filter(is_active=True).order_by("price")

    return render(
        request, "client/select_design_type.html", {"packages": active_packages}
    )


@login_required
def my_designs_page(request):
    if request.user.role != "customer":
        return HttpResponseForbidden("Not allowed")

    # Order by updated_at descending so newest are first
    designs_list = UserDesign.objects.filter(user=request.user).order_by("-updated_at")

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

    # Get active packages for the "Create New Design" modal
    active_packages = Package.objects.filter(is_active=True).order_by("price")

    # Stats bar (bottom of page) — computed from ALL designs, hindi lang
    # ang nasa current page para tama ang counters
    all_designs = UserDesign.objects.filter(user=request.user)
    total_designs = all_designs.count()
    month_start = timezone.localtime().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    created_this_month = all_designs.filter(created_at__gte=month_start).count()
    last_edited = all_designs.order_by("-updated_at").first()

    return render(
        request,
        "client/my_designs.html",
        {
            "designs": designs,
            "packages": active_packages,
            "search_query": search_query,
            "sort_filter": sort_filter,
            "total_designs": total_designs,
            "created_this_month": created_this_month,
            "last_edited": last_edited,
        },
    )


@login_required
@require_POST
def save_user_design(request):
    if request.user.role != "customer":
        return JsonResponse({"status": "error", "message": "Not allowed"}, status=403)

    try:
        data = json.loads(request.body)
        design_id = data.get("id")
        name = data.get("name", "Untitled Design")
        canvas_json = data.get("canvas_json")
        thumbnail_data = data.get("thumbnail")  # Base64 string
        base_package_id = data.get("base_package_id")

        if not canvas_json:
            return JsonResponse(
                {"status": "error", "message": "Canvas data is required"}, status=400
            )

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
            if image_file:
                design.thumbnail = image_file
            
            # Maintain or update base package
            if base_package_id:
                try:
                    design.base_package = Package.objects.get(id=base_package_id)
                except Package.DoesNotExist:
                    pass
            
            design.save()
            log_action(request.user, f"Updated custom design #{design.id}.")
        else:
            # Create new
            base_package = None
            if base_package_id:
                try:
                    base_package = Package.objects.get(id=base_package_id)
                except Package.DoesNotExist:
                    pass

            design = UserDesign.objects.create(
                user=request.user,
                name=name,
                canvas_json=canvas_json,
                thumbnail=image_file,
                base_package=base_package,
            )
            log_action(request.user, f"Created new custom design #{design.id}.")

        return JsonResponse(
            {
                "status": "success",
                "id": design.id,
                "message": "Design saved successfully",
            }
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

    # 1. Check if we're editing an existing design
    design_id = request.GET.get("id")
    package_id = request.GET.get("package_id")
    is_custom = request.GET.get("custom") == "true"

    if design_id:
        design = get_object_or_404(UserDesign, id=design_id, user=request.user)
        context["design"] = design
        if design.base_package:
            context["base_package"] = design.base_package
    elif package_id:
        # Starting a new design from a package
        base_package = get_object_or_404(Package, id=package_id)
        context["base_package"] = base_package
        # We don't save a UserDesign yet, we just pass the info to the frontend
    elif is_custom:
        # Starting a blank custom design
        pass
    else:
        # No ID and no package_id and no custom flag -> Redirect to selection
        return redirect("select_design_type")

    # 2. Extract quotas for all packages
    all_packages = Package.objects.all().order_by("price")
    all_package_quotas = {}
    all_categories = list(CanvasCategory.objects.values_list('name', flat=True))

    for pkg in all_packages:
        quotas = {}
        for feature in pkg.feature_list():
            feature_text = feature.strip()
            if not feature_text:
                continue

            # Case 1: "1 Backdrop", "50 Balloons"
            match = re.search(r"^(\d+)\s+(.+)$", feature_text, re.IGNORECASE)
            if match:
                qty = int(match.group(1))
                item_name = match.group(2).strip().lower()
                
                mapped_cat = None
                for cat_name in all_categories:
                    cat_lower = cat_name.lower()
                    if cat_lower in item_name or item_name in cat_lower or \
                       cat_lower.rstrip('s') in item_name or item_name.rstrip('s') in cat_lower:
                        mapped_cat = cat_lower
                        break
                
                if mapped_cat:
                    quotas[mapped_cat] = qty
                else:
                    quotas[item_name] = qty

                # NEW: Extract balloon color limit if present in this feature
                if "balloon" in feature_text.lower() and "color" in feature_text.lower():
                    color_match = re.search(r"max\s+(\d+)\s+colors", feature_text, re.IGNORECASE)
                    if color_match:
                        quotas["balloon_color_limit"] = int(color_match.group(1))
            else:
                feature_lower = feature_text.lower()
                
                # NEW: Extract balloon color limit for non-numeric features too
                if "balloon" in feature_lower and "color" in feature_lower:
                    color_match = re.search(r"max\s+(\d+)\s+colors", feature_text, re.IGNORECASE)
                    if color_match:
                        quotas["balloon_color_limit"] = int(color_match.group(1))

                mapped_cat = None
                for cat_name in all_categories:
                    cat_lower = cat_name.lower()
                    if cat_lower in feature_lower or feature_lower in cat_lower or \
                       cat_lower.rstrip('s') in feature_lower or feature_lower.rstrip('s') in cat_lower:
                        mapped_cat = cat_lower
                        break
                
                if mapped_cat:
                    quotas[mapped_cat] = 999
                else:
                    quotas[feature_text] = -1
        all_package_quotas[pkg.id] = quotas

    context["all_packages"] = all_packages
    context["all_package_quotas"] = json.dumps(all_package_quotas)

    # Set initial quotas for current base package
    if "base_package" in context:
        context["package_quotas"] = json.dumps(all_package_quotas.get(context["base_package"].id, {}))
    else:
        context["package_quotas"] = json.dumps({})

    # 3. Fetch AddOn prices to calculate visual cart
    addons = AddOn.objects.filter(is_active=True)
    addon_prices = {}
    for addon in addons:
        addon_prices[addon.name.lower()] = str(addon.price)

    context["addon_prices"] = json.dumps(addon_prices)

    categories = ["Backdrops", "Balloons", "Furniture", "Decorations"]
    context["categories"] = categories
    active_canvas_assets = list(
        CanvasAsset.objects.filter(is_active=True, category__is_active=True)
        .select_related("category")
        .order_by("category__order", "category__name", "label_ref__order", "subgroup", "sort_order", "id")
    )
    canvas_categories = list(CanvasCategory.objects.filter(is_active=True).order_by("order", "name"))

    assets_by_category = {}
    for asset in active_canvas_assets:
        assets_by_category.setdefault(asset.category_id, []).append(asset)

    # Attach explicit resolved assets per category so template rendering does not depend on prefetch state.
    for category in canvas_categories:
        category.design_assets = assets_by_category.get(category.id, [])

    context["canvas_categories"] = canvas_categories

    # Fallback payload for client-side hydration when sidebar cards are empty.
    canvas_assets_payload = {}
    for category in canvas_categories:
        category_key = category.name.lower().strip()
        items = []
        for asset in category.design_assets:
            src = ""
            if asset.image:
                src = asset.image.url
            elif asset.static_path:
                src = static(asset.static_path)
            items.append(
                {
                    "id": asset.id,
                    "label": asset.label or "Asset",
                    "src": src,
                    "category": category_key,
                    "type": asset.item_type or "image",
                    "width": int(asset.width or 150),
                    "height": int(asset.height or 150),
                }
            )
        canvas_assets_payload[category_key] = items
    context["canvas_assets_payload"] = json.dumps(canvas_assets_payload)
    context["canvas_assets_payload_obj"] = canvas_assets_payload

    return render(request, "client/design_canvas.html", context)


@login_required
def admin_canvas_assets(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    categories = CanvasCategory.objects.order_by("order", "name")
    selected_asset_category = request.GET.get("asset_category", "all")
    canvas_assets = CanvasAsset.objects.select_related("category").all()

    if selected_asset_category != "all":
        try:
            parsed_category_id = int(selected_asset_category)
            canvas_assets = canvas_assets.filter(category_id=parsed_category_id)
        except (TypeError, ValueError):
            selected_asset_category = "all"

    categories_paginator = Paginator(categories, 10)
    categories_page = categories_paginator.get_page(request.GET.get("cat_page"))

    assets_paginator = Paginator(canvas_assets, 8)
    canvas_assets = assets_paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "admin/canvas/admin_canvas_assets.html",
        {
            "categories": categories,
            "categories_page": categories_page,
            "canvas_assets": canvas_assets,
            "selected_asset_category": selected_asset_category,
        },
    )


@login_required
def admin_canvas_category_create(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        order = request.POST.get("order", 1)
        is_active = request.POST.get("is_active") == "on"
        if not name:
            messages.warning(request, "Please enter a category name before saving.")
            return render(request, "admin/canvas/canvas_category_form.html")
        CanvasCategory.objects.create(
            name=name, order=parse_non_negative_int(order, 1), is_active=is_active
        )
        log_action(request.user, f"Created canvas category '{name}'.")
        messages.success(request, "Canvas category created successfully.")
        return redirect("admin_canvas_assets")
    return render(request, "admin/canvas/canvas_category_form.html")


@login_required
def admin_canvas_category_edit(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    category = get_object_or_404(CanvasCategory, id=id)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        order = request.POST.get("order", 1)
        is_active = request.POST.get("is_active") == "on"
        if not name:
            messages.warning(request, "Please enter a category name before saving.")
            return render(
                request,
                "admin/canvas/canvas_category_form.html",
                {"category": category},
            )
        category.name = name
        category.order = parse_non_negative_int(order, 1)
        category.is_active = is_active
        category.save()
        log_action(request.user, f"Updated canvas category '{name}'.")
        messages.success(request, "Canvas category updated successfully.")
        return redirect("admin_canvas_assets")
    return render(
        request, "admin/canvas/canvas_category_form.html", {"category": category}
    )


@login_required
def admin_canvas_category_delete(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    category = get_object_or_404(CanvasCategory, id=id)
    cat_name = category.name
    category.delete()
    log_action(request.user, f"Deleted canvas category '{cat_name}'.")
    messages.success(request, "Canvas category deleted successfully.")
    return redirect("admin_canvas_assets")


@login_required
def admin_canvas_label_create(request):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    categories = CanvasCategory.objects.order_by("order", "name")
    if request.method == "POST":
        category_id = request.POST.get("category")
        name = request.POST.get("name", "").strip()
        order = request.POST.get("order", 1)
        is_active = request.POST.get("is_active") == "on"
        if not category_id:
            messages.warning(request, "Please select a category for this label.")
            return render(
                request,
                "admin/canvas/canvas_label_form.html",
                {"categories": categories},
            )
        if not name:
            messages.warning(request, "Please enter a label name before saving.")
            return render(
                request,
                "admin/canvas/canvas_label_form.html",
                {"categories": categories},
            )

        category = CanvasCategory.objects.filter(id=category_id).first()
        if not category:
            messages.warning(
                request,
                "Selected category could not be found. Please choose another category.",
            )
            return render(
                request,
                "admin/canvas/canvas_label_form.html",
                {"categories": categories},
            )
        CanvasLabel.objects.create(
            category=category,
            name=name,
            order=parse_non_negative_int(order, 1),
            is_active=is_active,
        )
        log_action(request.user, f"Created canvas label '{name}' in '{category.name}'.")
        messages.success(request, "Canvas label created successfully.")
        return redirect("admin_canvas_assets")
    return render(
        request, "admin/canvas/canvas_label_form.html", {"categories": categories}
    )


@login_required
def admin_canvas_label_edit(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    label = get_object_or_404(CanvasLabel, id=id)
    categories = CanvasCategory.objects.order_by("order", "name")
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        order = request.POST.get("order", 1)
        is_active = request.POST.get("is_active") == "on"
        if not name:
            messages.warning(request, "Please enter a label name before saving.")
            return render(
                request,
                "admin/canvas/canvas_label_form.html",
                {"label": label, "categories": categories},
            )
        label.name = name
        label.order = parse_non_negative_int(order, 1)
        label.is_active = is_active
        label.save()
        log_action(request.user, f"Updated canvas label '{name}'.")
        messages.success(request, "Canvas label updated successfully.")
        return redirect("admin_canvas_assets")
    return render(
        request,
        "admin/canvas/canvas_label_form.html",
        {"label": label, "categories": categories},
    )


@login_required
def admin_canvas_label_delete(request, id):
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")
    label = get_object_or_404(CanvasLabel, id=id)
    label_name = label.name
    CanvasAsset.objects.filter(label_ref=label).update(label_ref=None)
    label.delete()
    log_action(request.user, f"Deleted canvas label '{label_name}'.")
    messages.success(request, "Canvas label deleted successfully.")
    return redirect("admin_canvas_assets")


@login_required
def admin_canvas_asset_create(request):
    if request.user.role not in ["admin", "staff"]:
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
            return render(
                request,
                "admin/canvas/canvas_asset_form.html",
                {"categories": categories},
            )

        if not label:
            messages.warning(request, "Please enter an asset name before saving.")
            return render(
                request,
                "admin/canvas/canvas_asset_form.html",
                {"categories": categories},
            )

        if not image:
            messages.warning(request, "Please upload an image file for this asset.")
            return render(
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
            return render(
                request,
                "admin/canvas/canvas_asset_form.html",
                {"categories": categories},
            )

        if width_val < 1:
            messages.warning(request, "Default width must be at least 1.")
            return render(
                request,
                "admin/canvas/canvas_asset_form.html",
                {"categories": categories},
            )

        if height_val < 1:
            messages.warning(request, "Default height must be at least 1.")
            return render(
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
            return render(
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
            label_ref=None,
            label=label,
            subgroup="",
            static_path=static_path,
            item_type=item_type,
            image=image,
            width=width_val,
            height=height_val,
            sort_order=next_sort,
            is_active=is_active,
        )
        log_action(request.user, f"Added canvas asset '{label}' to '{category.name}'.")
        messages.success(request, "Canvas asset added successfully.")
        return redirect("admin_canvas_assets")

    return render(
        request,
        "admin/canvas/canvas_asset_form.html",
        {"categories": categories},
    )


@login_required
def admin_canvas_asset_edit(request, id):
    if request.user.role not in ["admin", "staff"]:
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
            return render(
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
            return render(
                request,
                "admin/canvas/canvas_asset_form.html",
                {
                    "canvas_asset": canvas_asset,
                    "categories": categories,
                    "next_url": next_url,
                    "scroll_target": scroll_target,
                },
            )

        if not new_image and not canvas_asset.image and not canvas_asset.static_path:
            messages.warning(request, "Please upload an image file for this asset.")
            return render(
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
            return render(
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
            return render(
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
            return render(
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
            return render(
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
        canvas_asset.label_ref = None
        canvas_asset.label = label
        canvas_asset.subgroup = ""
        canvas_asset.static_path = static_path
        canvas_asset.item_type = item_type
        canvas_asset.width = width_val
        canvas_asset.height = height_val
        canvas_asset.is_active = is_active
        if new_image:
            canvas_asset.image = new_image
        canvas_asset.save()

        log_action(request.user, f"Updated canvas asset #{canvas_asset.id}.")
        messages.success(request, "Canvas asset updated successfully.")
        if next_url.startswith("/"):
            if scroll_target:
                separator = "&" if "?" in next_url else "?"
                return redirect(f"{next_url}{separator}scroll={scroll_target}")
            return redirect(next_url)
        return redirect("admin_canvas_assets")

    return render(
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
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    canvas_asset = get_object_or_404(
        CanvasAsset.objects.select_related("category", "label_ref"), id=id
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
    if request.user.role not in ["admin", "staff"]:
        return HttpResponseForbidden("Not allowed")

    canvas_asset = get_object_or_404(CanvasAsset, id=id)
    asset_id = canvas_asset.id
    canvas_asset.delete()
    log_action(request.user, f"Deleted canvas asset #{asset_id}.")
    messages.success(request, "Canvas asset deleted successfully.")
    return redirect("admin_canvas_assets")
