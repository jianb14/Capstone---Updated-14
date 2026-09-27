"""Notification read/hide actions. (split from app/views.py)"""

from .common import *  # noqa: F401,F403


@login_required
def mark_notifications_read(request):
    if request.user.role not in ["admin", "staff"]:
        return JsonResponse({"status": "error", "message": "Not allowed"}, status=403)

    if request.method == "POST":
        # Mark all legacy booking notifications as read
        Booking.objects.filter(admin_notified=False).update(admin_notified=True)
        # Mark all new unified events as read
        AdminNotification.objects.filter(is_read=False).update(is_read=True)
        return JsonResponse({"status": "success"})

    return JsonResponse({"status": "error"}, status=400)


@login_required
def hide_notification(request, id):
    if request.user.role not in ["admin", "staff"]:
        return JsonResponse({"status": "error", "message": "Not allowed"}, status=403)

    if request.method == "POST":
        notif_id_str = str(id)
        if notif_id_str.startswith("b_"):
            # It's a legacy booking notification
            real_id = notif_id_str.replace("b_", "")
            booking = get_object_or_404(Booking, id=real_id)
            booking.admin_notif_hidden = True
            booking.save()
        elif notif_id_str.startswith("n_"):
            # It's a new admin notification event
            real_id = notif_id_str.replace("n_", "")
            notif = get_object_or_404(AdminNotification, id=real_id)
            notif.is_hidden = True
            notif.save()
        else:
            # Fallback for old integer IDs that might still exist in cached templates
            try:
                real_id = int(notif_id_str)
                booking = get_object_or_404(Booking, id=real_id)
                booking.admin_notif_hidden = True
                booking.save()
            except ValueError:
                return JsonResponse(
                    {"status": "error", "message": "Invalid ID format"}, status=400
                )

        return JsonResponse({"status": "success"})

    return JsonResponse({"status": "error"}, status=400)


@login_required
def mark_customer_notification_read(request, id):
    """Mark a customer's notification as read via AJAX."""
    try:
        notif = Notification.objects.get(id=id, user=request.user)
        notif.is_read = True
        notif.save()
        return JsonResponse({"status": "success"})
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
    return JsonResponse({"status": "success"})
