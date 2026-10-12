"""Japanese titles and descriptions, now that Japan passes the location filter.

The phrases are Renesas's and PFN's own, read from their public boards on
2026-10-11; before this, every Japanese title scored 0 and every Japanese
experience line was read as unknown.
"""
import unittest

from operation1million import experience, jsearch, location, ranking


class JapaneseTitleTests(unittest.TestCase):
    def setUp(self):
        self.rules = jsearch.load_plan()[0]['filter']

    def reason(self, title):
        return jsearch.rejection_reason({'title': title, 'raw': {}}, self.rules)

    def score(self, title):
        return jsearch.relevance({'title': title, 'raw': {}}, self.rules)[0]

    def test_chip_design_titles_pass_and_score(self):
        for title in ('デジタル回路設計エンジニア', 'LSI設計エンジニア（新卒）', '論理設計・検証エンジニア',
                      'AI半導体 (MN-Core) ASICフロントエンド設計エンジニア',
                      'Design Verification Engineer（SoC機能検証エンジニア）(1)'):
            with self.subTest(title=title):
                self.assertEqual(self.reason(title), '')
                self.assertGreaterEqual(self.score(title), self.rules['min_confidence'])

    def test_levels_mid_career_and_other_functions_are_refused(self):
        for title in ('シニアLSI設計エンジニア', '【経験者採用】デジタル回路設計', 'キャリア採用 SoC設計',
                      '課長 デジタル回路設計', '営業'):
            with self.subTest(title=title):
                self.assertEqual(self.reason(title), 'excluded')

    def test_analog_process_and_manufacturing_are_refused_as_in_english(self):
        for title in ('アナログ回路設計エンジニア', '製造技術エンジニア', '半導体プロセスエンジニア'):
            with self.subTest(title=title):
                self.assertEqual(self.reason(title), 'title_mismatch')
        self.assertEqual(self.reason('Analog Circuit Design Engineer'), 'title_mismatch')


class JapaneseRankingTests(unittest.TestCase):
    def test_new_graduate_design_is_the_first_band(self):
        for title in ('LSI設計エンジニア（新卒）', '2027年卒 デジタル回路設計'):
            with self.subTest(title=title):
                self.assertEqual(ranking.bucket(title), 0)
                self.assertTrue(ranking.early_career(title))

    def test_the_trade_and_its_neighbourhood(self):
        self.assertEqual(ranking.bucket('AI半導体 (MN-Core) ASICフロントエンド設計エンジニア'), 2)
        self.assertEqual(ranking.bucket('SoC機能検証エンジニア'), 2)
        self.assertEqual(ranking.bucket('組込ソフトウェアエンジニア'), 3)


class AsiaTabTests(unittest.TestCase):
    """Japan and China (with Hong Kong and Macau) on a Review tab of their own;
    not Taiwan (the user, 2026-10-11)."""

    def test_japan_and_china_by_city_country_or_japanese_script(self):
        for place in ('Kawasaki', 'Kodaira', 'Japan-Yokohama', 'Tokyo, Japan', '東京都', '神奈川県川崎市',
                      'Hiroshima, JP', 'Shanghai, China', 'Hong Kong'):
            with self.subTest(place=place):
                self.assertTrue(location.in_asia_tab(place))

    def test_not_taiwan_the_us_or_an_unreadable_place(self):
        for place in ('Hsinchu, Taiwan', 'Taipei, Taiwan, Republic of China', 'Austin, TX',
                      'Austin, TX; Tokyo, Japan', 'Remote', '', 'Bangalore, India'):
            with self.subTest(place=place):
                self.assertFalse(location.in_asia_tab(place))


class JapaneseExperienceTests(unittest.TestCase):
    def years(self, text):
        return experience.evaluate('エンジニア', text)['required_experience_years']

    def test_the_forms_renesas_writes(self):
        self.assertEqual(self.years('・アナログ回路設計経験3年以上'), 3)
        self.assertEqual(self.years('組み込みハードウェアおよびシステム設計・検証の領域における3年以上の実務経験。'), 3)
        self.assertEqual(self.years('・半導体後工程（組立・パッケージング）の技術開発経験（5年以上）'), 5)
        self.assertEqual(self.years('部門間調整業務等の経験が3年以上お持ちの方'), 3)

    def test_preferred_and_unstated_are_not_requirements(self):
        self.assertIsNone(self.years('【歓迎】FPGA開発経験3年以上'))
        self.assertIsNone(self.years('新卒採用。経験不問'))
        self.assertIsNone(self.years('Verilogの使用経験'))

    def test_english_text_is_untouched(self):
        self.assertEqual(experience.japanese_as_english('5+ years of RTL experience'),
                         '5+ years of RTL experience')


if __name__ == '__main__':
    unittest.main()
