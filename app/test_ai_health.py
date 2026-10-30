from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .models import AiRequest, User


class AiHealthTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='health-admin', role='admin')
        self.customer = User.objects.create_user(username='health-customer', role='customer')
        self.client.force_login(self.admin)
        self.url = reverse('ai_health')
        self.now = datetime(2026, 10, 28, 12, tzinfo=dt_timezone.utc)
        self.clock = patch('app.views.ai_health.timezone.now', return_value=self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def job(self, age=timedelta(hours=1), **kwargs):
        created = self.now - age
        row = AiRequest.objects.create(user=self.customer, input_text='PRIVATE PROMPT', fingerprint='health',
                                       state=kwargs.pop('state', 'succeeded'), **kwargs)
        AiRequest.objects.filter(pk=row.pk).update(created_at=created)
        return row

    def test_authorization_read_only_and_no_store(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.get(self.url, HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.url).status_code, 405)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_exact_window_zero_days_and_finished_denominator(self):
        self.job(age=timedelta(days=7))
        self.job(age=timedelta(days=7, microseconds=1))
        self.job(age=timedelta(seconds=-1))
        self.job(state='failed', error_code='provider_timeout')
        self.job(state='queued')
        report = self.client.get(self.url).context
        self.assertEqual((report['total'], report['success'], report['failed'], report['active']), (3, 1, 1, 1))
        self.assertEqual(report['success_rate'], 50.0)
        self.assertEqual(len(report['daily']), 8)  # Rolling seven days spans two partial boundary dates.
        self.assertEqual(sum(day['n'] for day in report['daily']), 3)
        self.assertTrue(any(day['n'] == 0 for day in report['daily']))
        self.assertTrue(any('queued' in alert for alert in report['alerts']))

    def test_duration_percentile_and_invalid_durations(self):
        for seconds in range(1, 21):
            self.job(started_at=self.now - timedelta(minutes=1), finished_at=self.now - timedelta(minutes=1, seconds=-seconds))
        self.job(started_at=self.now, finished_at=self.now - timedelta(seconds=1))
        self.job(started_at=self.now, finished_at=self.now + timedelta(seconds=1))
        self.job(state='running', started_at=self.now)
        report = self.client.get(self.url).context
        self.assertEqual(report['duration_count'], 20)
        self.assertEqual(report['average_seconds'], 10.5)
        self.assertEqual(report['p95'], 19.0)

    def test_usage_quality_and_malformed_legacy_metadata(self):
        self.job(metrics={'quality': {'checked': True, 'passed': False, 'repairs': 1}, 'calls': [
            {'input_tokens': 100, 'output_tokens': 30, 'estimated_usd': '0.002'},
            {'input_tokens': 0, 'output_tokens': 0},
            {'input_tokens': 10, 'output_tokens': 3, 'estimated_usd': 'NaN'},
            {'input_tokens': 20, 'output_tokens': 5, 'estimated_usd': '-1'},
            {'input_tokens': True, 'output_tokens': 8},
            {'input_tokens': -10, 'output_tokens': 6},
            {'estimated_usd': '9'}, {}, None]})
        self.job(metrics={'quality': 'old', 'calls': 'invalid'})
        self.job(metrics=[])
        response = self.client.get(self.url)
        report = response.context
        self.assertEqual((report['known_calls'], report['calls_count'], report['priced_calls']), (4, 8, 1))
        self.assertEqual((report['input_tokens'], report['output_tokens']), (130, 38))
        self.assertEqual(report['estimate'], '0.002000')
        self.assertEqual((report['repairs'], report['quality_failed'], report['checked']), (1, 1, 1))
        self.assertContains(response, 'This is not the provider invoice.')
        self.assertNotContains(response, 'PRIVATE PROMPT')

    def test_request_search_pagination_and_ajax_privacy(self):
        for _ in range(10):
            self.job(kind='generate', state='failed', error_code='provider_credits',
                     result={'response': 'PRIVATE REPLY'}, metrics={'private': 'PRIVATE METRIC'})
        self.job(age=timedelta(days=10), kind='advice')
        response = self.client.get(self.url, {'q': 'Image generation', 'state': 'failed', 'per_page': '4', 'page': '2'})
        self.assertEqual(response.context['page'].paginator.count, 10)
        self.assertEqual(len(response.context['recent']), 4)
        self.assertEqual(response.context['page'].number, 2)
        ajax = self.client.get(self.url, {'days': '30', 'page': '999'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(ajax.status_code, 200)
        self.assertEqual(ajax.json()['filters']['page'], '2')
        self.assertEqual(ajax.json()['filters']['days'], '30')
        for value in ('PRIVATE PROMPT', 'PRIVATE REPLY', 'PRIVATE METRIC', 'input_text', 'partial_text'):
            self.assertNotContains(ajax, value)
        by_id = self.client.get(self.url, {'q': str(response.context['recent'][0]['id'])[:8]})
        self.assertEqual(by_id.context['page'].paginator.count, 1)
        empty = self.client.get(self.url, {'q': 'missing-request'})
        self.assertContains(empty, 'No matching requests')
        self.assertNotContains(empty, 'class="ac-table ah-request-table"')

    def test_empty_invalid_filters_and_sample_limit(self):
        empty = self.client.get(self.url, {'days': 'invalid', 'state': 'invalid', 'per_page': '10000', 'page': '-1'})
        self.assertEqual((empty.context['days'], empty.context['per_page'], empty.context['state_filter']), (7, 8, ''))
        for key in ('success_rate', 'average_seconds', 'p95', 'estimate'):
            self.assertIsNone(empty.context[key])
        AiRequest.objects.bulk_create([AiRequest(user=self.customer, input_text='PRIVATE PROMPT', fingerprint='bulk',
            state='succeeded', metrics={'calls': [{'input_tokens': 1, 'output_tokens': 1}]}) for _ in range(501)])
        report = self.client.get(self.url).context
        self.assertEqual(report['total'], 501)
        self.assertEqual(report['sample_count'], 500)
        self.assertEqual(report['known_calls'], 500)
        self.assertEqual(sum(day['n'] for day in report['daily']), 501)

    def test_error_categories_count_failed_requests_only(self):
        self.job(state='failed', error_code='provider_auth')
        self.job(state='failed')
        self.job(error_code='stale_error')
        report = self.client.get(self.url).context
        self.assertEqual(sum(error['n'] for error in report['errors']), report['failed'])
        self.assertEqual({error['error_code'] for error in report['errors']}, {'provider_auth', 'not_recorded'})
        self.assertEqual(len(report['alerts']), 1)
