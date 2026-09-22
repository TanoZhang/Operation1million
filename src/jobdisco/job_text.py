"""Stable display titles without publisher time and location suffixes."""
import re
import unicodedata


POSTED_SUFFIX = re.compile(
    r'\s+(?:[|\-]\s*)?Posted\s+(?:today|yesterday|just now|'
    r'(?:a|an|one|\d+)\s+(?:minute|hour|day|week|month)s?\s+ago|'
    r'(?:on\s+)?\d{4}-\d{2}-\d{2}|(?:on\s+)?[A-Za-z]+\s+\d{1,2},?\s+\d{4})\s*$', re.I)


def clean_title(title, location=''):
    title = ' '.join(unicodedata.normalize('NFKC', title or '').split())
    location = ' '.join(unicodedata.normalize('NFKC', location or '').split())
    candidates = {location} if location else set()
    parts = [part.strip() for part in location.split(',')]
    if parts and parts[-1].casefold() in {'us', 'usa', 'united states', 'united states of america'}:
        prefix = ', '.join(parts[:-1])
        for country in ('US', 'USA', 'United States', 'United States of America'):
            candidates.add(', '.join(filter(None, [prefix, country])))

    def once(title):
        title = POSTED_SUFFIX.sub('', title).strip()
        for candidate in sorted(candidates, key=len, reverse=True):
            # Only a known full location suffix is removable; role words stay intact.
            match = re.search(r'\s+(?:[|\-]\s*)?' + re.escape(candidate) + r'$', title, re.I)
            if match:
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
            if isinstance(value, str) and value.strip():
                return value, kind
    paid = raw.get('jsearch')
    if isinstance(paid, dict):
        value = paid.get('job_description')
        if isinstance(value, str) and value.strip():
            return value, 'discovery'
    return '', None
