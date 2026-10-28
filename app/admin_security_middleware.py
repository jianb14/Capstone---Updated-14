"""A password-authenticated, unverified admin can only finish their own email setup."""
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse


class AdminEmailSetupMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not request.session.get('admin_email_setup_required') or not request.user.is_authenticated:
            return None
        if request.user.role != 'admin' or request.user.email_verified:
            request.session.pop('admin_email_setup_required', None)
            return None
        route = request.resolver_match.url_name
        if route in ('admin_email_setup', 'admin_profile', 'logout') and request.method == 'GET':
            return None
        if route == 'logout' and request.method == 'POST':
            return None
        if route == 'admin_security_action' and view_kwargs.get('purpose') == 'email':
            return None
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'message': 'Verify your own admin email before continuing.', 'verification_required': True}, status=403)
        return redirect(reverse('admin_profile') + '?verify_email=1#admin-email-verification')

    def __call__(self, request):
        return self.get_response(request)
