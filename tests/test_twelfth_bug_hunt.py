"""Pasted-link intake, 2026-10-02: #301-310.

Found by pasting one open posting per provider in the live index through the
intake on 1b9b149 (one request per site): 7 of 15 could not be read at all,
and of the eight that could, three stored a wrong location, description or
date. Each page below is cut down from what that site sent. Each case is red
on 1b9b149.
"""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

import requests
from requests.structures import CaseInsensitiveDict

from jobdisco import collector, export, manual_intake as intake, ranking, review
from jobdisco.validate_sources import Source


def empty():
    return {name: [] for name in ('pending', 'backlog', 'applied', 'skipped')}


def response(url, body, content_type='text/html; charset=utf-8', status=200):
    """A finished requests.Response, as the site sent it."""
    answer = requests.Response()
    answer.status_code, answer.url = status, url
    answer._content = body.encode('utf-8') if isinstance(body, str) else body
    answer._content_consumed = True
    answer.headers = CaseInsensitiveDict({'Content-Type': content_type})
    answer.encoding = requests.utils.get_encoding_from_headers(answer.headers)
    return answer


class FakeSession:
    """Answers each URL from a table and records what was asked."""

    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kwargs):
        self.asked.append(url)
        if url not in self.pages:
            return response(url, 'Not found', status=404)
        body, content_type = self.pages[url] if isinstance(self.pages[url], tuple) else (self.pages[url], None)
        return response(url, body, *(content_type,) if content_type else ())


def ld(record):
    return ('<html><head><script type="application/ld+json">%s</script></head><body></body></html>'
            % json.dumps(record, ensure_ascii=False))


def written_id(case, url):
    return next(group['id'] for group in case.page['pending'] if group['jobs'][0]['url'] == url)


class Pasted(unittest.TestCase):
    """POST /api/manual against a fake web, then read the queue the page reads."""

    sources = []
    fixture = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Path(self.temp.name) / 'applications.ndjson'
        self.db = Path(self.temp.name) / 'index.sqlite'

    def paste(self, pages, data):
        session = FakeSession(pages)
        fixture = self.fixture or empty()
        with patch.object(intake, 'public_url', side_effect=intake.normalized_url), \
             patch.object(intake.requests, 'Session', return_value=session), \
             patch.object(intake.collection_policy, 'STATE', Path(self.temp.name) / 'absent.sqlite'), \
             patch.object(intake.collection_policy, 'request_interval', return_value=0), \
             patch.object(collector, 'load_sources', return_value=self.sources), \
             patch.object(review.applications, 'queue', side_effect=lambda *args: copy.deepcopy(fixture)):
            server = review.make_server(self.db, self.ledger, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f'http://127.0.0.1:{server.server_port}'
                token = json.load(urlopen(base + '/api/queue'))['token']
                written = json.load(urlopen(Request(base + '/api/manual', data=json.dumps(data).encode(),
                                                    headers={'X-Review-Token': token})))
                self.page = json.load(urlopen(base + '/api/queue'))
                state = copy.deepcopy(server.current_queue())
            finally:
                server.shutdown(); server.server_close(); thread.join()
        self.asked = session.asked
        return written, state

    def added(self, pages, url, **data):
        written, state = self.paste(pages, dict(data, url=url))
        group = next(group for name in ('pending', 'applied') for group in state[name]
                     if group['id'] == written['id'])
        return group, group['jobs'][0]


class ProviderPages(Pasted):

    def test_301_greenhouse_posting_is_read_from_the_board_api(self):
        # The posting's page carries no JSON-LD: the job is drawn in the
        # browser from the board API the collector already reads.
        page = 'https://job-boards.greenhouse.io/tenstorrent/jobs/5248013007'
        api = 'https://boards-api.greenhouse.io/v1/boards/tenstorrent/jobs/5248013007'
        record = {'id': 5248013007, 'title': 'Sr. Engineer, Performance Infrastructure (RISC-V)',
                  'company_name': 'Tenstorrent', 'first_published': '2026-09-24T07:25:31-04:00',
                  'location': {'name': 'Australia; Santa Clara, California, United States'},
                  'absolute_url': page,
                  'content': '&lt;p&gt;Tenstorrent builds &lt;b&gt;RISC-V&lt;/b&gt; CPUs.&lt;/p&gt;'}
        group, job = self.added({page: '<html><body><div id="app"></div></body></html>',
                                 api: (json.dumps(record), 'application/json')}, page)
        self.assertEqual(group['title'], 'Sr. Engineer, Performance Infrastructure (RISC-V)')
        self.assertEqual(group['company'], 'Tenstorrent')
        self.assertEqual(job['location'], 'Australia; Santa Clara, California, United States')
        self.assertEqual(job['source_job_id'], '5248013007')
        self.assertEqual(job['posted_at'], '2026-09-24T07:25:31-04:00')
        self.assertEqual(job['manual_description'], 'Tenstorrent builds\nRISC-V\nCPUs.')
        self.assertEqual(job['url'], page)

    def test_302_smartrecruiters_posting_is_read_from_its_api(self):
        page = 'https://jobs.smartrecruiters.com/Sandisk/744000151450267'
        api = 'https://api.smartrecruiters.com/v1/companies/Sandisk/postings/744000151450267'
        record = {'id': '744000151450267', 'name': 'Senior Staff Engineer, Enterprise Data Platform',
                  'company': {'name': 'Sandisk', 'identifier': 'Sandisk'},
                  'location': {'city': 'Milpitas', 'region': 'CA', 'country': 'us', 'fullLocation': ', '},
                  'releasedDate': '2026-09-23T18:39:02.858Z',
                  'jobAd': {'sections': {'jobDescription': {'title': 'Job Description', 'text': '<p>Own the data platform.</p>'},
                                         'qualifications': {'title': 'Qualifications', 'text': '<ul><li>8 years</li></ul>'}}}}
        group, job = self.added({page: '<html><body></body></html>',
                                 api: (json.dumps(record), 'application/json')}, page)
        self.assertEqual(group['title'], 'Senior Staff Engineer, Enterprise Data Platform')
        self.assertEqual(group['company'], 'Sandisk')
        self.assertEqual(job['location'], 'Milpitas, CA, us')
        self.assertEqual(job['source_job_id'], '744000151450267')
        self.assertEqual(job['posted_at'], '2026-09-23T18:39:02.858Z')
        self.assertIn('Own the data platform.', job['manual_description'])
        self.assertIn('8 years', job['manual_description'])

    def test_303_schema_org_microdata_page(self):
        # SuccessFactors (Teradyne) marks the posting up with itemprop
        # attributes and publishes no JSON-LD.
        page = 'https://jobs.teradyne.com/Universal-Robots/job/Torino-Field-Applications-Engineer/1432340600'
        html = '''<html><body><div itemscope itemtype="http://schema.org/JobPosting">
          <h1><span itemprop="title">Field Applications Engineer</span></h1>
          <span itemprop="hiringOrganization">Universal Robots</span>
          <span itemprop="jobLocation" itemscope itemtype="http://schema.org/Place">
            <span itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">
              <meta itemprop="streetAddress" content="Torino, IT"></span></span>
          <meta itemprop="datePosted" content="Tue Sep 22 00:00:00 UTC 2026">
          <span itemprop="description"><p>Support customers with cobots.</p></span>
        </div></body></html>'''
        group, job = self.added({page: html}, page)
        self.assertEqual(group['title'], 'Field Applications Engineer')
        self.assertEqual(group['company'], 'Universal Robots')
        self.assertEqual(job['location'], 'Torino, IT')
        self.assertEqual(job['manual_description'], 'Support customers with cobots.')
        self.assertEqual(job['posted_at'], '2026-09-22')


class PostingFields(Pasted):

    def test_304_a_country_object_is_not_printed_as_a_python_dict(self):
        # Qualcomm (Eightfold), as sent: addressCountry is a schema.org Country.
        page = 'https://careers.qualcomm.com/careers/job/446721269051'
        record = {'@type': 'JobPosting', 'title': 'Supply Chain Analyst', 'hiringOrganization': {'name': 'Qualcomm'},
                  'jobLocation': [{'@type': 'Place', 'address': {'addressLocality': 'San Diego', 'addressRegion': 'CA',
                                                                'addressCountry': {'@type': 'Country', 'name': 'US'}}},
                                  {'@type': 'Place', 'address': {'addressLocality': 'Austin', 'addressRegion': 'TX',
                                                                'addressCountry': {'@type': 'Country', 'name': 'US'}}}]}
        group, job = self.added({page: ld(record)}, page)
        self.assertEqual(job['location'], 'San Diego, CA, US; Austin, TX, US')

    def test_305_escaped_html_description_is_read_as_text(self):
        # Cisco (Phenom) escapes the description's markup inside JSON-LD, and
        # the page showed "<p>Please note ..." as text.
        page = 'https://careers.cisco.com/global/en/job/2026805'
        record = {'@type': 'JobPosting', 'title': 'Software Engineer Embedded Systems II (Intern)',
                  'hiringOrganization': {'name': 'Cisco'},
                  'description': '&lt;p&gt;Please note this posting&lt;/p&gt;&lt;ul&gt;&lt;li&gt;C and C++&lt;/li&gt;&lt;/ul&gt;'}
        group, job = self.added({page: ld(record)}, page)
        self.assertEqual(job['manual_description'], 'Please note this posting\nC and C++')

    def test_306_page_without_a_header_charset_is_read_as_it_declares(self):
        # requests reads text/html with no charset as ISO-8859-1 -- the
        # collector's #197 -- and the title was stored as "Architect â\x80\x93 Drone".
        page = 'https://jobs.renesas.com/job/architect-drone-jid-6001'
        record = {'@type': 'JobPosting', 'title': 'Architect – Drone', 'hiringOrganization': {'name': 'Renesas'}}
        body = ('<html><head><meta charset="utf-8">' + ld(record)[12:]).encode('utf-8')
        group, job = self.added({page: (body, 'text/html')}, page)
        self.assertEqual(group['title'], 'Architect – Drone')

    def test_307_unpadded_iso_date_is_a_date(self):
        # Synopsys (Avature) and Arm (TalentBrew) publish datePosted as
        # "2026-9-21"; the queue read it as undated and ranked it as new today.
        self.assertEqual(ranking.posted_day('2026-9-21').isoformat(), '2026-09-21')
        self.assertEqual(ranking.posted_day('2026-09-21').isoformat(), '2026-09-21')
        self.assertIsNone(ranking.posted_day('2026-13-01'))


class GooglePage(Pasted):
    """Not red on 1b9b149: a guard on the fallback the first fix had, which
    read the heading of a page on a board the catalog knows."""

    sources = [Source('google:1', 'company_direct_sources', 'google', 'Google LLC', 'google_jobs',
                      'https://www.google.com/about/careers/applications/jobs/results', {})]

    def test_303_a_page_heading_is_not_taken_for_the_title(self):
        # Google's posting pages publish no structured data and head the
        # posting "job details" (live, 2026-10-02).
        self.db.touch()
        page = 'https://www.google.com/about/careers/applications/jobs/results/998-npi-engineer'
        with self.assertRaises(Exception) as caught:
            self.added({page: '<html><body><h1>job details</h1><main>NPI Engineer</main></body></html>'}, page)
        self.assertIn('400', str(caught.exception))


class KnownCompany(Pasted):
    """A link on a board the index already reads is that company's posting."""

    sources = [Source('silabs:1', 'company_sources', 'silicon_labs', 'Silicon Labs', 'workday',
                      'https://silabs.wd1.myworkdayjobs.com/SiliconLabsCareers', {})]

    def setUp(self):
        super().setUp()
        self.db.touch()  # load_sources is patched; the index only has to exist

    def indexed(self):
        job = {'url': 'https://silabs.wd1.myworkdayjobs.com/SiliconLabsCareers/job/Singapore/Test-Engineer_20521-1',
               'company_key': 'silicon_labs', 'provider_key': 'workday', 'source_job_id': '20521-1',
               'title': 'Product Test Engineer', 'location': 'Singapore', 'company': 'Silicon Labs'}
        return {'id': 'indexed-group', 'company': 'Silicon Labs', 'title': 'Product Test Engineer',
                'confidence': 40, 'bucket': 3, 'jobs': [job]}

    def test_308_catalog_company_and_board_requisition(self):
        # The page names the legal entity and the bare requisition; the share
        # link carries Workday's locale. All three made a second copy of a
        # posting already in the queue, under another company name.
        self.fixture = empty()
        self.fixture['pending'].append(self.indexed())
        page = 'https://silabs.wd1.myworkdayjobs.com/en-US/SiliconLabsCareers/job/Singapore/Test-Engineer_20521-1'
        record = {'@type': 'JobPosting', 'title': 'Product Test Engineer',
                  'hiringOrganization': {'name': 'Silicon Labs Intl'}, 'identifier': {'value': '20521'}}
        written, state = self.paste({page: ld(record)}, {'url': page, 'status': 'applied'})
        self.assertFalse(written['created'])
        self.assertEqual(written['id'], 'indexed-group')
        self.assertEqual([group['id'] for group in state['applied']], ['indexed-group'])
        self.assertFalse(state['pending'])

    def test_308_an_unindexed_posting_takes_the_catalog_name(self):
        page = 'https://silabs.wd1.myworkdayjobs.com/en-US/SiliconLabsCareers/job/Austin/RTL-Engineer_30001'
        record = {'@type': 'JobPosting', 'title': 'RTL Engineer', 'hiringOrganization': {'name': 'Silicon Labs Intl'},
                  'identifier': {'value': '30001'}}
        group, job = self.added({page: ld(record)}, page)
        self.assertEqual(group['company'], 'Silicon Labs')
        self.assertEqual(job['company_key'], 'silicon_labs')
        self.assertEqual(job['source_job_id'], '30001')


class Tabs(Pasted):

    def test_309_applied_from_a_link_is_listed_by_date(self):
        # Applied and Skipped are newest first; a pasted posting marked applied
        # today was put after every older application.
        older = {'id': 'older', 'company': 'Example', 'title': 'Engineer', 'confidence': 10,
                 'at': '2026-09-01T00:00:00+00:00', 'jobs': [{'url': 'https://example.com/1'}]}
        self.fixture = empty()
        self.fixture['applied'].append(older)
        written, state = self.paste({}, {'url': 'https://company.example/R9', 'company': 'Example',
                                         'title': 'RTL Engineer', 'status': 'applied'})
        self.assertEqual([group['id'] for group in state['applied']], [written['id'], 'older'])

    def test_310_a_pasted_job_board_listing_is_marked_third_party(self):
        # The page and the workbook mark third-party copies; a pasted one
        # carried no publisher, so a ZipRecruiter copy read as the company's.
        url = 'https://www.ziprecruiter.com/c/Wipro/Job/Design-Verification-Engineer/-in-San-Jose,CA?jid=3e79e6ae38df7b2a'
        group, job = self.added({}, url, company='Wipro', title='Design Verification Engineer')
        shown = next(group for group in self.page['pending'] if group['id'] == written_id(self, url))
        self.assertTrue(shown['jobs'][0]['third_party_site'])
        self.assertEqual(job['publisher'], 'ZipRecruiter')
        self.assertTrue(export.third_party_site(job))
        company = 'https://careers.wipro.com/job/123'
        group, job = self.added({}, company, company='Wipro', title='Design Verification Engineer')
        self.assertFalse(export.third_party_site(job))


class HardRejects(Pasted):
    """#311, reported by the user: an RTX posting that requires U.S.
    citizenship reached Review. Collected copies are refused -- every RTX
    posting in the index is -- but a pasted one skipped every check. Title,
    seniority, experience and PhD stay the user's call for a pasted job;
    citizenship does not."""

    CITIZEN = ('RTX is seeking a Digital Design Engineer intern. U.S. Citizen, U.S. Person, or Immigration '
               'Status Requirements: U.S. citizenship is required, as only U.S. citizens are eligible '
               'for a security clearance.')

    def refused(self, **data):
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as caught:
            self.paste({}, dict({'url': 'https://careers.rtx.com/global/en/job/01790999'}, **data))
        self.assertEqual(caught.exception.code, 400)
        return json.loads(caught.exception.read())['error']

    def test_311_citizenship_stated_in_the_posting(self):
        error = self.refused(company='Example Avionics', title='Digital Design Engineer Intern',
                             description=self.CITIZEN)
        self.assertIn('citizenship', error)

    def test_311_excluded_employer_whose_copy_cut_the_requirement(self):
        # JobLeads' copy of RTX's Tucson internship: two paragraphs, the
        # citizenship line gone. The employer list answers for it.
        error = self.refused(company='Raytheon', title='Digital Design Engineer Intern (FPGA/ASIC)',
                             description='RTX is seeking a Digital Design Engineer intern in the Effector '
                                         'Digital Products department.')
        self.assertIn('Raytheon', error)

    def test_311_citizenship_stated_in_the_title(self):
        error = self.refused(company='Example', title='FPGA Engineer - US Citizen Required')
        self.assertIn('citizenship', error)

    def test_311_already_pasted_is_hidden_and_applied_is_still_recorded(self):
        group = intake.create_group('https://careers.rtx.com/global/en/job/1', intake.posting_metadata(
            '', {'company': 'RTX', 'title': 'Digital Design Engineer', 'description': self.CITIZEN}))
        intake.save_manual(self.ledger, group)
        self.assertFalse(intake.augment_queue(empty(), self.ledger)['pending'])
        written, state = self.paste({}, {'url': 'https://careers.rtx.com/global/en/job/2', 'status': 'applied',
                                         'company': 'RTX', 'title': 'FPGA Engineer', 'description': self.CITIZEN})
        self.assertEqual([g['id'] for g in state['applied']], [written['id']])

    def test_311_experience_stays_the_users_call(self):
        group, job = self.added({}, 'https://company.example/R5', company='Example', title='RTL Design Engineer',
                                description='Requires 8+ years of RTL design experience.')
        self.assertEqual(group['title'], 'RTL Design Engineer')


if __name__ == '__main__':
    unittest.main()
