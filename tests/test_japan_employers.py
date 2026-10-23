import unittest

from operation1million import japan_employers as japan


class ClassifyTests(unittest.TestCase):
    """The user, 2026-10-23: no time on third-tier companies in Japan."""

    def test_staffing_first_then_big_then_other(self):
        self.assertEqual(japan.classify('株式会社テクノプロ テクノプロ・デザイン社'), japan.STAFFING)
        self.assertEqual(japan.classify('株式会社アルプス技研'), japan.STAFFING)
        self.assertEqual(japan.classify('アルプスアルパイン株式会社'), japan.BIG)
        self.assertEqual(japan.classify('Ｌｉｇｈｔ ＢＲＯＴＨＥＲＳ'), japan.STAFFING)
        self.assertEqual(japan.classify('社名非公開'), japan.STAFFING)
        self.assertEqual(japan.classify('東京都 府中市'), japan.STAFFING)
        self.assertEqual(japan.classify('ソニーセミコンダクタマニュファクチャリング株式会社'), japan.BIG)
        self.assertEqual(japan.classify('SCREENホールディングス'), japan.BIG)
        self.assertEqual(japan.classify('Pharmacy Arm Co'), japan.OTHER)
        self.assertEqual(japan.classify('株式会社シキノハイテック'), japan.OTHER)
        self.assertEqual(japan.classify('株式会社サンプル', '正社員（無期雇用派遣）'), japan.STAFFING)

    def test_only_a_whole_yearly_range_under_the_floor_is_low(self):
        self.assertTrue(japan.low_pay('【年収】 250万円 〜 450万円'))
        self.assertTrue(japan.low_pay('想定年収 380万円～480万円'))
        self.assertFalse(japan.low_pay('＜予定年収＞ 480万円～1,100万円'))
        self.assertFalse(japan.low_pay('年収：400万円以上'))
        self.assertFalse(japan.low_pay('年収 400万円〜'))
        # A monthly figure alone never drops one: bonuses are not in it.
        self.assertFalse(japan.low_pay('月給 22万円〜25万円'))
        self.assertFalse(japan.low_pay(''))
