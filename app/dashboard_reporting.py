"""The dashboard combines current operations with an explicitly filtered report."""
from datetime import timedelta
from urllib.parse import urlencode

from django.db.models import Count, F, Q
from django.urls import reverse
from django.utils import timezone

from .analytics_reporting import REPORT_ZONE, build_report, resolve_filters
from .models import Booking, ConcernTicket, Payment


def dashboard_greeting(stamp):
    hour = timezone.localtime(stamp, REPORT_ZONE).hour
    return 'Good morning' if 5 <= hour < 12 else 'Good afternoon' if 12 <= hour < 18 else 'Good evening'


def dashboard_filters(params):
    query = params.copy()
    # A dashboard starts with a useful operational week; Analytics keeps its
    # existing 30-day default. Explicit date ranges take priority over defaults.
    if not any(query.get(key) for key in ('filter_preset', 'start_date', 'end_date')):
        query['filter_preset'] = '7days'
    query['tab'] = 'overview'
    return resolve_filters(query)


def current_operations():
    from .views.change_management import change_queue_summary
    from .views.payments import _abandoned_paymongo_payment_query

    now = timezone.localtime(timezone=REPORT_ZONE)
    today, end = now.date(), now.date() + timedelta(days=6)
    counts = Booking.objects.aggregate(
        approvals=Count('pk', filter=Q(status='pending')),
        cancellations=Count('pk', filter=Q(status='cancel_requested')),
    )
    counts['payments'] = Payment.objects.filter(payment_status='pending').exclude(_abandoned_paymongo_payment_query()).count()
    counts['changes'] = change_queue_summary()['needs_review']
    counts['concerns'] = ConcernTicket.objects.filter(status='new').count()
    booking_url = reverse('admin_booking_list')
    queues = [
        {'key': 'approvals', 'label': 'Bookings awaiting approval', 'note': 'Review new booking requests',
         'url': booking_url + '?status=pending', 'icon': 'calendar', 'accent': 'blue'},
        {'key': 'payments', 'label': 'Payments to verify', 'note': 'Check submitted payment records',
         'url': reverse('admin_payment_list'), 'icon': 'wallet', 'accent': 'amber'},
        {'key': 'changes', 'label': 'Booking changes to review', 'note': 'Review changes or additional payments',
         'url': booking_url + '?tab=requests', 'icon': 'change', 'accent': 'teal'},
        {'key': 'cancellations', 'label': 'Cancellation requests', 'note': 'Confirm the next step with the customer',
         'url': booking_url + '?status=cancel_requested', 'icon': 'cancel', 'accent': 'red'},
        {'key': 'concerns', 'label': 'New customer concerns', 'note': 'Respond to a newly submitted concern',
         'url': reverse('admin_concerns') + '?concern_status=new', 'icon': 'message', 'accent': 'amber'},
    ]
    for row in queues:
        row['count'] = counts[row['key']]
    upcoming = Booking.objects.filter(status__in=('confirmed', 'cancel_requested'), event_date__range=(today, end))
    events = list(upcoming.select_related('user').order_by('event_date', F('event_time').asc(nulls_last=True), 'pk')[:5])
    for booking in events:
        booking.is_today = booking.event_date == today
    return {'queues': queues, 'queue_counts': counts, 'has_actions': any(counts.values()), 'upcoming_events': events,
        'upcoming_count': upcoming.count(), 'today_event_count': upcoming.filter(event_date=today).count(),
        'operations_now': now, 'operations_end': end,
        'upcoming_url': reverse('admin_calendar')}


def build_dashboard(filters):
    report = build_report(filters, include_insights=False)
    operations = current_operations()
    analytics_params = filters.params()
    analytics_params.pop('filter_preset')
    analytics_params['comparison'] = filters.comparison
    # All six figures and both graphs use precisely the same booking cohort
    # as Analytics. Operational queues above have their own, labelled scope.
    return {**report, **operations, 'dashboard_greeting': dashboard_greeting(operations['operations_now']),
        'dashboard_presets': [('today', 'Today'), ('7days', '7 days'), ('30days', '30 days'),
            ('month', 'This month'), ('all', 'All time')],
        'analytics_url': reverse('admin_analytics') + '?' + urlencode(analytics_params)}
