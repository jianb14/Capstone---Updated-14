"""Standalone error rendering: safe even when the database is unavailable."""
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.utils.cache import patch_vary_headers
from django.utils.encoding import escape_uri_path


ERRORS = {
    403: ('Access denied', "You don't have permission to open this page. Sign in with an authorized account or return to the home page."),
    404: ('Page not found', "We couldn't find the page you're looking for. The link may be outdated, or the page may have moved."),
    500: ('Something went wrong', "We couldn't complete your request. Please try again in a few moments. If you were submitting a form, check your account before sending it again."),
}


def wants_json(request):
    accept = request.headers.get('Accept', '')
    return (request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or ('application/json' in accept and 'text/html' not in accept))


def error_response(request, status, *, title=None, message=None):
    default_title, default_message = ERRORS[status]
    title, message = title or default_title, message or default_message
    if wants_json(request):
        response = JsonResponse({'error': title, 'message': message, 'status': status}, status=status)
    else:
        # Passing no request avoids auth, notification and other DB-backed processors.
        html = render_to_string('errors/http_error.html', {
            'status_code': status,
            'error_title': title,
            'error_message': message,
            'retry_url': escape_uri_path('/' + request.path.lstrip('/'))
                         if status == 500 and request.method in ('GET', 'HEAD') else '',
        })
        response = HttpResponse(html, status=status)
    response._balloorina_error_page = True
    patch_vary_headers(response, ('Accept', 'X-Requested-With'))
    return response


def permission_denied(request, exception):
    return error_response(request, 403)


def page_not_found(request, exception):
    return error_response(request, 404)


def server_error(request):
    return error_response(request, 500)


def csrf_failure(request, reason=''):
    return error_response(request, 403, title='Please refresh the page',
                          message="We couldn't verify this request. Your session may have expired. Open the form again and try once more.")


class ErrorPageMiddleware:
    """Give direct HTML permission responses the same page as raised exceptions."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (response.status_code == 403 and not response.streaming
                and not getattr(response, '_balloorina_error_page', False)
                and response.get('Content-Type', '').split(';')[0] == 'text/html'
                and not response.get('Content-Encoding')):
            patch_vary_headers(response, ('Accept', 'X-Requested-With'))
            if not wants_json(request):
                response.content = error_response(request, 403).content
                if response.has_header('Content-Length'):
                    response['Content-Length'] = str(len(response.content))
                # Validators for the original body are no longer valid.
                for header in ('ETag', 'Content-MD5'):
                    if response.has_header(header):
                        del response[header]
        return response
