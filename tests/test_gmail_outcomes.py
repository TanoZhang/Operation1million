"""Passed / Declined read from Gmail replies (2026-10-05).

The emails below are written in the shapes employers' and ATS mail take;
none is a real message. The IMAP layer is exercised against the live
mailbox on the VPS, not here.
"""
from email.message import EmailMessage
from pathlib import Path
import tempfile
import unittest

from jobdisco import applications, gmail_outcomes as gmail

DECLINES = [
    ('Your application to NVIDIA', 'Thank you for your interest in the ASIC Design Intern role. '
     'Unfortunately, we have decided to move forward with other candidates whose experience more '
     'closely matches our needs.'),
    ('Update on your Micron application', 'After careful consideration, we will not be moving forward '
     'with your application at this time. We wish you the best in your job search.'),
    ('AMD Careers', "We regret to inform you that you have not been selected for this position."),
    ('Your application', 'The position has been filled. We will keep your resume on file for future openings.'),
    ('Thank you from Marvell', "We've decided to pursue other applicants for the RTL Design Intern role."),
    ('Application status', "We won't be moving forward with your candidacy."),
    ('Regarding your application', 'Your application was unsuccessful on this occasion.'),
    ('Your application to Etched', 'Thank you for taking the time to interview with us. Unfortunately '
     'we have decided not to proceed.'),
    ('Re: Design Verification Intern', 'The team has decided to go in a different direction for this role.'),
]
PASSES = [
    ('Interview invitation - SoC Design Intern', 'We would like to invite you to interview for the role.'),
    ('Next steps with Cisco', 'Please use the link below to schedule your interview with the hiring manager.'),
    ('Micron - Online Assessment', 'Please complete the assessment within 5 days: https://www.hackerrank.com/test/abc'),
    ('NVIDIA', 'Could you share your availability for a 30 minute phone screen next week?'),
    ('AMD Digital Interview', 'You have been invited to complete a HireVue video interview.'),
    ('Your application', "We're pleased to let you know you've been selected to move forward to the next round."),
    ('Coding challenge', 'You have been invited to a CodeSignal General Coding Assessment.'),
    ('Re: RTL Intern', 'Thanks for applying! We were impressed and would like to schedule a call. '
     'Once you have picked a time on calendly.com/recruiter, you will get a confirmation.'),
    ('Offer', 'We are pleased to offer you the position of ASIC Design Intern.'),
    ('Times', 'Here are three slots. If none of these times work, please share your availability.'),
]
CONFIRMATIONS = [
    ('Thank you for applying to NVIDIA', 'We have received your application for ASIC Design Intern. '
     'If your qualifications match our needs, a recruiter will contact you to schedule an interview.'),
    ('Application received', 'Thank you for your application. Our team will review your resume and '
     'reach out to you about next steps if there is a fit. Please complete the following voluntary '
     'self-identification survey.'),
    ('Your application was submitted', 'Congratulations on taking the first step! Candidates who are '
     'selected will be invited to a phone screen.'),
    ('We got it', 'Thanks for applying. If you are selected for an interview, a recruiter will email you.'),
]


# The shape of an Optiver confirmation the user forwarded on 2026-10-05: it
# describes the interview process and offers none.
OPTIVER = '''Hi there,

Exciting news! Your application has been received. As you get ready to embark on your candidate
journey, we'd like to share some information to help prepare you for the interview process.

Below, you'll find a knowledge hub that outlines important information from a typical day at Optiver
to our vibrant company culture, what to expect during the interview process and highlights from our
internship program.

Discover our interview process

Step 1 - Application: Submit your job application and information on our website.

Step 2 - Assessments: Our assessments test various skills, including problem-solving and critical thinking.

Step 3 - Interviews: A series of conversations where we will further assess your skills and give you
the opportunity to learn more about the role.

Our interview process is designed to be engaging and thorough. This process can vary by role.

To learn more about our interview process, visit our campus FAQ page.

Preview YouTube video Meet Rens, Graduate Derivatives Trader
'''


class ClassifyTests(unittest.TestCase):
    def test_a_description_of_the_process_is_not_an_invitation(self):
        subject = 'Prepare for your application process with Optiver'
        self.assertIsNone(gmail.classify(subject, OPTIVER))
        # Not even without the line that says it is a confirmation.
        self.assertIsNone(gmail.classify(subject, OPTIVER.replace('Your application has been received. ', '')))
        # While a real invitation from the same firm still is one.
        self.assertEqual(gmail.classify('Optiver - Next steps', 'You have been invited to complete our '
                                        'online assessment. Please complete it within 7 days.'), 'passed')

    def test_rejections_are_declined(self):
        for subject, body in DECLINES:
            self.assertEqual(gmail.classify(subject, body), 'declined', subject + ' / ' + body)

    def test_invitations_assessments_and_offers_are_passed(self):
        for subject, body in PASSES:
            self.assertEqual(gmail.classify(subject, body), 'passed', subject + ' / ' + body)

    def test_a_confirmation_is_nothing_however_much_it_mentions_interviews(self):
        for subject, body in CONFIRMATIONS:
            self.assertIsNone(gmail.classify(subject, body), subject)

    def test_an_invitation_that_also_says_unfortunately_is_not_lost(self):
        verdict = gmail.classify('Rescheduling', 'Unfortunately the interviewer is out on Tuesday. '
                                 'Please select a time that works for you.')
        self.assertEqual(verdict, 'passed')
        both = gmail.classify('Update', 'Unfortunately we will not move forward with the RTL role. '
                              'However we would like to invite you to interview for the DV role.')
        self.assertEqual(both, 'unclear')

    def test_a_vague_mention_is_listed_rather_than_dropped(self):
        self.assertEqual(gmail.classify('Quick question', 'Are you free to talk with our hiring manager this week?'),
                         'unclear')
        self.assertIsNone(gmail.classify('Your weekly digest', 'Ten new semiconductor stories.'))

    def test_courtesies_alone_are_not_a_rejection(self):
        self.assertIsNone(gmail.classify('Good luck', 'Best of luck on your exams!'))


def group(gid, company, title, at='2026-09-20T00:00:00+00:00', req=''):
    return {'id': gid, 'company': company, 'title': title, 'at': at,
            'jobs': [{'url': 'https://example.test/' + gid, 'source_job_id': req}]}


def message(subject, text='', sender='Careers <no-reply@myworkday.com>', at='2026-10-01T00:00:00+00:00',
            outcome=None, mid='m1'):
    return {'id': mid, 'from': sender, 'subject': subject, 'text': text, 'at': at, 'outcome': outcome}


class MatchTests(unittest.TestCase):
    groups = [group('n1', 'NVIDIA', 'ASIC Design Intern', req='JR1999001'),
              group('n2', 'NVIDIA', 'Deep Learning Architecture Intern', req='JR1999002'),
              group('m1', 'Micron Technology, Inc.', 'Memory Design Intern'),
              group('a1', 'Advanced Micro Devices, Inc.', 'RTL Design Intern'),
              group('c1', 'Cisco Systems, Inc.', 'ASIC Verification Intern - San Jose'),
              group('c2', 'Cisco Systems, Inc.', 'ASIC Verification Intern - San Jose')]

    def ids(self, found):
        return sorted(item['id'] for item in found)

    def test_one_application_at_the_company(self):
        self.assertEqual(self.ids(gmail.match(self.groups, message('Your Micron application'))), ['m1'])
        self.assertEqual(self.ids(gmail.match(self.groups, message('Update', sender='AMD <careers@amd.com>'))), ['a1'])

    def test_several_need_a_requisition_or_title(self):
        self.assertEqual(gmail.match(self.groups, message('Your NVIDIA application')), [])
        self.assertEqual(self.ids(gmail.match(self.groups, message('NVIDIA: JR1999002'))), ['n2'])
        self.assertEqual(self.ids(gmail.match(self.groups, message(
            'Your NVIDIA application', 'Regarding the ASIC Design Intern position'))), ['n1'])

    def test_one_title_in_several_places_is_one_role(self):
        found = gmail.match(self.groups, message('Cisco', 'your application for ASIC Verification Intern - San Jose'))
        self.assertEqual(self.ids(found), ['c1', 'c2'])

    def test_an_email_older_than_the_application_is_about_something_else(self):
        old = message('Your Micron application', at='2026-09-01T00:00:00+00:00')
        self.assertEqual(gmail.match(self.groups, old), [])

    def test_company_names(self):
        self.assertEqual(gmail.company_names('Micron Technology, Inc.'), {'micron'})
        self.assertEqual(gmail.company_names('Advanced Micro Devices, Inc.'), {'advanced micro devices', 'amd'})
        self.assertEqual(gmail.company_names('Amazon.com, Inc.'), {'amazon', 'aws'})


class DecideTests(unittest.TestCase):
    groups = MatchTests.groups

    def test_latest_email_wins_and_hand_marks_are_left_alone(self):
        messages = [message('Micron interview', outcome='passed', mid='a', at='2026-10-01T00:00:00+00:00'),
                    message('Micron update', outcome='declined', mid='b', at='2026-10-03T00:00:00+00:00'),
                    message('AMD', outcome='passed', mid='c')]
        writes, unsorted = gmail.decide(self.groups, messages, {'a1': {'id': 'a1', 'outcome': ''}})
        self.assertEqual(writes, [('m1', 'declined', 'b')])
        self.assertEqual(unsorted, [])
        again, _ = gmail.decide(self.groups, messages, {'m1': {'outcome': 'declined', 'by': 'gmail'},
                                                            'a1': {'outcome': ''}})
        self.assertEqual(again, [])

    def test_what_cannot_be_settled_is_listed(self):
        messages = [message('Your NVIDIA application', outcome='declined', mid='x'),
                    message('Micron chat?', outcome='unclear', mid='y'),
                    message('Some startup', outcome='passed', mid='z')]
        writes, unsorted = gmail.decide(self.groups, messages, {})
        self.assertEqual(writes, [])
        self.assertEqual([(item['id'], item['groups']) for item in unsorted],
                         [('x', []), ('y', ['m1']), ('z', [])])


class ParseAndStoreTests(unittest.TestCase):
    def test_html_only_mail_is_read_as_text(self):
        mail = EmailMessage()
        mail['From'] = '=?utf-8?q?Micron_Careers?= <careers@micron.com>'
        mail['Subject'] = 'Your application'
        mail['Date'] = 'Thu, 01 Oct 2026 10:00:00 -0700'
        mail.set_content('<p>Unfortunately, we have decided<br>to pursue other candidates.</p>', subtype='html')
        parsed = gmail.parse(mail.as_bytes(), '123')
        self.assertEqual(parsed['at'], '2026-10-01T17:00:00+00:00')
        self.assertIn('Micron Careers', parsed['from'])
        self.assertEqual(gmail.classify(parsed['subject'], parsed['text']), 'declined')

    def test_marks_record_who_made_them(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'application_outcomes.ndjson'
            applications.append_outcome(path, 'g', 'declined', by='gmail', message='m')
            state = {'applied': [{'id': 'g'}]}
            applications.attach_outcomes(state, applications.read_outcomes(path))
            self.assertEqual(state['applied'][0]['outcome_by'], 'gmail')
            applications.append_outcome(path, 'g', '')
            self.assertEqual(gmail.last_events(path)['g'].get('by'), None)

    def test_unsorted_reads_back_newest_first(self):
        with tempfile.TemporaryDirectory() as folder:
            gmail._save(Path(folder) / 'unsorted.json', [{'at': '1'}, {'at': '3'}, {'at': '2'}])
            self.assertEqual([item['at'] for item in gmail.read_unsorted(folder)], ['3', '2', '1'])
            self.assertEqual(gmail.read_unsorted(Path(folder) / 'missing'), [])


if __name__ == '__main__':
    unittest.main()
