"""Exercise production error handling without adding public crash/preview routes."""
from copy import deepcopy

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from django.urls import get_resolver, include, path


def denied(request):
    raise PermissionDenied('private permission details')


def missing(request):
    raise Http404('private record details')


def broken(request):
    raise RuntimeError('private database credentials')


def forbidden(request):
    response = HttpResponseForbidden('Admins only')
    response['X-Permission-Check'] = 'preserved'
    response['Content-Length'] = str(len(response.content))
    response['Vary'] = 'Origin'
    response.set_cookie('error-test', 'preserved')
    return response


def json_forbidden(request):
    return JsonResponse({'message': 'Existing API contract'}, status=403)


def success(request):
    return HttpResponse('Success')


def unavailable_context(request):
    raise AssertionError('Error pages must not run request context processors')


# Delegate to the production URLconf, so tests catch missing handler registration.
def handler403(request, exception):
    return get_resolver('Project.urls').resolve_error_handler(403)(request, exception)


def handler404(request, exception):
    return get_resolver('Project.urls').resolve_error_handler(404)(request, exception)


def handler500(request):
    return get_resolver('Project.urls').resolve_error_handler(500)(request)


urlpatterns = [
    path('_errors/denied/', denied),
    path('_errors/missing/', missing),
    path('_errors/broken/', broken),
    path('_errors/forbidden/', forbidden),
    path('_errors/json/', json_forbidden),
    path('_errors/success/', success),
    path('', include('Project.urls')),
]


@override_settings(ROOT_URLCONF=__name__, DEBUG=False, SECURE_SSL_REDIRECT=False,
                   REQUEST_RATE_LIMITING_ENABLED=False)
class ErrorPageTests(SimpleTestCase):
    def setUp(self):
        self.client = Client(raise_request_exception=False)

    def assert_error_page(self, response, status):
        self.assertEqual(response.status_code, status)
        self.assertContains(response, 'Balloorina', status_code=status)
        self.assertContains(response, 'Back to Home', status_code=status)
        self.assertContains(response, f'HTTP {status}', status_code=status)
        self.assertContains(response, '<html lang="en">', status_code=status)
        self.assertContains(response, 'href="/"', status_code=status)
        self.assertNotContains(response, 'private ', status_code=status)

    def test_unknown_url_and_missing_record_have_branded_404(self):
        for url in ('/does-not-exist/?secret=hidden', '/_errors/missing/'):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assert_error_page(response, 404)
                self.assertNotContains(response, 'secret=hidden', status_code=404)

    def test_permission_exception_has_branded_403(self):
        response = self.client.get('/_errors/denied/')
        self.assert_error_page(response, 403)
        self.assertContains(response, 'href="/login/"', status_code=403)

    def test_direct_html_forbidden_is_branded_and_keeps_headers_and_cookies(self):
        response = self.client.get('/_errors/forbidden/', HTTP_ACCEPT='text/html')
        self.assert_error_page(response, 403)
        self.assertEqual(response['X-Permission-Check'], 'preserved')
        self.assertEqual(response.cookies['error-test'].value, 'preserved')
        self.assertEqual(int(response['Content-Length']), len(response.content))

    def test_unhandled_exception_has_branded_500(self):
        response = self.client.get('/_errors/broken/')
        self.assert_error_page(response, 500)
        self.assertContains(response, 'Try Again', status_code=500)

    def test_post_failure_never_offers_to_repeat_submission(self):
        response = self.client.post('/_errors/broken/', {'booking': 'example'})
        self.assert_error_page(response, 500)
        self.assertNotContains(response, 'Try Again', status_code=500)
        self.assertContains(response, 'check your account', status_code=500)

    def test_retry_link_stays_local_and_encodes_unsafe_path_characters(self):
        request = RequestFactory().get('/unavailable/')
        request.path = '//outside.example/unsafe\\retry'
        response = get_resolver('Project.urls').resolve_error_handler(500)(request)
        self.assertContains(response, 'href="/outside.example/unsafe%5Cretry"', status_code=500)

    def test_csrf_rejection_is_branded_and_hides_diagnostics(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post('/_errors/success/', HTTP_ACCEPT='text/html')
        self.assert_error_page(response, 403)
        self.assertNotContains(response, 'CSRF cookie not set', status_code=403)

    def test_existing_json_and_ajax_bodies_are_preserved(self):
        response = self.client.get('/_errors/json/', HTTP_ACCEPT='text/html')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {'message': 'Existing API contract'})
        for headers in ({'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                        {'HTTP_ACCEPT': 'application/json'}):
            with self.subTest(headers=headers):
                response = self.client.get('/_errors/forbidden/', **headers)
                self.assertEqual(response.content, b'Admins only')

    def test_html_json_and_ajax_variants_have_correct_cache_vary_headers(self):
        for url in ('/_errors/denied/', '/_errors/missing/', '/_errors/broken/', '/_errors/forbidden/'):
            for headers in ({'HTTP_ACCEPT': 'text/html'}, {'HTTP_ACCEPT': 'application/json'},
                            {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}):
                with self.subTest(url=url, headers=headers):
                    response = self.client.get(url, **headers)
                    vary = {value.strip().lower() for value in response.get('Vary', '').split(',')}
                    self.assertTrue({'accept', 'x-requested-with'} <= vary)
                    if url == '/_errors/forbidden/':
                        self.assertIn('origin', vary)

    def test_exception_responses_are_json_when_explicitly_requested(self):
        for url, status in (('/_errors/denied/', 403), ('/_errors/missing/', 404),
                            ('/_errors/broken/', 500)):
            for headers in ({'HTTP_ACCEPT': 'application/json'},
                            {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}):
                with self.subTest(url=url, headers=headers):
                    response = self.client.get(url, **headers)
                    self.assertEqual(response.status_code, status)
                    self.assertEqual(response.json()['status'], status)
                    self.assertNotIn('private', response.content.decode())

    def test_error_renderer_does_not_use_database_or_context_processors(self):
        templates = deepcopy(settings.TEMPLATES)
        templates[0]['OPTIONS']['context_processors'] = [__name__ + '.unavailable_context']
        with override_settings(TEMPLATES=templates):
            for status in (403, 404, 500):
                with self.subTest(status=status):
                    handler = get_resolver('Project.urls').resolve_error_handler(status)
                    request = RequestFactory().get('/unavailable/')
                    response = handler(request) if status == 500 else handler(request, Exception('private details'))
                    self.assert_error_page(response, status)

    def test_success_response_is_unchanged(self):
        response = self.client.get('/_errors/success/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'Success')

    def test_head_preserves_error_status_without_body(self):
        response = self.client.head('/_errors/missing/')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b'')
