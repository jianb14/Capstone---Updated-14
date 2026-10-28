"""Shared async content workspaces; every write is admin-only and CSRF protected."""
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from .account_lists import account_page_size
from .catalog_forms import FORMS, KINDS
from .models import AddOn, AdditionalOnly, CanvasAsset, CanvasCategory, GalleryCategory, GalleryImage, Package

RESOURCES = {
    'package': (Package, 'Package', 'Packages'), 'entrance': (AddOn, 'Entrance arch', 'Entrance arches'),
    'stand': (AdditionalOnly, 'Welcome stand', 'Welcome stands'),
    'gallery-image': (GalleryImage, 'Gallery image', 'Photos'), 'gallery-category': (GalleryCategory, 'Gallery category', 'Categories'),
    'canvas-asset': (CanvasAsset, 'Canvas asset', 'Assets'), 'canvas-category': (CanvasCategory, 'Canvas category', 'Categories'),
}
WORKSPACES = {
    'packages': ('Packages', 'Manage your packages, entrance arches and welcome stands.', 'admin_package_list', ('package', 'entrance', 'stand')),
    'gallery': ('Gallery', 'Organize the photos and categories your customers explore.', 'admin_gallery', ('gallery-image', 'gallery-category')),
    'canvas': ('Canvas Assets', 'Keep your design library organized and ready to use.', 'admin_canvas_assets', ('canvas-asset', 'canvas-category')),
}


def api_url(resource, action, pk=0):
    return reverse('admin_catalog_action', args=[resource, action, pk])


def private_json(data, status=200):
    response = JsonResponse(data, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


def image_url(item):
    if getattr(item, 'image', None):
        return item.image.url
    if getattr(item, 'static_path', ''):
        return static(item.static_path)
    if isinstance(item, (Package, AddOn, AdditionalOnly)):
        preview = next(iter(item.preview_images.all()), None)
        return preview.image.url if preview else ''
    return ''


def item_row(resource, item):
    is_offer = resource in ('package', 'entrance', 'stand')
    name = getattr(item, 'name', '') or getattr(item, 'label', '') or getattr(item, 'caption', '') or f'{RESOURCES[resource][1]} #{item.pk}'
    category = getattr(item, 'category', None)
    availability = ', '.join(label for key, label in KINDS if getattr(item, 'available_' + key, False))
    values = []
    if is_offer:
        values = [('Price', f'₱{item.price:,.2f}')]
        if resource == 'entrance':
            values.append(('Solo price', f'₱{item.solo_price:,.2f}' if item.solo_price is not None else 'Not set'))
    elif category:
        values = [('Category', category.name)]
        if resource == 'canvas-asset':
            values.append(('Size', f'{item.width} × {item.height} px'))
    else:
        count = getattr(item, 'item_count', None)
        if count is None:
            count = item.images.count() if resource == 'gallery-category' else item.assets.count()
        values = [('Display order', str(item.order)), ('Items', str(count))]
    return {'pk': item.pk, 'name': name, 'preview': image_url(item), 'values': values,
        'subtitle': f'#{item.pk}', 'availability': availability, 'has_status': hasattr(item, 'is_active'),
        'active': getattr(item, 'is_active', True), 'featured': getattr(item, 'is_featured', False),
        'protected': bool(getattr(item, 'builtin_key', None)),
        'detail_url': api_url(resource, 'detail', item.pk), 'edit_url': api_url(resource, 'edit', item.pk),
        'delete_url': api_url(resource, 'delete', item.pk)}


def workspace_context(request, workspace):
    from django.core.paginator import Paginator
    title, subtitle, route, resources = WORKSPACES[workspace]
    resource = request.GET.get('tab', resources[0])
    if resource not in resources:
        resource = resources[0]
    model, singular, plural = RESOURCES[resource]
    kind = request.GET.get('kind', 'package')
    if kind not in dict(KINDS):
        kind = 'package'
    queryset = model.objects.all()
    categories = GalleryCategory.objects.all() if workspace == 'gallery' else CanvasCategory.objects.filter(**{'available_' + kind: True}) if workspace == 'canvas' else []
    if workspace == 'canvas':
        queryset = queryset.filter(**{'available_' + kind: True})
        if resource == 'canvas-asset':
            queryset = queryset.filter(**{'category__available_' + kind: True})
    if resource.endswith('category'):
        queryset = queryset.annotate(item_count=Count('images' if workspace == 'gallery' else 'assets'))
    if resource in ('package', 'entrance', 'stand'):
        queryset = queryset.prefetch_related('preview_images')
    if resource in ('gallery-image', 'canvas-asset'):
        queryset = queryset.select_related('category')
    search = request.GET.get('q', '').strip()[:150]
    status = request.GET.get('status', '')
    category = request.GET.get('category') or request.GET.get('asset_category') or request.GET.get('image_category') or ''
    category = category if category.isdecimal() and len(category) < 12 else ''
    if search:
        field = 'caption' if resource == 'gallery-image' else 'label' if resource == 'canvas-asset' else 'name'
        matches = Q(**{field + '__icontains': search})
        if resource in ('gallery-image', 'canvas-asset'):
            matches |= Q(category__name__icontains=search)
        if search.lstrip('#').isdecimal() and len(search.lstrip('#')) < 12:
            matches |= Q(pk=int(search.lstrip('#')))
        queryset = queryset.filter(matches)
    has_status = resource != 'gallery-category'
    if has_status and status in ('active', 'hidden'):
        queryset = queryset.filter(is_active=status == 'active')
    else:
        status = ''
    has_category = resource in ('gallery-image', 'canvas-asset')
    if has_category and category:
        queryset = queryset.filter(category_id=category)
    sort = request.GET.get('sort', 'newest')
    sort = sort if sort in ('newest', 'oldest', 'name') else 'newest'
    order = ('caption' if resource == 'gallery-image' else 'label' if resource == 'canvas-asset' else 'name', 'pk') if sort == 'name' else ('pk',) if sort == 'oldest' else ('-pk',)
    page = Paginator(queryset.order_by(*order), account_page_size(request)).get_page(request.GET.get('page'))
    tabs = [{'key': key, 'label': RESOURCES[key][2], 'count': RESOURCES[key][0].objects.count()} for key in resources]
    context = {'workspace': workspace, 'title': title, 'subtitle': subtitle, 'list_url': reverse(route),
        'resource': resource, 'singular': singular, 'plural': plural, 'tabs': tabs, 'page': page,
        'rows': [item_row(resource, item) for item in page], 'per_page': page.paginator.per_page,
        'q': search, 'status_filter': status, 'category_filter': category, 'sort_filter': sort,
        'has_status': has_status, 'has_category': has_category, 'has_filters': bool(search or status or (has_category and category)),
        'categories': categories, 'selected_kind': kind, 'design_kinds': KINDS,
        'create_url': api_url(resource, 'create'), 'bulk_url': api_url(resource, 'bulk-delete')}
    # Preserve public integrations that inspect this page's selected canvas scope.
    if workspace == 'canvas':
        context['selected_asset_category'] = category or 'all'
        context['canvas_assets'] = page if resource == 'canvas-asset' else CanvasAsset.objects.none()
        context['categories_page'] = page if resource == 'canvas-category' else categories
    return context


@login_required
@require_GET
def catalog_workspace(request, workspace):
    if request.user.role != 'admin':
        return HttpResponseForbidden('Not allowed')
    context = workspace_context(request, workspace)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return private_json({'html': render_to_string('admin/catalog/_workspace.html', context, request), 'page': context['page'].number})
    response = render(request, 'admin/catalog/workspace.html', context)
    response['Cache-Control'] = 'private, no-store'
    return response


def delete_items(request, resource, ids):
    """Validate the complete selection before deleting anything; failures roll back all rows."""
    from .views.common import log_action
    model = RESOURCES[resource][0]
    try:
        with transaction.atomic():
            items = list(model.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
            if len(items) != len(ids):
                return private_json({'message': 'Some selected items no longer exist. Refresh the list and try again.'}, 409)
            if any(getattr(item, 'builtin_key', None) for item in items):
                return private_json({'message': 'Built-in canvas items cannot be deleted.'}, 400)
            for item in items:
                if resource == 'gallery-category' and item.images.exists():
                    return private_json({'message': f'“{item.name}” still has photos. Move or delete its photos first.'}, 400)
                if resource == 'canvas-category':
                    if item.design_requirements.exists() or item.offer_inclusions.exists():
                        return private_json({'message': f'“{item.name}” is used by an offer. Remove its offer requirements first.'}, 400)
                    if item.assets.exists():
                        return private_json({'message': f'“{item.name}” still has assets. Move or delete them first.'}, 400)
            names = [str(item) for item in items]
            model.objects.filter(pk__in=ids).delete()
            log_action(request.user, f'Deleted {len(items)} {resource} record(s): ' + ', '.join(f'#{pk}' for pk in ids))
    except (ProtectedError, IntegrityError):
        return private_json({'message': 'These items are still in use. Nothing was deleted.'}, 409)
    return private_json({'success': True, 'message': f'{len(names)} item(s) deleted.'})


def legacy_catalog_delete(request, resource, pk):
    """Keep bookmarked delete URLs safe: GET can never remove catalog records."""
    if request.user.role != 'admin':
        return HttpResponseForbidden('Not allowed')
    if request.method == 'GET' and resource in ('canvas-category', 'canvas-asset'):
        item = get_object_or_404(RESOURCES[resource][0], pk=pk)
        if item.builtin_key:
            return private_json({'message': 'Built-in canvas items cannot be deleted.'}, 400)
        if resource == 'canvas-category' and (item.design_requirements.exists() or item.offer_inclusions.exists()):
            return private_json({'message': 'Remove this category from its offer requirements before deleting it.'}, 400)
    return catalog_action(request, resource, 'delete', pk)


@login_required
@require_http_methods(['GET', 'POST'])
def catalog_action(request, resource, action, pk):
    if request.user.role != 'admin':
        return HttpResponseForbidden('Not allowed')
    if resource not in RESOURCES or action not in ('create', 'edit', 'detail', 'delete', 'bulk-delete'):
        raise Http404
    model, singular, _ = RESOURCES[resource]
    if action in ('delete', 'bulk-delete'):
        if request.method != 'POST':
            return private_json({'message': 'Use POST to delete items.'}, 405)
        raw = request.POST.getlist('ids') if action == 'bulk-delete' else [str(pk)]
        if not raw or len(raw) > 100 or any(not str(value).isdecimal() or len(str(value)) > 12 for value in raw):
            return private_json({'message': 'Select between 1 and 100 valid items.'}, 400)
        ids = sorted({int(value) for value in raw})
        if len(ids) != len(raw) or 0 in ids:
            return private_json({'message': 'Choose a valid selection without duplicates.'}, 400)
        return delete_items(request, resource, ids)
    item = get_object_or_404(model, pk=pk) if action != 'create' else None
    if action == 'detail':
        if request.method != 'GET':
            return private_json({'message': 'Use GET to view details.'}, 405)
        row = item_row(resource, item)
        details = list(row['values'])
        for field, label in (('description', 'Description'), ('features', 'Inclusions'), ('notes', 'Notes'), ('caption', 'Caption'), ('item_type', 'Item type')):
            if getattr(item, field, ''):
                details.append((label, getattr(item, field)))
        if row['availability']:
            details.append(('Available for', row['availability']))
        previews = [image_url(item)] if image_url(item) else []
        if resource in ('package', 'entrance', 'stand'):
            previews = [p.image.url for p in item.preview_images.all()] or previews
        return private_json({'html': render_to_string('admin/catalog/_detail.html', {'row': row, 'details': details, 'previews': previews, 'is_gallery_image': resource == 'gallery-image'}, request), 'title': singular + ' details'})
    if getattr(item, 'builtin_key', None):
        return private_json({'message': 'Built-in canvas items are protected. Configure their quantities in the offer editor.'}, 400)
    if resource in ('package', 'entrance', 'stand'):
        from .offer_editor import offer_editor
        response = offer_editor(request, resource, pk if item else None)
        response['Cache-Control'] = 'private, no-store'
        return response
    kind = request.GET.get('kind', 'package')
    kind = kind if kind in dict(KINDS) else 'package'
    form_kwargs = {'instance': item}
    if resource in ('canvas-asset', 'canvas-category'):
        form_kwargs['kind'] = kind
    form = FORMS[resource](request.POST if request.method == 'POST' else None,
        request.FILES if request.method == 'POST' else None, **form_kwargs)
    if request.method == 'POST':
        if not form.is_valid():
            return private_json({'errors': dict(form.errors)}, 400)
        try:
            with transaction.atomic():
                # Recheck protection after acquiring the row lock on an edit.
                if item:
                    locked = get_object_or_404(model.objects.select_for_update(), pk=item.pk)
                    if getattr(locked, 'builtin_key', None):
                        return private_json({'message': 'Built-in items cannot be edited.'}, 400)
                if resource == 'gallery-image' and not item:
                    data = form.cleaned_data
                    for upload in data['images']:
                        GalleryImage.objects.create(category=data['category'], caption=data['caption'], image=upload, is_active=data['is_active'])
                else:
                    form.save()
                from .views.common import log_action
                log_action(request.user, f'{"Updated" if item else "Created"} {resource}: {str(form.instance)[:160]}')
        except IntegrityError:
            return private_json({'errors': {'__all__': ['This item conflicts with an existing record. Check its name and category.']}}, 409)
        return private_json({'success': True, 'message': singular + ' saved successfully.'})
    title = ('Edit ' if item else 'Add ') + singular.lower()
    form_context = {
        'form': form, 'resource': resource, 'item': item, 'preview': image_url(item) if item else '',
        'form_url': request.get_full_path(), 'upload_limit': 4 if resource == 'gallery-image' and not item else 1}
    return private_json({'html': render_to_string('admin/catalog/_form.html', form_context, request),
        'footer_html': render_to_string('admin/catalog/_form_actions.html', form_context, request), 'title': title})
