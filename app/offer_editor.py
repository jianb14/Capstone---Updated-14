"""One form and one inclusion source for all three catalog offer types."""
import json

from django import forms
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .design_validation import eligible_assets
from .models import AddOn, AdditionalOnly, CanvasCategory, DesignOffer, Package
from .offer_inclusions import import_rows, store_inclusions

CATALOG = {'package': (Package, 'Package'), 'entrance': (AddOn, 'Entrance Arch'), 'stand': (AdditionalOnly, 'Welcome Stand')}
ROW_FIELDS = ('row_type', 'name', 'quantity', 'category_id', 'required_minimum', 'order')
MAX_INTEGER = 2147483647


class OfferDetailsForm(forms.Form):
    name = forms.CharField(max_length=100, label='Offer name')
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}), label='Short description')
    price = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0, label='Price (PHP)')
    solo_price = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0, label='Solo price (PHP)', required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}), label='Additional notes')
    is_featured = forms.BooleanField(required=False, label='Mark as Most Popular')
    design_enabled = forms.BooleanField(required=False, label='Available in Create Design')
    design_max_colors = forms.IntegerField(required=False, min_value=1, max_value=MAX_INTEGER, label='Maximum balloon colors')

    def __init__(self, *args, kind, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'] = forms.CharField(max_length=100 if kind == 'package' else 150, label='Offer name')
        if kind != 'package':
            del self.fields['description']
            del self.fields['is_featured']
        if kind != 'entrance':
            del self.fields['solo_price']
        else:
            self.fields['solo_price'].required = True
            self.fields['price'].label = 'With-package price (PHP)'
            del self.fields['notes']
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'oe-checkbox'
            else:
                field.widget.attrs['class'] = 'oe-input'
                field.widget.attrs['aria-describedby'] = f'error_{name}'
        self.fields['design_max_colors'].widget.attrs['placeholder'] = 'No color limit'
        self.fields['name'].widget.attrs['placeholder'] = 'e.g. Package 1-A' if kind == 'package' else 'e.g. Entrance A' if kind == 'entrance' else 'e.g. Stand A'


def rows_for_offer(offer, item, kind):
    if offer and offer.inclusions.exists():
        return list(offer.inclusions.values(*ROW_FIELDS))
    categories = list(CanvasCategory.objects.filter(**{'available_' + kind: True}))
    rules = list(offer.requirements.select_related('category')) if offer else []
    return import_rows(item.features if item else '', categories, rules)


def validate_rows(raw, categories):
    errors, rows, used = {}, [], set()
    if not isinstance(raw, list) or not raw:
        return [], {'inclusions': ['Add at least one item or service.']}
    if len(raw) > 200:
        return [], {'inclusions': ['Use no more than 200 inclusion rows.']}
    by_id = {c.pk: c for c in categories}
    for index, value in enumerate(raw):
        row_errors = {}
        if not isinstance(value, dict):
            errors[str(index)] = {'name': ['This row is invalid.']}
            continue
        name = str(value.get('name') or '').strip()
        row_type = value.get('row_type', 'item')
        if not name or len(name) > 500:
            row_errors['name'] = ['Enter an item or service name (up to 500 characters).']
        if row_type not in ('item', 'service'):
            row_errors['row_type'] = ['Choose Canvas item or Service.']
        def number(key, default=None):
            raw_value = value.get(key)
            if raw_value in ('', None):
                return default
            try:
                if isinstance(raw_value, bool) or not str(raw_value).isdigit():
                    raise ValueError
                result = int(raw_value)
                if result > MAX_INTEGER:
                    raise ValueError
                return result
            except (ValueError, TypeError):
                row_errors[key] = ['Enter a valid whole number.']
                return default
        quantity = number('quantity')
        minimum = number('required_minimum', 0)
        category_id = number('category_id') if row_type == 'item' else None
        if quantity == 0:
            row_errors['quantity'] = ['Use at least 1, or leave blank for Included.']
        if row_type == 'service':
            minimum = 0
        else:
            if 'required' in value:
                if not isinstance(value['required'], bool):
                    row_errors['required_minimum'] = ['Choose a valid required setting.']
                elif value['required'] and minimum < 1:
                    row_errors['required_minimum'] = ['Required items need a minimum of at least 1.']
                elif not value['required']:
                    minimum = 0
            if category_id is None:
                row_errors['category_id'] = ['Choose a canvas category, or change this row to Service.']
            elif category_id not in by_id:
                row_errors['category_id'] = ['This category is unavailable for this offer type.']
            elif category_id in used:
                row_errors['category_id'] = ['This category is already included. Edit its existing row.']
            else:
                used.add(category_id)
            if quantity is not None and minimum > quantity:
                row_errors['required_minimum'] = ['Required minimum cannot exceed quantity.']
        rows.append({'row_type': row_type, 'name': name, 'quantity': quantity, 'category_id': category_id, 'required_minimum': minimum, 'order': index})
        if row_errors:
            errors[str(index)] = row_errors
    return rows, errors


def validate_images(request, item):
    existing_ids = set(item.preview_images.values_list('pk', flat=True)) if item else set()
    try:
        removed = {int(pk) for pk in request.POST.get('remove_preview_ids', '').split(',') if pk.strip()}
    except ValueError:
        return [], set(), ['Invalid image selection.']
    if not removed.issubset(existing_ids):
        return [], set(), ['A selected image does not belong to this offer.']
    uploads = request.FILES.getlist('preview_images')
    errors = []
    if len(existing_ids - removed) + len(uploads) > 2:
        errors.append('Only 2 preview images are allowed in total. Remove an image before adding another.')
    for upload in uploads:
        try:
            forms.ImageField().clean(upload)
            upload.seek(0)
        except forms.ValidationError:
            errors.append(f'{upload.name}: choose a valid image file.')
    return uploads, removed, errors


def editor_response(request, kind, item=None, form=None, raw_rows=None, row_errors=None, image_errors=None):
    offer = DesignOffer.objects.filter(**{kind: item}).first() if item else None
    if form is None:
        initial = {key: getattr(item, key, '') for key in ('name', 'description', 'price', 'solo_price', 'notes', 'is_featured')} if item else {}
        initial.update(design_enabled=bool(offer and offer.is_enabled), design_max_colors=offer.max_balloon_colors if offer else None)
        form = OfferDetailsForm(kind=kind, initial=initial)
    categories = list(CanvasCategory.objects.filter(**{'available_' + kind: True}).order_by('order', 'name'))
    rows = raw_rows if isinstance(raw_rows, list) else rows_for_offer(offer, item, kind)
    previews = [{'id': p.pk, 'url': p.image.url} for p in item.preview_images.all()] if item else []
    context = {
        'offer_form': form, 'offer_kind': kind, 'offer_label': CATALOG[kind][1], 'catalog_item': item,
        'editor_data': {'rows': rows, 'categories': [{'id': c.pk, 'name': c.name, 'balloon': c.is_balloon, 'active': c.is_active} for c in categories],
                        'previews': previews, 'row_errors': row_errors or {}, 'image_errors': image_errors or []},
        'inclusions_json': json.dumps(rows), 'row_errors': row_errors or {}, 'image_errors': image_errors or [],
    }
    return render(request, 'admin/package/offer_form.html', context)


def offer_editor(request, kind, item_id=None):
    model = CATALOG[kind][0]
    item = get_object_or_404(model, pk=item_id) if item_id else None
    if request.method != 'POST':
        return editor_response(request, kind, item)
    form = OfferDetailsForm(request.POST, kind=kind)
    valid_details = form.is_valid()
    try:
        raw_rows = json.loads(request.POST.get('inclusions', '[]'))
    except (ValueError, TypeError):
        raw_rows = []
    categories = list(CanvasCategory.objects.filter(**{'available_' + kind: True}))
    rows, row_errors = validate_rows(raw_rows, categories)
    uploads, removed, image_errors = validate_images(request, item)
    if valid_details and form.cleaned_data['design_enabled']:
        if item and not item.is_active:
            form.add_error('design_enabled', 'Activate this catalog offer before enabling it in Create Design.')
        if not any(row['row_type'] == 'item' and row['required_minimum'] > 0 for row in rows):
            form.add_error('design_enabled', 'Select at least one required category before enabling the designer.')
        available_ids = set(eligible_assets(DesignOffer(kind=kind)).values_list('category_id', flat=True))
        for index, row in enumerate(rows):
            if row['row_type'] == 'item' and row['category_id'] and row['category_id'] not in available_ids:
                row_errors.setdefault(str(index), {}).setdefault('category_id', []).append('Add an active asset available for this offer type before enabling the designer.')
    if not form.is_valid() or row_errors or image_errors:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'errors': dict(form.errors), 'row_errors': row_errors, 'image_errors': image_errors}, status=400)
        return editor_response(request, kind, item, form, raw_rows, row_errors, image_errors)
    with transaction.atomic():
        data = form.cleaned_data
        creating = item is None
        item = item or model()
        for field in ('name', 'price', 'description', 'solo_price', 'notes', 'is_featured'):
            if field in form.fields:
                setattr(item, field, data[field])
        item.save()
        offer, _ = DesignOffer.objects.get_or_create(kind=kind, **{kind: item})
        store_inclusions(offer, rows, data['design_max_colors'], data['design_enabled'])
        item.preview_images.filter(pk__in=removed).delete()
        for upload in uploads:
            item.preview_images.create(image=upload, order=item.preview_images.count())
        from .views.common import log_action
        log_action(request.user, f"{'Created' if creating else 'Updated'} {CATALOG[kind][1].lower()} '{item.name}'.")
    messages.success(request, f'{CATALOG[kind][1]} saved successfully.')
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'redirect_url': reverse('admin_package_list')})
    return redirect('admin_package_list')
