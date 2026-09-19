"""The queue endpoint returns what the page renders, and no more.

`queue()` carries everything a decision needs to be written against. The browser
renders a fraction of it, and on 21,222 groups the difference was 3.6 MB of a
12.5 MB response -- title, source_job_id, company, company_key and confidence,
none of which the page touches. Trimming the response is safe only because the decision path
never reads it back: `do_POST` rebuilds the group from its own `queue()` call.
That is the property these tests hold in place.
"""
from pathlib import Path
import json
import re
import unittest

from jobdisco import review

ROOT = Path(__file__).resolve().parents[1]


def group(**extra):
    return dict({
        'id': 'abc', 'company': 'Example Semiconductor', 'title': 'RTL Design Engineer',
        'confidence': 80,
        'jobs': [{'url': 'https://example.test/1', 'location': 'Austin',
                  'provider_key': 'jsearch', 'first_seen': '2026-09-19T00:00:00+00:00',
                  'source_job_id': 'req-1', 'title': 'RTL Design Engineer',
                  'posted_at': None, 'company': 'Example Semiconductor',
                  'company_key': 'example', 'confidence': 80}]}, **extra)


class SlimTests(unittest.TestCase):
    def test_it_keeps_everything_the_page_renders(self):
        out = review.slim({'pending': [group()], 'ledger': '/tmp/l'})['pending'][0]
        self.assertEqual(set(out), {'id', 'company', 'title', 'confidence', 'jobs'})
        self.assertEqual(set(out['jobs'][0]),
                         {'url', 'location', 'provider_key', 'first_seen', 'posted_at'})

    def test_it_drops_the_fields_that_only_the_decision_path_needs(self):
        out = review.slim({'pending': [group()]})['pending'][0]
        for absent in ('source_job_id', 'title', 'company_key', 'company', 'confidence'):
            self.assertNotIn(absent, out['jobs'][0])

    def test_a_decided_group_keeps_its_timestamp_and_reason(self):
        out = review.slim({'skipped': [group(at='2026-09-19T01:00:00+00:00',
                                             reason='wrong stack')]})['skipped'][0]
        self.assertEqual(out['at'], '2026-09-19T01:00:00+00:00')
        self.assertEqual(out['reason'], 'wrong stack')

    def test_non_list_values_pass_through(self):
        """`ledger` and `token` are not groups."""
        out = review.slim({'ledger': '/tmp/applications.ndjson', 'pending': []})
        self.assertEqual(out['ledger'], '/tmp/applications.ndjson')

    def test_every_bucket_is_trimmed_not_just_pending(self):
        state = {name: [group()] for name in ('pending', 'backlog', 'applied', 'skipped')}
        out = review.slim(state)
        for name in state:
            self.assertNotIn('company_key', out[name][0]['jobs'][0], name)

    def test_a_group_missing_an_optional_field_does_not_raise(self):
        self.assertEqual(review.slim({'pending': [{'id': 'x', 'jobs': []}]})['pending'][0],
                         {'id': 'x', 'jobs': []})

    def test_it_is_smaller(self):
        full = {'pending': [group() for _ in range(200)]}
        self.assertLess(len(json.dumps(review.slim(full))), len(json.dumps(full)) * 0.75)


class ClientContractTests(unittest.TestCase):
    """If the page reads a field, the projection has to carry it."""

    def test_no_job_field_is_read_by_the_page_that_the_projection_drops(self):
        script = (ROOT / 'src/jobdisco/review_static/app.js').read_text(encoding='utf-8')
        # Every `job.<name>` the page touches, however it is spelled.
        read = set(re.findall(r'\bjob\.([a-z_]+)', script))
        self.assertTrue(read, 'found no job field reads; the pattern has gone stale')
        self.assertTrue(read <= set(review.JOB_FIELDS),
                        f'the page reads {sorted(read - set(review.JOB_FIELDS))}, '
                        f'which /api/queue no longer sends')

    def test_no_group_field_is_read_by_the_page_that_the_projection_drops(self):
        script = (ROOT / 'src/jobdisco/review_static/app.js').read_text(encoding='utf-8')
        read = set(re.findall(r'\bgroup\.([a-z_]+)', script))
        self.assertTrue(read)
        self.assertTrue(read <= set(review.GROUP_FIELDS) | {'jobs'},
                        f'the page reads {sorted(read - set(review.GROUP_FIELDS) - {"jobs"})}, '
                        f'which /api/queue no longer sends')


if __name__ == '__main__':
    unittest.main()
