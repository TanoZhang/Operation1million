"""Employer policy and publisher noise must not bypass review decisions."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import re
import tempfile
import unittest
from unittest import mock

from jobdisco import applications, jsearch, store
from jobdisco.job_text import clean_title


class FilterPolicyTests(unittest.TestCase):
    def setUp(self):
        self.rules = jsearch.load_plan()[0]['filter']

    def matches_keep(self, title):
        return any(re.search(p, title, re.I) for p in self.rules['keep_title_patterns'])

    def test_explicit_seniority_is_hard_rejected_before_keep(self):
        for title in ('Senior RTL Engineer', 'Sr. FPGA Engineer', 'Sr ASIC Engineer',
                      'ASIC Engineer, Sr.', 'SENIOR Design Verification Engineer',
                      'Director of RTL Design', 'FPGA Engineering Manager'):
            with self.subTest(title=title):
                row = {'title': title, 'raw': {'description': 'RTL ASIC FPGA UVM ' * 200}}
                self.assertEqual(jsearch.rejection_reason(row, self.rules), 'excluded')
        for title in ('Staff FPGA Engineer', 'Principal RTL Engineer', 'SRAM Design Engineer'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.excluded(title, self.rules))
        self.assertEqual(jsearch.rejection_reason({
            'title': 'RTL Engineer', 'raw': {'description': 'Work with Senior engineers and a Manager.'}
        }, self.rules), '')

    def test_unrelated_titles_are_hard_rejected_even_with_trade_evidence(self):
        titles = (
            'Silicon Photonics Engineer', 'Photonic Engineer', 'Photonics Engineer',
            'Optical Engineer', 'Optics Engineer', 'Optoelectronic Engineer',
            'Optoelectronics Engineer', 'Laser Engineer', 'Process Engineer',
            'Semiconductor Process Integration Engineer', 'Semiconductor Process Engineer',
            'Silicon Device Engineer', 'Device Integration Engineer', 'Silicon Yield Engineer',
            'Yield Engineer', 'Fab Engineer', 'Fabrication Engineer', 'Lithography Engineer',
            'Thin Film Engineer', 'Etch Engineer', 'Deposition Engineer',
            'Materials Engineer', 'Materials Scientist', 'Chemical Engineer',
            'Battery Engineer', 'Electrochemical Engineer', 'Electrochemistry Scientist',
            'Mechanical Engineer', 'Thermal Engineer', 'Structural Engineer',
            'Civil Engineer', 'Construction Engineer', 'Manufacturing Engineer',
            'Industrial Engineer', 'FPGA Photonics Engineer',
        )
        for title in titles:
            with self.subTest(title=title):
                row = {'title': title, 'raw': {'description': 'RTL ASIC FPGA UVM ' * 200}}
                self.assertEqual(jsearch.rejection_reason(row, self.rules), 'excluded')

    def test_device_is_only_rejected_as_an_explicit_fab_phrase(self):
        """`device` is not a fab word; the phrases built around it are."""
        for title in ('Semiconductor Device Engineer', 'Device Integration Engineer',
                      'Device Physics Engineer', 'Device Process Engineer',
                      'Device Characterization Engineer', 'Principal Process/Device Engineer',
                      'NAND Cell Device Engineer', 'Foundry Device Engineer',
                      'CMOS Device Integration Team'):
            with self.subTest(title=title):
                self.assertTrue(jsearch.excluded(title, self.rules))
        # Each of these reads as the trade to someone in it, and a bare
        # `device engineer` rule took all of them to reach the fab postings.
        for title in ('Device Validation Engineer', 'Silicon Device Validation Engineer',
                      'Embedded Device Engineer', 'PCIe Device Engineer',
                      'Hardware Device Engineer', 'Device Driver Engineer',
                      'Device Engineer', 'Staff Device Engineer'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.excluded(title, self.rules))

    def test_evidence_titles_are_admitted_only_by_their_description(self):
        """RF is answered by the posting's text, in neither direction by its name."""
        for title in ('RF Engineer', 'RFIC Engineer', 'RF IC Engineer',
                      'Microwave Engineer', 'Antenna Engineer',
                      'RFIC Digital Verification Engineer'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.excluded(title, self.rules), 'no longer a hard reject')
                self.assertTrue(jsearch.needs_evidence(title, self.rules))
                trade = {'title': title,
                         'raw': {'description': 'RTL ASIC FPGA UVM SystemVerilog ' * 200}}
                self.assertEqual(jsearch.rejection_reason(trade, self.rules), '')
                # Silence is not evidence. This is the one place the filter is
                # stricter than the score, which keeps a short description.
                for raw in ({}, {'description': 'Antenna tuning and spectrum planning.'}):
                    self.assertEqual(
                        jsearch.rejection_reason({'title': title, 'raw': raw}, self.rules),
                        'no_evidence')

    def test_an_evidence_title_cannot_escape_the_check_through_a_keep(self):
        """The check runs before the keeps, or the name would answer for itself."""
        row = {'title': 'RFIC Digital Design Engineer', 'raw': {'description': 'Short.'}}
        self.assertTrue(self.matches_keep(row['title']))
        self.assertEqual(jsearch.rejection_reason(row, self.rules), 'no_evidence')

    def test_software_survives_when_the_title_names_low_level_work(self):
        for title in ('Embedded Software Engineer', 'Firmware Software Engineer',
                      'Device Driver Software Engineer', 'SoC Software Engineer',
                      'Silicon Validation Software Engineer', 'FPGA Software Engineer',
                      'Hardware Software Co-Design Engineer'):
            with self.subTest(title=title):
                row = {'title': title, 'raw': {'description': 'RTL ASIC FPGA UVM ' * 200}}
                self.assertEqual(jsearch.rejection_reason(row, self.rules), '')
        # Nothing in these names the hardware underneath, so they still go.
        for title in ('Software Engineer', 'Software Engineer, Machine Learning',
                      'Full Stack Software Engineer', 'Software Development Engineer II'):
            with self.subTest(title=title):
                row = {'title': title, 'raw': {'description': 'RTL ASIC FPGA UVM ' * 200}}
                self.assertEqual(jsearch.rejection_reason(row, self.rules), 'title_mismatch')

    def test_target_titles_are_not_hard_rejected(self):
        for title in ('Silicon Validation Engineer', 'Pre-Silicon Validation Engineer',
                      'SoC Validation Engineer', 'Hardware Design Engineer',
                      'FPGA Validation Engineer', 'Embedded FPGA Engineer',
                      'Device Driver Engineer', 'Process Control FPGA Engineer'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.excluded(title, self.rules))

    def test_explicit_titles_keep_without_scoring(self):
        for title in ('RTL Design Engineer', 'ASIC Design Engineer', 'FPGA Engineer',
                      'SoC Design Verification Engineer', 'Digital Design Engineer',
                      'Physical Design Engineer', 'Logic Design Engineer',
                      'Pre-Silicon Verification Engineer', 'Hardware Verification Engineer',
                      'Formal Verification Engineer', 'DFT Engineer', 'VLSI Engineer'):
            with self.subTest(title=title):
                self.assertTrue(self.matches_keep(title))
                with mock.patch.object(jsearch, 'relevance', side_effect=AssertionError('Scoring reached')):
                    self.assertEqual(jsearch.rejection_reason({'title': title}, self.rules), '')

    def test_generic_titles_do_not_bypass_scoring(self):
        for title in ('Silicon Validation Engineer', 'Pre-Silicon Validation Engineer',
                      'Hardware Validation Engineer', 'Test Engineer', 'Semiconductor Engineer',
                      'IC Engineer', 'Embedded Engineer', 'Firmware Engineer',
                      'Digital Marketing Engineer', 'Verification Engineer', 'Formal Engineer',
                      'Silicon Photonics Engineer'):
            with self.subTest(title=title):
                self.assertFalse(self.matches_keep(title))
        row = {'title': 'Silicon Validation Engineer', 'raw': {'description': 'Ordinary duties. ' * 200}}
        with mock.patch.object(jsearch, 'relevance', return_value=(0, [])) as score:
            self.assertEqual(jsearch.rejection_reason(row, self.rules), 'off_domain')
            score.assert_called_once()

    def test_employer_blacklist_precedes_explicit_keeps(self):
        for employer in ('Boeing', 'The Boeing Company', 'Lockheed Martin Corporation',
                         'Northrop Grumman', 'RTX', 'RTX Corporation', 'Raytheon',
                         'L3Harris Technologies', 'General Dynamics', 'BAE Systems',
                         'Leidos', 'CACI International', 'SAIC', 'Amentum', 'Peraton', 'Anduril-1'):
            for title in ('RTL Design Engineer', 'FPGA Engineer', 'ASIC Design Engineer'):
                with self.subTest(employer=employer, title=title):
                    row = {'title': title, 'company_name': employer}
                    self.assertEqual(jsearch.rejection_reason(row, self.rules), 'excluded_employer')

    def test_title_and_employer_patterns_do_not_scan_description(self):
        for employer in ('NVIDIA', 'Analog Devices', 'RTX Labs Research', 'SAIC Motor', 'Peratonics'):
            row = {'title': 'NVIDIA RTX FPGA Engineer', 'company_name': employer,
                   'raw': {'description': 'Boeing RF IC Engineer process device Photonics Engineer'}}
            with self.subTest(employer=employer):
                self.assertEqual(jsearch.rejection_reason(row, self.rules), '')


class TitleTests(unittest.TestCase):
    def test_relative_dates_and_known_location_do_not_change_identity(self):
        role = 'Senior ASIC Design Verification Engineer'
        for suffix in ('Posted a day ago', 'Posted 2 days ago', 'Posted today', 'Posted on 2026-09-18'):
            noisy = role + ' Minneapolis, Minnesota, United States of America ' + suffix
            self.assertEqual(clean_title(noisy, 'Minneapolis, Minnesota, US'), role)
        self.assertEqual(clean_title('New York Hardware Engineer'), 'New York Hardware Engineer')

    def test_employer_exclusions_precede_strong_title_and_cached_score(self):
        rules = jsearch.load_plan()[0]['filter']
        for employer in ('Lockheed Martin Corporation', 'Northrop Grumman', 'Anduril-1'):
            row = {'title': 'ASIC & FPGA Verification Engineer Stf - E4',
                   'company_name': employer, 'raw': {'employer_name': employer, 'relevance': {'confidence': 100}}}
            self.assertEqual(jsearch.rejection_reason(row, rules), 'excluded_employer')
            self.assertEqual(jsearch.relevance(row, rules)[0], 0)
            self.assertEqual(store.score_row(row['title'], row['raw']), 0)
        row = {'title': 'NVIDIA RTX FPGA Verification Engineer', 'company_name': 'NVIDIA'}
        self.assertFalse(jsearch.employer_excluded(row, rules))


class QueueRulesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = Path(temporary.name) / 'jobs.sqlite'
        self.ledger = Path(temporary.name) / 'applications.ndjson'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript('''CREATE TABLE companies(company_key TEXT, name TEXT);
                INSERT INTO companies VALUES ('sample', 'Sample');
                CREATE TABLE jobs(url TEXT, company_key TEXT, title TEXT, location TEXT,
                    source_job_id TEXT,
                    first_seen TEXT, posted_at TEXT, provider_key TEXT, relevance INTEGER,
                    closed_at TEXT, raw TEXT);''')
            # A real JSearch row always carries the provider's job id. It is what
            # keeps a decision attached when the title gains "Posted 2 days ago"
            # and the url is rewritten underneath it.
            db.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 100, NULL, ?)',
                       ('https://example.test/job', 'sample', 'RTL Engineer', 'Minneapolis, Minnesota, US',
                        'provider-req-1', datetime.now(timezone.utc).isoformat(), 'jsearch', '{}'))

    def queue(self):
        return applications.queue(self.db, self.ledger)

    def test_existing_high_score_defense_employer_is_hidden(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE companies SET name='Anduril-1'")
            db.execute('UPDATE jobs SET relevance=100')
        self.assertEqual(self.queue()['pending'], [])

    def test_old_noisy_snapshot_survives_date_and_url_changes(self):
        role = 'ASIC Design Verification Engineer'
        old_title = role + ' Minneapolis, Minnesota, United States of America Posted a day ago'
        group = self.queue()['pending'][0]
        group['title'] = old_title
        group['jobs'][0]['location'] = 'Minneapolis, Minnesota, US'
        applications.append_decision(self.ledger, group, 'skipped', 'Already reviewed')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET title=?, location='Minneapolis, Minnesota, US', url=url || '-changed'",
                       (role + ' Minneapolis, Minnesota, United States of America Posted 2 days ago',))
        state = self.queue()
        self.assertEqual(state['pending'], [])
        self.assertEqual(state['skipped'][0]['title'], role)
        applications.append_decision(self.ledger, state['skipped'][0], 'pending')
        self.assertEqual(len(self.queue()['pending']), 1)
