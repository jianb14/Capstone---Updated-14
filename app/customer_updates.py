"""Incremental alerts for the existing application-owned notification messages."""
import re

from django.core import signing
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

from .models import Notification

_SALT = 'customer-update-bar'


def update_session(request):
    return request.session.get('customer_updates_login', str(request.user.last_login or ''))


def update_cursor(user_id, position):
    return signing.dumps([user_id, position], salt=_SALT, compress=True)


def notification_update(notice):
    """Only explicit booking events qualify; arbitrary notes never become alerts."""
    booking = notice.booking
    if not booking or notice.concern_id or booking.user_id != notice.user_id:
        return None
    key = booking.pk
    message = notice.message
    details = f"{reverse('customer_profile')}?booking_id={key}&modal=details&from_notif=1"
    event, title, body, action, kind, target = '', '', '', 'View booking', 'success', details
    if re.match(rf'^Your backdrop design for booking #{key} is ready!', message, re.I):
        event, title = 'design_ready', 'Your event design is ready.'
        body, action = f'Booking #{key}: view and download your design.', 'View design'
        target = details.replace('modal=details', 'modal=design')
    elif re.match(rf'^Great news! Your booking #{key} has been approved!', message, re.I):
        event, title = 'booking_approved', f'Booking #{key} approved.'
        body = 'Proceed to payment to confirm your reservation.'
    elif re.match(rf'^Hooray! Your booking #{key} is now CONFIRMED!', message, re.I):
        event, title, body = 'booking_confirmed', f'Booking #{key} confirmed.', 'Your reservation is confirmed.'
    elif re.match(rf"^We're sorry, but your booking #{key}(?: on \d{{4}}-\d{{2}}-\d{{2}})? was not approved\b", message, re.I):
        event, title, body, kind = 'booking_declined', f'Booking #{key} was not approved.', 'View the reason and next steps.', 'error'
    elif re.match(rf'^(?:Your )?Booking #{key} (?:has been |was |is now )?cancel(?:led|ed)\b', message, re.I):
        event, title, body, kind = 'booking_cancelled', f'Booking #{key} cancelled.', 'View your booking details.', 'warning'
    elif re.match(rf'^Booking #{key} expired\.', message, re.I):
        event, title, body, kind = 'booking_expired', f'Booking #{key} expired.', 'View the deadline and reservation details.', 'warning'
    else:
        payment = re.match(rf'^Your payment of PHP ([\d,]+\.\d{{2}}) for Booking #{key} (has been verified|was rejected)\.', message, re.I)
        change = re.match(rf'^Booking change request #\d+ for Booking #{key}: (.*)', message, re.I | re.S)
        if payment:
            from .context_processors import _customer_notif_target_url
            verified = payment[2].lower() == 'has been verified'
            event = 'payment_verified' if verified else 'payment_rejected'
            title = 'Payment verified.' if verified else 'Payment rejected.'
            body = f'Your PHP {payment[1]} payment for Booking #{key} has been verified.' if verified else f'Booking #{key}: view the reason and resubmit your payment.'
            action, kind, target = 'View payment', 'success' if verified else 'error', _customer_notif_target_url(notice)
        elif change:
            text = change[1]
            if text.startswith('Your quote is ready.'):
                event, title, body, action = 'change_quote', 'Your revised quote is ready.', f'Booking #{key}: review and accept it before the deadline.', 'Review quote'
            elif text.startswith('Your changes are now final.'):
                event, title, body = 'change_approved', 'Your booking changes are confirmed.', f'Booking #{key}: your accepted changes have been applied.'
            elif text.startswith('The requested change was declined:'):
                event, title, body, kind = 'change_declined', 'Your change request was declined.', f'Booking #{key}: your original reservation is unchanged.', 'error'
            elif text.startswith('The quote expired without acceptance/payment.'):
                event, title, body, kind = 'change_expired', 'Your change quote expired.', f'Booking #{key}: your original reservation is unchanged.', 'warning'
            elif text.startswith('Your additional payment was rejected:'):
                event, title, body, kind = 'payment_rejected', 'Additional payment rejected.', f'Booking #{key}: review the reason and quote deadline.', 'error'
    if not event:
        return None
    if event == 'booking_approved':
        from .context_processors import _customer_notif_target_url
        target = _customer_notif_target_url(notice)
    return {'id': notice.pk, 'event': event, 'title': title, 'description': body,
        'action': action, 'kind': kind, 'target_url': target, 'message': message,
        'created_at': notice.created_at.isoformat(), 'is_read': notice.is_read,
        'read_url': reverse('mark_customer_notification_read', args=[notice.pk])}


def customer_update_payload(user, cursor=None):
    owned = Notification.objects.filter(user=user)
    head = owned.aggregate(position=Max('pk'))['position'] or 0
    after = head
    if cursor:
        try:
            owner, after = signing.loads(cursor, salt=_SALT)
            if owner != user.pk or type(after) is not int or not 0 <= after <= 9223372036854775807:
                raise ValueError
        except (signing.BadSignature, ValueError, TypeError, KeyError):
            raise ValueError('Invalid notification update position.') from None
    items, delivery_ids = [], []
    # Persistent delivery state includes offline notices below the browser cursor.
    incoming = owned.filter(pk__lte=head, is_read=False, bar_shown_at__isnull=True, booking__user=user).select_related('booking').prefetch_related('booking__payments').order_by('-pk')
    for notice in incoming.iterator(chunk_size=200):
        item = notification_update(notice)
        if item:
            delivery_ids.append(notice.pk)
            if len(items) < 20:
                items.append(item)
    return {'updates': items, 'update_count': len(delivery_ids),
        'delivery_token': signing.dumps([user.pk, delivery_ids], salt=_SALT+'-delivery', compress=True) if delivery_ids else '',
        'updates_cursor': update_cursor(user.pk, max(after, head)),
        'unread_count': owned.filter(is_read=False).count()}


def acknowledge_customer_updates(user, token):
    """Acknowledge precisely the displayed batch; leave bell read state alone."""
    try:
        owner, keys = signing.loads(token, salt=_SALT+'-delivery')
        if owner != user.pk or not isinstance(keys, list) or not keys or any(
                type(key) is not int or not 0 < key <= 9223372036854775807 for key in keys):
            raise ValueError
    except (signing.BadSignature, ValueError, TypeError, KeyError):
        raise ValueError('Invalid notification delivery receipt.') from None
    shown_at = timezone.now()
    for start in range(0, len(keys), 500):
        Notification.objects.filter(user=user, pk__in=keys[start:start+500],
            bar_shown_at__isnull=True).update(bar_shown_at=shown_at)
