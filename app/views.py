from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count
from django.http import HttpResponseForbidden
from django.views.generic import TemplateView
from django.contrib import messages
from .models import Package, Booking, User, AuditLog, Design, Payment, ChatSession, ChatMessage, Review, ReviewImage, AddOn, AdditionalOnly, Notification, AdminNotification
from django.contrib.auth import get_user_model
import re
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from decimal import Decimal, InvalidOperation
from django.http import JsonResponse
from django.utils import timezone
from datetime import datetime, timedelta
from django.views.decorators.http import require_POST, require_GET
import json
from .services import get_chatbot_response
from django.db.models import Exists, OuterRef
from django.utils import timezone





def log_action(user, action):
    """Helper function to create an audit log entry."""
    AuditLog.objects.create(user=user, action=action)


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
            
        if len(top_reviews) >= 3:
            break
            
    return top_reviews

class HomePageView(TemplateView):
    template_name = 'client/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['top_reviews'] = get_top_reviews()
        return context

class AboutPageView(TemplateView):
    template_name = 'client/about.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['top_reviews'] = get_top_reviews()
        return context
    

class ServicesPageView(TemplateView):
    template_name = 'client/services.html'
    
    
class PackagePageView(TemplateView):
    template_name = 'client/package.html'


class GalleryPageView(TemplateView):
    template_name = 'client/gallery.html'
    

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
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        phone = request.POST.get('phone')
        role = 'customer'

        errors = []

        # ✅ Required fields
        if not first_name:
            errors.append("First name is required.")
        if not last_name:
            errors.append("Last name is required.")
        if not username:
            errors.append("Username is required.")
        if not email:
            errors.append("Email is required.")
        if not password:
            errors.append("Password is required.")
        if not confirm_password:
            errors.append("Confirm password is required.")

        # ✅ Email unique
        if User.objects.filter(email=email).exists():
            errors.append("Email already exists.")

        # ✅ Username unique
        if User.objects.filter(username=username).exists():
            errors.append("Username already exists.")

        # ✅ Password match
        if password != confirm_password:
            errors.append("Passwords do not match.")

        # ✅ Password rules
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")

        # ✅ Phone number validation
        if phone:
            cleaned_phone = re.sub(r'[\s\-\(\)\+]', '', phone)
            if not cleaned_phone.isdigit():
                errors.append("Phone number must contain only digits.")
            elif len(cleaned_phone) < 10 or len(cleaned_phone) > 15:
                errors.append("Phone number must be between 10 and 15 digits.")

        # ❌ If may error, balik form
        if errors:
            return render(request, 'auth/register.html', {'errors': errors})

        # ✅ Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            phone_number=phone,
            role=role
        )

        log_action(None, f"New user '{username}' registered.")

        return redirect('login')

    return render(request, 'auth/register.html')



User = get_user_model()

def user_login(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')

        # Try to get user by email
        try:
            user_obj = User.objects.get(email=email)
            username = user_obj.username  # Django authenticate needs username
        except User.DoesNotExist:
            return render(request, 'auth/login.html', {'error': 'Invalid email or password.'})

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)

            log_action(user, "User logged in.")

            if request.POST.get('remember_me'):
                request.session.set_expiry(1209600)  # 2 weeks
            else:
                request.session.set_expiry(0)  # browser close

            if user.role == 'customer':
                return redirect('home')
            elif user.role in ['admin', 'staff']:
                return redirect('dashboard')
        else:
            return render(request, 'auth/login.html', {'error': 'Invalid email or password.'})

    return render(request, 'auth/login.html')



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
    return render(request, 'admin/dashboard.html')


def check_booking_expirations():
    """Find pending bookings past their event date, mark as expired and notify user."""
    expired_bookings = Booking.objects.filter(status='pending', event_date__lt=timezone.now().date())
    for b in expired_bookings:
        b.status = 'expired'
        b.save()
        Notification.objects.create(
            user=b.user,
            booking=b,
            message=f"Paumanhin, ang iyong booking #{b.id} para sa {b.event_date} ay na-expire na dahil hindi ito nakumpirma sa tamang oras."
        )


@login_required
def customer_profile(request):
    if request.user.role != 'customer':
        return HttpResponseForbidden("Not allowed")

    # Auto-expire pending bookings in the past
    check_booking_expirations()

    user_bookings = Booking.objects.filter(user=request.user).order_by('-event_date')
    
    # Attach formatted time range for the table/modal and check if reviewed
    for b in user_bookings:
        b.time_range_display = get_booking_time_range(b)
        if b.status == 'completed':
            b.has_reviewed = b.reviews.filter(user=request.user).exists()
        else:
            b.has_reviewed = False

    # Calculate Stats
    total_bookings = user_bookings.count()
    pending_count = user_bookings.filter(status='pending').count()
    confirmed_count = user_bookings.filter(status='confirmed').count()
    completed_count = user_bookings.filter(status='completed').count()

    # Get active packages for the edit modal dropdown
    active_packages = Package.objects.filter(is_active=True)

    return render(request, 'client/customer_profile.html', {
        'user_bookings': user_bookings,
        'total_bookings': total_bookings,
        'pending_count': pending_count,
        'confirmed_count': confirmed_count,
        'completed_count': completed_count,
        'packages': active_packages,
    })

@login_required
@require_POST
def submit_review(request, id):
    if request.user.role != 'customer':
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking, id=id, user=request.user)

    if booking.status != 'completed':
        messages.error(request, "You can only review completed bookings.")
        return redirect('customer_profile')

    # Check if already reviewed
    if booking.reviews.filter(user=request.user).exists():
        messages.error(request, "You have already reviewed this booking.")
        return redirect('customer_profile')

    rating = request.POST.get('rating')
    comment = request.POST.get('comment')

    if rating and comment:
        # Validate rating range
        try:
            rating_val = int(rating)
        except (ValueError, TypeError):
            messages.error(request, "Invalid rating value.")
            return redirect('customer_profile')
        if rating_val < 1 or rating_val > 5:
            messages.error(request, "Rating must be between 1 and 5.")
            return redirect('customer_profile')

        images = request.FILES.getlist('images')
        
        if len(images) > 4:
            messages.error(request, "You can only upload a maximum of 4 pictures.")
            return redirect('customer_profile')

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
        return redirect('reviews')  # Redirect to the new reviews page
    else:
        messages.error(request, "Please provide both a rating and a comment.")

    return redirect('customer_profile')


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

# Helper to remove existing End Time tag to prevent duplication
def remove_end_time_tag(text):
    if not text: return ""
    return re.sub(r'\s*\(End Time: \d{2}:\d{2}\)', '', text).strip()

# Helper to format full time range string (e.g., "10:00 AM - 12:00 PM")
def get_booking_time_range(booking):
    if not booking.event_time:
        return ""
    start_str = booking.event_time.strftime("%I:%M %p")
    end_time_str = get_end_time_from_str(booking.special_requests or '')
    if end_time_str:
        try:
            end_time_obj = datetime.strptime(end_time_str, '%H:%M').time()
            end_str = end_time_obj.strftime("%I:%M %p")
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
                messages.error(request, "Cannot book a date in the past.")
                return redirect('booking_page')
            
            # 2. Past Time Check (If booking is Today)
            if booking_date == today and start_time:
                booking_time = datetime.strptime(start_time, '%H:%M').time()
                if booking_time < now.time():
                    messages.error(request, "Cannot book a time in the past.")
                    return redirect('booking_page')

            # 3. Double Booking / Overlap Check
            if start_time and end_time:
                new_start = datetime.combine(booking_date, datetime.strptime(start_time, '%H:%M').time())
                new_end = datetime.combine(booking_date, datetime.strptime(end_time, '%H:%M').time())
                
                # Get active bookings for this date
                existing_bookings = Booking.objects.filter(event_date=booking_date).exclude(status__in=['cancelled', 'denied'])
                
                for b in existing_bookings:
                    b_start = datetime.combine(booking_date, b.event_time)
                    # Extract end time from stored string or default to +4 hours
                    b_end_str = get_end_time_from_str(b.special_requests)
                    if b_end_str:
                        b_end = datetime.combine(booking_date, datetime.strptime(b_end_str, '%H:%M').time())
                    else:
                        b_end = b_start + timedelta(hours=4) # Default duration assumption
                    
                    # Check for Overlap: (StartA < EndB) and (EndA > StartB)
                    if new_start < b_end and new_end > b_start:
                        messages.error(request, f"Time slot unavailable. Overlaps with an existing booking ({b.event_time.strftime('%H:%M')} - {b_end.strftime('%H:%M')}).")
                        return redirect('booking_page')

        # 4. Validate total_price
        try:
            total_price_val = Decimal(request.POST.get('total_price', '0'))
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return redirect('booking_page')
        if total_price_val <= 0:
            messages.error(request, "Total price must be greater than 0.")
            return redirect('booking_page')
        MAX_PRICE = Decimal('99999999.99')
        if total_price_val > MAX_PRICE:
            messages.error(request, "Total price exceeds the maximum allowed value.")
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
        log_action(request.user, f"Created a new booking #{booking.id}.")

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

    # ❌ Dapat pwede mag-edit ONLY kapag:
    # 1) pending OR
    # 2) edit_allowed = True
    if not (booking.status == 'pending' or booking.edit_allowed):
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
            
            existing_bookings = Booking.objects.filter(event_date=booking_date).exclude(id=booking.id).exclude(status__in=['cancelled', 'denied'])
            for b in existing_bookings:
                b_start = datetime.combine(booking_date, b.event_time)
                b_end_str = get_end_time_from_str(b.special_requests)
                b_end = datetime.combine(booking_date, datetime.strptime(b_end_str, '%H:%M').time()) if b_end_str else b_start + timedelta(hours=4)
                
                if new_start < b_end and new_end > b_start:
                    messages.error(request, f"Time slot overlap with existing booking.")
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

        booking.edit_allowed = False  # ❗ after editing, turn off
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

    return render(request, 'admin/booking/admin_booking_detail.html', {
        'booking': booking,
        'cleaned_requests': cleaned_requests,
    })


@login_required
def admin_booking_action(request, id, action):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    booking = get_object_or_404(Booking, id=id)

    if action == 'confirm':
        booking.status = 'confirmed'
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
        booking.status = 'cancelled'
        booking.save()
        
        # Notify Customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=f"We're sorry, but your booking #{booking.id} was NOT approved. Please check your profile for more details."
        )
        log_action(request.user, f"Denied booking #{booking.id} for '{booking.user.username}'.")
        messages.success(request, "Booking denied!")
    elif action == 'complete':
        booking.status = 'completed'
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

    if booking.status not in ['pending', 'confirmed']:
        messages.error(request, "You cannot cancel this booking.")
        return redirect('customer_profile')

    booking.status = 'cancel_requested'
    booking.save()

    log_action(request.user, f"Requested to cancel booking #{booking.id}.")
    
    # Notify Admin
    AdminNotification.objects.create(
        booking=booking,
        user=request.user,
        message="requested to cancel their booking."
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
        log_action(request.user, f"Approved cancellation request for booking #{booking.id}.")
        
        # Notify Customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=f"Your cancellation request for booking #{booking.id} has been APPROVED. 👍"
        )
        messages.success(request, "Cancel approved.")
    elif action == 'deny':
        booking.status = 'confirmed'
        log_action(request.user, f"Denied cancellation request for booking #{booking.id}.")
        
        # Notify Customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=f"We're sorry, but your cancellation request for booking #{booking.id} was NOT approved."
        )
        messages.success(request, "Cancel denied.")

    booking.save()
    return redirect('admin_booking_list')


@login_required
def request_edit_booking(request, id):
    booking = get_object_or_404(Booking, id=id, user=request.user)

    if booking.status != 'confirmed':
        messages.error(request, "Only confirmed bookings can request edit.")
        return redirect('customer_profile')

    booking.edit_requested = True
    booking.save()
    log_action(request.user, f"Requested to edit booking #{booking.id}.")
    
    # Notify Admin
    AdminNotification.objects.create(
        booking=booking,
        user=request.user,
        message="requested to edit their booking."
    )
    
    messages.success(request, "Edit request sent.")
    return redirect('customer_profile')


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
        booking.edit_allowed = True
        log_action(request.user, f"Approved edit request for booking #{booking.id}.")
        
        # Notify Customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=f"Your edit request for booking #{booking.id} has been APPROVED. You can now update your booking details! ✅"
        )
        messages.success(request, "Edit approved. The customer can now edit the booking.")
    elif action == 'deny':
        booking.edit_requested = False
        booking.edit_allowed = False
        log_action(request.user, f"Denied edit request for booking #{booking.id}.")
        
        # Notify Customer
        Notification.objects.create(
            user=booking.user,
            booking=booking,
            message=f"We're sorry, but your edit request for booking #{booking.id} was NOT approved."
        )
        messages.success(request, "Edit denied.")

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
        user_obj.first_name = request.POST.get('first_name')
        user_obj.last_name = request.POST.get('last_name')
        user_obj.email = request.POST.get('email')
        user_obj.phone_number = request.POST.get('phone_number')
        user_obj.role = request.POST.get('role')

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
        try:
            price = Decimal(request.POST['price'])
            service_charge = Decimal(request.POST.get('service_charge', 0))
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(request, 'admin/package/package_form.html')

        MAX_PRICE = Decimal('99999999.99')
        if price < 0 or price > MAX_PRICE or service_charge < 0 or service_charge > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(request, 'admin/package/package_form.html')

        package = Package.objects.create(
            name=request.POST.get('name'),
            image=request.FILES.get('image'),
            features=request.POST.get('features'),
            price=price,
            service_charge=service_charge,
            notes=request.POST.get('notes'),
            service_features=request.POST.get('service_features'),
            service_notes=request.POST.get('service_notes'),
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
        try:
            package.price = Decimal(request.POST['price'])
            package.service_charge = Decimal(request.POST.get('service_charge', 0))
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(request, 'admin/package/package_form.html', {'package': package})

        MAX_PRICE = Decimal('99999999.99')
        if package.price < 0 or package.price > MAX_PRICE or package.service_charge < 0 or package.service_charge > MAX_PRICE:
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(request, 'admin/package/package_form.html', {'package': package})

        package.name = request.POST.get('name')
        package.features = request.POST.get('features')
        package.notes = request.POST.get('notes')
        package.service_features = request.POST.get('service_features')
        package.service_notes = request.POST.get('service_notes')
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

    return render(request, 'admin/package/package_list.html', {
        'packages': packages,
        'addons': addons,
        'additionals': additionals
    })
    
    
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

    return render(request, 'client/package.html', {
        'packages': packages,
        'addons': addons,
        'additionals': additionals
    })



from decimal import Decimal, InvalidOperation

@login_required
def admin_addon_create(request):
    if request.user.role not in ['admin', 'staff']:
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST":
        try:
            price = Decimal(request.POST['price'])
            solo_raw = request.POST.get('solo_price')
            solo_price = Decimal(solo_raw) if solo_raw else None
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(request, 'admin/package/addon_form.html')

        MAX_PRICE = Decimal('99999999.99')
        if price < 0 or price > MAX_PRICE or (solo_price is not None and (solo_price < 0 or solo_price > MAX_PRICE)):
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(request, 'admin/package/addon_form.html')

        addon = AddOn.objects.create(
            name=request.POST.get('name'),
            image=request.FILES.get('image'),
            price=price,              
            solo_price=solo_price,    
            features=request.POST.get('features'),
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
        try:
            addon.price = Decimal(request.POST['price'])
            solo_raw = request.POST.get('solo_price')
            addon.solo_price = Decimal(solo_raw) if solo_raw else None
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return render(request, 'admin/package/addon_form.html', {'addon': addon})

        MAX_PRICE = Decimal('99999999.99')
        if addon.price < 0 or addon.price > MAX_PRICE or (addon.solo_price is not None and (addon.solo_price < 0 or addon.solo_price > MAX_PRICE)):
            messages.error(request, "Price must be between 0 and 99,999,999.99.")
            return render(request, 'admin/package/addon_form.html', {'addon': addon})

        addon.name = request.POST.get('name')
        addon.features = request.POST.get('features')
        
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
            features=request.POST.get('features'),
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
        additional.features = request.POST.get('features')
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
@login_required
def admin_reports(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden("Admins only")

    # 1. Date Filtering
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    # Default to last 30 days if no date is provided
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

    # Base Queryset filtered by date
    filtered_bookings = Booking.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )

    # 2. Total Revenue (Sum of total_price for completed bookings in range)
    revenue_data = filtered_bookings.filter(status='completed').aggregate(Sum('total_price'))
    total_revenue = revenue_data['total_price__sum'] or 0

    # 3. Total Bookings in range
    total_bookings = filtered_bookings.count()

    # 4. Active Users (Total customers ever, usually not date-filtered but can be)
    active_users = User.objects.filter(role='customer', is_active=True).count()

    # 5. Pending Requests in range
    pending_requests = filtered_bookings.filter(status='pending').count()

    # 6. Revenue by Event Type (for Chart)
    revenue_by_event = filtered_bookings.filter(status='completed').values('event_type').annotate(total=Sum('total_price')).order_by('-total')
    
    # 7. Booking Status Distribution (for Chart)
    status_colors_map = {
        'completed': '#10b981',
        'confirmed': '#3b82f6',
        'pending': '#f59e0b',
        'cancelled': '#ef4444',
        'denied': '#ef4444',
        'expired': '#9ca3af'
    }
    status_dist_qs = filtered_bookings.values('status').annotate(count=Count('id')).order_by('status')
    status_distribution = []
    for item in status_dist_qs:
        s_raw = item['status']
        status_distribution.append({
            'status': s_raw,
            'label': s_raw.title(),
            'count': item['count'],
            'color': status_colors_map.get(s_raw.lower(), '#6366f1')
        })

    # 8. Recent Transactions in range
    recent_bookings = filtered_bookings.select_related('user').order_by('-created_at')[:15]

    return render(request, 'admin/admin_reports.html', {
        'total_revenue': total_revenue,
        'total_bookings': total_bookings,
        'active_users': active_users,
        'pending_requests': pending_requests,
        'recent_bookings': recent_bookings,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'revenue_by_event': list(revenue_by_event),
        'status_distribution': status_distribution,
    })




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
def design_canvas_page(request):
    if request.user.role != 'customer':
        return HttpResponseForbidden('Not allowed')
    
    # We will pass some categories for the sidebar items
    categories = ['Backdrops', 'Balloons', 'Furniture', 'Decorations']
    return render(request, 'client/design_canvas.html', {'categories': categories})

