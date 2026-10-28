"""Async page sections and ordered content collections for the admin workspace."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.text import Truncator
from django.views.decorators.http import require_http_methods

from .content_forms import content_form_class
from .home_statistics import get_customers_served, get_home_statistics
from .models import (AboutContent, AboutJourneyItem, AboutValueItem, GuidelineItem,
    GuidelinePageContent, HomeContent, HomeFaqItem, HomeFeatureItem, HomeHowItWorksStep,
    Service, ServiceContent)

# Only these fields are editable. Business statistics never enter a ModelForm.
PAGES = {
    'home': (HomeContent, 'Home Page', 'Shape your first impression, event highlights and booking journey.', 'admin_home_content', 'home'),
    'about': (AboutContent, 'About Page', 'Tell your story through your mission, values and milestones.', 'admin_about_content', 'about'),
    'services': (ServiceContent, 'Service Page', 'Present your services and help customers find the right styling.', 'admin_service_content', 'services'),
    'policies': (GuidelinePageContent, 'Guidelines & Policies', 'Keep your booking guidance, terms and privacy information clear.', 'admin_guidelines_content', 'guidelines'),
}
SECTIONS = {
    'home': {
        'hero': ('Welcome section', 'The main heading and introduction customers see first.', ('hero_label', 'hero_title', 'hero_subheadline', 'occasion_chips')),
        'support': ('Support hours', 'Set your daily support availability. Website statistics are automatic.', ('support_hours',)),
        'features-heading': ('Why choose us', 'Introduce the reasons customers should choose your team.', ('why_choose_title', 'why_choose_subtitle')),
        'steps-heading': ('How it works', 'Introduce the steps from choosing a setup to event day.', ('how_it_works_label', 'how_it_works_title', 'how_it_works_title_accent')),
        'faq-heading': ('Frequently asked questions', 'Set the heading and introduction for your FAQ collection.', ('faq_title', 'faq_subtitle')),
        'cta': ('Booking invitation', 'The final invitation to start planning a celebration.', ('cta_title', 'cta_subtitle')),
    },
    'about': {
        'hero': ('Welcome section', 'Introduce your business and what you stand for.', ('hero_label', 'hero_title', 'hero_subtitle')),
        'story': ('Our story', 'Share your story, highlights and a photo of your work.', ('story_label', 'story_title', 'story_paragraph_1', 'story_paragraph_2', 'story_points', 'story_image')),
        'mission': ('Our mission', 'Describe your purpose and approach to event styling.', ('mission_label', 'mission_title', 'mission_paragraph_1', 'mission_paragraph_2', 'mission_image')),
        'values-heading': ('Core values heading', 'Introduce the values behind your customer experience.', ('values_title', 'values_subtitle')),
        'journey-heading': ('Our journey heading', 'Introduce your business milestones and timeline.', ('journey_title', 'journey_subtitle')),
    },
    'services': {'hero': ('Welcome section', 'Introduce your event styling services.', ('hero_label', 'hero_title', 'hero_subtitle'))},
    'policies': {'page': ('Page introduction', 'Update the page heading, introduction and optional document link.', ('title', 'intro', 'attachment_label', 'attachment_url'))},
}
COLLECTIONS = {
    'home': {
        'features': (HomeFeatureItem, 'Feature', 'Features', ('title', 'description', 'icon_class', 'display_order', 'is_active'), 'home_content'),
        'steps': (HomeHowItWorksStep, 'Step', 'How it works', ('title', 'description', 'icon_class', 'display_order', 'is_active'), 'home_content'),
        'faqs': (HomeFaqItem, 'Question', 'FAQs', ('question', 'answer', 'display_order', 'is_active'), 'home_content'),
    },
    'about': {
        'values': (AboutValueItem, 'Value', 'Core values', ('title', 'description', 'icon_class', 'display_order', 'is_active'), 'about_content'),
        'journey': (AboutJourneyItem, 'Milestone', 'Journey milestones', ('caption', 'title', 'description', 'display_order', 'is_active'), 'about_content'),
    },
    'services': {'services': (Service, 'Service', 'Services', ('title', 'description', 'features', 'best_for', 'image', 'display_order', 'is_active'), None)},
    'policies': {key: (GuidelineItem, 'Section', label, ('heading', 'body', 'display_order', 'is_active'), 'page_content') for key, label in GuidelinePageContent.PAGE_CHOICES},
}


def private_json(data, status=200):
    response = JsonResponse(data, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


def current_tab(request, workspace):
    value = request.GET.get('tab', '')
    return value if value in COLLECTIONS[workspace] else next(iter(COLLECTIONS[workspace]))


def get_content(workspace, tab):
    model = PAGES[workspace][0]
    if workspace == 'policies':
        return model.objects.get_or_create(page_key=tab)[0]
    content = model.objects.first()
    if content is None:
        content = model.objects.create()
        # Seed a new page once. Deleting the last item must not recreate a collection.
        from .views.admin import _seed_home_defaults, _seed_about_defaults, _seed_service_defaults
        {'home': _seed_home_defaults, 'about': _seed_about_defaults, 'services': _seed_service_defaults}[workspace](content)
    return content


def action_url(workspace, resource, action, pk=0):
    return reverse('admin_content_action', args=(workspace, resource, action, pk))


def collection_query(workspace, tab, content):
    model, _, _, _, parent = COLLECTIONS[workspace][tab]
    # Public Home/About pages display all items, including legacy rows linked to
    # an older content record. Policies, however, must remain strictly separated.
    return model.objects.filter(**{parent: content}) if workspace == 'policies' else model.objects.all()


def workspace_context(request, workspace):
    if workspace not in PAGES:
        raise Http404
    tab = current_tab(request, workspace)
    content = get_content(workspace, tab)
    model, singular, plural, fields, _ = COLLECTIONS[workspace][tab]
    queryset = collection_query(workspace, tab, content)
    total, visible = queryset.count(), queryset.filter(is_active=True).count()
    q = request.GET.get('q', '').strip()[:150]
    status = request.GET.get('status', '')
    status = status if status in ('active', 'hidden') else ''
    sort = request.GET.get('sort', 'order')
    sort = sort if sort in ('order', 'newest', 'oldest', 'name') else 'order'
    name_field = 'question' if model == HomeFaqItem else 'heading' if model == GuidelineItem else 'title'
    if q:
        search = Q(**{name_field + '__icontains': q})
        for field in ('description', 'answer', 'body', 'features', 'best_for', 'caption'):
            if field in fields:
                search |= Q(**{field + '__icontains': q})
        if q.lstrip('#').isdecimal() and len(q.lstrip('#')) < 13:
            search |= Q(pk=int(q.lstrip('#')))
        queryset = queryset.filter(search)
    if status:
        queryset = queryset.filter(is_active=status == 'active')
    queryset = queryset.order_by(*{'order': ('display_order', 'pk'), 'newest': ('-pk',), 'oldest': ('pk',), 'name': (name_field, 'pk')}[sort])
    size = 4 if request.GET.get('per_page') == '4' else 8
    page = Paginator(queryset, size).get_page(request.GET.get('page'))
    rows = []
    for item in page:
        name = getattr(item, name_field) or f'Section #{item.pk}'
        rows.append({'pk': item.pk, 'name': name, 'active': item.is_active,
            'description': Truncator(getattr(item, 'description', '') or getattr(item, 'answer', '') or getattr(item, 'body', '')).chars(160),
            'order': item.display_order, 'preview': getattr(item, 'image', None),
            'edit_url': action_url(workspace, tab, 'edit', item.pk),
            'detail_url': action_url(workspace, tab, 'detail', item.pk),
            'delete_url': action_url(workspace, tab, 'delete', item.pk)})
    sections = []
    for key, (label, explanation, section_fields) in SECTIONS[workspace].items():
        title = next((getattr(content, f) for f in section_fields if 'title' in f and getattr(content, f)), '')
        sections.append({'label': label, 'description': explanation, 'preview': title,
            'url': action_url(workspace, key, 'section', content.pk)})
    tabs = []
    for key, (other_model, _, label, _, parent) in COLLECTIONS[workspace].items():
        qs = other_model.objects.all()
        if workspace == 'policies':
            qs = qs.filter(**{parent + '__page_key': key})
        tabs.append({'key': key, 'label': label, 'count': qs.count()})
    return {'workspace': workspace, 'content': content, 'tab': tab, 'tabs': tabs,
        'title': PAGES[workspace][1], 'subtitle': PAGES[workspace][2],
        'list_url': reverse(PAGES[workspace][3]),
        'public_url': reverse({'guidelines': 'guidelines', 'terms': 'terms_conditions', 'privacy': 'data_privacy'}[tab]) if workspace == 'policies' else reverse(PAGES[workspace][4]),
        'page': page, 'per_page': size, 'rows': rows, 'sections': sections,
        'q': q, 'status_filter': status, 'sort_filter': sort, 'has_filters': bool(q or status),
        'singular': singular, 'plural': plural, 'total': total, 'visible': visible, 'hidden_count': total - visible,
        'create_url': action_url(workspace, tab, 'create'), 'bulk_url': action_url(workspace, tab, 'bulk-delete'),
        'home_stats': get_home_statistics() if workspace == 'home' else None,
        'customers_served': get_customers_served() if workspace == 'about' else None}


@login_required
@require_http_methods(['GET'])
def content_workspace(request, workspace):
    if request.user.role != 'admin':
        return HttpResponseForbidden('Not allowed')
    context = workspace_context(request, workspace)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return private_json({'html': render_to_string('admin/content/workspace/_workspace.html', context, request), 'page': context['page'].number})
    response = render(request, 'admin/content/workspace/page.html', context)
    response['Cache-Control'] = 'private, no-store'
    return response


def notify_policy(request, tab, changed):
    if request.POST.get('notify_clients') != 'on' or not changed:
        return ''
    from .views.admin import _notify_clients_policy_update
    sent, failed = _notify_clients_policy_update(request, [tab])
    if failed:
        return f' However, {failed} email notice(s) could not be sent.'
    return f' Update notice emailed to {sent} customer(s).' if sent else ' No active customers with email addresses were found.'


@login_required
@require_http_methods(['GET', 'POST'])
def content_action(request, workspace, resource, action, pk):
    if request.user.role != 'admin':
        return HttpResponseForbidden('Not allowed')
    if workspace not in PAGES:
        raise Http404
    if action == 'section':
        if resource not in SECTIONS[workspace]:
            raise Http404
        item = get_object_or_404(PAGES[workspace][0], pk=pk)
        tab = item.page_key if workspace == 'policies' else next(iter(COLLECTIONS[workspace]))
        title, _, fields = SECTIONS[workspace][resource]
        model = type(item)
    else:
        if resource not in COLLECTIONS[workspace] or action not in ('create', 'edit', 'detail', 'delete', 'bulk-delete'):
            raise Http404
        tab = resource
        model, title, _, fields, parent = COLLECTIONS[workspace][tab]
        content = get_content(workspace, tab)
        queryset = collection_query(workspace, tab, content)
        item = get_object_or_404(queryset, pk=pk) if action not in ('create', 'bulk-delete') else None
        if action in ('delete', 'bulk-delete'):
            if request.method != 'POST':
                return private_json({'message': 'Use POST to delete content.'}, 405)
            raw = request.POST.getlist('ids') if action == 'bulk-delete' else [str(pk)]
            if not raw or len(raw) > 100 or any(not value.isdecimal() or len(value) > 12 for value in raw):
                return private_json({'message': 'Select between 1 and 100 valid items.'}, 400)
            ids = {int(value) for value in raw}
            if len(ids) != len(raw) or 0 in ids:
                return private_json({'message': 'Choose a valid selection without duplicates.'}, 400)
            with transaction.atomic():
                selected = list(queryset.select_for_update().filter(pk__in=ids))
                if len(selected) != len(ids):
                    return private_json({'message': 'Some selected items no longer exist. Refresh the list and try again.'}, 409)
                queryset.filter(pk__in=ids).delete()
                from .views.common import log_action
                log_action(request.user, f'Deleted {workspace} {resource}: ' + ', '.join(f'#{value}' for value in sorted(ids)))
            notice = notify_policy(request, tab, True) if workspace == 'policies' else ''
            return private_json({'success': True, 'message': f'{len(ids)} item(s) deleted.' + notice})
        if action == 'detail':
            if request.method != 'GET':
                return private_json({'message': 'Use GET to view details.'}, 405)
            details = [(model._meta.get_field(field).verbose_name.replace('_', ' ').capitalize(), getattr(item, field)) for field in fields if field not in ('image', 'is_active', 'icon_class')]
            return private_json({'title': title + ' details', 'html': render_to_string('admin/content/workspace/_detail.html', {'item': item, 'details': details, 'name': str(item)}, request)})
    form_type = content_form_class(model, fields)
    form = form_type(request.POST if request.method == 'POST' else None,
        request.FILES if request.method == 'POST' else None, instance=item, policy=workspace == 'policies')
    if request.method == 'POST':
        before = {name: str(getattr(item, name)) for name in fields} if item else None
        if not form.is_valid():
            return private_json({'errors': dict(form.errors), 'message': 'Check the highlighted fields.'}, 400)
        try:
            with transaction.atomic():
                saved = form.save(commit=False)
                changed = before is None or any(before[name] != str(getattr(saved, name)) for name in fields)
                if action == 'create' and parent:
                    setattr(saved, parent, content)
                saved.save(update_fields=[*fields, 'updated_at'] if item else None)
                from .views.common import log_action
                log_action(request.user, f'Updated {workspace} {resource} #{saved.pk}.' if item else f'Created {workspace} {resource} #{saved.pk}.')
        except IntegrityError:
            return private_json({'message': 'This content could not be saved. Refresh the list and try again.'}, 409)
        notice = notify_policy(request, tab, changed) if workspace == 'policies' else ''
        return private_json({'success': True, 'message': title + ' saved successfully.' + notice})
    preview = next((getattr(item, field).url for field in fields if item and field in ('image', 'story_image', 'mission_image') and getattr(item, field)), '')
    context = {'form': form, 'form_url': request.path, 'preview': preview, 'upload_limit': 1, 'item': item, 'workspace': workspace}
    return private_json({'title': ('Edit ' if item else 'Add ') + title.lower(),
        'html': render_to_string('admin/content/workspace/_form.html', context, request),
        'footer_html': render_to_string('admin/catalog/_form_actions.html', context, request)})
