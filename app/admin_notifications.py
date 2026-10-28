"""One bounded, stable feed for legacy bookings and newer admin notifications."""
from django.core import signing
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.dateparse import parse_datetime

from .models import AdminNotification, Booking, ConcernTicket


def concern_counts():
    return ConcernTicket.objects.aggregate(total=Count('id'), **{
        status: Count('id', filter=Q(status=status)) for status, _ in ConcernTicket.STATUS_CHOICES})


def unread_count():
    return (Booking.objects.filter(admin_notified=False, admin_notif_hidden=False).count()
            + AdminNotification.objects.filter(is_read=False, is_hidden=False).count())


def notification_rows(cursor=None):
    from .context_processors import _admin_notif_target_url
    boundary = None
    if cursor:
        try:
            stamp, kind, key = signing.loads(cursor, salt='admin-notifications')
            stamp = parse_datetime(stamp)
            if stamp is None or kind not in ('b', 'n') or type(key) is not int or key < 1:
                raise ValueError
            boundary = stamp, kind, key
        except (signing.BadSignature, ValueError, TypeError):
            raise ValueError('Invalid notification cursor.') from None
    merged = []
    sources = [('b', Booking.objects.filter(admin_notif_hidden=False).select_related('user')),
               ('n', AdminNotification.objects.filter(is_hidden=False).select_related('user', 'booking', 'concern'))]
    for kind, queryset in sources:
        if boundary:
            stamp, previous_kind, key = boundary
            before = Q(created_at__lt=stamp)
            if kind < previous_kind:
                before |= Q(created_at=stamp)
            elif kind == previous_kind:
                before |= Q(created_at=stamp, pk__lt=key)
            queryset = queryset.filter(before)
        for row in queryset.order_by('-created_at', '-pk')[:21]:
            booking = row if kind == 'b' else row.booking
            user = row.user or getattr(booking, 'user', None)
            concern_id = getattr(row, 'concern_id', None)
            message = f'booked a {row.event_type}' if kind == 'b' else row.message
            target = (f"{reverse('admin_concerns')}?concern_id={concern_id}" if concern_id else
                      _admin_notif_target_url('booking' if kind == 'b' else 'event', message, booking))
            merged.append({'id': f'{kind}_{row.pk}', 'raw_id': row.pk, 'kind': kind,
                'type': 'booking' if kind == 'b' else 'event', 'booking': booking, 'user': user,
                'message': message, 'created_at': row.created_at,
                'is_read': row.admin_notified if kind == 'b' else row.is_read, 'target_url': target})
    merged.sort(key=lambda row: (row['created_at'], row['kind'], row['raw_id']), reverse=True)
    rows = merged[:20]
    next_cursor = None
    if len(merged) > 20:
        last = rows[-1]
        next_cursor = signing.dumps([last['created_at'].isoformat(), last['kind'], last['raw_id']], salt='admin-notifications')
    return rows, next_cursor
