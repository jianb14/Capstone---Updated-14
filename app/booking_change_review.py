"""Read-only, owner-checked booking change previews use the final proposal rules."""
import hashlib
import json
from decimal import Decimal

from django.core.exceptions import ValidationError

from .booking_changes import snapshot, prepare_proposal, verified_paid, payment_amounts


def review_fields(booking):
    from .views.common import _booking_time_bounds, remove_end_time_tag
    fields = snapshot(booking)
    start, end = _booking_time_bounds(booking)
    fields.update(event_time=start.strftime('%H:%M') if start else '',
                  event_end_time=end.strftime('%H:%M') if end else '',
                  event_end_date=end.date().isoformat() if end else '',
                  duration_minutes=int((end-start).total_seconds()/60) if start and end else None,
                  special_requests=remove_end_time_tag(booking.special_requests or '').strip())
    return fields


def review_breakdown(booking):
    from .views.common import get_booking_display_breakdown
    detail = get_booking_display_breakdown(booking)
    return {'items': [{'label': item['label'], 'amount': str(item['amount'])} for item in detail['items']],
            'logistics': str(detail['service_charge']), 'overtime': str(detail['overtime_fee']),
            'logistics_note': detail['logistics_notes'] + ' ' + detail['logistics_explanation'],
            'overtime_note': detail['overtime_explanation']}


def review_baseline(booking):
    images = [{'id': str(image.pk), 'url': image.image.url, 'name': image.image.name}
              for image in booking.images.order_by('pk') if image.image]
    if booking.reference_image:
        images.insert(0, {'id': 'legacy', 'url': booking.reference_image.url, 'name': booking.reference_image.name})
    designs = [{'id': str(design.pk), 'url': design.image.url, 'name': design.image.name}
               for design in booking.designs.order_by('pk') if design.image]
    version_data = [snapshot(booking), [(image['id'], image['name']) for image in images],
                    [(image['id'], image['name']) for image in designs]]
    version = hashlib.sha256(json.dumps(version_data, sort_keys=True).encode()).hexdigest()
    detail = review_breakdown(booking)
    saved_items = (booking.fee_policy_snapshot or {}).get('catalog_items', [])
    saved_total = sum((Decimal(str(item['amount'])) for item in saved_items), Decimal('0'))
    available = bool(saved_items) and saved_total == booking.total_price - Decimal(detail['logistics']) - Decimal(detail['overtime'])
    if not available:
        from .views.common import get_booking_price_breakdown, normalize_package_part
        labels = {normalize_package_part(item['label']): item['label']
                  for item in get_booking_price_breakdown(booking)['items']}
        detail['items'] = [{'label': labels.get(normalize_package_part(part), part.strip()), 'amount': None}
                           for part in (booking.package_type or '').split('+') if part.strip()]
    return {'version': version, 'fields': review_fields(booking), 'images': images,
            'design_images': designs, 'item_prices_available': available, **detail}


def check_review_version(booking, data, original=None):
    original = original or review_baseline(booking)
    if data.get('original_version') and data['original_version'] != original['version']:
        raise ValidationError('Your current booking has changed. Please close and reopen Request Changes to review the latest details.')
    return original


def details_changed(before, after):
    names = ('event_type', 'event_date', 'event_time', 'event_end_time', 'event_end_date',
             'event_location', 'venue_landmark', 'package_type', 'design_theme', 'color_palette',
             'motto_text', 'special_requests', 'event_lat', 'event_lng')
    def canonical(name, value):
        if name in ('event_lat', 'event_lng'):
            return Decimal(value).quantize(Decimal('.000001')) if value not in (None, '') else None
        value = str(value or '').strip()
        if name == 'color_palette':
            return sorted(part.strip().lower() for part in value.split(',') if part.strip())
        return value
    return any(canonical(name, before.get(name)) != canonical(name, after.get(name)) for name in names)


def preview_review(booking, data, original):
    proposed = prepare_proposal(booking, data)
    fields = review_fields(proposed)
    amounts = payment_amounts(booking.total_price, proposed.total_price, verified_paid(booking))
    removals = set(data.getlist('remove_images[]')) & {image['id'] for image in original['images']}
    try:
        additions = int(data.get('new_image_count', '0'))
    except (TypeError, ValueError):
        raise ValidationError('Please check your selected reference pictures.')
    if additions < 0 or len(original['images']) - len(removals) + additions > 4:
        raise ValidationError('Keep a maximum of four reference images.')
    breakdown = review_breakdown(proposed)
    if fields['package_type'] == original['fields']['package_type'] and not original['item_prices_available']:
        breakdown['items'] = original['items']
    return {'success': True, 'original': original, 'proposed': fields,
            **breakdown,
            'payment_review_required': amounts['additional'] > amounts['remaining'],
            'payment': {name: str(value.quantize(Decimal('.01'))) for name, value in amounts.items()},
            'has_changes': details_changed(original['fields'], fields) or bool(removals or additions)}
