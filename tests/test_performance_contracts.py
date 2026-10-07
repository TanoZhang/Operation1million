import copy, json, os, tempfile, unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from operation1million import applications, review, jsearch, resume_fit
from tests.test_resume_fit import profile

class PerformanceContracts(unittest.TestCase):

    def test_warm_queue_reads_unchanged_ledgers_once_and_observes_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ledger = root / 'applications.ndjson'
            state = {k: [] for k in review.STATUSES}
            state['applied'] = [{'id': 'g', 'company': 'Example', 'title': 'RTL Engineer', 'confidence': 90, 'jobs': [{'url': 'https://example.test/job'}]}]
            with patch.object(applications, 'queue', side_effect=lambda *a: copy.deepcopy(state)), patch.object(applications, 'read_links', wraps=applications.read_links) as links, patch.object(applications, 'read_outcomes', wraps=applications.read_outcomes) as outcomes:
                server = review.make_server(root / 'db', ledger, 0)
                try:
                    for _ in range(10):
                        server.current_queue()
                    self.assertEqual((links.call_count, outcomes.call_count), (1, 1))
                    applications.append_link(applications.links_path(ledger), 'https://example.test/job', 'https://example.test/official')
                    applications.append_outcome(applications.outcomes_path(ledger), 'g', 'passed')
                    group = server.current_queue()['applied'][0]
                    self.assertEqual(group['outcome'], 'passed')
                    self.assertEqual(group['jobs'][0]['official_link'], 'https://example.test/official')
                    path = applications.outcomes_path(ledger)
                    stamp = path.stat()
                    replacement = root / 'replacement'
                    replacement.write_text(path.read_text().replace('passed', 'xxxxxx'), encoding='utf-8')
                    os.utime(replacement, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                    replacement.replace(path)
                    self.assertNotIn('outcome', server.current_queue()['applied'][0])
                    applications.links_path(ledger).unlink()
                    self.assertNotIn('official_link', server.current_queue()['applied'][0]['jobs'][0])
                finally:
                    server.server_close()

    def test_collector_parses_supported_software_jd_once_per_assessment(self):
        rules = dict(jsearch.load_plan()[0]['filter'], _resume_fit_profile=profile())
        row = {'title': 'Software Engineer', 'raw': {'description': 'Design and verify RTL.'}}
        with patch.object(resume_fit, 'sections', wraps=resume_fit.sections) as sections:
            self.assertEqual(jsearch.rejection_reason(row, rules), '')
            self.assertEqual(sections.call_count, 1)
            row['raw']['description'] = 'Design building water systems.'
            self.assertEqual(jsearch.rejection_reason(row, rules), 'resume_no_supported_core_duties')
            self.assertEqual(sections.call_count, 2)

    def test_detail_cache_decodes_only_inventory_urls(self):
        import sqlite3
        from types import SimpleNamespace
        from operation1million import job_details
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'db'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE jobs(url TEXT PRIMARY KEY,provider_key TEXT,raw TEXT)')
                db.executemany('INSERT INTO jobs VALUES (?,?,?)', [(f'https://example.test/{i}', 'workday', '{}') for i in range(6)])
            collector = SimpleNamespace(jobs=[{'url': 'https://example.test/0', 'title': 'RTL Engineer', 'raw': {}}])
            with patch.object(job_details, 'candidate', return_value=False), patch.object(job_details.json, 'loads', wraps=json.loads) as loads:
                job_details.enrich_inventory(collector, path, reader=None, provider='workday', metadata='detail', fields=(), evidence='description', skip_full=True)
                self.assertEqual(loads.call_count, 1)

    def test_citizenship_preferred_sections_are_parsed_once(self):
        rules = jsearch.load_plan()[0]['filter']
        text = 'Design RTL.\nPreferred qualifications\nMust be a U.S. citizen.'
        with patch.object(jsearch, 'preferred_spans', wraps=jsearch.preferred_spans) as spans:
            self.assertFalse(jsearch.us_person_required(text, rules))
            self.assertEqual(spans.call_count, 1)

    def test_alias_audit_reports_but_never_merges_domain_candidates(self):
        from operation1million import company_audit, employers
        rows = [{'name': 'Renesas Electronics', 'website': 'https://www.renesas.test'}, {'name': 'Renesas', 'website': 'https://renesas.test'}, {'name': 'Unconfirmed Entity', 'website': 'https://renesas.test'}, {'name': 'Different Company', 'website': {'bad': 'value'}}]
        before = dict(employers.ALIASES)
        result = company_audit.report(rows)
        self.assertEqual(result['identities'], 3)
        self.assertEqual(result['aliases'][0]['display'], 'Renesas')
        self.assertEqual(result['domain_candidates'], [{'reported_domain': 'renesas.test', 'identities': ['renesas', 'unconfirmed entity']}])
        self.assertEqual(result, company_audit.report(reversed(rows)))
        self.assertEqual(employers.ALIASES, before)

    def test_side_ledger_write_during_read_is_not_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ledger = root / 'applications.ndjson'
            state = {key: [] for key in review.STATUSES}
            state['applied'] = [{'id': 'g', 'company': 'Example', 'title': 'Engineer', 'confidence': 90, 'jobs': [{'url': 'https://example.test/job'}]}]
            reader = applications.read_outcomes
            calls = []

            def racing_read(path):
                value = reader(path)
                calls.append(1)
                if len(calls) == 1:
                    applications.append_outcome(path, 'g', 'passed')
                return value
            with patch.object(applications, 'queue', return_value=state), patch.object(applications, 'read_outcomes', side_effect=racing_read):
                server = review.make_server(root / 'db', ledger, 0)
                try:
                    self.assertNotIn('outcome', server.current_queue()['applied'][0])
                    self.assertEqual(server.current_queue()['applied'][0]['outcome'], 'passed')
                    server.current_queue()
                    self.assertEqual(len(calls), 2)
                finally:
                    server.server_close()

    def test_assessment_reuse_does_not_survive_profile_change_or_override_hard_reject(self):
        row = {'title': 'Software Engineer', 'raw': {'description': 'Design and verify RTL.'}}
        rules = dict(jsearch.load_plan()[0]['filter'], _resume_fit_profile=profile())
        self.assertEqual(jsearch.rejection_reason(row, rules), '')
        rules['_resume_fit_profile']['families'] = [{'id': 'other', 'evidence': 'Other project', 'all': ['unrelated duty']}]
        self.assertEqual(jsearch.rejection_reason(row, rules), 'resume_no_supported_core_duties')
        row['raw']['description'] = 'Design and verify RTL. Minimum 10 years of experience required.'
        with patch.object(resume_fit, 'assess', side_effect=AssertionError('Hard rejects must run first')):
            self.assertEqual(jsearch.rejection_reason(row, rules), 'required_experience_over_2_years')

    def test_company_audit_reads_inventory_and_writes_only_requested_report(self):
        import sqlite3
        from operation1million import company_audit
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'db'
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript('CREATE TABLE companies(company_key TEXT,name TEXT); CREATE TABLE jobs(company_key TEXT,raw TEXT,closed_at TEXT);')
                db.execute('INSERT INTO companies VALUES (?,?)', ('example', 'Example'))
                db.execute('INSERT INTO jobs VALUES (?,?,NULL)', ('example', json.dumps({'employer_website': 'https://example.test'})))
            before = path.read_bytes()
            report = company_audit.inspect(path)
            company_audit.write(root / 'report.json', report)
            self.assertEqual(json.loads((root / 'report.json').read_text()), report)
            self.assertEqual(report['identities'], 1)
            self.assertEqual(path.read_bytes(), before)
