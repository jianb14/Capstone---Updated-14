"""Admin request queue and a focused review of one specific amendment."""
from urllib.parse import urlencode, urlsplit

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, When
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from ..booking_changes import change_context, change_difference_rows
from ..booking_lifecycle import payment_was_received, process_booking_deadlines
from ..models import BookingChangeRequest, Payment


ADMIN_STATUSES = {
    'pending_review': ('For Review', 'Review the requested changes and send a quote.'),
    'quoted': ('Waiting for Customer', 'The customer is reviewing the quote.'),
    'awaiting_payment': ('Awaiting Additional Payment', 'The customer needs to submit the additional payment.'),
    'manual_review': ('Needs Attention', 'Resolve this request and its payment directly with the customer.'),
    'applied': ('Changes Applied', 'Accepted changes were applied to the booking.'),
    'rejected': ('Declined', 'The requested changes were declined.'),
    'withdrawn': ('Withdrawn', 'The request was closed; the original booking was retained.'),
    'expired': ('Expired', 'This request or quote expired.'),
}
ACTIVE = BookingChangeRequest.ACTIVE_STATUSES


def request_queue():
    received = Payment.objects.filter(change_request_id=OuterRef('pk'), payment_status='pending').filter(
        Q(payment_method='gcash') | Q(received_at__isnull=False) |
        ~Q(paymongo_payment_id='') | Q(notes__icontains='paid via paymongo'))
    return BookingChangeRequest.objects.annotate(has_received_payment=Exists(received))


def needs_action_filter():
    return Q(status__in=('pending_review', 'manual_review')) | Q(status='awaiting_payment', has_received_payment=True)


def change_queue_summary():
    return request_queue().aggregate(total=Count('pk'),
        active=Count('pk', filter=Q(status__in=ACTIVE)),
        needs_review=Count('pk', filter=needs_action_filter()),
        waiting=Count('pk', filter=Q(status__in=('quoted', 'awaiting_payment')) & ~needs_action_filter()),
        history=Count('pk', filter=~Q(status__in=ACTIVE)))


def decorate_change(change):
    label, note = ADMIN_STATUSES.get(change.status, (change.get_status_display(), ''))
    received = getattr(change, 'has_received_payment', None)
    if received is None:
        received = change.status == 'awaiting_payment' and any(payment.payment_status == 'pending' and payment_was_received(payment) for payment in change.payments.all())
    change.payment_to_verify = change.status == 'awaiting_payment' and received
    if change.payment_to_verify:
        label, note = 'Payment to Verify', 'An additional payment was submitted. Open the request to review it.'
    change.admin_status_label, change.admin_status_note = label, note
    change.needs_admin_action = change.status in ('pending_review', 'manual_review') or change.payment_to_verify
    change.is_active_request = change.status in ACTIVE
    rows = change_difference_rows(change)
    priority = {'Package / extras':0, 'Date':1, 'Start time':2, 'End time':3, 'Venue address':4}
    rows.sort(key=lambda row:priority.get(row['label'], 5))
    change.summary_rows, change.more_changes = rows[:2], max(len(rows)-2, 0)
    return change


def _queue_url(values, **updates):
    params = {**values, **updates}
    return f"{reverse('admin_booking_list')}?{urlencode({key:value for key,value in params.items() if value not in ('', None)})}"


def request_list_context(request, summary):
    scope = request.GET.get('scope', 'active')
    if scope not in ('active', 'history'):
        scope = 'active'
    statuses = [(key, label) for key,(label,_) in ADMIN_STATUSES.items() if (key in ACTIVE) == (scope == 'active')]
    status = request.GET.get('request_status', '')
    if status not in dict(statuses):
        status = ''
    search = request.GET.get('request_search', '').strip()
    booking_id = request.GET.get('booking_id', '')
    if not booking_id.isdigit():
        booking_id = ''
    changes = request_queue().select_related('booking__user', 'reviewed_by')
    changes = changes.filter(status__in=ACTIVE) if scope == 'active' else changes.exclude(status__in=ACTIVE)
    if status:
        changes = changes.filter(status=status)
    if booking_id:
        changes = changes.filter(booking_id=booking_id)
    if search:
        numeric = search.lstrip('#')
        match = Q(booking__user__username__icontains=search) | Q(booking__user__email__icontains=search) | Q(booking__user__first_name__icontains=search) | Q(booking__user__last_name__icontains=search) | Q(reason__icontains=search)
        if numeric.isdigit():
            match |= Q(pk=numeric) | Q(booking_id=numeric)
        changes = changes.filter(match)
    if scope == 'active':
        changes = changes.annotate(queue_priority=Case(When(needs_action_filter(), then=0), default=1, output_field=IntegerField())).order_by('queue_priority', '-created_at', '-pk')
    else:
        changes = changes.order_by('-updated_at', '-pk')
    page = Paginator(changes, 10).get_page(request.GET.get('request_page'))
    values = {'tab':'requests', 'scope':scope, 'request_search':search, 'request_status':status, 'booking_id':booking_id}
    back = _queue_url(values, request_page=page.number)
    for change in page:
        decorate_change(change)
        change.review_url = f"{reverse('admin_booking_change_detail', args=[change.pk])}?{urlencode({'return_to':back})}"
    return {'active_tab':'requests', 'change_summary':summary, 'request_scope':scope,
        'change_requests':page, 'request_search':search, 'request_status':status,
        'request_booking_id':booking_id, 'request_status_options':statuses,
        'request_active_url':_queue_url(values, scope='active', request_status=''),
        'request_history_url':_queue_url(values, scope='history', request_status=''),
        'request_clear_url':_queue_url({'tab':'requests', 'scope':scope}),
        'request_page_links':[
            {'label':number, 'url':_queue_url(values, request_page=number) if number != page.paginator.ELLIPSIS else '', 'current':number == page.number}
            for number in page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)
        ],
        'request_previous_url':_queue_url(values, request_page=page.previous_page_number()) if page.has_previous() else '',
        'request_next_url':_queue_url(values, request_page=page.next_page_number()) if page.has_next() else ''}


def request_return_url(request, change):
    value = request.POST.get('return_to') or request.GET.get('return_to') or ''
    try:
        parts = urlsplit(value)
        if not parts.scheme and not parts.netloc and parts.path == reverse('admin_booking_list'):
            return parts.path + (f'?{parts.query}' if parts.query else '')
    except ValueError:
        pass
    return _queue_url({'tab':'requests', 'scope':'active' if change.status in ACTIVE else 'history'})


def request_review_url(request, change):
    return f"{reverse('admin_booking_change_detail', args=[change.pk])}?{urlencode({'return_to':request_return_url(request, change)})}"


@login_required
@require_GET
def admin_booking_change_detail(request, change_id):
    if request.user.role not in ('admin', 'staff'):
        return HttpResponseForbidden('Not allowed')
    process_booking_deadlines()
    change = get_object_or_404(request_queue().select_related('booking__user', 'reviewed_by').prefetch_related('images', 'payments'), pk=change_id)
    decorate_change(change)
    booking = change.booking
    context = change_context(booking, change=change)
    context.update({'booking':booking, 'change_status_label':change.admin_status_label,
        'change_status_note':change.admin_status_note, 'return_to':request_return_url(request, change),
        'active_tab':'requests', 'change_summary':change_queue_summary()})
    response = render(request, 'admin/booking/change_request_detail.html', context)
    response['Cache-Control'] = 'private, no-store'
    return response
