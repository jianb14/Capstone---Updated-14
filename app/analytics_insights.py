"""Additional report views derived from saved bookings and credited payments."""
import re
from bisect import bisect_right
from collections import Counter, defaultdict
from decimal import Decimal

from django.db.models import Min, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import AddOn, AdditionalOnly, Booking, Package, Payment, Review
from .analytics_reporting import (REPORT_ZONE, ZERO, _buckets, _delta, _ranked,
    date_label, money, window_query)

PAYABLE = {'pending_payment', 'confirmed', 'cancel_requested', 'completed'}
COMMITTED = {'confirmed', 'cancel_requested', 'completed'}


def card(key, label, value, accent, note, icon='chart'):
    return {'key': key, 'label': label, 'value': value, 'accent': accent, 'note': note, 'icon': icon}


def _receipt_query(start, end):
    # Reuse the Philippine midnight bounds, on the annotated receipt timestamp.
    query = window_query('created', start, end)
    return Q(**{key.replace('created_at', 'report_received_at'): value for key, value in query.children})


def selected_collections(filters):
    queryset = Payment.objects.filter(payment_status='verified', applied_to_booking=True)
    if filters.event_type != 'all':
        queryset = queryset.filter(booking__event_type=filters.event_type)
    return queryset.annotate(report_received_at=Coalesce('received_at', 'paid_at')).filter(
        _receipt_query(filters.start, filters.end))


def collections_report(filters):
    """Receipt-date cash collection view, independent of booking scheduling dates."""
    mode, buckets = _buckets(filters.start, filters.end)
    starts = [row['start'] for row in buckets]
    current = [ZERO] * len(buckets); previous = [ZERO] * len(buckets)
    totals = [ZERO, ZERO]; methods = defaultdict(lambda: ZERO)
    count = fallback = undated = 0
    queryset = Payment.objects.filter(payment_status='verified', applied_to_booking=True)
    if filters.event_type != 'all':
        queryset = queryset.filter(booking__event_type=filters.event_type)
    condition = _receipt_query(filters.start, filters.end) | Q(report_received_at__isnull=True)
    if filters.previous_start:
        condition |= _receipt_query(filters.previous_start, filters.previous_end)
    rows = queryset.annotate(report_received_at=Coalesce('received_at', 'paid_at')).filter(condition).values(
        'amount', 'payment_method', 'report_received_at', 'received_at')
    for row in rows.iterator(chunk_size=2000):
        stamp = row['report_received_at']
        if stamp is None:
            undated += 1
            continue
        day = timezone.localtime(stamp, REPORT_ZONE).date()
        selected = filters.start <= day <= filters.end
        group = 0 if selected else 1
        amount = money(row['amount']); totals[group] += amount
        mapped = day if selected else filters.start + (day - filters.previous_start)
        index = bisect_right(starts, mapped) - 1
        if 0 <= index < len(buckets):
            (current if selected else previous)[index] += amount
        if selected:
            count += 1; fallback += row['received_at'] is None
            methods[row['payment_method']] += amount
    labels = dict(Payment.PAYMENT_METHOD_CHOICES)
    method_rows = [{'label': labels.get(key, key or 'Unspecified method'), 'value': money(value)}
        for key, value in sorted(methods.items(), key=lambda item: (-item[1], item[0]))]
    previous_ranges = []
    for bucket in buckets:
        if filters.previous_start:
            begin = filters.previous_start + (bucket['start'] - filters.start)
            end = min(filters.previous_end, filters.previous_start + (bucket['end'] - filters.start))
            previous_ranges.append(date_label(begin, end) if begin <= end else None)
        else:
            previous_ranges.append(None)
    return {'value': totals[0], 'count': count, 'fallback_count': fallback, 'undated_count': undated,
        'previous_value': totals[1] if filters.previous_start else None,
        'has_trend': any(current) or any(previous),
        'delta': _delta(totals[0], totals[1] if filters.previous_start else None), 'methods': method_rows,
        'trend': {'labels': [row['label'] for row in buckets], 'ranges': [row['range'] for row in buckets],
            'previous_ranges': previous_ranges, 'current': [float(value) for value in current],
            'previous': [float(value) if previous_ranges[i] else None for i, value in enumerate(previous)]
                if filters.previous_start else []}}


def offer_demand(records):
    categories = {'packages': set(Package.objects.values_list('name', flat=True)),
        'arches': set(AddOn.objects.values_list('name', flat=True)),
        'stands': set(AdditionalOnly.objects.values_list('name', flat=True))}
    lookup = defaultdict(list)
    for category, names in categories.items():
        for name in names:
            lookup[name.casefold().strip()].append((category, name.strip()))
    counts = {category: Counter() for category in categories}
    completed_values = {category: defaultdict(lambda: ZERO) for category in categories}
    unclassified = 0
    for row in records:
        seen = set()
        for part in re.split(r'\s+\+\s+', row['package_type'] or ''):
            name = re.sub(r'\s*\(solo\)\s*$', '', part, flags=re.I).strip()
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            matches = lookup.get(name.casefold(), [])
            if len({category for category, _ in matches}) > 1:
                unclassified += 1; continue
            matched = matches[0] if matches else None
            category = matched[0] if matched else None
            if matched:
                name = matched[1]
            if category is None:
                # Historical selections survive catalog removal; unfamiliar names
                # remain unclassified rather than being guessed as packages.
                for key, pattern in [('packages', r'^package\b'), ('arches', r'^(entrance|arch)\b'),
                        ('stands', r'^(welcome\s+stand|stand)\b')]:
                    if re.match(pattern, name, re.I):
                        category = key; break
            if category is None:
                unclassified += 1; continue
            counts[category][name] += 1
            if row['status'] == 'completed':
                completed_values[category][name] += money(row['total_price'])
    result = {}
    for category, counter in counts.items():
        result[category] = _ranked(counter)
        for row in result[category]:
            row['completed_value'] = sum((completed_values[category][name] for name in row['members']), ZERO)
    result['unclassified'] = unclassified
    return result


def customer_report(records):
    # First-time/returning describes completed events, never future reservations.
    today = timezone.localdate(timezone=REPORT_ZONE)
    completed = [row for row in records if row['status'] == 'completed' and row['event_date'] <= today]
    users = {row['user_id'] for row in completed}
    first = dict(Booking.objects.filter(status='completed', user_id__in=users, event_date__lte=today)
        .values('user_id').annotate(first=Min('event_date')).values_list('user_id', 'first'))
    selected_first = {}
    for row in completed:
        user = row['user_id']
        selected_first[user] = min(selected_first.get(user, row['event_date']), row['event_date'])
    returning = sum(first[user] < day for user, day in selected_first.items())
    new = len(users) - returning
    distribution = Counter(); reviewed = set()
    for row in Review.objects.filter(booking_id__in=[row['id'] for row in completed], rating__range=(1, 5)).values('booking_id', 'rating').iterator(chunk_size=2000):
        distribution[row['rating']] += 1; reviewed.add(row['booking_id'])
    review_count = sum(distribution.values())
    average = money(sum(rating * count for rating, count in distribution.items()) / Decimal(review_count)) if review_count else None
    return {'completed_customers': len(users), 'new': new, 'returning': returning,
        'returning_rate': round(returning / len(users) * 100, 1) if users else None,
        'reviews': review_count, 'average_rating': average, 'reviewed_bookings': len(reviewed),
        'review_coverage': round(len(reviewed) / len(completed) * 100, 1) if completed else None,
        'eligible_completed': len(completed),
        'types': [{'label': 'First-time', 'count': new}, {'label': 'Returning', 'count': returning}],
        'ratings': [{'label': f'{rating} star' + ('' if rating == 1 else 's'), 'count': distribution[rating]} for rating in range(5, 0, -1)]}


def build_insights(filters, records):
    balance = ZERO; payable_value = ZERO; credited_capped = ZERO; completed_unpaid = 0
    progress = Counter(); committed = []; unknown_time = 0
    for row in records:
        if row['status'] in PAYABLE:
            price, paid = max(money(row['total_price']), ZERO), max(money(row['credited']), ZERO)
            remaining = max(price - paid, ZERO)
            balance += remaining; payable_value += price; credited_capped += min(price, paid)
            progress['Fully paid' if paid >= price else 'Partially paid' if paid > 0 else 'Unpaid'] += 1
            completed_unpaid += row['status'] == 'completed' and remaining > 0
        if row['status'] in COMMITTED:
            committed.append(row)
    weekdays, months, hours = Counter(), Counter(), Counter()
    for row in committed:
        weekdays[row['event_date'].weekday()] += 1
        months[row['event_date'].month] += 1
        if row['event_time'] is None:
            unknown_time += 1
        else:
            hours[row['event_time'].hour] += 1
    total = len(records); expired = sum(row['status'] == 'expired' for row in records)
    expired_rate = round(expired / total * 100, 1) if total else 0
    offers = offer_demand(records)
    collections = collections_report(filters)
    customers = customer_report(records)
    payment_progress = [{'label': label, 'count': progress[label]} for label in ('Fully paid', 'Partially paid', 'Unpaid')]
    return {'remaining_balance': balance, 'payable_value': payable_value, 'credited_capped': credited_capped,
        'payable_count': sum(progress.values()), 'payment_progress': payment_progress, 'completed_unpaid': completed_unpaid,
        'expired': expired, 'expired_rate': expired_rate, 'committed_count': len(committed), 'unknown_time': unknown_time,
        'known_time': len(committed) - unknown_time,
        'weekdays': [{'label': label, 'count': weekdays[index]} for index, label in enumerate(['Mon','Tue','Wed','Thu','Fri','Sat','Sun'])],
        'months': [{'label': label, 'count': months[index]} for index, label in enumerate(['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'], 1)],
        'hours': [{'label': f'{hour:02d}:00', 'count': hours[hour]} for hour in range(24)],
        'offers': offers, 'collections': collections, 'customers': customers,
        'payment_kpis': [
            card('received', 'Collections received', f'₱{collections["value"]:,.2f}', 'green', f'{collections["count"]:,} verified payments by receipt date', 'wallet'),
            card('balance', 'Remaining balances', f'₱{balance:,.2f}', 'amber', 'Approved or completed bookings in this cohort', 'wallet'),
            card('fully_paid', 'Fully paid bookings', f'{progress["Fully paid"]:,}', 'green', 'Balance covered by verified applied payments', 'check'),
            card('partially_paid', 'Partially paid bookings', f'{progress["Partially paid"]:,}', 'blue', 'Verified payments with a remaining balance', 'wallet'),
            card('unpaid', 'Unpaid bookings', f'{progress["Unpaid"]:,}', 'red', 'Payable bookings without verified credit', 'cancel'),
            card('completed_unpaid', 'Unpaid completed events', f'{completed_unpaid:,}', 'red', 'Completed bookings with an outstanding balance', 'calendar')],
        'customer_kpis': [
            card('completed_customers', 'Customers served', f'{customers["completed_customers"]:,}', 'blue', 'Distinct customers with completed events', 'user'),
            card('new_customers', 'First-time customers', f'{customers["new"]:,}', 'teal', 'First completed event falls within this cohort', 'user'),
            card('returning_customers', 'Returning customers', f'{customers["returning"]:,}', 'green', 'Had a completed event on an earlier date', 'user'),
            card('returning_rate', 'Returning customer share', f'{customers["returning_rate"]:.1f}%' if customers['returning_rate'] is not None else '—', 'green', 'Among customers completing events in this cohort', 'chart'),
            card('average_rating', 'Average rating', f'{customers["average_rating"]:.2f} / 5' if customers['average_rating'] is not None else '—', 'amber', f'{customers["reviews"]:,} valid reviews of completed events', 'star'),
            card('review_coverage', 'Review coverage', f'{customers["review_coverage"]:.1f}%' if customers['review_coverage'] is not None else '—', 'teal', f'{customers["reviewed_bookings"]:,} of {customers["eligible_completed"]:,} completed events reviewed', 'chart')]
    }
