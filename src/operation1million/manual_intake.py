"""User-directed single-link intake, durable outside the derived job index."""
import codecs
from contextlib import contextmanager
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import re
import socket
import time
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit, urljoin, parse_qsl, urlencode

from bs4 import BeautifulSoup
import requests

from . import applications, collection_policy, collector, jsearch, ranking
from .job_text import readable_text


def path_for(ledger):
    return Path(ledger).with_name('manual_jobs.ndjson')


def normalized_url(value):
    parsed = urlsplit(value.strip())
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Paste a public HTTP or HTTPS job link')
    query = urlencode([(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                       if not key.lower().startswith('utm_') and key.lower() not in {'trk', 'trackingid', 'fbclid', 'gclid'}])
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip('/') or '/', query, ''))


def public_url(value):
    value = normalized_url(value)
    host = urlsplit(value).hostname
    addresses = socket.getaddrinfo(host, None)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('Only public job sites can be collected')
    return value


@contextmanager
def collection_slot(ledger):
    """Use the production collector lock when present; never run beside a pass."""
    production = Path('/opt/operation1million/collection.lock')
    if production.exists():
        import fcntl
        with production.open('rb') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Collection is already running. Add this link after the pass finishes.')
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
    else:
        with applications.locked(Path(ledger).with_name('manual_collection.lock')):
            yield


# Boards that serve many employers from one host: the employer is the first
# path segment of a posting's page and of the API the collector reads, so the
# two name the same tenant even though their hosts differ (#301, #308).
TENANT_PAGES = {
    'greenhouse': (re.compile(r'^(?:job-)?boards(?:\.eu)?\.greenhouse\.io$'), re.compile(r'^/([^/]+)/jobs/(\d+)')),
    'smartrecruiters': (re.compile(r'^(?:jobs|careers)\.smartrecruiters\.com$'), re.compile(r'^/([^/]+)/(\d+)')),
    'lever': (re.compile(r'^jobs(?:\.eu)?\.lever\.co$'), re.compile(r'^/([^/]+)/([0-9a-f-]{36})')),
    'ashby': (re.compile(r'^jobs\.ashbyhq\.com$'), re.compile(r'^/([^/]+)/([0-9a-f-]{36})')),
}
TENANT_APIS = {
    'greenhouse': re.compile(r'^/v1/boards/([^/]+)'),
    'smartrecruiters': re.compile(r'^/v1/companies/([^/]+)'),
    'lever': re.compile(r'^/v0/postings/([^/]+)'),
    'ashby': re.compile(r'^/posting-api/job-board/([^/]+)'),
}
# Where a tenant board's page carries no structured data -- Greenhouse and
# SmartRecruiters draw it in the browser -- the posting is read from the
# public API the collector already reads (measured 2026-10-02).
POSTING_APIS = {
    'greenhouse': 'https://boards-api.greenhouse.io/v1/boards/{0}/jobs/{1}',
    'smartrecruiters': 'https://api.smartrecruiters.com/v1/companies/{0}/postings/{1}',
}
# Job boards that republish employers' postings, by the publisher name paid
# search gives each; measured on every paid listing in the index, 2026-10-02.
# LinkedIn and Handshake are named, and export.third_party_site exempts them.
JOB_BOARDS = {
    'linkedin.com': 'LinkedIn', 'joinhandshake.com': 'Handshake', 'jobleads.com': 'JobLeads',
    'learn4good.com': 'Learn4Good', 'ziprecruiter.com': 'ZipRecruiter', 'jobmesh.io': 'JobMESH',
    'bebee.com': 'BeBee', 'indeed.com': 'Indeed', 'jobilize.com': 'Jobilize',
    'jobrapido.com': 'Jobrapido', 'trabajo.org': 'Trabajo.org', 'jooble.org': 'Jooble',
    'simplify.jobs': 'Simplify', 'snagajob.com': 'Snagajob', 'womenforhire.com': 'Women For Hire',
    'recruit.net': 'Recruit.net', 'digitalhire.com': 'Digitalhire', 'theladders.com': 'Ladders',
    'builtin.com': 'Built In', 'clearancejobs.com': 'Clearance Jobs', 'tealhq.com': 'Teal',
    'monster.com': 'Monster', 'talent.com': 'Talent.com', 'careerbuilder.com': 'CareerBuilder',
    'glassdoor.com': 'Glassdoor', 'jobserve.com': 'JobServe', 'whatjobs.com': 'WhatJobs',
    'dice.com': 'Dice', 'simplyhired.com': 'SimplyHired', 'wellfound.com': 'Wellfound',
}


def tenant_posting(url):
    """(provider, tenant, requisition) for a posting on a tenant board, else None."""
    parts = urlsplit(url)
    for provider, (host, path) in TENANT_PAGES.items():
        found = path.match(parts.path) if host.match(parts.hostname or '') else None
        if found:
            return provider, found.group(1), found.group(2)
    return None


def _tenant(source):
    pattern = TENANT_APIS.get(source.provider_key)
    found = pattern.match(urlsplit(source.access_url).path) if pattern else None
    return found.group(1).casefold() if found else None


def catalog_source(url, db):
    """The source the collector reads this posting's board through, or None.

    The host alone answers for a board of one employer. On a tenant board it
    named whichever company the catalog listed first under the API's host, so
    the tenant has to agree as well.
    """
    if db is None or not Path(db).is_file():
        return None
    posting = tenant_posting(url)
    host = urlsplit(url).hostname
    for source in collector.load_sources(Path(db)):
        if posting:
            if source.provider_key == posting[0] and _tenant(source) == posting[1].casefold():
                return source
        elif source.provider_key not in TENANT_APIS and urlsplit(source.access_url).hostname == host:
            return source
    return None


def _encoding(content_type, body):
    """The charset a body is in: its header's, else its own <meta>, else UTF-8 (#306).

    `requests` reads text/* with no charset as ISO-8859-1, the collector's #197.
    """
    found = re.search(r'charset\s*=\s*["\']?([\w-]+)', content_type or '', re.I) \
        or collector.META_CHARSET.search(body[:4096])
    encoding = found.group(1) if found else 'utf-8'
    encoding = encoding.decode('ascii') if isinstance(encoding, bytes) else encoding
    try:
        codecs.lookup(encoding)
    except LookupError:
        encoding = 'utf-8'
    return encoding


def _read(session, url, ledger, db, source=None):
    """One page: checked redirects, source pacing/cooldowns, no challenge bypass."""
    url = public_url(url)
    for _ in range(5):
        known = source or catalog_source(url, db)
        policy = collection_policy.SourcePolicy(SimpleNamespace(
            company_key=known.company_key if known else urlsplit(url).hostname,
            provider_key=known.provider_key if known else 'manual', access_url=url),
            3, path=Path(ledger).with_name('source_access.sqlite'))
        if collection_policy.STATE.is_file():
            collection_policy.merge_source_pauses(policy.path, collection_policy.STATE)
        policy.check()
        time.sleep(policy.interval)
        with session.get(url, headers={'User-Agent': collection_policy.USER_AGENT}, timeout=25,
                         allow_redirects=False, stream=True) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                url = public_url(urljoin(url, response.headers.get('Location', '')))
                continue
            if response.status_code == 429:
                policy.pause('HTTP 429', max(900, collection_policy.retry_after_seconds(response.headers.get('Retry-After')) or 0))
            if response.status_code in (401, 403, 405):
                policy.pause(f'HTTP {response.status_code}', 86400)
            if response.status_code >= 500:
                policy.pause(f'HTTP {response.status_code}', max(900, collection_policy.retry_after_seconds(response.headers.get('Retry-After')) or 0))
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > 2_000_000:
                    raise ValueError('Posting page is too large; supply the job details manually')
            body = bytes(content)
            text = body.decode(_encoding(response.headers.get('Content-Type'), body), errors='replace')
            if collection_policy.html_challenge(text):
                policy.pause('Posting requires an access challenge', 86400)
            return url, text
    raise ValueError('Too many redirects; paste the final public job link')


def read_public_page(url, ledger, db=None):
    """Bounded fetch of one page under the collector's lock."""
    with collection_slot(ledger), requests.Session() as session:
        return _read(session, url, ledger, db)


def _greenhouse(data):
    return {'title': data.get('title'), 'company': data.get('company_name'),
            'location': (data.get('location') or {}).get('name'), 'description': data.get('content'),
            'identifier': data.get('id'), 'datePosted': data.get('first_published'), 'raw': data}


def _smartrecruiters(data):
    sections = ((data.get('jobAd') or {}).get('sections') or {}).values()
    return {'title': data.get('name'), 'company': (data.get('company') or {}).get('name'),
            'location': data.get('location'), 'identifier': data.get('id'),
            'description': '\n'.join(str(section.get('text') or '') for section in sections
                                     if isinstance(section, dict)),
            'datePosted': data.get('releasedDate'), 'raw': data}


API_RECORDS = {'greenhouse': _greenhouse, 'smartrecruiters': _smartrecruiters}


def read_posting(url, ledger, db, supplied, official=False):
    """(final link, metadata) for a pasted link, read the way its board publishes it."""
    url = normalized_url(url)
    source = catalog_source(url, db)
    posting = tenant_posting(url)
    with collection_slot(ledger), requests.Session() as session:
        if posting and posting[0] in POSTING_APIS:
            api = POSTING_APIS[posting[0]].format(*posting[1:])
            _, text = _read(session, api, ledger, db, source or SimpleNamespace(
                company_key=f'{posting[0]}:{posting[1].casefold()}', provider_key=posting[0]))
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError('The board sent no posting for this link')
            return url, posting_metadata('', supplied, url, source, official, API_RECORDS[posting[0]](data))
        url, text = _read(session, url, ledger, db)
    # A short or tracking link names its board only once it has redirected.
    return url, posting_metadata(text, supplied, url, catalog_source(url, db), official)


def _microdata(soup):
    """A schema.org JobPosting marked up with itemprop attributes (#303).

    As SuccessFactors sends it (Teradyne, 2026-10-02): the place in
    streetAddress and the day as Java prints one, "Tue Sep 22 00:00:00 UTC 2026".
    """
    scope = soup.select_one('[itemtype*="schema.org/JobPosting"]')
    if scope is None:
        return {}

    def value(element):
        if element.has_attr('itemscope'):
            return {child['itemprop']: value(child) for child in element.select('[itemprop]')}
        return element.get('content') or element.get_text(' ', strip=True)
    record = {}
    for prop in ('title', 'hiringOrganization', 'jobLocation', 'datePosted', 'identifier'):
        element = scope.select_one(f'[itemprop="{prop}"]')
        if element is not None:
            record[prop] = value(element)
    place = record.get('jobLocation')
    if isinstance(place, dict):
        record['jobLocation'] = collector.location_text(place) or place.get('streetAddress') or ''
    try:
        record['datePosted'] = datetime.strptime(record.get('datePosted', ''), '%a %b %d %H:%M:%S UTC %Y').date().isoformat()
    except (TypeError, ValueError):
        pass
    element = scope.select_one('[itemprop="description"]')
    if element is not None:
        record['description'] = element.decode_contents()
    return record if record.get('title') else {}


def page_record(text):
    """The posting a page publishes: JSON-LD, else microdata.

    Not the page's heading: Google's posting pages head theirs "job details",
    and a wrong title is worse than asking for the right one.
    """
    soup = BeautifulSoup(text, 'html.parser')
    # One posting published twice is one posting.
    postings = {json.dumps(item, sort_keys=True): item for item in collector.jsonld(soup)}
    if len(postings) > 1:
        raise ValueError('This page contains multiple jobs; paste the individual job link')
    if postings:
        return next(iter(postings.values()))
    return _microdata(soup)


def _name(value):
    return value.get('name') if isinstance(value, dict) else value


def board_requisitions(url, source):
    """The ids the index could hold this posting under on its board (#308)."""
    if source is None:
        return []
    segment = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]
    if source.provider_key == 'workday':
        # As the collector reads externalPath: the part after the last '_'.
        return [segment.rsplit('_', 1)[-1]] if '_' in segment else []
    return [collector.html_job_id(url, source.provider_key)] if segment else []


def posting_metadata(text, supplied, url='', source=None, official=False, record=None):
    """What the queue needs: the user's details first, then the posting's own."""
    record = page_record(text) if record is None else record
    identifier = record.get('identifier')
    identifier = identifier.get('value') if isinstance(identifier, dict) else identifier
    title = supplied.get('title') or record.get('title')
    title = collector.clean(title) if isinstance(title, str) else ''
    # The catalog's name, where the board is one the index reads: the page
    # names the legal entity ("Silicon Labs Intl"), the queue the company.
    company = supplied.get('company') or (source.company_name if source else None) \
        or _name(record.get('hiringOrganization') or record.get('company'))
    company = company.strip() if isinstance(company, str) else ''
    if not title or not company:
        raise ValueError('Cannot identify this posting automatically. Fill Company and Title, then add it again.')
    posting = tenant_posting(url) if url else None
    requisitions = [str(value).strip() for value in (
        supplied.get('source_job_id'), posting and posting[2], *board_requisitions(url, source), identifier)
        if value is not None and str(value).strip()]
    metadata = {'title': title, 'company': company,
                'company_key': source.company_key if source else company.casefold(),
                'description': readable_text(supplied.get('description') or record.get('description') or ''),
                'source_job_id': requisitions[0] if requisitions else '',
                'requisitions': list(dict.fromkeys(requisitions)),
                'location': supplied.get('location') or collector.location_text(
                    record.get('jobLocation') or record.get('location')),
                'posted_at': record.get('datePosted'), 'raw': record}
    host = (urlsplit(url).hostname or '').lower() if url else ''
    publisher = next((name for domain, name in JOB_BOARDS.items()
                      if host == domain or host.endswith('.' + domain)), None)
    if publisher and not official:
        metadata['publisher'] = publisher
    return metadata


def refusal(job, rules=None):
    """Why a pasted posting is one the user cannot take, else None (#311).

    A pasted job skips discovery's filters: title, seniority, experience and
    PhD are the user's call for a posting they chose. Citizenship is not --
    the user cannot meet it -- and an RTX posting requiring it reached Review
    this way. The excluded employers are the defence employers whose postings
    require it; a third-party copy often cuts the sentence that says so.
    """
    rules = rules or jsearch.load_plan()[0]['filter']
    description = job.get('manual_description', job.get('description')) or ''
    raw = job.get('raw') if isinstance(job.get('raw'), dict) else {}
    row = {'title': job.get('title') or '', 'company': job.get('company') or '',
           'raw': dict(raw, description=description)}
    if jsearch.employer_excluded(row, rules):
        return f"{row['company']} is an excluded employer (defence; U.S. citizenship or clearance)"
    text = row['title'] + '\n' + jsearch.description_text(row, structured=True)
    if jsearch.us_person_required(text, rules):
        return 'The posting requires U.S. citizenship or U.S. person status'
    return None


def same_url(left, right):
    try:
        return normalized_url(left) == normalized_url(right)
    except ValueError:
        return False


def match_group(state, url, metadata=None):
    """Match explicit links or company-scoped requisition IDs, never title alone."""
    matches = []
    requisitions = (set(metadata.get('requisitions') or [metadata.get('source_job_id')]) - {'', None}
                    if metadata else set())
    for status, group in ((name, item) for name in ('pending', 'backlog', 'applied', 'skipped') for item in state[name]):
        for job in group['jobs']:
            if any(value and same_url(value, url)
                   for value in (job.get('url'), job.get('official_link'))):
                matches.append((status, group)); break
            if metadata and str(job.get('source_job_id') or '') in requisitions and (
                    applications.employer_name(group.get('company')) == applications.employer_name(metadata['company'])
                    or job.get('company_key') and job['company_key'] == metadata.get('company_key')):
                matches.append((status, group)); break
    unique = {group['id']: (status, group) for status, group in matches}
    return next(iter(unique.values())) if len(unique) == 1 else (None, None)


def create_group(url, metadata):
    stamp = datetime.now(timezone.utc).isoformat()
    metadata = {key: value for key, value in metadata.items() if key != 'requisitions'}
    job = dict(metadata, url=url, company_key=metadata.get('company_key') or metadata['company'].casefold(),
               provider_key='manual',
               first_seen=stamp, manual_description=metadata['description'], manual_import=True)
    score, hits = jsearch.relevance(metadata, jsearch.load_plan()[0]['filter'], description=metadata['description'])
    group = {'id': applications.decision_key(job), 'company': metadata['company'], 'title': metadata['title'],
             'confidence': score, 'bucket': ranking.bucket(metadata['title']), 'jobs': [job],
             'manual_import': True, 'early_career': ranking.early_career(metadata['title']),
             'less_related': False, 'matched_terms': hits}
    return group


def save_manual(ledger, group, replaced_ids=(), replaced_groups=()):
    event = {'at': datetime.now(timezone.utc).isoformat(), 'group': group,
             'replaced_ids': list(replaced_ids), 'replaced_groups': list(replaced_groups), 'source': 'user-pasted-link'}
    path = path_for(ledger)
    with applications.locked(path):
        applications._append_line(path, event)


def augment_queue(state, ledger):
    """Explicit imports survive filter changes, DB rebuilds and normal decisions."""
    from .employers import label_queue
    latest = {}
    path = path_for(ledger)
    if not path.exists():
        return label_queue(state)
    with applications.locked(path):
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                event = json.loads(line)
                latest[event['group']['id']] = event
    with applications.locked(ledger):
        decisions = applications.read_events(ledger)
    superseded = {ident for event in latest.values() for ident in event.get('replaced_ids', [])}
    rules = jsearch.load_plan()[0]['filter']
    for ident, event in latest.items():
        if ident in superseded:
            continue
        group = dict(event['group'])
        group['confidence'], group['matched_terms'] = jsearch.relevance(
            group['jobs'][0], rules, description=group['jobs'][0].get('manual_description', ''))
        status = 'pending'
        for decision in decisions:
            if decision.get('group_id') == ident:
                status = decision['status']
                group = dict(group, at=decision['at'], reason=decision.get('reason', ''))
        removed = {ident, *event.get('replaced_ids', [])}
        for name in ('pending', 'backlog', 'applied', 'skipped'):
            state[name] = [item for item in state[name] if item['id'] not in removed]
        # Pasted before #311, or refused under rules added since: not offered.
        # A decision already made keeps its tab.
        if status == 'pending' and refusal(group['jobs'][0], rules):
            continue
        from .employers import label_group
        state[status].append(label_group(group))
    state['pending'].sort(key=ranking.rank)
    # Newest first, as applications.queue orders them (#309).
    for name in ('applied', 'skipped'):
        state[name].sort(key=lambda group: group.get('at') or '', reverse=True)
    applications.attach_links(state, applications.read_links(applications.links_path(ledger)))
    applications.attach_outcomes(state, applications.read_outcomes(applications.outcomes_path(ledger)))
    return label_queue(state)
