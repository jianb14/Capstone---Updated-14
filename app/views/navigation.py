"""Authenticated, read-only topbar search for the admin workspace."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from ..admin_navigation import search_records


@never_cache
@login_required
@require_GET
def admin_global_search(request):
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Admin access is required.'}, status=403)
    try:
        data = search_records(request.GET.get('q', ''))
    except ValueError as error:
        return JsonResponse({'error': str(error)}, status=400)
    response = JsonResponse(data)
    response['Cache-Control'] = 'private, no-store'
    return response
