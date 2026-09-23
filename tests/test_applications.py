"""Application decisions survive job-index replacement and process restarts.

A decision covers one requisition. Company and title used to be the identity,
which merged separate openings that happened to share a name: measured on the
live queue, Apple's Design Verification Engineer was 48 postings across 14
locations, so skipping it once would have buried at least 34 other requisitions
without saying so. Showing a posting twice is recoverable; hiding one is not.
"""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import sqlite3
import tempfile
import threading
import unittest
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from unittest.mock import patch

from jobdisco import applications, review


class ApplicationsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = self.root / 'jobs.sqlite'
        self.ledger = self.root / 'operational/applications.ndjson'
        self.now = datetime.now(timezone.utc)
        self.create_database()

    def create_database(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript('''CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);
                INSERT INTO companies VALUES ('sample', 'Sample Semiconductor');
                CREATE TABLE jobs(url TEXT PRIMARY KEY, company_key TEXT, title TEXT, location TEXT,
                                  source_job_id TEXT,
                                  first_seen TEXT, posted_at TEXT, provider_key TEXT,
                                  relevance REAL, closed_at TEXT, raw TEXT,
                                  last_seen TEXT);''')
            # a and b share a company and a normalized title but are separate
            # requisitions. a2 is the same requisition as a, in another city.
            rows = [('a', 'RTL Engineer', 'req-a', 1, None),
                    ('a2', 'RTL Engineer', 'req-a', 1, None),
                    ('b', ' rtl  engineer ', 'req-b', 2, None),
                    ('c', 'Old Engineer', 'req-c', 4, None),
                    ('d', 'Closed Engineer', 'req-d', 1, 'closed')]
            for ident, title, requisition, age, closed in rows:
                db.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                           (f'https://example.test/{ident}', 'sample', title, ident.upper(),
                            requisition,
                            (self.now - timedelta(days=age)).isoformat(), None, 'direct', 80, closed,
                            json.dumps({'description': '<p>Design hardware.</p>'}),
                            (self.now - timedelta(days=age)).isoformat()))

    def queue(self):
        return applications.queue(self.db, self.ledger, self.now)

    def group_for(self, requisition, bucket='pending'):
        key = applications.decision_key({'provider_key': 'direct',
                                         'company_key': 'sample',
                                         'source_job_id': requisition, 'url': ''})
        return next(g for g in self.queue()[bucket] if g['id'] == key)

    def test_a_shared_title_is_not_a_shared_decision(self):
        """The bug this replaced: two requisitions answered by one click."""
        pending = self.queue()['pending']
        self.assertEqual(len(pending), 2, 'separate requisitions were merged')
        self.assertEqual({g['id'] for g in pending},
                         {applications.decision_key({'provider_key': 'direct',
                                                     'company_key': 'sample',
                                                     'source_job_id': r, 'url': ''})
                          for r in ('req-a', 'req-b')})

    def test_one_requisition_in_two_cities_is_still_one_decision(self):
        """The case the old grouping was right about, kept."""
        group = self.group_for('req-a')
        self.assertEqual({job['location'] for job in group['jobs']}, {'A', 'A2'})
        applications.append_decision(self.ledger, group, 'skipped', 'wrong stack')
        self.assertEqual(len(self.queue()['pending']), 1, 'the other city stayed open')
        self.assertEqual(len(self.queue()['skipped'][0]['jobs']), 2)

    def test_one_requisition_spanning_recent_and_backlog_has_one_complete_group(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE jobs SET first_seen=? WHERE url=?',
                       ((self.now - timedelta(days=5)).isoformat(), 'https://example.test/a2'))
        state = self.queue()
        key = self.group_for('req-a')['id']
        groups = [g for status in ('pending', 'backlog') for g in state[status]
                  if g['id'] == key]
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]['jobs']), 2)
        applications.append_decision(self.ledger, groups[0], 'applied')
        self.assertEqual(len(self.queue()['applied'][0]['jobs']), 2)

    def test_a_group_is_scored_on_its_best_listing_across_the_window(self):
        # The backlog listing scored higher, and merging it into the recent
        # group used to leave the group at the recent listing's score.
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE jobs SET first_seen=?, relevance=95 WHERE url=?',
                       ((self.now - timedelta(days=5)).isoformat(), 'https://example.test/a2'))
        self.assertEqual(self.group_for('req-a')['confidence'], 95)

    def test_a_board_that_states_only_an_age_gives_its_posting_a_date(self):
        # Workday prints "Posted 6 Days Ago", never a date, and its postings
        # reached the page undated.
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('ALTER TABLE jobs ADD COLUMN posted_relative TEXT')
            db.execute("UPDATE jobs SET posted_relative='Posted 6 Days Ago', last_seen=? WHERE url=?",
                       ('2026-09-23T11:38:00+00:00', 'https://example.test/a'))
            db.execute("UPDATE jobs SET posted_relative='Posted 30+ Days Ago' WHERE url=?",
                       ('https://example.test/b',))
        dates = {job['url']: job['posted_at'] for group in self.queue()['pending']
                 for job in group['jobs']}
        self.assertEqual(dates['https://example.test/a'], '2026-09-17')
        self.assertIsNone(dates['https://example.test/b'], 'a lower bound is not a date')

    def test_deciding_one_requisition_leaves_its_namesake_alone(self):
        applications.append_decision(self.ledger, self.group_for('req-a'), 'applied')
        remaining = self.queue()['pending']
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]['id'],
                         applications.decision_key({'provider_key': 'direct',
                                                    'company_key': 'sample',
                                                    'source_job_id': 'req-b', 'url': ''}))

    def test_direct_requisition_ids_are_scoped_to_the_company_board(self):
        left = applications.decision_key({'provider_key': 'workday', 'company_key': 'left',
                                          'source_job_id': 'R-123', 'url': 'https://left.test/job'})
        right = applications.decision_key({'provider_key': 'workday', 'company_key': 'right',
                                           'source_job_id': 'R-123', 'url': 'https://right.test/job'})
        self.assertNotEqual(left, right)

    def test_jsearch_requisition_ids_remain_provider_scoped(self):
        left = applications.decision_key({'provider_key': 'jsearch', 'company_key': 'left',
                                          'source_job_id': 'shared', 'url': 'https://left.test/job'})
        right = applications.decision_key({'provider_key': 'jsearch', 'company_key': 'right',
                                           'source_job_id': 'shared', 'url': 'https://right.test/job'})
        self.assertEqual(left, right)

    def test_applied_survives_database_rebuild(self):
        group = self.group_for('req-a')
        applications.append_decision(self.ledger, group, 'applied')
        self.db.unlink()
        self.create_database()
        state = self.queue()
        self.assertEqual(len(state['applied']), 1)
        self.assertEqual(applications.read_events(self.ledger)[0]['status'], 'applied')

    def test_a_new_requisition_under_a_decided_title_stays_pending(self):
        """Not missing a posting outranks not seeing a familiar title twice."""
        applications.append_decision(self.ledger, self.group_for('req-a'), 'applied')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("""INSERT INTO jobs SELECT 'https://example.test/new', company_key,
                          title, 'New York', 'req-new', first_seen, posted_at, provider_key,
                          relevance, closed_at, raw, last_seen
                          FROM jobs WHERE url='https://example.test/a'""")
        self.assertIn('req-new', {job['source_job_id']
                                  for group in self.queue()['pending'] for job in group['jobs']})

    def seen_table(self, url, decision, requisition='req-b', provider='jsearch',
                   ago=timedelta(0)):
        """The rejection record a paid pass leaves behind for a posting it drops."""
        stamp = (self.now - ago).isoformat()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS seen_jobs (
                provider_key TEXT NOT NULL, source_job_id TEXT NOT NULL, url TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '', employer TEXT NOT NULL DEFAULT '',
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                decision TEXT NOT NULL DEFAULT '', confidence INTEGER,
                filter_version TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (provider_key, source_job_id))""")
            db.execute('INSERT OR REPLACE INTO seen_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                       (provider, requisition, url, 'RTL Engineer', 'Sample Semiconductor',
                        stamp, stamp, decision, 80, 'v1'))
            db.execute("UPDATE jobs SET provider_key='jsearch' WHERE url=?", (url,))

    def pending_urls(self):
        return {job['url'] for status in ('pending', 'backlog')
                for group in self.queue()[status] for job in group['jobs']}

    def test_a_posting_the_last_pass_rejected_is_not_offered_from_an_older_copy(self):
        """The rejection is on record, and it is newer than the copy on show.

        A paid pass that rejects a posting does not store the description it
        rejected, so the index keeps the text from the pass that accepted it.
        The queue went on offering a posting whose published terms had since
        disqualified it -- and offering it with the description that still
        qualified.
        """
        url = 'https://example.test/b'
        self.seen_table(url, 'required_experience_over_2_years')
        self.assertNotIn(url, self.pending_urls())

    def test_a_rejection_of_another_requisition_at_that_address_hides_nothing(self):
        """A reused URL puts one refused posting and one accepted one together.

        Matching the rejection by address alone took the wrong one down: the
        posting on show is identified by its requisition, and that is what the
        record has to be about.
        """
        url = 'https://example.test/b'
        self.seen_table(url, 'required_experience_over_2_years',
                        requisition='the-requisition-that-was-refused')
        self.assertIn(url, self.pending_urls())

    def test_an_older_rejection_does_not_hide_what_a_later_pass_accepted(self):
        """The index being newer means the rejection has already been answered."""
        url = 'https://example.test/b'
        self.seen_table(url, 'required_experience_over_2_years', ago=timedelta(days=5))
        self.assertIn(url, self.pending_urls())

    def test_a_query_scoped_rejection_does_not_hide_the_posting(self):
        """An employer mismatch says the query asked wrongly, not that the job is."""
        url = 'https://example.test/b'
        self.seen_table(url, 'employer_mismatch')
        self.assertIn(url, self.pending_urls())

    def test_a_decision_follows_a_posting_from_jsearch_to_the_direct_board(self):
        """The store merges the two discoveries into one row; the ledger follows it.

        A posting found first through JSearch and later on the company's own
        board keeps its URL and takes the direct provider. The decision key is
        scoped by provider, so an applied job came back as pending on the pass
        that found it directly -- and the second application is the kind of
        mistake this ledger exists to prevent.
        """
        url = 'https://example.test/b'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET provider_key='jsearch', source_job_id='js-1' "
                       "WHERE url=?", (url,))
        found = next(group for group in self.queue()['pending']
                     if any(job['url'] == url for job in group['jobs']))
        applications.append_decision(self.ledger, found, 'applied')
        self.assertEqual([job['url'] for group in self.queue()['applied']
                          for job in group['jobs']], [url])

        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET provider_key='direct', source_job_id='req-b' "
                       "WHERE url=?", (url,))
        state = self.queue()
        self.assertEqual([job['url'] for group in state['applied']
                          for job in group['jobs']], [url])
        self.assertNotIn(url, {job['url'] for group in state['pending']
                               for job in group['jobs']})

    def test_a_replacement_at_that_address_is_not_the_posting_that_was_applied_to(self):
        """A changed provider is not on its own evidence of the same opening.

        A decision follows a posting from JSearch to the company's own board
        because the store merged the two discoveries into one row. An address
        handed to a different board carrying a different job is the other case
        entirely, and reading the provider alone hid the new posting behind the
        old decision.
        """
        url = 'https://example.test/b'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET provider_key='jsearch', source_job_id='js-1' "
                       "WHERE url=?", (url,))
        found = next(group for group in self.queue()['pending']
                     if any(job['url'] == url for job in group['jobs']))
        applications.append_decision(self.ledger, found, 'applied')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET provider_key='direct', source_job_id='req-new', "
                       "title='DFT Engineer' WHERE url=?", (url,))
        self.assertIn(url, {job['url'] for group in self.queue()['pending']
                            for job in group['jobs']})

    def identity(self, url, provider, scope, requisition):
        """Record the alias the store writes when a board publishes a requisition."""
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS job_identities(
                              provider_key TEXT NOT NULL, scope TEXT NOT NULL,
                              source_job_id TEXT NOT NULL, url TEXT NOT NULL,
                              PRIMARY KEY(provider_key, scope, source_job_id))''')
            db.execute('INSERT OR REPLACE INTO job_identities VALUES (?, ?, ?, ?)',
                       (provider, scope, requisition, url))

    def release_identities(self, url):
        """What `record_source` does when an address carries a new requisition."""
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('DELETE FROM job_identities WHERE url=?', (url,))

    def test_a_replacement_at_a_decided_address_is_not_hidden_by_a_provider_move(self):
        """The decision follows the opening, not the address it was found at.

        A decision made on a paid result is allowed to follow that posting to
        the company's own board. It was allowed to follow the address instead:
        a board that later advertised a different requisition at the same URL,
        under the same company and title, inherited the earlier application and
        never appeared for review. The store says which case it is -- a
        provider upgrade keeps the decided requisition among the address's
        aliases, a replacement releases it.
        """
        url = 'https://example.test/b'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET provider_key='jsearch', source_job_id='js-1' "
                       "WHERE url=?", (url,))
        self.identity(url, 'jsearch', '', 'js-1')
        found = next(group for group in self.queue()['pending']
                     if any(job['url'] == url for job in group['jobs']))
        applications.append_decision(self.ledger, found, 'applied')

        # The same opening, found again on the company's own board: the store
        # merges the two discoveries and holds both aliases.
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET provider_key='direct', source_job_id='req-b' "
                       "WHERE url=?", (url,))
        self.identity(url, 'direct', 'sample', 'req-b')
        self.assertNotIn(url, {job['url'] for group in self.queue()['pending']
                               for job in group['jobs']},
                         'a posting that only changed board came back as pending')

        # The board then advertises a different opening at that address.
        self.release_identities(url)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET source_job_id='req-new' WHERE url=?", (url,))
        self.identity(url, 'direct', 'sample', 'req-new')
        self.assertIn(url, {job['url'] for group in self.queue()['pending']
                            for job in group['jobs']},
                      'a requisition nobody has seen inherited an earlier application')
        self.assertEqual(len(self.queue()['applied']), 1,
                         'the application that was made stopped being history')

    def test_skip_and_reopen_only_append(self):
        group = self.group_for('req-a')
        applications.append_decision(self.ledger, group, 'skipped', 'Location')
        original = self.ledger.read_bytes()
        self.assertEqual(self.queue()['skipped'][0]['reason'], 'Location')
        applications.append_decision(self.ledger, group, 'pending')
        self.assertTrue(self.ledger.read_bytes().startswith(original))
        self.assertEqual(len(self.queue()['pending']), 2)
        self.assertEqual(self.queue()['skipped'], [])

    def test_reused_url_does_not_inherit_another_requisitions_decision(self):
        applications.append_decision(self.ledger, self.group_for('req-a'), 'skipped')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET source_job_id='req-new' WHERE url='https://example.test/a'")
        self.assertEqual(self.group_for('req-new')['jobs'][0]['url'], 'https://example.test/a')
        self.assertEqual(len(self.queue()['skipped']), 1)

    def old_title_group(self):
        group = self.group_for('req-a')
        group['id'] = 'old-company-title-key'
        group['jobs'].extend(self.group_for('req-b')['jobs'])
        return group

    def test_old_multi_requisition_snapshot_splits_before_reopening(self):
        applications.append_decision(self.ledger, self.old_title_group(), 'skipped')
        original = self.ledger.read_bytes()
        history = self.queue()['skipped']
        self.assertEqual(len(history), 2)
        first = self.group_for('req-a', 'skipped')
        applications.append_decision(self.ledger, first, 'pending')
        self.assertEqual({j['source_job_id'] for g in self.queue()['pending'] for j in g['jobs']},
                         {'req-a'})
        self.assertEqual(len(self.queue()['skipped']), 1)
        self.assertTrue(self.ledger.read_bytes().startswith(original))

    def test_all_requisitions_in_old_snapshot_survive_url_changes(self):
        applications.append_decision(self.ledger, self.old_title_group(), 'applied')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET url=url || '-new' WHERE source_job_id='req-b'")
        self.assertEqual(self.queue()['pending'], [])

    def test_new_identity_decision_overrides_older_url_only_decision(self):
        group = self.group_for('req-a')
        self.ledger.parent.mkdir(exist_ok=True)
        self.ledger.write_text(json.dumps({'url': group['jobs'][0]['url'],
                                          'at': self.now.isoformat(), 'status': 'skipped'}) + '\n',
                               encoding='utf-8')
        applications.append_decision(self.ledger, group, 'pending')
        self.assertEqual(len(self.group_for('req-a')['jobs']), 2)
        self.assertEqual(self.queue()['skipped'], [])

    def test_later_url_only_reopen_overrides_only_its_listing(self):
        group = self.group_for('req-a')
        applications.append_decision(self.ledger, group, 'applied')
        with self.ledger.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'url': group['jobs'][0]['url'],
                                     'at': self.now.isoformat(), 'status': 'pending'}) + '\n')
        self.assertEqual(len(self.group_for('req-a')['jobs']), 1)
        self.assertEqual(len(self.queue()['applied'][0]['jobs']), 1)

    def test_url_only_history_can_reopen_after_being_saved_as_a_snapshot(self):
        self.ledger.parent.mkdir(exist_ok=True)
        self.ledger.write_text(json.dumps({'url': 'https://example.test/a',
                                          'at': self.now.isoformat(), 'status': 'skipped'}) + '\n',
                               encoding='utf-8')
        history = self.queue()['skipped'][0]
        applications.append_decision(self.ledger, history, 'applied')
        applications.append_decision(self.ledger, self.queue()['applied'][0], 'pending')
        self.assertEqual(len(self.group_for('req-a')['jobs']), 2)
        self.assertEqual(self.queue()['applied'], [])
        self.assertEqual(self.queue()['skipped'], [])

    def test_url_only_event_is_honored(self):
        self.ledger.parent.mkdir()
        self.ledger.write_text(json.dumps({'url': 'https://example.test/a', 'at': self.now.isoformat(),
                                           'status': 'applied'}) + '\n', encoding='utf-8')
        surviving = {job['url'] for group in self.queue()['pending'] for job in group['jobs']}
        self.assertNotIn('https://example.test/a', surviving)
        self.assertIn('https://example.test/a2', surviving)
        self.assertEqual(self.queue()['applied'][0]['jobs'][0]['url'], 'https://example.test/a')

    def test_corrupt_tail_blocks_writes_without_rewriting_evidence(self):
        group = self.group_for('req-a')
        self.ledger.write_bytes(b'{"url":')
        with self.assertRaisesRegex(ValueError, 'line 1'):
            applications.append_decision(self.ledger, group, 'applied')
        self.assertEqual(self.ledger.read_bytes(), b'{"url":')

    def test_concurrent_decisions_produce_complete_append_only_events(self):
        group = self.group_for('req-a')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda number: applications.append_decision(
                self.ledger, group, 'skipped', str(number)), range(8)))
        events = applications.read_events(self.ledger)
        self.assertEqual(len(events), 8)
        self.assertEqual({event['reason'] for event in events}, {str(n) for n in range(8)})

    def test_history_survives_closure_and_aging_out(self):
        group = self.group_for('req-a')
        applications.append_decision(self.ledger, group, 'applied')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET closed_at='closed'")
        state = applications.queue(self.db, self.ledger, self.now + timedelta(days=30))
        self.assertEqual(state['pending'], [])
        self.assertEqual(state['backlog'], [])
        self.assertEqual(state['applied'][0]['title'], group['title'])


class BacklogTests(ApplicationsTests):
    """A three-day queue is a working rhythm, not an expiry date."""

    def test_an_undecided_job_moves_to_backlog_instead_of_vanishing(self):
        state = self.queue()
        backlog_ids = {job['source_job_id'] for g in state['backlog'] for job in g['jobs']}
        self.assertEqual(backlog_ids, {'req-c'}, 'the four-day-old posting was lost')
        self.assertNotIn('req-c', {job['source_job_id']
                                   for g in state['pending'] for job in g['jobs']})

    def test_the_backlog_is_still_decidable(self):
        applications.append_decision(self.ledger, self.group_for('req-c', 'backlog'), 'skipped')
        self.assertEqual(self.queue()['backlog'], [])
        self.assertEqual(self.queue()['skipped'][0]['jobs'][0]['source_job_id'], 'req-c')

    def test_a_closed_job_is_in_neither_queue(self):
        everywhere = {job['source_job_id'] for bucket in ('pending', 'backlog')
                      for g in self.queue()[bucket] for job in g['jobs']}
        self.assertNotIn('req-d', everywhere)

    def test_the_backlog_obeys_the_same_exclusions_as_the_queue(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET title='Senior RTL Engineer' WHERE source_job_id='req-c'")
        self.assertEqual(self.queue()['backlog'], [])


class HttpTests(ApplicationsTests):
    def test_description_survives_store_html_deduplication(self):
        from jobdisco import store
        text = 'Design RTL and verify hardware.'
        raw = store.slim({'descriptionPlain': text, 'descriptionHtml': '<p>' + text + '</p>'})
        self.assertNotIn('descriptionHtml', raw)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE jobs SET raw=? WHERE url=?',
                       (json.dumps(raw), 'https://example.test/a'))
        server = review.make_server(self.db, self.ledger, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        with urlopen(f'http://127.0.0.1:{server.server_port}/api/job?url=https://example.test/a') as response:
            self.assertEqual(json.load(response)['description'], text)

    def test_an_idle_connection_does_not_stop_the_server(self):
        """A browser opens speculative sockets and sends nothing on them.

        Requests used to be served one at a time, and reading a request line
        that never arrives does not return, so one such socket hung the review
        service until it was killed.
        """
        server = review.make_server(self.db, self.ledger, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        idle = socket.create_connection(('127.0.0.1', server.server_port))
        self.addCleanup(idle.close)
        with urlopen(f'http://127.0.0.1:{server.server_port}/api/queue', timeout=10) as response:
            self.assertIn('pending', json.load(response))

    def test_history_does_not_show_a_later_requisitions_description(self):
        """The decision was about one opening; the address now advertises another.

        The panel asked for whatever row holds that URL, so an applied item was
        illustrated with the prose of the posting that replaced it -- which
        reads as though the application was made against something it never was.
        """
        url = 'https://example.test/a'
        applications.append_decision(self.ledger, self.group_for('req-a'), 'applied')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET source_job_id='req-later', raw=? WHERE url=?",
                       (json.dumps({'description': 'A different opening entirely.'}), url))
        applied = self.queue()['applied'][0]
        server = review.make_server(self.db, self.ledger, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        root = f'http://127.0.0.1:{server.server_port}'
        with urlopen(f'{root}/api/job?url={url}&id={applied["id"]}') as response:
            replaced = json.load(response)
        self.assertTrue(replaced['replaced'])
        self.assertEqual(replaced['description'], '')
        # The listing that still holds its requisition answers as before.
        with urlopen(f'{root}/api/job?url=https://example.test/a2&id={applied["id"]}') as response:
            self.assertIn('Design hardware', json.load(response)['description'])

    def serve(self):
        server = review.make_server(self.db, self.ledger, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_port}'

    def test_a_posting_that_moved_provider_is_not_reported_as_replaced(self):
        """A posting found again on the company's own board keeps its URL.

        Its key changes with the provider, which is what told the panel it had
        been replaced -- so the description of a job the applicant had actually
        applied to was withheld from the history of that application.
        """
        url = 'https://example.test/b'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET provider_key='jsearch', source_job_id='js-1' "
                       "WHERE url=?", (url,))
        found = next(group for group in self.queue()['pending']
                     if any(job['url'] == url for job in group['jobs']))
        applications.append_decision(self.ledger, found, 'applied')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET provider_key='greenhouse', source_job_id='req-b' "
                       "WHERE url=?", (url,))
        applied = self.queue()['applied'][0]
        root = self.serve()
        query = (f'url={url}&id={applied["id"]}&provider=jsearch'
                 f'&title={quote(applied["title"])}')
        with urlopen(f'{root}/api/job?{query}') as response:
            body = json.load(response)
        self.assertNotIn('replaced', body)
        self.assertIn('Design hardware', body['description'])

    def test_a_plain_description_is_not_handed_to_an_html_parser(self):
        """`<T>` is a type, and the parser was deleting it without saying so."""
        url = 'https://example.test/a'
        plain = 'Write C++ with vector<T> and verify int<32> buses.'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE jobs SET raw=? WHERE url=?',
                       (json.dumps({'job_description': plain}), url))
        root = self.serve()
        with urlopen(f'{root}/api/job?url={url}') as response:
            self.assertEqual(json.load(response)['description'], plain)

    def test_a_description_that_is_markup_is_still_rendered_as_text(self):
        url = 'https://example.test/a'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE jobs SET raw=? WHERE url=?',
                       (json.dumps({'job_description': '<p>Design hardware.</p><ul><li>RTL</li></ul>'}),
                        url))
        root = self.serve()
        with urlopen(f'{root}/api/job?url={url}') as response:
            body = json.load(response)
        self.assertNotIn('<p>', body['description'])
        self.assertIn('Design hardware.', body['description'])

    def test_a_decision_does_not_rebuild_the_queue_it_was_just_given(self):
        """Building it replays the ledger and reads every open posting.

        A decision paid for that twice -- once to find the group to write, once
        through the refresh that follows -- and on a synthetic two thousand
        postings one build measured 460 ms here. The ledger and the index are
        files; when they last changed answers whether the answer still holds.
        """
        builds = []
        real_queue = applications.queue

        def counted(*args, **kwargs):
            builds.append(1)
            return real_queue(*args, **kwargs)

        with patch.object(review.applications, 'queue', counted):
            root = self.serve()
            with urlopen(root + '/api/queue') as response:
                state = json.load(response)
            self.assertEqual(len(builds), 1)
            with urlopen(root + '/api/queue') as response:
                json.load(response)
            self.assertEqual(len(builds), 1, 'nothing changed, and it built the queue again')

            payload = json.dumps({'id': state['pending'][0]['id'], 'status': 'applied'}).encode()
            request = Request(root + '/api/decision', data=payload,
                              headers={'Content-Type': 'application/json',
                                       'X-Review-Token': state['token']})
            with urlopen(request) as response:
                json.load(response)
            self.assertEqual(len(builds), 1, 'the decision rebuilt what it had just been given')

            with urlopen(root + '/api/queue') as response:
                after = json.load(response)
            # The decision is moved into the cached queue rather than paid for
            # with a second build; see test_a_decision_moves_its_group_...
            self.assertEqual(len(builds), 1, 'the decision was rebuilt rather than recorded')
            self.assertEqual(len(after['applied']), 1, 'the ledger changed and the queue did not')

    def test_a_pass_that_is_still_running_reaches_the_queue(self):
        """A commit in WAL mode lands in the sidecar, not in the database file.

        The queue is cached against when its inputs last changed, and the
        index's own timestamp and length do not move until a checkpoint --
        which a pass reaches only when it closes its connection, at the end.
        Everything a running pass had found was invisible to this page until
        then, and Refresh answered out of the cache with nothing to say so.
        """
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('PRAGMA journal_mode=WAL')
        root = self.serve()
        with urlopen(root + '/api/queue') as response:
            before = len(json.load(response)['pending'])

        collecting = sqlite3.connect(self.db)
        self.addCleanup(collecting.close)
        collecting.execute('PRAGMA journal_mode=WAL')
        collecting.execute(
            'INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('https://example.test/e', 'sample', 'Verification Engineer', 'AUSTIN',
             'req-e', (self.now - timedelta(hours=1)).isoformat(), None, 'direct', 80,
             None, json.dumps({'description': 'Design hardware.'}),
             (self.now - timedelta(hours=1)).isoformat()))
        # The pass commits each source as it finishes and keeps its connection.
        collecting.commit()

        with urlopen(root + '/api/queue') as response:
            after = json.load(response)['pending']
        self.assertEqual(len(after), before + 1,
                         'the page could not see a pass that was still running')
        self.assertIn('https://example.test/e',
                      {job['url'] for group in after for job in group['jobs']})

    def test_http_decisions_require_token_and_replay_on_refresh(self):
        server = review.make_server(self.db, self.ledger, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        root = f'http://127.0.0.1:{server.server_port}'
        with urlopen(root + '/api/queue') as response:
            state = json.load(response)
        payload = json.dumps({'id': state['pending'][0]['id'], 'status': 'applied'}).encode()
        with self.assertRaises(HTTPError) as rejected:
            urlopen(Request(root + '/api/decision', data=payload))
        self.assertEqual(rejected.exception.code, 403)
        with urlopen(Request(root + '/api/decision', data=payload,
                             headers={'X-Review-Token': state['token']})) as response:
            self.assertEqual(json.load(response)['status'], 'applied')
        with urlopen(root + '/api/queue') as response:
            refreshed = json.load(response)
        self.assertEqual(len(refreshed['pending']), len(state['pending']) - 1)
        self.assertEqual(len(refreshed['applied']), 1)

    def test_a_decision_moves_its_group_without_rebuilding_the_queue(self):
        """Clicking Skip or Mark applied used to cost a full rebuild -- about 28
        seconds live -- before the posting left the list. The cached queue is
        moved in place instead, and must say exactly what a full replay says."""
        server = review.make_server(self.db, self.ledger, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        root = f'http://127.0.0.1:{server.server_port}'
        with urlopen(root + '/api/queue') as response:
            state = json.load(response)
        decisions = [(state['pending'][0]['id'], 'applied'), (state['pending'][1]['id'], 'skipped'),
                     (state['backlog'][0]['id'], 'skipped')]
        builds = []
        real = applications.queue
        with patch.object(applications, 'queue', side_effect=lambda *a, **k: builds.append(1) or real(*a, **k)):
            for ident, status in decisions:
                body = json.dumps({'id': ident, 'status': status, 'reason': 'fixture'}).encode()
                with urlopen(Request(root + '/api/decision', data=body,
                                     headers={'X-Review-Token': state['token']})) as response:
                    self.assertEqual(json.load(response)['status'], status)
            with urlopen(root + '/api/queue') as response:
                moved = json.load(response)
        self.assertEqual(builds, [], 'a decision still rebuilt the whole queue')
        replayed = review.slim(real(self.db, self.ledger))

        def shape(queue):
            return {name: [(g['id'], sorted(j['url'] for j in g['jobs']), g.get('reason'))
                           for g in queue[name]] for name in ('pending', 'backlog', 'applied', 'skipped')}
        self.assertEqual(shape(moved), shape(replayed))
        self.assertEqual([g['at'] for g in moved['skipped']], [g['at'] for g in replayed['skipped']])

    def test_a_decision_made_while_the_index_changed_rebuilds_in_full(self):
        server = review.make_server(self.db, self.ledger, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        root = f'http://127.0.0.1:{server.server_port}'
        with urlopen(root + '/api/queue') as response:
            state = json.load(response)
        real = applications.append_decision

        def and_a_pass_commits(*args, **kwargs):
            written = real(*args, **kwargs)
            with closing(sqlite3.connect(self.db)) as db, db:
                db.execute("""INSERT INTO jobs VALUES ('https://example.test/e', 'sample',
                    'Fresh Engineer', 'E', 'req-e', ?, NULL, 'direct', 80, NULL, '{}', ?)""",
                           (self.now.isoformat(), self.now.isoformat()))
            os.utime(self.db, ns=(1, os.stat(self.db).st_mtime_ns + 10**9))
            return written
        with patch.object(applications, 'append_decision', side_effect=and_a_pass_commits):
            body = json.dumps({'id': state['pending'][0]['id'], 'status': 'applied'}).encode()
            urlopen(Request(root + '/api/decision', data=body,
                            headers={'X-Review-Token': state['token']})).close()
        with urlopen(root + '/api/queue') as response:
            after = json.load(response)
        self.assertIn('https://example.test/e',
                      {job['url'] for group in after['pending'] for job in group['jobs']},
                      'the cache was patched over a change it had not read')

    def test_a_backlog_item_can_be_decided_over_http(self):
        server = review.make_server(self.db, self.ledger, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        root = f'http://127.0.0.1:{server.server_port}'
        with urlopen(root + '/api/queue') as response:
            state = json.load(response)
        self.assertTrue(state['backlog'], 'the backlog never reached the client')
        payload = json.dumps({'id': state['backlog'][0]['id'], 'status': 'skipped'}).encode()
        with urlopen(Request(root + '/api/decision', data=payload,
                             headers={'X-Review-Token': state['token']})) as response:
            self.assertEqual(json.load(response)['status'], 'skipped')


if __name__ == '__main__':
    unittest.main()
