"""Read-only analytics for one explicit booking cohort and comparison window."""
from bisect import bisect_right
from calendar import monthrange
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db.models import Max, Min, Q, Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from .models import Booking, Payment

REPORT_ZONE = ZoneInfo('Asia/Manila')
ZERO = Decimal('0.00')
PRESETS = {'today', '7days', '30days', 'month', 'all'}
STATUS_LABELS = dict(Booking.STATUS_CHOICES)
STATUS_COLORS = {'pending': 'amber', 'pending_payment': 'amber', 'confirmed': 'blue',
    'completed': 'green', 'cancel_requested': 'teal', 'cancelled': 'red', 'expired': 'muted'}


@dataclass(frozen=True)
class ReportFilters:
    basis: str
    event_type: str
    preset: str
    start: date
    end: date
    previous_start: date | None
    previous_end: date | None
    event_options: tuple
    tab: str = 'overview'
    comparison: str = 'period'

    @property
    def basis_label(self):
        return 'Event date' if self.basis == 'event' else 'Booking submission date'

    @property
    def period_label(self):
        return date_label(self.start, self.end)

    @property
    def comparison_label(self):
        if self.previous_start is None:
            if self.comparison == 'none':
                return 'Previous-period comparison is disabled for this report.'
            return 'No earlier comparison period is available.'
        return 'Compared with ' + date_label(self.previous_start, self.previous_end)

    def params(self):
        return {'date_basis': self.basis, 'event_type': self.event_type, 'filter_preset': self.preset,
            'start_date': self.start.isoformat(), 'end_date': self.end.isoformat(), 'tab': self.tab}


def date_label(start, end):
    if start == end:
        return start.strftime('%b %d, %Y')
    return start.strftime('%b %d, %Y') + ' – ' + end.strftime('%b %d, %Y')


def money(value):
    return Decimal(value or 0).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def resolve_filters(params):
    requested_comparison = params.get('comparison', 'period')
    if requested_comparison not in ('period', 'month', 'none'):
        raise ValidationError('Choose a valid comparison mode.')
    tab = params.get('tab', 'overview')
    if tab not in ('overview', 'bookings', 'payments', 'customers'):
        raise ValidationError('Choose a valid analytics view.')
    basis = params.get('date_basis', 'event')
    if basis not in ('event', 'created'):
        raise ValidationError('Choose a valid date basis.')
    event_options = tuple(Booking.objects.order_by('event_type').values_list('event_type', flat=True).distinct())
    event_type = params.get('event_type', 'all')
    if event_type != 'all' and event_type not in event_options:
        raise ValidationError('Choose an event type from the list.')
    preset = params.get('filter_preset', '')
    if preset and preset not in PRESETS:
        raise ValidationError('Choose a valid reporting period.')
    raw_start, raw_end = params.get('start_date', ''), params.get('end_date', '')
    today = timezone.localdate(timezone=REPORT_ZONE)
    if preset == 'today':
        start = end = today
    elif preset in ('7days', '30days'):
        start, end = today - timedelta(days=6 if preset == '7days' else 29), today
    elif preset == 'month':
        start, end = today.replace(day=1), today
    elif preset == 'all':
        queryset = Booking.objects.all()
        if event_type != 'all':
            queryset = queryset.filter(event_type=event_type)
        field = 'event_date' if basis == 'event' else 'created_at'
        bounds = queryset.aggregate(first=Min(field), last=Max(field))
        def day(value):
            return timezone.localtime(value, REPORT_ZONE).date() if isinstance(value, datetime) else value
        start, end = day(bounds['first']) or today, day(bounds['last']) or today
        payments = Payment.objects.filter(payment_status='verified', applied_to_booking=True)
        if event_type != 'all':
            payments = payments.filter(booking__event_type=event_type)
        receipt_bounds = payments.annotate(receipt=Coalesce('received_at', 'paid_at')).aggregate(first=Min('receipt'), last=Max('receipt'))
        if receipt_bounds['first']:
            start = min(start, day(receipt_bounds['first'])) if bounds['first'] else day(receipt_bounds['first'])
            end = max(end, day(receipt_bounds['last'])) if bounds['last'] else day(receipt_bounds['last'])
    elif raw_start or raw_end:
        try:
            start, end = parse_date(raw_start), parse_date(raw_end)
        except (ValueError, TypeError):
            start = end = None
        if start is None or end is None:
            raise ValidationError('Enter both a valid start date and end date.')
    else:
        preset = '30days'
        start, end = today - timedelta(days=29), today
    if start > end:
        raise ValidationError('The start date cannot be after the end date.')
    previous_start = previous_end = None
    comparison = 'none' if preset == 'all' else 'month' if preset == 'month' else requested_comparison if not preset else 'period'
    if comparison == 'month' and (start.day != 1 or (start.year, start.month) != (end.year, end.month)):
        raise ValidationError('A month-to-date comparison must start on the first day of the same month.')
    if comparison != 'none':
        try:
            if comparison == 'month':
                previous_end = start - timedelta(days=1)
                previous_start = previous_end.replace(day=1)
                previous_end = previous_end.replace(day=min(end.day, previous_end.day))
            else:
                previous_end = start - timedelta(days=1)
                previous_start = previous_end - (end - start)
        except (OverflowError, ValueError):
            previous_start = previous_end = None
    return ReportFilters(basis, event_type, preset, start, end, previous_start, previous_end, event_options, tab, comparison)


def window_query(basis, start, end):
    if basis == 'event':
        return Q(event_date__range=(start, end))
    beginning = timezone.make_aware(datetime.combine(start, time.min), REPORT_ZONE)
    if end == date.max:
        return Q(created_at__gte=beginning, created_at__lte=timezone.make_aware(datetime.combine(end, time.max), REPORT_ZONE))
    after = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), REPORT_ZONE)
    return Q(created_at__gte=beginning, created_at__lt=after)


def selected_bookings(filters):
    queryset = Booking.objects.filter(window_query(filters.basis, filters.start, filters.end))
    return queryset if filters.event_type == 'all' else queryset.filter(event_type=filters.event_type)


def _buckets(start, end):
    days = (end - start).days + 1
    mode = 'day' if days <= 31 else 'week' if days <= 180 else 'month' if days <= 731 else 'year'
    year_step = max(1, (end.year - start.year + 48) // 48)
    result = []
    cursor = start
    while cursor <= end:
        if mode == 'day':
            stop = cursor
        elif mode == 'week':
            stop = min(end, cursor + timedelta(days=min(6, (end - cursor).days)))
        elif mode == 'month':
            stop = min(end, cursor.replace(day=monthrange(cursor.year, cursor.month)[1]))
        else:
            stop = min(end, date(min(end.year, cursor.year + year_step - 1), 12, 31))
        label = cursor.strftime('%b %d') if mode in ('day', 'week') else cursor.strftime('%b %Y') if mode == 'month' else str(cursor.year)
        result.append({'start': cursor, 'end': stop, 'label': label, 'range': date_label(cursor, stop)})
        if stop == end:
            break
        cursor = stop + timedelta(days=1)
    return mode, result


def _new_window(size):
    return {'count': 0, 'completed': 0, 'cancelled': 0, 'value': ZERO, 'collections': ZERO,
        'customers': set(), 'statuses': Counter(), 'events': Counter(), 'setups': Counter(),
        'event_values': defaultdict(lambda: ZERO), 'event_collections': defaultdict(lambda: ZERO),
        'trend': {'bookings': [0] * size, 'completed_value': [ZERO] * size, 'collections': [ZERO] * size}}


def _delta(current, previous):
    if previous is None:
        return {'direction': 'flat', 'text': 'All-time total', 'percent': None}
    change = current - previous
    direction = 'up' if change > 0 else 'down' if change < 0 else 'flat'
    if previous == 0:
        text = 'No change; previous period was 0' if current == 0 else 'Previous period was 0; no % baseline'
        percent = None
    else:
        percent = round(float(change / abs(previous) * 100), 1)
        text = f'{percent:+.1f}% vs previous period' if percent else 'No change vs previous period'
    return {'direction': direction, 'text': text, 'percent': percent}


def _ranked(counter, limit=6):
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0].casefold()))
    rows = [{'label': label, 'count': count, 'members': [label]} for label, count in ordered[:limit]]
    if len(ordered) > limit:
        rows.append({'label': 'Other selections (grouped)', 'count': sum(count for _, count in ordered[limit:]),
            'members': [label for label, _ in ordered[limit:]]})
    return rows


def build_report(filters, *, include_insights=True):
    mode, buckets = _buckets(filters.start, filters.end)
    starts = [bucket['start'] for bucket in buckets]
    current, previous = _new_window(len(buckets)), _new_window(len(buckets))
    selected_records = []
    condition = window_query(filters.basis, filters.start, filters.end)
    if filters.previous_start:
        condition |= window_query(filters.basis, filters.previous_start, filters.previous_end)
    queryset = Booking.objects.filter(condition)
    if filters.event_type != 'all':
        queryset = queryset.filter(event_type=filters.event_type)
    # One grouped SQL read supplies both periods, avoiding duplicated booking
    # counts from payment joins and keeping each chart/KPI on the same snapshot.
    rows = queryset.order_by().values('id', 'user_id', 'event_date', 'event_time', 'created_at', 'event_type',
        'package_type', 'status', 'total_price').annotate(credited=Coalesce(Sum('payments__amount',
            filter=Q(payments__payment_status='verified', payments__applied_to_booking=True)),
            Value(ZERO), output_field=DecimalField(max_digits=20, decimal_places=2)))
    for row in rows.iterator(chunk_size=2000):
        day = row['event_date'] if filters.basis == 'event' else timezone.localtime(row['created_at'], REPORT_ZONE).date()
        in_current = filters.start <= day <= filters.end
        if in_current and include_insights:
            selected_records.append(row)
        window = current if in_current else previous
        mapped = day if in_current else filters.start + (day - filters.previous_start)
        index = bisect_right(starts, mapped) - 1
        status = row['status']; completed = status == 'completed'
        value = money(row['total_price']) if completed else ZERO
        collections = money(row['credited'])
        window['count'] += 1; window['completed'] += completed; window['cancelled'] += status == 'cancelled'
        window['value'] += value; window['collections'] += collections; window['customers'].add(row['user_id'])
        window['statuses'][status] += 1
        event = row['event_type'].strip() or 'Unspecified event'
        setup = (row['package_type'] or '').split('+')[0].strip() or 'Unspecified setup'
        window['events'][event] += 1; window['setups'][setup] += 1
        window['event_values'][event] += value; window['event_collections'][event] += collections
        if 0 <= index < len(buckets):
            window['trend']['bookings'][index] += 1
            window['trend']['completed_value'][index] += value
            window['trend']['collections'][index] += collections
    total = current['count']
    completion_rate = round(current['completed'] / total * 100, 1) if total else 0
    cancellation_rate = round(current['cancelled'] / total * 100, 1) if total else 0
    average = money(current['value'] / current['completed']) if current['completed'] else ZERO
    compared = filters.previous_start is not None
    comparison = {key: _delta(current[key], previous[key] if compared else None) for key in ('count', 'value', 'collections')}
    statuses = [{'key': key, 'label': STATUS_LABELS.get(key, 'Unknown status'), 'count': count,
        'share': round(count / total * 100, 1) if total else 0, 'color': STATUS_COLORS.get(key, 'muted')}
        for key, count in sorted(current['statuses'].items(), key=lambda pair: list(STATUS_LABELS).index(pair[0]) if pair[0] in STATUS_LABELS else 99)]
    previous_ranges = []
    for bucket in buckets:
        if compared:
            beginning = filters.previous_start + (bucket['start'] - filters.start)
            ending = min(filters.previous_end, filters.previous_start + (bucket['end'] - filters.start))
            previous_ranges.append(date_label(beginning, ending) if beginning <= ending else None)
        else:
            previous_ranges.append(None)
    series = {}
    for key in current['trend']:
        series[key] = {'current': [float(value) if isinstance(value, Decimal) else value for value in current['trend'][key]],
            'previous': [(float(value) if isinstance(value, Decimal) else value) if previous_ranges[i] else None
                for i, value in enumerate(previous['trend'][key])] if compared else []}
    events = _ranked(current['events'])
    setups = _ranked(current['setups'])
    for event in events:
        event['value'] = sum((current['event_values'][name] for name in event['members']), ZERO)
        event['collections'] = sum((current['event_collections'][name] for name in event['members']), ZERO)
    payload = {'trend': {'labels': [bucket['label'] for bucket in buckets], 'ranges': [bucket['range'] for bucket in buckets],
        'previous_ranges': previous_ranges, 'series': series, 'bucket': mode, 'has_comparison': compared},
        'statuses': statuses, 'events': events, 'setups': setups, 'total': total}
    kpis = [
        {'key': 'bookings', 'label': 'Bookings', 'value': f'{total:,}', 'accent': 'blue', 'icon': 'calendar',
            'note': 'All statuses in the selected period', 'delta': comparison['count']},
        {'key': 'completed_value', 'label': 'Completed booking value', 'value': f'₱{current["value"]:,.2f}', 'accent': 'green', 'icon': 'check',
            'note': f'Average completed value: ₱{average:,.2f}', 'delta': comparison['value']},
        {'key': 'collections', 'label': 'Verified collections', 'value': f'₱{current["collections"]:,.2f}', 'accent': 'teal', 'icon': 'wallet',
            'note': 'Verified payments applied to these bookings', 'delta': comparison['collections']},
        {'key': 'completion', 'label': 'Completion rate', 'value': f'{completion_rate:.1f}%', 'accent': 'green', 'icon': 'check',
            'note': f'{current["completed"]:,} completed out of {total:,} bookings'},
        {'key': 'cancellation', 'label': 'Cancellation rate', 'value': f'{cancellation_rate:.1f}%', 'accent': 'red', 'icon': 'cancel',
            'note': f'{current["cancelled"]:,} cancelled out of {total:,} bookings'},
        {'key': 'customers', 'label': 'Customers with bookings', 'value': f'{len(current["customers"]):,}', 'accent': 'amber', 'icon': 'user',
            'note': 'Distinct customers in these bookings'},
    ]
    # Export resolved dates, rather than a relative Today preset that can change
    # at midnight after the current report has been displayed.
    export_params = filters.params(); export_params.pop('filter_preset')
    export_params['comparison'] = filters.comparison
    from .analytics_insights import build_insights, card
    insights = build_insights(filters, selected_records) if include_insights else {}
    booking_kpis = [kpis[0], kpis[3], kpis[4],
        card('expiry', 'Expired booking rate', f'{insights["expired_rate"]:.1f}%', 'amber',
            f'{insights["expired"]:,} expired out of {total:,} bookings', 'calendar'),
        card('committed', 'Committed events', f'{insights["committed_count"]:,}', 'teal',
            'Confirmed, cancel-requested or completed bookings', 'check'),
        card('arch_selections', 'Entrance arch selections', f'{sum(row["count"] for row in insights["offers"]["arches"]):,}', 'blue',
            'Recorded selections across all booking statuses', 'chart')] if include_insights else []
    payload['insights'] = insights
    params = filters.params()
    tabs = [{'key': key, 'label': label, 'url': reverse('admin_analytics') + '?' + urlencode({**params, 'tab': key})}
        for key, label in [('overview', 'Overview'), ('bookings', 'Bookings & Demand'), ('payments', 'Payments'), ('customers', 'Customers')]]
    return {'filters': filters, 'kpis': kpis, 'charts': payload, 'statuses': statuses, 'event_rows': events,
        'setup_rows': setups, 'total_bookings': total, 'completed_count': current['completed'],
        'cancelled_count': current['cancelled'], 'completed_value': current['value'],
        'verified_collections': current['collections'], 'completion_rate': completion_rate,
        'cancellation_rate': cancellation_rate, 'average_completed_value': average,
        'customer_count': len(current['customers']), 'comparison': comparison,
        'previous_count': previous['count'] if compared else None,
        'previous_completed_value': previous['value'] if compared else None,
        'previous_verified_collections': previous['collections'] if compared else None,
        'insights': insights, 'booking_kpis': booking_kpis, 'tabs': tabs,
        'export_url': reverse('admin_analytics_export_pdf') + '?' + urlencode(export_params),
        'excel_url': reverse('admin_analytics_export_excel') + '?' + urlencode(export_params),
        'generated_at': timezone.localtime(timezone=REPORT_ZONE)}
