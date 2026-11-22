"""Retain the submitted canvas independently of the customer's editable design."""
import json
from collections import Counter
from uuid import uuid4

from django.core.files.base import ContentFile

from .canvas_uploads import owned_uploads, resolve_upload_object, upload_payload, visible_placements
from .models import Design


def save_booking_design_reference(booking, user_design):
    state = json.loads(user_design.canvas_json)
    placements = list(visible_placements(state.get('objects', [])))
    retained = list(visible_placements(state.get('objects', []), include_hidden=True))
    uploads = {upload.pk: upload for upload in owned_uploads(
        [obj.get('_uploadId') for obj in retained if isinstance(obj, dict)], user_design.user_id)}
    retained_ids = {upload.pk for obj in retained if (upload := resolve_upload_object(obj, uploads))}
    counts = Counter()
    for obj in placements:
        upload = resolve_upload_object(obj, uploads)
        if upload:
            counts[upload.pk] += 1
    items = []
    for pk, quantity in counts.items():
        item = upload_payload(uploads[pk])
        item.update(category=uploads[pk].category.name, quantity=quantity)
        # A submitted reference no longer needs the editable placement signature.
        item.pop('token', None)
        items.append(item)
    image = ''
    if user_design.thumbnail:
        with user_design.thumbnail.open('rb') as source:
            image = ContentFile(source.read(), name=f'{uuid4().hex}.png')
    submitted = Design.objects.create(
        booking=booking, style=user_design.name[:50], color_palette='Custom', image=image,
        price_estimate=booking.total_price, status='finalized',
        reference_snapshot={'version': 1, 'booking_package': booking.package_type,
                            'canvas': state, 'custom_items': items})
    submitted.uploads.set([uploads[pk] for pk in retained_ids])
    return submitted
