"""Synthetic skill profiles exercise mandatory depth and transferable evidence."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from operation1million import applications, jsearch, resume_fit


def profile():
    return {'version': 1, 'families': [
        {'id': 'controls', 'evidence': 'Control project', 'all': [r'\bPLC\b', r'commission|PID']},
        {'id': 'digital', 'evidence': 'RTL project', 'all': [r'\bRTL\b', r'design|verif']},
    ], 'gaps': [
        {'id': 'network_depth', 'evidence': 'No industrial-network practice',
         'scope': 'requirements', 'all': [r'hands.on', r'EtherCAT']},
        {'id': 'expert_depth', 'evidence': 'Project exposure is not specialist experience',
         'scope': 'requirements', 'all': [r'expert', r'PLC']},
    ]}


class ResumeFitTests(unittest.TestCase):
    def test_exposure_is_not_mandatory_expertise(self):
        row = {'title': 'Control Engineer', 'raw': {'description':
            'Commission PLC PID loops.\nRequired qualifications\nExpert PLC programming and hands-on EtherCAT experience.'}}
        result = resume_fit.assess(row, profile())
        self.assertEqual(result['verdict'], 'reject')
        self.assertEqual(result['evidence'], ['network_depth'])

    def test_preferred_gaps_do_not_reject_supported_work(self):
        row = {'title': 'Engineer', 'raw': {'description':
            'Commission PLC PID loops.\nPreferred qualifications\nExpert PLC programming and hands-on EtherCAT experience.'}}
        self.assertEqual(resume_fit.assess(row, profile())['verdict'], 'keep')

    def test_preferred_words_and_metadata_are_not_core_duties(self):
        row = {'title': 'Engineer', 'raw': {'description': 'Design building water systems.',
               'preferred_qualifications': 'RTL design PLC PID', 'discovery_queries': ['RTL design']}}
        self.assertEqual(resume_fit.assess(row, profile())['verdict'], 'reject')

    def test_missing_and_qualification_only_jd_are_unknown(self):
        for raw in ({}, {'preferred_qualifications': 'RTL design'}, {'requirements': 'Engineering degree'}):
            self.assertEqual(resume_fit.assess({'title': 'Engineer', 'raw': raw}, profile())['verdict'], 'unknown')
        self.assertEqual(resume_fit.assess({'title': 'RTL Design Intern', 'raw': {
            'description': 'RTL Design Intern at Example'}}, profile())['verdict'], 'unknown')

    def test_separate_required_fields_and_resumed_duties(self):
        row = {'title': 'Engineer', 'raw': {'description':
            'Required qualifications\nSome training.\nResponsibilities\nDesign and verify RTL.',
            'requirements': 'Hands-on EtherCAT required.'}}
        self.assertEqual(resume_fit.assess(row, profile())['verdict'], 'reject')

    def test_intake_and_live_review_apply_same_profile_without_marking_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'jobs.sqlite'
            ledger = root / 'applications.ndjson'
            resume_fit.profile_path(ledger).write_text(json.dumps(profile()), encoding='utf-8')
            now = datetime.now(timezone.utc).isoformat()
            cases = [('supported', 'Design and verify RTL.'), ('unknown', ''),
                     ('unsupported', 'Design building water systems.')]
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript('''CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);
                    INSERT INTO companies VALUES ('example', 'Example');
                    CREATE TABLE jobs(url TEXT PRIMARY KEY, company_key TEXT, title TEXT, location TEXT,
                        source_job_id TEXT, first_seen TEXT, posted_at TEXT, provider_key TEXT,
                        relevance REAL, closed_at TEXT, raw TEXT, last_seen TEXT);''')
                for ident, prose in cases:
                    db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                        ('https://example.test/'+ident, 'example', 'RTL Engineer', 'Austin', ident,
                         now, None, 'example', 95, None, json.dumps({'description': prose}), now))
            rules = dict(jsearch.load_plan()[0]['filter'], _resume_fit_profile=profile())
            self.assertEqual(jsearch.rejection_reason({'title': 'RTL Engineer',
                'raw': {'description': cases[2][1]}}, rules), 'resume_no_supported_core_duties')
            state = applications.queue(path, ledger)
            ids = {j['source_job_id'] for g in state['pending']+state['backlog'] for j in g['jobs']}
            self.assertEqual(ids, {'supported', 'unknown'})
            self.assertFalse(ledger.exists())
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 3)

    def test_profile_reload_and_invalid_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'profile.json'
            self.assertIsNone(resume_fit.load(path))
            path.write_text(json.dumps(profile()), encoding='utf-8')
            self.assertEqual(resume_fit.load(path)['version'], 1)
            path.write_text('{"version":2}', encoding='utf-8')
            with self.assertRaises(ValueError):
                resume_fit.load(path)

    def test_private_transfer_evidence_can_admit_software_without_chip_vocabulary(self):
        rules = {'_resume_fit_profile': profile()}
        row = {'title': 'Software Engineer', 'raw': {'description': 'Commission PLC PID loops.'}}
        self.assertEqual(jsearch.software_jd_rejection(row, rules), '')
        row['raw'] = {}
        self.assertEqual(jsearch.software_jd_rejection(row, rules), '')
        row['raw'] = {'description': 'Build online shopping carts.'}
        self.assertEqual(jsearch.software_jd_rejection(row, rules), 'no_vlsi_evidence')
