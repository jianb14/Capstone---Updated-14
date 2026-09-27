"""Public pages: home, about, services, gallery, reviews, policies. (split from app/views.py)"""

from .common import *  # noqa: F401,F403
from .admin import _seed_about_defaults, _seed_service_defaults  # noqa: F401


class HomePageView(TemplateView):
    template_name = "client/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["home_content"] = HomeContent.objects.first()
        context["home_features"] = HomeFeatureItem.objects.filter(is_active=True)
        context["home_hiw_steps"] = HomeHowItWorksStep.objects.filter(is_active=True)
        context["home_faqs"] = HomeFaqItem.objects.filter(is_active=True)

        content = context["home_content"]
        chips_raw = content.occasion_chips.strip() if content else ""
        if not chips_raw:
            chips_raw = "Birthdays, Weddings, Corporate Events, Christenings, Graduation"
        context["home_occasion_chips"] = [
            chip.strip() for chip in chips_raw.split(",") if chip.strip()
        ]

        context["top_reviews"] = get_top_reviews()
        context["latest_creations"] = GalleryImage.objects.filter(
            is_active=True
        ).order_by("-id")[:6]
        return context


class AboutPageView(TemplateView):
    template_name = "client/about.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        about_content = AboutContent.objects.first()
        if about_content is None:
            about_content = AboutContent.objects.create()
        # Prefill blank CMS fields / empty Core Values table with the same
        # defaults the client template falls back to (fresh DB safety).
        _seed_about_defaults(about_content)
        context["about_content"] = about_content

        # Split hero title into main + accent lines using "|" as separator
        # e.g. "Turning Moments Into | Elegant Celebrations."
        raw_title = (about_content.hero_title if about_content else "") or ""
        if "|" in raw_title:
            title_main, title_accent = raw_title.split("|", 1)
        else:
            title_main, title_accent = raw_title, ""
        context["hero_title_main"] = title_main.strip()
        context["hero_title_accent"] = title_accent.strip()

        # Story checklist points: one item per line in the CMS textarea.
        # Fallback defaults para hindi mawala ang checklist sa deployed/fresh
        # database kung saan wala pang na-save sa story_points field.
        raw_points = (about_content.story_points if about_content else "") or ""
        story_points_list = [
            line.strip() for line in raw_points.splitlines() if line.strip()
        ]
        if not story_points_list:
            story_points_list = [
                "Professional balloon styling for all events",
                "Fast and reliable setup team",
                "Custom designs for birthdays, weddings, and corporate events",
                "Affordable packages without compromising quality",
            ]
        context["story_points_list"] = story_points_list

        context["about_values"] = AboutValueItem.objects.filter(is_active=True)
        # "Our Journey" timeline steps (max 4 are rendered on the page)
        context["journey_items"] = AboutJourneyItem.objects.filter(is_active=True)[:4]
        context["top_reviews"] = get_top_reviews()
        return context


# -----------------------------
# Services Page Interactive Widgets (AI Style Quiz + Date Availability)
# -----------------------------

class ServicesPageView(TemplateView):
    template_name = "client/services.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["service_content"] = ServiceContent.objects.first()
        if context["service_content"] is None:
            context["service_content"] = ServiceContent.objects.create()
        # Fresh-DB safety: punuin ang blangkong CMS fields / Services table
        # gamit ang mga default na kapareho ng client fallbacks.
        _seed_service_defaults(context["service_content"])
        context["services"] = Service.objects.filter(is_active=True).order_by("display_order")

        # Interactive widgets: instant price estimator + comparison table data
        active_packages = Package.objects.filter(is_active=True)
        active_addons = AddOn.objects.filter(is_active=True)
        service_charge_config = get_service_charge_config()

        context["packages"] = active_packages
        context["active_addons"] = active_addons
        context["global_service_charge"] = service_charge_config.amount
        context["global_service_charge_note"] = service_charge_config.notes

        estimator_packages = [
            {
                "id": package.id,
                "name": package.name,
                "price": str(package.price),
                "service_charge": str(package.service_charge or 0),
                "features": package.feature_list(),
            }
            for package in active_packages
        ]
        estimator_addons = [
            {
                "id": addon.id,
                "name": addon.name,
                "price": str(addon.price),
                "solo_price": str(addon.solo_price) if addon.solo_price is not None else None,
                "service_charge": str(addon.service_charge or 0),
                "features": addon.feature_list(),
            }
            for addon in active_addons
        ]
        context["services_widget_data"] = {
            "packages": estimator_packages,
            "addons": estimator_addons,
            "serviceCharge": str(service_charge_config.amount or 0),
        }
        return context


SERVICES_QUIZ_THROTTLE_SECONDS = 10


@require_POST
def theme_quiz_api(request):
    """
    JSON API for the Services page "Find Your Perfect Style" quiz.
    Builds a prompt from the visitor's answers and reuses the existing
    HuggingFace chatbot to generate a theme recommendation.
    """
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "error": "Please log in to get AI style suggestions."},
            status=403,
        )

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid request body."}, status=400)

    event_type = str(data.get("event_type") or "").strip()
    vibe = str(data.get("vibe") or "").strip()
    budget = str(data.get("budget") or "").strip()
    colors = str(data.get("colors") or "").strip()

    if not event_type or not vibe:
        return JsonResponse(
            {"success": False, "error": "Event type and vibe are required."},
            status=400,
        )

    # Light throttle so the HuggingFace API is not spammed.
    throttle_key = f"services_quiz_{request.user.id}"
    if not cache.add(throttle_key, "1", SERVICES_QUIZ_THROTTLE_SECONDS):
        return JsonResponse(
            {"success": False, "error": "Please wait a few seconds before trying again."},
            status=429,
        )

    service_titles = list(
        Service.objects.filter(is_active=True).values_list("title", flat=True)
    )
    service_hint = ", ".join(service_titles) if service_titles else "balloon styling services"

    prompt = (
        "You are a friendly balloon styling consultant for an event decoration business. "
        "A customer answered a short style quiz with these details:\n"
        f"- Event type: {event_type}\n"
        f"- Preferred vibe: {vibe}\n"
        f"- Budget range: {budget or 'Not specified'}\n"
        f"- Preferred colors: {colors or 'No preference'}\n\n"
        f"Our services include: {service_hint}.\n\n"
        "Recommend ONE balloon theme concept. Reply in Taglish (casual but professional), "
        "under 150 words, using this exact structure:\n"
        "1. Theme Name (bold)\n"
        "2. Color palette\n"
        "3. Recommended service from our list\n"
        "4. 3-4 suggested inclusions (balloon arch, centerpiece, backdrop, etc.)\n"
        "5. One-sentence pitch on why it fits their event.\n"
        "Do not mention that you are an AI."
    )

    payload = get_chatbot_response(prompt, user=request.user)
    text = (payload.get("text") or "").strip() if isinstance(payload, dict) else str(payload)

    if not text:
        return JsonResponse(
            {
                "success": False,
                "error": "The AI stylist is unavailable right now. Please try again later.",
            },
            status=502,
        )

    if payload.get("is_banned") or payload.get("is_warning"):
        return JsonResponse({"success": False, "error": text}, status=403)

    return JsonResponse({"success": True, "response": text})


@require_GET
def check_date_availability(request):
    """
    JSON API for the Services page "Is my date available?" quick-check.
    A date is considered taken when any active customer booking
    (pending_payment / confirmed / completed) exists on that day,
    matching the client booking calendar filter.
    """
    raw_date = (request.GET.get("date") or "").strip()
    try:
        selected_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse(
            {"success": False, "error": "Please provide a valid date."},
            status=400,
        )

    today = timezone.localdate()
    if selected_date < today:
        return JsonResponse(
            {"success": False, "error": "Please choose a future date."},
            status=400,
        )

    blocked_statuses = ["pending_payment", "confirmed", "completed"]
    blocked_dates = set(
        Booking.objects.filter(
            event_date__gte=today,
            status__in=blocked_statuses,
        ).values_list("event_date", flat=True)
    )
    # Admin-blocked dates are also unavailable
    blocked_dates.update(
        BlockedDate.objects.filter(date__gte=today).values_list("date", flat=True)
    )
    blocked_by_admin = BlockedDate.objects.filter(
        date=selected_date
    ).exists()

    available = selected_date not in blocked_dates

    suggestions = []
    cursor = selected_date + timedelta(days=1)
    while len(suggestions) < 3 and cursor <= selected_date + timedelta(days=60):
        if cursor not in blocked_dates:
            suggestions.append(cursor.isoformat())
        cursor += timedelta(days=1)

    return JsonResponse(
        {
            "success": True,
            "date": selected_date.isoformat(),
            "available": available,
            "message": (
                "Great news! This date is still open for booking."
                if available
                else (
                    "Sorry, this date is unavailable (blocked by the admin). Here are the nearest open dates:"
                    if blocked_by_admin
                    else "Sorry, this date is already fully booked. Here are the nearest open dates:"
                )
            ),
            "suggestions": suggestions,
        }
    )


def _policy_page_context(page_key):
    """Shared helper: loads a GuidelinePageContent document and its active items."""
    content = (
        GuidelinePageContent.objects.filter(page_key=page_key)
        .prefetch_related("items")
        .first()
    )
    items = (
        content.items.filter(is_active=True).order_by("display_order", "id")
        if content
        else []
    )
    return content, items


class GuidelinesPageView(TemplateView):
    template_name = "client/guidelines.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["policy"], context["policy_items"] = _policy_page_context(
            GuidelinePageContent.PAGE_GUIDELINES
        )
        return context


class TermsConditionsPageView(TemplateView):
    template_name = "client/terms_conditions.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["policy"], context["policy_items"] = _policy_page_context(
            GuidelinePageContent.PAGE_TERMS
        )
        return context


class DataPrivacyPageView(TemplateView):
    template_name = "client/data_privacy.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["policy"], context["policy_items"] = _policy_page_context(
            GuidelinePageContent.PAGE_PRIVACY
        )
        return context


class PackagePageView(TemplateView):
    template_name = "client/package.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service_charge_config = get_service_charge_config()
        context.update(
            {
                "packages": Package.objects.all().order_by(
                    "-is_featured", "-created_at"
                ),
                "addons": AddOn.objects.filter(is_active=True).order_by("-created_at"),
                "additionals": AdditionalOnly.objects.filter(is_active=True).order_by(
                    "-created_at"
                ),
                "service_charge_amount": service_charge_config.amount,
                "service_charge_notes": service_charge_config.notes,
            }
        )
        return context


class GalleryPageView(TemplateView):
    template_name = "client/gallery.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = GalleryCategory.objects.all()
        context["gallery_images"] = GalleryImage.objects.filter(
            is_active=True
        ).select_related("category")
        return context


def reviews_page(request):
    reviews = (
        Review.objects.select_related("user", "booking")
        .select_related("reply", "reply__admin")
        .order_by("-created_at")
    )

    import json

    # Check if the current user has liked each review
    if request.user.is_authenticated:
        for review in reviews:
            review.is_liked_by_user = review.likes.filter(id=request.user.id).exists()
            review.can_be_liked = request.user != review.user

            # Serialize images for editing if the user owns the review
            if review.user == request.user:
                images_data = [
                    {"id": img.id, "url": img.image.url} for img in review.images.all()
                ]
                review.images_json = json.dumps(images_data)
    else:
        for review in reviews:
            review.is_liked_by_user = False
            review.can_be_liked = False

    # Para sa "Write a Review" CTA — may completed booking ba na walang review pa?
    if request.user.is_authenticated:
        has_pending_review = Booking.objects.filter(
            user=request.user, status="completed", reviews__isnull=True
        ).exists()
    else:
        has_pending_review = False

    return render(
        request,
        "client/reviews.html",
        {"reviews": reviews, "has_pending_review": has_pending_review},
    )


@login_required
@require_POST
def like_review(request, review_id):
    review = get_object_or_404(Review, id=review_id)

    # Prevent user from liking their own review
    if review.user == request.user:
        return JsonResponse({"error": "You cannot like your own review."}, status=400)

    # Toggle like
    if review.likes.filter(id=request.user.id).exists():
        review.likes.remove(request.user)
        liked = False
    else:
        review.likes.add(request.user)
        liked = True

    return JsonResponse({"liked": liked, "total_likes": review.total_likes()})


@login_required
@require_POST
def edit_review(request, review_id):
    review = get_object_or_404(Review, id=review_id, user=request.user)

    rating = request.POST.get("rating")
    comment = request.POST.get("comment")
    images_to_delete = request.POST.getlist("delete_images[]")
    new_images = request.FILES.getlist("images")

    # Validate rating range
    try:
        rating_val = int(rating) if rating else 0
    except (ValueError, TypeError):
        rating_val = 0
    if rating_val < 1 or rating_val > 5:
        return JsonResponse(
            {"status": "error", "message": "Rating must be between 1 and 5."},
            status=400,
        )

    if rating and comment:
        # Calculate resulting image count
        current_images_count = review.images.count()
        resulting_count = current_images_count - len(images_to_delete) + len(new_images)

        if resulting_count > 4:
            return JsonResponse(
                {
                    "status": "error",
                    "message": "You can only have a maximum of 4 pictures per review.",
                },
                status=400,
            )

        # 1. Delete requested images
        if images_to_delete:
            for img_id in images_to_delete:
                try:
                    img = ReviewImage.objects.get(id=img_id, review=review)
                    img.image.delete()  # Deletes file from storage
                    img.delete()  # Deletes record from DB
                except ReviewImage.DoesNotExist:
                    pass

        # 2. Add new images
        if new_images:
            for image in new_images:
                ReviewImage.objects.create(review=review, image=image)

        # 3. Update Text and Rating
        review.rating = rating
        review.comment = comment
        review.save()

        log_action(request.user, f"Updated review #{review.id}.")
        return JsonResponse(
            {
                "status": "success",
                "message": "Review updated successfully!",
                "rating": review.rating,
                "comment": review.comment,
            }
        )

    return JsonResponse(
        {"status": "error", "message": "Rating and comment are required."}, status=400
    )


@login_required
@require_POST
def delete_review(request, review_id):
    review = get_object_or_404(Review, id=review_id, user=request.user)
    review_id_val = review.id
    review.delete()

    log_action(request.user, f"Deleted review #{review_id_val}.")
    return JsonResponse(
        {"status": "success", "message": "Review deleted successfully!"}
    )
