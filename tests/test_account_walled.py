"""Third-party sites behind an account wall, and publishers never requested.

Asked for by the user on 2026-09-27: a listing that cannot reach the real
posting in one click without an account or membership is blocked, and every
blocked publisher is excluded from the JSearch request itself.
"""
import os
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from jobdisco import jsearch

CONFIG, _ = jsearch.load_plan()
RULES = CONFIG['filter']
QUERY = jsearch.Query('ASIC Intern', 1, 'intern')


def item(**fields):
    base = {'job_id': 'j1', 'job_title': 'ASIC Design Intern', 'employer_name': 'Acme',
            'job_apply_link': 'https://www.dice.com/job-detail/1',
            'job_google_link': 'https://www.google.com/search?q=acme&ibp=htl;jobs',
            'job_publisher': 'Dice'}
    base.update(fields)
    return base


class RequestTests(unittest.TestCase):
    def fetch(self, settings):
        response = MagicMock(status_code=200)
        response.json.return_value = {'status': 'OK', 'data': {'jobs': []}}
        guard = MagicMock()
        guard.get.return_value = response
        search = {'endpoint_template': 'https://api.openwebninja.com/jsearch/search-v2',
                  'connection': {'auth_header': 'x-api-key'}}
        with patch.dict(os.environ, {'JSEARCH_API_KEY': 'test'}):
            jsearch.Client(search, settings, guard, session=MagicMock()).fetch_batch(QUERY)
        return parse_qs(urlsplit(guard.get.call_args.args[1]).query)

    def test_blocked_publishers_are_not_requested(self):
        params = self.fetch(CONFIG)
        asked = params['exclude_job_publishers'][0].split(',')
        for name in ('JobLeads', 'Jobrapido', 'Dice', 'Wellfound', 'Ladders', 'BeBee'):
            self.assertIn(name, asked)
        # The user has a Handshake account, so it is requested (2026-09-27).
        self.assertNotIn('Handshake', asked)

    def test_every_walled_site_is_excluded_by_name(self):
        asked = {jsearch._plain_name(name) for name in CONFIG['exclude_job_publishers']}
        for name in RULES['account_walled_publishers']:
            if name not in ('AngelList', 'TheLadders'):
                self.assertIn(jsearch._plain_name(name), asked)

    def test_a_plan_without_the_list_sends_nothing(self):
        settings = dict(CONFIG, exclude_job_publishers=[])
        self.assertNotIn('exclude_job_publishers', self.fetch(settings))

    def test_the_exclusion_is_part_of_the_search(self):
        without = dict(CONFIG, exclude_job_publishers=[])
        self.assertNotEqual(jsearch.search_space(CONFIG), jsearch.search_space(without))
        # A plan that never set it keeps the cursors it had.
        plain = {'country': 'us', 'date_posted': 'today', 'employment_types': ['INTERN']}
        self.assertEqual(jsearch.search_space(plain), jsearch.search_space(dict(plain, exclude_job_publishers=[])))

    def test_a_name_with_a_comma_is_refused(self):
        self.assertTrue(all(',' not in name for name in CONFIG['exclude_job_publishers']))


class WalledTests(unittest.TestCase):
    def test_an_account_walled_listing_is_blocked(self):
        row = jsearch.normalize_job(item(), QUERY, {}, RULES)
        self.assertEqual(jsearch.rejection_reason(row, RULES), 'excluded_publisher')

    def test_an_open_apply_option_is_taken_instead(self):
        options = [{'publisher': 'Dice', 'apply_link': 'https://www.dice.com/job-detail/1'},
                   {'publisher': 'Acme Careers', 'apply_link': 'https://careers.acme.com/job/77'}]
        row = jsearch.normalize_job(item(apply_options=options), QUERY, {}, RULES)
        self.assertEqual(row['url'], 'https://careers.acme.com/job/77')
        self.assertFalse(jsearch.publisher_excluded(row['url'], row['raw'], RULES))

    def test_a_walled_publisher_behind_a_google_link(self):
        raw = {'job_publisher': 'Wellfound'}
        self.assertTrue(jsearch.publisher_excluded('https://www.google.com/search?q=x', raw, RULES))
        # Its name on a link to the employer's own site is not a wall.
        self.assertFalse(jsearch.publisher_excluded('https://careers.acme.com/1', raw, RULES))

    def test_every_walled_domain_and_its_subdomains(self):
        for domain in RULES['account_walled_domains']:
            with self.subTest(domain=domain):
                self.assertTrue(jsearch.publisher_excluded(f'https://jobs.{domain}/x', {}, RULES))
                self.assertFalse(jsearch.publisher_excluded(f'https://not{domain}/x', {}, RULES))

    def test_a_blocked_option_is_no_way_around(self):
        options = [{'publisher': 'JobLeads', 'apply_link': 'https://www.jobleads.com/job/1'}]
        self.assertTrue(jsearch.publisher_excluded('https://www.dice.com/job/1',
                                                   {'apply_options': options}, RULES))

    def test_open_sites_are_not_walled(self):
        for url, publisher in (('https://www.linkedin.com/jobs/view/1', 'LinkedIn'),
                               ('https://app.joinhandshake.com/jobs/1', 'Handshake'),
                               ('https://lensa.com/job/1', 'Lensa'),
                               ('https://careers.acme.com/1', 'Acme')):
            with self.subTest(publisher=publisher):
                self.assertFalse(jsearch.publisher_excluded(url, {'job_publisher': publisher}, RULES))

    def test_normalizing_without_rules_is_unchanged(self):
        row = jsearch.normalize_job(item(), QUERY, {})
        self.assertEqual(row['url'], 'https://www.dice.com/job-detail/1')


if __name__ == '__main__':
    unittest.main()
