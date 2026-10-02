"""Stable display titles without publisher time and location suffixes."""
import re
import unicodedata
from html import escape, unescape

from bs4 import BeautifulSoup

from .location import US_STATES


# Shared by storage and Review; angle-bracket types such as vector<T> alone
# are not HTML and must remain visible.
MARKUP = re.compile(
    r'<\s*/?\s*(?:p|br|div|span|ul|ol|li|strong|b|em|i|h[1-6]|table|tr|td|th|a)\b'
    r'|<!--', re.I)


def readable_text(value):
    """Return visible prose, preserving angle-bracket types in plain text."""
    if not isinstance(value, str):
        return ''
    if MARKUP.search(value):
        return BeautifulSoup(value, 'html.parser').get_text('\n', strip=True).strip()
    # Entity decoding alone does not make plain text HTML. Parsing vector<T>
    # merely because the same sentence contains &amp; deletes the type name.
    plain = unescape(value)
    # Unless what it decodes to is markup: Greenhouse escapes its HTML, and the
    # page showed "<p>" and "<li>" as text (#207, 2026-10-01).
    if MARKUP.search(plain):
        return BeautifulSoup(plain, 'html.parser').get_text('\n', strip=True).strip()
    return plain.strip()


QUALIFICATION_FIELDS = (
    ('basic_qualifications', 'Basic qualifications'),
    ('required_qualifications', 'Required qualifications'),
    ('minimum_qualifications', 'Minimum qualifications'),
    ('qualifications', 'Qualifications'),
    ('requirements', 'Requirements'),
    ('preferred_qualifications', 'Preferred qualifications'),
    ('responsibilities', 'Responsibilities'),
)


def _qualification_text(value):
    """Render provider JSON qualification values with their field labels."""
    if isinstance(value, str):
        return readable_text(value)
    if isinstance(value, list):
        return '\n'.join(text for item in value if (text := _qualification_text(item)))
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            text = _qualification_text(item)
            if text:
                label = str(key).replace('_', ' ')
                label = label[:1].upper() + label[1:]
                parts.append(label + '\n' + text)
        return '\n'.join(parts)
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    return ''


def _with_qualifications(description, raw):
    """Preserve separately supplied prose and its qualification heading."""
    sections = []
    fields = QUALIFICATION_FIELDS + tuple((key, 'Provider excerpt') for key in TEASERS)
    for key, label in fields:
        value = raw.get(key)
        if key in TEASERS and value == description:
            continue
        text = _qualification_text(value)
        if text:
            sections.append(label + '\n' + text)
    if not sections:
        return description
    # Escape each plain fragment so the endpoint's HTML renderer cannot remove
    # a literal vector<T> when another section happens to contain markup.
    return '<div>' + '</div><div>'.join(escape(text) for text in
        [readable_text(description)] + sections if text) + '</div>'


# A dash may be an en or em dash (2026-09-27), and a month abbreviated with a
# point, "Sep. 7, 2026".
SEPARATOR = r'\s+(?:[|\-–—]\s*)?'
POSTED_SUFFIX = re.compile(
    # "Reposted", "Posted:" and "Posted on 09/07/2026" too (2026-09-27).
    SEPARATOR + r'(?:Re)?posted\s*:?\s+(?:today|yesterday|just now|'
    # "30+ Days Ago" is how Workday says a month or more.
    # And abbreviated: "1 hr ago", "3d ago" (2026-09-27).
    r'(?:a|an|one|\d+\+?)\s*(?:minute|min|hour|hr|h|day|d|week|wk|w|month|mo)s?\s+ago|'
    r'(?:on\s+)?\d{4}-\d{2}-\d{2}|(?:on\s+)?\d{1,2}/\d{1,2}/\d{4}|'
    r'(?:on\s+)?[A-Za-z]+\.?\s+\d{1,2},?\s+\d{4})\s*$', re.I)


# A requisition number is not the role: "RTL Engineer - Job ID 12345" and the
# same listing without it grouped apart (2026-09-27).
REQUISITION_SUFFIX = re.compile(
    r'\s*(?:[-|–—]\s*|\(\s*)?(?:job\s+id|req(?:uisition)?(?:\s+(?:id|no\.?|number))?)'
    r'\s*[:#]?\s*#?\s*[A-Za-z]{0,3}-?\d[\w-]*\s*\)?$', re.I)


def clean_title(title, location=''):
    title = ' '.join(unicodedata.normalize('NFKC', title or '').split())
    location = ' '.join(unicodedata.normalize('NFKC', location or '').split())
    candidates = {location} if location else set()
    parts = [part.strip() for part in location.split(',')]
    if parts and parts[-1].casefold() in {'us', 'usa', 'united states', 'united states of america'}:
        prefix = ', '.join(parts[:-1])
        for country in ('US', 'USA', 'United States', 'United States of America'):
            candidates.add(', '.join(filter(None, [prefix, country])))
        # And the place without the country: JSearch reads "Austin, TX, US"
        # where the title says "- Austin, TX" (2026-09-27).
        if prefix:
            candidates.add(prefix)
    # The state written the other way: "San Jose, California" in the title
    # and "San Jose, CA" in the location, or the reverse (2026-09-27).
    for candidate in list(candidates):
        pieces = [piece.strip() for piece in candidate.split(',')]
        for index, piece in enumerate(pieces):
            other = US_STATES.get(piece.casefold()) or next(
                (name.title() for name, code in US_STATES.items() if code == piece.casefold()), None)
            if other and index:
                candidates.add(', '.join(pieces[:index] + [other.upper() if len(other) == 2 else other]
                                         + pieces[index + 1:]))
    # The city alone: "CPU Physical Design Engineer, San Diego" and "(Austin)"
    # for "San Diego, California, United States of America" (#209, 25 queued
    # groups, 2026-10-01). The city is the first part, or the last where a
    # country code leads: "US, NV, Henderson".
    if len(parts) >= 2:
        city = parts[-1] if re.fullmatch(r'[A-Za-z]{2}', parts[0]) else parts[0]
        if len(city) >= 3:
            candidates.add(city)

    def once(title):
        title = POSTED_SUFFIX.sub('', title).strip()
        title = REQUISITION_SUFFIX.sub('', title).strip()
        # A hashtag is not the role, "#Embedded Software Engineer" (Qualcomm),
        # and a separator with nothing after it ends nothing (#215, 2026-10-01).
        title = re.sub(r'^#(?=[A-Za-z])', '', title)
        title = re.sub(r'\s*[,|\-–—:]\s*$', '', title)
        for candidate in sorted(candidates, key=len, reverse=True):
            # Only a known full location suffix is removable; role words stay intact.
            # A comma separates it as well: "Engineer, Austin, TX" came back
            # as "Engineer," (2026-09-27).
            # And "in Austin, TX" and "(Austin, TX)", which left "RTL
            # Engineer in" and the bracketed place behind (2026-09-27).
            # "Austin,TX" without a space is the same place (2026-09-27).
            # Or joined with a dash: "- Remote - US" for "Remote, US" (2026-09-27).
            place = r'(?:,\s*|\s*[-–]\s*)'.join(re.escape(piece.strip()) for piece in candidate.split(','))
            # Never the whole title: "Austin" for a posting in Austin stays.
            match = re.search(r'(?:\s*,\s*|\s+(?:in|at)\s+|' + SEPARATOR + ')' + place + r'$', title, re.I)
            if match and title[:match.start()].strip():
                return title[:match.start()].strip()
            match = re.search(r'\s*\(\s*' + place + r'\s*\)$', title, re.I)
            if match and title[:match.start()].strip():
                return title[:match.start()].strip()
        return title

    # Each suffix is only removable at the end, so whichever publisher put last
    # is the only one the first pass can reach: "Engineer - Posted today -
    # Austin, TX" came back still carrying the date, and calling this twice
    # returned something different from calling it once. Repeat until it
    # settles, which also makes the result the same however often it is applied.
    previous = None
    while title != previous:
        previous, title = title, once(title)
    return title


# Where providers put a posting's description, plain renderings first so that
# markup is parsed only when nothing else says it. `store.slim` reads the same
# two lists to decide when a teaser is a duplicate, so a field named here is
# one both the log and the review page recognise.
FULL_DESCRIPTIONS = ('descriptionPlain', 'job_description', 'description', 'jobDescription',
                     'content', 'descriptionHtml', 'jobDescriptionHtml')
TEASERS = ('descriptionTeaser', 'description_short')


def display_description(raw):
    """The description to show for a stored payload, and what kind it is.

    Returns (text, kind): kind is 'full' for the provider's own description,
    'excerpt' for a teaser the provider cut short, and 'discovery' for the text
    of the paid listing a direct posting took over, which the store keeps under
    `raw['jsearch']` for provenance. The current payload is always asked first,
    so a superseded listing is shown only where the current one says nothing.
    Measured on the live index, 2026-09-22: 1,280 of Phenom's 1,314 open
    postings carry a teaser and no full description, and the review page
    showed none of them.
    """
    if not isinstance(raw, dict):
        return '', None
    for fields, kind in ((FULL_DESCRIPTIONS, 'full'), (TEASERS, 'excerpt')):
        for key in fields:
            value = raw.get(key)
            if readable_text(value):
                return _with_qualifications(value, raw), kind
    # Qualification fields alone are not the posting's description: shown by
    # themselves, they hid the paid listing's full text behind one bullet.
    paid = raw.get('jsearch')
    if isinstance(paid, dict):
        value = paid.get('job_description')
        if readable_text(value):
            return _with_qualifications(value, raw), 'discovery'
    sections = _with_qualifications('', raw)
    if sections:
        return sections, 'full'
    return '', None
