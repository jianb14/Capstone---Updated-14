import re
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
    if getattr(notif, 'concern_id', None):
        if notif.concern.user_id == notif.user_id:
            return f"{reverse('report_concern')}?concern_id={notif.concern_id}&from_notif=1"
        return reverse('report_concern')
    msg = (getattr(notif, "message", "") or "").lower()
    booking = getattr(notif, "booking", None)

    if booking is not None and booking.user_id != notif.user_id:
        return reverse('customer_profile')

    def booking_details():
        return f"{reverse('customer_profile')}?booking_id={booking.id}&modal=details&from_notif=1"

    if booking is not None and 'booking change request' in msg:
        return f"{reverse('customer_profile')}?booking_id={booking.id}&modal=details&from_notif=1"

    if booking is not None and "backdrop design" in msg:
        return f"{reverse('customer_profile')}?booking_id={booking.id}&modal=design&from_notif=1"

    if booking is not None and (any(word in msg for word in ('expired', 'not approved', 'cancelled', 'canceled'))
            and not msg.startswith('your payment')):
        return booking_details()

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
        if booking is None:
            return reverse('my_payments')
        url = reverse('my_payments')
        if 'proceed to payment' in msg or 'payment reminder' in msg:
            if booking.status in ('pending_payment', 'confirmed'):
                return f'{url}?tab=action_required&booking_id={booking.id}&from_notif=1'
            return booking_details()
        # Notifications predate later payments. Keep older notices attached to
        # a record that already existed when the notice was created.
        records = list(booking.payments.all())
        records = [payment for payment in records if payment.created_at <= notif.created_at]
        amount = re.search(r'\bPHP\s*(\d[\d,]*(?:\.\d{2})?)', notif.message, re.I)
        if amount:
            from decimal import Decimal
            matching = [payment for payment in records if payment.amount == Decimal(amount.group(1).replace(',', ''))]
            records = matching or records
        if records:
            payment = max(records, key=lambda record: (record.created_at, record.id))
            return f'{url}?tab=payment_history&payment_id={payment.id}&from_notif=1'
        return booking_details()

    # Review-related (hal. completed booking na humihingi ng review).
    if re.search(r'\b(?:review|rate)\b', msg):
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
    if booking is not None and 'change request' in msg:
        match = re.search(r'\b(?:booking )?change request #(\d+)\b', msg)
        if match:
            return reverse('admin_booking_change_detail', args=[int(match.group(1))])
        return f"{reverse('admin_booking_list')}?tab=requests&booking_id={booking.pk}"

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
    if request.user.is_authenticated and request.user.role == 'admin':
        from .admin_notifications import unread_count
        # Header content is fetched on demand; rendering an admin page only needs counters.
        total_unread = unread_count()

        # Sidebar action badges (pareho ng Chat badge — itago kapag 0)
        # Pending payments must match the admin action queue: exclude abandoned
        # PayMongo checkout attempts so the badge never overcounts.
        from .views import _abandoned_paymongo_payment_query

        return {
            'notif_today': [],
            'notif_earlier': [],
            'notif_count': total_unread,
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
        notifications = (Notification.objects.filter(user=request.user).select_related('booking', 'concern')
            .prefetch_related('booking__payments').order_by('-created_at', '-id')[:20])
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
