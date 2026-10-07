"""Real captured structures, synthetic content; shared filtering regressions."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from operation1million import collector, job_details, jsearch, store


class DetailTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent / 'fixtures'
        self.page = (root / 'posting_detail_redacted.html').read_text(encoding='utf-8')
        self.workday = json.loads((root / 'workday_detail_redacted.json').read_text(encoding='utf-8'))
        self.eightfold = json.loads((root / 'eightfold_detail_redacted.json').read_text(encoding='utf-8'))
        self.smartrecruiters = json.loads((root / 'smartrecruiters_detail_redacted.json').read_text(encoding='utf-8'))
        self.row = {'title': 'RTL Engineer', 'url': 'https://example.test/careers/job/100',
                    'source_job_id': '100', 'raw': {}}

    def test_list_admits_but_captured_detail_rejects_required_years(self):
        rules = jsearch.load_plan()[0]['filter']
        self.assertEqual(jsearch.rejection_reason(self.row, rules), '')
        self.row['raw'] = job_details.page_fields(self.page, self.row, self.row['url'])
        self.assertEqual(jsearch.rejection_reason(self.row, rules), 'required_experience_over_2_years')
        merged = store.merge_raw(store.slim(self.row['raw']), {'name': 'RTL Engineer'})
        self.assertIn('5 years', merged['description'])

    def test_wrong_posting_redirect_or_title_is_unknown(self):
        for url, row in [('https://example.test/search', self.row),
                         (self.row['url'], dict(self.row, url=self.row['url']+'1')),
                         (self.row['url'], dict(self.row, title='DFT Engineer'))]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                job_details.page_fields(self.page, row, url)

    def test_workday_identity_and_missing_description(self):
        path = '/job/Example/RTL-Engineer_R0001'
        self.assertIn('8 years', job_details.workday_fields(self.workday, path)['description'])
        with self.assertRaises(ValueError):
            job_details.workday_fields(self.workday, path+'1')
        self.workday['jobPostingInfo']['jobDescription'] = ''
        with self.assertRaises(ValueError):
            job_details.workday_fields(self.workday, path)

    def test_full_list_description_avoids_extra_request(self):
        c = SimpleNamespace(source=SimpleNamespace(provider_key='eightfold'),
                            jobs=[dict(self.row, raw={'description': 'Digital design experience.'})],
                            fetch=Mock())
        self.assertEqual(job_details.enrich(c), [])
        c.fetch.assert_not_called()

    def test_json_inventory_enriches_before_session_close(self):
        source = SimpleNamespace(company_key='example', provider_key='phenom',
                                 access_url='https://example.test/api/pcsx/search')
        c = collector.Collector(source, SimpleNamespace(delay=1, store=False))
        c.jobs = [self.row]
        response = Mock(text=self.page, url=self.row['url'])
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        c.fetch = Mock(return_value=response)
        with patch.object(c, 'collect_json', return_value=('complete', '')):
            self.assertEqual(c.run(), ('complete', ''))
        self.assertIn('5 years', self.row['raw']['description'])

    def test_partial_inventory_status_survives_successful_details(self):
        source = SimpleNamespace(company_key='example', provider_key='eightfold',
                                 access_url='https://example.test/api/pcsx/search')
        c = collector.Collector(source, SimpleNamespace(delay=1, store=False))
        c.jobs = [self.row]
        with patch.object(c, 'collect_json', return_value=('partial', 'Missing continuation')), \
                patch('operation1million.job_details.enrich', return_value=[]):
            self.assertEqual(c.run(), ('partial', 'Missing continuation'))

    def test_html_shell_preserves_unknown_inventory(self):
        c = SimpleNamespace(source=SimpleNamespace(provider_key='talentbrew'),
                            jobs=[self.row], fetch=Mock())
        response = Mock(text='<html>Job search</html>', url=self.row['url'])
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        c.fetch.return_value = response
        self.assertEqual(len(job_details.enrich(c)), 1)
        self.assertEqual(len(c.jobs), 1)
        self.assertEqual(self.row['raw']['detail_evidence']['status'], 'unverified')

    def test_eightfold_preserves_preferred_heading_and_degree_alternatives(self):
        self.row['raw'] = job_details.eightfold_fields(self.eightfold, '100')
        result = jsearch.experience_debug(self.row)
        self.assertEqual(result['effective_experience_years'], 1)
        self.assertEqual(result['hard_pass_reason'], '')
        with self.assertRaises(ValueError):
            job_details.eightfold_fields(self.eightfold, '101')

    def test_smartrecruiters_sections_and_identity(self):
        description = job_details.smartrecruiters_fields(self.smartrecruiters, '100')['description']
        self.assertIn('5 years', description)
        self.assertIn('<h2>Qualifications</h2>', description)
        with self.assertRaises(ValueError):
            job_details.smartrecruiters_fields(self.smartrecruiters, '101')

    def test_detail_api_routes_use_inventory_identity(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        cases = [
            ('eightfold', 'https://example.test/api/pcsx/search?domain=example.test', {},
             self.eightfold, '/api/pcsx/position_details?position_id=100&domain=example.test&hl=en'),
            ('smartrecruiters', 'https://api.smartrecruiters.com/v1/companies/Example/postings', {},
             self.smartrecruiters, '/v1/companies/Example/postings/100'),
            ('workday', '', {'tenant': 'example', 'site': 'External', 'workday_host': 'wd1'},
             self.workday, '/wday/cxs/example/External/job/Example/RTL-Engineer_R0001'),
        ]
        for provider, access, fields, data, suffix in cases:
            response.json.return_value = data
            source = SimpleNamespace(provider_key=provider, access_url=access, fields=fields)
            c = SimpleNamespace(source=source, fetch=Mock(return_value=response))
            row = dict(self.row, raw={'externalPath': '/job/Example/RTL-Engineer_R0001'})
            with self.subTest(provider=provider):
                self.assertTrue(job_details.read(c, row)['description'])
                self.assertTrue(c.fetch.call_args.args[0].endswith(suffix))
