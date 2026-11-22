"""Resolve one event's typed design selection and its server-owned quote."""
import hashlib
import logging
import re
from decimal import Decimal
from functools import wraps

from django.core import signing
from django.core.exceptions import ValidationError
from django.http import Http404
from django.urls import reverse

from .design_validation import EvaluationCatalog, design_offer, evaluate_saved_design, evaluation_message
from .models import AddOn, AdditionalOnly, Package, ServiceChargeConfig, UserDesign

KINDS = ('package', 'entrance', 'stand')
KIND_LABELS = {'package': 'Package', 'entrance': 'Entrance Arch', 'stand': 'Welcome Stand'}
QUOTE_SALT = 'saved-design-booking-v1'


def _validate_kinds(kinds):
    if not kinds or len(kinds) > 3 or any(kinds.count(kind) > 1 for kind in KINDS):
        raise ValidationError('Choose at most one package, one entrance arch, and one welcome stand.')
    if 'package' not in kinds and 'entrance' not in kinds:
        raise ValidationError('Choose a package or entrance arch before adding a welcome stand.')


def _entries(pairs):
    kinds = [kind for kind, item in pairs]
    _validate_kinds(kinds)
    entries = []
    for kind, item in pairs:
        solo = kind == 'entrance' and 'package' not in kinds
        amount = item.solo_price if solo else item.price
        if not item.is_active or amount is None or not amount.is_finite() or amount < 0 or (solo and amount == 0):
            raise ValidationError(f'{item.name} is unavailable for this booking combination. Choose an available package or entrance.')
        entries.append({'kind': kind, 'item': item, 'amount': amount,
                        'label': item.name + (' (Solo)' if solo else ''),
                        'pricing_mode': 'solo' if solo else 'addon' if kind == 'entrance' else kind})
    entries.sort(key=lambda entry: KINDS.index(entry['kind']))
    if len(' + '.join(entry['label'] for entry in entries)) > 500:
        raise ValidationError('The selected offer names are too long for one booking. Please contact our team.')
    return entries


def resolve_design_selection(user, ids, *, lock=False):
    ids = list(ids)
    if not 1 <= len(ids) <= 3 or any(not str(pk).isascii() or not str(pk).isdigit() or len(str(pk)) > 18 or int(pk) <= 0 for pk in ids):
        raise ValidationError('Choose between one and three valid saved designs.')
    ids = [int(pk) for pk in ids]
    if len(set(ids)) != len(ids):
        raise ValidationError('The same design cannot be selected more than once.')
    query = UserDesign.objects.filter(user=user, pk__in=ids).select_related('design_offer', 'base_package')
    if lock:
        query = query.select_for_update(of=('self',))
    designs = list(query.order_by('pk'))
    if len(designs) != len(ids):
        raise Http404('Design not found.')
    catalog = EvaluationCatalog(designs)
    if lock:
        from .views.common import get_service_charge_config
        ServiceChargeConfig.objects.select_for_update().get(pk=get_service_charge_config().pk)
    pairs, by_kind = [], {}
    for design in designs:
        offer = design_offer(design, catalog)
        evaluation = evaluate_saved_design(design, catalog)
        if not evaluation['can_book']:
            error = ValidationError(evaluation_message(evaluation))
            error.design, error.evaluation = design, evaluation
            raise error
        item = offer.item
        if lock:
            item = type(item).objects.select_for_update().get(pk=item.pk)
        pairs.append((offer.kind, item))
        by_kind[offer.kind] = (design, offer)
    entries = _entries(pairs)
    for entry in entries:
        entry['design'], entry['offer'] = by_kind[entry['kind']]
    return entries


def design_payload(design, offer, evaluation):
    item = offer.item if offer else None
    return {'id': design.pk, 'name': design.name, 'kind': offer.kind if offer else '',
            'offer_name': offer.name if offer else '', 'ready': bool(evaluation['can_book']),
            'price': str(item.price) if item else '0',
            'solo_price': str(item.solo_price) if offer and offer.kind == 'entrance' and item.solo_price is not None else None,
            'thumbnail': reverse('user_design_preview', args=[design.pk]) + '?v=' + str(design.updated_at.timestamp()) if design.thumbnail else '',
            'updated_at': design.updated_at.isoformat()}


def selection_payload(entries):
    from .booking_themes import theme_decor_capabilities
    from .views.common import normalize_package_part
    capabilities = theme_decor_capabilities() if entries else {}
    result = []
    for entry in entries:
        design, offer = entry['design'], entry['offer']
        payload = design_payload(design, offer, {'can_book': True})
        payload.update(amount=str(entry['amount'].quantize(Decimal('.01'))),
                       label=entry['label'], pricing_mode=entry['pricing_mode'], kind_label=KIND_LABELS[entry['kind']],
                       theme_allowed=capabilities.get(normalize_package_part(offer.name), True))
        result.append(payload)
    return result


def _quote_data(entries):
    return {'designs': [[e['design'].pk, e['design'].updated_at.isoformat(), e['offer'].pk, e['kind'], e['label'],
             str(e['amount'].quantize(Decimal('.01'))), hashlib.sha256(e['design'].canvas_json.encode()).hexdigest()]
            for e in entries], 'fee_policy': fee_policy_payload()}


def fee_policy_payload():
    from .views.common import get_booking_duration_policy, get_logistics_origin, get_service_charge_config
    config = get_service_charge_config()
    origin = get_logistics_origin(config)
    duration = get_booking_duration_policy()
    return {'logistics': {'base': float(config.amount), 'shopLat': origin[0] if origin else None, 'shopLng': origin[1] if origin else None,
                         'freeRadius': float(config.free_radius_km), 'perKm': float(config.per_km_rate),
                         'maxCap': float(config.max_fee_cap)},
            'duration': {'minHours': duration['min_hours'], 'includedHours': duration['included_hours'],
                         'overtimeRate': float(duration['overtime_rate']), 'maxHours': duration['max_hours']},
            'notes': config.notes or ''}


def selection_quote(entries):
    return signing.Signer(salt=QUOTE_SALT).sign_object(_quote_data(entries), compress=True)


def quote_matches(token, entries):
    try:
        return signing.Signer(salt=QUOTE_SALT).unsign_object(token) == _quote_data(entries)
    except (signing.BadSignature, ValueError, TypeError):
        return False


def parse_catalog_selection(label):
    """Match whole catalog names, including literal plus signs, before separators."""
    def normalized(value):
        return re.sub(r'\s*\+\s*', ' + ', ' '.join(value.split())).lower()
    text = normalized(label or '')
    if not text:
        raise ValidationError('Choose a package or entrance arch before continuing.')
    candidates = []
    for kind, model in (('package', Package), ('entrance', AddOn), ('stand', AdditionalOnly)):
        for item in model.objects.all():
            candidates.append((normalized(item.name), kind, item, False))
            if kind == 'entrance':
                candidates.append((normalized(item.name + ' (Solo)'), kind, item, True))
                candidates.append((normalized(item.name + ' (Add-on)'), kind, item, False))
            if kind == 'stand':
                candidates.append((normalized(item.name + ' (Additional)'), kind, item, False))
    solutions = []
    def match(remainder, chosen):
        if len(solutions) > 1 or len(chosen) > 3:
            return
        if not remainder:
            solutions.append(chosen)
            return
        for name, kind, item, solo in candidates:
            if remainder == name:
                match('', chosen + [(kind, item, solo)])
            elif remainder.startswith(name + ' + '):
                match(remainder[len(name) + 3:], chosen + [(kind, item, solo)])
    match(text, [])
    if not solutions:
        if any(text == name or text.startswith(name + ' + ') or (' + ' + name) in text for name, *_ in candidates):
            raise ValidationError('One of the selected items is unavailable. Please update your selection.')
        return None  # Existing genuinely bespoke labels remain supported.
    if len(solutions) != 1:
        raise ValidationError('One of the selected items is unavailable or ambiguous. Please update your selection.')
    return solutions[0]


def validate_catalog_selection(label):
    parsed = parse_catalog_selection(label)
    if parsed is None:
        return None
    entries = _entries([(kind, item) for kind, item, solo in parsed])
    for kind, item, solo in parsed:
        if solo != (kind == 'entrance' and not any(e['kind'] == 'package' for e in entries)):
            raise ValidationError('Review the entrance solo or with-package rate before continuing.')
    return ' + '.join(e['label'] for e in entries)


def catalog_label(entry):
    suffix = ' (Add-on)' if entry['pricing_mode'] == 'addon' else ' (Additional)' if entry['kind'] == 'stand' else ''
    return entry['label'] + suffix


def save_selection_references(booking, entries, *, created_files=None):
    from .design_reference_snapshot import save_booking_design_reference
    saved = []
    try:
        for entry in entries:
            saved.append(save_booking_design_reference(booking, entry['design'], selection_item=entry))
            if created_files is not None and saved[-1].image:
                created_files.append((saved[-1].image.storage, saved[-1].image.name))
    except Exception:
        if created_files is None:
            for reference in saved:
                if reference.image:
                    reference.image.delete(save=False)
        raise
    return saved


def cleanup_booking_files(view):
    """New uploads must follow rollback through the outer submission receipt too."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        request._new_booking_files = []
        try:
            return view(request, *args, **kwargs)
        except Exception:
            for storage, name in request._new_booking_files:
                try:
                    storage.delete(name)
                except Exception:
                    logging.getLogger(__name__).exception('Could not clean a rolled-back booking upload.')
            raise
    return wrapped


def save_tracked_file(instance, field_name, created_files):
    try:
        instance.save()
    finally:
        field = getattr(instance, field_name)
        if field and field._committed:
            created_files.append((field.storage, field.name))
