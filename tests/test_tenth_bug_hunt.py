"""Fourth bug hunt, 2026-10-01: #197-216.

Found by building the review queue from the live index (bootstrapped from the
data repository, 2026-09-27) and reading what it showed, what it hid and what
the collectors had stored. Each case is the wording or markup of a real
posting or page. Red on 32d280b.
"""
import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from jobdisco import applications, jsearch, ranking
from jobdisco.collector import Collector, html_items
from jobdisco.job_text import clean_title, readable_text
from jobdisco.validate_sources import Source

RULES = jsearch.load_plan()[0]['filter']
SOURCE = Source('x', 'company_direct_sources', 'renesas', 'Renesas', 'renesas_careers',
                'https://jobs.renesas.com/vacanciessitemap.xml', {})


def refused(title):
    return jsearch.excluded(title, RULES) or jsearch.title_blocked(title, RULES)


def response(url, body, content_type):
    answer = requests.Response()
    answer.status_code, answer._content, answer.url = 200, body, url
    answer.headers['content-type'] = content_type
    # What the transport adapter does with a real response.
    answer.encoding = requests.utils.get_encoding_from_headers(answer.headers)
    return answer


def collector(source):
    args = Namespace(max_jobs=1000, max_pages=5, delay=0, timeout=1, retries=0,
                     source_state=Path(tempfile.gettempdir()) / 'unused_pauses.sqlite')
    c = Collector(source, args)
    c.session.request = Mock()
    return c


class CollectorTests(unittest.TestCase):
    def setUp(self):
        for target in ('jobdisco.collection_policy.robots_delay', 'jobdisco.collector.time.sleep'):
            patcher = patch(target, return_value=None)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_197_a_page_that_names_no_charset_in_its_header(self):
        """Renesas sends `text/html` with no charset and declares UTF-8 in the
        page. `requests` reads such a page as ISO-8859-1, and 150 open titles
        were stored as "Architect â\\x80\\x93 Drone" and Japanese mojibake."""
        c = collector(SOURCE)
        self.addCleanup(c.session.close)
        sitemap = b'<urlset><url><loc>https://jobs.renesas.com/job/a-jid-1</loc></url></urlset>'
        page = ('<html><head><meta charset="utf-8"/></head><body>'
                '<h1>Application Technology Architect – Drone</h1><main>Austin</main></body></html>')
        c.session.request.side_effect = [
            response(SOURCE.access_url, sitemap, 'application/xml'),
            response('https://jobs.renesas.com/job/a-jid-1', page.encode('utf-8'), 'text/html')]
        c.collect_sitemap()
        self.assertEqual(c.jobs[0]['title'], 'Application Technology Architect – Drone')

    def test_206_googles_location_beside_the_place_icon(self):
        """Google prints the place in an unnamed span after a `place` icon, so
        all 3,263 open Google postings were stored with no location and none
        could be placed abroad (7 of 20 on the page read were)."""
        row = ('<ul><li class="lLd3Je"><h3 class="QJPWVe">Account Executive</h3>'
               '<span class="RP7SMd"><i class="google-material-icons">corporate_fare</i><span>Google</span></span>'
               '<span class="pwO9Dc"><i class="google-material-icons">place</i>'
               '<span class="r0wTof">Dublin, Ireland</span></span>'
               '<a href="jobs/results/93814459062985414-account-executive?page=2">Learn more</a></li></ul>')
        items, _ = html_items(row, 'https://www.google.com/about/careers/applications/jobs/results',
                              'google_jobs')
        self.assertEqual(items[0]['location'], 'Dublin, Ireland')

    def test_207_greenhouse_is_asked_for_its_descriptions(self):
        """The Greenhouse job board API returns descriptions only with
        `content=true`. Without it the 414 open postings from four boards had
        none, so no experience, citizenship or PhD requirement was ever read."""
        c = collector(replace(SOURCE, provider_key='greenhouse',
                              access_url='https://boards-api.greenhouse.io/v1/boards/asteralabs/jobs'))
        self.addCleanup(c.session.close)
        reply = Mock(status_code=200, text='', headers={'content-type': 'application/json'})
        reply.json.return_value = {'jobs': [{'id': 1, 'title': 'RTL Engineer', 'absolute_url': 'https://x/1',
                                             'content': '&lt;p&gt;5+ years of RTL experience required&lt;/p&gt;'}]}
        c.session.request.return_value = reply
        c.run()
        self.assertIn('content=true', c.session.request.call_args[0][1])
        self.assertEqual(jsearch.experience_debug(c.jobs[0])['hard_pass_reason'],
                         'required_experience_over_2_years')

    def test_207_escaped_markup_is_markup(self):
        """Greenhouse escapes its HTML, and the review page showed the tags."""
        self.assertEqual(readable_text('&lt;p&gt;Design &amp; verify&lt;/p&gt;&lt;ul&gt;&lt;li&gt;UVM&lt;/li&gt;'),
                         'Design & verify\nUVM')
        self.assertEqual(readable_text('Use vector&lt;T&gt; &amp; maps'), 'Use vector<T> & maps')


class TitleRuleTests(unittest.TestCase):
    def test_198_a_security_operations_centre(self):
        """"SOC Support Specialist" (Huntress) ranked Core VLSI and "Strategic
        Assurance and SOC Services Intern" (an audit firm's SOC reports) led the
        Early career tab."""
        for title in ('SOC Support Specialist- Central Time Zone',
                      'Strategic Assurance and SOC Services Intern - Summer 2027'):
            self.assertEqual(ranking.bucket(title), 4, title)
        self.assertEqual(ranking.bucket('SoC Design Engineer'), 2)

    def test_199_cybersecurity_does_not_unmake_an_fpga_title(self):
        """"FPGA/SoC Embedded Cybersecurity Engineer" (AMD) was Related, because
        the security-centre test vetoed every core word, not only SOC."""
        self.assertEqual(ranking.bucket('FPGA/SoC Embedded Cybersecurity Engineer'), 2)
        self.assertEqual(ranking.bucket('Cyber Security SOC Engineer'), 4)

    def test_200_fpga_spelled_out(self):
        self.assertEqual(ranking.bucket('Field-Programmable Gate Arrays Engineer'), 2)
        self.assertEqual(ranking.bucket('Field Programmable Gate Array Developer'), 2)

    def test_201_hardware_and_firmware_abbreviated(self):
        for title in ('HW Engineer', 'SIT Engineer (HW/FW Focus)', 'FW Design Eng 2'):
            self.assertEqual(ranking.bucket(title), 3, title)

    def test_202_post_silicon_as_one_word(self):
        self.assertEqual(ranking.bucket('Server Postsilicon Project Engineer'), 3)
        self.assertEqual(ranking.bucket('Presilicon Validation Engineer'), 2)

    def test_203_principle_for_principal(self):
        """Astera's "Principle Validation Engineer" and NXP's "Principle DFT
        Engineer" passed the principal block the user asked for."""
        self.assertTrue(refused('Principle DFT Engineer'))
        self.assertTrue(refused('Principle Validation Engineer'))

    def test_205_distinguished(self):
        """Only "Distinguished Engineer" and "Distinguished Member" were named,
        and five distinguished architects and engineers were in the main tabs."""
        for title in ('Distinguished Formal Verification Architect', 'Distinguished Formal Verification',
                      'Distinguished Hardware Security Engineer Hybrid/Remote',
                      'Advanced Packaging, Distinguished Architect'):
            self.assertTrue(refused(title), title)

    def test_210_account_executive_is_sales(self):
        """90 queued groups; "Digital IC, Account Technology Executive (ATX)"
        sat in Core VLSI."""
        for title in ('Digital IC, Account Technology Executive (ATX)', 'Cybersecurity Account Executive',
                      'Strategic Account Representative, Strategic Accounts'):
            self.assertTrue(refused(title), title)
        self.assertFalse(refused('IC RTL2GDS Architect, AE'))

    def test_211_ip_design_and_digital_implementation(self):
        for title in ('Fabric IP Designer', 'Security IP Design Engineer', 'Ethernet IP Design Application Engineer',
                      'Digital Implementation AE Architect'):
            self.assertEqual(ranking.bucket(title), 2, title)

    def test_212_analog_blocks(self):
        for title in ('PLL Design Engineer', 'High Speed DAC Design Expert', 'Power Management Design Engineer',
                      'PLL Design/ Integration Staff Engineer'):
            self.assertEqual(ranking.bucket(title), 3, title)

    def test_213_an_mba_opening(self):
        """"MBA Internships" and "2027 MBA Leadership Development Program
        Intern" were on the Early career tab."""
        self.assertTrue(refused('MBA Internships'))
        self.assertTrue(refused('2027 MBA Leadership Development Program (MLDP) Intern'))

    def test_214_talent_sourcing(self):
        for title in ('Talent Sourcer, AI', 'Strategic Sourcing Specialist', 'Substrate Sourcing Architect'):
            self.assertTrue(refused(title), title)

    def test_216_manager_misspelled(self):
        self.assertTrue(refused('Program Manger, AUTA Experience'))


class ExperienceTests(unittest.TestCase):
    def test_204_non_internship_experience(self):
        """Amazon's "3+ years of non-internship professional software
        development experience" read as an internship opening, which overrides
        the experience gate: 80 queued listings asked three years or more."""
        found = jsearch.experience_debug({'title': 'SDE II , AWS IoT Fleet Management', 'raw': {
            'basic_qualifications': '- 3+ years of non-internship professional software development experience\n'
                                    "- Bachelor's degree or equivalent"}})
        self.assertFalse(found['entry_override'])
        self.assertEqual(found['hard_pass_reason'], 'required_experience_over_2_years')
        # An internship that is the opening still is one.
        self.assertTrue(jsearch.experience_debug({'title': 'Engineer', 'raw': {
            'description': 'This internship is open to students. 3+ years of coursework.'}})['entry_override'])


class TitleTextTests(unittest.TestCase):
    def test_209_the_city_alone_at_the_end(self):
        self.assertEqual(clean_title('CPU Physical Design Engineer, San Diego',
                                     'San Diego, California, United States of America'),
                         'CPU Physical Design Engineer')
        self.assertEqual(clean_title('CPU Physical Design Engineer (Austin)', 'Austin, Texas, United States'),
                         'CPU Physical Design Engineer')
        self.assertEqual(clean_title('Process Development Engineer Intern - MS/PhD – Lehi', 'Lehi, UT, United States'),
                         'Process Development Engineer Intern - MS/PhD')
        # Inside a bracket with other words it is part of the title.
        self.assertEqual(clean_title('FPGA Developer (Compute Test, North Reading)', 'North Reading, MA, US'),
                         'FPGA Developer (Compute Test, North Reading)')
        # A city that is the whole title stays.
        self.assertEqual(clean_title('Austin', 'Austin, TX, US'), 'Austin')

    def test_215_hashtag_and_dangling_separator(self):
        """Qualcomm prints 22 titles as hashtags, "#Embedded Software Engineer"."""
        self.assertEqual(clean_title('#Embedded Software Engineer', ''), 'Embedded Software Engineer')
        self.assertEqual(clean_title('EHS Specialist,', ''), 'EHS Specialist')
        self.assertEqual(clean_title('RTL Engineer -', ''), 'RTL Engineer')
        self.assertEqual(clean_title('C# Developer', ''), 'C# Developer')


class DecisionReplayTests(unittest.TestCase):
    def test_208_a_decided_paid_listing_under_an_older_title_cleaning(self):
        """An application recorded on 2026-09-26 stored the paid listing's title
        as "... Summer 2027 - Chandler, AZ, United States"; titles are cleaned
        of that today, so the same listing under a new id no longer matched
        the decision and came back to be applied for again."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        db, ledger = root / 'jobs.sqlite', root / 'operational/applications.ndjson'
        now = datetime.now(timezone.utc)
        seen = (now - timedelta(days=1)).isoformat()
        title = 'Security Verification/Validation Engineer Intern, BS - Summer 2027'
        old = {'url': 'https://x.example/jobs/old', 'provider_key': 'jsearch', 'company_key': 'marvell',
               'source_job_id': 'old', 'location': 'Chandler, Arizona, US',
               'title': title + ' - Chandler, AZ, United States'}
        ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps({
            'id': 'e1', 'url': old['url'], 'at': seen, 'status': 'applied', 'reason': '', 'group_id': 'g',
            'group': {'id': 'g', 'company': 'Marvell', 'title': old['title'], 'jobs': [old]}}) + '\n',
            encoding='utf-8')
        with closing(sqlite3.connect(db)) as con, con:
            con.executescript('''CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);
                CREATE TABLE jobs(url TEXT PRIMARY KEY, company_key TEXT, title TEXT, location TEXT,
                                  source_job_id TEXT, first_seen TEXT, posted_at TEXT, provider_key TEXT,
                                  relevance REAL, closed_at TEXT, raw TEXT, last_seen TEXT);''')
            con.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        ('https://x.example/jobs/new', 'marvell', title + ' - Chandler, AZ', 'Chandler, Arizona, US',
                         'new', seen, None, 'jsearch', 80, None, json.dumps({}), seen))
        state = applications.queue(db, ledger, now)
        self.assertEqual([group['title'] for group in state['pending'] + state['backlog']], [])


if __name__ == '__main__':
    unittest.main()
