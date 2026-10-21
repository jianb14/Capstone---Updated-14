"""Reviewed booking amendments. The live reservation changes only at finalization."""
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from functools import wraps

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .booking_lifecycle import deadline_notice, event_start_at, payment_was_received
from .models import (AdminNotification, Booking, BookingChangeRequest, BookingImage,
                     BookingStatusLog, Notification, SiteSettings)

FIELDS = ('event_type', 'event_date', 'event_time', 'event_end_date', 'event_end_time',
    'duration_minutes', 'event_location', 'event_lat', 'event_lng', 'venue_landmark',
    'package_type', 'special_requests', 'design_theme', 'color_palette', 'motto_text',
    'logistics_distance_km', 'logistics_fee', 'logistics_fee_override', 'overtime_hours',
    'overtime_fee', 'fee_policy_snapshot', 'total_price')
MONEY = Decimal('0.01')


def schedule_atomic(view):
    """Serialize reservation writes and temporary holds using the settings row."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        with transaction.atomic():
            config = SiteSettings.load()
            SiteSettings.objects.select_for_update().get(pk=config.pk)
            return view(*args, **kwargs)
    return wrapped


def snapshot(booking):
    result = {}
    for name in FIELDS:
        field = Booking._meta.get_field(name)
        value = deepcopy(field.to_python(getattr(booking, name)))
        if isinstance(value, (date, datetime, time)):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = str(value.quantize(Decimal(1).scaleb(-field.decimal_places)))
        result[name] = value
    return result


def proposed_booking(change):
    booking = deepcopy(change.booking)
    for name in FIELDS:
        setattr(booking, name, Booking._meta.get_field(name).to_python(change.proposed.get(name)))
    return booking


def verified_paid(booking):
    return booking.payments.filter(payment_status='verified', applied_to_booking=True).aggregate(total=Sum('amount'))['total'] or Decimal('0')


def change_payment_summary(change):
    paid = verified_paid(change.booking)
    historical = change.status not in BookingChangeRequest.ACTIVE_STATUSES and 'verified_paid_at_review' in change.quote
    if historical:
        paid = Decimal(change.quote['verified_paid_at_review'])
    extra = max(change.quoted_total - change.original_total, Decimal('0')) if paid > 0 else Decimal('0')
    excess = max(paid - change.quoted_total, Decimal('0')) if change.quoted_total < change.original_total else Decimal('0')
    return {'change_verified_paid':paid, 'change_extra_payment':extra,
        'change_verified_paid_label':'Verified payments when quoted' if historical else 'Verified payments already credited',
        'change_existing_balance':max(change.original_total - paid, Decimal('0')),
        'change_balance_after_extra':max(change.quoted_total - paid - extra, Decimal('0')),
        'change_excess_payment':excess, 'change_requires_nonrefund_ack':excess > 0}


def pending_proof(booking, exclude_change=None):
    payments = booking.payments.filter(payment_status='pending')
    if exclude_change:
        payments = payments.exclude(change_request=exclude_change)
    return any(payment_was_received(p) for p in payments)


def change_payment_state(change):
    """Shared customer actions for recorded funds, not just request status."""
    payments = list(change.payments.all())
    received = any(payment_was_received(p) for p in payments)
    reviewing = any(p.payment_status == 'pending' and payment_was_received(p) for p in payments)
    return {
        'change_payment_received': received,
        'change_payment_under_review': reviewing,
        'change_can_pay': bool(change.status == 'awaiting_payment' and change.accepted_at
            and change.additional_due > 0 and not received
            and change.expires_at and change.expires_at > timezone.now()),
        'change_can_withdraw': change.status in ('pending_review', 'quoted', 'awaiting_payment') and not received,
    }


def eligibility(booking, now=None):
    now = now or timezone.now()
    hours = SiteSettings.load().booking_change_cutoff_hours
    if booking.status not in ('pending_payment', 'confirmed'):
        return False, 'Change requests are available for approved or confirmed bookings only.'
    if event_start_at(booking) <= now + timedelta(hours=hours):
        return False, f'Changes within {hours} hours of the event need direct assistance. Please contact our team.'
    if any(change.status in BookingChangeRequest.ACTIVE_STATUSES for change in booking.change_requests.all()):
        return False, 'You already have an active change request for this booking.'
    return True, ''


def live_holds(now=None):
    now = now or timezone.now()
    holds = []
    for change in BookingChangeRequest.objects.filter(status__in=('quoted', 'awaiting_payment'), hold_start__isnull=False).select_related('booking').prefetch_related('payments'):
        if change.booking.status not in ('pending_payment', 'confirmed') or min(change.hold_start, event_start_at(change.booking)) <= now:
            continue
        if change.expires_at and change.expires_at <= now:
            if change.status != 'awaiting_payment' or not any(payment_was_received(p) and (p.received_at or p.created_at) <= change.expires_at for p in change.payments.all()):
                continue
        holds.append(change)
    return holds


def hold_conflicts(booking, now=None):
    from .views.common import _booking_time_bounds
    start, end = _booking_time_bounds(booking)
    if not start or not end:
        return []
    zone = timezone.get_default_timezone()
    start, end = timezone.make_aware(start, zone), timezone.make_aware(end, zone)
    # A submitted proof preserves its hold while the team verifies it.
    return [change for change in live_holds(now) if change.booking_id != booking.pk and change.hold_start < end and change.hold_end > start]


def ensure_available(booking):
    from .views.common import find_active_booking_conflicts
    from .models import BlockedDate
    from .views.common import _booking_time_bounds
    booking = deepcopy(booking)
    for name in ('event_date', 'event_time', 'event_end_date', 'event_end_time'):
        setattr(booking, name, Booking._meta.get_field(name).to_python(getattr(booking, name)))
    start, end = _booking_time_bounds(booking)
    if not start or not end or start >= end:
        raise ValidationError('Choose a valid start and end time.')
    if BlockedDate.objects.filter(date__gte=start.date(), date__lte=(end-timedelta(microseconds=1)).date()).exists():
        raise ValidationError('The requested date is unavailable. Choose another date.')
    if find_active_booking_conflicts(booking):
        raise ValidationError('The requested schedule is already reserved or temporarily held. Choose another time.')


def prepare_proposal(booking, data):
    from .views.common import (compute_logistics_quote, compute_overtime, capture_booking_fee_policy,
        get_booking_display_breakdown, get_booking_price_breakdown, get_booking_duration_policy,
        get_booking_lead_time_policy, remove_end_time_tag, normalize_package_part)
    from .views.bookings import _validate_design_preferences
    proposed = deepcopy(booking)
    try:
        proposed.event_date = date.fromisoformat(data.get('event_date', ''))
        proposed.event_time = datetime.strptime(data.get('start_time', ''), '%H:%M').time()
        proposed.event_end_time = datetime.strptime(data.get('end_time', ''), '%H:%M').time()
    except (ValueError, TypeError):
        raise ValidationError('Choose a valid event date and AM/PM time range.')
    cutoff = timezone.now() + timedelta(hours=SiteSettings.load().booking_change_cutoff_hours)
    if event_start_at(proposed) <= cutoff:
        raise ValidationError('The requested event is too soon for an online change. Please contact our team.')
    from .views.common import _booking_time_bounds
    _, saved_end = _booking_time_bounds(booking)
    schedule_changed = (proposed.event_date, proposed.event_time, proposed.event_end_time) != (booking.event_date, booking.event_time, saved_end.time() if saved_end else None)
    if schedule_changed:
        lead, earliest = get_booking_lead_time_policy()
        if proposed.event_date < earliest or not 7 <= proposed.event_time.hour < 18:
            raise ValidationError('Choose an available date and a start time between 7:00 AM and 6:00 PM.')
    policy = get_booking_duration_policy()
    saved = booking.fee_policy_snapshot or {}
    # Existing duration terms stay in force when only unrelated details change.
    if not schedule_changed:
        policy.update(included_hours=int(saved.get('included_hours', policy['included_hours'])), overtime_rate=Decimal(saved.get('overtime_rate', policy['overtime_rate'])))
    overtime = compute_overtime(proposed.event_time.strftime('%H:%M'), proposed.event_end_time.strftime('%H:%M'), proposed.event_date, policy)
    if overtime['error']:
        raise ValidationError(overtime['error'])
    proposed.event_end_date = proposed.event_date + timedelta(days=proposed.event_end_time <= proposed.event_time)
    proposed.duration_minutes = overtime['duration_minutes']
    if schedule_changed:
        proposed.overtime_hours, proposed.overtime_fee = overtime['overtime_hours'], overtime['overtime_fee']
    lengths = {'event_type':50, 'event_location':255, 'package_type':500, 'venue_landmark':255,
        'design_theme':100, 'color_palette':100, 'motto_text':150, 'special_requests':5000}
    for name, limit in lengths.items():
        value = (data.get(name, getattr(booking, name)) or '').strip()
        if len(value) > limit:
            raise ValidationError(f'{name.replace("_", " ").title()} is too long (maximum {limit} characters).')
        setattr(proposed, name, value)
    if not proposed.event_type or len(proposed.event_location) < 10 or not proposed.package_type:
        raise ValidationError('Event type, complete venue address, and a package are required.')
    error = _validate_design_preferences(proposed.design_theme, proposed.color_palette)
    if error:
        raise ValidationError(error)
    proposed.special_requests = (remove_end_time_tag(proposed.special_requests) + f'\n(End Time: {proposed.event_end_time:%H:%M})').strip()
    try:
        proposed.event_lat = Decimal(data.get('event_lat', str(booking.event_lat or '')))
        proposed.event_lng = Decimal(data.get('event_lng', str(booking.event_lng or '')))
        if not proposed.event_lat.is_finite() or not proposed.event_lng.is_finite() or not -90 <= proposed.event_lat <= 90 or not -180 <= proposed.event_lng <= 180:
            raise ValueError()
    except (ValueError, ArithmeticError):
        if proposed.event_location != booking.event_location or data.get('map_available', '1') != '0':
            raise ValidationError('Select the venue from search or drop an accurate map pin.')
        proposed.event_lat, proposed.event_lng = booking.event_lat, booking.event_lng
    venue_changed = (proposed.event_lat, proposed.event_lng, proposed.event_location) != (booking.event_lat, booking.event_lng, booking.event_location)
    quote = None
    if venue_changed:
        quote = compute_logistics_quote(proposed.event_lat, proposed.event_lng)
        if not quote['configured'] and quote['in_cavite'] is False:
            raise ValidationError('Logistics cannot be calculated for this location. Please contact our team.')
        proposed.logistics_fee_override = None  # An old venue override never follows a different venue.
        proposed.logistics_fee, proposed.logistics_distance_km = quote['total'], quote['distance_km']
    capture_booking_fee_policy(proposed, quote, refresh_logistics=venue_changed)
    if not schedule_changed:
        for key in ('included_hours', 'overtime_rate'):
            if key in saved:
                proposed.fee_policy_snapshot[key] = saved[key]
    old = get_booking_display_breakdown(booking)
    current = get_booking_price_breakdown(proposed)
    if proposed.package_type == booking.package_type:
        items, subtotal = old['items'], old['subtotal']
    else:
        parts = [p.strip() for p in proposed.package_type.split('+') if p.strip()]
        if len(current['items']) != len(parts) or len(set(map(normalize_package_part, parts))) != len(parts):
            raise ValidationError('One of the selected items is no longer available. Please update your selection.')
        # Preserve booked unit prices where a saved item quote exists.
        booked_items = {i['label']: Decimal(str(i['amount'])) for i in saved.get('catalog_items', [])}
        items = [{'label':i['label'], 'amount':booked_items.get(i['label'], i['amount'])} for i in current['items']]
        subtotal = sum((i['amount'] for i in items), Decimal('0'))
    proposed.fee_policy_snapshot['catalog_items'] = [{'label':i['label'], 'amount':str(i['amount'])} for i in items]
    proposed.total_price = (subtotal + current['service_charge'] + proposed.overtime_fee).quantize(MONEY)
    if not 0 < proposed.total_price <= Decimal('99999999.99'):
        raise ValidationError('The requested total is outside the allowed amount.')
    ensure_available(proposed)
    return proposed


def notify(change, message, admin=False):
    model = AdminNotification if admin else Notification
    model.objects.create(booking=change.booking, user=change.booking.user, message=f'Booking change request #{change.pk} for Booking #{change.booking_id}: {message}')


def audit(change, message, actor=None):
    BookingStatusLog.objects.create(booking=change.booking, old_status=change.booking.status,
        new_status=change.booking.status, changed_by=actor, notes=f'Change request #{change.pk}: {message}')


def check_current(change):
    booking = change.booking
    if booking.status not in ('pending_payment', 'confirmed'):
        raise ValidationError('The original booking is no longer active. Please contact our team.')
    if snapshot(booking) != change.original:
        raise ValidationError('The original booking has changed. The team must review and issue a new quote.')
    if pending_proof(booking, exclude_change=change):
        raise ValidationError('A submitted payment is still awaiting verification. Finish that verification before finalizing this quote.')


def issue_quote(change, actor, notes='', downgrade_ack=False, now=None):
    now = now or timezone.now()
    if len(notes) > 4000:
        raise ValidationError('Keep review notes within 4,000 characters.')
    if change.status not in ('pending_review', 'manual_review') or change.accepted_at:
        raise ValidationError('This request is no longer available for quoting.')
    check_current(change)
    proposed = proposed_booking(change)
    ensure_available(proposed)
    if min(event_start_at(proposed), event_start_at(change.booking)) <= now:
        raise ValidationError('The event start has passed. Please resolve this request directly with the customer.')
    paid = verified_paid(change.booking)
    delta = proposed.total_price - change.booking.total_price
    excess = max(paid - proposed.total_price, Decimal('0')) if delta < 0 else Decimal('0')
    if excess > 0 and (not downgrade_ack or not notes.strip()):
        raise ValidationError(f'This lower-priced booking leaves PHP {excess:,.2f} in excess payment. Explain the non-refundable excess to the customer in your message and confirm that you have reviewed it before sending the quote.')
    from .views.common import _booking_time_bounds, get_booking_display_breakdown
    start, end = _booking_time_bounds(proposed)
    zone = timezone.get_default_timezone()
    change.hold_start, change.hold_end = timezone.make_aware(start, zone), timezone.make_aware(end, zone)
    change.expires_at = min(now + timedelta(hours=SiteSettings.load().booking_payment_window_hours), event_start_at(proposed), event_start_at(change.booking))
    change.additional_due = max(delta, Decimal('0')) if paid > 0 else Decimal('0')
    change.quoted_total = proposed.total_price
    change.admin_notes, change.reviewed_by, change.downgrade_acknowledged = notes.strip(), actor, excess > 0 and downgrade_ack
    breakdown = get_booking_display_breakdown(proposed)
    change.quote = {'difference':str(delta), 'verified_paid_at_review':str(paid),
        'non_refundable_excess':str(excess),
        'items':[{'label':i['label'],'amount':str(i['amount'])} for i in breakdown['items']],
        'logistics':str(breakdown['service_charge']), 'logistics_explanation':breakdown['logistics_explanation'],
        'logistics_notes':breakdown['logistics_notes'], 'overtime':str(breakdown['overtime_fee']),
        'overtime_explanation':breakdown['overtime_explanation']}
    change.status = 'quoted'
    change.save()
    audit(change, 'Quote issued; original reservation retained.', actor)
    notify(change, 'Your quote is ready. Open Booking Details to review and accept it before the deadline.')


def apply_change(change, actor=None):
    check_current(change)
    if not change.accepted_at:
        raise ValidationError('The customer must accept the quote first.')
    booking = change.booking
    paid = change.payments.filter(payment_status='verified').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    if paid < change.additional_due:
        raise ValidationError('The required additional payment has not been verified.')
    proposed = proposed_booking(change)
    ensure_available(proposed)
    old_due = booking.payment_due_at
    for name in FIELDS:
        setattr(booking, name, getattr(proposed, name))
    # Never extend the original initial-payment deadline by requesting changes.
    if old_due:
        booking.payment_due_at = min(old_due, event_start_at(booking))
    booking.design_due_at = event_start_at(booking) - timedelta(hours=SiteSettings.load().booking_design_lead_hours)
    remove_ids = change.proposed.get('_remove_images', [])
    booking.images.filter(pk__in=[int(v) for v in remove_ids if str(v).isdigit()]).delete()
    if 'legacy' in remove_ids:
        booking.reference_image = ''
    for image in change.images.all():
        BookingImage.objects.create(booking=booking, image=image.image.name)
    booking.save()
    change.status, change.applied_at = 'applied', timezone.now()
    change.hold_start = change.hold_end = None
    change.save()
    change.payments.filter(payment_status='verified').update(applied_to_booking=True)
    total_paid = verified_paid(booking)
    booking.payment_status = 'paid' if total_paid >= booking.total_price else ('partial' if total_paid else 'pending')
    booking.save(update_fields=['payment_status'])
    audit(change, 'Customer-accepted changes applied; existing payment records retained.', actor)
    notify(change, 'Your changes are now final. Open Booking Details to see your updated reservation.')
    notify(change, 'Changes applied. Check the event design against the updated preferences and arrange any revision with the customer.', admin=True)


def expire_change(change, now=None):
    now = now or timezone.now()
    if change.status not in BookingChangeRequest.ACTIVE_STATUSES:
        return False
    terminal = change.booking.status not in ('pending_payment', 'confirmed')
    due = bool(change.expires_at and now >= change.expires_at) or min(event_start_at(change.booking), event_start_at(proposed_booking(change))) <= now
    if not terminal and not due:
        return False
    has_received = any(payment_was_received(p) for p in change.payments.all())
    if has_received:
        # Timely proof retains a quoted slot while verification is pending; escalate.
        timely = any(payment_was_received(p) and (p.received_at or p.created_at) <= change.expires_at for p in change.payments.all()) if change.expires_at else False
        future = min(event_start_at(change.booking), event_start_at(proposed_booking(change))) > now
        if not terminal and change.status == 'awaiting_payment' and timely and future:
            deadline_notice(change.booking, f'change-payment-review-{change.pk}',
                f'Change request #{change.pk} has a submitted payment awaiting verification. Verify urgently; the proposed slot remains held.')
            return False
        change.status = 'manual_review'
        deadline_notice(change.booking, f'change-manual-{change.pk}',
            f'Change request #{change.pk} needs manual payment resolution. Original reservation was not changed.')
    else:
        change.status = 'expired'
        notify(change, 'The quote expired without acceptance/payment. The proposed slot was released; your original booking was not changed.')
    change.hold_start = change.hold_end = None
    change.save()
    return True


@schedule_atomic
def process_changes(now=None):
    for change in BookingChangeRequest.objects.filter(status__in=BookingChangeRequest.ACTIVE_STATUSES).select_related('booking'):
        expire_change(change, now)


def change_difference_rows(change):
    rows = []
    labels = {'event_type':'Event type', 'event_date':'Date', 'event_time':'Start time', 'event_end_time':'End time', 'event_end_date':'End date',
        'event_location':'Venue address', 'venue_landmark':'Landmark', 'package_type':'Package / extras',
        'event_lat':'Venue latitude', 'event_lng':'Venue longitude', 'design_theme':'Theme', 'color_palette':'Colors', 'motto_text':'Backdrop text', 'special_requests':'Notes'}
    if change:
        for name, label in labels.items():
            before, after = change.original.get(name), change.proposed.get(name)
            if name == 'special_requests':
                from .views.common import remove_end_time_tag
                before, after = remove_end_time_tag(before or ''), remove_end_time_tag(after or '')
            if before != after:
                if name.endswith('time'):
                    before = time.fromisoformat(before).strftime('%I:%M %p').lstrip('0') if before else '—'
                    after = time.fromisoformat(after).strftime('%I:%M %p').lstrip('0') if after else '—'
                rows.append({'label':label, 'before':before or '—', 'after':after or '—'})
    return rows


def change_context(booking, change=None):
    if change is None:
        change = max(booking.change_requests.all(),
            key=lambda row:(row.status in BookingChangeRequest.ACTIVE_STATUSES, row.created_at, row.pk), default=None)
    if change and change.booking_id != booking.pk:
        raise ValueError('Change request does not belong to this booking.')
    allowed, reason = eligibility(booking)
    rows = change_difference_rows(change)
    payment_state = change_payment_state(change) if change else {}
    return {'change_request':change, 'change_rows':rows, 'can_request_changes':allowed,
        **(change_payment_summary(change) if change else {}),
        **payment_state,
        'change_status_label': 'Payment under review' if change and change.status == 'awaiting_payment'
            and payment_state['change_payment_under_review'] else '',
        'change_unavailable_reason':reason, 'change_cutoff_hours':SiteSettings.load().booking_change_cutoff_hours}
