"""Japan's chip boards read directly: BambooHR (EdgeCortix), Talentio (PFN).

Fixtures keep the shapes of the public responses captured on 2026-10-11 (see
fixtures/direct-source-captures.md); no request is made.
"""
import argparse
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from operation1million import experience, location
from operation1million.collector import Collector, Source

FIXTURES = Path(__file__).parent / 'fixtures'


def fixture(name):
    return (FIXTURES / name).read_text(encoding='utf-8')


class Response(SimpleNamespace):
    def json(self):
        return json.loads(self.text)


class JapanBoardTests(unittest.TestCase):
    def setUp(self):
        robots = patch('operation1million.collection_policy.robots_delay', return_value=None)
        robots.start()
        self.addCleanup(robots.stop)

    def collector(self, source, pages):
        args = argparse.Namespace(max_jobs=100, max_pages=10, delay=0, timeout=1,
                                  jsearch_timeout=1)
        c = Collector(source, args)
        self.addCleanup(c.session.close)
        asked = []

        def fetch(url, *unused):
            asked.append(url)
            for suffix, name in pages.items():
                if url.endswith(suffix):
                    return Response(text=fixture(name))
            raise AssertionError(f'unexpected request {url}')
        c.fetch = fetch
        return c, asked

    def test_bamboohr_reads_the_list_then_each_detail(self):
        source = Source('bamboohr:example', 'company_sources', 'edgecortix', 'EdgeCortix', 'bamboohr',
                        'https://example.bamboohr.com/careers', {'subdomain': 'example'})
        c, asked = self.collector(source, {'/careers/list': 'bamboohr_list_redacted.json',
                                           '/detail': 'bamboohr_detail_redacted.json'})
        self.assertEqual(c.run(), ('complete', ''))
        self.assertEqual(asked[0], 'https://example.bamboohr.com/careers/list')
        jobs = {job['source_job_id']: job for job in c.jobs}
        self.assertEqual(jobs['25']['url'], 'https://example.bamboohr.com/careers/25')
        # The title's "[Japan]" names the country the list leaves out.
        self.assertEqual(jobs['25']['location'], 'Kawasaki, Kanagawa, Japan')
        self.assertTrue(location.in_asia_tab(jobs['25']['location']))
        self.assertTrue(location.outside_allowed(jobs['33']['location']))
        self.assertIn('SystemVerilog', jobs['25']['raw']['description'])

    def test_talentio_reads_each_home_and_page(self):
        source = Source('talentio:example', 'company_sources', 'preferred_networks', 'Preferred Networks',
                        'talentio', 'https://open.talentio.com/r/1/c/example',
                        {'homes': ['https://open.talentio.com/r/1/c/example/homes/1'],
                         'location': 'Tokyo, Japan'})
        c, _ = self.collector(source, {'/homes/1': 'talentio_home_redacted.html',
                                       '/pages/101': 'talentio_page_redacted.html'})
        self.assertEqual(c.run(), ('complete', ''))
        [job] = c.jobs
        self.assertEqual(job['url'], 'https://open.talentio.com/r/1/c/example/pages/101')
        self.assertEqual(job['source_job_id'], '101')
        self.assertTrue(location.in_asia_tab(job['location']))
        # The preferred section's eight years are not a requirement.
        description = job['raw']['description']
        self.assertIn('応募資格（歓迎）', description)
        self.assertIsNone(experience.evaluate(job['title'], description)['required_experience_years'])

    def test_hrmos_pages_until_empty_and_reads_a_likely_posting(self):
        source = Source('hrmos:example', 'company_sources', 'toshiba', 'Toshiba', 'hrmos',
                        'https://hrmos.co/pages/example/jobs', {'country': 'Japan'})
        c, asked = self.collector(source, {'?page=1': 'hrmos_list_redacted.html',
                                           '?page=2': 'hrmos_empty_redacted.html',
                                           '/jobs/300000016': 'hrmos_detail_redacted.html'})
        self.assertEqual(c.run(), ('complete', ''))
        jobs = {job['source_job_id']: job for job in c.jobs}
        self.assertEqual(set(jobs), {'300000016', '000600001'})
        chip = jobs['300000016']
        self.assertEqual(chip['title'], 'AT-N1【神奈川】マイコン・システム LSIのデジタル設計エンジニア')
        self.assertEqual(chip['location'], '川崎市幸区, 神奈川県, Japan')
        self.assertEqual(experience.evaluate(chip['title'], chip['raw']['description'])['required_experience_years'], 3)
        # Accounting is listed but not worth a detail request.
        self.assertNotIn('https://hrmos.co/pages/example/jobs/000600001', asked)
        self.assertEqual(jobs['000600001']['location'], '首都圏, Japan')

    def test_hrmos_place_is_the_tag_that_names_one(self):
        """Tag lists as each board printed them on 2026-10-23: the second tag
        was taken as the place, and read 技術系, DX・ITシステム or a company."""
        from operation1million.collector import hrmos_place
        for tags, place in (
                (['技術職', '首都圏', '正社員'], '首都圏'),
                (['ソフトウェア開発', '技術系', '正社員', '群馬県邑楽郡明和町大輪336-1'], '群馬県邑楽郡'),
                (['愛知県（刈谷市）', 'DX・ITシステム', '正社員', '愛知県刈谷市朝日町2丁目1番地'], '愛知県'),
                (['障がい者採用', '東京エレクトロン株式会社', '正社員', '東京都港区赤坂赤坂Ｂｉｚタワー 他(1)'], '東京都港区'),
                (['生産企画本部', '品質保証', '正社員', '広丘事業所 (長野県：塩尻市)'], '長野県'),
                (['【技術系】AI技術', '全国（複数拠点）', '研究開発本部', '正社員'], '全国'),
                (['ソフトウェア開発', '技術系', '正社員', ''], '')):
            with self.subTest(tags=tags):
                self.assertEqual(hrmos_place(tags), place)

    def test_jposting_lists_from_json_and_reads_requirements_from_the_page(self):
        source = Source('jposting:example', 'company_sources', 'kioxia', 'Kioxia', 'jposting',
                        'https://api.example.com/example/u/jobs.phtml',
                        {'board': 'https://example.jposting.net/joblist/',
                         'detail': 'https://example.jposting.net/u/job.phtml?job_code=',
                         'encoding': 'euc-jp', 'country': 'Japan'})
        detail = (FIXTURES / 'jposting_detail_redacted.html').read_bytes()

        class Page:
            encoding = None
            @property
            def text(self):
                return detail.decode(self.encoding or 'latin-1')

        c, asked = self.collector(source, {})

        def fetch(url, *unused):
            asked.append(url)
            if 'jobs.phtml' in url:
                return Response(text=fixture('jposting_list_redacted.json'))
            return Page()
        c.fetch = fetch
        self.assertEqual(c.run(), ('complete', ''))
        self.assertEqual(c.session.headers['Referer'], 'https://example.jposting.net/joblist/')
        self.assertIn('job_items%5B%5D=description', asked[0].replace('[]', '%5B%5D'))
        jobs = {job['source_job_id']: job for job in c.jobs}
        chip = jobs['786']
        self.assertEqual(chip['url'], 'https://example.jposting.net/u/job.phtml?job_code=786')
        self.assertTrue(location.in_asia_tab(chip['location']))
        self.assertEqual(experience.evaluate(chip['title'], chip['raw']['description'])['required_experience_years'], 5)
        self.assertNotIn('https://example.jposting.net/u/job.phtml?job_code=880', asked)
        # The board's links to its other job families are not this posting's duties.
        self.assertNotIn('職種紹介をみる', chip['raw']['description'])

    def test_a_talentio_home_listing_nothing_is_partial(self):
        source = Source('talentio:example', 'company_sources', 'preferred_networks', 'Preferred Networks',
                        'talentio', 'https://open.talentio.com/r/1/c/example',
                        {'homes': ['https://open.talentio.com/r/1/c/example/homes/1']})
        c, _ = self.collector(source, {})
        c.fetch = lambda *unused: Response(text='<div data-react-props="{&quot;previewMode&quot;: false}"></div>')
        self.assertEqual(c.run(), ('partial', 'Talentio homes listed no postings'))


class Page(SimpleNamespace):
    """A response with bytes, text and headers, as the 2026-10-23 readers use."""
    def json(self):
        return json.loads(self.content)

    @property
    def text(self):
        return self.content.decode('utf-8')


class OwnReaderTests(JapanBoardTests):
    """The boards that needed a reader of their own (2026-10-23)."""

    def board(self, source, pages):
        c, asked = self.collector(source, {})

        def fetch(url, *unused):
            asked.append(url)
            for marker, (name, headers) in pages.items():
                if marker in url:
                    return Page(content=(FIXTURES / name).read_bytes(), url=url, headers=headers or {})
            raise AssertionError(f'unexpected request {url}')
        c.fetch = fetch
        return c, asked

    def test_jposting_html_list_reads_every_row_shape(self):
        source = Source('jposting:example', 'company_sources', 'mitsubishi_electric', 'Mitsubishi Electric',
                        'jposting', 'https://example.jposting.net/u/job.phtml',
                        {'list': 'html', 'detail': 'https://example.jposting.net/u/job.phtml?job_code=',
                         'encoding': 'euc-jp', 'country': 'Japan'})
        c, asked = self.board(source, {'job_code=': ('jposting_html_detail_redacted.html', None),
                                       'job.phtml': ('jposting_html_list_redacted.html', None)})
        self.assertEqual(c.run(), ('complete', ''))
        jobs = {job['source_job_id']: job for job in c.jobs}
        # One posting per code, though 104 is linked twice.
        self.assertEqual(set(jobs), {'101', '102', '103', '104'})
        self.assertEqual(jobs['101']['title'], '【東京】LSI論理設計エンジニア【半導体事業部】')
        self.assertEqual(jobs['102']['title'], '102 経理担当_EN')
        self.assertEqual(jobs['102']['location'], '東京都港区（本社）, Japan')
        self.assertEqual(jobs['103']['title'], '半導体材料の品質保証担当')
        self.assertEqual(jobs['103']['location'], '工場A （三重県四日市市）, Japan')
        self.assertEqual(jobs['104']['title'], 'RFモジュールのデジタル回路設計')
        # A likely title's page is read, decoded as EUC-JP whatever it declares,
        # and its 勤務地 replaces the list's place; an accountant's is not read.
        chip = jobs['101']
        self.assertTrue(chip['raw']['description'].startswith('職務内容'))
        self.assertEqual(chip['location'], '神奈川県鎌倉市, Japan')
        self.assertEqual(experience.evaluate(chip['title'], chip['raw']['description'])['required_experience_years'], 3)
        self.assertNotIn('https://example.jposting.net/u/job.phtml?job_code=102', asked)

    def test_sonar_reads_rows_and_checks_the_stated_count(self):
        source = Source('sonar:example', 'company_sources', 'honda', 'Honda', 'sonar',
                        'https://example.snar.jp/index.aspx', {'country': 'Japan'})
        c, asked = self.board(source, {'snar.jp': ('sonar_list_redacted.html', None)})
        self.assertEqual(c.run(), ('complete', ''))
        self.assertEqual(asked, ['https://example.snar.jp/index.aspx'])
        titles = [job['title'] for job in c.jobs]
        # The information heading is not a posting.
        self.assertEqual(titles, ['車載SoCのデジタル回路設計', '【55】_HM_経理・財務', '【55】_HM_経理・財務'])
        chip = c.jobs[0]
        self.assertEqual(chip['location'], '愛知本社（愛知県刈谷市）; 東京都港区, Japan')
        self.assertIn('SoCの論理設計と検証', chip['raw']['description'])
        self.assertIn('タグ: 回路設計', chip['raw']['description'])
        self.assertNotIn('［more］', chip['raw']['description'])
        # Two rows of one title keep two identities.
        self.assertEqual(len({job['url'] for job in c.jobs}), 3)
        self.assertTrue(c.jobs[2]['url'].endswith('~2'))

    def test_sonar_printing_fewer_rows_than_it_states_is_partial(self):
        source = Source('sonar:example', 'company_sources', 'honda', 'Honda', 'sonar',
                        'https://example.snar.jp/index.aspx', {'country': 'Japan'})
        c, _ = self.board(source, {})
        page = fixture('sonar_list_redacted.html').replace('value="3"', 'value="524"')
        c.fetch = lambda *unused: Page(content=page.encode('utf-8'), url='', headers={})
        self.assertEqual(c.run(), ('partial', 'sonar board printed 3 of 524 postings it states'))

    def test_axol_reads_the_list_then_a_likely_page(self):
        source = Source('axol:example', 'company_sources', 'rohm', 'ROHM', 'axol',
                        'https://job.axol.jp/hy/c/example/job/list', {'country': 'Japan'})
        c, asked = self.board(source, {'/job/detail/': ('axol_detail_redacted.html', None),
                                       '/job/list': ('axol_list_redacted.html', None)})
        self.assertEqual(c.run(), ('complete', ''))
        jobs = {job['title']: job for job in c.jobs}
        self.assertEqual(set(jobs), {'キャリア登録', '【京都】LSIのデジタル回路設計', '【東京】営業（日系車載）'})
        chip = jobs['【京都】LSIのデジタル回路設計']
        self.assertEqual(chip['url'], 'https://job.axol.jp/hy/c/example/job/detail/BBBB2222')
        self.assertEqual(chip['location'], '京都府, Japan')
        self.assertEqual(experience.evaluate(chip['title'], chip['raw']['description'])['required_experience_years'], 3)
        self.assertEqual(asked, ['https://job.axol.jp/hy/c/example/job/list',
                                 'https://job.axol.jp/hy/c/example/job/detail/BBBB2222'])

    def test_axol_reads_the_info_template_of_a_public_board(self):
        """Keyence's public board prints its pages as `info__*` items, and all
        five likely pages failed as having no labelled items (2026-10-23)."""
        source = Source('axol:example', 'company_sources', 'keyence', 'Keyence', 'axol',
                        'https://job.axol.jp/hy/c/example/job/list', {'country': 'Japan'})
        c, _ = self.board(source, {'/job/detail/': ('axol_detail_info_redacted.html', None),
                                   '/job/list': ('axol_list_redacted.html', None)})
        self.assertEqual(c.run(), ('complete', ''))
        chip = {job['title']: job for job in c.jobs}['【京都】LSIのデジタル回路設計']
        self.assertEqual(chip['location'], '大阪府大阪市, Japan')
        self.assertEqual(experience.evaluate(chip['title'], chip['raw']['description'])['required_experience_years'], 2)

    def test_an_axol_list_saying_nothing_is_open_is_complete_and_a_blank_one_is_not(self):
        source = Source('axol:example', 'company_sources', 'shimadzu', 'Shimadzu', 'axol',
                        'https://axol.jp/zw/c/example/job/list', {})
        c, _ = self.board(source, {'/job/list': ('axol_empty_redacted.html', None)})
        self.assertEqual(c.run(), ('complete', ''))
        c, _ = self.board(source, {})
        c.fetch = lambda *unused: Page(content=b'<html><body></body></html>', url='', headers={})
        self.assertEqual(c.run(), ('partial', 'axol list linked no postings'))

    def test_zookeep_reads_only_its_company_from_the_shared_sitemap(self):
        source = Source('zookeep:example', 'company_sources', 'sony_semiconductor_solutions',
                        'Sony Semiconductor Solutions', 'zookeep',
                        'https://app.zookeep.com/sitemap-career_site_job_postings.xml',
                        {'sitemap_prefix': 'https://app.zookeep.com/career/example/'})
        c, asked = self.board(source, {
            'sitemap': ('zookeep_sitemap_redacted.xml', {'content-type': 'application/xml'}),
            '/career/example/': ('zookeep_job_redacted.html', {'content-type': 'text/html'})})
        self.assertEqual(c.run(), ('complete', ''))
        self.assertNotIn('https://app.zookeep.com/career/othercompany/demo-job-863', asked)
        [job] = c.jobs
        # The provider's double space is kept as received.
        self.assertEqual(job['title'], 'DS_A0101  【厚木】LSIのFAE')
        self.assertEqual(job['location'], '神奈川県厚木市, Japan')
        self.assertEqual(job['posted_at'], '2026-05-14')

    def test_a_zookeep_place_without_its_country_is_read_in_the_sources(self):
        """Sony Group's postings name 「汐留（港区）」 alone (2026-10-23)."""
        source = Source('zookeep:example', 'company_sources', 'sony_group', 'Sony Group', 'zookeep',
                        'https://app.zookeep.com/sitemap-career_site_job_postings.xml',
                        {'sitemap_prefix': 'https://app.zookeep.com/career/example/', 'country': 'Japan'})
        page = fixture('zookeep_job_redacted.html').replace(
            '"addressLocality": "神奈川県厚木市", "addressCountry": "Japan"', '"addressLocality": "汐留（港区）"')
        c, _ = self.board(source, {
            'sitemap': ('zookeep_sitemap_redacted.xml', {'content-type': 'application/xml'})})
        fetch = c.fetch
        c.fetch = lambda url, *rest: (Page(content=page.encode('utf-8'), url=url, headers={'content-type': 'text/html'})
                                      if '/career/example/' in url else fetch(url, *rest))
        self.assertEqual(c.run(), ('complete', ''))
        self.assertEqual(c.jobs[0]['location'], '汐留（港区）, Japan')
        self.assertTrue(location.in_japan(c.jobs[0]['location']))

    def test_herp_reads_the_cards_then_a_likely_page(self):
        source = Source('herp:example', 'company_sources', 'arkedge_space', 'ArkEdge Space', 'herp',
                        'https://herp.careers/v1/example', {'country': 'Japan'})
        c, asked = self.board(source, {'/v1/example/AAAA': ('herp_job_redacted.html', None),
                                       '/v1/example': ('herp_list_redacted.html', None)})
        self.assertEqual(c.run(), ('complete', ''))
        jobs = {job['source_job_id']: job for job in c.jobs}
        # Cards only, each once; a group's link is not a posting.
        self.assertEqual(set(jobs), {'AAAA1111bbbb', 'CCCC2222dddd'})
        chip = jobs['AAAA1111bbbb']
        self.assertEqual(chip['url'], 'https://herp.careers/v1/example/AAAA1111bbbb')
        self.assertEqual(chip['location'], '有明オフィス（東京都江東区） ※基本オフィス出社, Japan')
        self.assertTrue(location.in_japan(chip['location']))
        self.assertEqual(experience.evaluate(chip['title'], chip['raw']['description'])['required_experience_years'], 2)
        self.assertEqual(jobs['CCCC2222dddd']['location'], 'Japan')
        self.assertNotIn('https://herp.careers/v1/example/CCCC2222dddd', asked)

    def test_wordpress_lists_from_rest_and_reads_a_likely_page(self):
        source = Source('wordpress:example', 'company_sources', 'rapidus', 'Rapidus', 'wordpress',
                        'https://www.example.inc/recruit/wp-json/wp/v2/career',
                        {'place_taxonomy': 'work_location_cat', 'abroad': ['海外'], 'country': 'Japan'})
        c, asked = self.board(source, {
            'work_location_cat?': ('wordpress_terms_redacted.json', None),
            '/v2/career?': ('wordpress_list_redacted.json', {'X-WP-Total': '2', 'X-WP-TotalPages': '1'}),
            '/recruit/experienced/': ('wordpress_page_redacted.html', None)})
        self.assertEqual(c.run(), ('complete', ''))
        jobs = {job['source_job_id']: job for job in c.jobs}
        mask = jobs['101']
        self.assertEqual(mask['title'], '（設計部）デジタル回路設計エンジニア')
        self.assertEqual(mask['location'], '北海道, Japan')
        self.assertTrue(mask['raw']['description'].startswith('職務内容'))
        # An entity in the REST title is the character; abroad is not Japan.
        self.assertEqual(jobs['102']['title'], '（Example US）Executive Assistant – Bilingual')
        self.assertEqual(jobs['102']['location'], '')
        self.assertNotIn('https://www.example.inc/recruit/experienced/us-assistant/', asked)

    def test_wordpress_short_of_its_stated_total_is_partial(self):
        source = Source('wordpress:example', 'company_sources', 'rapidus', 'Rapidus', 'wordpress',
                        'https://www.example.inc/recruit/wp-json/wp/v2/career', {})
        c, _ = self.board(source, {
            '/v2/career?': ('wordpress_list_redacted.json', {'X-WP-Total': '267', 'X-WP-TotalPages': '1'})})
        with patch('operation1million.job_details.candidate', return_value=False):
            self.assertEqual(c.run(), ('partial', 'WordPress listed 2 of 267 postings it states'))


if __name__ == '__main__':
    unittest.main()
