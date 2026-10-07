"""Private, evidence-based fit policy shared by intake and live Review.

The public code contains no resume. The private operational profile names
supported work and unsupported core requirements, with evidence for each rule.
It never writes application decisions or deletes source inventory.
"""
from functools import lru_cache
import json
import os
from pathlib import Path
import re

from .job_text import readable_text
from .paths import DATA

BODY_FIELDS = ('descriptionPlain', 'job_description', 'description', 'jobDescription',
               'content', 'descriptionHtml', 'jobDescriptionHtml', 'summary',
               'jobSummary', 'responsibilities', 'ExternalResponsibilitiesStr')
REQUIRED_FIELDS = ('basic_qualifications', 'minimum_qualifications',
                   'required_qualifications', 'requirements', 'qualifications',
                   'required_skills', 'ExternalQualificationsStr')
PREFERRED = re.compile(r'^(?:preferred|desired|nice.to.have|bonus)\b', re.I)
REQUIRED = re.compile(r'^(?:(?:(?:basic|minimum|required|essential)\s+)?'
                      r'(?:qualifications|requirements)|(?:required|essential)\s+skills)\b', re.I)
DUTIES = re.compile(r'^(?:(?:key|job|main|your)\s+)*(?:responsibilities|duties)\b|^what you.*do\b', re.I)


def profile_path(ledger=None):
    if ledger is not None:
        return Path(ledger).with_name('resume_fit.json')
    return Path(os.environ.get('OPERATION1MILLION_STORE', DATA / 'store')) / 'operational/resume_fit.json'


def load(path=None):
    path = Path(path) if path is not None else profile_path()
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return _load(str(path.resolve()), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=8)
def _load(path, mtime, size):
    profile = json.loads(Path(path).read_text(encoding='utf-8'))
    if profile.get('version') != 1 or not profile.get('families'):
        raise ValueError('Resume fit profile needs version 1 and supported families')
    for rule in profile['families'] + profile.get('gaps', []):
        if not rule.get('id') or not rule.get('evidence') or not rule.get('all'):
            raise ValueError('Resume fit rules require id, evidence and all patterns')
        if rule.get('scope', 'duties') not in {'duties', 'requirements'}:
            raise ValueError('Resume fit rule has invalid scope')
        for pattern in rule['all'] + rule.get('any', []) + rule.get('unless', []):
            re.compile(pattern, re.I)
    return profile


def _text(value):
    if isinstance(value, dict):
        return '\n'.join(_text(v) for v in value.values())
    if isinstance(value, list):
        return '\n'.join(_text(v) for v in value)
    return readable_text(value)


def sections(raw):
    duties, required = [], []

    def consume(value, mode):
        if isinstance(value, dict):
            for key, content in value.items():
                name = str(key).replace('_', ' ')
                child = ('preferred' if PREFERRED.match(name) else
                         'required' if REQUIRED.match(name) or name.casefold() == 'required' else
                         'duties' if DUTIES.match(name) else mode)
                consume(content, child)
            return mode
        if isinstance(value, list):
            for item in value:
                mode = consume(item, mode)
            return mode
        for line in _text(value).splitlines():
            line = line.strip()
            for pattern, next_mode in ((PREFERRED, 'preferred'), (REQUIRED, 'required'),
                                       (DUTIES, 'duties')):
                match = pattern.match(line)
                if match:
                    mode = next_mode
                    line = line[match.end():].lstrip(' :-')
                    break
            if mode == 'duties':
                duties.append(line)
            elif mode == 'required':
                required.append(line)
        return mode

    for key in BODY_FIELDS:
        consume(raw.get(key), 'duties')
    for key in REQUIRED_FIELDS:
        consume(raw.get(key), 'required')
    highlights = raw.get('job_highlights')
    if isinstance(highlights, dict):
        consume(highlights, 'ignored')
    return '\n'.join(duties).strip(), '\n'.join(required).strip()


def _matches(rule, text):
    return (all(re.search(p, text, re.I) for p in rule['all'])
            and (not rule.get('any') or any(re.search(p, text, re.I) for p in rule['any']))
            and not any(re.search(p, text, re.I) for p in rule.get('unless', [])))


def assess(row, profile):
    """Missing/qualification-only JD is unknown; preferred skills are not duties."""
    if not profile:
        return {'verdict': 'unknown', 'reason': 'no_profile', 'evidence': []}
    raw = row.get('raw')
    raw = raw if isinstance(raw, dict) else {}
    prose, required = sections(raw)
    title = row.get('title') or ''
    for rule in profile.get('gaps', []):
        text = required if rule.get('scope') == 'requirements' else prose
        if text and _matches(rule, text if rule.get('scope') == 'requirements' else title + '\n' + text):
            return {'verdict': 'reject', 'reason': 'unsupported_core_requirement',
                    'evidence': [rule['id']]}
    if not prose:
        return {'verdict': 'unknown', 'reason': 'missing_jd', 'evidence': []}
    # A title repeated by a publisher is not a description of the work.
    remainder = re.sub(re.escape(title), '', prose, flags=re.I) if title else prose
    if len(prose) < 300 and not re.search(
            r'\b(?:design\w*|develop\w*|build\w*|verif\w*|validat\w*|test\w*|'
            r'commission\w*|implement\w*|debug\w*|maintain\w*|research\w*)\b', remainder, re.I):
        return {'verdict': 'unknown', 'reason': 'missing_jd', 'evidence': []}
    matches = [rule['id'] for rule in profile['families'] if _matches(rule, prose)]
    if matches:
        return {'verdict': 'keep', 'reason': 'supported_transfer', 'evidence': matches}
    return {'verdict': 'reject', 'reason': 'no_supported_core_duties', 'evidence': []}


def configured_assessment(row, rules=None):
    rules = rules or {}
    profile = rules.get('_resume_fit_profile') if '_resume_fit_profile' in rules else load()
    return assess(row, profile)


def lazy_assessment(row, rules):
    """Reuse one result within this row's evaluation only; never cache across rows."""
    @lru_cache(maxsize=1)
    def evaluate():
        return configured_assessment(row, rules)
    return evaluate


def rejection(row, rules, assessment=None):
    result = assessment() if assessment is not None else configured_assessment(row, rules)
    return 'resume_' + result['reason'] if result['verdict'] == 'reject' else ''
