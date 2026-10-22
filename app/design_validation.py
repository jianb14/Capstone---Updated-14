"""Catalog identity, explicit offer rules, and the shared booking eligibility check."""
import json
from collections import Counter
from urllib.parse import urlsplit

from django.core import signing
from django.db.models import Q, Prefetch
from django.templatetags.static import static

from .models import CanvasAsset, DesignOffer, DesignRequirement, OfferInclusion

KINDS = dict(DesignOffer.TYPES)
TOKEN_SALT = 'canvas-catalog-v1'


def available(obj, kind):
    return kind in KINDS and getattr(obj, 'available_' + kind, False)


def asset_source(asset):
    return asset.image.url if asset.image else static(asset.static_path) if asset.static_path else ''


def asset_token(asset):
    # Stable across requests, so reopening a design preserves the same identity.
    return signing.Signer(salt=TOKEN_SALT).sign_object([asset.pk, asset.item_type, asset_source(asset)])


def asset_payload(asset):
    return {
        'id': asset.pk, 'label': asset.label, 'src': asset_source(asset),
        'token': asset_token(asset), 'category_id': asset.category_id,
        'category': asset.category.name.lower().strip(), 'type': asset.item_type,
        'width': asset.width, 'height': asset.height,
        'builtin_key': asset.builtin_key,
    }


def eligible_assets(offer):
    field = 'available_' + offer.kind
    return CanvasAsset.objects.filter(
        is_active=True, category__is_active=True,
        **{field: True, 'category__' + field: True},
    ).filter(Q(image__isnull=False) & ~Q(image='') | ~Q(static_path='') | Q(item_type='i-text'))


class EvaluationCatalog:
    """Request-local metadata shared by saved cards and the offer picker."""
    def __init__(self, designs=()):
        designs = tuple(designs)
        ids = {d.design_offer_id for d in designs if d.design_offer_id}
        packages = {d.base_package_id for d in designs if d.base_package_id}
        offers = DesignOffer.objects.filter(Q(is_enabled=True) | Q(pk__in=ids) | Q(package_id__in=packages)).select_related(
            'package', 'entrance', 'stand',
        ).prefetch_related(
            Prefetch('requirements', queryset=DesignRequirement.objects.select_related('category')),
            Prefetch('inclusions', queryset=OfferInclusion.objects.only('offer_id', 'row_type', 'category_id')),
        ).order_by('id')
        self.offers = {offer.pk: offer for offer in offers}
        self.packages = {offer.package_id: offer for offer in self.offers.values() if offer.package_id}
        self._assets = {}

    def rules(self, offer):
        return list(self.offers[offer.pk].requirements.all())

    def unresolved(self, offer):
        return any(row.row_type == 'item' and not row.category_id for row in self.offers[offer.pk].inclusions.all())

    def assets(self, offer):
        if offer.kind not in self._assets:
            self._assets[offer.kind] = {asset.pk: asset for asset in eligible_assets(offer).select_related('category').order_by()}
        return self._assets[offer.kind]


def setup_errors(offer, catalog=None):
    errors = []
    if not offer.item.is_active or offer.price is None:
        errors.append('This offer must be active and have a standalone price.')
    rules = catalog.rules(offer) if catalog else list(offer.requirements.select_related('category'))
    unresolved = catalog.unresolved(offer) if catalog else offer.inclusions.filter(row_type='item', category__isnull=True).exists()
    if unresolved:
        errors.append('Review imported inclusions: choose a canvas category or change the row to Service.')
    if not any(r.required for r in rules):
        errors.append('Select at least one required category before enabling the designer.')
    category_ids = {asset.category_id for asset in catalog.assets(offer).values()} if catalog else set(eligible_assets(offer).values_list('category_id', flat=True))
    for rule in rules:
        if not rule.category.is_active or not available(rule.category, offer.kind):
            errors.append(f'{rule.category.name}: category is not available for this design type.')
        elif rule.category_id not in category_ids:
            errors.append(f'{rule.category.name}: add an active asset available for this design type.')
    return errors


def offer_is_ready(offer, catalog=None):
    return offer.is_enabled and not setup_errors(offer, catalog)


def offer_payload(offer):
    return {
        'id': offer.pk, 'kind': offer.kind, 'name': offer.name,
        'price': str(offer.price or 0), 'max_balloon_colors': offer.max_balloon_colors,
        'enabled': offer_is_ready(offer),
        'requirements': [{
            'category_id': r.category_id, 'name': r.display_name or r.category.name, 'category_name': r.category.name, 'is_balloon': r.category.is_balloon,
            'required': r.required, 'minimum': r.minimum, 'maximum': r.maximum,
        } for r in offer.requirements.select_related('category')],
    }


def design_offer(design, catalog=None):
    if design.design_offer_id:
        return catalog.offers.get(design.design_offer_id) if catalog else design.design_offer
    if design.base_package_id:
        return catalog.packages.get(design.base_package_id) if catalog else DesignOffer.objects.filter(package_id=design.base_package_id).first()
    return None


def _source_matches(actual, expected):
    if not actual or not expected:
        return False
    actual, expected = urlsplit(actual), urlsplit(expected)
    if actual.scheme == 'data':
        return False
    return actual.path == expected.path and (not expected.netloc or actual.netloc == expected.netloc)


def resolve_catalog_object(obj, assets):
    """Never infer an official asset from a customer-supplied category label."""
    if obj.get('_designSource') == 'reference' or obj.get('_isBgImage') or obj.get('_isArtboard'):
        return None
    if obj.get('_assetId'):
        try:
            asset = assets.get(int(obj['_assetId']))
            if not asset or signing.Signer(salt=TOKEN_SALT).unsign_object(obj.get('_assetToken', '')) != [asset.pk, asset.item_type, asset_source(asset)]:
                return None
        except (ValueError, TypeError, signing.BadSignature):
            return None
        if asset.item_type == 'i-text':
            return asset if obj.get('type') in ('i-text', 'textbox', 'text') else None
        if obj.get('type') == 'image':
            return asset if _source_matches(obj.get('src'), asset_source(asset)) else None
        # Fabric SVGs are a single catalog placement, not one item per SVG path.
        svg_types = ('group', 'path', 'rect', 'circle', 'ellipse', 'polygon', 'polyline', 'line')
        if obj.get('_isColorableSVG') and obj.get('type') in svg_types and obj.get('_assetSource') == asset_source(asset):
            if obj.get('type') == 'group' and not obj.get('objects'):
                return None
            return asset
        return None
    # Legacy raster objects can be mapped only by an unambiguous catalog source.
    matches = [a for a in assets.values() if _source_matches(obj.get('src'), asset_source(a))]
    return matches[0] if len(matches) == 1 else None


def evaluate_design(canvas_json, offer, catalog=None):
    counts, invalid = Counter(), []
    result = {'can_book': False, 'counts': {}, 'missing_requirements': [], 'invalid_items': invalid, 'rows': []}
    try:
        state = json.loads(canvas_json) if isinstance(canvas_json, str) else canvas_json
        if not isinstance(state, dict) or not isinstance(state.get('objects'), list):
            raise ValueError
    except (ValueError, TypeError):
        invalid.append('Canvas data is invalid.')
        return result
    if not offer:
        invalid.append('Choose a Package, Entrance Arch, or Welcome Stand before booking.')
        return result
    if not offer_is_ready(offer, catalog):
        invalid.append('This design offer is temporarily unavailable. Please choose an available offer.')
    rules = catalog.rules(offer) if catalog else list(offer.requirements.select_related('category'))
    rules_by_category = {r.category_id: r for r in rules}
    assets = catalog.assets(offer) if catalog else {a.pk: a for a in eligible_assets(offer).select_related('category')}
    balloon_colors = set()
    for obj in state['objects']:
        if not isinstance(obj, dict):
            invalid.append('A canvas item is invalid.')
            continue
        if obj.get('_isArtboard') or obj.get('_isBgImage') or obj.get('_designSource') == 'reference':
            continue
        asset = resolve_catalog_object(obj, assets)
        if asset is None:
            if obj.get('_assetId') or obj.get('_designSource') == 'catalog' or obj.get('_packageCategory', 'custom') not in ('custom', '', None):
                invalid.append('Re-add an unrecognized catalog item from the asset list so it can be counted.')
            continue
        if asset.category_id not in rules_by_category:
            invalid.append(f'{asset.label} is not included in the selected offer.')
            continue
        if obj.get('visible') is False or obj.get('opacity', 1) == 0 or obj.get('scaleX', 1) == 0 or obj.get('scaleY', 1) == 0:
            continue
        if asset.item_type == 'i-text' and not str(obj.get('text', '')).strip():
            continue
        counts[asset.category_id] += 1
        if asset.category.is_balloon:
            color = obj.get('_currentColor') or obj.get('fill')
            if isinstance(color, str) and color and color not in ('transparent', 'rgba(255, 255, 255, 0.2)'):
                balloon_colors.add(color.lower())
    for rule in rules:
        used = counts[rule.category_id]
        missing = max(0, rule.minimum - used)
        over = rule.maximum is not None and used > rule.maximum
        row = {'category_id': rule.category_id, 'name': rule.display_name or rule.category.name, 'required': rule.required,
               'minimum': rule.minimum, 'maximum': rule.maximum, 'used': used, 'missing': missing, 'over_limit': over}
        result['rows'].append(row)
        if missing:
            result['missing_requirements'].append(row)
        if over:
            invalid.append(f'{rule.category.name}: maximum {rule.maximum}, currently {used}.')
    if offer.max_balloon_colors and len(balloon_colors) > offer.max_balloon_colors:
        invalid.append(f'Use no more than {offer.max_balloon_colors} balloon colors.')
    result['counts'] = dict(counts)
    result['invalid_items'] = list(dict.fromkeys(invalid))
    result['can_book'] = not result['invalid_items'] and not result['missing_requirements'] and bool(rules)
    return result


def evaluate_saved_design(design, catalog=None):
    return evaluate_design(design.canvas_json, design_offer(design, catalog), catalog)


def restore_catalog_metadata(canvas_json, offer):
    """Upgrade only uniquely recognizable legacy catalog objects, in memory."""
    try:
        state = json.loads(canvas_json)
        assets = {a.pk: a for a in eligible_assets(offer)} if offer else {}
        for obj in state.get('objects', []):
            if not isinstance(obj, dict) or obj.get('_assetId'):
                continue
            asset = resolve_catalog_object(obj, assets)
            if asset:
                obj.update(_assetId=asset.pk, _assetToken=asset_token(asset), _assetSource=asset_source(asset),
                           _designSource='catalog', _categoryId=asset.category_id)
        return state
    except (ValueError, TypeError, AttributeError):
        return {'objects': []}


def evaluation_message(evaluation):
    parts = [f"{r['name']}: add {r['missing']} more" for r in evaluation['missing_requirements']]
    return '; '.join(parts + evaluation['invalid_items']) or 'Ready to book'


def selection_groups(catalog=None):
    catalog = catalog or EvaluationCatalog()
    groups = []
    for kind, label in KINDS.items():
        offers = []
        for offer in catalog.offers.values():
            if offer.kind == kind and offer.is_enabled and offer_is_ready(offer, catalog):
                offer.required_rules = [r for r in catalog.rules(offer) if r.required]
                offers.append(offer)
        groups.append({'kind': kind, 'label': label, 'offers': offers})
    return groups


def design_card_status(evaluation):
    """Short, customer-facing guidance; the editor keeps the full validation details."""
    if evaluation['can_book']:
        return {'message': 'Required items complete. Your design is ready to book.', 'items': [], 'more': False}
    items = [f"Add {row['missing']} more: {row['name']}" for row in evaluation['missing_requirements']]
    over = [row for row in evaluation['rows'] if row['over_limit']]
    items.extend(f"Remove {row['used'] - row['maximum']}: {row['name']} ({row['maximum']} included)" for row in over)
    if len(evaluation['invalid_items']) > len(over):
        items.append('Review the flagged items in the editor.')
    message = 'Add the missing items to make this design ready to book.' if evaluation['missing_requirements'] else 'Review this design in the editor before booking.'
    return {'message': message,
            'items': items[:2], 'more': len(items) > 2}
