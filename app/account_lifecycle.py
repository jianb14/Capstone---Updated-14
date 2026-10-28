"""Serialize customer writes with irreversible account removal."""
from django.contrib.auth import logout
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect

from .models import User


class CustomerAccountLifecycleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if request.method not in ('POST','PUT','PATCH','DELETE') or not user.is_authenticated or user.role != 'customer':
            return self.get_response(request)
        # A request authenticated before removal must not recreate customer data
        # after the deletion commits. All customer writes take this lock first.
        with transaction.atomic():
            current = User.objects.select_for_update().filter(pk=user.pk).first()
            if not current or not current.is_active or current.deleted_at:
                logout(request)
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success':False,'message':'Please sign in again.'},status=401)
                return redirect('login')
            response = self.get_response(request)
            # Django converts view exceptions into error responses before they
            # reach middleware. Never commit a partially failed customer write.
            # Explicit 503 responses (for example a failed OTP email) still
            # commit their rate limits and invalidate the failed challenge.
            if response.status_code == 500:
                transaction.set_rollback(True)
            return response
