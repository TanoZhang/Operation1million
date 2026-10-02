"""User-directed single-link intake, durable outside the derived job index."""
from contextlib import contextmanager
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import socket
import time
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit, urljoin, parse_qsl, urlencode

from bs4 import BeautifulSoup
import requests

from . import applications, collection_policy, jsearch, ranking


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
    production = Path('/opt/jobdisco/collection.lock')
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


def read_public_page(url, ledger, db=None):
    """Bounded fetch, checked redirects, source pacing/cooldowns, no challenge bypass."""
    url = public_url(url)
    with collection_slot(ledger), requests.Session() as session:
        for _ in range(5):
            host = urlsplit(url).hostname
            source = SimpleNamespace(company_key=host, provider_key='manual', access_url=url)
            if db is not None:
                from .collector import load_sources
                known = [item for item in load_sources(Path(db)) if urlsplit(item.access_url).hostname == host]
                if known:
                    source = SimpleNamespace(company_key=known[0].company_key, provider_key=known[0].provider_key, access_url=url)
            policy = collection_policy.SourcePolicy(source, 3, path=Path(ledger).with_name('source_access.sqlite'))
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
                text = bytes(content).decode(response.encoding or 'utf-8', errors='replace')
                if collection_policy.html_challenge(text):
                    policy.pause('Posting requires an access challenge', 86400)
                return url, text
        raise ValueError('Too many redirects; paste the final public job link')


def posting_metadata(text, supplied):
    soup = BeautifulSoup(text, 'html.parser')
    def walk(value):
        if isinstance(value, list):
            for item in value:
                yield from walk(item)
        elif isinstance(value, dict):
            kind = value.get('@type')
            if kind == 'JobPosting' or isinstance(kind, list) and 'JobPosting' in kind:
                yield value
            else:
                for item in value.values():
                    yield from walk(item)
    postings = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            postings.extend(walk(json.loads(script.get_text())))
        except (ValueError, TypeError):
            continue
    if len(postings) > 1:
        raise ValueError('This page contains multiple jobs; paste the individual job link')
    record = postings[0] if postings else {}
    organization = record.get('hiringOrganization') or {}
    identifier = record.get('identifier') or {}
    location = record.get('jobLocation') or {}
    if isinstance(location, list):
        location = location[0] if location else {}
    address = (location.get('address') or {}) if isinstance(location, dict) else {}
    location_text = ', '.join(str(address.get(key)) for key in ('addressLocality', 'addressRegion', 'addressCountry') if address.get(key)) if isinstance(address, dict) else ''
    title = supplied.get('title') or record.get('title')
    company = supplied.get('company') or (organization.get('name') if isinstance(organization, dict) else organization)
    if not isinstance(title, str) or not title.strip() or not isinstance(company, str) or not company.strip():
        raise ValueError('Cannot identify this posting automatically. Fill Company and Title, then add it again.')
    description = supplied.get('description') or record.get('description') or ''
    return {'title': title.strip(), 'company': company.strip(),
            'description': BeautifulSoup(str(description), 'html.parser').get_text('\n', strip=True),
            'source_job_id': str(supplied.get('source_job_id') or (identifier.get('value') or '' if isinstance(identifier, dict) else identifier)),
            'location': supplied.get('location') or location_text,
            'posted_at': record.get('datePosted'), 'raw': record}


def same_url(left, right):
    try:
        return normalized_url(left) == normalized_url(right)
    except ValueError:
        return False


def match_group(state, url, metadata=None):
    """Match explicit links or company-scoped requisition IDs, never title alone."""
    matches = []
    for status, group in ((name, item) for name in ('pending', 'backlog', 'applied', 'skipped') for item in state[name]):
        for job in group['jobs']:
            if any(value and same_url(value, url)
                   for value in (job.get('url'), job.get('official_link'))):
                matches.append((status, group)); break
            if metadata and metadata.get('source_job_id') and str(job.get('source_job_id') or '') == metadata['source_job_id'] \
                and str(group.get('company') or '').casefold() == metadata['company'].casefold():
                matches.append((status, group)); break
    unique = {group['id']: (status, group) for status, group in matches}
    return next(iter(unique.values())) if len(unique) == 1 else (None, None)


def create_group(url, metadata):
    stamp = datetime.now(timezone.utc).isoformat()
    job = dict(metadata, url=url, company_key=metadata['company'].casefold(), provider_key='manual',
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
    latest = {}
    path = path_for(ledger)
    if not path.exists():
        return state
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
        state[status].append(group)
    state['pending'].sort(key=ranking.rank)
    applications.attach_links(state, applications.read_links(applications.links_path(ledger)))
    return state
