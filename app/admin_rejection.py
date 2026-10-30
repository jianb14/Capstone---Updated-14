"""Shared choices and saved reasons for admin booking and payment rejection."""

REJECTION_CHOICES = {
    'booking': (
        ('schedule_unavailable', 'Schedule is unavailable'),
        ('outside_service_area', 'Venue is outside our service area'),
        ('setup_unavailable', 'Requested setup is unavailable'),
        ('incomplete_details', 'Booking details are incomplete'),
        ('other', 'Other booking concern'),
    ),
    'payment': (
        ('amount_mismatch', 'Payment amount does not match'),
        ('invalid_receipt', 'Receipt is invalid or unreadable'),
        ('reference_mismatch', 'Payment reference does not match'),
        ('not_received', 'Payment has not been received'),
        ('duplicate', 'Duplicate payment submission'),
        ('other', 'Other payment concern'),
    ),
}


def rejection_reason(data, kind):
    choice_key, details_key = (('deny_reason_choice', 'deny_reason') if kind == 'booking'
                               else ('reject_reason_choice', 'admin_notes'))
    details = data.get(details_key, '').strip()
    # Preserve older text-only forms; new forms must select a known reason.
    if choice_key in data:
        label = dict(REJECTION_CHOICES[kind]).get(data.get(choice_key))
        if not label:
            raise ValueError('Choose a reason before continuing.')
        reason = f'{label}. {details}' if details else label
    else:
        reason = details
    if not reason or len(reason) > 2000:
        raise ValueError('Provide a reason of up to 2,000 characters.')
    return reason
