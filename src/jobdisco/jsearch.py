"""Fixed JSearch discovery plans, transport, and post-normalization filtering."""
from dataclasses import dataclass, replace
import hashlib
import math
import os
import re
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests
try:
    import tomllib
except ImportError:
    import tomli as tomllib

from .paths import CONFIG
from .collection_policy import retry_after_seconds
from .jsearch_access import QuotaExhausted


@dataclass(frozen=True)
class Query:
    query: str
    pages: int
    tier: str
    company_key: str = ''
    aliases: tuple = ()

    @property
    def key(self):
        return 'jsearch:' + hashlib.sha256(
            (self.company_key + '\n' + self.query).encode()).hexdigest()[:20]


def load_plan(path=CONFIG / 'jsearch_queries.toml'):
    with path.open('rb') as handle:
        config = tomllib.load(handle)
    quota = config.get('monthly_quota', 10000)
    utilization = config.get('target_utilization', .95)
    days = config.get('operating_days', 30)
    if type(quota) is not int or not 1 <= quota <= 10000 or not 0 < utilization <= 1 or type(days) is not int or days <= 0:
        raise ValueError('Invalid JSearch monthly quota, utilization, or operating days')
    config['monthly_target'] = math.floor(quota * utilization)
    config.setdefault('daily_budget', config['monthly_target'] // days)
    if type(config['daily_budget']) is not int or not 0 <= config['daily_budget'] <= config['monthly_target']:
        raise ValueError('Invalid daily page-credit budget')
    if type(config.get('billing_cycle_start_day', 1)) is not int or not 1 <= config.get('billing_cycle_start_day', 1) <= 31:
        raise ValueError('Invalid billing cycle start day')
    # How many pages one call may ask for. Narrower calls cost the same credits
    # and lose less when the provider times out.
    config.setdefault('max_pages_per_call', 10)
    if type(config['max_pages_per_call']) is not int or not 1 <= config['max_pages_per_call'] <= 20:
        raise ValueError('max_pages_per_call must be between 1 and 20')
    config.setdefault('country', 'us')
    config.setdefault('date_posted', 'today')
    config.setdefault('employment_types', ['FULLTIME', 'INTERN'])
    if config['country'] != 'us' or not config['employment_types'] or not set(config['employment_types']) <= {'FULLTIME', 'INTERN'}:
        raise ValueError('Functional discovery requires US full-time/intern settings')
    queries = []
    for row in config.get('query', []):
        if not row.get('enabled', True):
            continue
        text = row.get('query', '').strip()
        pages = row.get('pages')
        if not text or type(pages) is not int or not 1 <= pages <= 20 or re.search(r'(^|\s)-\w', text):
            raise ValueError('Queries require positive phrases and 1..20 pages')
        queries.append(Query(text, pages, row.get('tier', 'C')))
    if len({q.query.casefold() for q in queries}) != len(queries):
        raise ValueError('Duplicate JSearch query configuration')
    validate_budget(queries, config['daily_budget'])
    rules = config.setdefault('filter', {})
    for group in ('exclude_title_patterns', 'reject_title_patterns',
                  'keep_title_patterns', 'strong_terms', 'common_terms'):
        for expression in rules.get(group, []):
            re.compile(expression, re.I)
    defaults = {'min_confidence': 25, 'certain_strong_hits': 6, 'half_score': 15,
                'strong_weight': 3, 'common_weight': 1, 'title_multiplier': 2,
                'min_description_chars': 1500}
    for name, default in defaults.items():
        rules.setdefault(name, default)
        if type(rules[name]) is not int or rules[name] < 1:
            raise ValueError(f'Filter setting {name} must be a positive integer')
    if not 1 <= rules['min_confidence'] <= 100:
        raise ValueError('Filter min_confidence must fall between 1 and 100')
    return config, queries


def validate_budget(queries, budget):
    pages = sum(q.pages for q in queries)
    if pages > budget:
        raise ValueError(f'JSearch fixed plan needs {pages} page credits; budget is {budget}')
    return pages


def fallback_plan(config, sources, max_aliases=1):
    """Company discovery is an explicit list, separate from functional queries."""
    by_key = {s.company_key: s for s in sources}
    queries = []
    for row in config.get('company_fallbacks', []):
        if not row.get('enabled', True):
            continue
        key = row['company_key']
        if key not in by_key:
            raise ValueError(f'Unknown configured fallback company: {key}')
        source = by_key[key]
        aliases = tuple(dict.fromkeys(row.get('employer_aliases', []) + [source.company_name]))
        pages = row.get('pages', 1)
        if type(pages) is not int or not 1 <= pages <= 20:
            raise ValueError('Company fallback requires 1..20 pages')
        for alias in aliases[:max_aliases]:
            queries.append(Query(alias, pages, 'company', key, aliases))
    return queries


class SearchFailure(Exception):
    def __init__(self, message, stop=False):
        super().__init__(message)
        self.stop = stop


class Client:
    """Retrieve API job objects faithfully; no employer or business filtering."""
    def __init__(self, search, settings, guard, timeout=90, session=None):
        self.search, self.settings, self.guard = search, settings, guard
        self.timeout = timeout
        self.session = session or requests.Session()

    def close(self):
        self.session.close()

    def fetch(self, query):
        """Retrieve a query's pages, splitting a wide one across calls.

        Asking for too many pages at once times out at the provider, and a
        failed call is charged in full, so the widest asks were also the most
        expensive to lose. Measured over 52 queries: every call of 10 pages or
        fewer succeeded, while 4 of the 7 asking for 11 to 18 returned HTTP 504
        and took 61 page credits with them. The provider fetches the same pages
        either way; only how much one failure costs changes.
        """
        width = max(1, int(self.settings.get('max_pages_per_call', 10)))
        items, done = [], 0
        while done < query.pages:
            batch = min(query.pages - done, width)
            items.extend(self.fetch_batch(replace(query, pages=batch), first_page=done + 1))
            done += batch
        return items

    def fetch_batch(self, query, first_page=1):
        key = os.getenv('JSEARCH_API_KEY')
        if not key:
            raise SearchFailure('JSEARCH_API_KEY is missing; no request sent', stop=True)
        endpoint = urlsplit(self.search['endpoint_template'])
        if endpoint.scheme != 'https' or endpoint.netloc != 'api.openwebninja.com' or endpoint.path != '/jsearch/search-v2':
            raise ValueError('JSearch requires the configured OpenWeb Ninja HTTPS search-v2 endpoint')
        params = {'query': query.query, 'num_pages': query.pages,
                  'country': self.settings['country'], 'date_posted': self.settings['date_posted'],
                  'employment_types': ','.join(self.settings['employment_types'])}
        if first_page > 1:
            params['page'] = first_page
        url = urlunsplit(endpoint._replace(query=urlencode(params), fragment=''))
        response = None
        try:
            response = self.guard.get(self.session, url, credits=query.pages,
                                      headers={self.search['connection']['auth_header']: key},
                                      timeout=self.timeout)
            code = response.status_code
            if code in {401, 403, 429, 503}:
                wait = retry_after_seconds(response.headers.get('Retry-After')) or 0
                self.guard.pause(max(wait, 86400 if code in {401, 403} else 900))
                raise SearchFailure(f'JSearch HTTP {code}; account paused', stop=True)
            if code != 200:
                raise SearchFailure(f'JSearch HTTP {code}')
            payload = response.json()
            if not isinstance(payload, dict) or payload.get('status') != 'OK':
                raise SearchFailure('JSearch response status is not OK')
            data = payload.get('data')
            if not isinstance(data, dict) or not isinstance(data.get('jobs'), list):
                raise SearchFailure('Expected search-v2 data.jobs list')
            # num_pages already asks the provider for the fixed batch. A cursor
            # or a full result must not cause extra requests in this version.
            return data['jobs']
        except QuotaExhausted as exc:
            raise SearchFailure(str(exc), stop=True) from None
        except (requests.RequestException, ValueError):
            raise SearchFailure('JSearch transport or JSON error; reserved credits retained') from None
        finally:
            if response is not None:
                response.close()


def normalize_job(item, query, companies):
    # Use the existing normalized record shape; importing locally avoids a
    # collector/module cycle. Unknown employers never change the source catalog.
    from .collector import normalize, employer_normalize
    from .validate_sources import Source
    if not isinstance(item, dict):
        raise ValueError('Job must be an object')
    employer = item.get('employer_name') or 'Unknown employer'
    if not isinstance(employer, str):
        raise ValueError('Employer name must be text')
    key = companies.get(employer_normalize(employer))
    if not key:
        key = 'discovered_' + hashlib.sha256(employer.casefold().encode()).hexdigest()[:16]
    source = Source(query.key, 'discovery', key, employer, 'jsearch', '', {})
    link = item.get('job_apply_link') or item.get('job_google_link')
    if not link:
        link = next((r.get('apply_link') for r in item.get('apply_options', [])
                     if isinstance(r, dict) and r.get('apply_link')), None)
    row = normalize(source, {
        'title': item.get('job_title'), 'id': item.get('job_id'), 'url': link,
        'location': ', '.join(str(item[k]) for k in ('job_city', 'job_state', 'job_country') if item.get(k)),
        'posted_at': item.get('job_posted_at_datetime_utc')})
    row['raw'] = dict(item)
    row['raw']['discovery_queries'] = [query.query]
    return row


def excluded(title, rules):
    """Whether the job is one to decline outright, whatever it involves.

    This answers a different question from relevance. A defence programme is
    still a defence programme when the work is verification, and a director is
    still a director, so no score can overturn it and it is checked first.
    """
    return any(re.search(p, title or '', re.I)
               for p in rules.get('exclude_title_patterns', []))


def relevance(row, rules):
    """Score how much of the trade's vocabulary a posting uses, from 0 to 100.

    Terms only add. Nothing is deducted for a term being absent, so a tersely
    written posting is never punished for what it leaves out; it simply scores
    lower than one that spells the work out. A title match counts for more than
    a description match because a title is the employer's own summary.

    Enough distinct strong terms short-circuits the curve at 100: that many
    trade-exclusive proper nouns together are not something another industry
    prints by accident.
    """
    title = row.get('title') or ''
    if excluded(title, rules):
        # Score zero rather than high, so an excluded posting sinks in any ranking
        # that reads the stored number without re-applying the rules. Answered
        # from the title alone, before the rest of the posting is even read.
        return 0, []
    description = description_text(row)
    strong_weight = rules.get('strong_weight', 3)
    common_weight = rules.get('common_weight', 1)
    multiplier = rules.get('title_multiplier', 2)
    score, strong_hits, matched = 0, 0, []
    for patterns, weight, is_strong in (
            (rules.get('strong_terms', []), strong_weight, True),
            (rules.get('common_terms', []), common_weight, False)):
        for pattern in patterns:
            in_title = re.search(pattern, title, re.I)
            hit = in_title or re.search(pattern, description, re.I)
            if not hit:
                continue
            score += weight * (multiplier if in_title else 1)
            strong_hits += is_strong
            matched.append(hit.group(0).lower())
    if strong_hits >= rules.get('certain_strong_hits', 6):
        return 100, matched
    half = rules.get('half_score', 15)
    return (round(100 * score / (score + half)) if score else 0), matched


# Fields that carry no prose, so scanning them only invites false matches.
NON_PROSE_FIELDS = {
    'job_apply_link', 'job_google_link', 'apply_link', 'employer_website',
    'employer_logo', 'job_id', 'job_uid', 'job_posted_at_datetime_utc',
    'job_publisher', 'employer_name', 'job_latitude', 'job_longitude',
}


def description_text(row):
    """Everything the posting says about the work, in whatever field it says it.

    A provider may put the vocabulary in the description, in a skills array, or
    in highlight bullets; reading only one field would judge a posting on where
    its publisher chose to put the words rather than on what it says.
    """
    raw = row.get('raw')
    if not isinstance(raw, dict):
        return ''
    parts = []

    def walk(value):
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key not in NON_PROSE_FIELDS:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for key, value in raw.items():
        if key not in NON_PROSE_FIELDS and key != 'relevance':
            walk(value)
    return ' '.join(parts)


def rejection_reason(row, rules):
    """Title first, then the posting's vocabulary; the unreadable is kept.

    A title that names the work settles it either way, which is why an analog
    mixed-signal *verification* role survives while an analog *designer* does
    not. Only titles that say nothing reach the score, and only a posting whose
    full text uses none of the trade's vocabulary is dropped there; a truncated
    description is a publisher's excerpt, not silence, so it is kept.
    """
    title = row.get('title') or ''
    if excluded(title, rules):
        return 'excluded'
    if any(re.search(p, title, re.I) for p in rules.get('keep_title_patterns', [])):
        return ''
    if any(re.search(p, title, re.I) for p in rules.get('reject_title_patterns', [])):
        return 'title_mismatch'
    if relevance(row, rules)[0] >= rules.get('min_confidence', 25):
        return ''
    # A truncated description is not silence; it is a publisher's excerpt.
    if len(description_text(row)) < rules.get('min_description_chars', 1500):
        return ''
    return 'off_domain'


def collect(queries, client, settings, companies, persist):
    """Normalize and filter each fixed query, persisting through the shared store."""
    from .collector import employer_matches
    stats = {'jsearch_queries_planned': len(queries), 'jsearch_queries_completed': 0,
             'jsearch_pages_planned': sum(q.pages for q in queries),
             'jsearch_pages_used': 0, 'jsearch_jobs_raw': 0, 'jsearch_jobs_unique': 0,
             'jsearch_failures': 0, 'jsearch_jobs_rejected': 0,
             'jsearch_jobs_malformed': 0, 'jsearch_confidence': [],
             'jsearch_queries': []}
    unique = set()
    all_rows = []
    stop = False
    for query in queries:
        before = client.guard.credits
        detail = {'source_id': query.key, 'query': query.query, 'tier': query.tier,
                  'date_posted': settings['date_posted'], 'country': settings['country'],
                  'employment_types': settings['employment_types'],
                  'pages_planned': query.pages, 'pages_used': 0, 'jobs_raw': 0,
                  'jobs_accepted': 0, 'jobs_unique': 0, 'rejected': 0,
                  'malformed': 0, 'status': 'skipped', 'reason': ''}
        rows = []
        if not stop:
            try:
                items = client.fetch(query)
                detail['jobs_raw'] = len(items)
                stats['jsearch_jobs_raw'] += len(items)
                for item in items:
                    try:
                        row = normalize_job(item, query, companies)
                    except (ValueError, TypeError, KeyError):
                        detail['malformed'] += 1
                        continue
                    rules = settings.get('filter', {})
                    confidence, matched = relevance(row, rules)
                    if isinstance(row.get('raw'), dict):
                        row['raw']['relevance'] = {
                            'confidence': confidence,
                            'matched_terms': sorted(set(matched)),
                        }
                    reason = rejection_reason(row, rules)
                    if query.aliases and not employer_matches(row['company_name'], query.aliases):
                        reason = 'employer_mismatch'
                    if reason:
                        detail['rejected'] += 1
                        continue
                    identity = ('id', row['source_job_id']) if row['source_job_id'] else ('url', row['url'])
                    if identity not in unique:
                        detail['jobs_unique'] += 1
                        unique.add(identity)
                    stats['jsearch_confidence'].append(confidence)
                    rows.append(row)
                stats['jsearch_queries_completed'] += 1
                detail['status'] = 'partial' if detail['malformed'] else 'query_limited'
            except SearchFailure as exc:
                stats['jsearch_failures'] += 1
                detail['status'], detail['reason'] = 'failed', str(exc)
                stop = exc.stop
        else:
            detail['reason'] = 'Account stop condition from an earlier query'
        detail['pages_used'] = client.guard.credits - before
        detail['jobs_accepted'] = len(rows)
        stats['jsearch_pages_used'] += detail['pages_used']
        stats['jsearch_jobs_rejected'] += detail['rejected']
        stats['jsearch_jobs_malformed'] += detail['malformed']
        # A successful search is still query-limited, never a full board scan.
        persist(query, rows, detail)
        stats['jsearch_queries'].append(detail)
        all_rows.extend(rows)
    stats['jsearch_jobs_unique'] = len(unique)
    return all_rows, stats
