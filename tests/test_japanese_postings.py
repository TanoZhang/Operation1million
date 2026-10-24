"""Japanese titles and descriptions, now that Japan passes the location filter.

The phrases are Renesas's and PFN's own, read from their public boards on
2026-10-11; before this, every Japanese title scored 0 and every Japanese
experience line was read as unknown.
"""
import unittest

from operation1million import experience, jsearch, location, ranking, resume_fit


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

    def test_board_entries_that_are_not_openings_are_refused(self):
        """Read from HRMOS boards on 2026-10-23; each passed the filter before."""
        for title in ('キャリア登録', 'ウェルカムバック制度', 'ジョブ・リターン', '【宮城】カムバック採用（アルムナイ）',
                      '★★★リファラル採用（社員紹介）について★★★',
                      '【若手エンジニア向け】キヤノンのキャリア＆ライフ～気軽に参加！会社説明会～',
                      '採用活動における個人情報の取り扱いに関する通知 ※こちらは求人ではございません',
                      '【11月5日】オムロン制御機器事業　応募意思不問オンラインセミナー（検査システム事業本部）',
                      '【毎月開催×オンライン】応募意思不問：デンソー会社紹介セミナー'):
            with self.subTest(title=title):
                self.assertEqual(self.reason(title), 'excluded')
        # An open position is a real application, and an event company's job is a job.
        for title in ('IT・通信・AIエンジニア向けオープンポジション（応募職種に迷う方）',
                      '【2407】大型イベント事業の企画運営ディレクター'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.excluded(title, self.rules))

    def test_experience_welcome_is_not_mid_career_hiring(self):
        """2026-10-13: 経験者歓迎 welcomes experience; it does not require it."""
        for title in ('LSIエンジニア/年間休日120日以上/経験者歓迎/設計・開発エンジニア(半導体)',
                      '【【つくばエリア】電気系エンジニア(微経験者・第二新卒)】電気・電子回路設計エンジニア',
                      '【未経験者歓迎】FPGA設計エンジニア'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.excluded(title, self.rules))
        for title in ('電気電子エンジニア/回路・LSI/経験者むけ/業界最大手', '【正社員】経験者募集。LSI設計エンジニア'):
            with self.subTest(title=title):
                self.assertTrue(jsearch.excluded(title, self.rules))

    def test_analog_process_and_manufacturing_are_refused_as_in_english(self):
        for title in ('アナログ回路設計エンジニア', '製造技術エンジニア', '半導体プロセスエンジニア'):
            with self.subTest(title=title):
                self.assertEqual(self.reason(title), 'title_mismatch')
        self.assertEqual(self.reason('Analog Circuit Design Engineer'), 'title_mismatch')


class JapaneseRankingTests(unittest.TestCase):
    def test_the_entry_level_in_japanese_is_early_career_as_in_english(self):
        """2026-10-23: "Entry Level" and "Junior" were early career and their
        Japanese -- 未経験可, 経験不問, ポテンシャル採用 -- were not, so 53 open
        titles saying so sat with the experienced openings."""
        for title in ('FPGA設計（未経験可）', '【未経験可】パッケージングエンジニア', '回路設計 経験不問',
                      '車体部品の構造設計開発担当※ポテンシャル採用', '【業界未経験・ポテンシャル歓迎】SE'):
            with self.subTest(title=title):
                self.assertTrue(ranking.early_career(title))
        # New to the industry or the function is experienced otherwise; a range
        # up to a lead is not an entry level.
        for title in ('【神戸／業界未経験歓迎】システムエンジニア', '職種未経験歓迎 FPGA',
                      '【神戸／ポテンシャル〜メンバークラス】企画', 'デジタル回路設計エンジニア'):
            with self.subTest(title=title):
                self.assertFalse(ranking.early_career(title))

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


class JapaneseResumeFitTests(unittest.TestCase):
    """A paid search in Japan (2026-10-11): 「LSI論理回路設計・検証エンジニア」 and
    others were refused for naming no supported duty, the profile being English."""

    PROFILE = {'version': 1, 'gaps': [], 'families': [
        {'id': 'rtl', 'evidence': 'synthetic',
         'all': [r'\b(?:RTL|logic\s+design|digital\s+(?:design|circuits?)|SoCs?)\b',
                 r'\b(?:design\w*|verif\w*|validat\w*)\b']},
        {'id': 'circuit', 'evidence': 'synthetic',
         'all': [r'\bcircuit\s+design\b', r'\b(?:design|layout)\b']}]}
    DUTIES = ('LSIの論理回路設計と機能検証を担当していただきます。仕様検討からRTL設計、'
              'シミュレーションによる検証、試作後の評価まで一連の工程に携わります。' * 3)

    def assess(self, text, title='LSI論理回路設計・検証エンジニア'):
        return resume_fit.assess({'title': title, 'raw': {'description': text}}, self.PROFILE)

    def test_japanese_duties_meet_the_english_profile(self):
        result = self.assess(self.DUTIES)
        self.assertEqual(result['verdict'], 'keep')
        self.assertIn('rtl', result['evidence'])

    def test_circuit_design_counts_only_beside_a_chip(self):
        equipment = '製造装置の回路設計と制御基板の開発を担当していただきます。' * 6
        self.assertNotIn('circuit design', resume_fit.glossed(equipment))
        self.assertIn('circuit design', resume_fit.glossed('DRAMの回路設計を担当します。'))

    def test_english_text_is_untouched(self):
        self.assertEqual(resume_fit.glossed('RTL design and verification'), 'RTL design and verification')


class JapanSweepPlanTests(unittest.TestCase):
    def test_measured_phrases_page_to_their_own_depth(self):
        settings, _ = jsearch.load_plan()
        depth = {q.query: q.pages for q in settings['sweep_queries']}
        self.assertEqual(depth['論理回路 設計 エンジニア'], 150)
        self.assertEqual(depth['回路設計 新卒'], settings['backfill_tier_pages']['new_grad'])
        # The first sweep (2026-10-13) found nothing under the regional splits
        # and filtered out everything 半導体 新卒 returned.
        self.assertFalse({f'LSI 設計 {region}' for region in ('東京', '神奈川', '大阪', '京都', '愛知', '福岡')} & set(depth))
        self.assertNotIn('半導体 新卒', depth)
        # Kept by the second sweep (2026-10-13): 「<field> 未経験」 did best;
        # no インターン phrase found anything in Japan.
        self.assertEqual(depth['SoC 未経験'], settings['backfill_tier_pages']['new_grad'])
        self.assertFalse(any('インターン' in q for q in depth))
        # A bare trade word and English returned nothing in Japan.
        self.assertNotIn('デジタル回路設計', depth)
        self.assertFalse(any(q.isascii() for q in depth))

    def test_a_depth_past_the_runaway_guard_is_refused(self):
        import tempfile
        from pathlib import Path
        from operation1million.paths import CONFIG
        text = (CONFIG / 'jsearch_queries.toml').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plan.toml'
            path.write_text(text + '\n[[sweep_query]]\nquery = "LSI 深すぎ"\ntier = "A"\npages = 999\n',
                            encoding='utf-8')
            with self.assertRaises(ValueError):
                jsearch.load_plan(path)


class JapanSearchLocationTests(unittest.TestCase):
    def test_a_result_placed_only_in_job_location_is_in_japan(self):
        # JSearch in Japan, 2026-10-11: city, state and country empty, the
        # place written with its publisher in job_location.
        item = {'job_id': 'jp1', 'job_title': 'LSI論理回路設計・検証エンジニア', 'employer_name': 'Example',
                'job_apply_link': 'https://jp.indeed.com/viewjob?jk=1', 'job_city': None,
                'job_state': None, 'job_country': None,
                'job_location': '愛知県     •  提供元: Indeed.com'}
        row = jsearch.normalize_job(item, jsearch.Query('LSI 検証 エンジニア', 1, 'A'), {})
        self.assertEqual(row['location'], '愛知県')
        self.assertTrue(location.in_asia_tab(row['location']))


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

    def test_a_posting_printed_on_one_line_is_read_sentence_by_sentence(self):
        """ABLIC's HRMOS list excerpt (2026-10-23): the closing 「あれば尚可」 made
        the whole line preferred, and 「法人営業経験3年以上」 read as no requirement."""
        self.assertEqual(self.years(
            '業務内容 ・提案営業活動。 経験・必要スキル ・法人営業経験3年以上（電子部品・半導体業界尚可）。 '
            '・提案書作成能力。 など 語学力の有無 あれば尚可'), 3)
        # Canon's: what is required, then what is desirable, on one line.
        self.assertEqual(self.years('必要な経験/スキル 電気設備管理・保全業務の実務経験３年以上 '
                                    'あると望ましい経験/スキル 電気主任技術者'), 3)
        # A recommended database is not a preference for the years.
        self.assertEqual(self.years('【必須】\n・データベース設計に関する実務経験(3年以上, 推奨DB PostgreSQL)'), 3)

    def test_desirable_years_and_a_products_history_are_not_requirements(self):
        self.assertIsNone(self.years('・ソフトウェアテストの実務経験（3年以上が望ましい）'))
        self.assertIsNone(self.years('マーケティング経験がある（5年以上程度が望ましいが、必須条件ではない）'))
        self.assertIsNone(self.years('GVIFはソニー独自規格です。20年以上の歴史がある製品です。'))

    def test_english_text_is_untouched(self):
        self.assertEqual(experience.japanese_as_english('5+ years of RTL experience'),
                         '5+ years of RTL experience')


if __name__ == '__main__':
    unittest.main()
