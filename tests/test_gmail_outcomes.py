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
        self.assertEqual(gmail.classify('Quick update', 'The hiring manager is still going through feedback '
                                        'from your interview.'), 'unclear')
        self.assertEqual(gmail.classify('Quick question', 'Are you free to talk with our hiring manager this week?'),
                         'passed')
        self.assertIsNone(gmail.classify('Your weekly digest', 'Ten new semiconductor stories.'))

    def test_words_inside_other_words_do_not_count(self):
        # "your interview" contains "our interview", a descriptive phrase.
        self.assertEqual(gmail.classify('Update', 'The hiring manager is still going through feedback '
                                        'from your interview.'), 'unclear')

    def test_overlapping_phrases_are_all_seen(self):
        # "we regret" (a courtesy) and "regret to inform" (a rejection) overlap.
        self.assertEqual(gmail.classify('Update', 'We regret to inform you that we cannot extend you an '
                                        'invitation to interview for this role.'), 'declined')

    def test_a_wrapped_plain_text_email_is_read_as_sentences(self):
        wrapped = ('Thank you for your application. After carefully examining your application, we regret\n'
                   'to inform you that IBM is pursuing other candidates whose expertise is more closely\n'
                   'aligned to the job requirements.\n\nSincerely,\nRecruiting')
        self.assertEqual(gmail.classify('Your IBM Application', wrapped), 'declined')

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
        writes, unsorted, stars = gmail.decide(self.groups, messages, {'a1': {'id': 'a1', 'outcome': ''}})
        self.assertEqual(writes, [('m1', 'declined', 'b')])
        self.assertEqual(unsorted, [])
        again, _, _ = gmail.decide(self.groups, messages, {'m1': {'outcome': 'declined', 'by': 'gmail'},
                                                            'a1': {'outcome': ''}})
        self.assertEqual(again, [])

    def test_what_cannot_be_settled_is_listed(self):
        messages = [message('Your NVIDIA application', outcome='declined', mid='x'),
                    message('Micron chat?', outcome='unclear', mid='y'),
                    message('Some startup', outcome='passed', mid='z')]
        writes, unsorted, stars = gmail.decide(self.groups, messages, {})
        self.assertEqual(writes, [])
        self.assertEqual([(item['id'], item['groups']) for item in unsorted],
                         [('x', ['n1', 'n2']), ('y', ['m1']), ('z', [])])
        # An invitation from a company never applied to is listed, not starred.
        self.assertEqual(stars, [])

    def test_only_the_first_pass_per_position_is_starred(self):
        messages = [message('Micron assessment', outcome='passed', mid='a', at='2026-10-01T00:00:00+00:00'),
                    message('Micron interview', outcome='passed', mid='b', at='2026-10-04T00:00:00+00:00'),
                    message('Micron update', outcome='declined', mid='c', at='2026-10-08T00:00:00+00:00')]
        writes, _, stars = gmail.decide(self.groups, messages, {})
        self.assertEqual(stars, ['a'])
        # The second round changed nothing; the later rejection did.
        self.assertEqual(writes, [('m1', 'declined', 'c')])


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


# A fixed evaluation set, kept so a rule change cannot quietly undo a fix.
# Sample emails adapted from the tests of amimrjo/Job-Application-Tracker,
# the templates of fnuAshutosh/job-email-classifier and phrases of
# Adr1an04/erga-mcp (all MIT), plus hard cases written to break the rules.
# The rules were also measured on 89 real rejections published by
# DiogoRibeiro7/Job-Rejection-Analysis (MIT): 80 of the 81 with a body read
# Declined, the 81st being a confirmation (2026-10-05). That set holds a
# stranger's mail and is not copied here.
EVALUATION = [
    # amimrjo
    (None, 'Your application to Acme Corp', 'Thank you for applying to the Software Engineer position at Acme Corp. We have received your application and will be in touch.'),
    (None, 'Quick chat about a role?', "Hi, I came across your profile on LinkedIn and think you'd be a great fit for our Backend Engineer role. Would you be open to a quick chat this week?"),
    ('passed', 'Interview invitation - Beta Inc', 'We would like to schedule an interview for the position of Data Analyst. Please use this Calendly link to pick a time.'),
    ('declined', 'Update on your application', 'Thank you for your interest in Gamma LLC. After careful consideration, we have decided to move forward with other candidates for this role.'),
    ('passed', 'Your offer from Delta Co', 'We are pleased to offer you the position of Product Manager. Please find the attached offer letter.'),
    (None, 'This week in tech', 'Here is your weekly roundup of tech news and industry trends.'),
    (None, 'New jobs posted from Grainger Businesses', 'Thank you for joining the Grainger Businesses talent community! Joining our talent community will allow us to notify you directly when roles aligned to your interests are posted.'),
    (None, 'New job opportunities at Texas Instruments', 'Hello, We have new job opportunities that might interest you. Check them out: Network Engineer, AI Solutions Engineer. See all opportunities.'),
    ('passed', 'New job opportunities at Acme -- plus your interview invitation', "We have new job opportunities you might like. Separately: we'd like to schedule an interview for the position of Backend Engineer."),
    (None, 'Opportunity', "We have an opportunity we'd love to discuss with you regarding a role."),
    (None, 'Application received', 'Thank you for applying. We have received your application.'),
    # fnuAshutosh templates
    ('passed', 'Interview', 'We are pleased to invite you for an interview for the RTL Engineer position at Acme. The interview is scheduled for Oct 9.'),
    ('passed', 'Interview invitation', 'Acme would like to schedule an interview with you for the RTL role. Please confirm your availability for Oct 9.'),
    ('passed', 'Invite', 'You are invited to interview at Acme for a DV position. The interview will be conducted on Oct 9.'),
    ('passed', 'Great news', 'Great news! Acme has selected you for the RTL interview. We look forward to meeting you on Oct 9.'),
    ('declined', 'Decision', 'We appreciate your application for RTL at Acme, but we have chosen another candidate.'),
    ('declined', 'Decision', 'We have reviewed your application for RTL and regret to inform you that we will not be proceeding.'),
    (None, 'Application submitted', 'Acme has confirmed receipt of your application for RTL.'),
    (None, 'Submitted', 'Your application for RTL at Acme has been successfully submitted and is under review.'),
    (None, 'Resume help', 'We can help improve your resume for just $99. Get professional writing today!'),
    (None, 'Coaching', 'Urgent: Claim your FREE job interview coaching session now!'),
    (None, 'Profile', 'SPECIAL OFFER: Get your LinkedIn profile optimized by experts. Limited time only!'),
    # Hard confirmations
    (None, 'Thank you for applying', 'Thank you for applying. Please note we do not offer visa sponsorship for this role. We will review your application and contact you if there is a fit.'),
    (None, 'Application received', 'We received your application. If we are not able to move forward with your application, we will notify you by email.'),
    (None, 'Application received', 'Thanks for applying! If you are not selected for this role, we will keep your resume on file for future openings.'),
    (None, 'Your application', 'Your application has been received. Candidates who are selected will be invited to complete an online assessment.'),
    (None, 'Prepare for your application process with Optiver', 'Exciting news! Your application has been received. Step 2 - Assessments: Our assessments test various skills. Step 3 - Interviews: A series of conversations.'),
    (None, 'Mock interview', 'Book a mock interview with an ex-FAANG engineer. Practice interview questions today.'),
    (None, 'Join us', 'You are invited to our virtual career fair on Oct 10! Register for the event.'),
    (None, 'Hackathon', 'You are invited to participate in our annual hackathon.'),
    (None, 'Withdrawn', "We are sorry that you have decided not to continue with your application."),
    # Hard invitations
    ('passed', 'Next steps', 'Thank you for applying! We were impressed by your background and would like to invite you to a 30 minute phone screen. If none of the times work, please share your availability.'),
    ('passed', 'Assessment', 'As a next step, please complete the HackerRank assessment within 7 days.'),
    ('passed', 'Re: application', 'Are you available Tuesday or Wednesday afternoon for a call with the hiring manager? Please share your availability.'),
    ('passed', 'Rescheduling', 'Unfortunately the interviewer is out on Tuesday. Please select a time that works for you.'),
    ('passed', 'Micron Digital Interview', 'You have been invited to complete a HireVue digital interview for the Memory Design Intern role.'),
    ('passed', 'Next round', "Congratulations, you've advanced to the next round of our process."),
    ('passed', 'Interview request', 'Interview request: please select an interview time from the link below.'),
]


class EvaluationSetTests(unittest.TestCase):
    def test_every_case(self):
        wrong = [(want, gmail.classify(subject, body), subject) for want, subject, body in EVALUATION
                 if gmail.classify(subject, body) != want]
        self.assertEqual(wrong, [])


if __name__ == '__main__':
    unittest.main()
