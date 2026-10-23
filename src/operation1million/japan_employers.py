"""Which Japanese employers are worth an application (the user, 2026-10-23).

"日本想方法把工资低 然后公司低级的 删掉 ... 不想浪费时间在三流公司": a listing
in Japan is offered when its employer is on the big-company list, set apart in
its own section when the employer is on neither list, and never offered when
it is a staffing firm, an agency or a hidden employer. Size cannot tell them
apart: measured on the 352 Japan listings cut by hand that day, the firms with
a thousand staff or more were nearly all engineer-staffing houses.

Pay drops only a listing outside the big list, and only when every yearly
figure it states is under the floor ("400-1000万" stays). A monthly figure
alone never does: bonuses are not in it (the user, 2026-10-23).
"""
import re
import tomllib
import unicodedata
from functools import lru_cache

from .paths import CONFIG

BIG, OTHER, STAFFING = 'big', 'other', 'staffing'


def _normal(text):
    return unicodedata.normalize('NFKC', str(text or '')).casefold()


def _names(names):
    """One pattern for a list of names: an ASCII name must stand as a word."""
    parts = []
    for name in names:
        name = _normal(name)
        escaped = re.escape(name)
        parts.append(rf'(?<![a-z0-9]){escaped}(?![a-z0-9])' if name.isascii() else escaped)
    return re.compile('|'.join(parts)) if parts else None


@lru_cache(maxsize=None)
def rules(path=CONFIG / 'japan_employers.toml'):
    with open(path, 'rb') as handle:
        config = tomllib.load(handle)
    return {'big': _names(config.get('big', [])),
            'staffing': _names(config.get('staffing', [])),
            'anonymous': [re.compile(p) for p in config.get('anonymous_patterns', [])],
            'staffing_text': [re.compile(p) for p in config.get('staffing_text', [])],
            'floor': config.get('min_yearly_pay_man_yen', 500)}


def classify(employer, description='', loaded=None):
    """BIG, OTHER or STAFFING for a Japanese listing's employer."""
    loaded = loaded or rules()
    name = _normal(employer).strip()
    raw_name = unicodedata.normalize('NFKC', str(employer or '')).strip()
    if (not name or (loaded['staffing'] and loaded['staffing'].search(name))
            or any(p.search(raw_name) for p in loaded['anonymous'])):
        return STAFFING
    if loaded['big'] and loaded['big'].search(name):
        return BIG
    text = unicodedata.normalize('NFKC', str(description or ''))
    if any(p.search(text) for p in loaded['staffing_text']):
        return STAFFING
    return OTHER


_YEARLY = re.compile(r'(?:年収|年俸|想定年収|予定年収|理論年収)')
_MAN = r'(\d{1,2},?\d{3}|\d{3,4})(?:\.\d)?\s*万'
_RANGE = re.compile(_MAN + r'円?\s*(?:[〜~～\-－―]|から)\s*' + _MAN)
_SINGLE = re.compile(_MAN)


def yearly_ceiling(description):
    """The highest yearly pay, in 万円, the description states; None when it
    states none, or states only where it starts ("400万円以上", "400万円〜")."""
    text = unicodedata.normalize('NFKC', str(description or ''))
    ceilings = []
    for match in _YEARLY.finditer(text):
        window = text[match.end():match.end() + 80]
        found = _RANGE.search(window)
        if found:
            ceilings.append(int(found.group(2).replace(',', '')))
            continue
        single = _SINGLE.search(window)
        if single:
            after = window[single.end():single.end() + 6]
            if re.match(r'円?\s*(?:以上|〜|~|～|-|から)', after):
                return None
            ceilings.append(int(single.group(1).replace(',', '')))
    ceilings = [c for c in ceilings if 100 <= c <= 5000]
    return max(ceilings) if ceilings else None


def low_pay(description, loaded=None):
    """Whether every yearly figure stated is under the floor."""
    loaded = loaded or rules()
    ceiling = yearly_ceiling(description)
    return ceiling is not None and ceiling < loaded['floor']
