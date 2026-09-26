"""Conservative, deterministic required-experience gate; no inferred equivalency."""
import html
import re

# A co-op is an internship under another name, and a recent or college graduate
# a new one; "Hardware Co-op" asking three years of Python was refused while
# the same posting called an internship was not. "Early career" and "entry
# level" stay out on purpose: those postings may still ask for years.
ENTRY = re.compile(r'\b(?:intern|internship|co-?op|new\s+(?:college\s+)?grad(?:uate)?|'
                   r'(?:university|college|recent)\s+graduate)\b', re.I)
# "Will be an advantage" (Samsung) is a preference; a bare "advantage for
# FullChip" (NVIDIA) is not the marker, so the article is required.
OPTIONAL = re.compile(r'\b(?:preferred|desired|nice\s+to\s+have|a\s+plus|bonus|ideally|'
                      r'an?\s+advantage|advantageous|an\s+asset)\b', re.I)
REQUIRED = re.compile(r'\b(?:required|requirements?|minimum|basic\s+qualifications|must\s+have|at\s+least)\b', re.I)
DEGREE = re.compile(r"\b(?:BS|MS|bachelor(?:'s|s)?|master(?:'s|s)?)\b", re.I)
# A hyphen can carry the unit as well as a range: "3-year experience" states
# what "3 years experience" states. And the bound can be fractional, which this
# gate has to be able to exceed -- reading 2.5 as 2 decides the posting the
# other way, and reading it as 5 decides it wrongly in the other direction.
# "3 or more years" is a floor like "3+ years", and "yrs" is how a terse
# posting abbreviates the unit; both used to read as stating nothing.
NUMBER = (r'(?P<low>\d{1,2}(?:\.\d)?)(?:\s*(?:-|–|—|to)\s*\d{1,2})?\s*\+?'
          r'(?:\s+or\s+(?:more|greater))?')
YEARS = re.compile(r'(?<![\w.])' + NUMBER + r'\s*(?:[-–—]\s*)?(?:years?|yrs?)\b', re.I)
# Nobody asks for more than this. A bigger number is the company describing
# itself -- "with over 40 years of experience, Acme leads..." -- and was read
# as a forty-year requirement.
MAX_REQUIRED_YEARS = 20
# Spelled-out counts, rewritten as digits before anything is read: "five years
# of experience" and "three (3) years" asked as plainly as "5 years" and were
# read as asking nothing.
NUMBER_WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7,
                'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12,
                'fifteen': 15, 'twenty': 20}
SPELLED = re.compile(r'\b(%s)\b(?=\s*(?:\(\s*\d{1,2}\s*\)\s*)?(?:\+|\s*-?\s*plus\b)?'
                     r'(?:\s+or\s+more)?\s*(?:[-–—]\s*)?(?:years?|yrs?)\b)'
                     % '|'.join(NUMBER_WORDS), re.I)
# "3 (three) years" and "three (3) years" once the word is a digit: one number.
PAREN_REPEAT = re.compile(r'\b(\d{1,2})\s*\(\s*(?:\d{1,2}|%s)\s*\)' % '|'.join(NUMBER_WORDS), re.I)
# A form's label ahead of its value: "Years of experience: 5+" is "5+ years of
# experience" written the other way round.
LABELLED = re.compile(
    r'\byears\s+of\s+((?:\w+\s+){0,2}?experience)\s*(?:required\s*)?[:\-–—]\s*'
    r'(\d{1,2}(?:\.\d)?(?:\s*(?:-|–|to)\s*\d{1,2})?\s*\+?)(?!\s*(?:years?|yrs?)\b)', re.I)
SHORT_DEGREE = re.compile(r'\b(?P<degree>BS|MS)\s*\+\s*' + NUMBER + r'(?![\w\d])', re.I)
EXPERIENCE = re.compile(r'\b(?:experience|professional|industry)\b', re.I)
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
    r'\bor\b|\s/\s|\b(?:BS|MS|bachelor\w*|master\w*)\s*/\s*(?:BS|MS|bachelor\w*|master\w*)\b',
    re.I)

# A heading opens a section; a short sentence does not. "Python preferred."
# is two words and names a preference, and was read as a Preferred heading --
# which then suppressed the requirement on the line after it (in `degree`
# first, then Codex R6 here). A heading is written as one: it ends in a colon,
# or it is the name of a qualification section.
HEADING_WORDS = re.compile(
    r'^(?:minimum|basic|preferred|desired|required|requirements?|qualifications?|'
    r'nice[-\s]to[-\s]have|education|additional|responsibilities|about|benefits|what\s+you|'
    r'desirable|bonus|pluses|ideal(?:ly)?|extra\s+credit)\b',
    re.I)


def is_heading(block):
    return block.rstrip().endswith(':') or bool(HEADING_WORDS.match(block))


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
    text = html.unescape(description or '')
    text = re.sub(r'\b([BM])\.\s*S\.', r'\1S', text, flags=re.I)
    text = re.sub(r'<[^>]*>', '\n', text)
    text = SPELLED.sub(lambda found: str(NUMBER_WORDS[found.group(1).lower()]), text)
    text = PAREN_REPEAT.sub(r'\1', text)
    text = LABELLED.sub(r'\2 years of \1', text)
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
            elif re.match(r'^(?:responsibilities|about\b|benefits\b|what you)', block, re.I):
                optional_section = required_section = False
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
                duration = (DURATION_OF.search(before)
                            and not re.search(r's$', match.group(), re.I))
                if years_value(match['low']) > MAX_REQUIRED_YEARS or NON_WORK.search(after) or NOT_REQUIRED.search(after) or WINDOW.search(before) or SINCE_GRADUATION.match(after) or duration or (
                        NOT_A_MINIMUM.search(before)
                        and not STILL_A_MINIMUM.search(before)):
                    continue
                standalone = YEARS.fullmatch(clause.strip())
                under_heading = required_section and not ELAPSED.search(before)
                hands_on = (HANDS_ON.match(after) and not ELAPSED.search(before)
                            and years_value(match['low']) <= HANDS_ON_MAX_YEARS)
                if not (EXPERIENCE.search(clause) or REQUIRED.search(clause)
                        or DEGREE.search(before) or standalone or under_heading
                        or hands_on):
                    continue
                degrees = list(DEGREE.finditer(before))
                if degrees and INSTEAD_OF_DEGREE.match(before[degrees[-1].end():]):
                    continue
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
