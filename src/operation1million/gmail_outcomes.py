"""Mark applied positions Passed or Declined from the replies in Gmail.

Asked for on 2026-10-05: the user would rather not click Passed or Declined
by hand except where this misses. It reads the mailbox over IMAP with a Gmail
app password (GMAIL_ADDRESS, GMAIL_APP_PASSWORD). It never marks a message
read; the one change it makes is to star each reply it reads as Passed, once,
so one the user unstars stays unstarred.

An email becomes a mark only when its wording is plain and it names one
position. A hand-made mark is never overridden. Everything this cannot settle
-- a reply that might be an invitation, or one that could be about any of
forty Micron applications -- is listed for the user on the Applied tab
rather than dropped: a missed interview costs more than a minute of reading.

The phrase lists began from the ones open job trackers on GitHub use
(SaahithV6/job-application-pipeline, alfa546/Auto-Apply-AI,
ethos71/forget-the-thunderdome, VinayD2028/job-search-automation). Those
match a phrase anywhere in the email, and "interview" anywhere is also in
every confirmation that says "we will contact you to schedule an interview".
So this reads sentence by sentence, and an invitation phrase counts only in
a sentence that is neither conditional nor negated.
"""
import argparse
from datetime import datetime, timedelta, timezone
import email
import html
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
import imaplib
import json
import os
from pathlib import Path
import re
import sys

from bs4 import BeautifulSoup

from . import applications, local_config, manual_intake
from .paths import DB, ROOT

# ---------------------------------------------------------------- phrases --

DECLINED = (
    'unfortunately', 'regret to inform', 'we regret', 'with regret',
    'not moving forward', 'not be moving forward', 'not to move forward', 'not move forward',
    "won't be moving", "won't move forward", 'will not move',
    'decided not to move forward', 'will not be moving forward', 'unable to move forward',
    'move forward with other', 'moving forward with other', 'proceed with other',
    'other candidates', 'another candidate', 'other applicants', 'other qualified',
    'candidates whose', 'candidate whose', 'more closely match', 'more closely aligned',
    'better match', 'stronger match', 'better aligned', 'more aligned with',
    'pursue other', 'pursuing other', 'decided to pursue', 'go in a different direction',
    'going in a different direction', 'decided to go with', 'decided to move on',
    'not been selected', 'not selected', 'were not selected', 'not chosen',
    'not shortlisted', 'not been shortlisted',
    # Keysight, 2026-10-06: "we are sorry to inform you that you do not meet
    # the requirements for this position" went unread.
    'sorry to inform', 'do not meet the requirements', 'does not meet the requirements',
    'no longer under consideration', 'no longer being considered', 'no longer considering',
    'not proceed', 'not be proceeding', 'decided not to proceed', 'not be progressing',
    'not progress your application', 'not to progress', 'not advancing', 'not be advancing',
    'not advance', 'unable to offer', 'not able to offer', 'unable to extend',
    'not the right fit', 'not a fit', 'not a match', 'not a good fit',
    'position has been filled', 'role has been filled', 'filled the position',
    'filled the role', 'has been filled', 'have filled', 'position is no longer available',
    'role is no longer available', 'no longer accepting', 'has been closed',
    'have closed', 'been cancelled', 'been canceled', 'put on hold',
    'your application was not', 'application was unsuccessful', 'unsuccessful',
    'not successful', 'decided to pass', 'will not be extending',
    'keep your resume on file', 'keep your information on file', 'keep your details on file',
    'apply for other', 'apply to other', 'apply for future', 'apply to future',
    'future opportunities', 'future openings', 'best of luck', 'wish you the best',
    'wish you success', 'wish you luck', 'success in your job search',
    'success in your search', 'not in a position to', 'difficult decision',
    'tough decision', 'highly competitive', 'large number of applications',
    'many qualified', 'after careful consideration', 'after careful review',
)
# Some of these are courtesies a rejection is padded with and an invitation
# can use too ("best of luck on Thursday!"). Alone they say nothing.
DECLINED_WEAK = {
    'unfortunately', 'we regret', 'with regret',
    'best of luck', 'wish you the best', 'wish you success', 'wish you luck',
    'future opportunities', 'future openings', 'highly competitive',
    'large number of applications', 'many qualified', 'after careful consideration',
    'after careful review', 'difficult decision', 'tough decision', 'has been closed',
    'have closed', 'been cancelled', 'been canceled', 'put on hold', 'other qualified',
    'apply for future', 'apply to future', 'keep your resume on file',
    'keep your information on file', 'keep your details on file', 'apply for other', 'apply to other',
}

# The shapes a rejection takes, beyond fixed phrases. Fixed phrases caught 63 of
# 89 real rejections (DiogoRibeiro7/Job-Rejection-Analysis, MIT); the misses
# were wordings like these: "it isn't a match", "we do not feel that it is a
# good match", "this role was recently filled", "this position has been
# cancelled", "not able to further consider", "no longer interviewing",
# "we have selected another applicant".
DECLINED_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"(?:\bnot|n't|\bno)\b[^.;]{0,50}\b(?:match|fit|align|aligned|suited|suitable)\b",
    r"\b(?:move|moving|proceed|proceeding|go|going)(?: forward)? with (?:other|others|another)\b",
    r"\bmore closely (?:match|matches|matched|meet|meets|align|aligns|aligned|fit|fits)\b",
    r"\b(?:position|role|requisition|opening|job|posting|program)\b[^.;]{0,30}\b(?:has|have|was|were|is|had)\b"
    r"(?: been| now)?(?: recently)?(?: officially)? (?:filled|cancel+ed|closed|withdrawn|put on hold|on hold|at capacity)",
    r"(?:\bnot|n't|unable to|\bno longer)\b(?: be)?(?: able to)?(?: further)? (?:consider|considering|move|moving|"
    r"proceed|proceeding|progress|progressing|advance|advancing|pursue|pursuing|interview|interviewing)\b"
    r"(?! (?:in|over|by) )",
    r"\b(?:selected|chosen|hired|identified|offered the (?:position|role) to)\b(?: an?)? (?:another|other|different|"
    r"more qualified|stronger)\b[^.;]{0,20}\b(?:candidate|candidates|applicant|applicants|individual|person)\b",
    r"\bdecided (?:not to|to not)\b(?! (?:apply|continue|withdraw))",
    r"\bmoving ahead with other\b|\bnot (?:be )?moving ahead\b",
))

PASSED = (
    # An interview, asked for.
    'invite you to interview', 'invite you to an interview', 'invite you for an interview',
    'invite you to a', 'invite you to participate', 'invite you to complete', 'invite you to take',
    'invite you to the next', 'invite you to schedule', 'invitation to interview',
    'interview invitation', 'invited to interview', 'interview request', 'interview availability',
    'select an interview time', 'choose an interview time', 'skills assessment',
    'selected you for', 'look forward to meeting you', 'look forward to speaking with you',
    'look forward to talking with you', 'are you free', 'are you available', 'would you be available',
    'when are you free', 'when are you available', 'when would you be available', 'like to invite',
    'would like to schedule', "we'd like to schedule", 'like to set up', 'like to speak with you',
    'like to talk with you', 'like to chat with you', 'like to meet with you', 'like to connect with you',
    'schedule an interview', 'schedule your interview', 'schedule a time', 'schedule a call',
    'schedule a phone', 'schedule a video', 'schedule a meeting', 'schedule time',
    'set up a time', 'set up a call', 'set up an interview', 'book a time', 'book your interview',
    'book an interview', 'pick a time', 'select a time', 'choose a time', 'choose a slot',
    'select a slot', 'select your preferred', 'your availability', 'share your availability',
    'provide your availability', 'availability for', 'available times', 'times that work',
    'time that works', 'scheduling link', 'self-schedule', 'calendly.com', 'goodtime.io',
    'paradox.ai', 'interview has been scheduled', 'interview is scheduled', 'interview is confirmed',
    'interview confirmation', 'confirm your interview', 'interview details',
    'phone screen', 'phone interview', 'video interview', 'virtual interview', 'zoom interview',
    'teams interview', 'technical interview', 'technical screen', 'recruiter screen',
    'recruiter call', 'screening call', 'hiring manager interview', 'panel interview',
    'onsite interview', 'on-site interview', 'final round', 'next round', 'super day', 'superday',
    # Moved on, said outright.
    'move you forward', 'moving you forward', 'move forward with your application',
    'move forward with your candidacy', 'moving forward with your application',
    'moving forward with your candidacy', 'selected to move forward', 'selected for an interview',
    'selected for the next', 'selected to interview', 'shortlisted', 'advance to the next',
    'advanced to the next', 'advancing to the next', 'proceed to the next', 'progress to the next',
    'progressed to the next', 'moved to the next',
    # An assessment.
    # HPE, 2026-10-05: "You are invited to our screening process", six
    # questions with a deadline, read as nothing.
    'invited to our screening', 'invited to participate in our screening', 'screening questionnaire',
    'online assessment', 'coding assessment', 'technical assessment', 'coding challenge',
    'coding test', 'technical test', 'online test', 'take-home', 'take home assignment',
    'complete the assessment', 'complete an assessment', 'complete this assessment',
    'assessment invitation', 'assessment link', 'video assessment',
    'one-way video', 'recorded interview', 'digital interview', 'hackerrank', 'hackerank',
    'codesignal', 'codility', 'hirevue', 'karat', 'pymetrics', 'harver', 'mettl', 'testgorilla',
    'modern hire', 'coderpad', 'spark hire', 'sparkhire', 'imocha', 'glider.ai',
    # An offer is further along still.
    'pleased to offer', 'offer letter', 'offer of employment', 'extend an offer',
    'extend you an offer', 'like to offer you',
)
# Mentioned, but not plainly an invitation: listed for the user, never dropped.
# "IMC has invited you to the ... Candidate Portal" (the first real run):
# a portal is not an interview, but it is worth a look.
PASSED_WEAK = ('invited you to', 'invited you', 'interview', 'assessment', 'next step', 'next stage',
               'speak with', 'chat with',
               'meet with', 'call with', 'recruiter', 'hiring manager', 'availability')

# A sentence about what may happen is not an invitation. "If your background
# matches, we will contact you to schedule an interview" is in nearly every
# confirmation. A bare "if" is not enough to say so: "If none of these times
# work, share your availability" is an invitation all the same.
HEDGES = (
    # What a confirmation says may come next, not an invitation: "If you are
    # applying to a role that requires coding skills, you may receive an
    # invitation to take a coding assessment" (General Motors, first real run).
    'may receive', 'will receive', 'might receive', 'if you are applying', 'if your role', 'requires coding',
    'talent community', 'talent network', 'join our', 'newsletter', 'event', 'webinar', 'hackathon',
    'registration confirmation', 'security alert', 'new jobs', 'job opportunities', 'new roles',
    'coaching', 'claim your', 'for free', 'free trial', 'sign up', 'limited time', 'discount', '% off',
    'subscribe',
    'career fair', 'info session', 'information session', 'mock interview', 'interview prep',
    'practice interview', 'interview tips',
    'if your', 'if you are selected', 'are selected', 'be selected', 'is selected',
    'should you', 'should your', 'if we ', 'if there', 'if our', 'if you meet', 'if you match',
    'if you qualify', 'if you pass', 'if successful', 'successful candidates', 'if you move',
    'if you advance', 'next steps if', 'qualifications match', 'experience matches',
    ' might ', 'whether', 'in the event', 'will be in touch',
    'will contact', 'will reach out', 'be contacted', 'reach out to you', 'get back to you',
    'selected candidates', 'qualified candidates', 'candidates who', 'applicants who',
    'those selected', 'if selected', 'we will review', 'will be reviewed', 'under review',
    'reviewing your', 'review your application', 'review your resume', 'interview process may',
    'typical', 'our process', 'hiring process', 'recruiting process', 'interview process',
    'tips', 'prepare for', 'how to', 'blog', 'webinar', 'unsubscribe', 'job alert',
    'similar jobs', 'recommended', 'jobs you', 'privacy', 'do not reply',
)
# A description of the process names interviews and assessments without
# offering one: "Step 2 - Assessments: our assessments test problem-solving"
# (an Optiver confirmation the user forwarded, 2026-10-05). Only a vague
# mention is set aside for this; a plain invitation phrase still counts.
DESCRIPTIVE = (
    'step 1', 'step 2', 'step 3', 'step 4', 'step 5', 'stage 1', 'stage 2', 'stage 3',
    'what to expect', 'learn more', 'designed to', 'can vary', 'may vary', 'a series of',
    'our assessments', 'our interviews', 'our interview', 'candidate journey', 'knowledge hub',
    'prepare you', 'get ready', 'faq', 'video', 'blog', 'culture', 'internship program',
)
DECLINE_HEDGES = (' if ', 'whether', 'in the event', 'should we', 'should you', 'regardless',
                  'either way', 'one way or')
# An invitation to a portal is not one to interview, though it is worth a
# look: these cancel a plain invitation phrase, not a vague mention.
PORTAL = ('candidate portal', 'portal', 'create an account', 'create your account')
NEGATION = re.compile(r"\b(?:not|cannot|unable|unfortunately|regret|no longer)\b|n't\b")
CONFIRMATION = (
    'thank you for applying', 'thanks for applying', 'thank you for your application',
    'thanks for your application', 'received your application', 'application received',
    'application has been received', 'application was received', 'application was submitted',
    'application has been submitted', 'successfully submitted', 'successfully applied',
    'we have received', 'confirming your application', 'application confirmation',
    'thank you for your interest', 'your application is in', 'confirmed receipt', 'received your job application',
    # Read as unknown on the real mail, 2026-10-06: Tesla, Cisco (ten of
    # them), Stateside Brands.
    "we've received your", 'thank you for taking the first step', 'no further action is needed',
)
# Mail from an employer that is plainly not news: a login code, an account to
# verify, a withdrawal the user made. Everything else no rule recognises is
# `unknown` and shown, not dropped (2026-10-06): phrase lists will always
# trail the wording, and the HPE screening invitations, a Keysight rejection
# and IMC's request for a sponsorship form were all read as nothing. Kept to
# what a footer does not say -- "unsubscribe" is in invitations too.
NOISE = (
    'security code', 'verification code', 'one-time password', 'one time password',
    'verify your candidate account', 'verify your email', 'verify your account', 'confirm your identity',
    'confirm your email', 'confirm your career profile', 'registration code', 'reset your password',
    'password reset', 'sign-in code', 'login code', 'withdrawn your', 'decided not to continue',
    'weekly digest', 'new jobs', 'new job opportunities', 'jobs posted', 'job alert', 'jobs you may',
    'career fair', 'hackathon', 'webinar', 'info session', 'information session', 'mock interview',
    'claim your', 'special offer', 'limited time', 'thank you for registering', 'candidates like you',
)


def _plain(text):
    # Some mailers leave entities in the text part: Cisco's "taking&nbsp;the&nbsp;first
    # step" and HPE's invitation matched no phrase until unescaped (2026-10-06).
    text = html.unescape(str(text or '')).replace('’', "'").replace('‘', "'").replace('\xa0', ' ')
    return ' '.join(text.casefold().split())


def _unwrap(text):
    """Join lines a mailer wrapped at ~72 columns back into their sentence.

    Split at every line break, "we regret to inform you that" and "we cannot
    extend you an invitation" were two sentences, and a real rejection read
    as a mention of an interview. A line long enough to have been wrapped and
    not ending in punctuation continues on the next one.
    """
    joined = []
    for line in str(text).replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        line = line.strip()
        if (line and joined and joined[-1] and len(joined[-1]) >= 40
                and not re.search(r'[.!?:;]["\')\]]?$', joined[-1])):
            joined[-1] += ' ' + line
        else:
            joined.append(line)
    return '\n'.join(joined)


def _sentences(text):
    return [' ' + part.strip() + ' ' for part in re.split(r'(?<=[.!?])\s+|\n+|\s{3,}', _unwrap(text))
            if part.strip()]


def _phrases(phrases):
    """One pattern for a list of phrases, each matched as whole words.

    Plain substring tests found "our interview" inside "your interview" and
    would find "event" inside "prevent": a phrase must start and end at a
    word boundary wherever it starts or ends with a letter or digit.
    """
    parts = []
    for phrase in sorted({phrase.strip() for phrase in phrases}, key=len, reverse=True):
        part = re.escape(phrase)
        if phrase[:1].isalnum():
            part = r'(?<![a-z0-9])' + part
        if phrase[-1:].isalnum():
            part += r'(?![a-z0-9])'
        parts.append(part)
    return re.compile('|'.join(parts))


_OVERLAPPING = {}


def _found(pattern, line):
    """Every phrase present, overlapping ones included: in "we regret to
    inform you" a plain scan takes "we regret" and never sees "regret to
    inform" starting inside it."""
    if pattern not in _OVERLAPPING:
        _OVERLAPPING[pattern] = re.compile('(?=(' + pattern.pattern + '))')
    return {match.group(1) for match in _OVERLAPPING[pattern].finditer(line)}


def classify(subject, body):
    """'passed', 'declined', 'unclear' (look at it), 'unknown' (no rule
    recognises it: look at it) or None (known to be nothing to do).

    Order matters, and it leans toward not losing an invitation: a plain
    invitation is Passed even in an email that also says "unfortunately",
    unless the same email is also a plain rejection, which is unclear.
    Nothing is dropped for want of a rule: only a confirmation or plain
    noise is None.
    """
    lines = _sentences(str(subject or '') + '\n' + str(body or ''))
    lowered = [' ' + _plain(line) + ' ' for line in lines]
    passed = any(_PASSED.search(line) and not _HEDGES.search(line) and not _PORTAL.search(line)
                 and not NEGATION.search(line) for line in lowered)
    plain = [line for line in lowered if not _DECLINE_HEDGES.search(line)]
    hits = set().union(*(_found(_DECLINED, line) for line in plain)) if plain else set()
    patterned = any(pattern.search(line) for line in plain for pattern in DECLINED_PATTERNS)
    declined = patterned or bool(hits - DECLINED_WEAK)
    if passed and declined:
        return 'unclear'
    if passed:
        return 'passed'
    if declined:
        return 'declined'
    mentioned = any(_PASSED_WEAK.search(line) and not _HEDGES.search(line) and not _DESCRIPTIVE.search(line)
                    for line in lowered)
    if any(_CONFIRMATION.search(line) for line in lowered):
        return None
    if mentioned or len(hits) >= 2:
        return 'unclear'
    if any(_NOISE.search(line) for line in lowered):
        return None
    return 'unknown'


_PASSED, _PASSED_WEAK, _DECLINED = _phrases(PASSED), _phrases(PASSED_WEAK), _phrases(DECLINED)
_HEDGES, _DECLINE_HEDGES = _phrases(HEDGES), _phrases(DECLINE_HEDGES)
_DESCRIPTIVE, _CONFIRMATION, _PORTAL = _phrases(DESCRIPTIVE), _phrases(CONFIRMATION), _phrases(PORTAL)
_NOISE = _phrases(NOISE)


# ---------------------------------------------------------------- matching --

TAIL = {'inc', 'incorporated', 'corp', 'corporation', 'llc', 'ltd', 'limited', 'co', 'company',
        'plc', 'com', 'ai', 'io', 'technology', 'technologies', 'systems', 'group', 'holdings',
        'international', 'labs', 'semiconductor', 'semiconductors', 'usa', 'us', 'america'}
ALIASES = {'advanced micro devices': ['amd'], 'international business machines': ['ibm'],
           'taiwan semiconductor manufacturing': ['tsmc'], 'hewlett packard enterprise': ['hpe'],
           'amazon': ['amazon', 'aws'], 'meta platforms': ['meta'], 'alphabet': ['google'],
           'texas instruments': ['texas instruments'], 'on semiconductor': ['onsemi']}


def company_key(company):
    """One name per employer however the ledger spells it: "Marvell
    Technology, Inc.", "Marvell Technology" and "Marvell" are all marvell.
    A name the tail-stripping would shrink below three letters keeps its
    words: "ON Semiconductor" is not "on", which matched "Update on your
    Application" from another firm (first real run)."""
    full = applications.employer_name(company)
    words = full.split()
    while len(words) > 1 and words[-1] in TAIL:
        words.pop()
    name = ' '.join(words)
    return name if len(name) >= 3 else full


def company_names(company):
    """The ways an email names a company: 'Micron Technology, Inc.' -> micron."""
    name = company_key(company)
    names = {name} if name else set()
    # Workday writes from generalmotors@ and blueorigin@myworkday.com.
    if ' ' in name and len(name.replace(' ', '')) >= 6:
        names.add(name.replace(' ', ''))
    for full, short in ALIASES.items():
        if name.startswith(full) or name in short:
            names.update(short)
            # A canonical brand (AMD) must still match mail spelling its legal
            # name out. Company display normalization must not erase evidence.
            if applications.employer_name(full) == name:
                names.add(full)
                if ' ' in full and len(full.replace(' ', '')) >= 6:
                    names.add(full.replace(' ', ''))
    return {item for item in names if len(item) >= 3}


def _has(name, text):
    return re.search(r'(?<![a-z0-9])' + re.escape(name) + r'(?![a-z0-9])', text) is not None


def _words(text):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', _plain(text)).split())


def match(groups, message, company_only=False):
    """The applied groups an email is about, or [] when it is not plain which.

    The sender and subject name the company; where one company has several
    applications, a requisition id or the full title in the email picks one.
    With one application there, an email naming some other role is not
    about it: General Motors' confirmation of a role missing from the ledger
    was read as about the one GM application (first real run).

    A decision can be recorded weeks after the application -- Muse's were
    reconciled in bulk -- so an email is set aside only when it is more than
    45 days older than the decision.
    """
    head = _words(message['from'] + ' ' + message['subject'])
    body = _words(message['text'][:4000])
    when = message['at']
    eligible = [group for group in groups
                if not group.get('at') or _later(when, days=45) >= group['at']]
    by_company = {}
    for group in eligible:
        for name in company_names(group.get('company')):
            by_company.setdefault(name, []).append(group)
    named = {name for name in by_company if _has(name, head)}
    if not named:
        named = {name for name in by_company if len(name) >= 4 and _has(name, body)}
    candidates = {id(group): group for name in named for group in by_company[name]}
    companies = {company_key(group.get('company')) for group in candidates.values()}
    if len(companies) != 1:
        return []
    candidates = list(candidates.values())
    if company_only:
        return candidates
    text = head + ' ' + _words(message['text'])
    ids = {id(group): {_words(job['source_job_id']) for job in group.get('jobs', ())
                      if len(str(job.get('source_job_id') or '')) >= 4}
           for group in candidates}
    # Explicit requisition labels are evidence against a title/company fallback.
    explicit = {_words(value) for value in re.findall(
        r'\b(?:JR\d{4,}|R\d{5,})\b', message['subject'] + ' ' + message['text'], re.I)}
    explicit.update(_words(value) for value in re.findall(
        r'\b(?:requisition|job|req)(?:\s+(?:id|number|no\.?))?\s*[:#]\s*([a-z0-9-]{4,})',
        message['subject'] + ' ' + message['text'], re.I))
    by_id = [group for group in candidates if any(_has(value, text) for value in ids[id(group)])]
    if explicit:
        # Multiple requisitions in a thread cannot safely select one application.
        if len(explicit) != 1:
            return []
        by_id = [group for group in candidates if explicit <= ids[id(group)]]
        return by_id
    if by_id:
        # Return multiple copies only with a shared, actually mentioned identifier.
        shared = set.intersection(*(ids[id(group)] for group in by_id))
        return by_id if any(_has(value, text) for value in shared) else []
    by_title = [group for group in candidates if len(_words(group.get('title'))) >= 6
                and _has(_words(group.get('title')), text)]
    # A title found only inside a longer one found is not the one named:
    # Optiver's "FPGA Engineer Intern (Summer 2027 - Austin)" also contains
    # "FPGA Engineer" and "FPGA Engineer Intern (Summer 2027)" (2026-10-07).
    by_title = [group for group in by_title
                if not any(_words(group.get('title')) != _words(other.get('title'))
                           and _has(_words(group.get('title')), _words(other.get('title')))
                           for other in by_title)]
    if len(by_title) == 1:
        return by_title
    if len(candidates) == 1 and not _names_a_role(message):
        return candidates
    return []


ROLE_WORDS = re.compile(r'\b(?:intern|internship|co-?op|engineer|engineering|developer|designer|'
                        r'scientist|analyst|technician|graduate|associate)\b')


def _names_a_role(message):
    """Whether the subject or body names a role, as "Your application to 2027 Summer
    Intern - Digital Product" does and "Your IBM Application Status" does not."""
    return bool(ROLE_WORDS.search(_plain(message.get('subject')) + ' ' + _plain(message.get('text'))))


def _later(when, days):
    try:
        moment = datetime.fromisoformat(when)
    except (TypeError, ValueError):
        return '9999'
    return (moment + timedelta(days=days)).isoformat()


# Applicant-tracking and mail services that send for many employers: the
# sender's domain says nothing about which.
SHARED_SENDERS = {'myworkday', 'workday', 'greenhouse', 'greenhouse-mail', 'lever', 'hire', 'ashbyhq',
                  'smartrecruiters', 'successfactors', 'icims', 'jobvite', 'taleo', 'oraclecloud',
                  'eightfold', 'candidate', 'linkedin', 'indeed', 'handshake', 'joinhandshake', 'gmail',
                  'outlook', 'yahoo', 'hotmail', 'paradox', 'hirevue', 'hackerrank', 'codesignal',
                  'avature', 'phenom', 'ukg', 'ultipro', 'adp', 'bamboohr', 'workable', 'recruitee'}


def _sender(message):
    """The employer a sender's domain names, or '' for a shared service:
    no-reply@optiver.com and no-reply@optiver.us are both optiver."""
    address = parseaddr(message.get('from') or '')[1].lower()
    labels = address.rpartition('@')[2].split('.')
    if len(labels) < 2:
        return ''
    label = labels[-2] if labels[-2] not in {'co', 'com'} or len(labels) < 3 else labels[-3]
    return '' if label in SHARED_SENDERS else label


def decide(groups, messages, current):
    """Outcomes to write, and the emails to show the user.

    `current` is the last outcome event per group. A group whose last mark
    was made by hand is left alone, cleared by hand included. Emails are
    read oldest first, so the latest word wins: an interview and then a
    rejection ends Declined.
    """
    wanted, unsorted, stars, seen_senders = {}, [], [], set()
    for message in sorted(messages, key=lambda item: item['at']):
        verdict = message.get('outcome')
        sender = _sender(message)
        if verdict is None:
            if sender:
                seen_senders.add(sender)
            continue
        found = match(groups, message)
        # Unknown is listed like unclear, and only for an employer applied
        # to: a newsletter no rule names stays out of the list.
        if verdict in ('unclear', 'unknown') or not found:
            guess = found or match(groups, message, company_only=True)
            if not guess and verdict != 'passed':
                continue
            unsorted.append({'id': message['id'], 'at': message['at'], 'from': message['from'],
                             'subject': message['subject'], 'outcome': verdict,
                             'company': guess[0]['company'] if guess else '',
                             'groups': [group['id'] for group in guess]})
            # Starred when it names a company applied to, or one that wrote
            # before -- Optiver's assessment came after Optiver's confirmation,
            # with no Optiver row in the ledger. A recruiter's cold "are you
            # available?" from nowhere is not news.
            if verdict == 'passed' and (guess or _sender(message) in seen_senders):
                stars.append(message['id'])
            continue
        if verdict == 'passed':
            stars.append(message['id'])
        for group in found:
            # A second round after a pass changes nothing; a rejection after
            # it does, since the latest word wins.
            wanted[group['id']] = (verdict, message['id'])
    writes = []
    for group_id, (verdict, message_id) in wanted.items():
        last = current.get(group_id)
        if last and last.get('by') != 'gmail':
            continue
        if last and last.get('outcome') == verdict:
            continue
        writes.append((group_id, verdict, message_id))
    return writes, unsorted, stars


# -------------------------------------------------------------------- mail --

QUERY = ('-in:sent -in:chats -from:jobalerts-noreply@linkedin.com -from:jobs-listings@linkedin.com '
         '(application OR applying OR applied OR candidacy OR candidate OR interview OR assessment '
         'OR position OR role OR opportunity OR unfortunately OR "next steps" OR hackerrank '
         'OR codesignal OR hirevue OR codility OR karat OR offer)')


def gmail_dir():
    return Path(os.environ.get('OPERATION1MILLION_GMAIL_DIR', ROOT / '.local/gmail'))


def _header(value):
    try:
        return str(make_header(decode_header(value or '')))
    except (ValueError, LookupError):
        return str(value or '')


def _text(part):
    payload = part.get_payload(decode=True) or b''
    charset = part.get_content_charset() or 'utf-8'
    try:
        return payload.decode(charset, errors='replace')
    except LookupError:
        return payload.decode('utf-8', errors='replace')


def parse(raw, message_id):
    """One RFC 822 message: who, when, subject and its readable text."""
    parsed = email.message_from_bytes(raw)
    plain, html = [], []
    for part in parsed.walk():
        if part.get_content_maintype() == 'multipart' or part.get_filename():
            continue
        if part.get_content_type() == 'text/plain':
            plain.append(_text(part))
        elif part.get_content_type() == 'text/html':
            html.append(_text(part))
    text = '\n'.join(plain)
    if not text.strip() and html:
        text = BeautifulSoup('\n'.join(html), 'html.parser').get_text('\n')
    try:
        at = parsedate_to_datetime(parsed['Date']).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, IndexError):
        at = datetime.now(timezone.utc).isoformat()
    name, address = parseaddr(_header(parsed['From']))
    return {'id': message_id, 'at': at, 'from': f'{name} <{address}>'.strip(),
            'subject': _header(parsed['Subject']), 'text': text[:20000]}


def _all_mail(connection):
    """Gmail's All Mail folder, by its flag: its name follows the account's language."""
    status, folders = connection.list()
    if status == 'OK':
        for line in folders:
            line = line.decode(errors='replace') if isinstance(line, bytes) else str(line)
            if '\\All' in line:
                return line.rsplit(' "/" ', 1)[-1]
    return '"[Gmail]/All Mail"'


def fetch(address, password, since, known, capture=None):
    """New messages matching QUERY since `since`, by Gmail's own message id.

    Read-only: the folder is opened with EXAMINE and the body is fetched
    with BODY.PEEK, which leaves the message unread.
    """
    connection = imaplib.IMAP4_SSL('imap.gmail.com', timeout=60)
    try:
        connection.login(address, password)
        status, _ = connection.select(_all_mail(connection), readonly=True)
        if status != 'OK':
            raise RuntimeError('Could not open All Mail')
        search = f'after:{since:%Y/%m/%d} {QUERY}'
        status, data = connection.uid('SEARCH', 'X-GM-RAW', '"' + search.replace('"', '\\"') + '"')
        if status != 'OK':
            raise RuntimeError('Gmail search failed')
        uids = data[0].split() if data and data[0] else []
        found = []
        for start in range(0, len(uids), 50):
            chunk = b','.join(uids[start:start + 50])
            status, data = connection.uid('FETCH', chunk, '(X-GM-MSGID)')
            if status != 'OK':
                raise RuntimeError('Gmail fetch failed')
            if capture is not None and not capture:
                capture.append(repr(data))
            for item in data:
                head = item[0] if isinstance(item, tuple) else item
                if not isinstance(head, bytes):
                    continue
                gm = re.search(rb'X-GM-MSGID (\d+)', head)
                uid = re.search(rb'UID (\d+)', head)
                if gm and uid and gm.group(1).decode() not in known:
                    found.append((uid.group(1), gm.group(1).decode()))
        messages = []
        for start in range(0, len(found), 25):
            chunk = b','.join(uid for uid, _ in found[start:start + 25])
            status, data = connection.uid('FETCH', chunk, '(X-GM-MSGID BODY.PEEK[])')
            if status != 'OK':
                raise RuntimeError('Gmail fetch failed')
            if capture is not None and len(capture) == 1:
                capture.append(repr(data[:1])[:3000])
            for item in data:
                if not isinstance(item, tuple):
                    continue
                gm = re.search(rb'X-GM-MSGID (\d+)', item[0])
                if gm:
                    messages.append(parse(item[1], gm.group(1).decode()))
        return messages
    finally:
        try:
            connection.logout()
        except (OSError, imaplib.IMAP4.error):
            pass


def star(address, password, message_ids):
    """Star these messages (Gmail's star is IMAP's \\Flagged). Returns the ids
    starred; one Gmail no longer has is skipped."""
    if not message_ids:
        return []
    connection = imaplib.IMAP4_SSL('imap.gmail.com', timeout=60)
    done = []
    try:
        connection.login(address, password)
        status, _ = connection.select(_all_mail(connection))
        if status != 'OK':
            raise RuntimeError('Could not open All Mail')
        for message_id in message_ids:
            status, data = connection.uid('SEARCH', 'X-GM-MSGID', message_id)
            uids = data[0].split() if status == 'OK' and data and data[0] else []
            if uids and connection.uid('STORE', uids[0], '+FLAGS', '(\\Flagged)')[0] == 'OK':
                done.append(message_id)
        return done
    finally:
        try:
            connection.logout()
        except (OSError, imaplib.IMAP4.error):
            pass


# --------------------------------------------------------------------- run --

def last_events(path):
    """The last outcome event per group, hand-made or not, clears included."""
    last = {}
    path = Path(path)
    if not path.exists():
        return last
    with path.open(encoding='utf-8-sig') as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and isinstance(event.get('id'), str):
                last[event['id']] = event
    return last


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def _save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, path)


def _settled(item, event, cache):
    """Only a decision after this reply can settle it; replay time is not mail time."""
    if not event:
        return False
    if event.get('by') == 'gmail':
        decision_at = (cache.get(event.get('message')) or {}).get('at')
        if not decision_at or not event.get('outcome'):
            return False
    else:
        decision_at = event.get('at')
    return bool(decision_at and decision_at >= item['at'])


def _inputs(ledger):
    """What a pass decides from besides the mail: the decisions, pasted jobs,
    outcome marks and these rules. A change to any is worth one re-read."""
    files = (Path(ledger), manual_intake.path_for(ledger), applications.outcomes_path(ledger), Path(__file__))
    out = []
    for path in files:
        try:
            stat = path.stat()
            out.append([str(path), stat.st_size, stat.st_mtime_ns])
        except OSError:
            out.append([str(path), None, None])
    return out


def run(db, ledger, address, password, directory=None, capture=None, preview=False):
    """One pass. With `preview`, everything is read and decided and nothing is
    written or starred: the returned summary carries what would have been.

    Passive after the first pass, asked for on 2026-10-06: the first pass
    searches the whole window, later ones only mail since the last pass, and
    a pass with no new mail and unchanged decisions stops before building the
    queue -- which cost about four CPU minutes every half hour.
    """
    directory = Path(directory or gmail_dir())
    cache_path = directory / 'messages.json'
    cache = _load(cache_path, {})
    known = {key for key, message in cache.items() if 'text' in message}
    last = _load(directory / 'last-run.json', {})
    new = None
    if cache and last.get('at') and not preview:
        # Two days of overlap: Gmail's after: is a date, and mail can arrive late.
        new = fetch(address, password, datetime.fromisoformat(last['at']) - timedelta(days=2), known, capture)
        if not new and last.get('inputs') == _inputs(ledger):
            return {'at': datetime.now(timezone.utc).isoformat(), 'idle': True,
                    'checked': len(cache), 'written': 0}
    groups = manual_intake.augment_queue(applications.queue(db, ledger), ledger)['applied']
    if not groups:
        return {'applied': 0, 'checked': 0, 'written': 0, 'unsorted': 0}
    if new is None:
        # Decisions can be recorded weeks after applying; read from well before.
        since = min(datetime.fromisoformat(group['at']) for group in groups if group.get('at')) - timedelta(days=45)
        new = fetch(address, password, since, known, capture)
    for message in new:
        cache[message['id']] = message
    # Every email is classified on every run, so a rule fixed today also
    # re-reads what arrived last week.
    for message in cache.values():
        if 'text' in message:
            message['outcome'] = classify(message['subject'], message['text'])
    outcomes = applications.outcomes_path(ledger)
    writes, unsorted, stars = decide(groups, list(cache.values()), last_events(outcomes))
    if preview:
        by_id = {group['id']: group for group in groups}
        return {'preview': True, 'applied': len(groups), 'checked': len(cache),
                'marks': [{'outcome': verdict, 'company': by_id[group_id]['company'],
                           'title': by_id[group_id]['title'], 'email': cache[message_id]['subject'],
                           'from': cache[message_id]['from'], 'at': cache[message_id]['at']}
                          for group_id, verdict, message_id in writes],
                'list': unsorted, 'stars': [cache[message_id]['subject'] for message_id in stars]}
    _save(cache_path, cache)
    for group_id, verdict, message_id in writes:
        applications.append_outcome(outcomes, group_id, verdict, by='gmail', message=message_id)
    # Settled since, by hand or by a later email: not worth showing again.
    marked = last_events(outcomes)
    recent = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat()
    unsorted = [item for item in unsorted if item['at'] >= recent and not (
        item['groups'] and all(_settled(item, marked.get(group), cache) for group in item['groups']))]
    _save(directory / 'unsorted.json', unsorted)
    # Every Passed round is news; persist message IDs so user-unstarred mail
    # is never automatically starred again.
    starred_path = directory / 'starred.json'
    starred = set(_load(starred_path, []))
    to_star = [message_id for message_id in stars if message_id not in starred]
    newly = star(address, password, to_star)
    _save(starred_path, sorted(starred | set(newly)))
    summary = {'at': datetime.now(timezone.utc).isoformat(), 'applied': len(groups),
               'checked': len(cache), 'written': len(writes), 'unsorted': len(unsorted),
               'starred': len(newly)}
    _save(directory / 'last-run.json', dict(summary, inputs=_inputs(ledger)))
    return summary


def read_unsorted(directory=None):
    """What the last run could not settle, newest first, for the Applied tab."""
    items = _load(Path(directory or gmail_dir()) / 'unsorted.json', [])
    return sorted(items, key=lambda item: item.get('at', ''), reverse=True) if isinstance(items, list) else []


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--db', type=Path, default=DB)
    parser.add_argument('--ledger', type=Path, default=None)
    parser.add_argument('--capture', type=Path, help='Write the first raw IMAP responses here (private).')
    parser.add_argument('--preview', action='store_true',
                        help='Read and decide, write no marks and star nothing; print what would happen.')
    args = parser.parse_args()
    local_config.load_credentials()
    address, password = os.environ.get('GMAIL_ADDRESS', ''), os.environ.get('GMAIL_APP_PASSWORD', '')
    if not address or not password:
        print('GMAIL_ADDRESS and GMAIL_APP_PASSWORD are not set; nothing checked.')
        return 0
    capture = [] if args.capture else None
    try:
        summary = run(args.db, args.ledger or applications.ledger_path(), address,
                      password.replace(' ', ''), capture=capture, preview=args.preview)
    except (imaplib.IMAP4.error, OSError, RuntimeError) as exc:
        # A refused login names no secret; say which kind of failure it was.
        print(f'Gmail check failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1
    if args.capture:
        args.capture.write_text('\n\n'.join(capture or []), encoding='utf-8')
    if args.preview:
        print(f"Preview: {summary['applied']} applied positions, {summary['checked']} emails read")
        print('\nWould mark:')
        for mark in summary['marks']:
            print(f"  {mark['outcome'].upper():9} {mark['company']} | {mark['title']}\n"
                  f"            {mark['at'][:10]} {mark['from']} | {mark['email']}")
        print('\nWould list for a look:')
        for item in summary['list']:
            print(f"  {item['outcome']:9} {item['at'][:10]} {item['company'] or '-'} | {item['subject']}")
        print('\nWould star:', *summary['stars'], sep='\n  ')
        return 0
    print(json.dumps(summary))
    return 0


if __name__ == '__main__':
    sys.exit(main())
