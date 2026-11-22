"""Retain the submitted canvas independently of the customer's editable design."""
import json
from collections import Counter
from uuid import uuid4

from django.core.files.base import ContentFile

from .canvas_uploads import owned_uploads, resolve_upload_object, upload_payload, visible_placements
from .models import Design


def save_booking_design_reference(booking, user_design, *, selection_item=None):
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
    metadata = {'version': 1, 'booking_package': booking.package_type,
                'canvas': state, 'custom_items': items}
    if selection_item:
        metadata.update(version=2, kind=selection_item['kind'],
                        kind_label=selection_item['offer'].get_kind_display(),
                        source_design_id=user_design.pk, design_name=user_design.name,
                        offer_id=selection_item['offer'].pk, offer_name=selection_item['item'].name,
                        pricing_mode=selection_item['pricing_mode'], amount=str(selection_item['amount']))
    submitted = Design(
        booking=booking, style=user_design.name[:50], color_palette='Custom', image=image,
        price_estimate=selection_item['amount'] if selection_item else booking.total_price,
        status='finalized', reference_snapshot=metadata)
    try:
        submitted.save()
        submitted.uploads.set([uploads[pk] for pk in retained_ids])
    except Exception:
        if submitted.image and submitted.image._committed:
            submitted.image.delete(save=False)
        raise
    return submitted
