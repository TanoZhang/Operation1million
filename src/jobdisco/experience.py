"""Conservative, deterministic required-experience gate; no inferred equivalency."""
import html
import re

ENTRY = re.compile(r'\b(?:intern|internship|new\s+(?:college\s+)?grad(?:uate)?|university\s+graduate)\b', re.I)
OPTIONAL = re.compile(r'\b(?:preferred|desired|nice\s+to\s+have|a\s+plus|bonus|ideally)\b', re.I)
REQUIRED = re.compile(r'\b(?:required|requirements?|minimum|basic\s+qualifications|must\s+have|at\s+least)\b', re.I)
DEGREE = re.compile(r"\b(?:BS|MS|bachelor(?:'s|s)?|master(?:'s|s)?)\b", re.I)
# A hyphen can carry the unit as well as a range: "3-year experience" states
# what "3 years experience" states. And the bound can be fractional, which this
# gate has to be able to exceed -- reading 2.5 as 2 decides the posting the
# other way, and reading it as 5 decides it wrongly in the other direction.
NUMBER = r'(?P<low>\d{1,2}(?:\.\d)?)(?:\s*(?:-|–|—|to)\s*\d{1,2})?\s*\+?'
YEARS = re.compile(r'(?<![\w.])' + NUMBER + r'(?:\s+|\s*[-–—]\s*)years?\b', re.I)
SHORT_DEGREE = re.compile(r'\b(?P<degree>BS|MS)\s*\+\s*' + NUMBER + r'(?![\w\d])', re.I)
EXPERIENCE = re.compile(r'\b(?:experience|professional|industry)\b', re.I)
# A duration that has to pass, not one that has to have passed. Under a
# required heading a bare number of years is read as a requirement, and "ship
# two tape-outs within three years" is a deadline the job sets, not experience
# it asks for. `over` is deliberately absent: "over 5 years" is a floor.
ELAPSED = re.compile(r'\b(?:in|within|during|after|next|past|last)\s+(?:\w+\s+){0,2}$', re.I)
NON_WORK = re.compile(r'^\s*[- ]?\s*(?:roadmap|degree|program(?:me)?|course|plan)\b', re.I)
# Someone the posting supervises, not the posting itself. A role senior enough
# to mentor an intern is the opposite of an entry-level opening, and reading
# "you will mentor our interns" as an internship let such a posting skip the
# experience gate entirely.
SUPERVISES = re.compile(
    r'\b(?:mentor|supervis|manage|managing|lead|leading|coach|guid|train|'
    r'onboard|oversee|overseeing|support|collaborat|work)\w*\s+'
    r'(?:\w+\s+){0,3}$', re.I)
# An upper bound or a denial is not a minimum. "Fewer than three years" and
# "no more than 5 years" describe who may apply, not what they must already
# have, and reading the number as a floor rejected the postings that said it.
NOT_A_MINIMUM = re.compile(
    r'\b(?:no|not|without|less\s+than|fewer\s+than|under|up\s+to|at\s+most|'
    r'maximum\s+of|max\.?)\s+(?:\w+\s+){0,2}$', re.I)
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
AS_EXPERIENCE = re.compile(r'^\s*(?:or\s+co-?op\s+)?experience\b', re.I)
# `or` always separates alternatives; `/` only does where it stands between the
# two degree paths -- spaced, as in "BS+4 / MS+2", or joining the degrees
# themselves. A slash inside a term of the trade, RTL/FPGA or analog/mixed-signal,
# is not an alternative, and reading it as one let the MS path's two years stand
# in for the five the posting asked of a bachelor's.
ALTERNATIVE = re.compile(
    r'\bor\b|\s/\s|\b(?:BS|MS|bachelor\w*|master\w*)\s*/\s*(?:BS|MS|bachelor\w*|master\w*)\b',
    re.I)


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
        if PRIOR.search(fragment(text, match)) or AS_EXPERIENCE.match(text[match.end():]):
            return True
    return False


def entry_level(title, text):
    """Whether the posting is an entry-level opening, not one that mentions one.

    The title is taken at its word. In the body the same nouns routinely
    describe other people or other times, so a mention governed by a
    supervising verb, by a denial, or by a word putting it in the applicant's
    past is read as what it is: evidence of seniority, of a posting ruling an
    internship out, or of a qualification being asked for.
    """
    if ENTRY.search(title or ''):
        return True
    for match in ENTRY.finditer(text or ''):
        sentence = fragment(text, match)
        if (not SUPERVISES.search(sentence) and not DENIES.search(sentence)
                and not PRIOR.search(sentence)
                and not AS_EXPERIENCE.match(text[match.end():])):
            return True
    return False


def evaluate(title, description):
    """Return auditable facts. Unknown experience is None, never assumed zero.

    Standalone experience requirements are mandatory unless marked optional.
    Separate mandatory requirements use the maximum lower bound. Only an
    explicit BS/MS alternative selects the stated MS path, never a degree bonus.
    """
    text = html.unescape(description or '')
    text = re.sub(r'\b([BM])\.\s*S\.', r'\1S', text, flags=re.I)
    text = re.sub(r'<[^>]*>', '\n', text)
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
    # Keep explicit alternatives together even when formatted as separate bullets.
    text = re.sub(r'\s*\n\s*(?=(?:or\b|/))', ' ', text, flags=re.I)
    text = re.sub(r'(\bor|/)\s*\n\s*', r'\1 ', text, flags=re.I)
    for block in re.split(r'[\n;]|(?<=[.!?])\s+', text):
        block = block.strip(' \t-*•')
        if not block:
            continue
        # Headings establish scope across bullets, unlike an inline preference.
        if not re.search(r'\d', block):
            if OPTIONAL.search(block) and len(block.split()) <= 7:
                optional_section, required_section = True, False
            elif REQUIRED.search(block) and len(block.split()) <= 7:
                optional_section, required_section = False, True
            elif re.match(r'^(?:responsibilities|about\b|benefits\b|what you)', block, re.I):
                optional_section = required_section = False
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
                if not (REQUIRED.search(head) and OPTIONAL.search(tail)
                        and len(tail.split()) > 1):
                    continue
            cuts.append(separator)
        clauses, start = [], 0
        for cut in cuts:
            clauses.append(block[start:cut.start()])
            start = cut.end()
        clauses.append(block[start:])
        candidates = []
        for clause in clauses:
            if OPTIONAL.search(clause) or (optional_section and not REQUIRED.search(clause)):
                continue
            matches = list(YEARS.finditer(clause))
            for match in matches:
                before, after = clause[:match.start()], clause[match.end():]
                if NON_WORK.search(after) or NOT_REQUIRED.search(after) or (
                        NOT_A_MINIMUM.search(before)
                        and not STILL_A_MINIMUM.search(before)):
                    continue
                standalone = YEARS.fullmatch(clause.strip())
                under_heading = required_section and not ELAPSED.search(before)
                if not (EXPERIENCE.search(clause) or REQUIRED.search(clause)
                        or DEGREE.search(before) or standalone or under_heading):
                    continue
                degrees = list(DEGREE.finditer(before))
                degree = degrees[-1].group().lower() if degrees else ''
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
        effective.append(max(ms + independent) if bs and ms and explicit_alternative else max(bounds))
        debug['matched_text'].extend(dict.fromkeys(c[2] for c in candidates))
    debug['required_experience_years'] = max(values, default=None)
    debug['effective_experience_years'] = max(effective, default=None)
    if not debug['entry_override'] and debug['effective_experience_years'] is not None and debug['effective_experience_years'] > 2:
        debug['hard_pass_reason'] = 'required_experience_over_2_years'
    return debug
