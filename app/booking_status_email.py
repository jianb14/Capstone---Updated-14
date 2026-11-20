"""Customer lifecycle mail driven by the shared booking status history."""
import logging
from decimal import Decimal
from ipaddress import ip_address
from urllib.parse import urlsplit

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from .models import Booking, BookingStatusLog

logger = logging.getLogger(__name__)

STATUS_MESSAGES = {
    'pending': ('Submitted', 'We received your booking. It is awaiting approval.'),
    'pending_payment': ('Approved - Pending Payment',
        'Your booking is approved. Please submit your initial payment before the deadline below.'),
    'confirmed': ('Confirmed', 'Your booking is confirmed. We look forward to your event!'),
    'cancelled': ('Cancelled', 'Your booking has been cancelled or was not approved.'),
    'expired': ('Expired', 'Your booking has expired. Please contact us if you need help booking again.'),
    'completed': ('Completed', 'Thank you for trusting Balloorina! You can leave a review from your account.'),
}


def booking_email_origin():
    """Use configured public addresses; never depend on a worker's HTTP request."""
    explicit = getattr(settings, 'BOOKING_EMAIL_BASE_URL', '').strip()
    candidates = [explicit] if explicit else [
        *getattr(settings, 'CSRF_TRUSTED_ORIGINS', []),
        *(f'https://{host}' for host in settings.ALLOWED_HOSTS
          if host not in ('localhost', '127.0.0.1', '[::1]')),
    ]
    for candidate in candidates:
        parts = urlsplit(candidate)
        if not explicit:
            host = (parts.hostname or '').rstrip('.').lower()
            if host == 'localhost' or host.endswith('.localhost'):
                continue
            try:
                if ip_address(host).is_loopback:
                    continue
            except ValueError:
                pass  # A DNS hostname, not an IP address.
        if (parts.scheme in ('https', 'http') and parts.hostname
                and '*' not in parts.netloc and not parts.username and not parts.password
                and not parts.query and not parts.fragment and parts.path in ('', '/')):
            return f'{parts.scheme}://{parts.netloc}'
    return ''


def send_status_email(booking_id, subject, body, recipient):
    """Do not retry ambiguous provider results or undo a committed booking."""
    try:
        if send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=False) == 1:
            return
    except Exception:
        # Provider exception text can include message data or credentials.
        pass
    logger.warning('Booking status email acceptance is unconfirmed for booking %s.', booking_id)


@receiver(post_save, sender=BookingStatusLog, dispatch_uid='customer_booking_status_email')
def queue_booking_status_email(sender, instance, created, raw=False, using='default', **kwargs):
    if (raw or not created or instance.old_status == instance.new_status
            or instance.new_status not in STATUS_MESSAGES):
        return
    try:
        # Reload saved values: submission can still hold string times on its model.
        booking = Booking.objects.using(using).select_related('user').get(pk=instance.booking_id)
        recipient = (booking.user.email or '').strip()
        if not recipient:
            return
        origin = booking_email_origin()
        if not origin:
            logger.warning('Booking status email has no public site URL for booking %s.', booking.pk)
            return
        label, explanation = STATUS_MESSAGES[instance.new_status]
        name = booking.user.get_full_name() or booking.user.username
        schedule = str(booking.event_date)
        if booking.event_time:
            schedule += f' {booking.event_time:%H:%M}'
        lines = [f'Hi {name},', '', f'Booking #{booking.pk}', f'Status: {label}',
                 f'Event: {booking.event_type or "Event"}', f'Event date: {schedule} (Asia/Manila)',
                 f'Location: {booking.event_location}', '', explanation]
        if instance.new_status == 'pending_payment':
            # Use the same calculation as the customer payment page.
            from .views.payments import _get_booking_payment_breakdown
            _, _, total, paid, balance, deposit = _get_booking_payment_breakdown(booking)
            due = min(max(balance, Decimal('0.00')), max(deposit - paid, Decimal('0.00')))
            lines.extend(['', f'Booking total: PHP {total:,.2f}', f'Initial payment due: PHP {due:,.2f}'])
            if booking.payment_due_at:
                deadline = timezone.localtime(booking.payment_due_at)
                lines.append(f'Payment deadline: {deadline:%Y-%m-%d %H:%M %Z}')
            lines.append('Open your booking for payment options and current payment details.')
        if instance.new_status in ('cancelled', 'expired'):
            reason = (booking.admin_denial_reason if instance.new_status == 'cancelled' else '') or instance.notes
            if reason:
                lines.extend(['', f'Reason: {reason}'])
        lines.extend(['', f'View Booking: {origin}{reverse("view_booking", args=[booking.pk])}',
                      'Please sign in to view your booking.', '', 'Balloorina Team'])
        # Snapshot now: a later save in this transaction must not rewrite this email.
        subject = f'Booking #{booking.pk} - {label} | Balloorina'
        body = '\n'.join(lines)
        booking_id = booking.pk
        transaction.on_commit(lambda: send_status_email(booking_id, subject, body, recipient), using=using)
    except Exception as error:
        logger.warning('Could not prepare booking status email for history entry %s (%s).',
                       instance.pk, type(error).__name__)
