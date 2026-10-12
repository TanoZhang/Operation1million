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

    def test_a_talentio_home_listing_nothing_is_partial(self):
        source = Source('talentio:example', 'company_sources', 'preferred_networks', 'Preferred Networks',
                        'talentio', 'https://open.talentio.com/r/1/c/example',
                        {'homes': ['https://open.talentio.com/r/1/c/example/homes/1']})
        c, _ = self.collector(source, {})
        c.fetch = lambda *unused: Response(text='<div data-react-props="{&quot;previewMode&quot;: false}"></div>')
        self.assertEqual(c.run(), ('partial', 'Talentio homes listed no postings'))


if __name__ == '__main__':
    unittest.main()
