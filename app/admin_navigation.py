"""Admin breadcrumb labels and a bounded, read-only global record search."""
import re
from functools import reduce
from operator import or_

from django.db.models import Case, IntegerField, Q, Value, When
from django.urls import reverse

from .models import Booking, Payment, User

SEARCH_LIMIT = 4
SEARCH_MAX_LENGTH = 120


def admin_breadcrumbs(request):
    match = request.resolver_match
    name = match.url_name if match else ''
    kwargs = match.kwargs if match else {}
    dashboard = {'label': 'Dashboard', 'url': reverse('dashboard')}
    if name == 'dashboard':
        return [{**dashboard, 'url': ''}]
    sections = [
        (('admin_booking_',), 'Bookings', 'admin_booking_list'),
        (('admin_payment_', 'admin_gcash_'), 'Payments', 'admin_payment_list'),
        (('admin_user_',), 'Users', 'admin_user_list'),
        (('admin_review',), 'Reviews', 'admin_reviews'),
        (('admin_concern',), 'Customer concerns', 'admin_concerns'),
        (('admin_analytics',), 'Reports & Analytics', 'admin_analytics'),
        (('admin_audit_',), 'Audit log', 'admin_audit_log'),
        (('admin_calendar', 'admin_blocked_'), 'Calendar', 'admin_calendar'),
        (('admin_home_', 'admin_hiw_', 'admin_faq_'), 'Home content', 'admin_home_content'),
        (('admin_about_',), 'About content', 'admin_about_content'),
        (('admin_guidelines_',), 'Guidelines & policies', 'admin_guidelines_content'),
        (('admin_service_content', 'admin_service_item_'), 'Service content', 'admin_service_content'),
        (('admin_package_', 'admin_addon_', 'admin_additional_', 'admin_service_charge_'), 'Packages', 'admin_package_list'),
        (('admin_gallery',), 'Gallery', 'admin_gallery'),
        (('admin_canvas_',), 'Canvas assets', 'admin_canvas_assets'),
        (('admin_chat_',), 'Chat', 'admin_chat_inbox'),
        (('admin_site_',), 'Site settings', 'admin_site_settings'),
        (('admin_profile',), 'My profile', 'admin_profile'),
        (('ai_health',), 'AI health', 'ai_health'),
    ]
    for prefixes, label, parent in sections:
        if name.startswith(prefixes):
            crumbs = [dashboard, {'label': label, 'url': reverse(parent)}]
            if name == 'admin_booking_list' and request.GET.get('tab') == 'requests':
                crumbs.append({'label': 'Change requests', 'url': ''})
            elif name == 'admin_booking_change_detail':
                crumbs.append({'label': 'Change requests', 'url': reverse(parent) + '?tab=requests'})
                crumbs.append({'label': f'Request #{kwargs.get("change_id", "")}', 'url': ''})
            elif name == 'admin_review_detail':
                # This route opens the Reviews workspace with its details modal.
                pass
            elif name != parent:
                record_id = kwargs.get('id') or kwargs.get('session_id')
                record_labels = {
                    'admin_booking_detail': 'Booking', 'admin_payment_detail': 'Payment',
                    'admin_user_detail': 'User', 'admin_package_detail': 'Package',
                    'admin_addon_detail': 'Entrance arch', 'admin_additional_detail': 'Welcome stand',
                    'admin_gallery_image_detail': 'Image', 'admin_canvas_asset_detail': 'Asset',
                    'admin_chat_thread': 'Conversation',
                }
                if name in record_labels and record_id:
                    leaf = f'{record_labels[name]} #{record_id}'
                elif name.endswith('_create'):
                    leaf = 'Add ' + _record_kind(name)
                elif name.endswith('_edit'):
                    leaf = 'Edit ' + _record_kind(name) + (f' #{record_id}' if record_id else '')
                elif name == 'admin_gcash_config':
                    leaf = 'GCash settings'
                elif name == 'admin_service_charge_update':
                    leaf = 'Service charge'
                else:
                    leaf = ''
                if leaf:
                    crumbs.append({'label': leaf, 'url': ''})
            crumbs[-1]['url'] = ''
            return crumbs
    return [dashboard, {'label': 'Admin workspace', 'url': ''}]


def _record_kind(name):
    for token, label in (('gallery_image', 'image'), ('gallery_category', 'category'),
            ('canvas_asset', 'asset'), ('canvas_category', 'category'),
            ('home_feature', 'feature'), ('hiw_step', 'step'), ('faq', 'FAQ'),
            ('about_value', 'value'), ('about_journey', 'journey step'),
            ('service_item', 'service'), ('additional', 'welcome stand'), ('addon', 'entrance arch'),
            ('package', 'package'), ('user', 'user'), ('blocked_date', 'unavailable date')):
        if token in name:
            return label
    return 'item'


def _words_query(words, fields):
    query = Q()
    for word in words:
        query &= reduce(or_, (Q(**{field + '__icontains': word}) for field in fields))
    return query


def _customer_name(user):
    return 'Removed account' if user.deleted_at else (user.get_full_name().strip() or user.username)


def search_records(query):
    query = query.strip()
    if len(query) > SEARCH_MAX_LENGTH:
        raise ValueError(f'Keep your search within {SEARCH_MAX_LENGTH} characters.')
    if '\x00' in query:
        raise ValueError('Remove unsupported characters from your search.')
    if len(query) < 2 and not (query.isascii() and query.isdigit()):
        return {'query': query, 'groups': [], 'has_more': False}
    match = re.fullmatch(r'#?(?:(booking|book|bkg|payment|pay|customer|cust|user)[\s:#-]*)?([0-9]{1,18})', query, re.I)
    kind, number = (match[1].lower() if match[1] else '', int(match[2])) if match else ('', None)
    bookings = Booking.objects.select_related('user')
    customers = User.objects.filter(role='customer', deleted_at__isnull=True)
    payments = Payment.objects.select_related('booking', 'booking__user')
    from .views.payments import _abandoned_paymongo_payment_query
    payments = payments.exclude(_abandoned_paymongo_payment_query())
    if number is not None:
        if kind in ('payment', 'pay'):
            bookings = bookings.none(); customers = customers.none()
            payments = payments.filter(pk=number)
        elif kind in ('customer', 'cust', 'user'):
            bookings = bookings.filter(user_id=number); customers = customers.filter(pk=number)
            payments = payments.filter(booking__user_id=number)
        else:
            bookings = bookings.filter(pk=number)
            if kind:
                customers = customers.none(); payments = payments.filter(booking_id=number)
            else:
                customer_query = Q(pk=number)
                if len(query) >= 7:
                    customer_query |= Q(phone_number__icontains=query)
                customers = customers.filter(customer_query)
                payments = payments.filter(Q(pk=number) | Q(booking_id=number))
    else:
        words = query.split()
        bookings = bookings.filter(_words_query(words, ['user__first_name', 'user__last_name', 'user__username',
            'user__email', 'event_type', 'event_location', 'package_type', 'status']))
        customers = customers.filter(_words_query(words, ['first_name', 'last_name', 'username', 'email', 'phone_number']))
        payments = payments.filter(_words_query(words, ['transaction_ref', 'gcash_reference_number',
            'gcash_sender_name', 'booking__user__first_name', 'booking__user__last_name',
            'booking__user__username', 'booking__user__email', 'payment_method', 'payment_status']))
    groups = []
    priority = (Case(When(pk=number, then=Value(0)), default=Value(1), output_field=IntegerField()),) if number is not None else ()
    booking_rows = list(bookings.order_by(*priority, '-created_at', '-pk')[:SEARCH_LIMIT + 1])
    customer_rows = list(customers.order_by(*priority, 'first_name', 'last_name', 'pk')[:SEARCH_LIMIT + 1])
    payment_rows = list(payments.order_by(*priority, '-created_at', '-pk')[:SEARCH_LIMIT + 1])
    items = [
        ('bookings', 'Bookings', booking_rows, lambda row: {
            'title': f'Booking #{row.pk} · {row.event_type or "Event"}',
            'description': f'{_customer_name(row.user)} · {row.event_date:%b %d, %Y} · {row.get_status_display()}',
            'url': reverse('admin_booking_detail', args=[row.pk])}),
        ('customers', 'Customers', customer_rows, lambda row: {
            'title': _customer_name(row), 'description': row.email or f'Customer #{row.pk}',
            'url': reverse('admin_user_detail', args=[row.pk])}),
        ('payments', 'Payments', payment_rows, lambda row: {
            'title': f'Payment #{row.pk} · ₱{row.amount:,.2f}',
            'description': f'Booking #{row.booking_id} · {row.get_payment_status_display()} · {row.transaction_ref}',
            'url': reverse('admin_payment_detail', args=[row.pk])}),
    ]
    for key, label, rows, serialize in items:
        if rows:
            groups.append({'key': key, 'label': label, 'items': [serialize(row) for row in rows[:SEARCH_LIMIT]],
                'has_more': len(rows) > SEARCH_LIMIT})
    return {'query': query, 'groups': groups, 'has_more': any(group['has_more'] for group in groups)}
