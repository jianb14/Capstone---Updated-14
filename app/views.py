from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count, Avg, Max
from django.http import HttpResponseForbidden
from django.views.generic import TemplateView
from django.contrib import messages
from .models import Package, Booking, User, AuditLog, Design, Payment, ChatSession, ChatMessage, Review, ReviewImage, AddOn, AdditionalOnly, Notification, AdminNotification, UserDesign, GalleryCategory, GalleryImage, BookingImage, ServiceChargeConfig, ConcernTicket, CanvasCategory, CanvasLabel, CanvasAsset
from django.contrib.auth import get_user_model
import re
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.password_validation import validate_password
from decimal import Decimal, InvalidOperation
from django.http import JsonResponse
from django.utils import timezone
from datetime import datetime, timedelta
from django.views.decorators.http import require_POST, require_GET
import json
import hashlib
import logging
import time
from .services import get_chatbot_response
from django.db.models import Exists, OuterRef
from django.utils import timezone
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.encoding import force_bytes, force_str
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.urls import reverse
from django.core.mail import send_mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import transaction
from calendar import monthrange

logger = logging.getLogger(__name__)


def _increase_rate_limit_counter(key, timeout_seconds):
    if cache.add(key, 1, timeout=timeout_seconds):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=timeout_seconds)
        return 1


def _get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _format_wait_time(seconds):
    seconds = max(1, int(seconds))
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes, rem_seconds = divmod(seconds, 60)
    if minutes < 60:
        if rem_seconds:
            return f"{minutes} minute{'s' if minutes != 1 else ''} and {rem_seconds} second{'s' if rem_seconds != 1 else ''}"
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, rem_minutes = divmod(minutes, 60)
    if rem_minutes:
        return f"{hours} hour{'s' if hours != 1 else ''} and {rem_minutes} minute{'s' if rem_minutes != 1 else ''}"
    return f"{hours} hour{'s' if hours != 1 else ''}"


def _is_reset_request_rate_limited(request, email):
    client_ip = _get_client_ip(request)
    normalized_email = (email or "").strip().lower()
    email_hash = hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()
    now = int(time.time())

    cooldown_seconds = getattr(settings, "FORGOT_PASSWORD_COOLDOWN_SECONDS", 60)
    window_seconds = getattr(settings, "FORGOT_PASSWORD_RATE_LIMIT_WINDOW_SECONDS", 3600)
    ip_limit = getattr(settings, "FORGOT_PASSWORD_RATE_LIMIT_PER_IP", 5)
    email_limit = getattr(settings, "FORGOT_PASSWORD_RATE_LIMIT_PER_EMAIL", 3)

    cooldown_key = f"pwd-reset:cooldown:ip:{client_ip}"
    cooldown_until_key = f"{cooldown_key}:until"
    ip_count_key = f"pwd-reset:count:ip:{client_ip}"
    ip_window_until_key = f"{ip_count_key}:until"
    email_count_key = f"pwd-reset:count:email:{email_hash}"
    email_window_until_key = f"{email_count_key}:until"

    if cache.get(cooldown_key):
        cooldown_until = cache.get(cooldown_until_key) or (now + cooldown_seconds)
        wait_seconds = max(1, int(cooldown_until) - now)
        return True, f"Please wait {_format_wait_time(wait_seconds)} before requesting another reset link."

    current_ip_count = cache.get(ip_count_key, 0)
    current_email_count = cache.get(email_count_key, 0)
    if current_ip_count >= ip_limit or current_email_count >= email_limit:
        ip_wait_seconds = 0
        email_wait_seconds = 0

        if current_ip_count >= ip_limit:
            ip_window_until = cache.get(ip_window_until_key) or (now + window_seconds)
            ip_wait_seconds = max(1, int(ip_window_until) - now)

        if current_email_count >= email_limit:
            email_window_until = cache.get(email_window_until_key) or (now + window_seconds)
            email_wait_seconds = max(1, int(email_window_until) - now)

        wait_seconds = max(ip_wait_seconds, email_wait_seconds, 1)
        return True, f"Too many reset attempts. Please try again in {_format_wait_time(wait_seconds)}."

    cache.set(cooldown_key, 1, timeout=cooldown_seconds)
    cache.set(cooldown_until_key, now + cooldown_seconds, timeout=cooldown_seconds)
    cache.add(ip_window_until_key, now + window_seconds, timeout=window_seconds)
    cache.add(email_window_until_key, now + window_seconds, timeout=window_seconds)
    _increase_rate_limit_counter(ip_count_key, window_seconds)
    _increase_rate_limit_counter(email_count_key, window_seconds)
    return False, ""


def _send_account_verification_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    verify_url = request.build_absolute_uri(
        reverse('verify_email', kwargs={'uidb64': uid, 'token': token})
    )
    subject = "Verify your Balloorina account"
    body = (
        f"Hi {user.first_name or user.username},\n\n"
        f"Thanks for registering at Balloorina.\n"
        f"Please verify your Gmail by clicking the link below:\n{verify_url}\n\n"
        f"If you did not create this account, you can ignore this email."
    )
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@balloorina.local')
    send_mail(
        subject,
        body,
        from_email,
        [user.email],
        fail_silently=False,
    )


def log_action(user, action):
    """Helper function to create an audit log entry."""
    AuditLog.objects.create(user=user, action=action)


def get_service_charge_config():
    config, _ = ServiceChargeConfig.objects.get_or_create(
        id=1,
        defaults={
            "amount": Decimal("0.00"),
            "notes": "Includes styling fee, toll fees, fuel, crew meals, and ingress/egress logistics.",
        },
    )
    return config


def normalize_package_part(value):
    cleaned = re.sub(r"\s*\((add-on|additional|solo)\)\s*$", "", value or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.lower()


def format_booking_selection(package_type):
    parts = [p.strip() for p in (package_type or "").split("+") if p.strip()]
    if not parts:
        return "Custom Booking"

    packages = []
    addons = []
    solo_addons = []
    additionals = []

    for part in parts:
        if re.search(r"\(solo\)\s*$", part, re.IGNORECASE):
            solo_addons.append(re.sub(r"\s*\(solo\)\s*$", "", part, flags=re.IGNORECASE).strip())
        elif re.search(r"\(add-on\)\s*$", part, re.IGNORECASE):
            addons.append(re.sub(r"\s*\(add-on\)\s*$", "", part, flags=re.IGNORECASE).strip())
        elif re.search(r"\(additional\)\s*$", part, re.IGNORECASE):
            additionals.append(re.sub(r"\s*\(additional\)\s*$", "", part, flags=re.IGNORECASE).strip())
        else:
            packages.append(part)

    segments = []
    if packages:
        segments.append(f"Package: {', '.join(packages)}")
    if addons:
        segments.append(f"Add-on: {', '.join(addons)}")
    if solo_addons:
        segments.append(f"Solo Add-on: {', '.join(solo_addons)}")
    if additionals:
        segments.append(f"Additional: {', '.join(additionals)}")

    return " | ".join(segments) if segments else "Custom Booking"


def get_booking_price_breakdown(booking):
    parts = [p.strip() for p in (booking.package_type or "").split("+") if p.strip()]
    breakdown = []
    subtotal = Decimal("0.00")

    package_map = {
        normalize_package_part(pkg.name): pkg
        for pkg in Package.objects.all()
    }
    addon_map = {
        normalize_package_part(addon.name): addon
        for addon in AddOn.objects.all()
    }
    additional_map = {
        normalize_package_part(additional.name): additional
        for additional in AdditionalOnly.objects.all()
    }

    for raw_part in parts:
        is_solo = raw_part.endswith("(Solo)")
        part_name = raw_part.replace("(Solo)", "").strip() if is_solo else raw_part
        normalized_part_name = normalize_package_part(part_name)
        amount = None
        label = raw_part

        if is_solo:
            addon = addon_map.get(normalized_part_name)
            if addon and addon.solo_price is not None:
                amount = addon.solo_price
                label = f"{addon.name.strip()} (Solo)"
        else:
            package_obj = package_map.get(normalized_part_name)
            if package_obj:
                amount = package_obj.price
                label = package_obj.name.strip()
            else:
                addon = addon_map.get(normalized_part_name)
                if addon:
                    amount = addon.price
                    label = f"{addon.name.strip()} (Add-on)"
                else:
                    additional = additional_map.get(normalized_part_name)
                    if additional:
                        amount = additional.price
                        label = f"{additional.name.strip()} (Additional)"

        if amount is not None:
            subtotal += amount
            breakdown.append({"label": label, "amount": amount})

    service_charge = Decimal("0.00")
    if parts:
        service_charge = get_service_charge_config().amount or Decimal("0.00")

    computed_total = subtotal + service_charge
    return {
        "items": breakdown,
        "subtotal": subtotal,
        "service_charge": service_charge,
        "computed_total": computed_total,
        "stored_total": booking.total_price or Decimal("0.00"),
    }


def build_booking_snapshot(booking):
    return {
        "event_type": booking.event_type or "",
        "event_date": booking.event_date.isoformat() if booking.event_date else "",
        "event_time": booking.event_time.strftime("%H:%M") if booking.event_time else "",
        "event_location": booking.event_location or "",
        "package_type": booking.package_type or "",
        "special_requests": booking.special_requests or "",
        "total_price": str(booking.total_price or Decimal("0.00")),
    }


def apply_booking_snapshot(booking, snapshot):
    if not snapshot:
        return

    booking.event_type = snapshot.get("event_type", booking.event_type)
    event_date_raw = snapshot.get("event_date")
    event_time_raw = snapshot.get("event_time")
    total_price_raw = snapshot.get("total_price")

    if event_date_raw:
        try:
            booking.event_date = datetime.strptime(event_date_raw, "%Y-%m-%d").date()
        except ValueError:
            pass

    if event_time_raw:
        try:
            booking.event_time = datetime.strptime(event_time_raw, "%H:%M").time()
        except ValueError:
            booking.event_time = None
    else:
        booking.event_time = None

    booking.event_location = snapshot.get("event_location", booking.event_location)
    booking.package_type = snapshot.get("package_type", booking.package_type)
    booking.special_requests = snapshot.get("special_requests", booking.special_requests)

    if total_price_raw:
        try:
            booking.total_price = Decimal(str(total_price_raw))
        except (InvalidOperation, TypeError):
            pass


def get_top_reviews():
    """Helper function to get the top 3 reviews, prioritizing 5-stars and unique per user."""
    # Fetch reviews ordered by rating descending, then newest first
    all_reviews = Review.objects.select_related('user', 'booking').order_by('-rating', '-created_at')
    
    top_reviews = []
    seen_users = set()
    
    for review in all_reviews:
        if review.user.id not in seen_users:
            top_reviews.append(review)
            seen_users.add(review.user.id)
            
        if len(top_reviews) >= 6:
            break
            
    for review in top_reviews:
        review.booking_selection_display = format_booking_selection(
            review.booking.package_type if review.booking else ""
        )

    return top_reviews

class HomePageView(TemplateView):
    template_name = 'client/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['top_reviews'] = get_top_reviews()
        context['latest_creations'] = GalleryImage.objects.filter(is_active=True).order_by('-id')[:6]
        return context

class AboutPageView(TemplateView):
    template_name = 'client/about.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['top_reviews'] = get_top_reviews()
        return context
    

class ServicesPageView(TemplateView):
    template_name = 'client/services.html'
    

class GuidelinesPageView(TemplateView):
    template_name = 'client/guidelines.html'
    
    
class PackagePageView(TemplateView):
    template_name = 'client/package.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service_charge_config = get_service_charge_config()
        context.update({
            "packages": Package.objects.all().order_by("-is_featured", "-created_at"),
            "addons": AddOn.objects.filter(is_active=True).order_by("-created_at"),
            "additionals": AdditionalOnly.objects.filter(is_active=True).order_by("-created_at"),
            "service_charge_amount": service_charge_config.amount,
            "service_charge_notes": service_charge_config.notes,
        })
        return context


class GalleryPageView(TemplateView):
    template_name = 'client/gallery.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = GalleryCategory.objects.all()
        context['gallery_images'] = GalleryImage.objects.filter(is_active=True).select_related('category')
        return context
    

def reviews_page(request):
    reviews = Review.objects.select_related('user', 'booking').order_by('-created_at')
    
    import json
    
    # Check if the current user has liked each review
    if request.user.is_authenticated:
        for review in reviews:
            review.is_liked_by_user = review.likes.filter(id=request.user.id).exists()
            review.can_be_liked = (request.user != review.user)
            
            # Serialize images for editing if the user owns the review
            if review.user == request.user:
                images_data = [{'id': img.id, 'url': img.image.url} for img in review.images.all()]
                review.images_json = json.dumps(images_data)
    else:
        for review in reviews:
            review.is_liked_by_user = False
            review.can_be_liked = False
            
    return render(request, 'client/reviews.html', {'reviews': reviews})

@login_required
@require_POST
def like_review(request, review_id):
    review = get_object_or_404(Review, id=review_id)

    # Prevent user from liking their own review
    if review.user == request.user:
        return JsonResponse({'error': 'You cannot like your own review.'}, status=400)

    # Toggle like
    if review.likes.filter(id=request.user.id).exists():
        review.likes.remove(request.user)
        liked = False
    else:
        review.likes.add(request.user)
        liked = True

    return JsonResponse({
        'liked': liked,
        'total_likes': review.total_likes()
    })

@login_required
@require_POST
def edit_review(request, review_id):
    review = get_object_or_404(Review, id=review_id, user=request.user)
    
    rating = request.POST.get('rating')
    comment = request.POST.get('comment')
    images_to_delete = request.POST.getlist('delete_images[]')
    new_images = request.FILES.getlist('images')
    
    # Validate rating range
    try:
        rating_val = int(rating) if rating else 0
    except (ValueError, TypeError):
        rating_val = 0
    if rating_val < 1 or rating_val > 5:
        return JsonResponse({'status': 'error', 'message': 'Rating must be between 1 and 5.'}, status=400)
    
    if rating and comment:
        # Calculate resulting image count
        current_images_count = review.images.count()
        resulting_count = current_images_count - len(images_to_delete) + len(new_images)
        
        if resulting_count > 4:
            return JsonResponse({'status': 'error', 'message': 'You can only have a maximum of 4 pictures per review.'}, status=400)
            
        # 1. Delete requested images
        if images_to_delete:
            for img_id in images_to_delete:
                try:
                    img = ReviewImage.objects.get(id=img_id, review=review)
                    img.image.delete() # Deletes file from storage
                    img.delete()       # Deletes record from DB
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
        return JsonResponse({
            'status': 'success',
            'message': 'Review updated successfully!',
            'rating': review.rating,
            'comment': review.comment
        })
    
    return JsonResponse({'status': 'error', 'message': 'Rating and comment are required.'}, status=400)

@login_required
@require_POST
def delete_review(request, review_id):
    review = get_object_or_404(Review, id=review_id, user=request.user)
    review_id_val = review.id
    review.delete()
    
    log_action(request.user, f"Deleted review #{review_id_val}.")
    return JsonResponse({'status': 'success', 'message': 'Review deleted successfully!'})
    
    
User = get_user_model()

def register(request):
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        phone = request.POST.get('phone', '').strip()
        role = 'customer'

        errors = []

        # Required fields
        if not first_name:
            errors.append("First name is required.")
        if not last_name:
            errors.append("Last name is required.")
        if not username:
            errors.append("Username is required.")
        if not email:
            errors.append("Email is required.")
        elif not re.fullmatch(r"[A-Za-z0-9._%+-]+@gmail\.com", email):
            errors.append("Please enter a valid Gmail address (example: yourname@gmail.com).")
        if not password:
            errors.append("Password is required.")
        if not confirm_password:
            errors.append("Confirm password is required.")
        if not phone:
            errors.append("Phone number is required.")

        # Email unique
        if User.objects.filter(email=email).exists():
            errors.append("Email already exists.")

        # Username unique
        if User.objects.filter(username=username).exists():
            errors.append("Username already exists.")

        # Password match
        if password != confirm_password:
            errors.append("Passwords do not match.")

        # Password rules
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")

        # Phone number validation
        cleaned_phone = re.sub(r'[\s\-\(\)\+]', '', phone)
        if phone and not cleaned_phone.isdigit():
            errors.append("Phone number must contain only digits.")
        elif phone and (len(cleaned_phone) < 10 or len(cleaned_phone) > 15):
            errors.append("Phone number must be between 10 and 15 digits.")

        if errors:
            return render(request, 'auth/register.html', {'errors': errors})

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    phone_number=phone,
                    role=role,
                    email_verified=False,
                )
                _send_account_verification_email(request, user)
        except Exception:
            logger.exception("Failed to send account verification email.")
            errors.append("We could not send a verification email right now. Please try again in a moment.")
            return render(request, 'auth/register.html', {'errors': errors})

        log_action(None, f"New user '{username}' registered. Verification email sent.")
        messages.success(request, "Registration successful! Please check your Gmail and verify your account before logging in.")
        return redirect('login')

    return render(request, 'auth/register.html')


def verify_email(request, uidb64, token):
    user = None
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if not user:
        messages.error(request, "Invalid verification link.")
        return redirect('login')

    if user.email_verified:
        messages.success(request, "Your email is already verified. You can log in.")
        return redirect('login')

    if not default_token_generator.check_token(user, token):
        messages.error(request, "This verification link is invalid or expired. Please register again.")
        return redirect('register')

    user.email_verified = True
    user.save(update_fields=['email_verified'])
    log_action(user, "Email verified.")
    messages.success(request, "Email verified successfully. You can now log in.")
    return redirect('login')


User = get_user_model()

def user_login(request):
    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip().lower()
        password = request.POST.get('password')

        # Try to get user by email
        try:
            user_obj = User.objects.get(email=email)
            username = user_obj.username  # Django authenticate needs username
        except User.DoesNotExist:
            return render(request, 'auth/login.html', {'error': 'Invalid email or password.'})

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if not getattr(user, 'email_verified', True):
                return render(request, 'auth/login.html', {
                    'error': 'Please verify your Gmail first. Check your inbox for the verification link.'
                })

            login(request, user)

            log_action(user, "User logged in.")
            if request.POST.get('remember_me'):
                request.session.set_expiry(1209600)  # 2 weeks
            else:
                request.session.set_expiry(0)  # browser close

            if user.role == 'customer':
                messages.success(request, "Login successful! Welcome.")
                return redirect('home')
            elif user.role in ['admin', 'staff']:
                messages.success(request, "Login successful! Welcome to the dashboard.")
                return redirect('dashboard')
        else:
            return render(request, 'auth/login.html', {'error': 'Invalid email or password.'})

    return render(request, 'auth/login.html')
def forgot_password_request(request):
    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()
        generic_message = "If the email exists, a password reset link has been sent."

        if not email:
            messages.error(request, "Please enter your account email.")
            return render(request, 'auth/forgot_password.html')

        is_limited, rate_limit_message = _is_reset_request_rate_limited(request, email)
        if is_limited:
            messages.error(request, rate_limit_message)
            return render(request, 'auth/forgot_password.html')

        try:
            user = User.objects.get(email__iexact=email)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = request.build_absolute_uri(
                reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
            )
            subject = "Balloorina Password Reset"
            body = (
                f"Hi {user.first_name or user.username},\n\n"
                f"We received a request to reset your password.\n"
                f"Use the link below:\n{reset_url}\n\n"
                f"If you did not request this, you can ignore this message."
            )
            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@balloorina.local')
            send_mail(
                subject,
                body,
                from_email,
                [user.email],
                fail_silently=getattr(settings, 'EMAIL_FAIL_SILENTLY', True)
            )
        except User.DoesNotExist:
            pass
        except Exception:
            logger.exception("Failed to send forgot-password email.")

        messages.success(request, generic_message)
        return redirect('forgot_password')

    return render(request, 'auth/forgot_password.html')


def password_reset_confirm(request, uidb64, token):
    user = None
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    is_valid_link = bool(user and default_token_generator.check_token(user, token))

    if request.method == 'POST':
        if not is_valid_link:
            messages.error(request, "This reset link is invalid or expired.")
            return redirect('forgot_password')

        password = request.POST.get('password') or ''
        confirm_password = request.POST.get('confirm_password') or ''

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, 'auth/reset_password.html', {'is_valid_link': is_valid_link})

        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return render(request, 'auth/reset_password.html', {'is_valid_link': is_valid_link})

        user.set_password(password)
        user.save()
        log_action(user, "Password reset via forgot password.")
        messages.success(request, "Password updated successfully. You can now log in.")
        return redirect('login')

    return render(request, 'auth/reset_password.html', {'is_valid_link': is_valid_link})


@login_required
def report_concern(request):
    if request.user.role != 'customer':
        return HttpResponseForbidden("Not allowed")

    form_error_message = ""
    form_error_toasts = []
    form_data = {
        'category': '',
        'other_category': '',
        'subject': '',
        'message': '',
    }

    if request.method == 'POST':
        category = (request.POST.get('category') or '').strip()
        subject = (request.POST.get('subject') or '').strip()
        message_text = (request.POST.get('message') or '').strip()
        other_category = (request.POST.get('other_category') or '').strip()

        form_data = {
            'category': category,
            'other_category': other_category,
            'subject': subject,
            'message': message_text,
        }

        valid_categories = {choice[0] for choice in ConcernTicket.CATEGORY_CHOICES}

        if category not in valid_categories:
            form_error_message = "Please select a valid category."
        elif category == 'other' and not other_category:
            form_error_message = "Please specify your concern type."
        elif not subject:
            form_error_message = "Please enter a subject."
        elif not message_text:
            form_error_message = "Please enter your message."
        else:
            if category == 'other' and other_category:
                subject = f"{subject} (Other: {other_category})"
            ticket = ConcernTicket.objects.create(
                user=request.user,
                category=category,
                subject=subject,
                message=message_text,
            )
            log_action(request.user, f"Submitted concern ticket #{ticket.id}.")
            messages.success(request, "Concern submitted. Our team will review it soon.")
            return redirect('report_concern')

    if form_error_message:
        form_error_toasts = [form_error_message]

    my_tickets = ConcernTicket.objects.filter(user=request.user).order_by('-created_at')[:20]
    return render(request, 'client/report_concern.html', {
        'my_tickets': my_tickets,
        'form_data': form_data,
        'form_error_toasts': form_error_toasts,
    })


def user_logout(request):
    if request.user.is_authenticated:
        log_action(request.user, "User logged out.")
    logout(request)
    return redirect('home')


@login_required
def change_password(request):
    if request.method == 'POST':
        # Check if it's an AJAX request
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            log_action(request.user, "Changed their password.")
            update_session_auth_hash(request, user)  # Important to keep the user logged in
            if is_ajax:
                return JsonResponse({'success': True, 'message': 'Password updated successfully!'})
            messages.success(request, 'Your password was successfully updated!')
        else:
            if is_ajax:
                return JsonResponse({'success': False, 'errors': form.errors})
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{error}")
    return redirect('customer_profile')


@login_required
def dashboard(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    return render(request, 'admin/dashboard.html', build_dashboard_context(request))


def check_booking_expirations():
    """Find pending bookings past their event date, mark as expired and notify user."""
    expired_bookings = Booking.objects.filter(status='pending', event_date__lt=timezone.now().date())
    for b in expired_bookings:
        b.status = 'expired'
        b.save()
        Notification.objects.create(
            user=b.user,
            booking=b,
            message=f"Your booking #{b.id} for {b.event_date} has expired because it was not confirmed in time."
        )


@login_required
def my_profile(request):
    if request.user.role != 'customer':
        return HttpResponseForbidden("Not allowed")

    user_bookings = Booking.objects.filter(user=request.user)
    total_bookings = user_bookings.count()
    pending_count = user_bookings.filter(status='pending').count()
    confirmed_count = user_bookings.filter(status='confirmed').count()
    completed_count = user_bookings.filter(status='completed').count()

    return render(request, 'client/my_profile.html', {
        'total_bookings': total_bookings,
        'pending_count': pending_count,
        'confirmed_count': confirmed_count,
        'completed_count': completed_count,
    })

@login_required
def my_reviews(request):
    if request.user.role != 'customer':
        return HttpResponseForbidden("Not allowed")
    
    reviews_list = Review.objects.filter(user=request.user).select_related('booking').order_by('-created_at')
    
    # Pagination for published reviews (5 per page)
    paginator_published = Paginator(reviews_list, 5)
    page_published_number = request.GET.get('page_published', 1)
    try:
        reviews = paginator_published.page(page_published_number)
    except PageNotAnInteger:
        reviews = paginator_published.page(1)
    except EmptyPage:
        reviews = paginator_published.page(paginator_published.num_pages)
    
    # Check if the current user has liked each review (though they are their own reviews, just in case template expects it)
    for review in reviews:
        review.is_liked_by_user = review.likes.filter(id=request.user.id).exists()
        review.can_be_liked = False # cannot like own review
            
        images_data = [{'id': img.id, 'url': img.image.url} for img in review.images.all()]
        review.images_json = json.dumps(images_data)

    # Fetch completed bookings without reviews
    pending_reviews_list = Booking.objects.filter(
        user=request.user, 
        status='completed', 
        reviews__isnull=True
    ).order_by('-event_date')

    # Pagination for pending reviews (5 per page)
    paginator_pending = Paginator(pending_reviews_list, 5)
    page_pending_number = request.GET.get('page_pending', 1)
    try:
        pending_reviews = paginator_pending.page(page_pending_number)
    except PageNotAnInteger:
        pending_reviews = paginator_pending.page(1)
    except EmptyPage:
        pending_reviews = paginator_pending.page(paginator_pending.num_pages)

    # Attach formatted time range
    for b in pending_reviews:
        b.time_range_display = get_booking_time_range(b)

    return render(request, 'client/my_reviews.html', {
        'reviews': reviews,
        'published_page_obj': reviews,
        'pending_reviews': pending_reviews,
        'pending_page_obj': pending_reviews
    })


@login_required
def customer_profile(request):
    if request.user.role != 'customer':
        return HttpResponseForbidden("Not allowed")

    # Auto-expire pending bookings in the past
    check_booking_expirations()

    # Get filter parameters
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', 'all')
    sort_date = request.GET.get('sort_date', 'desc')

    user_bookings = Booking.objects.filter(user=request.user)

    # Calculate Stats before filtering so overall stats remain correct
    total_bookings = user_bookings.count()
    pending_count = user_bookings.filter(status='pending').count()
    confirmed_count = user_bookings.filter(status='confirmed').count()
    completed_count = user_bookings.filter(status='completed').count()

    # Apply Search Filter (by ID or Event Type)
    if search_query:
        if search_query.isdigit():
            user_bookings = user_bookings.filter(Q(id=search_query) | Q(event_type__icontains=search_query))
        else:
            user_bookings = user_bookings.filter(event_type__icontains=search_query)

    # Apply Status Filter
    if status_filter != 'all':
        if status_filter == 'request_edit':
            user_bookings = user_bookings.filter(status='confirmed', edit_requested=True)
        elif status_filter == 'request_cancel':
            user_bookings = user_bookings.filter(status='cancel_requested')
        else:
            user_bookings = user_bookings.filter(status=status_filter)

    # Apply Sorting
    if sort_date == 'id_desc':
        user_bookings = user_bookings.order_by('-id')
    elif sort_date == 'id_asc':
        user_bookings = user_bookings.order_by('id')
    elif sort_date == 'oldest':
        user_bookings = user_bookings.order_by('event_date')
    else:
        user_bookings = user_bookings.order_by('-event_date')

    # Pagination
    paginator = Paginator(user_bookings, 10)  # Show 10 bookings per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Attach formatted time range for the table/modal and check if reviewed
    for b in page_obj:
        b.time_range_display = get_booking_time_range(b)
        if b.status == 'completed':
            b.has_reviewed = b.reviews.filter(user=request.user).exists()
        else:
            b.has_reviewed = False
        b.price_breakdown = get_booking_price_breakdown(b)

    # Get active packages, addons, additionals for the edit modal dropdown
    active_packages = Package.objects.filter(is_active=True)
    active_addons = AddOn.objects.filter(is_active=True)
    active_additionals = AdditionalOnly.objects.all()
    service_charge_config = get_service_charge_config()

    return render(request, 'client/customer_profile.html', {
        'page_obj': page_obj,
        'user_bookings': page_obj,  # To maintain some backward compatibility for template logic, though page_obj is better
        'total_bookings': total_bookings,
        'pending_count': pending_count,
        'confirmed_count': confirmed_count,
        'completed_count': completed_count,
        'packages': active_packages,
        'active_addons': active_addons,
        'active_additionals': active_additionals,
        'global_service_charge': service_charge_config.amount,
        'global_service_charge_note': service_charge_config.notes,
        'search_query': search_query,
        'status_filter': status_filter,
        'sort_date': sort_date,
    })

@login_required
@require_POST
def submit_review(request, id):
    if request.user.role != 'customer':
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking, id=id, user=request.user)

    referer = request.META.get('HTTP_REFERER', '')
    fallback_redirect = 'customer_profile'
    if 'my-reviews' in referer or 'my_reviews' in referer:
        fallback_redirect = 'my_reviews'

    if booking.status != 'completed':
        messages.error(request, "You can only review completed bookings.")
        return redirect(fallback_redirect)

    # Check if already reviewed
    if booking.reviews.filter(user=request.user).exists():
        messages.error(request, "You have already reviewed this booking.")
        return redirect(fallback_redirect)

    rating = request.POST.get('rating')
    comment = request.POST.get('comment')

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

        images = request.FILES.getlist('images')
        
        if len(images) > 4:
            messages.error(request, "You can only upload a maximum of 4 pictures.")
            return redirect(fallback_redirect)

        review = Review.objects.create(
            user=request.user,
            booking=booking,
            rating=rating,
            comment=comment
        )
        
        for img in images:
            ReviewImage.objects.create(review=review, image=img)
            
        log_action(request.user, f"Submitted a review for booking #{booking.id}.")
        
        # Notify Admin
        AdminNotification.objects.create(
            booking=booking,
            user=request.user,
            message="submitted a new review."
        )
        
        messages.success(request, "Thank you for your review!")
        # On success, if they were in my_reviews, redirect them to my_reviews to see it immediately.
        # Otherwise redirect to the main reviews board.
        if fallback_redirect == 'my_reviews':
            return redirect('my_reviews')
        return redirect('reviews')  # Redirect to the new reviews page
    else:
        messages.error(request, "Please provide both a rating and a comment.")

    return redirect(fallback_redirect)


@login_required
def admin_profile(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    return render(request, 'admin/admin_profile.html')


# Helper to extract End Time from special_requests string
def get_end_time_from_str(text):
    match = re.search(r'\(End Time: (\d{2}:\d{2})\)', text)
    if match:
        return match.group(1)
    return None

# Helper to format "HH:MM" or time object into readable 12-hour time.
def format_time_12h(value):
    if not value:
        return ""
    try:
        if hasattr(value, "strftime"):
            return value.strftime("%I:%M %p").lstrip("0")
        parsed = datetime.strptime(str(value), "%H:%M")
        return parsed.strftime("%I:%M %p").lstrip("0")
    except (ValueError, TypeError):
        return str(value)

# Helper to remove existing End Time tag to prevent duplication
def remove_end_time_tag(text):
    if not text: return ""
    return re.sub(r'\s*\(End Time: \d{2}:\d{2}\)', '', text).strip()

# Helper to format full time range string (e.g., "10:00 AM - 12:00 PM")
def get_booking_time_range(booking):
    if not booking.event_time:
        return ""
    start_str = format_time_12h(booking.event_time)
    end_time_str = get_end_time_from_str(booking.special_requests or '')
    if end_time_str:
        try:
            end_time_obj = datetime.strptime(end_time_str, '%H:%M').time()
            end_str = format_time_12h(end_time_obj)
            return f"{start_str} - {end_str}"
        except ValueError:
            pass
    return start_str

# -------------------------
# BOOKING PAGE (Calendar + Form)
# -------------------------
@login_required
def booking_page(request):
    if request.user.role != 'customer':
        return HttpResponseForbidden("Not allowed")

    # Prepare Calendar Events
    all_bookings = Booking.objects.exclude(status__in=['cancelled']).filter(event_date__gte=timezone.now().date())
    calendar_events = []
    
    # Get active packages and optionals for the stepper
    active_packages = Package.objects.filter(is_active=True)
    active_addons = AddOn.objects.filter(is_active=True)
    active_additionals = AdditionalOnly.objects.all()
    service_charge_config = get_service_charge_config()

    for b in all_bookings:
        start_dt = datetime.combine(b.event_date, b.event_time) if b.event_time else None
        end_time_str = get_end_time_from_str(b.special_requests or '')
        end_dt = None
        if end_time_str:
            try:
                end_time_obj = datetime.strptime(end_time_str, '%H:%M').time()
                end_dt = datetime.combine(b.event_date, end_time_obj)
            except ValueError:
                pass

        calendar_events.append({
            'title': get_booking_time_range(b),
            'start': start_dt.isoformat() if start_dt else b.event_date.isoformat(),
            'end': end_dt.isoformat() if end_dt else None,
            'color': '#d97706' if b.status == 'pending' else '#3b82f6'
        })

    return render(request, 'client/booking/booking_page.html', {
        'calendar_events': calendar_events,
        'packages': active_packages,
        'active_addons': active_addons,
        'active_additionals': active_additionals,
        'global_service_charge': service_charge_config.amount,
        'global_service_charge_note': service_charge_config.notes,
    })

# -------------------------
# ADMIN CALENDAR PAGE
# -------------------------
@login_required
def admin_calendar(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    # Show ALL bookings regardless of status or date
    all_bookings = Booking.objects.select_related('user').all()
    calendar_events = []

    # Color mapping per status
    status_colors = {
        'confirmed': '#3b82f6',       # Blue
        'pending': '#d97706',         # Yellow/Amber
        'completed': '#22c55e',       # Green
        'expired': '#6b7280',         # Gray
        'cancelled': '#ef4444',       # Red
        'cancel_requested': '#f97316', # Orange
    }

    for b in all_bookings:
        start_dt = datetime.combine(b.event_date, b.event_time) if b.event_time else None
        end_time_str = get_end_time_from_str(b.special_requests or '')
        end_dt = None
        if end_time_str:
            try:
                end_time_obj = datetime.strptime(end_time_str, '%H:%M').time()
                end_dt = datetime.combine(b.event_date, end_time_obj)
            except ValueError:
                pass

        # Include client name and time range in the title
        client_name = b.user.first_name or b.user.username
        time_range = get_booking_time_range(b)
        event_title = f"{client_name} — {time_range}" if time_range else client_name

        # Clean special requests for display
        cleaned_requests = remove_end_time_tag(b.special_requests or '')

        calendar_events.append({
            'title': event_title,
            'start': start_dt.isoformat() if start_dt else b.event_date.isoformat(),
            'end': end_dt.isoformat() if end_dt else None,
            'color': status_colors.get(b.status, '#3b82f6'),
            'booking_id': b.id,
            'client_name': f"{b.user.first_name} {b.user.last_name}".strip() or b.user.username,
            'event_type': b.event_type or '—',
            'event_location': b.event_location or '—',
            'package_type': b.package_type or '—',
            'status': b.get_status_display(),
            'status_raw': b.status,
            'time_range': time_range or '—',
            'event_date': b.event_date.strftime('%B %d, %Y'),
            'total_price': str(b.total_price),
        })

    return render(request, 'admin/admin_calendar.html', {
        'calendar_events': calendar_events,
    })


@login_required
def mark_notifications_read(request):
    if request.user.role not in ['admin', 'staff']:
        return JsonResponse({'status': 'error', 'message': 'Not allowed'}, status=403)
    
    if request.method == 'POST':
        # Mark all legacy booking notifications as read
        Booking.objects.filter(admin_notified=False).update(admin_notified=True)
        # Mark all new unified events as read
        AdminNotification.objects.filter(is_read=False).update(is_read=True)
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error'}, status=400)


@login_required
def hide_notification(request, id):
    if request.user.role not in ['admin', 'staff']:
        return JsonResponse({'status': 'error', 'message': 'Not allowed'}, status=403)
    
    if request.method == 'POST':
        notif_id_str = str(id)
        if notif_id_str.startswith('b_'):
            # It's a legacy booking notification
            real_id = notif_id_str.replace('b_', '')
            booking = get_object_or_404(Booking, id=real_id)
            booking.admin_notif_hidden = True
            booking.save()
        elif notif_id_str.startswith('n_'):
            # It's a new admin notification event
            real_id = notif_id_str.replace('n_', '')
            notif = get_object_or_404(AdminNotification, id=real_id)
            notif.is_hidden = True
            notif.save()
        else:
            # Fallback for old integer IDs that might still exist in cached templates
            try:
                real_id = int(notif_id_str)
                booking = get_object_or_404(Booking, id=real_id)
                booking.admin_notif_hidden = True
                booking.save()
            except ValueError:
                return JsonResponse({'status': 'error', 'message': 'Invalid ID format'}, status=400)
                
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error'}, status=400)


@login_required
def mark_customer_notification_read(request, id):
    """Mark a customer's notification as read via AJAX."""
    try:
        notif = Notification.objects.get(id=id, user=request.user)
        notif.is_read = True
        notif.save()
        return JsonResponse({'status': 'success'})
    except Notification.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Notification not found'}, status=404)

@login_required
@require_POST
def clear_all_notifications(request):
    """Mark all of a customer's notifications as read."""
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'status': 'success'})


# -------------------------
# CREATE BOOKING
# -------------------------
@login_required
def create_booking(request):
    if request.user.role != 'customer':
        return HttpResponseForbidden("Not allowed")

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

    if request.method == "POST":
        start_time = request.POST.get('start_time')
        end_time = request.POST.get('end_time')
        event_date = request.POST.get('event_date')
        special_requests = request.POST.get('special_requests', '')
        special_requests = remove_end_time_tag(special_requests) # Clean up

        # Combine notes if end_time is provided (since model might only have event_time)
        if end_time:
            special_requests = f"{special_requests}\n(End Time: {end_time})".strip()

        # Validation for past dates/times
        now = timezone.localtime(timezone.now())
        today = now.date()
        
        if event_date:
            booking_date = datetime.strptime(event_date, '%Y-%m-%d').date()
            
            # 1. Past Date Check
            if booking_date < today:
                error_msg = "Cannot book a date in the past."
                if is_ajax:
                    return JsonResponse({'success': False, 'message': error_msg})
                messages.error(request, error_msg)
                return redirect('booking_page')
            
            # 2. Past Time Check (If booking is Today)
            if booking_date == today and start_time:
                booking_time = datetime.strptime(start_time, '%H:%M').time()
                if booking_time < now.time():
                    error_msg = "The selected start time has already passed. Please choose a future time."
                    if is_ajax:
                        return JsonResponse({'success': False, 'message': error_msg})
                    messages.error(request, error_msg)
                    return redirect('booking_page')

            # 3. Minimum Duration Check (1 hour)
            if start_time and end_time:
                booking_start_dt = datetime.combine(today, datetime.strptime(start_time, '%H:%M').time())
                booking_end_dt = datetime.combine(today, datetime.strptime(end_time, '%H:%M').time())
                
                # Handle cases where end time is crossing midnight (though forms usually restrict this)
                if booking_end_dt <= booking_start_dt:
                    booking_end_dt += timedelta(days=1)
                
                duration = booking_end_dt - booking_start_dt
                if duration < timedelta(hours=1):
                    error_msg = "Please choose an end time that is at least 1 hour after the start time."
                    if is_ajax:
                        return JsonResponse({'success': False, 'message': error_msg})
                    messages.error(request, error_msg)
                    return redirect('booking_page')

            # 4. Double Booking / Overlap Check
            if start_time and end_time:
                new_start = datetime.combine(booking_date, datetime.strptime(start_time, '%H:%M').time())
                new_end = datetime.combine(booking_date, datetime.strptime(end_time, '%H:%M').time())
                
                # Get active bookings for this date
                existing_bookings = Booking.objects.filter(event_date=booking_date).exclude(status__in=['cancelled', 'denied'])
                
                for b in existing_bookings:
                    if not b.event_time:
                        continue
                        
                    b_start = datetime.combine(booking_date, b.event_time)
                    # Extract end time from stored string or default to +4 hours
                    b_end_str = get_end_time_from_str(b.special_requests)
                    if b_end_str:
                        b_end = datetime.combine(booking_date, datetime.strptime(b_end_str, '%H:%M').time())
                    else:
                        b_end = b_start + timedelta(hours=4) # Default duration assumption
                    
                    # Check for Overlap: (StartA < EndB) and (EndA > StartB)
                    if new_start < b_end and new_end > b_start:
                        existing_start = format_time_12h(b.event_time)
                        existing_end = format_time_12h(b_end.time())
                        error_msg = (
                            f"Time slot unavailable. Another booking is already scheduled from "
                            f"{existing_start} to {existing_end}. Please choose a different time."
                        )
                        if is_ajax:
                            return JsonResponse({'success': False, 'message': error_msg})
                        messages.error(request, error_msg)
                        return redirect('booking_page')

        # 4. Validate total_price
        try:
            total_price_val = Decimal(request.POST.get('total_price', '0'))
        except InvalidOperation:
            error_msg = "Invalid price format."
            if is_ajax:
                return JsonResponse({'success': False, 'message': error_msg})
            messages.error(request, error_msg)
            return redirect('booking_page')
        if total_price_val <= 0:
            error_msg = "Total price must be greater than 0."
            if is_ajax:
                return JsonResponse({'success': False, 'message': error_msg})
            messages.error(request, error_msg)
            return redirect('booking_page')
        MAX_PRICE = Decimal('99999999.99')
        if total_price_val > MAX_PRICE:
            error_msg = "Total price exceeds the maximum allowed value."
            if is_ajax:
                return JsonResponse({'success': False, 'message': error_msg})
            messages.error(request, error_msg)
            return redirect('booking_page')

        booking = Booking.objects.create(
            user=request.user,
            event_type=request.POST.get('event_type'),
            event_date=event_date,
            event_time=start_time, # Save start time to event_time field
            event_location=request.POST.get('event_location'),
            package_type=request.POST.get('package_type'),
            special_requests=special_requests,
            reference_image=request.FILES.get('reference_image'),
            total_price=total_price_val
        )
        
        # Save multiple images (up to 4)
        images = request.FILES.getlist('reference_images')
        
        # Fallback if the form only sent single 'reference_image'
        if not images and request.FILES.get('reference_image'):
            images = [request.FILES.get('reference_image')]
            
        for img in images[:4]:
            BookingImage.objects.create(booking=booking, image=img)

        log_action(request.user, f"Created a new booking #{booking.id}.")

        if is_ajax:
            # Build event data so frontend can add to calendar dynamically
            event_title = f"{start_time} - {end_time} | {request.POST.get('event_type', '')}"
            event_start = f"{event_date}T{start_time}:00" if start_time else event_date
            event_end = f"{event_date}T{end_time}:00" if end_time else None
            return JsonResponse({
                'success': True,
                'message': 'Your booking has been successfully submitted! Please wait for admin confirmation.',
                'event_data': {
                    'title': event_title,
                    'start': event_start,
                    'end': event_end,
                    'backgroundColor': '#f5b041',
                    'borderColor': '#f5b041',
                    'textColor': '#ffffff'
                }
            })
        messages.success(request, "Booking created successfully!")
        return redirect('booking_page')

    return redirect('booking_page')


# -------------------------
# VIEW BOOKING
# -------------------------
@login_required
def view_booking(request, id):
    booking = get_object_or_404(Booking, id=id)

    if request.user != booking.user:
        return HttpResponseForbidden("Not allowed")

    booking.time_range_display = get_booking_time_range(booking)

    return render(request, 'client/booking/booking_detail.html', {'booking': booking})


# -------------------------
# EDIT BOOKING
# -------------------------
@login_required
def edit_booking(request, id):
    booking = get_object_or_404(Booking, id=id)

    if request.user != booking.user:
        return HttpResponseForbidden("Not allowed")

    # Allow direct edit for pending bookings.
    # For confirmed bookings, allow edit only when an edit request exists (or admin legacy allow flag is on).
    if not (booking.status == 'pending' or booking.edit_requested or booking.edit_allowed):
        messages.error(request, "You cannot edit this booking.")
        return redirect('customer_profile')

    if request.method == "POST":
        start_time = request.POST.get('start_time')
        end_time = request.POST.get('end_time')
        special_requests = request.POST.get('special_requests', '')
        special_requests = remove_end_time_tag(special_requests) # Clean up before appending

        # --- Validation Logic (Same as Create) ---
        now = timezone.localtime(timezone.now())
        today = now.date()
        booking_date = datetime.strptime(request.POST.get('event_date'), '%Y-%m-%d').date()

        if booking_date < today:
            messages.error(request, "Cannot change to a past date.")
            return redirect('edit_booking', id=id)

        if start_time and end_time:
            new_start = datetime.combine(booking_date, datetime.strptime(start_time, '%H:%M').time())
            new_end = datetime.combine(booking_date, datetime.strptime(end_time, '%H:%M').time())
            
            # Handle cases where end time is crossing midnight
            booking_end_dt_calc = new_end
            if booking_end_dt_calc <= new_start:
                booking_end_dt_calc += timedelta(days=1)
                
            if (booking_end_dt_calc - new_start) < timedelta(hours=1):
                messages.error(request, "Please choose an end time that is at least 1 hour after the start time.")
                return redirect('edit_booking', id=id)
            
            existing_bookings = Booking.objects.filter(event_date=booking_date).exclude(id=booking.id).exclude(status__in=['cancelled', 'denied'])
            for b in existing_bookings:
                b_start = datetime.combine(booking_date, b.event_time)
                b_end_str = get_end_time_from_str(b.special_requests)
                b_end = datetime.combine(booking_date, datetime.strptime(b_end_str, '%H:%M').time()) if b_end_str else b_start + timedelta(hours=4)
                
                if new_start < b_end and new_end > b_start:
                    existing_start = format_time_12h(b_start.time())
                    existing_end = format_time_12h(b_end.time())
                    messages.error(
                        request,
                        f"Time slot unavailable. Another booking is already scheduled from "
                        f"{existing_start} to {existing_end}. Please choose a different time."
                    )
                    return redirect('edit_booking', id=id)
        # -----------------------------------------

        if end_time:
            special_requests = f"{special_requests}\n(End Time: {end_time})".strip()

        booking.event_type = request.POST.get('event_type')
        booking.event_date = request.POST.get('event_date')
        booking.event_time = start_time
        booking.event_location = request.POST.get('event_location')
        booking.package_type = request.POST.get('package_type')
        booking.special_requests = special_requests
        booking.total_price = request.POST.get('total_price')
        
        if request.FILES.get('reference_image'):
            booking.reference_image = request.FILES.get('reference_image')

        # Remove deleted images
        remove_images = request.POST.getlist('remove_images[]')
        if remove_images:
            if 'legacy' in remove_images:
                if booking.reference_image:
                    booking.reference_image.delete(save=False)
                remove_images.remove('legacy')
            if remove_images:
                try:
                    remove_ids = [int(i) for i in remove_images if i.isdigit()]
                    if remove_ids:
                        BookingImage.objects.filter(id__in=remove_ids, booking=booking).delete()
                except ValueError:
                    pass
            
        # Add new images
        new_images = request.FILES.getlist('reference_images')
        current_img_count = booking.images.count()
        if booking.reference_image:
            current_img_count += 1
            
        allowed_new = max(0, 4 - current_img_count)
        
        for img in new_images[:allowed_new]:
            BookingImage.objects.create(booking=booking, image=img)

        # Keep edit_requested for confirmed bookings so admin can still approve/deny based on updated data.
        if booking.status == 'pending':
            booking.edit_requested = False
            booking.edit_allowed = False
        booking.save()

        log_action(request.user, f"Edited booking #{booking.id}.")
        messages.success(request, "Booking updated successfully!")
        return redirect('customer_profile')

    return render(request, 'client/booking/booking_form.html', {'booking': booking})


# -------------------------
# DELETE BOOKING
# -------------------------
@login_required
def delete_booking(request, id):
    booking = get_object_or_404(Booking, id=id)

    if request.user != booking.user:
        return HttpResponseForbidden("Not allowed")

    if booking.status != 'pending':
        messages.error(request, "Only pending bookings can be deleted.")
        return redirect('customer_profile')

    if request.method == "POST":
        booking_id = booking.id
        booking.delete()
        log_action(request.user, f"Deleted booking #{booking_id}.")
        messages.success(request, "Booking deleted successfully!")
        return redirect('customer_profile')

    return render(request, 'client/booking/booking_delete_confirm.html', {'booking': booking})


# -------------------------
# ADMIN APPROVE/DENY BOOKING
# -------------------------
@login_required
def admin_booking_list(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    # Auto-expire pending bookings in the past
    check_booking_expirations()

    status_filter = request.GET.get('status')
    bookings = Booking.objects.order_by('-created_at')

    if status_filter:
        if status_filter == 'edit_requested':
            bookings = bookings.filter(edit_requested=True)
        else:
            bookings = bookings.filter(status=status_filter)
    
    # Search Logic
    search_query = request.GET.get('search')
    if search_query:
        if search_query.startswith('#') and search_query[1:].isdigit():
            # If search query looks like #123, search by ID
            bookings = bookings.filter(id=search_query[1:])
        else:
            bookings = bookings.filter(
                Q(user__username__icontains=search_query) |
                Q(user__email__icontains=search_query) |
                Q(event_type__icontains=search_query) |
                Q(status__icontains=search_query) |
                Q(id__icontains=search_query)
            )
            
    # Pagination Logic (10 items per page)
    paginator = Paginator(bookings, 10)
    page_number = request.GET.get('page')
    bookings_page = paginator.get_page(page_number)
    
    # Attach formatted time range for display
    for b in bookings_page:
        b.time_range_display = get_booking_time_range(b)

    return render(request, 'admin/booking/admin_booking_list.html', {
        'bookings': bookings_page,
        'search_query': search_query or "",
        'status_filter': status_filter or ""
    })

@login_required
def admin_booking_detail(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking, id=id)

    # Add formatted time range
    booking.time_range_display = get_booking_time_range(booking)

    # Clean up special requests for display to hide the end time tag
    cleaned_requests = remove_end_time_tag(booking.special_requests or '')
    price_breakdown = get_booking_price_breakdown(booking)

    return render(request, 'admin/booking/admin_booking_detail.html', {
        'booking': booking,
        'cleaned_requests': cleaned_requests,
        'price_breakdown': price_breakdown,
    })


@login_required
def admin_booking_action(request, id, action):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking, id=id)

    if action == 'confirm':
        booking.status = 'confirmed'
        booking.admin_denial_reason = None
        log_action(request.user, f"Confirmed booking #{booking.id} for '{booking.user.username}'.")
        booking.save()
        
        # Notify Customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=f"Hooray! Your booking #{booking.id} is now CONFIRMED! See you soon! 🎉"
        )
        messages.success(request, "Booking confirmed!")
    elif action == 'deny':
        if request.method != 'POST':
            messages.error(request, "Please provide a denial reason.")
            return redirect('admin_booking_list')

        deny_reason = request.POST.get('deny_reason', '').strip()
        if not deny_reason:
            messages.error(request, "Denial reason is required.")
            return redirect('admin_booking_list')

        booking.status = 'cancelled'
        booking.admin_denial_reason = deny_reason
        booking.save()
        
        # Notify Customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=f"We're sorry, but your booking #{booking.id} was NOT approved. Reason: {deny_reason}"
        )
        log_action(request.user, f"Denied booking #{booking.id} for '{booking.user.username}'.")
        messages.success(request, "Booking denied!")
    elif action == 'complete':
        booking.status = 'completed'
        booking.admin_denial_reason = None
        booking.save()
        
        # Notify Customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=f"Thank you for trusting us! Your booking #{booking.id} is now COMPLETED. We hope you enjoyed our service! ❤️ Please feel free to leave a review about your experience! 😊"
        )
        log_action(request.user, f"Marked booking #{booking.id} as completed for '{booking.user.username}'.")
        messages.success(request, "Booking marked as completed!")

    return redirect('admin_booking_list')


@login_required
def request_cancel_booking(request, id):
    booking = get_object_or_404(Booking, id=id, user=request.user)

    if booking.status != 'confirmed':
        messages.error(request, "You cannot cancel this booking.")
        return redirect('customer_profile')

    if request.method != 'POST':
        messages.error(request, "Please submit a cancellation reason.")
        return redirect('customer_profile')

    reason = request.POST.get('reason', '').strip()
    if not reason:
        messages.error(request, "Cancellation reason is required.")
        return redirect('customer_profile')

    booking.status = 'cancel_requested'
    booking.cancel_request_reason = reason
    booking.edit_requested = False
    booking.edit_allowed = False
    booking.save()

    log_action(request.user, f"Requested to cancel booking #{booking.id}.")
    
    # Notify Admin
    AdminNotification.objects.create(
        booking=booking,
        user=request.user,
        message=f"requested to cancel their booking. Reason: {reason}"
    )
    
    messages.success(request, "Cancel request sent. Please wait for admin approval.")
    return redirect('customer_profile')



@login_required
def admin_cancel_action(request, id, action):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking, id=id)

    if booking.status != 'cancel_requested':
        messages.error(request, "Invalid action.")
        return redirect('admin_booking_list')

    if action == 'approve':
        booking.status = 'cancelled'
        booking.cancel_request_reason = None
        log_action(request.user, f"Approved cancellation request for booking #{booking.id}.")
        
        # Notify Customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=f"Your cancellation request for booking #{booking.id} has been APPROVED. Your booking is now cancelled."
        )
        messages.success(request, "Cancellation approved. Booking is now cancelled.")
    elif action == 'deny':
        booking.status = 'confirmed'
        booking.cancel_request_reason = None
        log_action(request.user, f"Denied cancellation request for booking #{booking.id}.")
        
        # Notify Customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=f"We're sorry, but your cancellation request for booking #{booking.id} was NOT approved."
        )
        messages.success(request, "Cancellation denied. Booking remains confirmed.")

    booking.save()
    return redirect('admin_booking_list')


@login_required
def request_edit_booking(request, id):
    booking = get_object_or_404(Booking, id=id, user=request.user)

    if booking.status != 'confirmed':
        messages.error(request, "Only confirmed bookings can request edit.")
        return redirect('customer_profile')

    if request.method != 'POST':
        messages.error(request, "Please submit an edit reason.")
        return redirect('customer_profile')

    reason = request.POST.get('reason', '').strip()
    if not reason:
        messages.error(request, "Edit reason is required.")
        return redirect('customer_profile')

    if not booking.edit_requested:
        booking.edit_original_snapshot = build_booking_snapshot(booking)

    booking.edit_requested = True
    booking.edit_allowed = True
    booking.edit_request_reason = reason
    booking.save()
    log_action(request.user, f"Requested to edit booking #{booking.id}.")
    
    # Notify Admin
    AdminNotification.objects.create(
        booking=booking,
        user=request.user,
        message=f"requested to edit their booking. Reason: {reason}"
    )
    
    messages.success(request, "Edit request sent. You can now edit your booking.")
    return redirect(f"{reverse('customer_profile')}?open_edit={booking.id}")


@login_required
def admin_edit_action(request, id, action):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking, id=id)

    if not booking.edit_requested:
        messages.error(request, "No edit request found.")
        return redirect('admin_booking_list')

    if action == 'approve':
        booking.edit_requested = False
        booking.edit_allowed = False
        booking.edit_request_reason = None
        booking.edit_original_snapshot = None
        log_action(request.user, f"Approved edit request for booking #{booking.id}.")
        
        # Notify Customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=f"Your edit request for booking #{booking.id} has been APPROVED. Your updated booking details are now confirmed."
        )
        messages.success(request, "Edit approved. Updated booking details are now confirmed.")
    elif action == 'deny':
        apply_booking_snapshot(booking, booking.edit_original_snapshot)
        booking.edit_requested = False
        booking.edit_allowed = False
        booking.edit_request_reason = None
        booking.edit_original_snapshot = None
        log_action(request.user, f"Denied edit request for booking #{booking.id}.")
        
        # Notify Customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=f"We're sorry, but your edit request for booking #{booking.id} was NOT approved."
        )
        messages.success(request, "Edit denied. Booking reverted to previous details.")

    booking.save()
    return redirect('admin_booking_list')




# =========================
# ADMIN USER MANAGEMENT
# =========================

@login_required
def admin_user_list(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    # 1. Kunin lahat ng users
    users_list = User.objects.all().order_by('username')

    # 2. Role Filter
    role_filter = request.GET.get('role')
    if role_filter and role_filter in ['admin', 'staff', 'customer']:
        users_list = users_list.filter(role=role_filter)

    # 3. Search Logic
    search_query = request.GET.get('search')
    if search_query:
        users_list = users_list.filter(
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query)
        )

    # 4. Pagination Logic (10 items per page)
    paginator = Paginator(users_list, 10)
    page_number = request.GET.get('page')
    users = paginator.get_page(page_number)

    return render(request, 'admin/user/admin_user_list.html', {'users': users})


@login_required
def admin_user_edit(request, id):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Admins only")

    user_obj = get_object_or_404(User, id=id)

    # ❌ bawal i-edit ang sarili
    if user_obj == request.user:
        messages.error(request, "You cannot edit your own account.")
        return redirect('admin_user_list')

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()
        role = request.POST.get('role', '').strip()

        user_obj.first_name = first_name
        user_obj.last_name = last_name
        user_obj.email = email
        user_obj.phone_number = phone_number
        user_obj.role = role

        if not first_name:
            messages.error(request, "First name is required.")
            return render(request, 'admin/user/admin_user_edit.html', {'u': user_obj})

        if not last_name:
            messages.error(request, "Last name is required.")
            return render(request, 'admin/user/admin_user_edit.html', {'u': user_obj})

        if not email:
            messages.error(request, "Email is required.")
            return render(request, 'admin/user/admin_user_edit.html', {'u': user_obj})

        if not phone_number:
            messages.error(request, "Phone number is required.")
            return render(request, 'admin/user/admin_user_edit.html', {'u': user_obj})

        valid_roles = {'admin', 'staff', 'customer'}
        if role not in valid_roles:
            messages.error(request, "Role is required.")
            return render(request, 'admin/user/admin_user_edit.html', {'u': user_obj})

        log_action(request.user, f"Edited user profile for '{user_obj.username}'.")
        user_obj.save()
        messages.success(request, "User updated successfully.")
        return redirect('admin_user_list')

    return render(request, 'admin/user/admin_user_edit.html', {'u': user_obj})


@login_required
def admin_user_toggle_active(request, id):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Admins only")

    user_obj = get_object_or_404(User, id=id)

    if user_obj == request.user:
        messages.error(request, "You cannot deactivate yourself.")
        return redirect('admin_user_list')

    user_obj.is_active = not user_obj.is_active
    user_obj.save()

    status = "activated" if user_obj.is_active else "deactivated"
    log_action(request.user, f"User account for '{user_obj.username}' has been {status}.")
    messages.success(request, f"User '{user_obj.username}' has been {status} successfully.")
    return redirect('admin_user_list')


@login_required
def admin_user_delete(request, id):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Admins only")

    user_obj = get_object_or_404(User, id=id)

    if user_obj == request.user:
        messages.error(request, "You cannot delete yourself.")
        return redirect('admin_user_list')

    username = user_obj.username
    user_obj.delete()
    log_action(request.user, f"Deleted user account for '{username}'.")
    messages.success(request, "User deleted.")
    return redirect('admin_user_list')


@login_required
def admin_audit_log_list(request):
    if request.user.role not in ['admin']:
        return HttpResponseForbidden("Admins only")

    log_list = AuditLog.objects.select_related('user').all()

    # Search Logic
    search_query = request.GET.get('search')
    if search_query:
        log_list = log_list.filter(
            Q(action__icontains=search_query) |
            Q(user__username__icontains=search_query)
        )

    # Pagination Logic (15 items per page)
    paginator = Paginator(log_list, 15)
    page_number = request.GET.get('page')
    logs = paginator.get_page(page_number)

    return render(request, 'admin/audit_log_list.html', {
        'logs': logs,
        'search_query': search_query or ""
    })


@login_required
def admin_package_create(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    
    if request.method == "POST":
        features = request.POST.get('features', '').strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render(request, 'admin/package/package_form.html')

        try:
            price = Decimal(request.POST['price'])
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(request, 'admin/package/package_form.html')

        MAX_PRICE = Decimal('99999999.99')
        if price < 0 or price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(request, 'admin/package/package_form.html')

        package = Package.objects.create(
            name=request.POST.get('name'),
            image=request.FILES.get('image'),
            features=features,
            price=price,
            notes=request.POST.get('notes'),
            is_featured=bool(request.POST.get('is_featured')),
        )

        log_action(request.user, f"Created new package: '{package.name}'.")
        messages.success(request, "Package created successfully!")
        return redirect('admin_package_list')

    return render(request, 'admin/package/package_form.html')

@login_required
def admin_package_edit(request, id):
    package = get_object_or_404(Package, id=id)

    if request.method == "POST":
        features = request.POST.get('features', '').strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render(request, 'admin/package/package_form.html', {'package': package})

        try:
            package.price = Decimal(request.POST['price'])
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(request, 'admin/package/package_form.html', {'package': package})

        MAX_PRICE = Decimal('99999999.99')
        if package.price < 0 or package.price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(request, 'admin/package/package_form.html', {'package': package})

        package.name = request.POST.get('name')
        package.features = features
        package.notes = request.POST.get('notes')
        package.is_featured = bool(request.POST.get('is_featured'))

        if request.FILES.get('image'):
            package.image = request.FILES.get('image')

        package.save()
        log_action(request.user, f"Edited package: '{package.name}'.")
        messages.success(request, "Package updated successfully!")
        return redirect('admin_package_list')

    return render(request, 'admin/package/package_form.html', {'package': package})


@login_required
def admin_package_list(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    # Featured packages first, then others, newest first
    packages = Package.objects.all().order_by('-is_featured', '-created_at')
    addons = AddOn.objects.all().order_by('-created_at')
    additionals = AdditionalOnly.objects.all().order_by('-created_at')
    service_charge_config = get_service_charge_config()

    return render(request, 'admin/package/package_list.html', {
        'packages': packages,
        'addons': addons,
        'additionals': additionals,
        'service_charge_config': service_charge_config,
    })


@login_required
def admin_service_charge_update(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    if request.method != "POST":
        return redirect('admin_package_list')

    config = get_service_charge_config()
    amount_raw = request.POST.get('service_charge_amount', '').strip()
    notes = request.POST.get('service_charge_notes', '').strip()

    if not notes:
        messages.error(request, "Service charge notes are required.")
        return redirect('admin_package_list')

    if not amount_raw:
        messages.error(request, "Service charge amount is required.")
        return redirect('admin_package_list')

    try:
        amount = Decimal(amount_raw)
    except InvalidOperation:
        messages.error(request, "Invalid service charge amount.")
        return redirect('admin_package_list')

    max_price = Decimal('99999999.99')
    if amount < 0 or amount > max_price:
        messages.error(request, "Service charge must be between 0 and 99,999,999.99.")
        return redirect('admin_package_list')

    config.amount = amount
    config.notes = notes
    config.save()

    log_action(request.user, f"Updated global service charge to {config.amount}.")
    messages.success(request, "Service charge settings updated.")
    return redirect('admin_package_list')
    
    
@login_required
def admin_package_detail(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    package = get_object_or_404(Package, id=id)

    return render(request, 'admin/package/package_detail.html', {
        'package': package
    })


@login_required
def admin_package_delete(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    package = get_object_or_404(Package, id=id)
    package_name = package.name
    package.delete()
    log_action(request.user, f"Deleted package: '{package_name}'.")
    messages.success(request, "Package deleted successfully!")
    return redirect('admin_package_list')


def package(request):
    packages = Package.objects.all().order_by('-is_featured', '-created_at')
    addons = AddOn.objects.filter(is_active=True).order_by('-created_at')
    additionals = AdditionalOnly.objects.filter(is_active=True).order_by('-created_at')
    service_charge_config = get_service_charge_config()

    return render(request, 'client/package.html', {
        'packages': packages,
        'addons': addons,
        'additionals': additionals,
        'service_charge_amount': service_charge_config.amount,
        'service_charge_notes': service_charge_config.notes,
    })



from decimal import Decimal, InvalidOperation

@login_required
def admin_addon_create(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST":
        features = request.POST.get('features', '').strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render(request, 'admin/package/addon_form.html')

        solo_raw = request.POST.get('solo_price', '').strip()
        if not solo_raw:
            messages.error(request, "Solo price is required.")
            return render(request, 'admin/package/addon_form.html')

        try:
            price = Decimal(request.POST['price'])
            solo_price = Decimal(solo_raw)
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(request, 'admin/package/addon_form.html')

        MAX_PRICE = Decimal('99999999.99')
        if price < 0 or price > MAX_PRICE or solo_price < 0 or solo_price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(request, 'admin/package/addon_form.html')

        addon = AddOn.objects.create(
            name=request.POST.get('name'),
            image=request.FILES.get('image'),
            price=price,              
            solo_price=solo_price,
            features=features,
        )

        log_action(request.user, f"Created new add-on: '{addon.name}'.")
        messages.success(request, "Add-on created successfully!")
        return redirect('admin_package_list')

    return render(request, 'admin/package/addon_form.html')


@login_required
def admin_addon_detail(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    addon = get_object_or_404(AddOn, id=id)

    return render(request, 'admin/package/addon_detail.html', {
        'addon': addon
    })


@login_required
def admin_addon_edit(request, id):
    addon = get_object_or_404(AddOn, id=id)

    if request.method == "POST":
        features = request.POST.get('features', '').strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render(request, 'admin/package/addon_form.html', {'addon': addon})

        solo_raw = request.POST.get('solo_price', '').strip()
        if not solo_raw:
            messages.error(request, "Solo price is required.")
            return render(request, 'admin/package/addon_form.html', {'addon': addon})

        try:
            addon.price = Decimal(request.POST['price'])
            addon.solo_price = Decimal(solo_raw)
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(request, 'admin/package/addon_form.html', {'addon': addon})

        MAX_PRICE = Decimal('99999999.99')
        if addon.price < 0 or addon.price > MAX_PRICE or addon.solo_price < 0 or addon.solo_price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(request, 'admin/package/addon_form.html', {'addon': addon})

        addon.name = request.POST.get('name')
        addon.features = features
        
        if request.FILES.get('image'):
            addon.image = request.FILES.get('image')

        addon.save()

        log_action(request.user, f"Edited add-on: '{addon.name}'.")
        messages.success(request, "Add-on updated successfully!")
        return redirect('admin_package_list')

    return render(request, 'admin/package/addon_form.html', {'addon': addon})



@login_required
def admin_addon_delete(request, id):
    addon = get_object_or_404(AddOn, id=id)
    addon_name = addon.name
    addon.delete()
    log_action(request.user, f"Deleted add-on: '{addon_name}'.")
    messages.success(request, "Add-on deleted successfully!")
    return redirect('admin_package_list')



@login_required
def admin_additional_create(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    
    if request.method == "POST":
        features = request.POST.get('features', '').strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render(request, 'admin/package/additional_form.html')

        try:
            price = Decimal(request.POST['price'])
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(request, 'admin/package/additional_form.html')

        MAX_PRICE = Decimal('99999999.99')
        if price < 0 or price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(request, 'admin/package/additional_form.html')

        additional = AdditionalOnly.objects.create(
            name=request.POST.get('name'),
            image=request.FILES.get('image'),
            price=price,
            features=features,
            notes=request.POST.get('notes'),
        )

        log_action(request.user, f"Created new additional item: '{additional.name}'.")
        messages.success(request, "Additional created successfully!")
        return redirect('admin_package_list')

    return render(request, 'admin/package/additional_form.html')




@login_required
def admin_additional_edit(request, id):
    additional = get_object_or_404(AdditionalOnly, id=id)

    if request.method == "POST":
        features = request.POST.get('features', '').strip()
        if not features:
            messages.error(request, "Inclusions are required.")
            return render(request, 'admin/package/additional_form.html', {'additional': additional})

        try:
            additional.price = Decimal(request.POST['price'])
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(request, 'admin/package/additional_form.html', {'additional': additional})

        MAX_PRICE = Decimal('99999999.99')
        if additional.price < 0 or additional.price > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(request, 'admin/package/additional_form.html', {'additional': additional})

        additional.name = request.POST.get('name')
        additional.features = features
        additional.notes = request.POST.get('notes')
        
        if request.FILES.get('image'):
            additional.image = request.FILES.get('image')

        additional.save()

        log_action(request.user, f"Edited additional item: '{additional.name}'.")
        messages.success(request, "Additional updated successfully!")
        return redirect('admin_package_list')

    return render(request, 'admin/package/additional_form.html', {'additional': additional})


@login_required
def admin_additional_detail(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    additional = get_object_or_404(AdditionalOnly, id=id)

    return render(request, 'admin/package/additional_detail.html', {
        'additional': additional
    })


@login_required
def admin_additional_delete(request, id):
    additional = get_object_or_404(AdditionalOnly, id=id)
    additional_name = additional.name
    additional.delete()
    log_action(request.user, f"Deleted additional item: '{additional_name}'.")
    messages.success(request, "Additional deleted successfully!")
    return redirect('admin_package_list')


# =========================
# ADMIN REPORTS
# =========================
def _get_reporting_date_range(request):
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    if not start_date_str or not end_date_str:
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=30)
    else:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=30)

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    return start_date, end_date


def _status_distribution_from_queryset(filtered_bookings):
    status_colors_map = {
        'completed': '#10b981',
        'confirmed': '#3b82f6',
        'pending': '#f59e0b',
        'cancel_requested': '#f87171',
        'cancelled': '#ef4444',
        'expired': '#9ca3af'
    }
    status_dist_qs = filtered_bookings.values('status').annotate(count=Count('id')).order_by('status')
    status_distribution = []
    for item in status_dist_qs:
        status_raw = item['status']
        status_distribution.append({
            'status': status_raw,
            'label': status_raw.title(),
            'count': item['count'],
            'color': status_colors_map.get(status_raw.lower(), '#6b7280')
        })
    return status_distribution


def _get_trend_bucket_mode(date_range_days):
    if date_range_days <= 31:
        return 'day'
    if date_range_days <= 180:
        return 'week'
    return 'month'


def _build_trend_spans_and_labels(start_date, end_date, bucket_mode):
    spans = []
    labels = []
    cursor = start_date

    while cursor <= end_date:
        if bucket_mode == 'day':
            bucket_end = cursor
            label = cursor.strftime('%b %d')
        elif bucket_mode == 'week':
            bucket_end = min(cursor + timedelta(days=6), end_date)
            label = f"{cursor.strftime('%b %d')} - {bucket_end.strftime('%b %d')}"
        else:
            month_end_day = monthrange(cursor.year, cursor.month)[1]
            natural_month_end = datetime(cursor.year, cursor.month, month_end_day).date()
            bucket_end = min(natural_month_end, end_date)
            if cursor.day == 1 and bucket_end.day == month_end_day:
                label = cursor.strftime('%b %Y')
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

    for created_date, booking_total, status in bookings_qs.values_list('created_at__date', 'total_price', 'status'):
        bucket_idx = bucket_index_by_day.get(created_date)
        if bucket_idx is None:
            continue
        bookings_series[bucket_idx] += 1
        if status == 'completed':
            revenue_series[bucket_idx] += float(booking_total or 0)

    return bookings_series, revenue_series


def build_dashboard_context(request):
    start_date, end_date = _get_reporting_date_range(request)
    date_range_days = (end_date - start_date).days + 1

    event_type_options = list(
        Booking.objects
        .exclude(event_type__isnull=True)
        .exclude(event_type__exact='')
        .values_list('event_type', flat=True)
        .distinct()
        .order_by('event_type')
    )
    selected_event_type = (request.GET.get('event_type') or 'all').strip()
    if selected_event_type != 'all' and selected_event_type not in event_type_options:
        selected_event_type = 'all'

    filtered_bookings = Booking.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )
    if selected_event_type != 'all':
        filtered_bookings = filtered_bookings.filter(event_type=selected_event_type)

    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=max(date_range_days - 1, 0))
    previous_period_bookings = Booking.objects.filter(
        created_at__date__gte=previous_start,
        created_at__date__lte=previous_end
    )
    if selected_event_type != 'all':
        previous_period_bookings = previous_period_bookings.filter(event_type=selected_event_type)

    status_distribution = _status_distribution_from_queryset(filtered_bookings)
    today = timezone.localdate()

    edit_requests = filtered_bookings.filter(edit_requested=True).count()
    cancel_requests = filtered_bookings.filter(status='cancel_requested').count()
    pending_approvals = filtered_bookings.filter(status='pending').count()
    action_queue_total = pending_approvals + edit_requests + cancel_requests

    upcoming_deadline_bookings = Booking.objects.filter(
        status='pending',
        event_date__gte=today,
        event_date__lte=today + timedelta(days=3)
    ).select_related('user').order_by('event_date')[:6]
    for booking in upcoming_deadline_bookings:
        booking.days_left = (booking.event_date - today).days

    total_revenue = filtered_bookings.filter(status='completed').aggregate(Sum('total_price'))['total_price__sum'] or 0
    total_bookings = filtered_bookings.count()
    completed_count = filtered_bookings.filter(status='completed').count()
    cancelled_count = filtered_bookings.filter(status='cancelled').count()
    avg_booking_value = filtered_bookings.filter(status='completed').aggregate(Avg('total_price'))['total_price__avg'] or 0
    completion_rate = round((completed_count / total_bookings) * 100, 1) if total_bookings else 0
    cancellation_rate = round((cancelled_count / total_bookings) * 100, 1) if total_bookings else 0

    prev_period_bookings = previous_period_bookings.count()
    period_delta = total_bookings - prev_period_bookings
    period_delta_pct = round((period_delta / prev_period_bookings) * 100, 1) if prev_period_bookings > 0 else (100.0 if total_bookings > 0 else 0.0)
    prev_completed_revenue = previous_period_bookings.filter(status='completed').aggregate(Sum('total_price'))['total_price__sum'] or 0
    revenue_delta = total_revenue - prev_completed_revenue
    revenue_delta_pct = round((revenue_delta / prev_completed_revenue) * 100, 1) if prev_completed_revenue else (100.0 if total_revenue > 0 else 0.0)

    revenue_by_event = list(
        filtered_bookings
        .filter(status='completed')
        .values('event_type')
        .annotate(total=Sum('total_price'))
        .order_by('-total')
    )
    top_event_label = 'No completed bookings yet'
    top_event_revenue = 0
    if revenue_by_event:
        top_event_label = revenue_by_event[0]['event_type']
        top_event_revenue = revenue_by_event[0]['total'] or 0

    package_counts = {}
    completed_with_packages = filtered_bookings.filter(status='completed').values_list('package_type', flat=True)
    for package_type in completed_with_packages:
        if not package_type:
            continue
        first_part = str(package_type).split('+')[0].strip()
        if first_part:
            package_counts[first_part] = package_counts.get(first_part, 0) + 1
    top_package_name = 'No package data'
    top_package_count = 0
    if package_counts:
        top_package_name, top_package_count = max(package_counts.items(), key=lambda item: item[1])

    package_rows = []
    package_revenue = {}
    completed_with_package_revenue = filtered_bookings.filter(status='completed').values_list('package_type', 'total_price')
    for package_type, booking_total in completed_with_package_revenue:
        if not package_type:
            continue
        package_name = str(package_type).split('+')[0].strip()
        if not package_name:
            continue
        package_counts[package_name] = package_counts.get(package_name, 0) + 1
        package_revenue[package_name] = package_revenue.get(package_name, Decimal("0.00")) + (booking_total or Decimal("0.00"))

    for package_name, count in sorted(package_counts.items(), key=lambda item: item[1], reverse=True)[:8]:
        package_rows.append({
            'package_name': package_name,
            'count': count,
            'revenue': package_revenue.get(package_name, Decimal("0.00")),
        })

    top_customers = filtered_bookings.values('user__username', 'user__email').annotate(
        bookings_count=Count('id'),
        total_spent=Sum('total_price')
    ).order_by('-total_spent')[:8]

    status_table = [
        {
            'label': item['label'],
            'count': item['count'],
            'color': item['color'],
            'share_pct': round((item['count'] / total_bookings) * 100, 1) if total_bookings else 0,
        }
        for item in status_distribution
    ]

    recent_audit_logs = AuditLog.objects.select_related('user').order_by('-created_at')[:6]
    recent_bookings = filtered_bookings.select_related('user').order_by('-created_at')[:15]

    trend_bucket_mode = _get_trend_bucket_mode(date_range_days)
    trend_bucket_spans, chart_labels = _build_trend_spans_and_labels(start_date, end_date, trend_bucket_mode)
    bookings_trend, revenue_trend = _aggregate_trend_series(filtered_bookings, start_date, trend_bucket_spans)

    prev_bookings_trend, prev_revenue_trend = _aggregate_trend_series(
        previous_period_bookings,
        previous_start,
        trend_bucket_spans,
    )

    trend_title_map = {
        'day': 'Daily Trend',
        'week': 'Weekly Trend',
        'month': 'Monthly Trend',
    }
    trend_bucket_label_map = {
        'day': 'Daily buckets',
        'week': 'Weekly buckets',
        'month': 'Monthly buckets',
    }

    queue_breakdown = {
        'labels': ['Pending', 'Edit Requests', 'Cancel Requests'],
        'values': [pending_approvals, edit_requests, cancel_requests],
        'colors': ['#f59e0b', '#3b82f6', '#ef4444'],
    }

    return {
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'selected_event_type': selected_event_type,
        'event_type_options': event_type_options,
        'active_users': User.objects.filter(role='customer', is_active=True).count(),
        'pending_approvals': pending_approvals,
        'edit_requests': edit_requests,
        'cancel_requests': cancel_requests,
        'action_queue_total': action_queue_total,
        'upcoming_deadline_bookings': upcoming_deadline_bookings,
        'period_delta': period_delta,
        'period_delta_pct': period_delta_pct,
        'total_revenue': total_revenue,
        'avg_booking_value': avg_booking_value,
        'completion_rate': completion_rate,
        'cancellation_rate': cancellation_rate,
        'completed_count': completed_count,
        'cancelled_count': cancelled_count,
        'total_bookings': total_bookings,
        'revenue_delta': revenue_delta,
        'revenue_delta_pct': revenue_delta_pct,
        'top_event_label': top_event_label,
        'top_event_revenue': top_event_revenue,
        'top_package_name': top_package_name,
        'top_package_count': top_package_count,
        'top_customers': top_customers,
        'status_table': status_table,
        'package_rows': package_rows,
        'revenue_by_event': revenue_by_event,
        'date_range_days': date_range_days,
        'recent_audit_logs': recent_audit_logs,
        'recent_bookings': recent_bookings,
        'trend_title': trend_title_map.get(trend_bucket_mode, 'Trend'),
        'trend_bucket_label': trend_bucket_label_map.get(trend_bucket_mode, 'Trend buckets'),
        'dashboard_trend_labels': chart_labels,
        'dashboard_bookings_trend': bookings_trend,
        'dashboard_revenue_trend': revenue_trend,
        'dashboard_prev_bookings_trend': prev_bookings_trend,
        'dashboard_prev_revenue_trend': prev_revenue_trend,
        'queue_breakdown': queue_breakdown,
        'dashboard_status_labels': [item['label'] for item in status_distribution],
        'dashboard_status_values': [item['count'] for item in status_distribution],
        'dashboard_status_colors': [item['color'] for item in status_distribution],
    }


def build_reports_context(request):
    start_date, end_date = _get_reporting_date_range(request)
    concern_base_qs = ConcernTicket.objects.select_related('user').filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    ).order_by('-created_at')

    status_filter = (request.GET.get('concern_status') or '').strip()
    valid_statuses = {choice[0] for choice in ConcernTicket.STATUS_CHOICES}
    if status_filter and status_filter in valid_statuses:
        concern_filtered_qs = concern_base_qs.filter(status=status_filter)
    else:
        status_filter = ''
        concern_filtered_qs = concern_base_qs

    recent_admin_notifications = AdminNotification.objects.select_related('user', 'booking').filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    ).order_by('-created_at')[:20]

    concern_count = concern_base_qs.count()
    new_count = concern_base_qs.filter(status='new').count()
    in_progress_count = concern_base_qs.filter(status='in_progress').count()
    resolved_count = concern_base_qs.filter(status='resolved').count()

    concerns_paginator = Paginator(concern_filtered_qs, 8)
    concerns_page = concerns_paginator.get_page(request.GET.get('page'))

    return {
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'date_range_days': (end_date - start_date).days + 1,
        'concern_rows': concerns_page,
        'concerns_page': concerns_page,
        'concern_status_filter': status_filter,
        'concern_records_count': concern_filtered_qs.count(),
        'total_concerns': concern_count,
        'new_concerns': new_count,
        'in_progress_concerns': in_progress_count,
        'resolved_concerns': resolved_count,
        'admin_notifications': recent_admin_notifications,
    }


@login_required
def admin_reports(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Admins only")
    return render(request, 'admin/admin_reports.html', build_reports_context(request))


@login_required
@require_POST
def admin_concern_update(request, id):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Admins only")

    ticket = get_object_or_404(ConcernTicket, id=id)
    next_url = request.POST.get('next') or reverse('admin_reports')

    raw_status = (request.POST.get('status') or '').strip()
    valid_statuses = {choice[0] for choice in ConcernTicket.STATUS_CHOICES}
    if raw_status not in valid_statuses:
        messages.error(request, "Invalid concern status selected.")
        return redirect(next_url)

    ticket.status = raw_status
    ticket.admin_notes = (request.POST.get('admin_notes') or '').strip()
    ticket.save(update_fields=['status', 'admin_notes', 'updated_at'])

    log_action(request.user, f"Updated concern #{ticket.id} to '{ticket.get_status_display()}'.")
    messages.success(request, f"Concern #{ticket.id} updated to {ticket.get_status_display()}.")
    return redirect(next_url)




@require_POST
def chat_api(request):
    """
    API endpoint for the chatbot.
    Expects JSON: { "message": "user message", "session_id": 123 }
    """
    try:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON body'}, status=400)
            
        user_message = data.get('message')
        session_id = data.get('session_id')
        
        if not user_message:
            return JsonResponse({'error': 'Message is required'}, status=400)

        # Ensure user is authenticated to use sessions properly
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=403)

        # Default receiver for AI bot
        admin_user = User.objects.filter(role='admin').first() or User.objects.filter(is_superuser=True).first()
        if not admin_user:
            return JsonResponse({'error': 'System misconfiguration (no admin found)'}, status=500)

        # Handle ChatSession
        session = None
        is_new_session = False
        if session_id:
            try:
                session = ChatSession.objects.get(id=session_id, user=request.user)
            except ChatSession.DoesNotExist:
                pass # If passed session_id is invalid, we will just create a new one

        if not session:
            # Create a new session, extracting a title from the first message
            title = user_message[:30] + '...' if len(user_message) > 30 else user_message
            session = ChatSession.objects.create(user=request.user, title=title)
            is_new_session = True

        # --- 1. FETCH CONTEXT (HISTORY) FIRST ---
        history = []
        recent_msgs = ChatMessage.objects.filter(session=session).order_by('-sent_at')[:8]
        
        # Reorder to chronological (oldest to newest) for the AI
        for msg in reversed(recent_msgs):
            role = 'user' if msg.sender == request.user else 'assistant'
            history.append({'role': role, 'content': msg.message})

        # --- 2. SAVE USER MESSAGE ---
        ChatMessage.objects.create(
            session=session,
            sender=request.user, 
            receiver=admin_user, 
            message=user_message
        )

        # Get AI Response with History
        ai_result = get_chatbot_response(user_message, conversation_history=history)
        
        # ai_result is now a dict: {'text': str, 'is_warning': bool}
        ai_text = ai_result.get('text', '')
        is_warning = ai_result.get('is_warning', False)

        if not is_warning:
            ChatMessage.objects.create(
                session=session,
                sender=admin_user, 
                receiver=request.user, 
                message=ai_text
            )

        return JsonResponse({
            'response': ai_text, 
            'is_warning': is_warning,
            'session_id': session.id,
            'is_new_session': is_new_session,
            'session_title': session.title
        })

    except Exception as e:
        print(f"Chat API Error: {e}") # Debugging
        return JsonResponse({'error': str(e)}, status=500)



@login_required
@require_GET
def chat_sessions(request):
    """
    GET endpoint to fetch all chat sessions for the current user.
    """
    sessions = ChatSession.objects.filter(user=request.user).order_by('-updated_at')
    sessions_list = []
    for s in sessions:
        sessions_list.append({
            'id': s.id,
            'title': s.title,
            'updated_at': s.updated_at.strftime('%b %d, %Y')
        })
    return JsonResponse({'sessions': sessions_list})


@login_required
def chat_history(request):
    """
    GET endpoint to fetch recent chat messages for a specific session.
    Expects ?session_id=123
    """
    session_id = request.GET.get('session_id')
    
    if not session_id:
        return JsonResponse({'messages': []})

    recent_msgs = ChatMessage.objects.filter(
        session_id=session_id,
        session__user=request.user
    ).order_by('-sent_at')[:50]
    
    messages_list = []
    for msg in reversed(list(recent_msgs)):
        role = 'user' if msg.sender == request.user else 'assistant'
        messages_list.append({
            'role': role,
            'content': msg.message,
            'sent_at': msg.sent_at.strftime('%I:%M %p'),
        })
    
    return JsonResponse({'messages': messages_list})

@login_required
@require_POST
def chat_clear(request):
    """
    POST endpoint to clear a specific chat session.
    Expects JSON: { "session_id": 123 }
    """
    try:
        data = json.loads(request.body)
        session_id = data.get('session_id')
        if session_id:
            ChatSession.objects.filter(id=session_id, user=request.user).delete()
            return JsonResponse({'success': True})
        return JsonResponse({'error': 'session_id required'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def select_design_type(request):
    if request.user.role != 'customer':
        return HttpResponseForbidden('Not allowed')
    
    # Get active packages to display as options
    active_packages = Package.objects.filter(is_active=True).order_by('price')
    
    return render(request, 'client/select_design_type.html', {
        'packages': active_packages
    })

@login_required
def my_designs_page(request):
    if request.user.role != 'customer':
        return HttpResponseForbidden('Not allowed')
    
    # Order by updated_at descending so newest are first
    designs_list = UserDesign.objects.filter(user=request.user).order_by('-updated_at')
    
    paginator = Paginator(designs_list, 10) # Show 10 designs per page
    page_number = request.GET.get('page')
    designs = paginator.get_page(page_number)
    
    # Get active packages for the "Create New Design" modal
    active_packages = Package.objects.filter(is_active=True).order_by('price')
    
    return render(request, 'client/my_designs.html', {
        'designs': designs,
        'packages': active_packages
    })

@login_required
@require_POST
def save_user_design(request):
    if request.user.role != 'customer':
        return JsonResponse({'status': 'error', 'message': 'Not allowed'}, status=403)
    
    try:
        data = json.loads(request.body)
        design_id = data.get('id')
        name = data.get('name', 'Untitled Design')
        canvas_json = data.get('canvas_json')
        thumbnail_data = data.get('thumbnail') # Base64 string

        if not canvas_json:
            return JsonResponse({'status': 'error', 'message': 'Canvas data is required'}, status=400)

        # Handle thumbnail image (Base64)
        from django.core.files.base import ContentFile
        import base64
        import uuid

        image_file = None
        if thumbnail_data and ',' in thumbnail_data:
            format, imgstr = thumbnail_data.split(';base64,') 
            ext = format.split('/')[-1] 
            image_file = ContentFile(base64.b64decode(imgstr), name=f"{uuid.uuid4().hex}.{ext}")

        if design_id:
            # Update existing
            design = get_object_or_404(UserDesign, id=design_id, user=request.user)
            if name: # Only update name if provided (don't overwrite if saving from editor)
                design.name = name
            design.canvas_json = canvas_json
            if image_file:
                design.thumbnail = image_file
            design.save()
            log_action(request.user, f"Updated custom design #{design.id}.")
        else:
            # Create new
            design = UserDesign.objects.create(
                user=request.user,
                name=name,
                canvas_json=canvas_json,
                thumbnail=image_file
            )
            log_action(request.user, f"Created new custom design #{design.id}.")

        return JsonResponse({'status': 'success', 'id': design.id, 'message': 'Design saved successfully'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
@require_POST
def rename_user_design(request, id):
    if request.user.role != 'customer':
        return JsonResponse({'status': 'error', 'message': 'Not allowed'}, status=403)
    
    try:
        design = get_object_or_404(UserDesign, id=id, user=request.user)
        data = json.loads(request.body)
        new_name = data.get('name')
        
        if not new_name or not new_name.strip():
            return JsonResponse({'status': 'error', 'message': 'Name cannot be empty'}, status=400)
            
        design.name = new_name.strip()
        design.save()
        log_action(request.user, f"Renamed custom design #{design.id} to '{design.name}'.")
        return JsonResponse({'status': 'success', 'name': design.name})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
@require_POST
def delete_user_design(request, id):
    if request.user.role != 'customer':
        return JsonResponse({'status': 'error', 'message': 'Not allowed'}, status=403)
    
    try:
        design = get_object_or_404(UserDesign, id=id, user=request.user)
        design_id_val = design.id
        design.delete()
        log_action(request.user, f"Deleted custom design #{design_id_val}.")
        return JsonResponse({'status': 'success', 'message': 'Design deleted successfully'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
def design_canvas_page(request):
    if request.user.role != 'customer':
        return HttpResponseForbidden('Not allowed')
    
    context = {}
    
    # 1. Check if we're editing an existing design
    design_id = request.GET.get('id')
    package_id = request.GET.get('package_id')
    is_custom = request.GET.get('custom') == 'true'

    if design_id:
        design = get_object_or_404(UserDesign, id=design_id, user=request.user)
        context['design'] = design
        if design.base_package:
            context['base_package'] = design.base_package
    elif package_id:
        # Starting a new design from a package
        base_package = get_object_or_404(Package, id=package_id)
        context['base_package'] = base_package
        # We don't save a UserDesign yet, we just pass the info to the frontend
    elif is_custom:
        # Starting a blank custom design
        pass
    else:
        # No ID and no package_id and no custom flag -> Redirect to selection
        return redirect('select_design_type')
        
    # 2. Extract quotas if there is a base package (simple text parsing of features)
    quotas = {}
    if 'base_package' in context:
        bp = context['base_package']
        for feature in bp.feature_list():
            # e.g., "1 Backdrop", "50 Balloons"
            # Very simple parser: take the first number as the quantity, the rest as the category/keyword
            match = re.search(r'^(\d+)\s+(.+)$', feature.strip(), re.IGNORECASE)
            if match:
                qty = int(match.group(1))
                item_name = match.group(2).strip()
                # Use a normalized key (lowercase) to match against frontend categories
                quotas[item_name.lower()] = qty

    # Pass quotas as JSON string
    context['package_quotas'] = json.dumps(quotas)

    # 3. Fetch AddOn prices to calculate visual cart
    addons = AddOn.objects.filter(is_active=True)
    addon_prices = {}
    for addon in addons:
        addon_prices[addon.name.lower()] = str(addon.price)
    
    context['addon_prices'] = json.dumps(addon_prices)
    
    categories = ['Backdrops', 'Balloons', 'Furniture', 'Decorations']
    context['categories'] = categories
    context['canvas_categories'] = (
        CanvasCategory.objects.filter(is_active=True)
        .prefetch_related('labels', 'assets__label_ref')
        .order_by('order', 'name')
    )
    
    return render(request, 'client/design_canvas.html', context)


# =========================================
# ADMIN GALLERY MANAGEMENT
# =========================================

@login_required
def admin_gallery(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    categories = GalleryCategory.objects.all()
    selected_image_category = request.GET.get('image_category', 'all')
    gallery_images = GalleryImage.objects.select_related('category').all()

    if selected_image_category != 'all':
        try:
            category_id = int(selected_image_category)
            gallery_images = gallery_images.filter(category_id=category_id)
        except (TypeError, ValueError):
            selected_image_category = 'all'

    paginator = Paginator(gallery_images, 5)
    page_number = request.GET.get('page')
    gallery_images = paginator.get_page(page_number)

    return render(request, 'admin/gallery/admin_gallery.html', {
        'categories': categories,
        'gallery_images': gallery_images,
        'selected_image_category': selected_image_category,
    })


@login_required
def admin_gallery_category_create(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        order = request.POST.get('order', 0)
        if not name:
            messages.error(request, 'Category name is required.')
            return render(request, 'admin/gallery/gallery_category_form.html')
        GalleryCategory.objects.create(name=name, order=int(order) if order else 0)
        log_action(request.user, f"Created gallery category '{name}'.")
        messages.success(request, 'Category created successfully.')
        return redirect('admin_gallery')
    return render(request, 'admin/gallery/gallery_category_form.html')


@login_required
def admin_gallery_category_edit(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    category = get_object_or_404(GalleryCategory, id=id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        order = request.POST.get('order', 0)
        if not name:
            messages.error(request, 'Category name is required.')
            return render(request, 'admin/gallery/gallery_category_form.html', {'category': category})
        category.name = name
        category.order = int(order) if order else 0
        category.save()
        log_action(request.user, f"Updated gallery category '{name}'.")
        messages.success(request, 'Category updated successfully.')
        return redirect('admin_gallery')
    return render(request, 'admin/gallery/gallery_category_form.html', {'category': category})


@login_required
def admin_gallery_category_delete(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    category = get_object_or_404(GalleryCategory, id=id)
    cat_name = category.name
    category.delete()
    log_action(request.user, f"Deleted gallery category '{cat_name}'.")
    messages.success(request, 'Category deleted successfully.')
    return redirect('admin_gallery')


@login_required
def admin_gallery_image_create(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    categories = GalleryCategory.objects.all()
    if request.method == 'POST':
        category_id = request.POST.get('category')
        caption = request.POST.get('caption', '').strip()
        image = request.FILES.get('image')
        if not category_id or not image:
            messages.error(request, 'Category and image are required.')
            return render(request, 'admin/gallery/gallery_image_form.html', {'categories': categories})
        category = get_object_or_404(GalleryCategory, id=category_id)
        GalleryImage.objects.create(category=category, image=image, caption=caption)
        log_action(request.user, f"Added gallery image to '{category.name}'.")
        messages.success(request, 'Image added successfully.')
        return redirect('admin_gallery')
    return render(request, 'admin/gallery/gallery_image_form.html', {'categories': categories})


@login_required
def admin_gallery_image_edit(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    gallery_image = get_object_or_404(GalleryImage, id=id)
    categories = GalleryCategory.objects.all()
    next_url = request.GET.get('next') or request.POST.get('next') or ''
    scroll_target = request.GET.get('scroll_target') or request.POST.get('scroll_target') or ''
    if request.method == 'POST':
        category_id = request.POST.get('category')
        caption = request.POST.get('caption', '').strip()
        new_image = request.FILES.get('image')
        is_active = request.POST.get('is_active') == 'on'
        if not category_id:
            messages.error(request, 'Category is required.')
            return render(request, 'admin/gallery/gallery_image_form.html', {
                'gallery_image': gallery_image,
                'categories': categories,
                'next_url': next_url,
                'scroll_target': scroll_target
            })
        gallery_image.category = get_object_or_404(GalleryCategory, id=category_id)
        gallery_image.caption = caption
        gallery_image.is_active = is_active
        if new_image:
            gallery_image.image = new_image
        gallery_image.save()
        log_action(request.user, f"Updated gallery image #{gallery_image.id}.")
        messages.success(request, 'Image updated successfully.')
        if next_url.startswith('/'):
            if scroll_target:
                separator = '&' if '?' in next_url else '?'
                return redirect(f"{next_url}{separator}scroll={scroll_target}")
            return redirect(next_url)
        return redirect('admin_gallery')
    return render(request, 'admin/gallery/gallery_image_form.html', {
        'gallery_image': gallery_image,
        'categories': categories,
        'next_url': next_url,
        'scroll_target': scroll_target
    })


@login_required
def admin_gallery_image_detail(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    gallery_image = get_object_or_404(GalleryImage.objects.select_related('category'), id=id)
    next_url = request.GET.get('next') or '/staff/gallery/?scroll=gallery-images-section'
    scroll_target = request.GET.get('scroll_target') or 'gallery-images-section'
    if not str(next_url).startswith('/'):
        next_url = '/staff/gallery/?scroll=gallery-images-section'
    if scroll_target and 'scroll=' not in next_url:
        separator = '&' if '?' in next_url else '?'
        next_url = f"{next_url}{separator}scroll={scroll_target}"

    return render(request, 'admin/gallery/gallery_image_detail.html', {
        'gallery_image': gallery_image,
        'next_url': next_url,
    })


@login_required
def admin_gallery_image_delete(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    gallery_image = get_object_or_404(GalleryImage, id=id)
    img_id = gallery_image.id
    gallery_image.image.delete()  # Delete file from storage
    gallery_image.delete()
    log_action(request.user, f"Deleted gallery image #{img_id}.")
    messages.success(request, 'Image deleted successfully.')
    return redirect('admin_gallery')


# =========================================
# ADMIN CANVAS ASSET MANAGEMENT
# =========================================

@login_required
def admin_canvas_assets(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    categories = CanvasCategory.objects.order_by('order', 'name')
    labels = CanvasLabel.objects.select_related('category').order_by('category__order', 'order', 'name')
    selected_asset_category = request.GET.get('asset_category', 'all')
    selected_asset_label = request.GET.get('asset_label', 'all')
    canvas_assets = CanvasAsset.objects.select_related('category', 'label_ref').all()
    parsed_category_id = None

    if selected_asset_category != 'all':
        try:
            parsed_category_id = int(selected_asset_category)
            canvas_assets = canvas_assets.filter(category_id=parsed_category_id)
        except (TypeError, ValueError):
            selected_asset_category = 'all'
            parsed_category_id = None

    if selected_asset_label != 'all':
        try:
            label_id = int(selected_asset_label)
            label_obj = labels.filter(id=label_id).first()
            # Guard against invalid category+label combinations from manual URL edits.
            if not label_obj or (parsed_category_id is not None and label_obj.category_id != parsed_category_id):
                selected_asset_label = 'all'
            else:
                canvas_assets = canvas_assets.filter(label_ref_id=label_id)
        except (TypeError, ValueError):
            selected_asset_label = 'all'

    categories_paginator = Paginator(categories, 10)
    categories_page = categories_paginator.get_page(request.GET.get('cat_page'))

    labels_paginator = Paginator(labels, 10)
    labels_page = labels_paginator.get_page(request.GET.get('lbl_page'))

    assets_paginator = Paginator(canvas_assets, 8)
    canvas_assets = assets_paginator.get_page(request.GET.get('page'))

    return render(request, 'admin/canvas/admin_canvas_assets.html', {
        'categories': categories,
        'labels': labels,
        'categories_page': categories_page,
        'labels_page': labels_page,
        'canvas_assets': canvas_assets,
        'selected_asset_category': selected_asset_category,
        'selected_asset_label': selected_asset_label,
    })


@login_required
def admin_canvas_category_create(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        order = request.POST.get('order', 1)
        is_active = request.POST.get('is_active') == 'on'
        if not name:
            messages.warning(request, 'Please enter a category name before saving.')
            return render(request, 'admin/canvas/canvas_category_form.html')
        CanvasCategory.objects.create(name=name, order=int(order) if order else 1, is_active=is_active)
        log_action(request.user, f"Created canvas category '{name}'.")
        messages.success(request, 'Canvas category created successfully.')
        return redirect('admin_canvas_assets')
    return render(request, 'admin/canvas/canvas_category_form.html')


@login_required
def admin_canvas_category_edit(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    category = get_object_or_404(CanvasCategory, id=id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        order = request.POST.get('order', 1)
        is_active = request.POST.get('is_active') == 'on'
        if not name:
            messages.warning(request, 'Please enter a category name before saving.')
            return render(request, 'admin/canvas/canvas_category_form.html', {'category': category})
        category.name = name
        category.order = int(order) if order else 1
        category.is_active = is_active
        category.save()
        log_action(request.user, f"Updated canvas category '{name}'.")
        messages.success(request, 'Canvas category updated successfully.')
        return redirect('admin_canvas_assets')
    return render(request, 'admin/canvas/canvas_category_form.html', {'category': category})


@login_required
def admin_canvas_category_delete(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    category = get_object_or_404(CanvasCategory, id=id)
    cat_name = category.name
    category.delete()
    log_action(request.user, f"Deleted canvas category '{cat_name}'.")
    messages.success(request, 'Canvas category deleted successfully.')
    return redirect('admin_canvas_assets')


@login_required
def admin_canvas_label_create(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    categories = CanvasCategory.objects.order_by('order', 'name')
    if request.method == 'POST':
        category_id = request.POST.get('category')
        name = request.POST.get('name', '').strip()
        order = request.POST.get('order', 1)
        is_active = request.POST.get('is_active') == 'on'
        if not category_id:
            messages.warning(request, 'Please select a category for this label.')
            return render(request, 'admin/canvas/canvas_label_form.html', {'categories': categories})
        if not name:
            messages.warning(request, 'Please enter a label name before saving.')
            return render(request, 'admin/canvas/canvas_label_form.html', {'categories': categories})

        category = CanvasCategory.objects.filter(id=category_id).first()
        if not category:
            messages.warning(request, 'Selected category could not be found. Please choose another category.')
            return render(request, 'admin/canvas/canvas_label_form.html', {'categories': categories})
        CanvasLabel.objects.create(
            category=category,
            name=name,
            order=int(order) if order else 1,
            is_active=is_active,
        )
        log_action(request.user, f"Created canvas label '{name}' in '{category.name}'.")
        messages.success(request, 'Canvas label created successfully.')
        return redirect('admin_canvas_assets')
    return render(request, 'admin/canvas/canvas_label_form.html', {'categories': categories})


@login_required
def admin_canvas_label_edit(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    label = get_object_or_404(CanvasLabel, id=id)
    categories = CanvasCategory.objects.order_by('order', 'name')
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        order = request.POST.get('order', 1)
        is_active = request.POST.get('is_active') == 'on'
        if not name:
            messages.warning(request, 'Please enter a label name before saving.')
            return render(request, 'admin/canvas/canvas_label_form.html', {'label': label, 'categories': categories})
        label.name = name
        label.order = int(order) if order else 1
        label.is_active = is_active
        label.save()
        log_action(request.user, f"Updated canvas label '{name}'.")
        messages.success(request, 'Canvas label updated successfully.')
        return redirect('admin_canvas_assets')
    return render(request, 'admin/canvas/canvas_label_form.html', {'label': label, 'categories': categories})


@login_required
def admin_canvas_label_delete(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")
    label = get_object_or_404(CanvasLabel, id=id)
    label_name = label.name
    CanvasAsset.objects.filter(label_ref=label).update(label_ref=None)
    label.delete()
    log_action(request.user, f"Deleted canvas label '{label_name}'.")
    messages.success(request, 'Canvas label deleted successfully.')
    return redirect('admin_canvas_assets')


@login_required
def admin_canvas_asset_create(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    categories = CanvasCategory.objects.order_by('order', 'name')
    labels = CanvasLabel.objects.select_related('category').order_by('category__order', 'order', 'name')
    if request.method == 'POST':
        category_id = request.POST.get('category')
        label_id = request.POST.get('label_ref')
        label = request.POST.get('label', '').strip()
        static_path = ''
        item_type = 'image'
        image = request.FILES.get('image')
        width = request.POST.get('width', '150')
        height = request.POST.get('height', '150')
        is_active = request.POST.get('is_active') == 'on'

        if not category_id:
            messages.warning(request, 'Please select a category for this asset.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {'categories': categories, 'labels': labels})

        if not label_id:
            messages.warning(request, 'Please select a label group for this asset.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {'categories': categories, 'labels': labels})

        if not label:
            messages.warning(request, 'Please enter an asset name before saving.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {'categories': categories, 'labels': labels})

        if not image:
            messages.warning(request, 'Please upload an image file for this asset.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {'categories': categories, 'labels': labels})

        try:
            width_val = int(width)
            height_val = int(height)
        except ValueError:
            messages.warning(request, 'Default width and height must be valid whole numbers.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {'categories': categories, 'labels': labels})

        if width_val < 1:
            messages.warning(request, 'Default width must be at least 1.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {'categories': categories, 'labels': labels})

        if height_val < 1:
            messages.warning(request, 'Default height must be at least 1.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {'categories': categories, 'labels': labels})

        category = CanvasCategory.objects.filter(id=category_id).first()
        if not category:
            messages.warning(request, 'Selected category could not be found. Please choose another category.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {'categories': categories, 'labels': labels})

        label_obj = CanvasLabel.objects.filter(id=label_id, category=category).first()
        if not label_obj:
            messages.warning(request, 'Selected label group is invalid for the chosen category.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {'categories': categories, 'labels': labels})

        next_sort = (CanvasAsset.objects.filter(label_ref=label_obj).aggregate(max_sort=Max('sort_order'))['max_sort'] or 0) + 1
        CanvasAsset.objects.create(
            category=category,
            label_ref=label_obj,
            label=label,
            subgroup=label_obj.name,
            static_path=static_path,
            item_type=item_type,
            image=image,
            width=width_val,
            height=height_val,
            sort_order=next_sort,
            is_active=is_active,
        )
        log_action(request.user, f"Added canvas asset '{label}' to '{category.name}'.")
        messages.success(request, 'Canvas asset added successfully.')
        return redirect('admin_canvas_assets')

    return render(request, 'admin/canvas/canvas_asset_form.html', {'categories': categories, 'labels': labels})


@login_required
def admin_canvas_asset_edit(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    canvas_asset = get_object_or_404(CanvasAsset, id=id)
    categories = CanvasCategory.objects.order_by('order', 'name')
    labels = CanvasLabel.objects.select_related('category').order_by('category__order', 'order', 'name')
    next_url = request.GET.get('next') or request.POST.get('next') or ''
    scroll_target = request.GET.get('scroll_target') or request.POST.get('scroll_target') or ''

    if request.method == 'POST':
        category_id = request.POST.get('category')
        label_id = request.POST.get('label_ref')
        label = request.POST.get('label', '').strip()
        static_path = canvas_asset.static_path or ''
        item_type = canvas_asset.item_type or 'image'
        new_image = request.FILES.get('image')
        width = request.POST.get('width', '150')
        height = request.POST.get('height', '150')
        is_active = request.POST.get('is_active') == 'on'

        if not category_id:
            messages.warning(request, 'Please select a category for this asset.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {
                'canvas_asset': canvas_asset,
                'categories': categories,
                'labels': labels,
                'next_url': next_url,
                'scroll_target': scroll_target,
            })

        if not label_id:
            messages.warning(request, 'Please select a label group for this asset.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {
                'canvas_asset': canvas_asset,
                'categories': categories,
                'labels': labels,
                'next_url': next_url,
                'scroll_target': scroll_target,
            })

        if not label:
            messages.warning(request, 'Please enter an asset name before saving.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {
                'canvas_asset': canvas_asset,
                'categories': categories,
                'labels': labels,
                'next_url': next_url,
                'scroll_target': scroll_target,
            })

        if not new_image and not canvas_asset.image and not canvas_asset.static_path:
            messages.warning(request, 'Please upload an image file for this asset.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {
                'canvas_asset': canvas_asset,
                'categories': categories,
                'labels': labels,
                'next_url': next_url,
                'scroll_target': scroll_target,
            })

        try:
            width_val = int(width)
            height_val = int(height)
        except ValueError:
            messages.warning(request, 'Default width and height must be valid whole numbers.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {
                'canvas_asset': canvas_asset,
                'categories': categories,
                'labels': labels,
                'next_url': next_url,
                'scroll_target': scroll_target,
            })

        if width_val < 1:
            messages.warning(request, 'Default width must be at least 1.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {
                'canvas_asset': canvas_asset,
                'categories': categories,
                'labels': labels,
                'next_url': next_url,
                'scroll_target': scroll_target,
            })

        if height_val < 1:
            messages.warning(request, 'Default height must be at least 1.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {
                'canvas_asset': canvas_asset,
                'categories': categories,
                'labels': labels,
                'next_url': next_url,
                'scroll_target': scroll_target,
            })

        category = CanvasCategory.objects.filter(id=category_id).first()
        if not category:
            messages.warning(request, 'Selected category could not be found. Please choose another category.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {
                'canvas_asset': canvas_asset,
                'categories': categories,
                'labels': labels,
                'next_url': next_url,
                'scroll_target': scroll_target,
            })

        label_obj = CanvasLabel.objects.filter(id=label_id, category=category).first()
        if not label_obj:
            messages.warning(request, 'Selected label group is invalid for the chosen category.')
            return render(request, 'admin/canvas/canvas_asset_form.html', {
                'canvas_asset': canvas_asset,
                'categories': categories,
                'labels': labels,
                'next_url': next_url,
                'scroll_target': scroll_target,
            })

        canvas_asset.category = category
        canvas_asset.label_ref = label_obj
        canvas_asset.label = label
        canvas_asset.subgroup = label_obj.name
        canvas_asset.static_path = static_path
        canvas_asset.item_type = item_type
        canvas_asset.width = width_val
        canvas_asset.height = height_val
        canvas_asset.is_active = is_active
        if new_image:
            canvas_asset.image = new_image
        canvas_asset.save()

        log_action(request.user, f"Updated canvas asset #{canvas_asset.id}.")
        messages.success(request, 'Canvas asset updated successfully.')
        if next_url.startswith('/'):
            if scroll_target:
                separator = '&' if '?' in next_url else '?'
                return redirect(f"{next_url}{separator}scroll={scroll_target}")
            return redirect(next_url)
        return redirect('admin_canvas_assets')

    return render(request, 'admin/canvas/canvas_asset_form.html', {
        'canvas_asset': canvas_asset,
        'categories': categories,
        'labels': labels,
        'next_url': next_url,
        'scroll_target': scroll_target,
    })


@login_required
def admin_canvas_asset_detail(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    canvas_asset = get_object_or_404(CanvasAsset.objects.select_related('category', 'label_ref'), id=id)
    next_url = request.GET.get('next') or '/staff/canvas-assets/?scroll=canvas-assets-list-section'
    scroll_target = request.GET.get('scroll_target') or 'canvas-assets-list-section'
    if not str(next_url).startswith('/'):
        next_url = '/staff/canvas-assets/?scroll=canvas-assets-list-section'
    if scroll_target and 'scroll=' not in next_url:
        separator = '&' if '?' in next_url else '?'
        next_url = f"{next_url}{separator}scroll={scroll_target}"

    return render(request, 'admin/canvas/canvas_asset_detail.html', {
        'canvas_asset': canvas_asset,
        'next_url': next_url,
    })


@login_required
def admin_canvas_asset_delete(request, id):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    canvas_asset = get_object_or_404(CanvasAsset, id=id)
    asset_id = canvas_asset.id
    canvas_asset.delete()
    log_action(request.user, f"Deleted canvas asset #{asset_id}.")
    messages.success(request, 'Canvas asset deleted successfully.')
    return redirect('admin_canvas_assets')


