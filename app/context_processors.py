from django.urls import reverse

from .models import Booking, ChatMessage, ChatSession, Notification, AdminNotification, Payment, ConcernTicket


# ---------------------------------------------------------------------------
# Notification deep-link routing (Option A: keyword-based, walang migration).
#
# Bakit kailangan: ang Notification/AdminNotification ay may booking FK lang —
# walang type/payment/review FK. Kaya dati lahat ng notif click ay bumabagsak
# sa booking detail (customer_profile / admin_booking_detail), kahit payment o
# review yun. Ang helpers dito ay nagbabasa ng message text at nagbabalik ng
# tamang target URL per type. Ang booking-related ay nananatili sa booking
# detail (existing behavior preserved); ang payment/review/chat ay naka-route
# sa kani-kanilang pages.
# ---------------------------------------------------------------------------

def _latest_booking_payment_id(booking):
    """Pinakabagong Payment ID ng booking (para diretso sa payment detail)."""
    if booking is None or getattr(booking, "id", None) is None:
        return None
    try:
        latest = (
            Payment.objects.filter(booking_id=booking.id)
            .order_by("-created_at", "-id")
            .values_list("id", flat=True)
            .first()
        )
    except Exception:
        return None
    return latest


def _latest_booking_review_id(booking):
    """Pinakabagong Review ID ng booking (para diretso sa review detail)."""
    if booking is None or getattr(booking, "id", None) is None:
        return None
    try:
        from .models import Review

        latest = (
            Review.objects.filter(booking_id=booking.id)
            .order_by("-created_at", "-id")
            .values_list("id", flat=True)
            .first()
        )
    except Exception:
        return None
    return latest


def _customer_notif_target_url(notif):
    """Target URL ng isang customer Notification batay sa message text."""
    msg = (getattr(notif, "message", "") or "").lower()
    booking = getattr(notif, "booking", None)

    # Payment-related: verified / rejected / received / reminder / proceed-to-payment.
    # Diretso sa detalye ng pinakabagong payment ng booking (hindi list) —
    # para pag-click, kita agad yung payment status/amount/ref.
    if any(
        key in msg
        for key in (
            "payment",
            "php",
            "paid",
            "gcash",
            "paymongo",
            "outstanding",
            "settle",
            "proceed to payment",
            "receipt",
        )
    ):
        url = reverse("my_payments")
        # Verified/rejected/received/reminder/expired-payment -> history tab;
        # "proceed to payment" (booking approved) -> action-required tab.
        if "proceed to payment" in msg or "approved" in msg:
            return f"{url}?tab=action_required"
        return f"{url}?tab=payment_history"

    # Review-related (hal. completed booking na humihingi ng review).
    if "review" in msg or "rate" in msg:
        return reverse("my_reviews")

    # Chat-related.
    if "chat" in msg or "support" in msg:
        return reverse("client_chat_page")

    # Default: booking detail (existing from_notif flow — huwag baklasin).
    if booking is not None:
        url = reverse("customer_profile")
        return f"{url}?search={booking.id}&booking_id={booking.id}&from_notif=1"
    return reverse("customer_profile")


def _admin_notif_target_url(notif_type, message, booking):
    """Target URL ng isang admin notif (legacy booking o AdminNotification event)."""
    msg = (message or "").lower()

    # Payment-related: "New GCash/PayMongo payment submitted ..." etc.
    # Diretso sa payment detail ng pinakabagong payment ng booking —
    # para pag-click, kita agad yung proof/amount at verify/reject buttons.
    if any(
        key in msg
        for key in ("payment", "gcash", "paymongo", "php", "verify", "receipt")
    ):
        payment_id = _latest_booking_payment_id(booking)
        if payment_id is not None:
            return reverse("admin_payment_detail", args=[payment_id])
        # Fallback: walang payment record (hal. lumang notif) -> filtered list.
        url = reverse("admin_payment_list")
        if booking is not None:
            return f"{url}?search=booking:{booking.id}"
        return url

    # Review-related: "submitted a new review."
    # Diretso sa review detail ng pinakabagong review ng booking.
    if "review" in msg:
        review_id = _latest_booking_review_id(booking)
        if review_id is not None:
            return reverse("admin_review_detail", args=[review_id])
        # Fallback: walang review record -> reviews list.
        url = reverse("admin_reviews")
        user = getattr(booking, "user", None)
        if user is not None and getattr(user, "username", ""):
            return f"{url}?search={user.username}"
        return url

    # Chat-related: "requested admin chat support: ..."
    if "chat" in msg or "support" in msg:
        return reverse("admin_chat_inbox")

    # Concern-related.
    if "concern" in msg or "ticket" in msg:
        return reverse("admin_concerns")

    # Default: booking detail (existing behavior preserved).
    if booking is not None:
        return reverse("admin_booking_detail", args=[booking.id])
    return "#"


def admin_notifications(request):
    """Inject pending booking and admin notifications for admin users."""
    if request.user.is_authenticated and request.user.role in ("admin", "staff"):
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
                'is_read': b.admin_notified,
                'target_url': _admin_notif_target_url(
                    'booking', f"booked a {b.event_type}", b
                ),
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
                'is_read': e.is_read,
                'target_url': _admin_notif_target_url(
                    'event', e.message, e.booking
                ),
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

        # Sidebar action badges (pareho ng Chat badge — itago kapag 0)
        # Pending payments must match the admin action queue: exclude abandoned
        # PayMongo checkout attempts so the badge never overcounts.
        from .views import _abandoned_paymongo_payment_query

        return {
            'notif_today': notif_today,
            'notif_earlier': notif_earlier,
            'notif_count': unread_count,
            'pending_bookings_count': Booking.objects.filter(status='pending').count(),
            'pending_payments_count': (
                Payment.objects.filter(payment_status='pending')
                .exclude(_abandoned_paymongo_payment_query())
                .count()
            ),
            'new_concerns_count': ConcernTicket.objects.filter(status='new').count(),
        }
    return {}


def chat_notifications(request):
    """Inject chat counters for customer and admin navigation."""
    if not request.user.is_authenticated:
        return {}

    if request.user.role == 'customer':
        unread_chat_count = ChatMessage.objects.filter(
            receiver=request.user,
            is_read=False,
            session__is_admin_support=True,
        ).exclude(sender=request.user).count()
        return {'unread_chat_count': unread_chat_count}

    if request.user.role == 'admin' or request.user.is_superuser:
        sessions = ChatSession.objects.filter(is_admin_support=True).exclude(status='ai')
        return {
            'admin_chat_pending_count': 0,
            'admin_chat_unread_count': sum(
                1 for session in sessions
                if session.status != 'closed' and session.has_unread_for_admin
            ),
        }

    return {}


def customer_notifications(request):
    """Inject notifications for the logged-in customer."""
    if request.user.is_authenticated and request.user.role == 'customer':
        notifications = Notification.objects.filter(user=request.user).order_by('-created_at')[:10]
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
        # Lagyan bawat notif ng tamang deep-link (payment -> My Payments, atbp.)
        # para hindi lahat bumabagsak sa booking detail.
        for notif in notifications:
            notif.target_url = _customer_notif_target_url(notif)
        return {
            'customer_notifications': notifications,
            'unread_notifications_count': unread_count,
        }
    return {}
