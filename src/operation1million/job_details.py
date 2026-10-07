"""Read public posting evidence omitted by board inventories."""
import json
import re
import sqlite3
from html import escape
from contextlib import closing
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import requests

from .collection_policy import SourcePaused
from .experience import ENTRY
from .job_text import readable_text

# Verified against captured public posting pages, not search-result snippets.
PAGE_PROVIDERS = {'talentbrew', 'phenom', 'avature', 'jobs2web'}
PROVIDERS = PAGE_PROVIDERS | {'workday', 'smartrecruiters', 'eightfold'}
REFRESH_AFTER = timedelta(days=7)


def same_url(left, right):
    """Ignore query tracking and trailing slash, retain host and posting path."""
    a, b = urlsplit(left), urlsplit(right)
    return (a.hostname, a.path.rstrip('/')) == (b.hostname, b.path.rstrip('/'))


def page_fields(text, row, response_url):
    from .manual_intake import page_record
    if not same_url(response_url, row['url']):
        raise ValueError('Detail redirected away from requested posting')
    data = page_record(text)
    if not readable_text(data.get('description')):
        raise ValueError('Posting page has no readable description')
    if data.get('url') and not same_url(data['url'], row['url']):
        raise ValueError('Detail payload identifies another posting')
    # Some boards omit url/identifier. Require the returned title as a second
    # check even when the HTTP endpoint and published URL match.
    title = lambda value: re.sub(r'\s+', ' ', readable_text(value)).strip().casefold()
    if title(data.get('title')) != title(row['title']):
        raise ValueError('Detail title does not match inventory')
    return {'description': data['description']}


def read(collector, row):
    if collector.source.provider_key == 'eightfold':
        from .validate_sources import request_for
        parts = urlsplit(request_for(collector.source)[0])
        domain = parse_qs(parts.query)['domain'][0]
        query = urlencode({'position_id': row['source_job_id'], 'domain': domain, 'hl': 'en'})
        endpoint = urlunsplit(parts._replace(path='/api/pcsx/position_details', query=query))
        with collector.fetch(endpoint) as response:
            return eightfold_fields(response.json(), row['source_job_id'])
    if collector.source.provider_key == 'smartrecruiters':
        from .validate_sources import request_for
        endpoint = request_for(collector.source)[0].split('?')[0].rstrip('/')
        with collector.fetch(endpoint + '/' + str(row['source_job_id'])) as response:
            return smartrecruiters_fields(response.json(), row['source_job_id'])
    if collector.source.provider_key == 'workday':
        from .validate_sources import workday_request
        path = row['raw'].get('externalPath', '')
        if not path.startswith('/job/') or '?' in path or '#' in path:
            raise ValueError('Workday inventory has no posting path')
        endpoint = workday_request(collector.source)[0].rsplit('/jobs', 1)[0] + path
        with collector.fetch(endpoint) as response:
            return workday_fields(response.json(), path)
    with collector.fetch(row['url']) as response:
        return page_fields(response.text, row, response.url)


def workday_fields(data, path):
    """Bind a captured CXS detail to its inventory externalPath."""
    posting = data.get('jobPostingInfo') or {}
    published_path = urlsplit(posting.get('externalUrl') or '').path
    if not path.startswith('/job/') or not published_path.endswith(path):
        raise ValueError('Workday detail does not match requested posting')
    description = posting.get('jobDescription')
    if not readable_text(description):
        raise ValueError('Workday detail has no readable description')
    return {'description': description}


def smartrecruiters_fields(data, identifier):
    if str(data.get('id')) != str(identifier):
        raise ValueError('SmartRecruiters detail does not match requested posting')
    sections = (data.get('jobAd') or {}).get('sections') or {}
    description = '\n'.join(
        '<h2>' + escape(section.get('title') or '') + '</h2>' + section['text']
        for section in sections.values() if readable_text(section.get('text')))
    if not readable_text(description):
        raise ValueError('SmartRecruiters detail has no readable description')
    return {'description': description}


def eightfold_fields(data, identifier):
    """Use the full HTML JD; JSON-LD can omit required/preferred headings."""
    posting = data.get('data') or {}
    if str(posting.get('id')) != str(identifier):
        raise ValueError('Eightfold detail does not match requested posting')
    description = posting.get('jobDescription')
    if not readable_text(description):
        raise ValueError('Eightfold detail has no readable description')
    return {'description': description}


def enrich(collector, db_path=None):
    return enrich_inventory(collector, db_path, reader=read,
                            provider=collector.source.provider_key,
                            metadata='detail_evidence', fields=('description',),
                            evidence='description', skip_full=True)


def candidate(row, rules):
    """Fetch detail for title-relevant leads, including chip-named software."""
    from . import jsearch, ranking
    # Select on title first; the newly read JD then faces the shared filters.
    lead = {'title': row['title'], 'raw': {}}
    if (ranking.bucket(row['title']) == 4
            and jsearch.relevance(lead, rules)[0] < rules.get('min_confidence', 25)):
        return False
    reason = jsearch.rejection_reason(lead, rules)
    return not reason or (reason == 'missing_software_jd'
                          and bool(jsearch.SOFTWARE_VLSI_EVIDENCE.search(row['title'])))


def enrich_inventory(collector, db_path, *, reader, provider, metadata, fields, evidence, skip_full):
    """Enrich relevant inventory with paced, cached public detail reads.

    Rows are never removed from inventory. Failed details remain unknown, not
    rejected or closed. Successful evidence uses fields retained by the durable log.
    The caller owns the existing collection lock and persistence transaction.
    """
    from . import jsearch
    from .job_text import display_description
    previous = {}
    if db_path is not None:
        with closing(sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            for url, raw in db.execute('SELECT url, raw FROM jobs WHERE provider_key=?', (provider,)):
                try:
                    decoded = json.loads(raw or '{}')
                except (TypeError, ValueError):
                    continue
                if isinstance(decoded, dict):
                    previous[url] = decoded
    rules = jsearch.load_plan()[0]['filter']
    now = datetime.now(timezone.utc)
    errors = []
    for row in sorted(collector.jobs, key=lambda r: not bool(ENTRY.search(r['title']))):
        if not candidate(row, rules):
            continue
        if skip_full and display_description(row['raw'])[1] == 'full':
            continue
        old = previous.get(row['url'], {})
        proof = old.get(metadata) or {}
        if not isinstance(proof, dict):
            proof = {}
        try:
            checked = datetime.fromisoformat(proof.get('checked_at', ''))
            fresh = timedelta(0) <= now - checked < REFRESH_AFTER
        except (ValueError, TypeError):
            fresh = False
        if (fresh and proof.get('status') == 'verified'
                and proof.get('title') == row['title']
                and proof.get('source_job_id') == str(row.get('source_job_id') or '')
                and proof.get('posted_at') == row.get('posted_at')
                and readable_text(old.get(evidence))):
            row['raw'].update({key: old.get(key, '') for key in fields})
            row['raw'][metadata] = proof
            continue
        row['raw'][metadata] = {'status': 'unverified'}
        try:
            found = reader(collector, row)
            row['raw'].update(found)
            row['raw'][metadata] = {
                'status': 'verified', 'checked_at': now.isoformat(),
                'title': row['title'], 'posted_at': row.get('posted_at'),
                'source_job_id': str(row.get('source_job_id') or ''),
            }
        except SourcePaused:
            raise
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            errors.append(f'{row["source_job_id"]}: {type(exc).__name__}: {exc}')
    return errors
