"""Shared employer aliases, separate from immutable requisition identity.

Only explicit aliases merge brands. Legal suffix removal is safe for matching;
substring/fuzzy matching would merge staffing firms with their clients.
"""
from functools import lru_cache
import html
import re
import unicodedata


SUFFIXES = {'inc', 'incorporated', 'corp', 'corporation', 'llc', 'ltd',
            'limited', 'co', 'company', 'plc'}
# Catalog names and confirmed brand aliases. Add aliases here, not in callers.
GROUPS = (
    ('Marvell', ('Marvell Technology', 'Marvell Technologies', '31 MSI - (Marvell Semi',
                '31 MSI - (Marvell Semiconductor, Inc.)',
                '31 MSI - (Marvell Semiconductor Inc.) US')),
    ('AMD', ('Advanced Micro Devices',)),
    ('Amazon', ('Amazon.com',)),
    ('Cadence', ('Cadence Design Systems',)),
    ('Cisco', ('Cisco Systems',)),
    ('Micron', ('Micron Technology',)),
    ('Intel', ()), ('NVIDIA', ()), ('Qualcomm', ()), ('Broadcom', ()),
    ('Apple', ()), ('Google', ()), ('Microsoft', ()), ('Synopsys', ()),
    ('Altera', ()), ('Applied Materials', ()), ('KLA', ()),
    ('Lam Research', ()), ('Arm', ()), ('SanDisk', ()), ('SiFive', ()),
)


def _plain(value):
    text = unicodedata.normalize('NFKD', html.unescape(str(value or '')))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    words = re.sub(r'[\W_]+', ' ', text.casefold()).split()
    while words and words[-1] in SUFFIXES:
        words.pop()
    return ' '.join(words)


ALIASES = {_plain(alias): name for name, aliases in GROUPS for alias in (name, *aliases)}


@lru_cache(maxsize=4096)
def identity(name):
    plain = _plain(name)
    return _plain(ALIASES.get(plain, plain))


@lru_cache(maxsize=4096)
def display(name):
    """Stable public label; the original provider value remains in raw/ledger."""
    plain = _plain(name)
    if plain in ALIASES:
        return ALIASES[plain]
    # Preserve spelling and punctuation for unconfirmed brands.
    text = ' '.join(html.unescape(str(name or '')).split())
    suffix = r'[,\s]+(?:' + '|'.join(sorted(SUFFIXES)) + r')\.?\s*$'
    while True:
        shortened = re.sub(suffix, '', text, flags=re.I).rstrip(', ')
        if shortened == text:
            return text
        text = shortened


def label_group(group):
    """Normalize an in-memory group without mutating its stored job snapshots."""
    group['company'] = display(group.get('company'))
    group['jobs'] = [dict(job, company=display(job.get('company') or group['company']))
                     for job in group['jobs']]
    return group
