"""Admin booking queues and their shared HTML/async presentation."""
from datetime import date


from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q, Subquery, Value
from django.db.models.functions import Concat
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse

from ..booking_lifecycle import lifecycle_display
from ..models import Booking, BookingChangeRequest, BookingDesignDelivery, Payment


def is_async(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def mutation_response(request, success, message, booking_id, *, field='', status=400):
    """Keep old links/forms working while the workspace uses JSON responses."""
    from django.contrib import messages
    from django.shortcuts import redirect
    if is_async(request):
        return JsonResponse({'success': success, 'message': message,
            'errors': {field: message} if field else {}}, status=200 if success else status)
    (messages.success if success else messages.error)(request, message)
    return redirect('admin_booking_detail', id=booking_id)


def has_verified_payment(booking):
    return booking.payments.filter(payment_status='verified', applied_to_booking=True, amount__gt=0).exists()


def booking_feedback(request, level, message, *, field=''):
    from django.contrib import messages
    request._booking_notice = (level != 'error', message)
    request._booking_error_field = field
    if not is_async(request):
        getattr(messages, level)(request, message)


def booking_action_response(request, booking_id):
    from django.shortcuts import redirect
    if is_async(request):
        success, message = getattr(request, '_booking_notice', (False, 'Unknown booking action.'))
        field = getattr(request, '_booking_error_field', '')
        return JsonResponse({'success': success, 'message': message,
            'errors': {field: message} if field else {}}, status=200 if success else 400)
    return redirect('admin_booking_detail', id=booking_id)


def design_query():
    revision = BookingChangeRequest.objects.filter(booking_id=OuterRef('pk'), status='applied',
        proposed___design_changed=True, applied_at__isnull=False).order_by('-applied_at', '-pk')
    latest = BookingDesignDelivery.objects.filter(booking_id=OuterRef('pk')).order_by('-uploaded_at', '-pk')
    paid = Payment.objects.filter(booking_id=OuterRef('pk'), payment_status='verified',
        applied_to_booking=True, amount__gt=0)
    return Booking.objects.annotate(verified_payment=Exists(paid),
        revision_at=Subquery(revision.values('applied_at')[:1]),
        delivered_at=Subquery(latest.values('uploaded_at')[:1]))


def design_state_filter(state):
    from django.db.models import F
    ready = Q(delivered_at__isnull=False) & (Q(revision_at__isnull=True) | Q(delivered_at__gt=F('revision_at')))
    if state == 'sent':
        return ready
    if state == 'revision':
        return ~ready & Q(revision_at__isnull=False)
    if state == 'needed':
        return ~ready & Q(revision_at__isnull=True)
    return Q()


def _filters(request, queryset, *, default_status=''):
    search = request.GET.get('search', '').strip()[:150]
    status = request.GET.get('status', default_status)
    if status not in dict(Booking.STATUS_CHOICES):
        status = ''
    start, end = request.GET.get('date_from', '').strip(), request.GET.get('date_to', '').strip()
    error, dates = '', {}
    for key, value in [('date_from', start), ('date_to', end)]:
        if value:
            try:
                dates[key] = date.fromisoformat(value)
            except ValueError:
                error = 'Enter a valid date.'
    if not error and start and end and dates['date_from'] > dates['date_to']:
        error = 'The end date must be on or after the start date.'
    if error:
        queryset = queryset.none()
    else:
        if start:
            queryset = queryset.filter(event_date__gte=dates['date_from'])
        if end:
            queryset = queryset.filter(event_date__lte=dates['date_to'])
    if status:
        queryset = queryset.filter(status=status)
    if search:
        queryset = queryset.annotate(customer_full_name=Concat('user__first_name', Value(' '), 'user__last_name'))
        term = Q(customer_full_name__icontains=search) | Q(user__username__icontains=search) | Q(user__email__icontains=search) | Q(
            user__first_name__icontains=search) | Q(user__last_name__icontains=search) | Q(event_type__icontains=search)
        numeric = search.lstrip('#')
        if numeric.isdecimal() and len(numeric) <= 19 and int(numeric) <= 2**63-1:
            term |= Q(pk=int(numeric))
        queryset = queryset.filter(term)
    return queryset, {'search_query': search, 'status_filter': status,
        'date_from': start, 'date_to': end, 'filter_error': error}


def workspace_context(request):
    from .change_management import change_queue_summary, request_list_context
    from .common import find_active_booking_conflicts, get_booking_time_range
    summary = Booking.objects.aggregate(total=Count('pk'), **{
        key: Count('pk', filter=Q(status=key)) for key, _ in Booking.STATUS_CHOICES})
    changes = change_queue_summary()
    designs = design_query().filter(status='confirmed', verified_payment=True)
    design_summary = {'total': designs.count(), **{
        key: designs.filter(design_state_filter(key)).count() for key in ('needed', 'revision', 'sent')}}
    tab = request.GET.get('tab', 'bookings')
    if tab not in ('bookings', 'requests', 'designs'):
        tab = 'bookings'
    per_page = 4 if request.GET.get('per_page') == '4' else 8
    context = {'active_tab': tab, 'booking_summary': summary, 'change_summary': changes,
        'design_summary': design_summary, 'per_page': per_page, 'status_options': Booking.STATUS_CHOICES}
    if tab == 'requests':
        context.update(request_list_context(request, changes))
        context['page'] = context['change_requests']
        context['page_key'] = 'request_page'
        context['has_filters'] = bool(context['request_search'] or context['request_status'] or context['request_booking_id'])
        return context
    queryset = design_query().select_related('user').prefetch_related('payments', 'design_deliveries', 'change_requests')
    if tab == 'designs':
        queryset = queryset.filter(status='confirmed', verified_payment=True)
        state = request.GET.get('design_status', '')
        if state not in ('needed', 'revision', 'sent'):
            state = ''
        queryset = queryset.filter(design_state_filter(state))
        context['design_status'] = state
        queryset = queryset.order_by('design_due_at', 'event_date', 'event_time', 'pk')
    else:
        order = request.GET.get('sort', '')
        queryset = queryset.order_by('event_date', 'event_time', 'pk') if order == 'event' else queryset.order_by('-created_at', '-pk')
        context['sort'] = order if order == 'event' else ''
    queryset, filters = _filters(request, queryset, default_status='pending' if tab == 'bookings' else '')
    context.update(filters)
    page = Paginator(queryset, per_page).get_page(request.GET.get('page'))
    rows = list(page)
    for booking in rows:
        booking.time_range_display = get_booking_time_range(booking)
        booking.lifecycle = lifecycle_display(booking)
        booking.can_send_design = booking.status in ('confirmed', 'completed') and booking.verified_payment
        booking.design_label = ('Design sent' if booking.lifecycle['design_ready'] else
            'Needs revision' if booking.lifecycle['design_revision_pending'] else 'Needs design')
        booking.has_conflict = bool(find_active_booking_conflicts(booking))
    context.update({'bookings': page, 'page': page, 'page_key': 'page',
        'has_filters': bool(filters['search_query'] or filters['status_filter'] or filters['date_from'] or filters['date_to'] or context.get('design_status'))})
    return context


def workspace_response(request):
    context = workspace_context(request)
    if is_async(request):
        response = JsonResponse({'success': True, 'html': render_to_string('admin/booking/workspace/_workspace.html', context, request=request)})
    else:
        response = render(request, 'admin/booking/admin_booking_list.html', context)
    response['Cache-Control'] = 'private, no-store'
    return response
