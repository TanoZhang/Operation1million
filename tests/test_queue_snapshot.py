"""A restart can reuse a queue only when all authoritative inputs still match."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from jobdisco import review, queue_snapshot
from jobdisco.queue_snapshot import QueueSnapshot


def empty():
    return {name: [] for name in ('pending', 'backlog', 'applied', 'skipped')}


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.ledger = Path(folder.name)/'applications.ndjson'
        self.db = Path(folder.name)/'jobs.sqlite'

    def server(self):
        server = review.make_server(self.db, self.ledger, port=0)
        self.addCleanup(server.server_close)
        return server

    def test_restart_restores_without_rebuilding(self):
        with patch.object(review.applications, 'queue', side_effect=lambda *args: empty()) as build:
            self.assertEqual(self.server().current_queue(), empty())
            self.assertEqual(self.server().current_queue(), empty())
            self.assertEqual(build.call_count, 1)

    def test_ledger_or_index_changes_force_rebuild(self):
        with patch.object(review.applications, 'queue', side_effect=lambda *args: empty()) as build:
            self.server().current_queue()
            self.ledger.write_text('\n', encoding='utf-8')
            self.server().current_queue()
            self.db.write_bytes(b'new database content')
            self.server().current_queue()
            self.assertEqual(build.call_count, 3)

    def test_corrupted_snapshot_is_disposable(self):
        with patch.object(review.applications, 'queue', side_effect=lambda *args: empty()) as build:
            self.server().current_queue()
            self.ledger.with_name('review_queue.cache.json').write_text('{truncated', encoding='utf-8')
            self.server().current_queue()
            self.assertEqual(build.call_count, 2)

    def test_code_date_rules_wal_manual_links_signature_changes_invalidate(self):
        store = QueueSnapshot(self.ledger, self.db)
        signature = store.signature(['ledger', 'db', 'wal', 'date', 'rules', 'manual'], 'links')
        store.save(signature, empty())
        self.assertEqual(store.load(signature), empty())
        for index in range(6):
            key = ['ledger', 'db', 'wal', 'date', 'rules', 'manual']; key[index] = 'changed'
            self.assertIsNone(store.load(store.signature(key, 'links')))
        self.assertIsNone(store.load(store.signature(['ledger', 'db', 'wal', 'date', 'rules', 'manual'], 'changed')))
        store.identity[-1] = 'changed code'
        self.assertIsNone(store.load(store.signature(['ledger', 'db', 'wal', 'date', 'rules', 'manual'], 'links')))

    def test_cache_write_failure_does_not_break_queue(self):
        with patch.object(review.applications, 'queue', return_value=empty()), patch.object(queue_snapshot.tempfile, 'NamedTemporaryFile', side_effect=PermissionError('cache write refused')):
            self.assertEqual(self.server().current_queue(), empty())
