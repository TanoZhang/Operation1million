"""Which postings are located only outside the United States.

Asked for on 2026-09-22: a posting located only abroad is not worth reviewing,
one also offered in the U.S. is. Every string below is a format measured in
the live queue that day.
"""
import unittest

from jobdisco.location import country, outside_us


class CountryTests(unittest.TestCase):
    def test_places_abroad(self):
        for text in ('IN, KA, Bengaluru', 'Bangalore, India', 'Bengaluru, IN', 'GB, London',
                     'DE, RP, Neuwied', 'Singapore, Singapore', 'Taichung City, Taichung City, Taiwan',
                     'Hiroshima, Japan', 'Alajuela, CR', 'Hsinchu City, Taiwan; Seoul, Korea, Republic of',
                     'Tianjin (Weiwu)', 'AU, VIC, Melbourne'):
            with self.subTest(text=text):
                self.assertEqual(country(text), 'foreign')

    def test_places_in_the_united_states(self):
        for text in ('US, WA, Seattle', 'US, IN, New Carlisle', 'San Diego, California, United States of America',
                     'Location Cupertino', 'Austin, Texas', 'Dallas, TX, United States', 'Carmel, IN',
                     'Paris, TX', 'London, KY', 'Dublin, California', 'Kentucky, US', 'US Headquarters',
                     'USA-TX-Austin - River Place B7'):
            with self.subTest(text=text):
                self.assertEqual(country(text), 'us')

    def test_a_us_listing_anywhere_keeps_the_posting(self):
        self.assertFalse(outside_us('Austin, Texas; Bangalore, India'))

    def test_what_says_nothing_is_kept(self):
        for text in ('', None, '2 Locations', 'Multiple locations', 'Remote', 'Location Cambridge', 'USTER'):
            with self.subTest(text=text):
                self.assertIsNone(country(text))
                self.assertFalse(outside_us(text))


if __name__ == '__main__':
    unittest.main()
