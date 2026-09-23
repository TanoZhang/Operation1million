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

    def test_a_canadian_province_is_abroad_whatever_the_city_is_called(self):
        # Burlington is on the U.S. list, and "ON" is no state, so the city
        # decided and a posting in Ontario was kept as a Vermont one.
        for text in ('Burlington, ON', 'Burlington, Ontario', 'Cambridge, ON',
                     'Waterloo, Ontario', 'Montreal, QC', 'Vancouver, British Columbia'):
            with self.subTest(text=text):
                self.assertEqual(country(text), 'foreign')
        # A province name leading the string is not a region: Ontario, California.
        self.assertNotEqual(country('Ontario, CA'), 'foreign')

    def test_a_state_code_no_country_uses_is_the_state(self):
        # GA, PA, SC, MT and AL were treated as country codes too, so a city
        # sharing its name with one abroad was placed there.
        for text in ('Athens, GA', 'Athens, PA', 'Florence, SC', 'Florence, AL'):
            with self.subTest(text=text):
                self.assertEqual(country(text), 'us')

    def test_a_city_abroad_beside_another_countrys_code_is_the_state(self):
        # CA is Canada or California; Dublin is neither Canadian nor Indian.
        for text in ('Dublin, CA', 'Moscow, ID', 'Berlin, MA', 'Delhi, CA'):
            with self.subTest(text=text):
                self.assertEqual(country(text), 'us')
        for text in ('Toronto, CA', 'Munich, DE', 'Haifa, IL', 'Hyderabad, IN'):
            with self.subTest(text=text):
                self.assertEqual(country(text), 'foreign')

    def test_a_us_listing_anywhere_keeps_the_posting(self):
        self.assertFalse(outside_us('Austin, Texas; Bangalore, India'))

    def test_what_says_nothing_is_kept(self):
        for text in ('', None, '2 Locations', 'Multiple locations', 'Remote', 'Location Cambridge', 'USTER'):
            with self.subTest(text=text):
                self.assertIsNone(country(text))
                self.assertFalse(outside_us(text))


if __name__ == '__main__':
    unittest.main()


class ReportedBugTests(unittest.TestCase):
    """Reported 2026-09-22 after the rule went live."""

    def test_several_places_are_read_in_either_order(self):
        """A semicolon separates places, a comma separates a place's parts.
        Read as one string, "Oregon; Toronto" was no state and the posting was
        removed -- while the same two places the other way round were kept."""
        for text in ('Salem, Oregon; Toronto, Canada', 'Toronto, Canada; Salem, Oregon',
                     'Paris, TX; Toronto, Canada', 'Austin, Texas; Bangalore, India'):
            with self.subTest(text=text):
                self.assertEqual(country(text), 'us')
                self.assertFalse(outside_us(text))

    def test_a_country_written_out_beats_a_shared_city_name(self):
        self.assertEqual(country('Burlington, Canada'), 'foreign')
        self.assertEqual(country('Burlington, VT'), 'us')
        self.assertEqual(country('London, United Kingdom'), 'foreign')
        self.assertEqual(country('London, KY'), 'us')
