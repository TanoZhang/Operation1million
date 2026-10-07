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
                   'ExternalQualificationsStr')
PREFERRED = re.compile(r'^(?:preferred|desired|nice.to.have|bonus)\b', re.I)
REQUIRED = re.compile(r'^(?:(?:basic|minimum|required|essential)\s+)?(?:qualifications|requirements)\b', re.I)
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
    for key in BODY_FIELDS:
        mode = 'duties'
        for line in _text(raw.get(key)).splitlines():
            line = line.strip()
            if PREFERRED.match(line):
                mode = 'preferred'
            elif REQUIRED.match(line):
                mode = 'required'
            elif DUTIES.match(line):
                mode = 'duties'
            elif mode == 'duties':
                duties.append(line)
            elif mode == 'required':
                required.append(line)
    required.extend(_text(raw.get(key)) for key in REQUIRED_FIELDS)
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
    if not prose:
        return {'verdict': 'unknown', 'reason': 'missing_jd', 'evidence': []}
    title = row.get('title') or ''
    # A title repeated by a publisher is not a description of the work.
    remainder = re.sub(re.escape(title), '', prose, flags=re.I) if title else prose
    if len(prose) < 300 and not re.search(
            r'\b(?:design\w*|develop\w*|build\w*|verif\w*|validat\w*|test\w*|'
            r'commission\w*|implement\w*|debug\w*|maintain\w*|research\w*)\b', remainder, re.I):
        return {'verdict': 'unknown', 'reason': 'missing_jd', 'evidence': []}
    for rule in profile.get('gaps', []):
        text = required if rule.get('scope') == 'requirements' else title + '\n' + prose
        if _matches(rule, text):
            return {'verdict': 'reject', 'reason': 'unsupported_core_requirement',
                    'evidence': [rule['id']]}
    matches = [rule['id'] for rule in profile['families'] if _matches(rule, prose)]
    if matches:
        return {'verdict': 'keep', 'reason': 'supported_transfer', 'evidence': matches}
    return {'verdict': 'reject', 'reason': 'no_supported_core_duties', 'evidence': []}


def configured_assessment(row, rules=None):
    rules = rules or {}
    profile = rules.get('_resume_fit_profile') if '_resume_fit_profile' in rules else load()
    return assess(row, profile)


def rejection(row, rules):
    result = configured_assessment(row, rules)
    return 'resume_' + result['reason'] if result['verdict'] == 'reject' else ''
