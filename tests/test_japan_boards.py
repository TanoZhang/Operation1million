"""Japan's chip boards read directly: BambooHR (EdgeCortix), Talentio (PFN).

Fixtures keep the shapes of the public responses captured on 2026-10-11 (see
fixtures/direct-source-captures.md); no request is made.
"""
import argparse
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from operation1million import experience, location
from operation1million.collector import Collector, Source

FIXTURES = Path(__file__).parent / 'fixtures'


def fixture(name):
    return (FIXTURES / name).read_text(encoding='utf-8')


class Response(SimpleNamespace):
    def json(self):
        return json.loads(self.text)


class JapanBoardTests(unittest.TestCase):
    def setUp(self):
        robots = patch('operation1million.collection_policy.robots_delay', return_value=None)
        robots.start()
        self.addCleanup(robots.stop)

    def collector(self, source, pages):
        args = argparse.Namespace(max_jobs=100, max_pages=10, delay=0, timeout=1,
                                  jsearch_timeout=1, fallback_queries=1)
        c = Collector(source, args)
        self.addCleanup(c.session.close)
        asked = []

        def fetch(url, *unused):
            asked.append(url)
            for suffix, name in pages.items():
                if url.endswith(suffix):
                    return Response(text=fixture(name))
            raise AssertionError(f'unexpected request {url}')
        c.fetch = fetch
        return c, asked

    def test_bamboohr_reads_the_list_then_each_detail(self):
        source = Source('bamboohr:example', 'company_sources', 'edgecortix', 'EdgeCortix', 'bamboohr',
                        'https://example.bamboohr.com/careers', {'subdomain': 'example'})
        c, asked = self.collector(source, {'/careers/list': 'bamboohr_list_redacted.json',
                                           '/detail': 'bamboohr_detail_redacted.json'})
        self.assertEqual(c.run(), ('complete', ''))
        self.assertEqual(asked[0], 'https://example.bamboohr.com/careers/list')
        jobs = {job['source_job_id']: job for job in c.jobs}
        self.assertEqual(jobs['25']['url'], 'https://example.bamboohr.com/careers/25')
        # The title's "[Japan]" names the country the list leaves out.
        self.assertEqual(jobs['25']['location'], 'Kawasaki, Kanagawa, Japan')
        self.assertTrue(location.in_asia_tab(jobs['25']['location']))
        self.assertTrue(location.outside_allowed(jobs['33']['location']))
        self.assertIn('SystemVerilog', jobs['25']['raw']['description'])

    def test_talentio_reads_each_home_and_page(self):
        source = Source('talentio:example', 'company_sources', 'preferred_networks', 'Preferred Networks',
                        'talentio', 'https://open.talentio.com/r/1/c/example',
                        {'homes': ['https://open.talentio.com/r/1/c/example/homes/1'],
                         'location': 'Tokyo, Japan'})
        c, _ = self.collector(source, {'/homes/1': 'talentio_home_redacted.html',
                                       '/pages/101': 'talentio_page_redacted.html'})
        self.assertEqual(c.run(), ('complete', ''))
        [job] = c.jobs
        self.assertEqual(job['url'], 'https://open.talentio.com/r/1/c/example/pages/101')
        self.assertEqual(job['source_job_id'], '101')
        self.assertTrue(location.in_asia_tab(job['location']))
        # The preferred section's eight years are not a requirement.
        description = job['raw']['description']
        self.assertIn('応募資格（歓迎）', description)
        self.assertIsNone(experience.evaluate(job['title'], description)['required_experience_years'])

    def test_hrmos_pages_until_empty_and_reads_a_likely_posting(self):
        source = Source('hrmos:example', 'company_sources', 'toshiba', 'Toshiba', 'hrmos',
                        'https://hrmos.co/pages/example/jobs', {'country': 'Japan'})
        c, asked = self.collector(source, {'?page=1': 'hrmos_list_redacted.html',
                                           '?page=2': 'hrmos_empty_redacted.html',
                                           '/jobs/300000016': 'hrmos_detail_redacted.html'})
        self.assertEqual(c.run(), ('complete', ''))
        jobs = {job['source_job_id']: job for job in c.jobs}
        self.assertEqual(set(jobs), {'300000016', '000600001'})
        chip = jobs['300000016']
        self.assertEqual(chip['title'], 'AT-N1【神奈川】マイコン・システム LSIのデジタル設計エンジニア')
        self.assertEqual(chip['location'], '川崎市幸区, 神奈川県, Japan')
        self.assertEqual(experience.evaluate(chip['title'], chip['raw']['description'])['required_experience_years'], 3)
        # Accounting is listed but not worth a detail request.
        self.assertNotIn('https://hrmos.co/pages/example/jobs/000600001', asked)
        self.assertEqual(jobs['000600001']['location'], '首都圏, Japan')

    def test_jposting_lists_from_json_and_reads_requirements_from_the_page(self):
        source = Source('jposting:example', 'company_sources', 'kioxia', 'Kioxia', 'jposting',
                        'https://api.example.com/example/u/jobs.phtml',
                        {'board': 'https://example.jposting.net/joblist/',
                         'detail': 'https://example.jposting.net/u/job.phtml?job_code=',
                         'encoding': 'euc-jp', 'country': 'Japan'})
        detail = (FIXTURES / 'jposting_detail_redacted.html').read_bytes()

        class Page:
            encoding = None
            @property
            def text(self):
                return detail.decode(self.encoding or 'latin-1')

        c, asked = self.collector(source, {})

        def fetch(url, *unused):
            asked.append(url)
            if 'jobs.phtml' in url:
                return Response(text=fixture('jposting_list_redacted.json'))
            return Page()
        c.fetch = fetch
        self.assertEqual(c.run(), ('complete', ''))
        self.assertEqual(c.session.headers['Referer'], 'https://example.jposting.net/joblist/')
        self.assertIn('job_items%5B%5D=description', asked[0].replace('[]', '%5B%5D'))
        jobs = {job['source_job_id']: job for job in c.jobs}
        chip = jobs['786']
        self.assertEqual(chip['url'], 'https://example.jposting.net/u/job.phtml?job_code=786')
        self.assertTrue(location.in_asia_tab(chip['location']))
        self.assertEqual(experience.evaluate(chip['title'], chip['raw']['description'])['required_experience_years'], 5)
        self.assertNotIn('https://example.jposting.net/u/job.phtml?job_code=880', asked)
        # The board's links to its other job families are not this posting's duties.
        self.assertNotIn('職種紹介をみる', chip['raw']['description'])

    def test_a_talentio_home_listing_nothing_is_partial(self):
        source = Source('talentio:example', 'company_sources', 'preferred_networks', 'Preferred Networks',
                        'talentio', 'https://open.talentio.com/r/1/c/example',
                        {'homes': ['https://open.talentio.com/r/1/c/example/homes/1']})
        c, _ = self.collector(source, {})
        c.fetch = lambda *unused: Response(text='<div data-react-props="{&quot;previewMode&quot;: false}"></div>')
        self.assertEqual(c.run(), ('partial', 'Talentio homes listed no postings'))


if __name__ == '__main__':
    unittest.main()
