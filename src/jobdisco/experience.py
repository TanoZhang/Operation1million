"""Conservative, deterministic required-experience gate; no inferred equivalency."""
import html
import re
import unicodedata

# A co-op is an internship under another name, and a recent or college graduate
# a new one; "Hardware Co-op" asking three years of Python was refused while
# the same posting called an internship was not. "Early career" and "entry
# level" stay out on purpose: those postings may still ask for years.
# Not "non-internship": Amazon's "3+ years of non-internship professional
# software development experience" made 80 queued postings internships, and
# their years were waved through (#204, live queue, 2026-10-01).
ENTRY = re.compile(r'(?<!\bnon-)(?<!\bnon\s)(?<!\bnon)'
                   r'\b(?:intern|internship|co-?op|new\s+(?:college\s+)?grad(?:uate)?|'
                   r'(?:university|college|recent)\s+graduate)\b', re.I)
# "Will be an advantage" (Samsung) is a preference; a bare "advantage for
# FullChip" (NVIDIA) is not the marker, so the article is required.
# "Desirable", "beneficial" and "helpful" too (2026-09-27): "3+ years of
# experience desirable" was a requirement.
# "Nice-to-Haves", "Must-Haves" and "Pluses" as a heading, "a big plus" in a
# line (2026-09-27): hyphenated, plural or qualified, each was read as nothing.
OPTIONAL = re.compile(r'\b(?:preferred|desired|desirable|nice[-\s]+to[-\s]+haves?|a\s+plus|pluses|'
                      r'(?:big|huge|great|strong|definite|major)\s+plus|bonus|ideally|'
                      r'an?\s+advantage|advantageous|an\s+asset|beneficial|helpful|'
                      # "The ideal candidate has 5+ years" (2026-09-27), as the
                      # degree filter already read it.
                      r'ideal\s+candidates?)\b', re.I)
REQUIRED = re.compile(r'\b(?:required|requirements?|minimum|basic\s+qualifications|must[-\s]+haves?|at\s+least)\b', re.I)
# The short forms with their field: "BSEE + 5 years or MSEE + 3 years" was no
# degree at all, and read as asking nothing (2026-09-27).
SHORT_FORMS = r'(?:BS|MS)(?:EE|CS|CE|c)?'
DEGREE = re.compile(r"\b(?:" + SHORT_FORMS + r"|bachelor(?:'s|s)?|master(?:'s|s)?)\b", re.I)
# A hyphen can carry the unit as well as a range: "3-year experience" states
# what "3 years experience" states. And the bound can be fractional, which this
# gate has to be able to exceed -- reading 2.5 as 2 decides the posting the
# other way, and reading it as 5 decides it wrongly in the other direction.
# "3 or more years" is a floor like "3+ years", and "yrs" is how a terse
# posting abbreviates the unit; both used to read as stating nothing.
# "Seven plus years" is "7+ years" (2026-09-27); it read as stating nothing.
# "YOE" is how a terse posting writes "years of experience".
# Between the two ends of a range: "3~5", "3 through 5", "3-to-5", and "2 or
# 3" / "2/3", whose floor is the first (2026-09-27; each read the upper end).
RANGE = r'(?:\s*(?:-|–|—|~|/)\s*|[\s-]+(?:to|through|thru|or)[\s-]+)'
NUMBER = (r'(?P<low>\d{1,2}(?:\.\d)?)(?:' + RANGE + r'\d{1,2})?(?:\s*\+|\s*-?\s*plus\b)?'
          r'(?:\s+or\s+(?:more|greater))?')
YEARS = re.compile(r'(?<![\w.])' + NUMBER + r'\s*(?:[-–—]\s*)?(?:years?|yrs?|yoe)\b', re.I)
# Nobody asks for more than this. A bigger number is the company describing
# itself -- "with over 40 years of experience, Acme leads..." -- and was read
# as a forty-year requirement.
MAX_REQUIRED_YEARS = 20
# Spelled-out counts, rewritten as digits before anything is read: "five years
# of experience" and "three (3) years" asked as plainly as "5 years" and were
# read as asking nothing.
NUMBER_WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7,
                'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12,
                'thirteen': 13, 'fourteen': 14, 'fifteen': 15, 'sixteen': 16,
                'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20}
# "Five to seven years" is a range from five. Only "seven" stood beside the
# unit, so only it was rewritten and the floor read as seven (2026-09-27).
SPELLED = re.compile((r'\b(%(words)s)\b(?=\s*(?:\(\s*\d{1,2}\s*\)\s*)?'
                      r'(?:' + RANGE + r'(?:\d{1,2}|%(words)s)\b\s*(?:\(\s*\d{1,2}\s*\)\s*)?)?'
                      r'(?:\+|\s*-?\s*plus\b)?'
                      r'(?:\s+or\s+more)?\s*(?:[-–—]\s*)?(?:years?|yrs?)\b)')
                     % {'words': '|'.join(NUMBER_WORDS)}, re.I)
# "3 (three) years" and "three (3) years" once the word is a digit: one number.
PAREN_REPEAT = re.compile(r'\b(\d{1,2})\s*\(\s*(?:\d{1,2}|%s)\s*\)' % '|'.join(NUMBER_WORDS), re.I)
# A form's label ahead of its value: "Years of experience: 5+" is "5+ years of
# experience" written the other way round.
LABELLED = re.compile(
    r'\byears\s+of\s+((?:\w+\s+){0,2}?experience)\s*(?:required\s*)?[:\-–—]\s*'
    r'(\d{1,2}(?:\.\d)?(?:\s*(?:-|–|to)\s*\d{1,2})?\s*\+?)(?!\s*(?:years?|yrs?)\b)', re.I)
# More forms of the label: "Years experience: 3+", "Yrs of experience: 3",
# "Experience (years): 3", "# of years experience: 3" (2026-09-27).
LABELLED_SHORT = re.compile(
    r'(?:#\s*of\s+)?\b(?:(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp)|experience\s*\(\s*(?:years?|yrs?)\s*\))'
    r'\s*(?:required\s*)?[:\-–—]\s*'
    r'(\d{1,2}(?:\.\d)?(?:\s*(?:-|–|to)\s*\d{1,2})?\s*\+?)(?!\s*(?:years?|yrs?)\b)', re.I)
SHORT_DEGREE = re.compile(r'\b(?P<degree>' + SHORT_FORMS + r')\s*\+\s*' + NUMBER + r'(?![\w\d])', re.I)
# "Exp: 3+ yrs" is as terse as "3+ YOE" (2026-09-27).
EXPERIENCE = re.compile(r'\b(?:experience|professional|industry|yoe|exp)\b', re.I)
# The work itself, named straight after the duration. "8+ years of hands-on
# FPGA designs" asks for eight years as plainly as "8 years of experience" does,
# and was read as asking nothing because none of the words above is in it --
# reported by the user on 2026-09-22. Only practice words and verbs of the
# trade: "30 years of pioneering" and "25 years of innovation" are a company
# describing itself, which is also why the bound below caps the number.
HANDS_ON = re.compile(
    r'^\s*(?:of\s+)?(?:(?:hands[-\s]?on|practical|proven|relevant|direct|demonstrated)\b'
    r'|(?:designing|developing|building|working|writing|coding|programming|debugging|'
    r'verifying|validating|testing|implementing|architecting|using|delivering|'
    r'shipping|performing|creating|doing)\b)', re.I)
HANDS_ON_MAX_YEARS = 15
LEADING_SUBJECT = re.compile(r'^\s+(?:in|of|with|working|doing|across|on|as)\b', re.I)
# A duration that has to pass, not one that has to have passed. Under a
# required heading a bare number of years is read as a requirement, and "ship
# two tape-outs within three years" is a deadline the job sets, not experience
# it asks for. `over` is deliberately absent: "over 5 years" is a floor.
ELAPSED = re.compile(r'\b(?:in|within|during|after|next|past|last)\s+(?:\w+\s+){0,2}$', re.I)
# A window of time, not an amount of work, on every path that admits a number.
# "Bachelor's degree ... within past 2 years" (NXP, 2026-09-26) is how recently
# the applicant graduated; the degree word beside it admitted the number as a
# degree path's years, and at three years it hid the new-grad posting. Narrower
# than ELAPSED, which would also drop "Experience in RTL design 3+ years".
WINDOW = re.compile(
    r'\b(?:(?:within|in|during|over)\s+(?:the\s+)?(?:past|last|previous|preceding)'
    r'|within(?:\s+the)?|(?:the\s+)?(?:past|last|previous))\s+'
    r'(?:\d{1,2}\s+months?\s+or\s+)?$', re.I)
SINCE_GRADUATION = re.compile(
    r'^\s*(?:of|since|after|from|following)\s+'
    r'(?:(?:your|the|their|a|an|degree|university|college|school)\s+)*'
    r'(?:graduat|complet|receiv|earn|obtain|conferr|start\s+date|hire\s+date|date\s+of\s+hire)'
    # Time a student still has ahead: "at least 1.5 years remaining until graduation".
    r'|^\s*(?:(?:remaining|left)\b|(?:until|before)\s+(?:your\s+)?graduat)',
    re.I)
# The years are the other way to qualify, not the degree's years: "Masters
# Degree or 5 years commercial experience" (Altera) asks nothing of a master's.
# Not "degree or equivalent and 3 years", where the years are still owed.
INSTEAD_OF_DEGREE = re.compile(r'^(?:(?!\b(?:and|with|plus)\b)[^.;]){0,60}\bor\s+(?:an?\s+)?$', re.I)
# Months of experience, as years: "36 months of experience" read as nothing
# (2026-09-27). Only where experience follows, so "within the past 6 months"
# stays a window.
MONTHS = re.compile(
    r'(?<![\w.])(\d{1,3})(?:\s*(?:-|–|—|to)\s*(\d{1,3}))?(\s*\+)?\s+months?\b'
    r'(?=\s+(?:of\s+)?(?:[\w-]+\s+){0,3}?(?:experience|exp)\b)', re.I)


def _as_years(found):
    def count(months):
        return f'{round(int(months) / 12, 1):g}'
    span = count(found[1]) + ('-' + count(found[2]) if found[2] else '')
    return span + (found[3] or '') + ' years'


# The unit left out of the second path: "3+ years of experience (or 1+ with
# Master's)" (2026-09-27).
UNITLESS = re.compile(
    r"(?<![\w.])(\d{1,2}(?:\.\d)?\s*\+?)(?=\s+(?:with|for)\s+(?:an?\s+|the\s+)?"
    r"(?:MS|BS|master|bachelor|PhD|doctora))", re.I)
# The degree named after the years it goes with: "4+ years of experience with
# a BS, or 2+ years with an MS". Only the degree before the years was read, so
# the first path took the second's degree and the MS path was lost
# (2026-09-27). Never across an `or`, which starts the next path.
DEGREE_AFTER = re.compile(
    r"^(?:(?!\bor\b)[^.;\d])*?(?:\b(?:with|and|plus|holding|having)\s+|\(\s*)(?:an?\s+|the\s+)?"
    r"(?P<degree>" + SHORT_FORMS + r"|bachelor(?:'s|s)?|master(?:'s|s)?)\b", re.I)
# The length of the thing offered: "a 2-year full-time rotational experience".
# Singular unit after an article, which a requirement does not use.
DURATION_OF = re.compile(r'\b(?:a|an|this|our|the)\s+$', re.I)
# A sentence about other positions. Intel's sponsorship paragraph says "skills
# shortage roles are typically STEM positions requiring ... a Bachelor's degree
# with at least three years of post-degree related job experience".
OTHER_POSITIONS = re.compile(
    r'\bskills?\s+shortage\b|\btypically\s+(?:\w+\s+){0,3}(?:positions|roles)\s+requir', re.I)
# Where a structured field ended. `jsearch.description_text` joins a payload's
# fields into one text and emits a field's key as a heading when the key names
# a qualification; without an end mark that heading's scope ran on into the
# next, unrelated field, so the same two fields in the other order were judged
# differently. A control character, because it cannot occur in prose.
SECTION_END = '\x1e'
NON_WORK = re.compile(r'^\s*[- ]?\s*(?:roadmap|degree|program(?:me)?|course|plan)\b', re.I)
# An age or years of school, not of work: "at least 18 years old" read as an
# eighteen-year requirement, "at least 3 years of college" as three (2026-09-27).
AGE_OR_SCHOOLING = re.compile(
    r'^\s*(?:old|of\s+age)\b'
    # "at least 3 years of a 4-year degree" too, which read as three years
    # of work (#258, 2026-10-02). Not "program": "years of program management".
    r'|^\s*(?:of\s+)?(?:(?:a|an|the|your)\s+)?(?:(?:\d|two|three|four|five)[-\s]year\s+)?'
    r"(?:(?:undergraduate|graduate|university|college|full[-\s]time|bachelor'?s?|master'?s?)\s+)?"
    r'(?:college|university|school|study|studies|coursework|education|degree)\b', re.I)
# Years the job gives, not years it asks for: "you will gain 3 years of experience".
OFFERED = re.compile(r'\b(?:gain|gaining|acquire|earn)\s+(?:\w+\s+){0,2}$', re.I)
# A master's with no years of its own as the other way in: "3 years of
# experience OR a Master's degree", "Bachelor's + 3 years, or Master's degree".
# The master's path asks nothing (2026-09-27).
MASTERS_INSTEAD = re.compile(
    r"^(?:(?!\bor\b)[^.;\d])*\bor\s+(?:an?\s+|the\s+)?(?:MS(?:EE|CS|CE|c)?|master(?:'s|s)?|"
    # "3+ years of experience, or Bachelor's degree in engineering" (2026-09-27).
    r"BS(?:EE|CS|CE|c)?|bachelor(?:'s|s)?)\b[^.;\d]*(?:[.;]|$)", re.I)
# The master's named first, with no years of its own, then "or" a bachelor's
# with years: "Master's degree in a quantitative field, or Bachelor's degree
# and 5+ years" asks nothing of a master's (2026-09-27).
MASTERS_FIRST = re.compile(
    r"\b(?:MS(?:EE|CS|CE|c)?|master(?:'s|s)?)\b(?:(?!\d)[^.;])*?\bor\s+(?:an?\s+)?(?:BS|bachelor)", re.I)
# Someone the posting supervises, not the posting itself. A role senior enough
# to mentor an intern is the opposite of an entry-level opening, and reading
# "you will mentor our interns" as an internship let such a posting skip the
# experience gate entirely.
SUPERVISES = re.compile(
    r'\b(?:mentor|supervis|manage|managing|lead|leading|coach|guid|train|'
    r'onboard|oversee|overseeing|support|collaborat|work)\w*\s+'
    r'(?:[\w,/-]+\s+){0,3}$', re.I)
# One end of a span, not the opening. Marvell's benefits line, "at every stage
# - from internship to retirement", is on half its postings and made each one
# an internship, a Senior Director's included.
SPAN_START = re.compile(r'\bfrom\s+$', re.I)
SPAN_END = re.compile(r'^\s+(?:to|through|until)\b', re.I)
# Directions to other openings. "Students: explore our internship
# opportunities" and "Looking for an internship? Visit our university page"
# are careers-site boilerplate on senior postings, and each made a ten-year
# requirement an entry-level opening's (2026-09-27).
POINTER = re.compile(
    r'\b(?:explore|visit|check\s+out|browse|see|view|learn\s+(?:more\s+)?about|'
    r'looking\s+for|interested\s+in|search\s+for)\s+(?:\w+\s+){0,2}$', re.I)
# An upper bound or a denial is not a minimum. "Fewer than three years" and
# "no more than 5 years" describe who may apply, not what they must already
# have, and reading the number as a floor rejected the postings that said it.
NOT_A_MINIMUM = re.compile(
    r'\b(?:no|not|without|less\s+than|fewer\s+than|under|up\s+to|at\s+most|'
    r'maximum(?:\s+of)?|max\.?)\s+(?:\w+\s+){0,2}$', re.I)
# The bound after the number: "5 years of experience or less", "5 years max"
# read as a five-year floor (2026-09-27).
UPPER_AFTER = re.compile(
    r'^\s*(?:of\s+(?:[\w-]+\s+){0,3}?)?(?:or\s+(?:less|fewer)|max(?:imum)?\b|at\s+most)', re.I)
# A floor stated as who is turned away: "Candidates with less than 5 years of
# experience will not be considered" (2026-09-27) is five years required.
TURNED_AWAY = re.compile(
    r"^\s*(?:of\s+)?(?:[\w-]+\s+){0,4}?(?:will\s+not|won't|need\s+not|are\s+not|cannot|can't)\s+"
    r'(?:be\s+)?(?:considered|apply|eligible|accepted)', re.I)
# Except that "no less than three years" is a floor stated in the negative.
# The bound above saw its "no" and discarded the requirement it introduces, so
# some of the strictest postings of all were read as stating nothing at all.
STILL_A_MINIMUM = re.compile(r'\b(?:no|not)\s+(?:less|fewer)\s+than\s*$', re.I)
# The denial can also follow the number instead of preceding it. "Five years of
# experience is not required" names the figure in order to rule it out, and
# reading the figure alone turned the postings most willing to take someone
# early into the ones this gate refused.
NOT_REQUIRED = re.compile(
    r"""^\s*(?:\w+\s+){0,4}?\b(?:not|isn'?t|aren'?t|no\s+longer)\s+(?:\w+\s+){0,2}"""
    r'(?:required|needed|necessary|mandatory|expected)\b', re.I)
# A denial is not an opening. "This is not an internship" and "no internships
# are available" name the thing they are refusing, and reading that name as
# evidence of an entry-level role let the posting skip the experience gate on
# the strength of a word that was there to exclude it.
DENIES = re.compile(
    r"\b(?:not|isn'?t|aren'?t|no|never|rather\s+than|instead\s+of|excluding|"
    r'other\s+than)\s+(?:\w+\s+){0,3}$', re.I)
# An internship someone has already done. "Prior internship experience" and
# "internship experience preferred" ask for a history; they do not describe the
# opening, and reading them as one let a posting skip the experience gate on
# the strength of a word about the applicant's past.
PRIOR = re.compile(
    r'\b(?:prior|previous|past|completed|former|earlier|relevant|'
    r'at\s+least\s+one)\s+(?:\w+\s+){0,2}$', re.I)
# Plural too: Intel's "obtained through ... job experience, internship
# experiences and or schoolwork" was read as an internship opening, which let
# a Senior CPU engineer's eight years skip the gate.
AS_EXPERIENCE = re.compile(r'^\s*(?:or\s+co-?op\s+)?experiences?\b', re.I)
# `or` always separates alternatives; `/` only does where it stands between the
# two degree paths -- spaced, as in "BS+4 / MS+2", or joining the degrees
# themselves. A slash inside a term of the trade, RTL/FPGA or analog/mixed-signal,
# is not an alternative, and reading it as one let the MS path's two years stand
# in for the five the posting asked of a bachelor's.
ALTERNATIVE = re.compile(
    r'\bor\b|\s/\s|\b(?:' + SHORT_FORMS + r'|bachelor\w*|master\w*)\s*/\s*(?:' + SHORT_FORMS + r'|bachelor\w*|master\w*)\b'
    # The master's path in brackets: "10+ years (5+ with MS)" (2026-09-27).
    r"|\(\s*\d{1,2}(?:\.\d)?\s*\+?\s*(?:years?|yrs?)\s+with\s+(?:an?\s+)?(?:MS|master)",
    re.I)

# A heading opens a section; a short sentence does not. "Python preferred."
# is two words and names a preference, and was read as a Preferred heading --
# which then suppressed the requirement on the line after it (in `degree`
# first, then Codex R6 here). A heading is written as one: it ends in a colon,
# or it is the name of a qualification section.
#
# The name, all of it, and not only its first word. Matching the first word
# alone read "Ideally you know Python." and "Bonus if you know Perl." as
# Preferred headings (2026-09-27), and missed "Must Have" and "Job
# Requirements" written as an HTML heading with no colon.
HEADING_VOCABULARY = frozenset('''
    minimum basic preferred desired desirable required requirement requirements
    qualification qualifications nice to have haves must education additional bonus
    points pluses plus a ideal ideally extra credit skills skill experience
    and & / job key core technical knowledge abilities competencies other
    what you need bring your who are we're looking for candidate profile
'''.split())
# The headings that end a section may name the company or the role, so their
# first word is enough: "About Acme", "Benefits at Acme".
NEUTRAL_HEADING = re.compile(r'^(?:education|degrees?|qualifications?|skills|experience|'
                             r'knowledge|technical\s+skills)\b', re.I)
SECTION_CLOSERS = re.compile(r'^(?:responsibilities|about\b|benefits\b|what\s+you)', re.I)


# A heading written in title case need not use only those words: Microsoft's
# "Additional Or Preferred Qualifications" and GE's "Desired Characteristics"
# stopped being headings under the word list alone, and their preferred years
# became requirements (found on the live index, 2026-09-27). It must still
# start like a heading and read like one -- short, capitalised, no full stop.
HEADING_START = re.compile(
    r'^(?:minimum|basic|preferred|desired|desirable|required|requirements?|qualifications?|nice|'
    r'education|additional|bonus|pluses|ideal(?:ly)?|extra|key|core|must|what|who|your|technical|'
    r'skills?|experience|other)\b', re.I)
CONNECTORS = {'or', 'and', 'of', 'the', 'to', 'a', 'an', 'for', 'in', 'with', '&', '/', 'we', 'you'}


def title_case_line(block, minimum_words=1):
    # Short, capitalised, and not a sentence: no full stop, question or comma at the end.
    block = block.strip().rstrip(':').strip()
    # "Preferred: Python" is a heading with its content, a line, not a section.
    if not block or block[-1] in '.!?,;' or ':' in block:
        return False
    words = re.findall(r"[A-Za-z][\w'’-]*|&|/", block)
    return (minimum_words <= len(words) <= 6
            and all(word[0].isupper() or word.lower() in CONNECTORS for word in words))


def is_heading(block):
    block = block.strip()
    # A bracketed marker annotates the line above it: Quanta's "(Preferred)"
    # opened a Preferred section and hid "5+ years of professional" (live
    # index, 2026-09-27).
    if block.startswith('('):
        return False
    if block.endswith(':') or SECTION_CLOSERS.match(block):
        return True
    words = re.findall(r"[\w'&/]+", block.lower())
    if words and all(word in HEADING_VOCABULARY for word in words):
        return True
    return bool(HEADING_START.match(block)) and title_case_line(block)


# UTF-8 read as Windows-1252, as some boards serve it: "7+ years inÂ\xa0Mixed-
# Signal" glued "in" to the next word and the requirement was not read (live
# index, 2026-09-27). Only the sequences that are never meant.
MOJIBAKE = (('Â ', ' '), ('Â ', ' '), ('â€™', "'"), ('â€˜', "'"),
            ('â€œ', '"'), ('â€\x9d', '"'), ('â€“', '–'),
            ('â€”', '—'))


def repair_mojibake(text):
    for broken, meant in MOJIBAKE:
        text = text.replace(broken, meant)
    return text


def years_value(text):
    """2 stays an int, 2.5 stays 2.5. Rounding either way answers the gate wrongly."""
    value = float(text)
    return int(value) if value.is_integer() else value


def fragment(text, match):
    """The words immediately governing a mention, back to the last break."""
    return (text[:match.start()].rsplit('.', 1)[-1]
            .rsplit('\n', 1)[-1].rsplit(';', 1)[-1])


def internship_experience(text):
    """Whether the posting asks for an internship the applicant has already done.

    Not a reason to refuse anything -- an internship already served is a
    qualification, and this only marks the posting so a reader can see why the
    word is there. It is also what keeps such a posting out of `entry_level`.
    """
    for match in ENTRY.finditer(text or ''):
        if PRIOR.search(fragment(text, match)):
            return True
        # "Your internship experience will involve", "the best and most
        # interesting internship experience": this internship, described, and
        # no internship asked for (#294, 2026-10-02).
        if (AS_EXPERIENCE.match(text[match.end():])
                and not THIS_INTERNSHIP.search(text[max(0, match.start() - 80):match.start()])):
            return True
    return False


THIS_INTERNSHIP = re.compile(r'\b(?:your|this|our|the\s+(?:best|most))\s+(?:[\w-]+\s+){0,3}$', re.I)


SENIOR_TITLE = re.compile(
    r'\b(?:staff|senior|sr\.?|principal|lead|manager|director|head\s+of|fellow|distinguished)\b', re.I)


# A title may name the openings in the plural: "Summer Interns 2027",
# "ASIC Co-ops", "RTL New Grads" (2026-09-27). Only the title: in the body the
# plural is usually other people.
# And a student, trainee or apprentice named in the title (2026-09-27).
ENTRY_PLURAL = re.compile(r'\b(?:interns|internships|co-?ops|new\s+(?:college\s+)?grad(?:uate)?s|'
                          r'students?|trainees?|apprentice(?:ship)?s?)\b', re.I)
# An opening for someone still studying, said without the word "intern":
# "graduating between December 2026 and June 2027", "Expected graduation
# date: May 2027", "currently enrolled in a Master's program" (2026-09-27).
STUDENT_OPENING = re.compile(
    r'\b(?:graduating\s+(?:in|between|by|from)|expected\s+graduation|graduation\s+date\s*:|'
    r'currently\s+(?:enrolled|pursuing)|must\s+be\s+(?:currently\s+)?enrolled|'
    # "new grads encouraged to apply" (2026-09-27).
    r'(?:new|recent|college|university)\s+(?:college\s+)?grad(?:uate)?s\s+(?:are\s+)?'
    r'(?:encouraged|welcome|invited|eligible)|'
    r'open\s+to\s+(?:new|recent|college|university)\s+(?:college\s+)?grad(?:uate)?s?)\b', re.I)
# The company's other programmes, not this opening: "Acme also offers new grad
# and internship opportunities", "... posted separately", "Ask about our
# internship program" (2026-09-27).
ELSEWHERE = re.compile(
    r'\b(?:we|our)\b[^.\n]*\balso\b|\balso\s+(?:run|runs|offer|offers|have|has|hire|hires|post|posts)\b'
    r'|\bseparately\b|\bask\s+about\b', re.I)
# The applicant as the intern, not someone they supervise: "You will work as
# an intern" matched the supervising verb "work" (2026-09-27).
AS_ROLE = re.compile(r'\bas\s+(?:an?\s+|the\s+)?$', re.I)
# A duration the job sets, not experience it asks for: "Position duration: 3
# years", "Contract length: 3 years", "Must commit to 3 years"; and a degree's
# own length, "Bachelor's degree (4-year)" (2026-09-27).
TERM = re.compile(
    r'\b(?:duration|length|term|commitment|commit\s+to)\s*:?\s*(?:of\s+)?$'
    # A frequency: "... and every 2 years thereafter" (live index, 2026-09-27).
    r'|\bevery\s+$'
    # The path for someone with no degree: "In lieu of a degree, minimum of 8
    # years" is an alternative, not a floor for a graduate (2026-09-27).
    r"|\b(?:in\s+lieu\s+of|without)\s+(?:an?\s+|the\s+)?(?:[\w'-]+\s+){0,2}?degree\b[^.;]*$"
    r"|\b(?:degree|bachelor\S*|master\S*|BS|MS)\s*\(\s*$", re.I)
# A preference in brackets with a subject of its own is an aside: "5+ years
# (8+ preferred)" and "(SystemVerilog preferred)" made the five years optional
# (2026-09-27). "(preferred)" alone still marks the years.
ASIDE = re.compile(r'\(([^()]*)\)')
MARKER_WORDS = {'preferred', 'desired', 'desirable', 'a', 'plus', 'strongly', 'highly', 'is', 'but',
                'not', 'required', 'nice', 'to', 'have', 'bonus', 'ideally', 'an', 'advantage', 'very'}


def _without_asides(clause):
    def drop(found):
        inside = found.group(1)
        words = re.findall(r"[\w+']+", inside.lower())
        if OPTIONAL.search(inside) and any(word not in MARKER_WORDS for word in words):
            return ' '
        return found.group(0)
    return ASIDE.sub(drop, clause)


# Years someone else has: the team, colleagues, a manager, the company. "Our
# team averages 10+ years of experience" and "We have 10 years of experience
# building chips" rejected postings as ten-year requirements (2026-09-27).
OTHER_PEOPLES_YEARS = re.compile(
    r'\bour\s+(?:[\w-]+\s+){0,2}?(?:team|teams|engineers|founders|leadership|leaders|experts|'
    r'people|staff|company|group|members)\b(?:\s+[\w-]+){0,4}?\s+$'
    r'|\b(?:engineers|mentors|colleagues|experts|leaders|managers?|peers|veterans|professionals|'
    r'people|team)\s+(?:who\s+have\s+|with\s+)(?:an?\s+average\s+of\s+|over\s+|more\s+than\s+)?$'
    r"|\b(?:we\s+have|we've|backed\s+by|built\s+on|founded\s+on)\s+(?:over\s+|more\s+than\s+)?$"
    r'|\baverag(?:e|es|ing)\s+(?:of\s+)?$', re.I)
# Unless the sentence is asking for that person.
ASKING = re.compile(r'\b(?:looking\s+for|seeking|hiring|searching\s+for|someone|somebody|'
                    r'candidates?|applicants?|need|needs|want|wants|ideal)\b', re.I)


def entry_level(title, text):
    """Whether the posting is an entry-level opening, not one that mentions one.

    The title is taken at its word. In the body the same nouns routinely
    describe other people or other times, so a mention governed by a
    supervising verb, by a denial, or by a word putting it in the applicant's
    past is read as what it is: evidence of seniority, of a posting ruling an
    internship out, or of a qualification being asked for.
    """
    if ENTRY.search(title or '') or ENTRY_PLURAL.search(title or ''):
        return True
    if SENIOR_TITLE.search(title or ''):
        # A staff or senior opening is not an internship whatever its
        # careers-site boilerplate says about internships (2026-09-27).
        return False
    for match in STUDENT_OPENING.finditer(text or ''):
        sentence = fragment(text, match)
        if not SUPERVISES.search(sentence) and not POINTER.search(sentence) and not DENIES.search(sentence):
            return True
    for match in ENTRY.finditer(text or ''):
        sentence = fragment(text, match)
        whole = sentence + re.split(r'[.\n;]', text[match.start():])[0]
        if ELSEWHERE.search(whole):
            continue
        supervised = SUPERVISES.search(sentence) and not AS_ROLE.search(sentence)
        if (not supervised and not DENIES.search(sentence)
                and not PRIOR.search(sentence) and not POINTER.search(sentence)
                and not (SPAN_START.search(sentence) and SPAN_END.match(text[match.end():]))
                and not AS_EXPERIENCE.match(text[match.end():])):
            return True
    return False


def evaluate(title, description):
    """Return auditable facts. Unknown experience is None, never assumed zero.

    Standalone experience requirements are mandatory unless marked optional.
    Separate mandatory requirements use the maximum lower bound. Only an
    explicit BS/MS alternative selects the stated MS path, never a degree bonus.
    """
    # Compatibility forms too: a full-width "５＋ years" (2026-09-27).
    text = unicodedata.normalize('NFKC', repair_mojibake(html.unescape(description or '')))
    # "5 yrs. of experience": the point ended the sentence (2026-09-27).
    text = re.sub(r'\b(yrs?|exp)\.(?=\s)', r'\1', text, flags=re.I)
    text = re.sub(r'\b([BM])\.\s*S\.', r'\1S', text, flags=re.I)
    # The degrees under other names, read as BS and MS (live index, 2026-09-27):
    # B.Tech / M.Tech, B.E. / M.E. and BE / ME in capitals only -- "be" and "me"
    # are words -- and a graduate degree, which is a master's or more.
    text = re.sub(r'\b([BM])\.?\s?Tech\b\.?', r'\1S', text, flags=re.I)
    text = re.sub(r'\b([BM])\.E\.?(?=[\s,/;)]|$)', r'\1S', text)
    text = re.sub(r'(?<![\w.])([BM])E(?=[\s,/;)]|$)', r'\1S', text)
    text = re.sub(r'\b(?:post-?\s?graduate|graduate|advanced)\s+degree\b', "Master's degree", text, flags=re.I)
    text = re.sub(r'<[^>]*>', '\n', text)
    # "A decade of experience" is ten years, and read as none (#259, 2026-10-02).
    text = re.sub(r'\b(?:a|one)\s+decade\b', '10 years', text, flags=re.I)
    text = re.sub(r'\b(two|2)\s+decades\b', '20 years', text, flags=re.I)
    # "Three plus (3+) years": the digits in brackets after the plus (#285).
    text = re.sub(r'\b(?:%s)\s*(?:\+|plus)\s*\(\s*(\d{1,2})\s*\+?\s*\)' % '|'.join(NUMBER_WORDS),
                  r'\1+', text, flags=re.I)
    text = SPELLED.sub(lambda found: str(NUMBER_WORDS[found.group(1).lower()]), text)
    text = PAREN_REPEAT.sub(r'\1', text)
    text = LABELLED.sub(r'\2 years of \1', text)
    text = LABELLED_SHORT.sub(r'\1 years of experience', text)
    text = MONTHS.sub(_as_years, text)
    text = UNITLESS.sub(r'\1 years', text)
    debug = dict(entry_override=entry_level(title, text),
                 internship_experience=internship_experience(text),
                 required_experience_years=None, effective_experience_years=None,
                 matched_text=[], hard_pass_reason='')
    # Two separate pieces of section context, because they are not opposites.
    # `optional_section` suppresses what follows a "Preferred" heading;
    # `required_section` admits a bare duration under a "Requirements" heading,
    # where the words `experience` and `required` are in the heading rather
    # than in the bullet. Either heading replaces both, and a Responsibilities,
    # About, Benefits or "What you" heading ends both.
    optional_section = required_section = False
    values, effective = [], []
    paths = {'bs': [], 'ms': []}
    # Keep explicit alternatives together even when formatted as separate bullets.
    text = re.sub(r'\s*\n\s*(?=(?:or\b|/))', ' ', text, flags=re.I)
    text = re.sub(r'(\bor|/)\s*\n\s*', r'\1 ', text, flags=re.I)
    # And across a semicolon: "Bachelor's and 3+ years; or Master's and 1+
    # years" was two blocks, and the master's path was no alternative at all.
    text = re.sub(r';\s*(?=or\b)', ', ', text, flags=re.I)
    # And across a full stop: Qualcomm's "... 3+ years of experience. OR
    # Master's degree and 2+ years ..." split the two paths (2026-09-27).
    text = re.sub(r'\.\s+(?=or\b)', ', ', text, flags=re.I)
    for block in re.split(r'[\n;]|(?<=[.!?])\s+', text):
        block = block.strip(' \t-*•')
        if not block:
            continue
        if SECTION_END in block:
            # A structured field ended here, and the heading it opened ends
            # with it -- whichever order the fields arrived in.
            optional_section = required_section = False
            block = block.replace(SECTION_END, '').strip(' \t-*•')
            if not block:
                continue
        # Headings establish scope across bullets, unlike an inline preference.
        if not re.search(r'\d', block):
            if OPTIONAL.search(block) and len(block.split()) <= 7 and is_heading(block):
                optional_section, required_section = True, False
            elif REQUIRED.search(block) and len(block.split()) <= 7 and is_heading(block):
                optional_section, required_section = False, True
            elif SECTION_CLOSERS.match(block):
                optional_section = required_section = False
            elif (optional_section and is_heading(block) and len(block.split()) <= 7
                  and not NEUTRAL_HEADING.match(block)):
                # Another heading ends a preferred section: "Key
                # Qualifications:" after "Preferred Qualifications:" (2026-09-27).
                # A sub-heading of it -- Education, Skills -- does not.
                optional_section = False
            continue
        if OTHER_POSITIONS.search(block):
            continue
        if REQUIRED.match(block):
            optional_section = False
        # Separate a mandatory clause from an optional one in the same sentence.
        cuts = []
        for separator in re.finditer(r'(?:,|\band\b)\s*(?=\d)|\bbut\b|,\s+(?=\S)', block, re.I):
            head, tail = block[:separator.start()], block[separator.end():]
            prior = list(YEARS.finditer(head))
            if not prior or DEGREE.search(head[prior[-1].end():]):
                continue
            if separator.group().startswith(',') and not re.match(r'\s*\d', tail):
                # A comma introducing something other than another number cuts
                # only where it hands an optional marker a subject of its own.
                # "5 years experience required, FPGA knowledge preferred" keeps
                # its five years; without the cut the trailing `preferred`
                # discarded the whole sentence, requirement included. "5 years
                # experience, preferred" is the same marker attaching to the
                # years themselves, and still makes them optional.
                # And where the preference has a subject of its own: "5+
                # years of experience with Verilog, SystemVerilog preferred"
                # (2026-09-27). "..., preferred but not required" does not.
                if not (OPTIONAL.search(tail) and len(tail.split()) > 1
                        and (REQUIRED.search(head) or not OPTIONAL.match(tail.strip()))):
                    continue
            cuts.append(separator)
        clauses, start = [], 0
        for cut in cuts:
            clauses.append(block[start:cut.start()])
            start = cut.end()
        clauses.append(block[start:])
        candidates = []
        for clause in clauses:
            clause = _without_asides(clause)
            if OPTIONAL.search(clause) or (optional_section and not REQUIRED.search(clause)):
                continue
            matches = list(YEARS.finditer(clause))
            for match in matches:
                before, after = clause[:match.start()], clause[match.end():]
                duration = (DURATION_OF.search(before)
                            and not re.search(r's$', match.group(), re.I))
                if TERM.search(before) or (OTHER_PEOPLES_YEARS.search(before) and not ASKING.search(before)) or years_value(match['low']) > MAX_REQUIRED_YEARS or NON_WORK.search(after) or AGE_OR_SCHOOLING.match(after) or OFFERED.search(before) or NOT_REQUIRED.search(after) or WINDOW.search(before) or SINCE_GRADUATION.match(after) or duration or (
                        NOT_A_MINIMUM.search(before)
                        and not STILL_A_MINIMUM.search(before)
                        and not TURNED_AWAY.match(after)) or UPPER_AFTER.match(after):
                    continue
                standalone = YEARS.fullmatch(clause.strip())
                # A bullet that leads with the years names what it asks for:
                # "7+ years in Mixed-Signal SOC products", "Who You Are: 7+
                # years in systems diagnostics" (live index, 2026-09-27).
                leading = (not clause[:match.start()].strip(' \t-*•·')
                           and LEADING_SUBJECT.match(after))
                under_heading = required_section and not ELAPSED.search(before)
                hands_on = (HANDS_ON.match(after) and not ELAPSED.search(before)
                            and years_value(match['low']) <= HANDS_ON_MAX_YEARS)
                if not (EXPERIENCE.search(clause) or REQUIRED.search(clause)
                        or DEGREE.search(before) or DEGREE_AFTER.match(after)
                        or standalone or under_heading or leading
                        or hands_on):
                    continue
                degrees = list(DEGREE.finditer(before))
                following = DEGREE_AFTER.match(after)
                # "BS, or 2+ years with an MS" is another degree's path, not
                # years instead of the BS.
                if not following and degrees and INSTEAD_OF_DEGREE.match(before[degrees[-1].end():]):
                    continue
                degree = (following['degree'] if following
                          else degrees[-1].group() if degrees else '').lower()
                if degree.startswith(('bs', 'bachelor')) and MASTERS_FIRST.search(before):
                    candidates.append((0, 'ms', clause.strip()))
                if not degree.startswith(('ms', 'master')) and MASTERS_INSTEAD.match(after):
                    # The years are the path without a master's, and the
                    # master's path asks none.
                    degree = degree or 'bs'
                    candidates.append((0, 'ms', clause.strip()))
                candidates.append((years_value(match['low']), degree, clause.strip()))
            for match in SHORT_DEGREE.finditer(clause):
                if any(m.start() <= match.end() and m.end() >= match.start() for m in matches):
                    continue
                candidates.append((years_value(match['low']), match['degree'].lower(), clause.strip()))
        if not candidates:
            continue
        bounds = [c[0] for c in candidates]
        ms = [c[0] for c in candidates if c[1].startswith(('ms', 'master'))]
        bs = [c[0] for c in candidates if c[1].startswith(('bs', 'bachelor'))]
        explicit_alternative = bool(ALTERNATIVE.search(block))
        values.extend(bounds)
        independent = [c[0] for c in candidates if not c[1]]
        if bs and ms and (explicit_alternative or not independent):
            # Two degree paths: alternatives, whether joined by "or" or only by
            # a comma. The user's decision of 2026-09-27; a master's path the
            # applicant can meet is not hidden behind a bachelor's.
            effective.append(max(ms + independent))
        elif ms and not bs and independent and explicit_alternative:
            # "3+ years, or 1+ with a master's": the untagged years are the
            # path without one.
            effective.append(max(ms))
        elif not independent and not (bs and ms) and (bs or ms):
            # One degree's path. Its other may be in the next bullet, sentence
            # or clause: "BS with 4+ years; MS with 2+ years" (user decision).
            paths['ms' if ms else 'bs'].append(max(bounds))
        else:
            effective.append(max(bounds))
        debug['matched_text'].extend(dict.fromkeys(c[2] for c in candidates))
    if paths['bs'] and paths['ms']:
        effective.append(max(paths['ms']))
    else:
        effective.extend(paths['bs'] + paths['ms'])
    debug['required_experience_years'] = max(values, default=None)
    debug['effective_experience_years'] = max(effective, default=None)
    if not debug['entry_override'] and debug['effective_experience_years'] is not None and debug['effective_experience_years'] > 2:
        debug['hard_pass_reason'] = 'required_experience_over_2_years'
    return debug
