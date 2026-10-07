"""Fixed JSearch discovery plans, transport, and post-normalization filtering."""
from dataclasses import dataclass, replace
import hashlib
import html
import unicodedata
import math
from datetime import date
import os
import re
import time
from urllib.parse import urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
try:
    import tomllib
except ImportError:
    import tomli as tomllib

from .paths import CONFIG
from .collection_policy import retry_after_seconds
from .jsearch_access import AccountPaused, QuotaExhausted
from .job_text import clean_title
from .experience import (SECTION_END, OPTIONAL, REQUIRED, NEUTRAL_HEADING, is_heading,
                         title_case_line, repair_mojibake)


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
    # The plan renews every cycle_days from a fixed date, not on a day of the
    # month, so a period never stretches or shrinks with February.
    config.setdefault('cycle_start', '2026-09-16')
    config.setdefault('cycle_days', 30)
    try:
        date.fromisoformat(str(config['cycle_start']))
    except ValueError:
        raise ValueError('cycle_start must be an ISO date') from None
    if type(config['cycle_days']) is not int or not 1 <= config['cycle_days'] <= 366:
        raise ValueError('cycle_days must be between 1 and 366')
    # A budget day runs from one scheduled pass to the next, so these two say
    # when that is. Validated here rather than at the guard so a typo stops the
    # plan from loading instead of surfacing halfway through a paid run.
    config.setdefault('budget_timezone', 'America/Los_Angeles')
    config.setdefault('budget_day_resets_at', '04:38')
    if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', str(config['budget_day_resets_at'])):
        raise ValueError('budget_day_resets_at must be a 24-hour HH:MM time')
    try:
        ZoneInfo(str(config['budget_timezone']))
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(
            f"Unknown budget_timezone {config['budget_timezone']!r}; "
            'install tzdata or name a zone this host knows') from None
    # A sweep runs deeper than a daily pass because it is spending credits that
    # expire with the cycle rather than pacing a month.
    config.setdefault('backfill_max_pages_per_query', 200)
    if type(config['backfill_max_pages_per_query']) is not int or not 1 <= config['backfill_max_pages_per_query'] <= 1000:
        raise ValueError('backfill_max_pages_per_query must be between 1 and 1000')
    # Every call asks for exactly one page, so a page is the unit of both billing
    # and loss: a provider timeout now costs one credit instead of the whole ask.
    # This global ceiling validates each authored query cap and guards manual
    # queries. Actual use can stop earlier when the provider runs out.
    config.setdefault('max_pages_per_query', 40)
    if type(config['max_pages_per_query']) is not int or not 1 <= config['max_pages_per_query'] <= 100:
        raise ValueError('max_pages_per_query must be between 1 and 100')
    # Daily rows carry individual page caps so broad families can receive more
    # depth without multiplying narrow query variants. Backfill retains a
    # separate cap per priority tier because its sweep is deliberately deeper.
    for name in ('backfill_tier_pages',):
        table = config.setdefault(name, {})
        if not isinstance(table, dict):
            raise ValueError(f'{name} must be a table of tier to page cap')
        ceiling = config['backfill_max_pages_per_query']
        for tier, depth in table.items():
            if type(depth) is not int or not 1 <= depth <= ceiling:
                raise ValueError(f'{name}.{tier} must be between 1 and {ceiling}')
    config.setdefault('country', 'us')
    config.setdefault('date_posted', 'today')
    config.setdefault('employment_types', ['FULLTIME', 'INTERN'])
    if config['country'] != 'us' or not config['employment_types'] or not set(config['employment_types']) <= {'FULLTIME', 'INTERN'}:
        raise ValueError('Functional discovery requires US full-time/intern settings')
    publishers = config.setdefault('exclude_job_publishers', [])
    if not isinstance(publishers, list) or any(
            not isinstance(name, str) or not name.strip() or ',' in name for name in publishers):
        raise ValueError('exclude_job_publishers must be an array of publisher names without commas')
    config['max_pages_per_query_daily'] = config['max_pages_per_query']
    queries = []
    for row in config.get('query', []):
        if not row.get('enabled', True):
            continue
        text = row.get('query', '').strip()
        tier = row.get('tier', 'A')
        pages = row.get('pages', config['max_pages_per_query'])
        if not text or type(pages) is not int or not 1 <= pages <= config['max_pages_per_query'] or re.search(r'(^|\s)-\w', text):
            raise ValueError('Queries require positive phrases and a cap within max_pages_per_query')
        queries.append(Query(text, pages, tier))
    if len({q.query.casefold() for q in queries}) != len(queries):
        raise ValueError('Duplicate JSearch query configuration')
    validate_budget(queries, config['daily_budget'])
    # Caps may sum past the daily budget. Many queries reach their final cursor far
    # below theirs, so caps held to the budget left about half of it unspent; the
    # guard stops a day at its budget, and tier order decides who is left out.
    config['daily_pages_cap'] = sum(q.pages for q in queries)
    rules = config.setdefault('filter', {})
    if not isinstance(rules, dict):
        raise ValueError('filter must be a table')
    domains = rules.get('exclude_publisher_domains', [])
    if not isinstance(domains, list) or any(
            not isinstance(domain, str) or not re.fullmatch(
                r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', domain)
            for domain in domains):
        raise ValueError('filter.exclude_publisher_domains must be an array of lowercase DNS domains')
    walled = rules.get('account_walled_domains', [])
    if not isinstance(walled, list) or any(
            not isinstance(domain, str) or not re.fullmatch(
                r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', domain)
            for domain in walled):
        raise ValueError('filter.account_walled_domains must be an array of lowercase DNS domains')
    names = rules.get('account_walled_publishers', [])
    if not isinstance(names, list) or any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError('filter.account_walled_publishers must be an array of names')
    for group in ('exclude_employer_patterns', 'exclude_title_patterns', 'reject_title_patterns',
                  'function_title_patterns', 'hardware_title_terms', 'role_title_terms',
                  'us_person_required_patterns', 'exclude_publisher_patterns',
                  'keep_title_patterns', 'evidence_title_patterns', 'strong_terms', 'common_terms'):
        expressions = rules.get(group, [])
        if not isinstance(expressions, list) or any(not isinstance(p, str) for p in expressions):
            raise ValueError(f'filter.{group} must be an array of strings')
        for expression in expressions:
            re.compile(expression, re.I)
    defaults = {'min_confidence': 25, 'certain_strong_hits': 6, 'half_score': 15,
                'strong_weight': 3, 'common_weight': 1, 'title_multiplier': 2,
                'min_description_chars': 1500}
    # Zero is meaningful for one of them: it turns the short-circuit off and
    # leaves the curve to separate postings a fixed cut would have tied.
    floors = dict.fromkeys(defaults, 1)
    floors['certain_strong_hits'] = 0
    title_floor = rules.setdefault('title_only_floor', [])
    if (not isinstance(title_floor, list) or len(title_floor) > 5
            or any(type(value) is not int or not 0 <= value <= 100 for value in title_floor)):
        raise ValueError('filter.title_only_floor must list up to five integers from 0 to 100')
    for name, default in defaults.items():
        rules.setdefault(name, default)
        if type(rules[name]) is not int or rules[name] < floors[name]:
            raise ValueError(f'Filter setting {name} must be an integer of at least {floors[name]}')
    if not 1 <= rules['min_confidence'] <= 100:
        raise ValueError('Filter min_confidence must fall between 1 and 100')
    return config, queries


def validate_budget(queries, budget):
    """Every query must be able to reach its first page.

    A deliberately smaller invocation cap is valid, and company fallbacks use
    credits released by functional queries that stop early. The fixed plan's
    sum is checked separately while loading its configuration.
    """
    if len(queries) > budget:
        raise ValueError(
            f'JSearch plan holds {len(queries)} queries; the daily budget of '
            f'{budget} page credits cannot give each one a first page')
    return len(queries)


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
    def __init__(self, message, stop=False, budget=False, transient=False):
        super().__init__(message)
        self.stop = stop
        # A server error that a later request may not meet: HTTP 500, 502,
        # 504. On 2026-09-24 fifteen of 35 queries stopped for the day at their
        # first 504 and lost every page after it; one retry costs one credit.
        self.transient = transient
        # Reaching the budget is how an adaptive run is meant to end. Counting
        # it as a transport failure would make the failure count useless.
        self.budget = budget


PAGE_SIZE = 10


def page_identity(items):
    """The set of provider job ids on a page, or None when it cannot be taken.

    Used only to notice a provider that returns the same page twice. Items
    without an id are not comparable, so such a page never matches.

    An id sent as a list or an object cannot go in a set, and raising here
    discarded a page that had already been paid for, along with every sound
    result on it. A page carrying such an id is simply not comparable, which is
    what None says, and the repeated-page check is the only reader.
    """
    ids = set()
    for item in items:
        if not isinstance(item, dict) or not item.get('job_id'):
            continue
        try:
            ids.add(item['job_id'])
        except TypeError:
            return None
    return ids if len(ids) == len(items) and items else None


class Client:
    """Retrieve API job objects faithfully; no employer or business filtering."""
    def __init__(self, search, settings, guard, timeout=90, session=None):
        self.search, self.settings, self.guard = search, settings, guard
        self.timeout = timeout
        self.session = session or requests.Session()
        self.page_cursors = {}
        self.cursor_loops = set()

    def close(self):
        self.session.close()

    def fetch_page(self, query, page):
        """Retrieve one page as (items, exhausted).

        search-v2 may return fewer than ten jobs with more pages available.
        Only the opaque response cursor identifies the next page; ordinal page
        numbers are local progress counters, never API request parameters.
        """
        items = self.fetch_batch(replace(query, pages=1), first_page=page)
        token = self.page_cursors.get((query.key, page + 1))
        repeated = token and any(key == query.key and number <= page and value == token
                                 for (key, number), value in self.page_cursors.items())
        if repeated:
            self.cursor_loops.add(query.key)
        else:
            self.cursor_loops.discard(query.key)
        return items, not token or bool(repeated)

    def fetch(self, query):
        """Page through a whole query, for callers that want it in one piece."""
        items, page, previous = [], 1, None
        while page <= query.pages:
            batch, done = self.fetch_page(query, page)
            identities = page_identity(batch)
            if identities is not None and identities == previous:
                break
            previous = identities
            items.extend(batch)
            if done:
                break
            page += 1
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
        # Ask JSearch to omit known blocked publisher names; enforce locally too.
        if self.settings.get('exclude_job_publishers'):
            params['exclude_job_publishers'] = ','.join(self.settings['exclude_job_publishers'])
        if first_page > 1:
            token = self.page_cursors.get((query.key, first_page))
            if not token:
                raise SearchFailure('Missing search-v2 cursor; cannot request an ordinal page')
            params['cursor'] = token
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
                raise SearchFailure(f'JSearch HTTP {code}', transient=code in {500, 502, 504})
            payload = response.json()
            if not isinstance(payload, dict) or payload.get('status') != 'OK':
                raise SearchFailure('JSearch response status is not OK')
            data = payload.get('data')
            if not isinstance(data, dict) or not isinstance(data.get('jobs'), list):
                raise SearchFailure('Expected search-v2 data.jobs list')
            token = data.get('cursor')
            if token is not None and not isinstance(token, str):
                raise SearchFailure('Invalid search-v2 cursor')
            self.page_cursors[(query.key, first_page + 1)] = token or None
            return data['jobs']
        except AccountPaused as exc:
            raise SearchFailure(str(exc), stop=True) from None
        except QuotaExhausted as exc:
            raise SearchFailure(str(exc), stop=True, budget=True) from None
        except (requests.RequestException, ValueError):
            raise SearchFailure('JSearch transport or JSON error; reserved credits retained') from None
        finally:
            if response is not None:
                response.close()


def public_link(value):
    """The value as a public HTTP(S) address with a host, or None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    parts = urlsplit(value)
    return value if parts.scheme in {'http', 'https'} and parts.netloc else None


def link_host(value):
    """The lower-case host of a link or of a domain-form publisher name, or ''."""
    if not isinstance(value, str) or not value.strip():
        return ''
    value = value.strip()
    try:
        host = urlsplit(value if '://' in value or value.startswith('//') else '//' + value).hostname
    except ValueError:
        return ''
    return (host or '').lower().rstrip('.')


def _on(host, domains):
    return bool(host) and any(host == domain or host.endswith('.' + domain) for domain in domains)


def closed_link(value, rules):
    """A link on a blocked site or on one that wants an account first."""
    host = link_host(value)
    return _on(host, rules.get('exclude_publisher_domains', ())) or _on(
        host, rules.get('account_walled_domains', ()))


def _plain_name(value):
    return re.sub(r'[\s.]+', '', str(value or '').casefold().strip().removesuffix('.com'))


def walled_publisher(name, rules):
    """Whether JSearch's publisher name is one of the account-walled sites."""
    return bool(name) and _plain_name(name) in {
        _plain_name(entry) for entry in rules.get('account_walled_publishers', ())}


def open_apply_option(raw, rules):
    """An apply link on a site that is neither blocked nor walled, or None."""
    options = raw.get('apply_options') if isinstance(raw, dict) else None
    for option in options if isinstance(options, list) else ():
        if not isinstance(option, dict):
            continue
        link = public_link(option.get('apply_link'))
        if (link and not closed_link(link, rules)
                and not walled_publisher(option.get('publisher'), rules)
                and not _on(link_host(link), ('google.com',))):
            return link
    return None


def normalize_job(item, query, companies, rules=None):
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
    # The first candidate that is a public address, not the first that is
    # nonempty. A blank or `javascript:void(0)` apply link used to win, fail the
    # URL check and throw the whole job away with a working Google link sitting
    # right behind it; `https://` with no host passed the check and became the
    # posting's identity.
    options = item.get('apply_options') if isinstance(item.get('apply_options'), list) else []
    candidates = [item.get('job_apply_link'), item.get('job_google_link'),
                  *(r.get('apply_link') for r in options if isinstance(r, dict))]
    link = next((found for found in map(public_link, candidates) if found), None)
    # An apply link behind an account wall or on a blocked site is not the
    # posting's link when an open one is offered (2026-09-27): "Apply on Dice"
    # beside "Apply on the company's site" takes the company's.
    if rules and link and closed_link(link, rules):
        link = open_apply_option(item, rules) or link
    posted = item.get('job_posted_at_datetime_utc')
    if posted is not None and not isinstance(posted, (str, int, float)):
        # An optional field the provider sent in a shape nothing can store.
        # It stays in raw as sent; the posting keeps everything else. Missing
        # publisher data is not held against a posting anywhere else either.
        posted = None
    row = normalize(source, {
        'title': item.get('job_title'), 'id': item.get('job_id'), 'url': link,
        'location': ', '.join(str(item[k]) for k in ('job_city', 'job_state', 'job_country') if item.get(k)),
        'posted_at': posted})
    row['raw'] = dict(item)
    row['title'] = clean_title(row['title'], row['location'])
    if not row['title']:
        # Checked after cleaning, because cleaning is what can empty it. An
        # empty title raised in SQLite at the page checkpoint instead of here,
        # outside the per-item boundary, and took every valid posting on the
        # page -- already paid for -- down with it.
        raise ValueError('Job title is empty once cleaned')
    row['raw']['discovery_queries'] = [query.query]
    return row


_ALTERNATIONS = {}


class AnyOf:
    """Any of several patterns: one alternation where that is exact, the rest apart."""

    def __init__(self, joined, alone):
        self.joined, self.alone = joined, alone

    def search(self, text):
        found = self.joined.search(text) if self.joined is not None else None
        if found:
            return found
        return next((hit for hit in (pattern.search(text) for pattern in self.alone) if hit),
                    None)


def joinable(pattern):
    """Whether a pattern means the same inside an alternation as it does alone.

    Groups number themselves across the whole expression, so joining renumbers
    every group after the first pattern's: a backreference then points at a
    neighbour's capture, and two patterns naming the same group stop compiling
    at all -- after `load_plan` had accepted each of them, and after a paid page
    had been bought. A global inline flag is only legal at the start of an
    expression, which is not where it lands once joined.
    """
    if re.compile(pattern, re.I).groups:
        return False
    try:
        re.compile(f'(?:{pattern})|(?:)', re.I)
    except re.error:
        return False
    return True


def any_of(patterns):
    """One compiled alternation for a list of patterns, or None for an empty list.

    Asking "does any of these sixty patterns match" by trying sixty patterns
    costs sixty passes over the string; asking it as one alternation costs one.
    On the live queue that was 2.5 million searches a request. The answer is the
    same -- a boolean `any` over `search` is exactly what an alternation of
    non-capturing groups computes -- and `tests/test_exclusion_alternation.py`
    checks it against every title the store holds rather than against examples.

    Keyed by the pattern list, so a changed rule set compiles a new one and a
    test that swaps rules is not served a stale answer.
    """
    key = tuple(patterns)
    if key not in _ALTERNATIONS:
        if not key:
            _ALTERNATIONS[key] = None
        else:
            together = [p for p in key if joinable(p)]
            _ALTERNATIONS[key] = AnyOf(
                re.compile('|'.join(f'(?:{p})' for p in together), re.I) if together else None,
                [re.compile(p, re.I) for p in key if not joinable(p)])
    return _ALTERNATIONS[key]


def excluded(title, rules):
    """Whether the job is one to decline outright, whatever it involves.

    This answers a different question from relevance. A defence programme is
    still a defence programme when the work is verification, and a director is
    still a director, so no score can overturn it and it is checked first.
    """
    combined = any_of(rules.get('exclude_title_patterns', []))
    return bool(combined and combined.search(title or ''))


def needs_evidence(title, rules):
    """Whether this title has to be justified by the posting's own text.

    A middle answer between the two the filter had. `excluded` says the title
    settles it against the posting and no description can argue; the score says
    the title is ordinary and the description decides, but gives an unreadable
    description the benefit of the doubt. RF titles are neither: `RF Engineer`
    is not the trade, and `RFIC Digital Verification Engineer` plainly is, and
    hard-rejecting the pattern took both.

    So the title is let through and, when the publisher supplies prose, that
    prose is used to decide it. A missing description is not evidence against
    the posting: it gets the same benefit of the doubt as any other unreadable
    or truncated posting.
    """
    combined = any_of(rules.get('evidence_title_patterns', []))
    return bool(combined and combined.search(title or ''))


def names_the_trade(title, rules):
    """Whether a title itself names VLSI work: a keep pattern or a strong term."""
    keep = any_of(rules.get('keep_title_patterns', []))
    strong = any_of(rules.get('strong_terms', []))
    return bool((keep and keep.search(title or '')) or (strong and strong.search(title or '')))


def title_blocked(title, rules):
    """The soft title block: another function's word, and none of the trade's.

    Unlike `excluded`, a title that also names the work is let through to be
    scored -- "Low Power Verification Engineer" is the trade, "Power Integrity
    Engineer" is not. The paid filter and the review queue ask the same
    question through this, so a direct board's posting is held to the rule a
    paid result is.
    """
    title = title or ''
    if names_the_trade(title, rules):
        return False
    combined = any_of(rules.get('reject_title_patterns', []))
    if combined and combined.search(title):
        return True
    # The softer tier. Its words name a function that is sometimes silicon work
    # and sometimes not, and the first version dropped both alike: measured on
    # the live queue, 38 early-career groups -- "AI GPU Power Architect - New
    # College Grad", NAND and DRAM product engineering internships -- went with
    # "Supply Chain Planner". A title that says what hardware it is about and
    # what engineering it does, or that it is an early-career opening, is kept.
    function = any_of(rules.get('function_title_patterns', []))
    if not (function and function.search(title)):
        return False
    subject = any_of(rules.get('hardware_title_terms', []))
    role = any_of(rules.get('role_title_terms', []))
    return not (subject and subject.search(title) and role and role.search(title))


ANALOG_CHIP_ROLE = re.compile(
    r'\b(?:analog|mixed[-\s]?signal|AMS)\b.{0,65}\b(?:design|layout|engineer|intern)\b', re.I)
ANALOG_CHIP_INTERN = re.compile(
    r'\b(?:analog|mixed[-\s]?signal|AMS)\b.{0,65}\b(?:hardware|design|layout)\b'
    r'.{0,35}\b(?:intern|internship)\b', re.I)
ANALOG_CHIP_EVIDENCE = re.compile(
    r'\b(?:ASIC|SoC|VLSI|RTL|Verilog|SystemVerilog|SRAM|DRAM|'
    r'test\s+chips?|IC\s+layout|analog\s+IC|integrated\s+circuit|'
    r'tape[-\s]?outs?|DRC|LVS|Cadence\s+Virtuoso)\b', re.I)


def analog_chip_evidence(title, description):
    """Rescue chip-evidenced analog roles and unreadable analog chip interns."""
    if (not ANALOG_CHIP_ROLE.search(title or '')
            or re.search(r'\b(?:PCB|board|power\s+electronics)\b', title or '', re.I)):
        return False
    if not (description or '').strip() and ANALOG_CHIP_INTERN.search(title or ''):
        return True
    return len({match.group(0).casefold() for match in
                ANALOG_CHIP_EVIDENCE.finditer(description or '')}) >= 2


def publisher_excluded(url, raw, rules):
    """Whether the posting comes through a job site the user has blocked.

    Asked on the whole link and on the publisher JSearch names, because one
    can be missing or disagree with the other; a blocked site is blocked by
    whichever says so. The whole link rather than its host since the user
    asked for "trabajo" to go wherever it appears, an Amazon address included.
    """
    publisher = raw.get('job_publisher') if isinstance(raw, dict) else None
    # Evidence-backed domains are host matches, separate from the user's
    # broader text exclusions. Never match a domain mentioned in a URL path.
    for value in (url, publisher):
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        try:
            host = urlsplit(value if '://' in value or value.startswith('//')
                            else '//' + value).hostname
        except ValueError:
            continue
        host = (host or '').lower().rstrip('.')
        if any(host == domain or host.endswith('.' + domain)
               for domain in rules.get('exclude_publisher_domains', [])):
            return True
    combined = any_of(rules.get('exclude_publisher_patterns', []))
    if combined and (combined.search(url or '')
                     or (isinstance(publisher, str) and combined.search(publisher))):
        return True
    return account_walled(url, raw, rules)


def account_walled(url, raw, rules):
    """Whether reaching the posting needs an account or a membership.

    Asked for on 2026-09-27: a third-party listing that cannot reach the real
    posting in one click without signing up is blocked. Its link is on a
    walled site, or JSearch names a walled publisher and the link is only its
    Google Jobs page. An open apply option elsewhere keeps the posting.
    """
    host = link_host(url)
    publisher = raw.get('job_publisher') if isinstance(raw, dict) else None
    walled = _on(host, rules.get('account_walled_domains', ())) or (
        walled_publisher(publisher, rules) and (not host or _on(host, ('google.com',))))
    return walled and open_apply_option(raw, rules) is None


def employer_excluded(row, rules):
    raw = row.get('raw') if isinstance(row.get('raw'), dict) else {}
    employer = row.get('company_name') or row.get('company') or raw.get('employer_name') or ''
    combined = any_of(rules.get('exclude_employer_patterns', []))
    return bool(combined and combined.search(str(employer)))


def relevance(row, rules, description=None):
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
    if excluded(title, rules) or employer_excluded(row, rules):
        # Score zero rather than high, so an excluded posting sinks in any ranking
        # that reads the stored number without re-applying the rules. Answered
        # from the title alone, before the rest of the posting is even read.
        return 0, []
    description = description_text(row) if description is None else description
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
    # A short-circuit at a fixed number of strong terms stops the count exactly
    # where it starts being informative: everything from six distinct terms to
    # thirty-four read 100 alike, 798 postings deep, with nothing at all between
    # 70 and 99. Set `certain_strong_hits` to 0 to let the curve keep running.
    certain = rules.get('certain_strong_hits', 6)
    if certain and strong_hits >= certain:
        return 100, matched
    half = rules.get('half_score', 15)
    confidence = round(100 * score / (score + half)) if score else 0
    # A posting whose board publishes no description -- or only an excerpt --
    # was scored on its title's few words and read as barely relevant: "Design
    # Verification Intern" scored 12. The user asked on 2026-09-22 for the
    # title to decide instead. So such a posting scores at least what a posting
    # with the same kind of title typically scores when it does publish a full
    # description; see `title_only_floor` in the config for the measurement.
    # Only a floor: a higher score from the words it has is kept. Not for an
    # evidence title, whose name is exactly what may not be taken on trust.
    if (len(description) < rules.get('min_description_chars', 1500)
            and not needs_evidence(title, rules)):
        from .ranking import bucket
        floors = rules.get('title_only_floor', [])
        band = bucket(title)
        if band < len(floors):
            confidence = max(confidence, floors[band])
    return confidence, matched


# Fields that carry no prose, so scanning them only invites false matches.
NON_PROSE_FIELDS = {
    'job_apply_link', 'job_google_link', 'apply_link', 'employer_website',
    'employer_logo', 'job_id', 'job_uid', 'job_posted_at_datetime_utc',
    'job_publisher', 'employer_name', 'job_latitude', 'job_longitude',
    'job_city', 'job_state', 'job_country', 'job_location', 'job_employment_type',
    'job_employment_types', 'job_posted_at_timestamp', 'job_posted_at',
    'city', 'state', 'country', 'location', 'locations', 'employment_type',
    'employment_types', 'posted_at', 'created_at', 'updated_at',
}
TITLE_FIELDS = {'title', 'job_title', 'name', 'position_name'}

# Fields this collector writes into a provider's payload. They record how a
# posting was found and judged, not what it says, so they are never read back as
# its prose. `discovery_queries` was the one missing: the search phrase itself
# became evidence, so an ordinary RTL role asking five years was accepted
# whenever the query that found it said "Intern" -- and an antenna job scored
# as silicon work whenever it was found by a query naming the trade.
COLLECTOR_FIELDS = frozenset({'relevance', 'experience_filter', 'discovery_queries', 'apple_detail', 'detail_evidence'})

TAGS = re.compile(r'<[^>]{0,400}>')
WHITESPACE = re.compile(r'\s+')
ESCAPED_TAG = re.compile(r'&lt;/?(?:p|li|ul|ol|div|br|h[1-6]|span|strong|b|em|i|a)\b', re.I)


# A field whose name is a qualification heading. `requirements` was missing
# (Codex R5): a PhD under a "requirements" field was read as bare prose.
HEADING_KEY = re.compile(r'preferred|desired|required|requirements?|qualifications', re.I)


def field_heading(key):
    """A field's name written as a heading. The colon is what says so: since
    R6 a line is a heading only when it reads as one, and "job required skills"
    did not, so its requirement had no section (2026-09-27)."""
    return key.replace('_', ' ') + ':'


def description_text(row, structured=False):
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
                if key not in NON_PROSE_FIELDS and key not in COLLECTOR_FIELDS:
                    heading = structured and HEADING_KEY.search(key)
                    if heading:
                        parts.append(field_heading(key))
                    walk(item)
                    if heading:
                        parts.append(SECTION_END)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for key, value in raw.items():
        # The title is scored separately with its higher title weight. Only
        # suppress these names at the payload root: a nested skill `name` is
        # useful prose and must remain searchable.
        # B61: a direct posting that replaced a paid one keeps the paid payload
        # under `jsearch` as provenance. It is not read for requirements, where
        # a superseded one can only refuse the posting wrongly; relevance still
        # reads it, where extra vocabulary can only add.
        if structured and key == 'jsearch':
            continue
        if key not in NON_PROSE_FIELDS and key not in TITLE_FIELDS and key not in COLLECTOR_FIELDS:
            # B49: a qualification heading is scoped to its own field. The mark
            # after the field closes it, so "preferred qualifications" no
            # longer reaches into the job description that happens to follow.
            heading = structured and HEADING_KEY.search(key)
            if heading:
                parts.append(field_heading(key))
            walk(value)
            if heading:
                parts.append(SECTION_END)
    # Markup is not prose. A publisher's excerpt is kept rather than judged, on
    # the grounds that a short description is truncation and not silence -- but
    # a few hundred words of boilerplate wrapped in tags measured well past the
    # length that decides it, so the excerpt was judged after all and dropped.
    # Greenhouse escapes its markup. Left escaped, its "<p>" and "<li>" were
    # no line breaks, the whole description one line with no headings, and a
    # U.S.-citizenship line under "Preferred" read as required (#269, 2026-10-02).
    joined = '\n'.join(parts)
    if ESCAPED_TAG.search(joined):
        joined = html.unescape(joined)
    if structured:
        text = re.sub(r'</?(?:p|li|ul|ol|div|br|h[1-6])\b[^>]*>', '\n', joined, flags=re.I)
        return TAGS.sub(' ', text).strip()
    return WHITESPACE.sub(' ', TAGS.sub(' ', joined)).strip()


SOFTWARE_TITLE = re.compile(r'\bsoftware\b', re.I)
# Deliberately exclude generic hardware, embedded, validation, CPU/GPU and
# silicon (including Silicon Valley). Ranking vocabulary is not JD evidence.
SOFTWARE_VLSI_EVIDENCE = re.compile(
    r'\b(?:ASIC|FPGA|VLSI|RTL|Verilog|SystemVerilog|VHDL|UVM|'
    r'ATPG|SRAM|DRAM|Cadence\s+Virtuoso|Synopsys\s+Design\s+Compiler|'
    r'pre[-\s]?silicon|post[-\s]?silicon|'
    r'(?:chip|silicon|SoC|integrated\s+circuit)\s+(?:design|verification|validation|'
    r'debug|bring[-\s]?up)|physical\s+design|static\s+timing\s+analysis)\b', re.I)
# Real prose fields observed in the stored provider payloads. A catalog path,
# department, title, or superseded paid payload must never stand in for a JD.
SOFTWARE_JD_FIELDS = frozenset({
    'description', 'job_description', 'descriptionHtml', 'descriptionPlain',
    'descriptionTeaser', 'description_short', 'content', 'job_highlights',
    'qualifications', 'basic_qualifications', 'preferred_qualifications',
    'requirements', 'responsibilities', 'skills', 'required_skills',
    'ExternalQualificationsStr', 'ExternalResponsibilitiesStr', 'ShortDescriptionStr',
})


def software_jd_rejection(row, rules=None):
    """Shared automatic-admission gate; returns a reason or an empty string.

    A private resume profile can establish transferable duties or unknown JD.
    Otherwise software titles need chip-specific evidence in current prose;
    neither an old score nor title/search metadata can supply it.
    """
    if not SOFTWARE_TITLE.search(row.get('title') or ''):
        return ''
    from .resume_fit import configured_assessment
    fit = configured_assessment(row, rules)
    if fit['verdict'] == 'keep' or fit['reason'] == 'missing_jd':
        return ''
    raw = row.get('raw')
    raw = raw if isinstance(raw, dict) else {}
    prose = description_text({'raw': {key: value for key, value in raw.items()
                                     if key in SOFTWARE_JD_FIELDS}}, structured=True)
    if not prose:
        return 'missing_software_jd'
    return '' if SOFTWARE_VLSI_EVIDENCE.search(prose) else 'no_vlsi_evidence'


def experience_debug(row, text=None):
    from .experience import evaluate
    return evaluate(row.get('title'),
                    description_text(row, structured=True) if text is None else text)


def us_person_required(text, rules):
    """Whether the posting's own text requires U.S. citizenship or U.S. person status.

    A hard pass, asked for on 2026-09-22: the applicant cannot meet it, so no
    title or score argues it back in. Read from the structured text, the same
    text the experience requirement is read from, so a paid listing a direct
    posting has superseded cannot impose a requirement the company never
    stated. What the patterns deliberately leave alone is in the config.
    """
    # An entity or a no-break space is a space: "U.S.&nbsp;citizenship is
    # required" was missed, where the other gates unescape (2026-09-27).
    text = unicodedata.normalize('NFKC', repair_mojibake(html.unescape(text or '')))
    # Sentences are split at full stops, and "U.S." is full of them: the lead
    # of "If the role requires U.S. citizenship, candidates must be U.S.
    # citizens" was " citizenship, candidates ", its condition lost
    # (2026-09-27). The same text with those points blanked, same offsets.
    plain = ABBREVIATION.sub(lambda found: found.group().replace('.', ' '), text)
    for pattern in rules.get('us_person_required_patterns', []):
        optional_spans = preferred_spans(text)
        for match in re.finditer(pattern, text, re.I):
            # The sentence the match stands in, up to it. A requirement stated
            # conditionally is not this posting's requirement: "ITAR projects,
            # which may require U.S. citizenship" and Microsoft's boilerplate
            # "If the role requires US citizenship, as indicated in the job
            # description" were both passing postings that ask for neither --
            # found reading every removal in the live queue, 2026-09-22.
            lead = re.split(r'[.;:!?\n\u2022]', plain[max(0, match.start() - 200):match.start()])[-1]
            # An adversative starts a new clause: permission to work remotely
            # does not soften the citizenship requirement after "but".
            lead = re.split(r'\bbut\b|\bhowever\b', lead, flags=re.I)[-1]
            # Only the bare "If hired," is unconditional. "If selected for a
            # position that requires a clearance" still names a condition.
            lead = re.sub(r'\bif\s+(?:hired|selected|offered\s+the\s+position)\s*(?:,|$|(?=(?:you|candidates?|applicants?)\b))',
                          '', lead, flags=re.I)
            # "... Green Card holder, or authorized to work in the US" lists
            # a way in anyone with work authorization has (2026-09-27).
            rest = re.split(r'[.;!?\n•]', plain[match.end():match.end() + 200])[0]
            # A condition or a licence after it: "... if working on ITAR
            # projects", "... where applicable", "... unless an export
            # license is obtained" (2026-09-27).
            if TRAILING_CONDITION.match(rest) or LICENCE_INSTEAD.search(rest):
                continue
            # Under a preferred heading, or a line labelled as a preference.
            if any(start <= match.start() < end for start, end in optional_spans):
                continue
            if WORK_AUTHORIZATION.search(rest):
                continue
            # About some other positions, not this one: "Some positions
            # require U.S. citizenship", "For positions requiring access to
            # classified information, ...", "... is required for positions
            # supporting government contracts" (2026-09-27).
            if OTHER_POSITIONS.search(lead) or OTHER_SCOPE.match(rest):
                continue
            if not HEDGED.search(lead) and not DENIED.search(lead):
                return True
    return required_citizenship_bullet(text)


# The requirement as a bare bullet under a required heading: "Requirements:
# - BS in EE - U.S. Citizenship" said nothing the patterns could read
# (2026-09-27). Only the bare noun phrase, and only under a heading that
# requires; under Preferred or About it is not this posting's requirement.
CITIZENSHIP_BULLET = re.compile(
    r'^\s*(?:U\.?\s?S\.?|United\s+States)\s+(?:citizens?(?:hip)?|persons?)'
    r'\s*(?:\(\s*required\s*\))?\s*\.?\s*$', re.I)


def required_citizenship_bullet(text):
    required = False
    for line in re.split(r'[\n•]', text or ''):
        if SECTION_END in line:
            required = False
            line = line.replace(SECTION_END, '')
        line = line.strip(' \t-*')
        if not line:
            continue
        if is_heading(line) and len(line.split()) <= 7:
            required = bool(REQUIRED.search(line)) and not OPTIONAL.search(line)
            continue
        if required and CITIZENSHIP_BULLET.match(line):
            return True
    return False


TRAILING_CONDITION = re.compile(
    r'^\s*,?\s*(?:if|where|when|whenever|depending|as\s+(?:needed|applicable|required))\b', re.I)
LICENCE_INSTEAD = re.compile(
    # "..., or be able to obtain a US export license" (live queue, 2026-09-27).
    r'\b(?:unless|or)\s+(?:\w+\s+){0,5}?(?:an?\s+)?(?:U\.?\s?S\.?\s+)?(?:export\s+)?licen[cs]e\b', re.I)
PREFERENCE_LABEL = re.compile(r'^\s*[-*•]?\s*(?:preferred|desired|nice[-\s]to[-\s]have|bonus)\b[^:\n]{0,30}:', re.I)


def preferred_spans(text):
    # Character ranges under a preferred heading or on a preference-labelled
    # line. "Preferred Qualifications: - Must be a U.S. citizen" is not this
    # posting's requirement, and was a hard pass (2026-09-27).
    spans, start, optional, offset = [], None, False, 0
    for line in text.splitlines(keepends=True):
        stripped = line.replace(SECTION_END, '').strip(' \t\r\n-*')
        if SECTION_END in line:
            optional = False
        bulleted = line.lstrip()[:1] in ('-', '*', '•')
        # Any heading ends a preferred section, a known one or not: Blue
        # Origin's "Export Control Regulations" after its preferred list was
        # read as more of it, and hid its U.S. person requirement (live
        # index, 2026-09-27). Its own sub-headings do not.
        heading = stripped and not bulleted and (
            (is_heading(stripped) and len(stripped.split()) <= 7) or title_case_line(stripped, 2))
        if heading and not NEUTRAL_HEADING.match(stripped):
            optional = bool(OPTIONAL.search(stripped))
        elif optional or PREFERENCE_LABEL.match(line):
            spans.append((offset, offset + len(line)))
        offset += len(line)
    return spans


ABBREVIATION = re.compile(r'\b(?:U\.\s?S\.(?:\s?A\.)?|e\.g\.|i\.e\.|etc\.)', re.I)
WORK_AUTHORIZATION = re.compile(
    r'\bor\s+(?:\w+\s+){0,3}(?:authori[sz]ed|eligible|permitted|able)\s+to\s+work\b'
    # "... or hold a valid work visa", "... or H-1B holder" (2026-09-27).
    r'|\bor\s+(?:\w+\s+){0,3}(?:work\s+(?:visa|authori[sz]ation|permit)|H-?1B|OPT|EAD)\b', re.I)
OTHER_POSITIONS = re.compile(
    r'\b(?:some|certain|many|most|several|select|other)\s+(?:of\s+(?:our|the)\s+)?'
    r'(?:positions|roles|jobs|programs|projects|cases|opportunities)\b'
    # Plural only: "This position requires that the candidate ... be a US
    # Citizen" is this posting's own requirement (live index, 2026-09-27).
    r'|\b(?:positions|roles|jobs)\s+(?:that\s+|which\s+)?requir'
    r'|\b(?:positions|roles|jobs)\s+(?:that|which)\s*$', re.I)
OTHER_SCOPE = re.compile(
    r'^\s*(?:only\s+)?(?:for|on)\s+(?:positions|roles|those|certain|some|defense|government|'
    r'programs|projects|work\s+on)\b', re.I)


# Words that make what follows conditional rather than stated.
HEDGED = re.compile(r'\b(?:if|may|might|could|where|whether|should)\b', re.I)
# A denial just ahead of the requirement: "You do not need to be a U.S.
# citizen" and "Candidates are not required to hold U.S. citizenship" say the
# opposite of what the pattern after them matches, and were hard passes.
DENIED = re.compile(r"(?:\b(?:not|never)|n't)\s+(?:\w+\s+){0,2}$", re.I)


def eligibility_rejection(row, rules, requirements=None):
    """Return the posting-level eligibility rejection and parsed experience.

    Paid intake and the Review queue must apply these hard checks in the same
    order. Keeping the orchestration here prevents a newly added eligibility
    rule from reaching one path but not the other.

    Updates raw['experience_filter'] when raw is a dictionary, preserving the
    paid collector's diagnostic contract. The supplied requirements, when
    present, must be structured text from this same row.
    """
    requirements = (description_text(row, structured=True)
                    if requirements is None else requirements)
    experience = experience_debug(row, requirements)
    if isinstance(row.get('raw'), dict):
        row['raw']['experience_filter'] = experience
    reason = experience['hard_pass_reason']
    if not reason and us_person_required(requirements, rules):
        reason = 'us_person_required'
    if not reason:
        from .degree import phd_only
        if phd_only(row.get('title'), requirements):
            reason = 'phd_only'
    if not reason:
        from .resume_fit import rejection as resume_rejection
        reason = resume_rejection(row, rules)
    return reason, experience


def rejection_reason(row, rules, description=None, score=None):
    """Hard rejects, software JD evidence, then existing title/score policy.

    Software titles require current chip-specific JD evidence even when the
    title names ASIC/FPGA. Missing software prose is held, not auto-admitted.

    A title that names the work settles it either way. Analog design/layout
    needs chip evidence unless its explicit IC title or an unreadable analog
    internship settles the narrow exception. Only titles that say nothing reach
    the score, and only a posting whose full text uses none of the trade's
    vocabulary is dropped there; a truncated
    description is a publisher's excerpt, not silence, so it is kept.

    Between the two sits `needs_evidence`: a title trusted in neither
    direction. Supplied prose must justify it, while absent prose is kept
    because missing publisher data is not a negative signal.
    """
    title = row.get('title') or ''
    if employer_excluded(row, rules):
        return 'excluded_employer'
    if publisher_excluded(row.get('url'), row.get('raw'), rules):
        return 'excluded_publisher'
    if excluded(title, rules):
        return 'excluded'
    # Walking a posting's payload is the expensive part of judging it, and this
    # function asked for the same text up to four times -- three here and once
    # more inside `relevance`. Read once, pass it down. Identical output; the
    # only thing that changes is how often the same walk happens.
    #
    # `description` and `score` let the caller pass what it has already worked
    # out for the same row. `take` scores every posting before asking this
    # whether to keep it, and the score this function needs is the same number
    # from the same text.
    prose = description

    def description():
        nonlocal prose
        if prose is None:
            prose = description_text(row)
        return prose

    reason, _ = eligibility_rejection(row, rules)
    if reason:
        return reason
    reason = software_jd_rejection(row, rules)
    if reason:
        return reason
    if SOFTWARE_TITLE.search(title) and not title_blocked(title, rules):
        return ''
    # Before the keeps, not after: the point of an evidence title is that its
    # name is not trusted, and a title that also happens to match a keep would
    # otherwise skip the check it exists for. A posting that really is the trade
    # says so in its description and passes here anyway.
    if needs_evidence(title, rules):
        if not description():
            return ''
        confidence = score if score is not None else relevance(row, rules, description())[0]
        return '' if confidence >= rules.get('min_confidence', 25) else 'no_evidence'
    if any(re.search(p, title, re.I) for p in rules.get('keep_title_patterns', [])):
        return ''
    if title_blocked(title, rules) and not analog_chip_evidence(title, description()):
        return 'title_mismatch'
    confidence = score if score is not None else relevance(row, rules, description())[0]
    if confidence >= rules.get('min_confidence', 25):
        return ''
    # A truncated description is not silence; it is a publisher's excerpt.
    if len(description()) < rules.get('min_description_chars', 1500):
        return ''
    return 'off_domain'


# Mechanical hard passes, including explicit required work experience.
# Missing descriptions and domain-vocabulary judgements remain separate.
HARD_REJECTIONS = frozenset({'excluded', 'excluded_employer', 'excluded_publisher',
                             'required_experience_over_2_years',
                             'us_person_required', 'phd_only'})


# Early career is what this search is for, so it is asked first -- all three
# of its tiers before the general roles in A, not after them.
#
# "Second" is not a priority when the tier ahead asks for more than the day
# holds. Under the previous plan A was fifteen queries twelve pages deep, so it
# asked for 180 of a 320-credit day before the internships were reached at all,
# and any day opening with less than that in hand reached none of them. That
# was every day: across the two passes that plan ran, 144 page credits were
# spent, all 144 of them inside tier A, and the eleven internship queries had
# never once been sent.
TIER_ORDER = ('intern', 'new_grad', 'early_career', 'A', 'company')


def search_space(settings):
    """A fingerprint of what a query is being asked, beyond its own words.

    A resumable cursor says which page of a search to ask for next, which only
    means anything while the search is the same one. The window, the country
    and the employment types all decide the result set, so a cursor kept under
    the query alone would be handed to a later run that had changed one of them
    and would point at a page of a search that no longer exists. Including them
    makes such a cursor simply not match, and a sweep starts again at page one
    -- reading twice, which costs credits, rather than skipping, which loses
    postings. `Query.key` cannot carry this: it is also the stored source id.
    """
    shape = '|'.join((settings.get('country', ''), settings.get('date_posted', ''),
                      ','.join(sorted(settings.get('employment_types', ())))))
    # Excluding publishers changes the result set, so a cursor from before the
    # change points at a page of another search. Only added to the shape when
    # set, so a plan without it keeps its cursors.
    if settings.get('exclude_job_publishers'):
        shape += '|' + ','.join(sorted(name.casefold() for name in settings['exclude_job_publishers']))
    # Numeric-page checkpoints (including false exhausted flags) are obsolete.
    return hashlib.sha256(('cursor-v2|' + shape).encode()).hexdigest()[:8]


def tier_rank(tier):
    return TIER_ORDER.index(tier) if tier in TIER_ORDER else len(TIER_ORDER)


def filter_fingerprint(rules):
    """A short stable name for the filter configuration that made a decision.

    Not a mechanism for re-judging anything, because none is needed: every row
    a provider returns is scored and decided again from scratch, so a changed
    filter takes effect on the next pass that sees the job, and the record is
    overwritten with the new decision.

    What it marks is the one case that does not self-correct -- a job rejected
    once and never returned again keeps whichever decision was current when it
    was last seen. That is only ever observable in hindsight, and it cannot be
    repaired by rescoring, because the record deliberately holds no description
    to rescore. This says which filter to blame, and nothing more.
    """
    import json
    return hashlib.sha256(
        json.dumps(rules, sort_keys=True, default=str).encode()).hexdigest()[:12]


def collect(queries, client, settings, companies, persist, backfill=False,
            checkpoint=None, deadline=None, record_seen=None):
    """Page through each query adaptively, breadth first within a tier.

    Actual depth is discovered up to each configured cap, so the budget is
    spent in priority order: every internship query takes a page, then
    a second, until that tier is exhausted, before New Grad begins. Running
    a query to its own end before starting the next one would instead starve
    the tail of the plan -- the same queries, every day, would never be reached.
    """
    from .collector import employer_matches
    stats = {'jsearch_queries_planned': len(queries), 'jsearch_queries_completed': 0,
             'jsearch_pages_cap': sum(q.pages for q in queries),
             'jsearch_pages_used': 0, 'jsearch_jobs_raw': 0, 'jsearch_jobs_unique': 0,
             'jsearch_failures': 0, 'jsearch_jobs_rejected': 0,
             'jsearch_jobs_malformed': 0, 'jsearch_confidence': [],
             # One total cannot say whether a pass is working. A title the rules
             # refuse outright and a posting whose description simply did not
             # argue its case are different events, and only the second moves
             # when the term lists are edited.
             'jsearch_rejected_hard': 0, 'jsearch_rejected_other': 0,
             'jsearch_rejections': {},
             'jsearch_queries': []}
    unique = set()
    all_rows = []
    stop = False
    # Why the rotation ended, for the queries it never reached. Three unrelated
    # things end a run -- the clock, the budget, the provider -- and reporting
    # all three as the provider sends whoever reads the report looking for an
    # outage that never happened.
    stop_reason = None
    rules = settings.get('filter', {})
    filter_version = filter_fingerprint(rules)

    space = search_space(settings)
    # B63: the billing period this sweep's page numbers belong to, captured
    # once. `resume_page` and `advance` each used to ask for the period at the
    # moment they ran, so a page requested at 23:59:59 on a cycle's last day
    # and answered two seconds later wrote its progress into the new cycle --
    # and marked the new cycle's sweep finished before it had asked anything.
    sweep_period = client.guard.period()[0] if backfill else None
    state = {}
    for query in queries:
        # A backfill is one sweep spread over the cycle's last days, so it picks
        # up where the previous day stopped instead of re-buying its own pages.
        cursor = query.key + ':' + space
        start, finished = (client.guard.resume_page(cursor, period=sweep_period)
                           if backfill else (1, False))
        if backfill and start > 1 and not finished:
            token = client.guard.resume_token(cursor, period=sweep_period)
            if token:
                client.page_cursors[(query.key, start)] = token
            else:
                # Old numeric checkpoints cannot locate a search-v2 page.
                # Restart safely rather than silently asking page one as N.
                start = 1
        state[query.key] = {
            'query': query, 'cursor': cursor, 'rows': [], 'seen': [], 'page': start,
            'previous': None, 'done': finished,
            'detail': {'source_id': query.key, 'query': query.query, 'tier': query.tier,
                       'date_posted': settings['date_posted'], 'country': settings['country'],
                       'employment_types': settings['employment_types'],
                       'pages_cap': query.pages, 'pages_used': 0, 'jobs_raw': 0,
                       'resumed_from': start,
                       'jobs_accepted': 0, 'jobs_unique': 0, 'rejected': 0,
                       'malformed': 0, 'status': 'skipped', 'reason': ''}}

    def take(query, items):
        """Normalize, filter and keep one page's worth of a query's results."""
        entry = state[query.key]
        detail, rows = entry['detail'], entry['rows']
        detail['jobs_raw'] += len(items)
        stats['jsearch_jobs_raw'] += len(items)
        for item in items:
            try:
                row = normalize_job(item, query, companies, rules)
            except (ValueError, TypeError, KeyError):
                detail['malformed'] += 1
                continue
            # One walk of the payload for the whole judgement. Scoring,
            # the keep/reject rules and the experience gate all read the same
            # prose, and each used to extract it again from the raw record.
            prose = description_text(row)
            confidence, matched = relevance(row, rules, prose)
            if isinstance(row.get('raw'), dict):
                row['raw']['relevance'] = {
                    'confidence': confidence,
                    'matched_terms': sorted(set(matched)),
                }
            reason = rejection_reason(row, rules, description=prose, score=confidence)
            if not reason and query.aliases and not employer_matches(row['company_name'], query.aliases):
                # Only where the posting had nothing against it already. An
                # employer mismatch says this query asked the wrong question;
                # it is not a finding about the job, and the seen record keeps
                # the last decision written. Overwriting a hard rejection with
                # it made a posting refused on its own terms look merely
                # off-query, and the review queue stopped hiding it.
                reason = 'employer_mismatch'
            # Recorded before the decision, not after it. A rejected posting used
            # to leave nothing but a counter, so the same job was fetched,
            # normalized, scored and rejected again on every pass and nothing
            # could say whether it had been seen before. This keeps only what
            # dedup needs -- no description, no raw payload.
            entry['seen'].append({
                'provider_key': 'jsearch',
                'source_job_id': row['source_job_id'] or row['url'],
                'url': row['url'], 'title': row.get('title') or '',
                'employer': row.get('company_name') or '',
                'decision': reason, 'confidence': confidence,
                # `rejection_reason` has already run the gate and left its
                # working on the row; running it again is a second structured
                # walk of the same payload for the same answer.
                'experience_filter': (isinstance(row.get('raw'), dict)
                                      and row['raw'].get('experience_filter')
                                      or experience_debug(row)),
                'filter_version': filter_version})
            if reason:
                detail['rejected'] += 1
                stats['jsearch_rejections'][reason] = stats['jsearch_rejections'].get(reason, 0) + 1
                key = ('jsearch_rejected_hard'
                       if reason in HARD_REJECTIONS else 'jsearch_rejected_other')
                stats[key] += 1
                continue
            # Unique by id and by address: JSearch gives one listing a new
            # job_id nearly every time, so an id alone counted it again, and a
            # moved address with the same id is still one job (2026-09-27).
            identities = {('url', row['url'])} | ({('id', row['source_job_id'])} if row['source_job_id'] else set())
            if not identities & unique:
                detail['jobs_unique'] += 1
            unique.update(identities)
            stats['jsearch_confidence'].append(confidence)
            rows.append(row)

    original_order = {query.key: index for index, query in enumerate(queries)}
    for tier in sorted({q.tier for q in queries}, key=tier_rank):
        active = [q for q in queries if q.tier == tier and not state[q.key]['done']]
        if backfill:
            # A small sweep may end before every query gets one page. Resume the
            # shallowest cursors first on the next run so the same leading
            # queries cannot consume every deliberately bounded invocation.
            active.sort(key=lambda q: (state[q.key]['page'], original_order[q.key]))
        while active and not stop:
            for query in list(active):
                entry = state[query.key]
                detail = entry['detail']
                if deadline is not None and time.monotonic() >= deadline:
                    detail['status'] = 'query_limited'
                    detail['reason'] = 'JSearch runtime limit reached before this page'
                    stop = True
                    stop_reason = 'the run reached its time limit'
                    break
                if backfill and client.guard.period()[0] != sweep_period:
                    # The page numbers in hand belong to the sweep that just
                    # ended. The new cycle's sweep starts at page one, on its
                    # own run, not from where the old one had got to.
                    detail['status'] = 'query_limited'
                    detail['reason'] = 'The billing period changed during the sweep'
                    stop = True
                    stop_reason = 'the billing period changed'
                    break
                # The guard has to bind before the credit is spent, not after:
                # a resumed sweep can start already past its own cap.
                if entry['page'] > query.pages:
                    stats['jsearch_queries_completed'] += 1
                    detail['status'] = 'partial' if detail['malformed'] else 'query_limited'
                    detail['reason'] = f'Runaway guard stopped paging at {query.pages} pages'
                    entry['done'] = True
                    active.remove(query)
                    continue
                before = client.guard.credits
                failure = None
                try:
                    items, exhausted = client.fetch_page(query, entry['page'])
                except SearchFailure as exc:
                    failure = exc
                spent = client.guard.credits - before
                detail['pages_used'] += spent
                stats['jsearch_pages_used'] += spent
                if failure is not None and failure.transient and not entry.get('retried'):
                    # Asked again once, after the rest of the round, from the
                    # same page: the query is not over because the server was.
                    stats['jsearch_failures'] += 1
                    entry['retried'] = True
                    detail['reason'] = f'{failure}; retried once'
                    continue
                if failure is not None:
                    if not failure.budget:
                        stats['jsearch_failures'] += 1
                    detail['status'] = 'query_limited' if failure.budget else 'failed'
                    detail['reason'] = str(failure)
                    stop = failure.stop
                    if stop:
                        stop_reason = ('the page-credit budget was exhausted' if failure.budget
                                       else f'the provider stopped the account ({failure})')
                    entry['done'] = True
                    active.remove(query)
                    if stop:
                        break
                    continue
                asked = entry['page']
                cursor_looping = query.key in client.cursor_loops
                identities = page_identity(items)
                looping = identities is not None and identities == entry['previous']
                entry['previous'] = identities
                malformed_before = detail['malformed']
                if not looping:
                    before_rows = len(entry['rows'])
                    before_seen = len(entry['seen'])
                    take(query, items)
                    new_seen = entry['seen'][before_seen:]
                    # Paid results become durable before a resumable cursor can
                    # move past them. A crash after this callback may repeat a
                    # page, but it cannot skip jobs that existed only in memory.
                    if record_seen is not None and new_seen:
                        record_seen(new_seen)
                    if checkpoint is not None:
                        checkpoint(query, entry['rows'][before_rows:], detail)
                entry['page'] += 1
                if backfill:
                    # An empty page is not proof the results ran out: a provider
                    # hiccup returns one too, and settling the cursor on it would
                    # skip the rest of this query for the whole cycle. So it ends
                    # the query for this run only, and the next day asks the same
                    # page again -- one repeated page costs a credit, a silently
                    # skipped query costs everything after it. A page that came
                    # without a next cursor and with rows, or an empty first
                    # page without a next cursor, are genuine ends.
                    # A last page carrying a record that could not be read is
                    # held open, like the empty page above: settling it would
                    # retire the query for the cycle with that posting lost,
                    # and nothing on the next day could ask again. It costs the
                    # same as that rule does -- one repeated page a day -- and
                    # only on the last page: holding a middle page would stall
                    # the query there for as long as the record stays broken.
                    held = (not looping and exhausted
                            and detail['malformed'] > malformed_before)
                    settled = (not looping and not cursor_looping and not held
                               and (exhausted and (bool(items) or asked == 1)))
                    # An unsettled empty page is the one page that must not be
                    # stepped over: nothing was persisted from it, so the cursor
                    # stays where it is and the next day asks for it again.
                    resume = (entry['page'] if not looping and not cursor_looping and not held and (items or settled)
                              else asked)
                    client.guard.advance(entry['cursor'], resume, exhausted=settled,
                                         period=sweep_period,
                                         token=client.page_cursors.get((query.key, resume)))
                if exhausted or looping:
                    if detail['status'] != 'failed':
                        stats['jsearch_queries_completed'] += 1
                        detail['status'] = 'partial' if detail['malformed'] else 'query_limited'
                        if looping or cursor_looping:
                            detail['reason'] = 'Provider repeated a page; stopped advancing'
                    entry['done'] = True
                    active.remove(query)

    for entry in state.values():
        query, detail, rows = entry['query'], entry['detail'], entry['rows']
        if detail['pages_used'] and detail['status'] == 'skipped':
            # It paged and kept rows; the budget ran out mid-rotation before it
            # could reach its own end. 'skipped' is for a query never reached,
            # and it is not a status a run may finish on.
            detail['status'] = 'partial' if detail['malformed'] else 'query_limited'
            if not detail['reason']:
                detail['reason'] = 'Budget reached before this query finished paging'
        if not entry['done'] and not detail['reason']:
            # Never reached. Say which of the three ended the rotation, because
            # "the account stopped" sent a reader hunting for a provider outage
            # when the real answer was that the budget had simply run out.
            detail['reason'] = (f'Not reached: {stop_reason}' if stop_reason
                                else 'Not reached before the run ended')
        detail['jobs_accepted'] = len(rows)
        stats['jsearch_jobs_rejected'] += detail['rejected']
        stats['jsearch_jobs_malformed'] += detail['malformed']
        persist(query, rows, detail)
        stats['jsearch_queries'].append(detail)
        all_rows.extend(rows)
    stats['jsearch_jobs_unique'] = sum(detail['jobs_unique'] for detail in (e['detail'] for e in state.values()))
    return all_rows, stats
