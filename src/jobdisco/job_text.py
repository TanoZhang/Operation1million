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
