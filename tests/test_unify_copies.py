"""One job found on several sites is one group (asked for on 2026-10-04)."""
import unittest

from operation1million.applications import employer_name, unify_copies


def group(key, *jobs):
    return key, {'id': key, 'company': jobs[0]['company'], 'title': jobs[0]['title'],
                 'confidence': 50, 'bucket': 0, 'flagged': False,
                 'internship_experience': False, 'jobs': list(jobs)}


def job(url, company, title, place='', provider='jsearch'):
    return {'url': url, 'company': company, 'title': title, 'location': place,
            'provider_key': provider}


def undecided(_job):
    return None


class UnifyCopiesTests(unittest.TestCase):
    def test_a_paid_copy_joins_the_company_posting_despite_suffix_and_punctuation(self):
        recent = dict([
            group('wd', job('https://marvell.wd1.myworkdayjobs.com/x_2604513', 'Marvell Technology, Inc.',
                            'Firmware Engineer Intern, MS - Summer 2027', 'Santa Clara, CA', 'workday')),
            group('li', job('https://www.linkedin.com/jobs/view/1', 'Marvell Technology',
                            'Firmware Engineer Intern, MS, Summer 2027')),
        ])
        unify_copies(recent, {}, undecided)
        self.assertEqual(list(recent), ['wd'])
        self.assertEqual(len(recent['wd']['jobs']), 2)

    def test_a_title_listed_per_city_takes_the_copy_only_by_its_city(self):
        recent = dict([
            group('a', job('https://jobs.apple.com/1', 'Apple', 'VLSI CAD Engineer', 'Cupertino', 'apple_jobs')),
            group('b', job('https://jobs.apple.com/2', 'Apple', 'VLSI CAD Engineer', 'Austin', 'apple_jobs')),
            group('c', job('https://www.linkedin.com/jobs/view/3', 'Apple Inc.', 'VLSI CAD Engineer',
                           'Austin, Texas, US')),
        ])
        unify_copies(recent, {}, undecided)
        self.assertEqual(sorted(recent), ['a', 'b'])
        self.assertEqual([item['url'] for item in recent['b']['jobs']][-1],
                         'https://www.linkedin.com/jobs/view/3')

    def test_a_copy_that_could_be_either_requisition_stays_apart(self):
        recent = dict([
            group('a', job('https://careers.amd.com/jobs/87526', 'AMD', 'RTL Design Engineer', 'Austin', 'amd_careers')),
            group('b', job('https://careers.amd.com/jobs/92475', 'AMD', 'RTL Design Engineer', 'Austin', 'amd_careers')),
            group('c', job('https://www.linkedin.com/jobs/view/3', 'AMD', 'RTL Design Engineer', 'Austin, Texas, US')),
            group('d', job('https://www.indeed.com/viewjob?jk=4', 'AMD', 'RTL Design Engineer', '')),
        ])
        unify_copies(recent, {}, undecided)
        self.assertEqual(sorted(recent), ['a', 'b', 'c', 'd'])

    def test_company_requisitions_with_one_title_are_never_merged_with_each_other(self):
        recent = dict([
            group('a', job('https://careers.amd.com/jobs/87526', 'AMD', 'RTL Design Engineer', 'Austin', 'amd_careers')),
            group('b', job('https://careers.amd.com/jobs/92475', 'AMD', 'RTL Design Engineer', 'Austin', 'amd_careers')),
        ])
        unify_copies(recent, {}, undecided)
        self.assertEqual(sorted(recent), ['a', 'b'])

    def test_a_copy_naming_another_city_than_the_company_posting_stays_apart(self):
        recent = dict([
            group('wd', job('https://sample.wd5.myworkdayjobs.com/x_JR1', 'Sample', 'RTL Engineer',
                            'Austin, TX', 'workday')),
            group('li', job('https://www.linkedin.com/jobs/view/1', 'Sample', 'RTL Engineer',
                            'Boston, Massachusetts, US')),
            group('many', job('https://sample.wd5.myworkdayjobs.com/x_JR2', 'Other', 'DV Engineer',
                              '3 Locations', 'workday')),
            group('in', job('https://www.indeed.com/viewjob?jk=2', 'Other', 'DV Engineer',
                            'Boston, Massachusetts, US')),
        ])
        unify_copies(recent, {}, undecided)
        # "3 Locations" names no city, so it can be Boston; Austin cannot.
        self.assertEqual(sorted(recent), ['li', 'many', 'wd'])

    def test_paid_listings_of_one_job_in_one_city_are_one_group(self):
        recent = dict([
            group('li', job('https://www.linkedin.com/jobs/view/1', 'NIKSUN', 'Junior Engineer, FPGA',
                            'Princeton, New Jersey, US')),
            group('in', job('https://www.indeed.com/viewjob?jk=2', 'NIKSUN, Inc.', 'Junior Engineer FPGA',
                            'Princeton, New Jersey, US')),
        ])
        unify_copies(recent, {}, undecided)
        self.assertEqual(len(recent), 1)

    def test_a_listing_naming_no_city_joins_the_one_that_does_but_not_one_of_several(self):
        one = dict([
            group('li', job('https://www.linkedin.com/jobs/view/1', 'Optiver', 'FPGA Engineer Intern', 'Austin, Texas, US')),
            group('hv', job('https://careerservices.fas.harvard.edu/jobs/2', 'Optiver', 'FPGA Engineer Intern', 'US')),
        ])
        unify_copies(one, {}, undecided)
        self.assertEqual(len(one), 1)
        several = dict([
            group('a', job('https://www.linkedin.com/jobs/view/1', 'Intel', 'Physical Design Engineer', 'Phoenix, Arizona, US')),
            group('b', job('https://www.linkedin.com/jobs/view/2', 'Intel', 'Physical Design Engineer', 'Boxborough, Massachusetts, US')),
            group('c', job('https://www.indeed.com/viewjob?jk=3', 'Intel', 'Physical Design Engineer', '')),
        ])
        unify_copies(several, {}, undecided)
        self.assertEqual(len(several), 3)

    def test_an_application_through_a_copy_covers_the_company_posting(self):
        recent = dict([
            group('wd', job('https://intel.wd1.myworkdayjobs.com/x_JR1', 'Intel', 'Silicon Intern', 'Hillsboro', 'workday')),
        ])
        backlog = dict([
            group('sim', job('https://simplify.jobs/p/1', 'Intel Corporation', 'Silicon Intern')),
        ])

        def decided(item):
            return {'status': 'applied'} if 'simplify' in item['url'] else None

        covered = unify_copies(recent, backlog, decided)
        self.assertEqual(covered, {'wd'})
        self.assertEqual(backlog, {})

    def test_a_recent_copy_brings_its_older_company_posting_into_the_recent_tab(self):
        recent = dict([group('li', job('https://www.linkedin.com/jobs/view/1', 'MatX', 'AI Silicon Architect',
                                       'Mountain View, California, US'))])
        backlog = dict([group('ash', job('https://jobs.ashbyhq.com/matx/1', 'MatX', 'AI Silicon Architect',
                                         'Mountain View (HQ) or Remote', 'ashby'))])
        unify_copies(recent, backlog, undecided)
        self.assertEqual(list(recent), ['ash'])
        self.assertEqual(backlog, {})

    def test_early_career_namesakes_in_the_same_place_are_one_group(self):
        # Asked for on 2026-10-05: Micron listed "New College Grad - ENG, HIG
        # HBM PSE Design Validation" twice in Boise under two job numbers.
        title = 'New College Grad - ENG, HIG HBM PSE Design Validation'
        recent = dict([
            group('a', job('https://careers.micron.com/careers/job/44701529', 'Micron Technology, Inc.',
                           title, 'Boise, Idaho, United States of America', 'eightfold')),
            group('b', job('https://careers.micron.com/careers/job/44702722', 'Micron Technology, Inc.',
                           title, 'Boise, Idaho, United States of America', 'eightfold')),
        ])
        unify_copies(recent, {}, undecided)
        self.assertEqual(len(recent), 1)
        self.assertEqual(len(next(iter(recent.values()))['jobs']), 2)

    def test_early_career_namesakes_in_other_places_stay_apart(self):
        title = 'Silicon Technology Research Scientist Intern - 2027'
        recent = dict([
            group('a', job('https://ibm.test/1', 'IBM', title, 'Yorktown Heights, NY', 'ibm')),
            group('b', job('https://ibm.test/2', 'IBM', title, 'Albany, NY', 'ibm')),
        ])
        unify_copies(recent, {}, undecided)
        self.assertEqual(sorted(recent), ['a', 'b'])

    def test_experienced_namesakes_in_one_place_stay_apart(self):
        # KLA had about fifteen "Product Development Engineer" openings in Milpitas.
        recent = dict([
            group('a', job('https://kla.test/2638951', 'KLA', 'Product Development Engineer', 'Milpitas, CA', 'workday')),
            group('b', job('https://kla.test/2634749', 'KLA', 'Product Development Engineer', 'Milpitas, CA', 'workday')),
        ])
        unify_copies(recent, {}, undecided)
        self.assertEqual(sorted(recent), ['a', 'b'])

    def test_a_skipped_namesake_is_not_folded_into_an_open_one(self):
        # A skip answers its own opening only; merging would let it hide the other.
        recent = dict([
            group('a', job('https://micron.test/1', 'Micron', 'Intern - DRAM Design Engineer', 'Boise, ID', 'eightfold')),
            group('b', job('https://micron.test/2', 'Micron', 'Intern - DRAM Design Engineer', 'Boise, ID', 'eightfold')),
        ])

        def decided(item):
            return {'status': 'skipped'} if item['url'].endswith('/1') else None

        covered = unify_copies(recent, {}, decided)
        self.assertEqual(sorted(recent), ['a', 'b'])
        self.assertEqual(covered, set())

    def test_employer_name_drops_the_legal_suffix_only(self):
        self.assertEqual(employer_name('NIKSUN, Inc.'), 'niksun')
        self.assertEqual(employer_name('QUALCOMM Incorporated'), 'qualcomm')
        self.assertEqual(employer_name('Advanced Micro Devices, Inc.'), 'amd')


if __name__ == '__main__':
    unittest.main()
