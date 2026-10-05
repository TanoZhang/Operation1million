"""JSearch collection defects found analysing nine days of paid runs, 2026-09-27.

The data repository's manifests and seen table, read against the plan: 10,867
paid records were 1,491 listings, because JSearch gives a listing a new
job_id nearly every time it returns it; one Qualcomm internship came back
under 113 ids. Red on 2665fa6.
"""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from operation1million import jsearch, store
from operation1million.jsearch_access import RequestGuard

SEARCH = {'endpoint_template': 'https://api.openwebninja.com/jsearch/search-v2',
          'connection': {'auth_header': 'x-api-key'}}


def job(ident, url=None, **extra):
    return {'job_id': ident, 'job_title': 'RTL Design Engineer', 'employer_name': 'Analog Devices',
            'job_apply_link': url or f'https://jobs.example/{ident}',
            'job_description': 'Full responsibilities and qualifications. ' * 500, **extra}


class PaidRunTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings, _ = jsearch.load_plan()
        for target in ('operation1million.jsearch_access.time.sleep',):
            p = patch(target, Mock())
            p.start()
            self.addCleanup(p.stop)
        p = patch.dict('os.environ', {'JSEARCH_API_KEY': 'offline-test-placeholder'})
        p.start()
        self.addCleanup(p.stop)
        self.guard = RequestGuard(self.root / 'usage.sqlite', daily_limit=320, target_limit=9600)
        self.session = Mock()
        self.client = jsearch.Client(SEARCH, self.settings, self.guard, session=self.session)

    def response(self, jobs=(), status=200, cursor=None):
        response = Mock(status_code=status, headers={})
        response.json.return_value = {'status': 'OK', 'data': {'jobs': list(jobs), 'cursor': cursor}}
        return response

    def collect(self, queries):
        return jsearch.collect(queries, self.client, self.settings, {}, lambda *args: None)

    def test_194_one_listing_under_two_ids_is_one_unique_job(self):
        """The run's unique count read JSearch's job_id, which changes for the
        same listing; the manifests' unique counts were inflated five-fold."""
        page = [job('a', 'https://www.linkedin.com/jobs/view/1'), job('b', 'https://www.linkedin.com/jobs/view/1'),
                job('c', 'https://www.linkedin.com/jobs/view/2')]
        self.session.get.return_value = self.response(page)
        _, stats = self.collect([jsearch.Query('RTL Design Engineer', 1, 'A')])
        self.assertEqual(stats['jsearch_jobs_unique'], 2)

    def test_195_a_server_error_is_retried_once(self):
        """On 2026-09-24 fifteen of 35 queries stopped for the day at their
        first HTTP 504 and lost every page after it."""
        full = [job(f'{n}') for n in range(10)]
        self.session.get.side_effect = [self.response(full, cursor="retry-second"), self.response(status=504),
                                        self.response(full[:3])]
        rows, stats = self.collect([jsearch.Query('RTL Design Engineer', 5, 'A')])
        self.assertEqual(self.session.get.call_count, 3)
        self.assertEqual(stats['jsearch_failures'], 1)
        self.assertNotEqual(stats['jsearch_queries'][0]['status'], 'failed')

    def test_195_twice_is_the_end(self):
        self.session.get.side_effect = [self.response(status=504), self.response(status=504)]
        _, stats = self.collect([jsearch.Query('RTL Design Engineer', 5, 'A')])
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(stats['jsearch_queries'][0]['status'], 'failed')


class SeenCountTests(unittest.TestCase):
    def test_193_a_listing_seen_before_under_another_id_is_not_new(self):
        """seen_existing was 0 on every manifest: new listings were counted by
        the seen table's key, the unstable job_id."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'jobs.sqlite'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.commit()
        store.migrate(path)
        with closing(store.connect(path)) as db, db:
            store.record_seen(db, [{'provider_key': 'jsearch', 'source_job_id': 'a', 'url': 'https://x/1'}])
            rows = [{'provider_key': 'jsearch', 'source_job_id': 'b', 'url': 'https://x/1'},
                    {'provider_key': 'jsearch', 'source_job_id': 'c', 'url': 'https://x/2'},
                    {'provider_key': 'jsearch', 'source_job_id': 'd', 'url': 'https://x/2'}]
            self.assertEqual(store.count_new_listings(db, rows), (1, 1))


if __name__ == '__main__':
    unittest.main()
