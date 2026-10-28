"""Administrator account directory; editing, deletion and reset actions are retired."""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from ..models import User
from ..user_management import UserStatusError, change_user_access, user_details_context, user_list_context


def _is_admin(request):
    return request.user.role == 'admin' and request.user.is_active and not request.user.deleted_at


@never_cache
@login_required
@require_GET
def admin_user_list(request):
    if not _is_admin(request):
        return HttpResponseForbidden('Admins only')
    context = user_list_context(request)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'html': render_to_string('admin/user/_queue.html', context, request=request),
                             'counts': context['user_summary'], 'page': context['users'].number})
    target = request.GET.get('user_id', '')
    if target.isdecimal() and len(target) < 19:
        context['initial_user'] = get_object_or_404(User, pk=int(target))
    return render(request, 'admin/user/admin_user_list.html', context)


@never_cache
@login_required
@require_GET
def admin_user_detail(request, id):
    if not _is_admin(request):
        return HttpResponseForbidden('Admins only')
    user = get_object_or_404(User, pk=id)
    detail = user_details_context(user)
    html = render_to_string('admin/user/admin_user_detail.html', detail, request=request)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'html': html, 'id': user.pk, 'name': user.get_full_name() or user.username})
    context = user_list_context(request)
    context.update(initial_user=user, initial_detail_html=html)
    return render(request, 'admin/user/admin_user_list.html', context)


@never_cache
@login_required
@require_POST
def admin_user_toggle_active(request, id):
    if not _is_admin(request):
        return JsonResponse({'message': 'Admins only'}, status=403)
    # Check existence first, including for retired accounts and old bookmarked forms.
    get_object_or_404(User, pk=id, deleted_at__isnull=True)
    action, expected = request.POST.get('action'), request.POST.get('expected_active')
    if action not in ('activate', 'deactivate') or expected not in ('1', '0'):
        return JsonResponse({'message': 'Choose an account action and confirm its current status.'}, status=400)
    try:
        user, changed = change_user_access(
            actor_id=request.user.pk, target_id=id, active=action == 'activate',
            expected_active=expected == '1', login_url=request.build_absolute_uri(reverse('login')),
        )
    except UserStatusError as error:
        return JsonResponse({'message': error.message}, status=error.status)
    verb = 'activated' if user.is_active else 'deactivated'
    return JsonResponse({'success': True, 'changed': changed, 'id': user.pk, 'active': user.is_active,
                         'message': f'Account {verb}. An email notification was sent.' if changed
                                    else f'This account is already {"active" if user.is_active else "inactive"}. No additional email was sent.'})


@never_cache
@login_required
def _retired_user_action(request, id):
    if not _is_admin(request):
        return HttpResponseForbidden('Admins only')
    get_object_or_404(User, pk=id, deleted_at__isnull=True)
    return HttpResponseForbidden('Editing, deleting and sending password resets are not available in user management.')


# Old URLs fail closed so bookmarks or manually crafted requests cannot mutate accounts.
admin_user_edit = _retired_user_action
admin_user_delete = _retired_user_action
admin_user_reset_password = _retired_user_action
