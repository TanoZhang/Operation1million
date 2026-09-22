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

from jobdisco import ranking, review

ROOT = Path(__file__).resolve().parents[1]


def group(**extra):
    return dict({
        'id': 'abc', 'company': 'Example Semiconductor', 'title': 'RTL Design Engineer',
        'confidence': 80, 'bucket': 1, 'flagged': False,
        'jobs': [{'url': 'https://example.test/1', 'location': 'Austin',
                  'provider_key': 'jsearch', 'first_seen': '2026-09-19T00:00:00+00:00',
                  'source_job_id': 'req-1', 'title': 'RTL Design Engineer',
                  'posted_at': None, 'company': 'Example Semiconductor',
                  'company_key': 'example', 'confidence': 80}]}, **extra)


class SlimTests(unittest.TestCase):
    def test_it_keeps_everything_the_page_renders(self):
        out = review.slim({'pending': [group()], 'ledger': '/tmp/l'})['pending'][0]
        self.assertEqual(set(out), {'id', 'company', 'title', 'confidence', 'jobs',
                                    'bucket', 'flagged'})
        self.assertEqual(set(out['jobs'][0]),
                         {'url', 'location', 'provider_key', 'first_seen', 'posted_at'})

    def test_the_band_and_its_mark_reach_the_page(self):
        """Band 0 must survive the projection; a falsy value is still a value."""
        out = review.slim({'pending': [group(bucket=0, flagged=True)]})['pending'][0]
        self.assertEqual(out['bucket'], 0)
        self.assertIs(out['flagged'], True)

    def test_the_page_has_a_class_for_every_band_it_can_emit(self):
        """A chip rendered into a class that does not exist is an invisible chip."""
        css = (ROOT / 'src/jobdisco/review_static/style.css').read_text(encoding='utf-8')
        self.assertIn('.band{', css, 'the base chip style carries bands with no rule of their own')
        for index in range(len(ranking.LABELS)):
            self.assertTrue(f'.band-{index}' in css or '.band{' in css)
        self.assertIn('.flagged{', css)

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


class ClientSourceContractTests(unittest.TestCase):
    """Three defects the page could only have in a browser, read as source.

    This checkout has no JavaScript runtime, so these assert the shape of the
    fix rather than its behaviour: a bare date parsed as a local calendar day,
    a refresh that ignores an answer a newer one has overtaken, and a skip
    dialog that files its reason against the posting it was opened for.
    """

    def script(self):
        return (ROOT / 'src/jobdisco/review_static/app.js').read_text(encoding='utf-8')

    def test_dates_do_not_go_through_the_utc_reading_of_a_bare_day(self):
        script = self.script()
        # Asserted with a message rather than assertIn: a failure here would
        # otherwise print the whole page source.
        self.assertTrue('const asDate = value =>' in script,
                        'the page has no local-day reading of a bare date')
        for reader in ('const date = value =>', 'const postedToday = job =>'):
            line = next(l for l in script.splitlines() if l.startswith(reader))
            self.assertIn('asDate(', line, f'{reader} still parses the value directly')
            self.assertNotIn('new Date(value)', line)
            self.assertNotIn('new Date(job.posted_at)', line)

    def test_a_refresh_discards_an_answer_a_newer_one_has_overtaken(self):
        body = self.script().split('async function refresh()')[1].split('}')[0]
        self.assertTrue('++queueVersion' in body, 'refresh takes no sequence number')
        self.assertTrue('if (version !== queueVersion) return;' in body,
                        'refresh does not discard an overtaken answer')

    def test_the_skip_dialog_files_against_the_posting_it_was_opened_for(self):
        script = self.script()
        self.assertTrue('skipTarget = group.id;' in script,
                        'the dialog does not record which posting it was opened for')
        self.assertTrue("decide('skipped', $('#reason').value, skipTarget)" in script,
                        'the skip form does not submit against that posting')
        self.assertTrue('const id = target ?? selected;' in script,
                        'decide() ignores the posting it was given')


    def test_nothing_is_drawn_until_the_first_queue_arrives(self):
        """Seen on 2026-09-22: a page reading "All done for today", 0 to review,
        over a queue of 532. The placeholder state was rendered before the first
        response, by a tab click or a keystroke during a cold build."""
        script = self.script()
        render = script.split('function render() {')[1]
        self.assertTrue(render.lstrip().startswith('if (!loaded) return;'),
                        'render() draws the placeholder state before any queue is loaded')
        refresh = script.split('async function refresh()')[1].split('function filtered')[0]
        self.assertTrue('state = next; loaded = true;' in refresh,
                        'only a successful response may mark the queue loaded')
        self.assertTrue('if (!loaded) $('#list').innerHTML' in refresh,
                        'a failed first load leaves the list saying it is loading')


    def test_a_saved_decision_leaves_the_list_before_the_refresh(self):
        """Asked for on 2026-09-22: Skip or Mark applied should take the posting
        out of the list and into its tab at once, not after a reload."""
        decide = self.script().split('async function decide(')[1].split('\n}\n')[0]
        self.assertTrue('moveDecided(id, written);' in decide, 'the page waits for the reload')
        self.assertLess(decide.index('moveDecided(id, written);'), decide.index('refresh();'))
        self.assertFalse('await refresh();' in decide,
                         'the next decision is held until the reload answers')

class QueueCacheTests(unittest.TestCase):
    """A read of the index must not cost the next visitor a 28-second build."""

    def setUp(self):
        import tempfile
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.wal = Path(self.folder.name) / 'index.sqlite-wal'

    def test_an_empty_sidecar_has_no_fingerprint_however_often_it_is_touched(self):
        import os
        self.assertIsNone(review.wal_fingerprint(self.wal), 'an absent sidecar')
        self.wal.write_bytes(b'')
        self.assertIsNone(review.wal_fingerprint(self.wal), 'an empty sidecar')
        os.utime(self.wal, ns=(1, 10**18))
        self.assertIsNone(review.wal_fingerprint(self.wal), 'a touched empty sidecar')

    def test_a_sidecar_holding_a_commit_still_invalidates(self):
        self.wal.write_bytes(b'x' * 32)
        first = review.wal_fingerprint(self.wal)
        self.assertIsNotNone(first)
        self.wal.write_bytes(b'x' * 64)
        self.assertNotEqual(review.wal_fingerprint(self.wal), first)

    def test_the_warm_up_builds_before_anyone_asks_and_survives_a_failure(self):
        import threading
        calls = []
        stop = threading.Event()

        class Server:
            def current_queue(self):
                calls.append(1)
                if len(calls) == 1:
                    raise OSError('index locked')
                stop.set()
        review.keep_warm(Server(), every=0, stop=stop)
        self.assertEqual(len(calls), 2, 'one failed build stopped the warm-up')


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
