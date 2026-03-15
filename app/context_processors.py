from .models import Booking, Notification, AdminNotification


def admin_notifications(request):
    """Inject pending booking and admin notifications for admin/staff users."""
    if request.user.is_authenticated and request.user.role in ['admin', 'staff']:
        from django.utils import timezone
        
        # 1. Fetch legacy Booking notifications (new bookings)
        recent_bookings = Booking.objects.filter(
            admin_notif_hidden=False
        ).select_related('user')
        
        # 2. Fetch new AdminNotification events (edits, cancels, reviews)
        recent_events = AdminNotification.objects.filter(
            is_hidden=False
        ).select_related('booking', 'user')

        # Unified list of dictionaries
        unified_notifs = []

        for b in recent_bookings:
            unified_notifs.append({
                'id': f'b_{b.id}',
                'type': 'booking',
                'raw_id': b.id,
                'booking': b,
                'user': b.user,
                'message': f"booked a {b.event_type}",
                'created_at': b.created_at,
                'is_read': b.admin_notified
            })

        for e in recent_events:
            unified_notifs.append({
                'id': f'n_{e.id}',
                'type': 'event',
                'raw_id': e.id,
                'booking': e.booking,
                'user': e.user or getattr(e.booking, 'user', None),
                'message': e.message,
                'created_at': e.created_at,
                'is_read': e.is_read
            })

        # Sort combined list by created_at (newest first)
        unified_notifs.sort(key=lambda x: x['created_at'], reverse=True)

        today = timezone.localtime().date()
        notif_today = []
        notif_earlier = []
        unread_count = 0

        for notif in unified_notifs:
            notif_date = timezone.localtime(notif['created_at']).date()
            if notif_date == today:
                notif_today.append(notif)
            else:
                notif_earlier.append(notif)
                
            if not notif['is_read']:
                unread_count += 1

        return {
            'notif_today': notif_today,
            'notif_earlier': notif_earlier,
            'notif_count': unread_count,
        }
    return {}


def customer_notifications(request):
    """Inject notifications for the logged-in customer."""
    if request.user.is_authenticated and request.user.role == 'customer':
        notifications = Notification.objects.filter(user=request.user).order_by('-created_at')[:10]
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
        return {
            'customer_notifications': notifications,
            'unread_notifications_count': unread_count,
        }
    return {}
