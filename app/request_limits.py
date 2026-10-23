"""Route policies exclude read-only pages, polling and provider callbacks."""
from django.conf import settings
from django.db import OperationalError
from django.utils.deprecation import MiddlewareMixin

from .request_protection import (RateLimited, bucket_key, client_ip, configured_rule,
                                 consume_rules, limit_response)
from .models import RequestRateBucket


POST_POLICIES = {
    'register': ('registration',), 'password_reset_confirm': ('password_reset_submit',),
    'change_password': ('password_change',),
    'create_booking': ('booking_create', 'booking_daily'),
    'request_booking_change': ('booking_change',), 'edit_booking': ('booking_change',),
    'submit_payment': ('payment_submit',), 'create_paymongo_checkout': ('payment_submit',),
    'booking_change_payment': ('payment_submit',),
    'chat_api': ('chat_send',), 'admin_chat_thread': ('chat_send',),
    'chat_request_admin': ('support_request',), 'report_concern': ('concern',),
    'submit_review': ('review_submit',), 'edit_review': ('review_edit',),
    'like_review': ('reaction',), 'chat_reaction': ('reaction',), 'chat_toggle_reaction': ('reaction',),
    'save_user_design': ('design_save',), 'chat_save_design': ('design_save',),
    'chat_image_feedback': ('reaction',),
}
GET_POLICIES = {
    'admin_analytics_export_excel': ('report_export',), 'admin_analytics_export_pdf': ('report_export',),
    'download_payment_receipt_pdf': ('receipt_download',),
}
PUBLIC_POSTS = {'register', 'password_reset_confirm'}


class RequestLimitsMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # Reject oversized multipart requests before CSRF or the view parses uploads.
        if not settings.REQUEST_RATE_LIMITING_ENABLED:
            return None
        if request.method == 'POST' and request.content_type == 'multipart/form-data':
            try:
                length = int(request.META.get('CONTENT_LENGTH') or 0)
            except ValueError:
                length = 0
            if length > settings.UPLOAD_MAX_REQUEST_BYTES:
                message = 'The upload is too large. Please reduce the files and submit again.'
                return limit_response(request, RateLimited(60, 'upload_size', message), status=413)
        return None

    def process_view(self, request, view, args, kwargs):
        if not settings.REQUEST_RATE_LIMITING_ENABLED:
            return None
        match = request.resolver_match
        name = match.url_name
        ip = client_ip(request)
        authenticated = request.user.is_authenticated
        subject = f'user:{request.user.pk}' if authenticated else f'ip:{ip}'
        rules = []
        if request.method == 'POST' and (name == 'login' or match.view_name == 'admin:login'):
            identity = (request.POST.get('email') or request.POST.get('username') or '').strip().casefold()
            rules.append(configured_rule('login_ip', ip))
            if identity:
                rules.append(configured_rule('login_account', identity))
                request._login_rate_identity = identity
        elif request.method == 'POST':
            if not authenticated and name not in PUBLIC_POSTS:
                return None
            policy_subject = f'ip:{ip}' if name in PUBLIC_POSTS else subject
            rules.extend(configured_rule(scope, policy_subject) for scope in POST_POLICIES.get(name, ()))
            if request.content_type == 'multipart/form-data':
                if request.FILES:
                    size = sum(upload.size for _, uploads in request.FILES.lists() for upload in uploads)
                    rules.extend([configured_rule('upload_requests', subject), configured_rule('upload_bytes', subject, size)])
        elif request.method == 'GET' and authenticated:
            rules.extend(configured_rule(scope, subject) for scope in GET_POLICIES.get(name, ()))
        if not rules:
            return None
        try:
            consume_rules(rules)
        except RateLimited as error:
            return limit_response(request, error)
        except OperationalError:
            # Do not silently allow unlimited requests when the shared store is unavailable.
            error = RateLimited(5, message='Request protection is temporarily unavailable. Please try again in 5 seconds.')
            return limit_response(request, error, status=503)
        return None

    def process_response(self, request, response):
        identity = getattr(request, '_login_rate_identity', None)
        if identity and response.status_code == 302 and request.user.is_authenticated:
            RequestRateBucket.objects.filter(pk=bucket_key('login_account', identity)).delete()
        return response
