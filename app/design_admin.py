"""Controls embedded in the existing Package / Entrance / Stand edit forms."""
from functools import wraps

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render, redirect
from .canvas_builtins import BUILTIN_MESSAGE

from .design_validation import KINDS, available, eligible_assets
from .models import Package, AddOn, AdditionalOnly, CanvasCategory, CanvasAsset, DesignOffer, DesignRequirement

OWNERS = {'package': (Package, 'package'), 'entrance': (AddOn, 'addon'), 'stand': (AdditionalOnly, 'additional')}
TEMPLATES = {'package': 'package', 'entrance': 'addon', 'stand': 'additional'}


def availability_values(request, default='package'):
    values = request.POST.getlist('available_for') if 'availability_present' in request.POST else [default]
    if not values or any(v not in KINDS for v in values):
        raise ValidationError('Select at least one valid design type under Available for.')
    return {'available_' + kind: kind in values for kind in KINDS}


def render_offer_form(request, template, context=None, **kwargs):
    context = dict(context or {})
    kind = next(k for k, name in TEMPLATES.items() if template.endswith('/' + name + '_form.html'))
    item = context.get(OWNERS[kind][1])
    from .offer_editor import editor_response, OfferDetailsForm
    form = OfferDetailsForm(request.POST, kind=kind) if request.method == 'POST' else None
    return editor_response(request, kind, item, form=form)


def parse_rules(request, kind):
    rows = []
    categories = CanvasCategory.objects.filter(**{'available_' + kind: True})
    known_ids = set(categories.values_list('id', flat=True))
    for key in request.POST:
        if key.startswith('rule_') and key.endswith('_included'):
            try:
                cid = int(key.split('_')[1])
            except (ValueError, IndexError):
                raise ValidationError('Invalid design category.')
            if cid not in known_ids:
                raise ValidationError('A selected category is unavailable for this design type.')
    for category in categories:
        prefix = 'rule_' + str(category.pk) + '_'
        if prefix + 'included' not in request.POST:
            continue
        required = prefix + 'required' in request.POST
        try:
            minimum = int(request.POST.get(prefix + 'minimum', '0'))
            raw_max = request.POST.get(prefix + 'maximum', '').strip()
            maximum = int(raw_max) if raw_max else None
        except ValueError:
            raise ValidationError(f'{category.name}: quantities must be whole numbers.')
        if minimum < 0 or maximum is not None and maximum < 1:
            raise ValidationError(f'{category.name}: use non-negative minimums and positive maximums.')
        if required and minimum < 1 or not required and minimum != 0:
            raise ValidationError(f'{category.name}: required items need a minimum of 1; optional items need 0.')
        if maximum is not None and minimum > maximum:
            raise ValidationError(f'{category.name}: minimum cannot exceed maximum.')
        rows.append({'category': category, 'required': required, 'minimum': minimum, 'maximum': maximum})
    raw_colors = request.POST.get('design_max_colors', '').strip()
    try:
        colors = int(raw_colors) if raw_colors else None
    except ValueError:
        raise ValidationError('Balloon color limit must be a positive whole number.')
    if colors is not None and colors < 1:
        raise ValidationError('Balloon color limit must be at least 1.')
    enabled = 'design_enabled' in request.POST
    if enabled:
        if not any(r['required'] for r in rows):
            raise ValidationError('Select at least one required category before enabling the designer.')
        dummy = DesignOffer(kind=kind)
        available_ids = set(eligible_assets(dummy).values_list('category_id', flat=True))
        for row in rows:
            if not row['category'].is_active or row['category'].pk not in available_ids:
                raise ValidationError(f"{row['category'].name}: add an active asset available for {KINDS[kind]} first.")
        if kind == 'entrance' and not request.POST.get('solo_price', '').strip():
            raise ValidationError('Set a solo price before enabling an Entrance design.')
    return rows, enabled, colors


def configure_design_offer(kind):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.user.role not in ('admin', 'staff'):
                return HttpResponseForbidden('Not allowed')
            if request.method != 'POST' or 'inclusions' in request.POST:
                from .offer_editor import offer_editor
                return offer_editor(request, kind, kwargs.get('id'))
            if request.method == 'POST' and 'design_rules_present' in request.POST:
                try:
                    request.design_configuration = parse_rules(request, kind)
                except ValidationError as exc:
                    messages.error(request, ' '.join(exc.messages))
                    item = get_object_or_404(OWNERS[kind][0], pk=kwargs['id']) if 'id' in kwargs else None
                    return render_offer_form(request, 'admin/package/' + TEMPLATES[kind] + '_form.html', {OWNERS[kind][1]: item})
            with transaction.atomic():
                return view(request, *args, **kwargs)
        return wrapped
    return decorate


def store_offer_config(request, item, kind):
    offer, _ = DesignOffer.objects.get_or_create(kind=kind, **{kind: item})
    if hasattr(request, 'design_configuration'):
        rows, offer.is_enabled, offer.max_balloon_colors = request.design_configuration
        offer.save()
        offer.requirements.all().delete()
        DesignRequirement.objects.bulk_create([DesignRequirement(offer=offer, **row) for row in rows])
    # Compatibility for older admin form POSTs: convert once into the same source.
    from .offer_inclusions import import_rows, store_inclusions
    categories = list(CanvasCategory.objects.filter(**{'available_' + kind: True}))
    canonical = import_rows(item.features, categories, list(offer.requirements.select_related('category')))
    for row in canonical:
        if not row['category_id']:
            row['row_type'] = 'service'
            row['required_minimum'] = 0
    store_inclusions(offer, canonical, offer.max_balloon_colors, offer.is_enabled)


def render_canvas_form(request, template, context=None, **kwargs):
    context = dict(context or {})
    item = context.get('canvas_asset') or context.get('category')
    selected = request.POST.getlist('available_for') if request.method == 'POST' and 'availability_present' in request.POST else [k for k in KINDS if available(item, k)] if item else [request.GET.get('kind', 'package')]
    context['availability_choices'] = [{'kind': k, 'label': label, 'checked': k in selected} for k, label in KINDS.items()]
    context['selected_kind'] = request.POST.get('kind', request.GET.get('kind', 'package'))
    if template.endswith('canvas_asset_form.html'):
        context['categories'] = list(CanvasCategory.objects.order_by('order', 'name'))
        context['category_types'] = {c.pk: [k for k in KINDS if available(c, k)] for c in context['categories']}
    return render(request, template, context, **kwargs)


def configure_canvas_availability(is_asset=False):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.user.role not in ('admin', 'staff'):
                return HttpResponseForbidden('Not allowed')
            if 'id' in kwargs:
                model = CanvasAsset if is_asset else CanvasCategory
                if model.objects.filter(pk=kwargs['id'], builtin_key__isnull=False).exists():
                    messages.info(request, BUILTIN_MESSAGE)
                    return redirect('admin_canvas_assets')
            if request.method == 'POST':
                try:
                    values = availability_values(request)
                    if is_asset:
                        category = CanvasCategory.objects.filter(pk=request.POST.get('category')).first()
                        if category and any(values['available_' + k] and not available(category, k) for k in KINDS):
                            raise ValidationError('Choose a category available in every selected design type, or update the category first.')
                    elif 'id' in kwargs:
                        for k in KINDS:
                            if not values['available_' + k] and CanvasAsset.objects.filter(category_id=kwargs['id'], **{'available_' + k: True}).exists():
                                raise ValidationError(f'Remove {KINDS[k]} availability from this category\'s assets first.')
                    request.canvas_availability = values
                except (ValidationError, ValueError, TypeError) as exc:
                    messages.error(request, ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'Choose a valid category.')
                    model = CanvasAsset if is_asset else CanvasCategory
                    item = get_object_or_404(model, pk=kwargs['id']) if 'id' in kwargs else None
                    key = 'canvas_asset' if is_asset else 'category'
                    return render_canvas_form(request, 'admin/canvas/canvas_' + ('asset' if is_asset else 'category') + '_form.html', {key: item})
            with transaction.atomic():
                response = view(request, *args, **kwargs)
                if response.status_code == 302 and request.method == 'POST' and response.url.endswith('/canvas-assets/'):
                    response['Location'] = response.url + '?kind=' + request.POST.get('kind', 'package') if request.POST.get('kind') in KINDS else response.url
                return response
        return wrapped
    return decorate
