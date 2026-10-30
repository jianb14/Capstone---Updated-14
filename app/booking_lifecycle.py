"""Booking deadlines, read models, and repeat-safe background processing.

Paid/submitted payments are protected. A missed design deadline alerts the team;
it never expires a confirmed booking. All timestamps use the site timezone.
"""
import logging
from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import AdminNotification, Booking, BookingDeadlineNotice, BookingStatusLog, Notification, SiteSettings

logger = logging.getLogger(__name__)


def event_start_at(booking):
    # Unknown legacy times retain the reservation through the end of that date.
    return timezone.make_aware(datetime.combine(booking.event_date, booking.event_time or time.max), timezone.get_default_timezone())


def payment_was_received(payment):
    if payment.payment_status == 'verified':
        return payment.amount > 0
    if payment.payment_status != 'pending':
        return False
    return payment.payment_method == 'gcash' or bool(payment.received_at or payment.paymongo_payment_id or 'paid via paymongo' in (payment.notes or '').lower())


def deadline_policy():
    settings = SiteSettings.objects.first()
    return (max(1, settings.booking_payment_window_hours) if settings else 24,
        max(1, settings.booking_design_lead_hours) if settings else 24)


def set_approval_deadlines(booking, now=None):
    now = now or timezone.now()
    hours, lead = deadline_policy()
    booking.approved_at = now
    booking.payment_due_at = min(now + timedelta(hours=hours), event_start_at(booking))
    booking.design_due_at = event_start_at(booking) - timedelta(hours=lead)


def deadline_notice(booking, key, message):
    # Called under the booking row lock; the unique constraint also protects workers.
    notice, created = BookingDeadlineNotice.objects.get_or_create(booking=booking, key=key)
    if created:
        AdminNotification.objects.create(booking=booking, user=booking.user, message=message)
        def email_admin():
            from .views.common import send_admin_alert_email
            send_admin_alert_email(f'Booking #{booking.pk} - deadline alert', message)
        transaction.on_commit(email_admin)
    return created


def lifecycle_display(booking, now=None):
    now = now or timezone.now()
    payments = list(booking.payments.all())
    awaiting = [p for p in payments if p.payment_status == 'pending' and payment_was_received(p)]
    deliveries = list(booking.design_deliveries.all())
    revisions = [change for change in booking.change_requests.all() if change.status == 'applied' and change.proposed.get('_design_changed')]
    revision = max(revisions, key=lambda change:(change.applied_at, change.pk)) if revisions else None
    revision_at = revision.applied_at if revision else None
    has_design = any(not revision_at or image.uploaded_at > revision_at for image in deliveries)
    due = booking.design_due_at or event_start_at(booking) - timedelta(hours=deadline_policy()[1])
    active = booking.status == 'confirmed'
    return {'payment_due_at': booking.payment_due_at, 'awaiting_verification': bool(awaiting),
        'design_due_at': due, 'design_preparing': active and not has_design,
        'design_overdue': active and not has_design and now >= due, 'design_ready': has_design,
        'design_revision_pending': bool(revision_at and not has_design), 'design_revision_at':revision_at}


def process_booking(booking_id, now=None):
    now = now or timezone.now()
    with transaction.atomic():
        booking = Booking.objects.select_for_update().select_related('user').get(pk=booking_id)
        if booking.status not in ('pending', 'pending_payment', 'confirmed'):
            return False
        start = event_start_at(booking)
        payments = list(booking.payments.all())
        received = [p for p in payments if payment_was_received(p)]
        pending = [p for p in received if p.payment_status == 'pending']
        # Legacy records get a visible grace window instead of an old, hidden deadline.
        if booking.status == 'pending_payment' and booking.payment_due_at is None:
            set_approval_deadlines(booking, now)
            booking.save(update_fields=['approved_at', 'payment_due_at', 'design_due_at'])
        if booking.status == 'confirmed' and booking.design_due_at is None:
            booking.design_due_at = start - timedelta(hours=deadline_policy()[1])
            booking.save(update_fields=['design_due_at'])
        due = start if booking.status == 'pending' else booking.payment_due_at
        if booking.status in ('pending', 'pending_payment') and due and now >= due and not received:
            old_status = booking.status
            booking.status = 'expired'
            booking.save(update_fields=['status', 'updated_at'])
            reason = 'The event start time passed before admin approval.' if old_status == 'pending' else 'The initial payment deadline passed without a submitted payment.'
            BookingStatusLog.objects.create(booking=booking, old_status=old_status, new_status='expired', notes=reason)
            Notification.objects.create(booking=booking, user=booking.user,
                message=f'Booking #{booking.id} expired. {reason}')
            return True
        for payment in pending:
            submitted = payment.received_at or (payment.updated_at if payment.payment_method.startswith('paymongo_') else payment.created_at)
            review_due = min(submitted + timedelta(hours=24), start)
            if now >= review_due:
                deadline_notice(booking, f'payment-review-{payment.pk}',
                    f'Urgent payment verification: Booking #{booking.id} has submitted payment #{payment.pk} awaiting review. Do not expire a customer payment while it is being checked.')
        design = lifecycle_display(booking, now) if booking.status == 'confirmed' else {}
        if booking.status == 'confirmed' and now >= booking.design_due_at and not design['design_ready']:
            key = f"design-revision-{design['design_revision_at'].isoformat()}" if design['design_revision_at'] else 'design-overdue'
            deadline_notice(booking, key,
                f'Urgent: Booking #{booking.id} event on {timezone.localtime(start):%b %d, %Y %I:%M %p} needs a current event design. Upload the customer design or its required revision now.')
        return False


def process_booking_deadlines(now=None):
    now = now or timezone.now()
    candidates = Booking.objects.filter(
        Q(status='pending', event_date__lte=timezone.localdate(now)) |
        Q(status='pending_payment') |
        Q(status='confirmed', design_due_at__lte=now) |
        Q(status='confirmed', design_due_at__isnull=True) |
        Q(status='confirmed', payments__payment_status='pending')
    ).values_list('pk', flat=True).distinct()
    expired = 0
    for pk in candidates.iterator():
        try:
            expired += int(process_booking(pk, now))
        except Booking.DoesNotExist:
            continue
    from .booking_changes import process_changes
    process_changes(now)
    return expired
