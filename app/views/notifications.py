"""Notification read/hide actions. (split from app/views.py)"""

from .common import *  # noqa: F401,F403


@login_required
@require_GET
def admin_notification_feed(request):
    from ..admin_notifications import notification_rows, unread_count, concern_counts
    if request.user.role != 'admin':
        return JsonResponse({'message': 'Not allowed'}, status=403)
    counts = concern_counts()
    data = {'unread_count': unread_count(), 'new_concerns_count': counts['new'], 'concern_counts': counts}
    if request.GET.get('summary') != '1':
        try:
            rows, cursor = notification_rows(request.GET.get('cursor'))
        except ValueError as exc:
            return JsonResponse({'message': str(exc)}, status=400)
        data.update(items=[{'id': row['id'], 'created_at': row['created_at'].isoformat(),
            'message': f"{row['user'].get_full_name() or row['user'].username} {row['message']}" if row['user'] else row['message'],
            'is_read': row['is_read'], 'target_url': row['target_url'],
            'read_url': reverse('mark_admin_notification_read', args=[row['id']])} for row in rows], next_cursor=cursor)
    response = JsonResponse(data)
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_POST
def mark_admin_notification_read(request, id):
    from ..admin_notifications import unread_count
    if request.user.role != 'admin':
        return JsonResponse({'message': 'Not allowed'}, status=403)
    match = re.fullmatch(r'(b|n)_([1-9]\d{0,18})', id)
    if not match or int(match.group(2)) > 9223372036854775807:
        return JsonResponse({'message': 'Invalid notification.'}, status=400)
    kind, key = match.groups()
    if kind == 'b':
        item = get_object_or_404(Booking, pk=int(key), admin_notif_hidden=False)
        Booking.objects.filter(pk=item.pk).update(admin_notified=True)
    else:
        item = get_object_or_404(AdminNotification, pk=int(key), is_hidden=False)
        AdminNotification.objects.filter(pk=item.pk).update(is_read=True)
    response = JsonResponse({'status': 'success', 'unread_count': unread_count()})
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
def mark_notifications_read(request):
    if request.user.role != 'admin':
        return JsonResponse({"status": "error", "message": "Not allowed"}, status=403)

    if request.method == "POST":
        # Mark all legacy booking notifications as read
        Booking.objects.filter(admin_notified=False).update(admin_notified=True)
        # Mark all new unified events as read
        AdminNotification.objects.filter(is_read=False).update(is_read=True)
        from ..admin_notifications import unread_count
        return JsonResponse({"status": "success", 'unread_count': unread_count()})

    return JsonResponse({"status": "error"}, status=400)


@login_required
@require_POST
def hide_notification(request, id):
    from ..admin_notifications import unread_count
    if request.user.role != 'admin':
        return JsonResponse({'status': 'error', 'message': 'Not allowed'}, status=403)
    match = re.fullmatch(r'(?:(b|n)_)?([1-9]\d{0,18})', str(id))
    if not match or int(match.group(2)) > 9223372036854775807:
        return JsonResponse({'status': 'error', 'message': 'Invalid notification.'}, status=400)
    kind, key = match.groups()
    if kind == 'n':
        notice = get_object_or_404(AdminNotification, pk=int(key))
        AdminNotification.objects.filter(pk=notice.pk).update(is_hidden=True)
    else:
        booking = get_object_or_404(Booking, pk=int(key))
        Booking.objects.filter(pk=booking.pk).update(admin_notif_hidden=True)
    return JsonResponse({'status': 'success', 'unread_count': unread_count()})


@login_required
@require_POST
def mark_customer_notification_read(request, id):
    """Mark a customer's notification as read via AJAX."""
    try:
        notif = Notification.objects.get(id=id, user=request.user)
        notif.is_read = True
        notif.save(update_fields=['is_read'])
        return JsonResponse({"status": "success", 'unread_count': Notification.objects.filter(user=request.user, is_read=False).count()})
    except Notification.DoesNotExist:
        return JsonResponse(
            {"status": "error", "message": "Notification not found"}, status=404
        )


# -------------------------
# CREATE BOOKING
# -------------------------

@login_required
@require_POST
def clear_all_notifications(request):
    """Mark all of a customer's notifications as read."""
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return JsonResponse({"status": "success", 'unread_count': Notification.objects.filter(user=request.user, is_read=False).count()})


@login_required
@require_GET
def customer_notification_feed(request):
    """Fresh customer-owned notices with stable pagination; opening never reads them."""
    from django.core import signing
    from django.utils.dateparse import parse_datetime
    from ..context_processors import _customer_notif_target_url
    if request.user.role != 'customer':
        return JsonResponse({'message': 'Not allowed'}, status=403)
    if request.GET.get('summary') == '1':
        response = JsonResponse({'unread_count': Notification.objects.filter(user=request.user, is_read=False).count()})
        response['Cache-Control'] = 'private, no-store'
        return response
    notices = Notification.objects.filter(user=request.user).select_related('booking', 'concern').prefetch_related('booking__payments')
    cursor = request.GET.get('cursor')
    if cursor:
        try:
            stamp, key = signing.loads(cursor, salt='customer-notifications')
            stamp = parse_datetime(stamp)
            if stamp is None or not isinstance(key, int):
                raise ValueError
        except (signing.BadSignature, ValueError, TypeError):
            return JsonResponse({'message': 'Invalid notification cursor.'}, status=400)
        notices = notices.filter(Q(created_at__lt=stamp) | Q(created_at=stamp, id__lt=key))
    rows = list(notices.order_by('-created_at', '-id')[:21])
    more = len(rows) > 20
    rows = rows[:20]
    items = [{'id': row.id, 'message': row.message, 'is_read': row.is_read,
        'created_at': row.created_at.isoformat(), 'target_url': _customer_notif_target_url(row),
        'read_url': reverse('mark_customer_notification_read', args=[row.id])} for row in rows]
    response = JsonResponse({'items': items, 'unread_count': Notification.objects.filter(user=request.user, is_read=False).count(),
        'next_cursor': signing.dumps([rows[-1].created_at.isoformat(), rows[-1].pk], salt='customer-notifications') if more else None})
    response['Cache-Control'] = 'private, no-store'
    return response
