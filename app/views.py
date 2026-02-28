from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count
from django.http import HttpResponseForbidden
from django.views.generic import TemplateView
from django.contrib import messages
from .models import User, Booking, Package, AddOn, AdditionalOnly, AuditLog, Design, ChatMessage, ChatSession
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





def log_action(user, action):
    """Helper function to create an audit log entry."""
    AuditLog.objects.create(user=user, action=action)


class HomePageView(TemplateView):
    template_name = 'client/home.html'


class AboutPageView(TemplateView):
    template_name = 'client/about.html'
    

class ServicesPageView(TemplateView):
    template_name = 'client/services.html'
    
    
class PackagePageView(TemplateView):
    template_name = 'client/package.html'


class GalleryPageView(TemplateView):
    template_name = 'client/gallery.html'
    
    
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
        if not re.search(r'[A-Z]', password):
            errors.append("Password must contain at least one uppercase letter.")
        if not re.search(r'[0-9]', password):
            errors.append("Password must contain at least one number.")
        # special character optional, no error

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


@login_required
def customer_profile(request):
    if request.user.role != 'customer':
        return HttpResponseForbidden("Not allowed")

    user_bookings = Booking.objects.filter(user=request.user).order_by('-event_date')
    
    # Attach formatted time range for the table/modal
    for b in user_bookings:
        b.time_range_display = get_booking_time_range(b)

    # Prepare Calendar Events
    all_bookings = Booking.objects.exclude(status__in=['cancelled']).filter(event_date__gte=timezone.now().date())
    calendar_events = []

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
            'title': get_booking_time_range(b), # Shows "10:00 AM - 12:00 PM" on bar
            'start': start_dt.isoformat() if start_dt else b.event_date.isoformat(),
            'end': end_dt.isoformat() if end_dt else None,
            'color': '#d97706' if b.status == 'pending' else '#3b82f6'
        })

    # Calculate Stats
    total_bookings = user_bookings.count()
    pending_count = user_bookings.filter(status='pending').count()
    confirmed_count = user_bookings.filter(status='confirmed').count()
    completed_count = user_bookings.filter(status='completed').count()

    return render(request, 'client/customer_profile.html', {
        'user_bookings': user_bookings,
        'calendar_events': calendar_events,
        'total_bookings': total_bookings,
        'pending_count': pending_count,
        'confirmed_count': confirmed_count,
        'completed_count': completed_count,
    })


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
                return redirect('create_booking')
            
            # 2. Past Time Check (If booking is Today)
            if booking_date == today and start_time:
                booking_time = datetime.strptime(start_time, '%H:%M').time()
                if booking_time < now.time():
                    messages.error(request, "Cannot book a time in the past.")
                    return redirect('create_booking')

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
                        return redirect('create_booking')

        booking = Booking.objects.create(
            user=request.user,
            event_type=request.POST.get('event_type'),
            event_date=event_date,
            event_time=start_time, # Save start time to event_time field
            event_location=request.POST.get('event_location'),
            number_of_guests=request.POST.get('number_of_guests'),
            package_type=request.POST.get('package_type'),
            special_requests=special_requests,
            total_price=request.POST.get('total_price')
        )
        log_action(request.user, f"Created a new booking #{booking.id}.")

        messages.success(request, "Booking created successfully!")
        return redirect('customer_profile')

    return render(request, 'client/booking/booking_form.html')


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
        booking.number_of_guests = request.POST.get('number_of_guests')
        booking.package_type = request.POST.get('package_type')
        booking.special_requests = special_requests
        booking.total_price = request.POST.get('total_price')

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

    bookings = Booking.objects.order_by('-created_at')
    # Attach formatted time range for display
    for b in bookings:
        b.time_range_display = get_booking_time_range(b)

    return render(request, 'admin/booking/admin_booking_list.html', {'bookings': bookings})

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
        messages.success(request, "Booking confirmed!")
    elif action == 'deny':
        booking.status = 'cancelled'
        booking.save()
        log_action(request.user, f"Denied booking #{booking.id} for '{booking.user.username}'.")
        messages.success(request, "Booking denied!")

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
        messages.success(request, "Cancel approved.")
    elif action == 'deny':
        booking.status = 'confirmed'
        log_action(request.user, f"Denied cancellation request for booking #{booking.id}.")
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
        messages.success(request, "Edit approved. You can now edit the booking.")
    elif action == 'deny':
        booking.edit_requested = False
        booking.edit_allowed = False
        log_action(request.user, f"Denied edit request for booking #{booking.id}.")
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
            return redirect('admin_package_create')

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
            return redirect('admin_package_edit', id=id)

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
            price = Decimal(request.POST['price'])  # ✅ DITO
            solo_raw = request.POST.get('solo_price')
            solo_price = Decimal(solo_raw) if solo_raw else None
        except InvalidOperation:
            messages.error(request, "Invalid price format.")
            return redirect('admin_addon_create')

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
            return redirect('admin_addon_edit', id=id)

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
            return redirect('admin_additional_create')

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
            return redirect('admin_additional_edit', id=id)

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

    # 1. Total Revenue (Sum of total_price for completed bookings)
    # Note: Mas mainam kung may Payment model status, pero base sa Booking status muna tayo
    revenue_data = Booking.objects.filter(status='completed').aggregate(Sum('total_price'))
    total_revenue = revenue_data['total_price__sum'] or 0

    # 2. Total Bookings (Lahat ng bookings)
    total_bookings = Booking.objects.count()

    # 3. Active Users (Customers only)
    active_users = User.objects.filter(role='customer', is_active=True).count()

    # 4. Pending Requests
    pending_requests = Booking.objects.filter(status='pending').count()

    # 5. Recent Transactions (Latest 10 bookings)
    recent_bookings = Booking.objects.select_related('user').order_by('-created_at')[:10]

    return render(request, 'admin/admin_reports.html', {
        'total_revenue': total_revenue,
        'total_bookings': total_bookings,
        'active_users': active_users,
        'pending_requests': pending_requests,
        'recent_bookings': recent_bookings,
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
