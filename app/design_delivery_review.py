"""Missed design reviews; callers serialize writes with the booking row lock."""
from django import forms
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import AdminNotification, BookingDesignReview, BookingStatusLog, Notification


def ensure_design_review(booking, now=None, display=None):
    from .booking_lifecycle import deadline_notice, lifecycle_display
    now = now or timezone.now()
    display = display or lifecycle_display(booking, now)
    if not display['design_review_required']:
        return display['design_review']
    review, created = BookingDesignReview.objects.get_or_create(booking=booking, cycle=display['design_cycle'],
        defaults={'due_at': display['design_due_at'], 'event_ended_at': display['event_end_at']})
    if created:
        deadline_notice(booking, f'design-missed-{review.cycle}',
            f'Urgent: Booking #{booking.pk} event has ended without a current design delivered by its end. '
            'Review what happened and record the resolution before marking this booking completed.',
            f'Your event has ended, but no current design was recorded as delivered by its end for booking #{booking.pk}. '
            'Our team needs to review what happened and contact you about the resolution.')
    return review


class DesignResolutionForm(forms.Form):
    outcome = forms.ChoiceField(choices=BookingDesignReview.OUTCOME_CHOICES)
    notes = forms.CharField(max_length=2000)
    delivered_at = forms.DateTimeField(required=False)
    service_fulfilled = forms.BooleanField(required=False)

    def __init__(self, *args, display, **kwargs):
        super().__init__(*args, **kwargs)
        self.display = display

    def clean(self):
        data = super().clean()
        outcome, delivered = data.get('outcome'), data.get('delivered_at')
        if outcome == 'external_delivery':
            if delivered is None and 'delivered_at' not in self.errors:
                self.add_error('delivered_at', 'Enter the actual date and time the design was delivered.')
            elif delivered and delivered > timezone.now():
                self.add_error('delivered_at', 'The actual delivery time cannot be in the future.')
            elif delivered and self.display['design_revision_at'] and delivered <= self.display['design_revision_at']:
                self.add_error('delivered_at', 'The delivery must be for the current design requirements.')
        elif outcome == 'late_delivery' and not self.display['design_ready']:
            self.add_error('outcome', 'Upload the current design before choosing an online delivery resolution.')
        return data


def resolve_design_review(booking, actor, data):
    from .booking_lifecycle import lifecycle_display
    display = lifecycle_display(booking)
    revision = display['design_revision_at']
    if booking.status != 'confirmed' or not display['event_ended']:
        return None, {'outcome': 'Only confirmed bookings with an ended event can have a missed-design resolution.'}
    if data.get('design_revision') != (revision.isoformat() if revision else ''):
        return None, {'design_revision': 'The design requirements changed. Reopen the booking before recording a resolution.'}
    review = ensure_design_review(booking, display=display)
    if not review:
        return None, {'outcome': 'This booking has no missed-design issue to resolve.'}
    if data.get('review_id') != str(review.pk) or data.get('review_version') != str(review.version):
        return None, {'': 'This design review changed. Reopen the booking and review the latest details before saving.'}
    form = DesignResolutionForm(data, display=display)
    if not form.is_valid():
        return None, {field: str(errors[0]) for field, errors in form.errors.items()}
    values = form.cleaned_data
    if review.resolved_at:
        same = (review.outcome == values['outcome'] and review.notes == values['notes'] and
            review.service_fulfilled == values['service_fulfilled'] and
            (review.outcome != 'external_delivery' or review.delivered_at == values['delivered_at']))
        return (review, {}) if same else (None, {'': 'Another resolution is already recorded. Reopen the booking to read it; your changes were not saved.'})
    review.outcome = values['outcome']
    review.notes = values['notes']
    review.service_fulfilled = values['service_fulfilled']
    if review.outcome == 'external_delivery':
        review.delivered_at = values['delivered_at']
    elif review.outcome == 'late_delivery':
        deliveries = [item for item in booking.design_deliveries.all() if not revision or item.uploaded_at > revision]
        review.delivered_at = min(item.uploaded_at for item in deliveries)
    review.resolved_at, review.resolved_by = timezone.now(), actor
    review.save()
    delivery_note = f' Actual delivery: {timezone.localtime(review.delivered_at):%b %d, %Y %I:%M %p}.' if review.delivered_at else ''
    BookingStatusLog.objects.create(booking=booking, old_status=booking.status, new_status=booking.status, changed_by=actor,
        notes=f'Design issue resolved: {review.get_outcome_display()}.{delivery_note} '
        f'Service fulfilled: {"yes" if review.service_fulfilled else "no"}. {review.notes}')
    Notification.objects.create(booking=booking, user=booking.user,
        message=f'A design delivery resolution was recorded for booking #{booking.pk}: {review.get_outcome_display()}. '
        'Open Booking Details to read the explanation.')
    return review, {}


def resolution_snapshot(review):
    return {'outcome': review.get_outcome_display(), 'notes': review.notes,
        'delivered_at': review.delivered_at.isoformat() if review.delivered_at else None,
        'resolved_at': review.resolved_at.isoformat(), 'due_at': review.due_at.isoformat(),
        'service_fulfilled': review.service_fulfilled}


def resolution_history(reviews, current):
    history = []
    for review in reviews:
        snapshots = list(review.history)
        if review != current and review.resolved_at:
            snapshots.append(resolution_snapshot(review))
        for snapshot in snapshots:
            item = dict(snapshot)
            for field in ('delivered_at', 'resolved_at', 'reopened_at', 'due_at'):
                item[field] = parse_datetime(item[field]) if item.get(field) else None
            history.append(item)
    return sorted(history, key=lambda item: item['resolved_at'], reverse=True)


def reopen_deleted_delivery_review(booking, actor):
    from .booking_lifecycle import lifecycle_display
    display = lifecycle_display(booking)
    review = display['design_review']
    if not review or not review.resolved_at or review.outcome != 'late_delivery' or display['design_ready']:
        return
    BookingStatusLog.objects.create(booking=booking, old_status=booking.status, new_status=booking.status, changed_by=actor,
        notes=f'Design issue reopened after the last current design was deleted. Previous resolution: '
        f'{review.notes} (recorded {timezone.localtime(review.resolved_at):%b %d, %Y %I:%M %p}).')
    snapshot = resolution_snapshot(review)
    snapshot['reopened_at'] = timezone.now().isoformat()
    review.history.append(snapshot)
    review.version += 1
    review.resolved_at = review.resolved_by = review.delivered_at = None
    review.outcome = review.notes = ''
    review.service_fulfilled = False
    review.save()
    message = f'Design delivery review reopened for booking #{booking.pk}: the last current design image was removed.'
    AdminNotification.objects.create(booking=booking, user=booking.user, message=message)
    Notification.objects.create(booking=booking, user=booking.user, message=message)
