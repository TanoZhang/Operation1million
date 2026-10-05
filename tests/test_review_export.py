"""The review page's sorts and its one-key Excel export, asked for 2026-10-01.

The export writes what the page is showing, in its order, to one workbook
that each export replaces; nothing is opened and no second file is left.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import xml.dom.minidom
import zipfile

from jobdisco import export, review

ROOT = Path(__file__).resolve().parents[1]


def sheet_rows(path):
    with zipfile.ZipFile(path) as book:
        for name in book.namelist():
            xml.dom.minidom.parseString(book.read(name))
        sheet = book.read('xl/worksheets/sheet1.xml').decode('utf-8')
        links = book.read('xl/worksheets/_rels/sheet1.xml.rels').decode('utf-8')
    rows = []
    for row in re.findall(r'<row r="\d+">(.*?)</row>', sheet):
        rows.append(re.findall(r'<t xml:space="preserve">(.*?)</t>|<v>(.*?)</v>', row))
    return [[text or number for text, number in row] for row in rows], links


GROUP = {'id': 'g1', 'company': 'A & B Semiconductor', 'title': 'RTL <Design> Engineer', 'confidence': 62,
         'bucket': 2, 'early_career': False, 'less_related': False,
         'jobs': [{'url': 'https://x.example/job?id=1&src="a"', 'location': 'Austin, TX',
                   'posted_at': '2026-09-30', 'first_seen': '2026-09-30T10:00:00+00:00',
                   'provider_key': 'workday'}]}


class WorkbookTests(unittest.TestCase):
    def test_third_party_marker_has_explicit_site_exceptions(self):
        for url in ('https://www.linkedin.com/jobs/1', 'https://app.joinhandshake.com/jobs/1'):
            self.assertFalse(export.third_party_site({'url': url, 'provider_key': 'jsearch'}))
        self.assertTrue(export.third_party_site({'url': 'https://indeed.com/1', 'provider_key': 'jsearch'}))
        self.assertTrue(export.third_party_site({'url': 'https://linkedin.com.other.test/1', 'provider_key': 'jsearch'}))
        self.assertFalse(export.third_party_site({'url': 'https://company.test/1', 'provider_key': 'workday'}))

    def test_workbook_declares_the_excel_normal_style(self):
        with zipfile.ZipFile(BytesIO(export.workbook_bytes([]))) as book:
            styles = xml.dom.minidom.parseString(book.read('xl/styles.xml'))
        normal = styles.getElementsByTagName('cellStyle')
        self.assertEqual(len(normal), 1)
        self.assertEqual(normal[0].getAttribute('name'), 'Normal')
        self.assertEqual(normal[0].getAttribute('builtinId'), '0')

    def setUp(self):

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'review-queue.xlsx'

    def test_a_readable_workbook_with_a_link_per_listing(self):
        self.assertEqual(export.write(self.path, [('pending', GROUP)]), 1)
        rows, links = sheet_rows(self.path)
        self.assertEqual(rows[0][:3], ['Status', 'Company', 'Title'])
        self.assertEqual(rows[1][:3], ['To review', 'A &amp; B Semiconductor', 'RTL &lt;Design&gt; Engineer'])
        self.assertIn('62', rows[1])
        self.assertIn('Target="https://x.example/job?id=1&amp;src=&quot;a&quot;"', links)

    def test_each_export_replaces_the_one_file(self):
        export.write(self.path, [('pending', GROUP)])
        early = dict(GROUP, id='g2', early_career=True)
        export.write(self.path, [('backlog', early), ('applied', dict(GROUP, at='2026-09-29T00:00:00+00:00'))])
        rows, _ = sheet_rows(self.path)
        self.assertEqual([row[0] for row in rows[1:]], ['Early career', 'Applied'])
        self.assertEqual([path.name for path in self.path.parent.iterdir()], ['review-queue.xlsx'])

    def test_a_workbook_open_in_excel_is_reported_not_duplicated(self):
        export.write(self.path, [('pending', GROUP)])
        with patch('jobdisco.export.os.replace', side_effect=PermissionError(13, 'in use')):
            with self.assertRaises(export.ExportLocked):
                export.write(self.path, [('pending', GROUP)])
        self.assertEqual([path.name for path in self.path.parent.iterdir()], ['review-queue.xlsx'])

    def test_control_characters_do_not_break_the_file(self):
        export.write(self.path, [('pending', dict(GROUP, title='RTL\x0b Engineer\x00'))])
        rows, _ = sheet_rows(self.path)
        self.assertEqual(rows[1][2], 'RTL Engineer')


class ExportEndpointTests(unittest.TestCase):
    # The review fixture alone; subclassing would run every one of its tests again.
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = self.root / 'jobs.sqlite'
        self.ledger = self.root / 'operational/applications.ndjson'
        seen = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript('''CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);
                INSERT INTO companies VALUES ('sample', 'Sample Semiconductor');
                CREATE TABLE jobs(url TEXT PRIMARY KEY, company_key TEXT, title TEXT, location TEXT,
                                  source_job_id TEXT, first_seen TEXT, posted_at TEXT, provider_key TEXT,
                                  relevance REAL, closed_at TEXT, raw TEXT, last_seen TEXT);''')
            for ident in ('a', 'b', 'c'):
                db.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                           (f'https://example.test/{ident}', 'sample', 'RTL Engineer', ident.upper(),
                            f'req-{ident}', seen, None, 'direct', 80, None,
                            json.dumps({'description': '<p>Design hardware.</p>'}), seen))

    def serve(self):
        self.export_path = self.root / 'exports' / 'review-queue.xlsx'
        server = review.make_server(self.db, self.ledger, 0, self.export_path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_port}'

    def post(self, root, body, token):
        request = Request(root + '/api/export', data=json.dumps(body).encode(), method='POST',
                          headers={'Content-Type': 'application/json', 'X-Review-Token': token})
        with urlopen(request) as response:
            return json.load(response)

    def test_the_page_order_is_the_workbook_order(self):
        root = self.serve()
        with urlopen(root + '/api/queue') as response:
            state = json.load(response)
        ids = [group['id'] for group in state['pending']][::-1]
        written = self.post(root, {'ids': ids + ['not-a-group']}, state['token'])
        self.assertEqual(written['groups'], len(ids))
        rows, _ = sheet_rows(self.export_path)
        locations = {group['id']: [job['location'] for job in group['jobs']] for group in state['pending']}
        expected = [location for group in ids for location in locations[group]]
        self.assertEqual([row[3] for row in rows[1:]], expected)

    def test_it_needs_the_page_token(self):
        root = self.serve()
        with self.assertRaises(HTTPError) as refused:
            self.post(root, {'ids': []}, 'wrong')
        self.assertEqual(refused.exception.code, 403)
        self.assertFalse(self.export_path.exists())

    def test_selected_download_contains_only_requested_group_and_is_an_attachment(self):
        root = self.serve()
        with urlopen(root + '/api/queue') as response:
            state = json.load(response)
        chosen = state['pending'][0]
        request = Request(root + '/api/export/download',
                          data=json.dumps({'ids': [chosen['id'], chosen['id']]}).encode(), method='POST',
                          headers={'Content-Type': 'application/json', 'X-Review-Token': state['token']})
        with urlopen(request) as response:
            self.assertIn('attachment', response.headers['Content-Disposition'])
            self.assertEqual(response.headers['Content-Type'],
                             'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            downloaded = response.read()
        self.assertFalse(self.export_path.exists())
        download_path = self.root / 'download.xlsx'
        download_path.write_bytes(downloaded)
        rows, _ = sheet_rows(download_path)
        self.assertEqual(len(rows) - 1, len(chosen['jobs']))
        self.assertEqual([row[3] for row in rows[1:]], [job['location'] for job in chosen['jobs']])

    def test_selected_download_requires_token(self):
        root = self.serve()
        request = Request(root + '/api/export/download', data=b'{"ids":[]}', method='POST',
                          headers={'Content-Type': 'application/json'})
        with self.assertRaises(HTTPError) as refused:
            urlopen(request)
        self.assertEqual(refused.exception.code, 403)


class PageContractTests(unittest.TestCase):
    def setUp(self):
        self.script = (ROOT / 'src/jobdisco/review_static/app.js').read_text(encoding='utf-8')
        self.page = (ROOT / 'src/jobdisco/review_static/index.html').read_text(encoding='utf-8')

    def test_every_sort_in_the_menu_is_one_the_script_knows(self):
        # The sort menu's own options; the Applied tab's Show menu has others.
        menu = re.search(r'<select id="sort">(.*?)</select>', self.page).group(1)
        values = re.findall(r'<option value="([^"]+)"', menu)
        self.assertEqual(set(values), {'fit-desc', 'fit-desc-oldest', 'fit-asc', 'newest', 'oldest',
                                       'recommended'})
        for value in values:
            if value != 'recommended':
                self.assertIn(f"'{value}':", self.script)

    def test_the_export_key_stays_out_of_text_fields(self):
        self.assertIn("event.key !== 'e'", self.script)
        self.assertIn("closest?.('input, textarea, select", self.script)
        self.assertIn("'/api/export/download'", self.script)
        self.assertIn('id="export"', self.page)


if __name__ == '__main__':
    unittest.main()
