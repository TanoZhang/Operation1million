"""Conservative, deterministic required-experience gate; no inferred equivalency."""
import html
import re

ENTRY = re.compile(r'\b(?:intern|internship|new\s+(?:college\s+)?grad(?:uate)?|university\s+graduate)\b', re.I)
OPTIONAL = re.compile(r'\b(?:preferred|desired|nice\s+to\s+have|a\s+plus|bonus|ideally)\b', re.I)
REQUIRED = re.compile(r'\b(?:required|requirements?|minimum|basic\s+qualifications|must\s+have|at\s+least)\b', re.I)
DEGREE = re.compile(r"\b(?:BS|MS|bachelor(?:'s|s)?|master(?:'s|s)?)\b", re.I)
NUMBER = r'(?P<low>\d{1,2})(?:\s*(?:-|–|—|to)\s*\d{1,2})?\s*\+?'
YEARS = re.compile(r'(?<![\w.])' + NUMBER + r'\s+years?\b', re.I)
SHORT_DEGREE = re.compile(r'\b(?P<degree>BS|MS)\s*\+\s*' + NUMBER + r'(?![\w\d])', re.I)
EXPERIENCE = re.compile(r'\b(?:experience|professional|industry)\b', re.I)
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
# A denial is not an opening. "This is not an internship" and "no internships
# are available" name the thing they are refusing, and reading that name as
# evidence of an entry-level role let the posting skip the experience gate on
# the strength of a word that was there to exclude it.
DENIES = re.compile(
    r"\b(?:not|isn'?t|aren'?t|no|never|rather\s+than|instead\s+of|excluding|"
    r'other\s+than)\s+(?:\w+\s+){0,3}$', re.I)


def entry_level(title, text):
    """Whether the posting is an entry-level opening, not one that mentions one.

    The title is taken at its word. In the body the same nouns routinely
    describe other people, so a mention governed by a supervising verb, or by a
    denial, is read as what it is: evidence of seniority, or of a posting
    ruling an internship out.
    """
    if ENTRY.search(title or ''):
        return True
    for match in ENTRY.finditer(text or ''):
        sentence = (text[:match.start()].rsplit('.', 1)[-1]
                    .rsplit('\n', 1)[-1].rsplit(';', 1)[-1])
        if not SUPERVISES.search(sentence) and not DENIES.search(sentence):
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
                 required_experience_years=None, effective_experience_years=None,
                 matched_text=[], hard_pass_reason='')
    optional_section = False
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
                optional_section = True
            elif REQUIRED.search(block) and len(block.split()) <= 7:
                optional_section = False
            elif re.match(r'^(?:responsibilities|about\b|benefits\b|what you)', block, re.I):
                optional_section = False
            continue
        if REQUIRED.match(block):
            optional_section = False
        # Separate a mandatory clause from an optional one in the same sentence.
        cuts = []
        for separator in re.finditer(r'(?:,|\band\b)\s*(?=\d)|\bbut\b', block, re.I):
            prior = list(YEARS.finditer(block[:separator.start()]))
            if prior and not DEGREE.search(block[prior[-1].end():separator.start()]):
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
                if NON_WORK.search(after) or (NOT_A_MINIMUM.search(before)
                                              and not STILL_A_MINIMUM.search(before)):
                    continue
                standalone = YEARS.fullmatch(clause.strip())
                if not (EXPERIENCE.search(clause) or REQUIRED.search(clause) or DEGREE.search(before) or standalone):
                    continue
                degrees = list(DEGREE.finditer(before))
                degree = degrees[-1].group().lower() if degrees else ''
                candidates.append((int(match['low']), degree, clause.strip()))
            for match in SHORT_DEGREE.finditer(clause):
                if any(m.start() <= match.end() and m.end() >= match.start() for m in matches):
                    continue
                candidates.append((int(match['low']), match['degree'].lower(), clause.strip()))
        if not candidates:
            continue
        bounds = [c[0] for c in candidates]
        ms = [c[0] for c in candidates if c[1].startswith(('ms', 'master'))]
        bs = [c[0] for c in candidates if c[1].startswith(('bs', 'bachelor'))]
        explicit_alternative = bool(re.search(r'\bor\b|/', block, re.I))
        values.extend(bounds)
        independent = [c[0] for c in candidates if not c[1]]
        effective.append(max(ms + independent) if bs and ms and explicit_alternative else max(bounds))
        debug['matched_text'].extend(dict.fromkeys(c[2] for c in candidates))
    debug['required_experience_years'] = max(values, default=None)
    debug['effective_experience_years'] = max(effective, default=None)
    if not debug['entry_override'] and debug['effective_experience_years'] is not None and debug['effective_experience_years'] > 2:
        debug['hard_pass_reason'] = 'required_experience_over_2_years'
    return debug
