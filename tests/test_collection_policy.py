"""Request-policy and direct API contracts; no network requests are made."""
import argparse
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from jobdisco.collection_policy import retry_after_seconds
from jobdisco.collector import Collector, Source, main
from jobdisco import probe_sources
from jobdisco.validate_sources import validate


class CollectionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.args = argparse.Namespace(
            max_pages=4, max_jobs=100, delay=0, timeout=1, retries=3,
            source_state=Path(self.temp.name) / 'source_access.sqlite',
        )
        self.source = Source('test', 'company_sources', 'micron', 'Micron', 'eightfold',
                             'https://careers.micron.com/api/pcsx/search?domain=micron.com', {})

    def response(self, status=200, data=None, headers=None, text=''):
        response = Mock(status_code=status, headers=headers or {'content-type': 'application/json'}, text=text)
        response.json.return_value = data or {}
        return response

    def collector(self, source=None):
        collector = Collector(source or self.source, self.args)
        collector.session.request = Mock()
        self.addCleanup(collector.session.close)
        return collector

    def test_429_stops_immediately_and_survives_restart(self):
        c = self.collector(replace(self.source, company_key='microsoft'))
        c.session.request.return_value = self.response(429, headers={'Retry-After': '3600'})
        with patch('jobdisco.collection_policy.time.time', return_value=1000), patch('jobdisco.collector.time.sleep') as sleep:
            status, reason = c.run()
            self.assertEqual(status, 'paused')
            self.assertIn('429', reason)
            self.assertEqual(c.requests, 1)
            sleep.assert_not_called()
            restarted = self.collector(c.source)
            self.assertEqual(restarted.run()[0], 'paused')
            restarted.session.request.assert_not_called()
        with closing(sqlite3.connect(self.args.source_state)) as db:
            self.assertEqual(db.execute('SELECT retry_at FROM source_pauses').fetchone()[0], 4600)

    def test_validator_respects_the_same_persisted_pause(self):
        c = self.collector()
        c.session.request.return_value = self.response(429)
        self.assertEqual(c.run()[0], 'paused')
        restarted = self.collector()
        session = Mock()
        with patch('jobdisco.validate_sources.SourcePolicy', return_value=restarted.policy):
            result = validate(self.source, session)
        self.assertEqual(result['verdict'], 'paused')
        session.get.assert_not_called()
        session.post.assert_not_called()

    def test_503_honors_retry_after_before_success(self):
        c = self.collector()
        c.session.request.side_effect = [self.response(503, headers={'Retry-After': '45'}), self.response()]
        with patch('jobdisco.collector.time.sleep') as sleep:
            c.fetch(c.source.access_url)
        self.assertEqual(c.requests, 2)
        sleep.assert_called_once_with(45)

    def test_long_http_date_defers_instead_of_retrying_early(self):
        c = self.collector()
        date = format_datetime(datetime.fromtimestamp(1120, timezone.utc), usegmt=True)
        c.session.request.return_value = self.response(503, headers={'Retry-After': date})
        with patch('jobdisco.collection_policy.time.time', return_value=1000), patch('jobdisco.collector.time.sleep') as sleep:
            self.assertEqual(c.run()[0], 'paused')
            self.assertEqual(c.requests, 1)
            sleep.assert_not_called()

    def test_503_retries_are_bounded_with_exponential_waits(self):
        c = self.collector()
        c.session.request.return_value = self.response(503)
        with patch('jobdisco.collector.time.sleep') as sleep:
            self.assertEqual(c.run()[0], 'paused')
        self.assertEqual(c.requests, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 10, 20])

    def test_small_delay_cannot_override_source_minimum(self):
        for company, provider, expected in [('microsoft', 'eightfold', 3), ('micron', 'eightfold', 2.5), ('amd', 'amd_careers', 1)]:
            with self.subTest(company=company):
                c = self.collector(replace(self.source, company_key=company, provider_key=provider))
                c.session.request.return_value = self.response()
                with patch('jobdisco.collector.time.sleep') as sleep:
                    c.fetch(c.source.access_url)
                    c.fetch(c.source.access_url)
                sleep.assert_called_once_with(expected)

    def test_sitemap_stops_after_first_challenge(self):
        c = self.collector(replace(self.source, company_key='renesas', provider_key='renesas_careers'))
        sitemap = self.response()
        sitemap.content = b'<urlset><url><loc>https://jobs.example/1</loc></url><url><loc>https://jobs.example/2</loc></url></urlset>'
        blocked = self.response(headers={'content-type': 'text/html'}, text='<h1>Human Verification</h1>')
        c.session.request.side_effect = [sitemap, blocked]
        with patch('jobdisco.collector.time.sleep'):
            self.assertEqual(c.run()[0], 'paused')
        self.assertEqual(c.requests, 2)

    def test_retry_after_parses_dates_and_ignores_invalid_values(self):
        self.assertEqual(retry_after_seconds('30.2'), 31)
        self.assertEqual(retry_after_seconds('Thu, 01 Jan 1970 00:20:00 GMT', now=1000), 200)
        self.assertEqual(retry_after_seconds('-1'), 0)
        for value in [None, 'invalid', 'nan', 'inf']:
            self.assertIsNone(retry_after_seconds(value))

    def test_pcsx_pagination_and_field_mapping(self):
        c = self.collector()
        c.session.request.side_effect = [
            self.response(data={'data': {'count': 2, 'positions': [
                {'id': '1', 'name': 'Hardware Engineer', 'locations': ['Boise', 'Remote'],
                 'positionUrl': '/careers/job/1', 'postedTs': 1000}]}}),
            self.response(data={'data': {'count': 2, 'positions': [
                {'id': '2', 'name': 'Verification Engineer', 'positionUrl': '/careers/job/2'}]}}),
        ]
        with patch('jobdisco.collector.time.sleep'):
            self.assertEqual(c.run(), ('complete', ''))
        self.assertIn('start=1', c.session.request.call_args_list[1].args[1])
        self.assertIn('num=10', c.session.request.call_args_list[1].args[1])
        self.assertEqual(c.jobs[0]['location'], 'Boise; Remote')
        self.assertEqual(c.jobs[0]['posted_at'], '1970-01-01T00:16:40+00:00')
        self.assertEqual(c.jobs[0]['url'], 'https://careers.micron.com/careers/job/1')

    def test_amd_nested_items_and_page_numbers(self):
        c = self.collector(replace(self.source, company_key='amd', provider_key='amd_careers', access_url='https://careers.amd.com/api/jobs'))
        c.session.request.side_effect = [
            self.response(data={'totalCount': 2, 'jobs': [{'data': {'req_id': '1', 'title': 'Engineer'}}]}),
            self.response(data={'totalCount': 2, 'jobs': [{'data': {'req_id': '2', 'title': 'Engineer'}}]}),
        ]
        with patch('jobdisco.collector.time.sleep'):
            self.assertEqual(c.run(), ('complete', ''))
        self.assertIn('page=2', c.session.request.call_args_list[1].args[1])
        self.assertEqual(c.jobs[0]['url'], 'https://careers.amd.com/careers-home/jobs/1')

    def test_paid_search_is_disabled_by_default_and_empty_boards_do_not_trigger_it(self):
        for options, status in [([], 'failed'), (['--jsearch-budget', '1'], 'complete'), (['--jsearch-budget', '1'], 'paused')]:
            with self.subTest(options=options, status=status):
                argv = ['job-collect', '--output', self.temp.name] + options
                with patch('sys.argv', argv), patch('jobdisco.collector.load_credentials'), \
                     patch('jobdisco.collector.load_sources', return_value=[self.source]), \
                     patch('jobdisco.collector.RequestGuard') as guard, \
                     patch('jobdisco.collector.Collector.run', return_value=(status, '')), \
                     patch('jobdisco.collector.fallback') as fallback, patch('builtins.print'):
                    guard.return_value.attempts = 0
                    main()
                    fallback.assert_not_called()

    def test_legacy_probe_command_does_not_send_requests(self):
        with patch('requests.Session') as session, patch('builtins.print'):
            self.assertEqual(probe_sources.main(), 2)
        session.assert_not_called()


if __name__ == '__main__':
    unittest.main()
