"""What the review page shows as a posting's description, and whose it is.

R02 and the B23/B27 residual from Codex's fifteenth audit. Both run the real
store and the real server over loopback; nothing is mocked but the clock-free
fixture itself.
"""
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.parse import urlencode
from urllib.request import urlopen
from unittest.mock import patch

from jobdisco import applications, review, store
from jobdisco.job_text import display_description
from jobdisco.validate_sources import Source

DIRECT = Source('ashby:fixture', 'company_sources', 'fixture', 'Fixture', 'ashby', '', {})
PAID = Source('jsearch:fixture', 'discovery', 'fixture', 'Fixture', 'jsearch', '', {})


def row(ident, url, provider='ashby', raw=None):
    return dict(company_key='fixture', company_name='Fixture', provider_key=provider,
                source_job_id=ident, url=url, title='RTL Design Engineer', location='US',
                posted_at=None, raw=raw or {})


class DescriptionTests(unittest.TestCase):
    def test_nested_qualifications_preserve_labels_and_values(self):
        job = row('nested', 'https://example.test/nested', raw={
            'description': 'Build RTL blocks.',
            'requirements': {'education': 'BS in EE',
                             'skills': ['SystemVerilog', ['UVM']],
                             'minimum_projects': 2,
                             'travel_required': False,
                             'other': None}})
        self.persist([job])
        with self.server() as get:
            text = get(url=job['url'])['description']
        for fragment in ('Requirements', 'Education', 'BS in EE', 'Skills',
                         'SystemVerilog', 'UVM', 'Minimum projects', '2',
                         'Travel required', 'false'):
            self.assertIn(fragment, text)

    def test_unique_teaser_requirement_survives_a_nonempty_description(self):
        from jobdisco import jsearch
        job = row('unique', 'https://example.test/unique', raw={
            'description': 'Build RTL blocks.',
            'descriptionTeaser': 'Must be a U.S. citizen.'})
        self.persist([job])
        raw = json.loads(self.db.execute('SELECT raw FROM jobs').fetchone()[0])
        self.assertEqual(raw['descriptionTeaser'], 'Must be a U.S. citizen.')
        self.assertEqual(jsearch.rejection_reason(dict(job, raw=raw),
                         jsearch.load_plan()[0]['filter']), 'us_person_required')
        with self.server() as get:
            self.assertIn('Must be a U.S. citizen.', get(url=job['url'])['description'])

    def test_required_heading_is_not_lost_to_a_substring_in_prose(self):
        job = row('context', 'https://example.test/context', raw={
            'description': 'Python is preferred.', 'required_qualifications': 'Python'})
        self.persist([job])
        with self.server() as get:
            text = get(url=job['url'])['description']
        self.assertIn('Required qualifications\nPython', text)

    def test_entities_do_not_make_plain_type_names_into_html(self):
        for index, raw in enumerate((
                {'description': 'Use vector<T> &amp; RTL.'},
                {'description': 'Use vector<T> &amp; RTL.', 'requirements': 'Know C++.'})):
            job = row(str(index), 'https://example.test/type/' + str(index), raw=raw)
            self.persist([job])
            with self.server() as get:
                self.assertIn('Use vector<T> & RTL.', get(url=job['url'])['description'])

    def test_updated_duplicate_html_does_not_restore_obsolete_requirements(self):
        from jobdisco import jsearch
        url = 'https://example.test/update'
        self.persist([row('update', url, raw={
            'descriptionPlain': 'Earlier summary.',
            'descriptionHtml': '<p>You must be a U.S. citizen.</p>'})])
        self.persist([row('update', url, raw={
            'descriptionPlain': 'Build RTL blocks.',
            'descriptionHtml': '<p>Build RTL blocks.</p>'})])
        raw = json.loads(self.db.execute('SELECT raw FROM jobs WHERE url=?', (url,)).fetchone()[0])
        self.assertNotIn('citizen', json.dumps(raw))
        self.assertEqual(jsearch.rejection_reason(row('update', url, raw=raw),
                         jsearch.load_plan()[0]['filter']), '')

    def test_structural_html_survives_storage_and_replay(self):
        from jobdisco import degree, jsearch
        job = row('structure', 'https://example.test/structure', raw={
            'descriptionPlain': 'Basic Qualifications PhD in EE',
            'descriptionHtml': '<h2>Basic Qualifications</h2><p>PhD in EE</p>'})
        self.persist([job])
        # Rebuild a separate derived index from the event log.
        rebuilt = self.root / 'replayed.sqlite'
        with closing(sqlite3.connect(rebuilt)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        store.rebuild(rebuilt)
        for path in (self.path, rebuilt):
            with closing(sqlite3.connect(path)) as db:
                raw = json.loads(db.execute('SELECT raw FROM jobs').fetchone()[0])
            self.assertIn('descriptionHtml', raw)
            self.assertTrue(degree.phd_only(job['title'],
                jsearch.description_text({'raw': raw}, structured=True)))

    def test_empty_html_preserves_teaser_and_experience_gate(self):
        from jobdisco import jsearch
        job = row('teaser', 'https://example.test/teaser', raw={
            'description': '<p></p>',
            'descriptionTeaser': 'RTL role requiring 5 years of experience.'})
        self.persist([job])
        raw = json.loads(self.db.execute('SELECT raw FROM jobs').fetchone()[0])
        self.assertEqual(jsearch.rejection_reason(dict(job, raw=raw),
                         jsearch.load_plan()[0]['filter']), 'required_experience_over_2_years')
        with self.server() as get:
            self.assertEqual(get(url=job['url']), {
                'description': job['raw']['descriptionTeaser'], 'kind': 'excerpt'})

    def test_details_include_separate_qualification_fields(self):
        job = row('sections', 'https://example.test/sections', raw={
            'description': 'Build vector<T> RTL blocks.',
            'basic_qualifications': ['BS in EE.', 'SystemVerilog experience.'],
            'preferred_qualifications': '<p>UVM experience.</p>'})
        self.persist([job])
        with self.server() as get:
            body = get(url=job['url'])['description']
        for phrase in ('vector<T>', 'BS in EE.', 'SystemVerilog experience.', 'UVM experience.'):
            self.assertIn(phrase, body)

    def test_non_object_paid_payload_does_not_break_the_queue(self):
        job = row('malformed', 'https://example.test/malformed', provider='jsearch')
        self.persist([job], source=PAID)
        for value in (None, [], 'provider error', 1):
            self.db.execute('UPDATE jobs SET raw=?', (json.dumps(value),))
            self.db.commit()
            with self.subTest(value=value):
                self.assertEqual(len(applications.queue(self.path, self.ledger)['pending']), 1)

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='jobdisco-description-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.path = self.root / 'index.sqlite'
        self.ledger = self.root / 'applications.ndjson'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('fixture', 'Fixture')")
        for patcher in (patch.object(store, 'ROOT', self.root),
                        patch.object(store, 'LOG', self.root / 'history')):
            patcher.start()
            self.addCleanup(patcher.stop)
        store.migrate(self.path)
        self.db = store.connect(self.path)
        self.addCleanup(self.db.close)
        self.stamp = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()

    def persist(self, rows, source=DIRECT):
        result = store.record_source(self.db, source, rows, 'partial', 'full', 1, stamp=self.stamp)
        store.append_log(self.db, result['new_urls'] + result['changed_urls'], result['closed_urls'],
                         self.stamp, seen_urls=result['seen_urls'], source_id=source.source_id,
                         allow_sealed=True)
        self.db.commit()

    @contextmanager
    def server(self):
        instance = review.make_server(self.path, self.ledger, port=0)
        thread = threading.Thread(target=instance.serve_forever, daemon=True)
        thread.start()
        try:
            def get(**query):
                route = f'http://127.0.0.1:{instance.server_port}/api/job?' + urlencode(query)
                with urlopen(route, timeout=10) as response:
                    return json.load(response)
            yield get
        finally:
            instance.shutdown()
            instance.server_close()
            thread.join(timeout=5)

    # R02 -- a description stored under a field the page did not look in.

    def test_a_description_under_content_is_shown(self):
        job = row('A', 'https://example.test/A', raw={'content': 'Current provider description.'})
        self.persist([job])
        with self.server() as get:
            self.assertEqual(get(url=job['url']), {'description': 'Current provider description.'})

    def test_a_teaser_is_shown_and_says_it_is_one(self):
        job = row('A', 'https://example.test/A', raw={'descriptionTeaser': 'Design RTL for...'})
        self.persist([job])
        with self.server() as get:
            self.assertEqual(get(url=job['url']),
                             {'description': 'Design RTL for...', 'kind': 'excerpt'})

    def test_the_current_payload_is_asked_before_the_listing_it_replaced(self):
        raw = {'description': 'The company says this.',
               'jsearch': {'job_description': 'The paid listing said this.'}}
        self.assertEqual(display_description(raw), ('The company says this.', 'full'))
        self.assertEqual(display_description({'jsearch': raw['jsearch']}),
                         ('The paid listing said this.', 'discovery'))
        self.assertEqual(display_description({'title': 'x', 'url': 'https://example.test'}),
                         ('', None))

    def test_the_store_and_the_page_recognise_the_same_fields(self):
        """`slim` drops a teaser only beside a full description; if the two
        lists drifted apart, one of them would drop or miss a description."""
        from jobdisco import job_text
        self.assertIs(store.FULL_DESCRIPTIONS, job_text.FULL_DESCRIPTIONS)
        self.assertIs(store.TEASERS, job_text.TEASERS)

    # B23/B27 -- a replacement mistaken for a provider move.

    def decided_on_paid_listing(self):
        old = row('OLD', 'https://example.test/reused', 'jsearch',
                  raw={'job_description': 'Original requisition description.'})
        self.persist([old], PAID)
        group = applications.queue(self.path, self.ledger)['pending'][0]
        applications.append_decision(self.ledger, group, 'applied')
        self.persist([row('DIRECT-OLD', old['url'], raw={'description': 'Direct original description.'})])
        return old, group

    def test_a_replacement_under_the_same_title_is_not_shown_as_the_decided_job(self):
        old, group = self.decided_on_paid_listing()
        self.persist([row('NEW', old['url'], raw={'description': 'New requisition description.'})])
        state = applications.queue(self.path, self.ledger)
        self.assertEqual((len(state['applied']), len(state['pending'])), (1, 1),
                         'the queue itself should already tell these apart')
        with self.server() as get:
            self.assertEqual(get(url=old['url'], id=group['id']),
                             {'description': '', 'replaced': True})
            # Whatever the page claims about the provider and title it is showing.
            self.assertEqual(get(url=old['url'], id=group['id'], provider='jsearch',
                                 title=old['title']),
                             {'description': '', 'replaced': True})
            current = state['pending'][0]
            self.assertEqual(get(url=old['url'], id=current['id']),
                             {'description': 'New requisition description.'})

    def test_a_posting_that_only_changed_provider_still_shows_its_description(self):
        old, group = self.decided_on_paid_listing()
        state = applications.queue(self.path, self.ledger)
        self.assertEqual([g['id'] for g in state['applied']], [group['id']])
        with self.server() as get:
            self.assertEqual(get(url=old['url'], id=group['id']),
                             {'description': 'Direct original description.'})


class CheckpointManifestTests(unittest.TestCase):
    """O10: describing a day after each append must not reread the whole day."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='jobdisco-o10-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for patcher in (patch.object(store, 'ROOT', self.root),
                        patch.object(store, 'LOG', self.root / 'history')):
            patcher.start()
            self.addCleanup(patcher.stop)
        (self.root / 'history/runs').mkdir(parents=True)
        self.stamp = datetime.now(timezone.utc).isoformat()
        self.path = store.daily_log(self.stamp)

    def append(self, n):
        store._append_records(self.stamp, [{'type': 'seen', 'urls': [f'u{n}'], 'at': self.stamp}])
        return store._file_facts(self.path)

    def fresh(self):
        sha, records = store._scan_file(self.path)
        return sha.hexdigest(), records

    def test_twenty_checkpoints_read_the_file_once(self):
        """Codex measured 420 records visited for 40 logged; now the one scan
        that seeds the cache is the only one."""
        real = store._scan_file
        scans = []
        with patch.object(store, '_scan_file', side_effect=lambda p: scans.append(1) or real(p)):
            facts = [self.append(n) for n in range(20)]
        self.assertEqual(len(scans), 1)
        self.assertEqual(facts[-1], self.fresh())
        self.assertEqual(facts[-1][1], 20)

    def test_another_writer_is_noticed(self):
        self.append(0)
        self.append(1)
        import gzip as gz
        with self.path.open('ab') as handle:
            handle.write(gz.compress(b'{"type": "seen"}\n', mtime=0))
        self.assertEqual(store._file_facts(self.path), self.fresh())
        self.assertEqual(store._file_facts(self.path)[1], 3)

    def test_a_failed_write_is_not_counted(self):
        self.append(0)
        real_open = Path.open

        def failing(path, mode='r', *args, **kwargs):
            handle = real_open(path, mode, *args, **kwargs)
            if mode == 'ab':
                handle.write(b'partial')
                handle.close()
                raise OSError('disk full')
            return handle
        with patch.object(Path, 'open', failing), self.assertRaises(OSError):
            store._append_records(self.stamp, [{'type': 'seen', 'urls': ['x'], 'at': self.stamp}])
        self.assertEqual(store._file_facts(self.path), self.fresh())
        self.assertEqual(store._file_facts(self.path)[1], 1)

    def test_a_rollover_starts_the_new_file_fresh(self):
        self.append(0)
        store.shard_daily_log(self.stamp)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.append(1), self.fresh())
        self.assertEqual(self.append(2)[1], 2)


if __name__ == '__main__':
    unittest.main()
