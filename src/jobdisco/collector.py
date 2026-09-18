"""Collect public SQL job sources; report incomplete boards and safe fallbacks."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, nullcontext
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
try:
    import tomllib
except ImportError:
    import tomli as tomllib

from .validate_sources import Source, request_for, json_items
from .paths import ROOT, CONFIG, DB, RUNS
from .jsearch_access import RequestGuard, load_credentials
from .collection_policy import SourcePolicy, SourcePaused, retry_after_seconds, STATE as SOURCE_STATE
from . import store
from . import jsearch

FIELDS = ['company_key', 'company_name', 'provider_key', 'title', 'location', 'url', 'source_job_id', 'posted_at', 'raw']
JSON_PROVIDERS = {'workday', 'greenhouse', 'ashby', 'oracle_cloud', 'smartrecruiters', 'phenom', 'amazon_jobs', 'eightfold', 'amd_careers'}
_MICROSOFT_SOURCE_LOCK = threading.Lock()


def source_lock(source):
    """Serialize Microsoft without reducing concurrency for other sources."""
    return _MICROSOFT_SOURCE_LOCK if source.company_key == 'microsoft' else nullcontext()


def config(name):
    with (CONFIG / name).open('rb') as f:
        return tomllib.load(f)


def load_sources(db):
    with closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        con.row_factory = sqlite3.Row
        result = []
        for table, key in [('company_sources', 'source_instance_id'), ('company_direct_sources', 'direct_source_id')]:
            for row in con.execute(f'SELECT s.*, c.name FROM {table} s JOIN companies c USING(company_key) WHERE s.enabled=1 ORDER BY s.company_key'):
                result.append(Source(row[key], table, row['company_key'], row['name'], row['provider_key'], row['access_url'], json.loads(row['instance_fields_json'])))
    return result


def query_url(url, **params):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return urlunsplit(parts._replace(query=urlencode(query)))


def clean(value):
    return BeautifulSoup(str(value or ''), 'html.parser').get_text(' ', strip=True)


def location_text(value):
    if isinstance(value, list):
        return '; '.join(filter(None, (location_text(v) for v in value)))
    if isinstance(value, dict):
        if 'address' in value:
            return location_text(value['address'])
        parts = []
        for k in ['name', 'city', 'region', 'country', 'addressLocality', 'addressRegion', 'addressCountry']:
            v = value.get(k)
            if not v:
                continue
            # schema.org allows nested objects here, e.g. addressCountry as a Country.
            parts.append(location_text(v) if isinstance(v, (dict, list)) else str(v))
        return ', '.join(filter(None, parts))
    return str(value or '')


POSTED_FORMATS = ['%b %d, %Y', '%B %d, %Y', '%m/%d/%Y', '%Y-%m-%d', '%d %b %Y']


def posted_from_text(text):
    """Absolute posting date printed in a board row, or None for relative phrasing."""
    cleaned = re.sub(r'(?i)^\s*(posted|date posted)\s*:?\s*', '', str(text or '')).strip()
    for fmt in POSTED_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return None


def normalize(source, item):
    p = source.provider_key
    title = item.get('title') or item.get('Title') or item.get('jobTitle') or item.get('name')
    ident = item.get('id') or item.get('Id') or item.get('jobId') or item.get('jobSeqNo') or item.get('source_job_id')
    url = item.get('absolute_url') or item.get('jobUrl') or item.get('url') or item.get('detail_url')
    location = item.get('location') or item.get('locationsText') or item.get('PrimaryLocation') or item.get('jobLocation') or item.get('cityState')
    posted = item.get('datePosted') or item.get('publishedAt') or item.get('PostedDate') or item.get('posted_at') or item.get('postedDate')
    if not posted and item.get('posted_text'):
        posted = posted_from_text(item['posted_text'])
    if not posted and p == 'greenhouse':
        # first_published is the original posting; updated_at only tracks edits.
        posted = item.get('first_published') or item.get('updated_at')
    if p == 'workday':
        url = source.access_url.rstrip('/') + '/' + item.get('externalPath', '').lstrip('/')
        ident = item.get('externalPath', '').rsplit('_', 1)[-1] or None
        # Relative dates remain in raw; do not pretend they are absolute timestamps.
        posted = None
    elif p == 'oracle_cloud':
        parts = urlsplit(source.access_url)
        path = parts.path.split('/jobs')[0] + '/job/' + str(ident)
        url = urlunsplit(parts._replace(path=path, query='', fragment=''))
    elif p == 'smartrecruiters':
        url = item.get('applyUrl') or f"https://jobs.smartrecruiters.com/{source.fields['company_slug']}/{ident}"
        posted = item.get('releasedDate')
    elif p == 'phenom':
        url = url or f"https://{source.fields['career_domain']}/global/en/job/{ident}"
    elif p == 'amd_careers':
        # apply_url points at the iCIMS login wall; the public posting is on careers.amd.com.
        url = f"https://careers.amd.com/careers-home/jobs/{item.get('req_id') or item.get('slug')}"
        ident = item.get('req_id') or item.get('slug')
        location = item.get('full_location') or ', '.join(filter(None, [item.get('city'), item.get('state'), item.get('country')]))
        posted = item.get('posted_date') or item.get('create_date')
    elif p == 'eightfold':
        # positionUrl is site-relative; postedTs is a Unix timestamp.
        url = urljoin(source.access_url, item.get('positionUrl') or '')
        location = item.get('locations') or item.get('standardizedLocations')
        ts = item.get('postedTs') or item.get('creationTs')
        posted = datetime.fromtimestamp(ts, timezone.utc).isoformat() if isinstance(ts, (int, float)) else None
    elif p == 'amazon_jobs':
        ident = item.get('id_icims') or ident
        url = urljoin('https://www.amazon.jobs', item.get('job_path') or url) if item.get('job_path') or url else None
        posted = item.get('posted_date')
    if not title or not url or urlsplit(str(url)).scheme not in {'http', 'https'}:
        raise ValueError('Job record lacks a title or public HTTP URL')
    return dict(zip(FIELDS, [source.company_key, source.company_name, p, clean(title), location_text(location), str(url), str(ident) if ident is not None else None, posted, item]))


def jsonld(soup):
    def walk(data):
        if isinstance(data, list):
            for v in data:
                yield from walk(v)
        elif isinstance(data, dict):
            types = data.get('@type', [])
            if types == 'JobPosting' or isinstance(types, list) and 'JobPosting' in types:
                yield data
            else:
                for value in data.values():
                    if isinstance(value, (dict, list)):
                        yield from walk(value)
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            yield from walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            continue


def reported_total(provider, data):
    """The posting count the provider states for the whole board, if it states one."""
    if not isinstance(data, dict):
        return None
    if provider == 'oracle_cloud':
        return (data.get('items') or [{}])[0].get('TotalJobsCount')
    if provider == 'phenom':
        return (data.get('refineSearch') or {}).get('totalHits')
    if provider == 'eightfold':
        return (data.get('data') or {}).get('count')
    if provider == 'amd_careers':
        return data.get('totalCount') or data.get('count')
    return data.get('total') or data.get('totalFound') or data.get('hits')


def html_job_id(href, provider):
    """The requisition a board row points at, not the words in its URL.

    The last path segment is usually the identifier, but Apple puts the slug
    there and the requisition before it: one role advertised at forty stores
    shares a slug while each store has its own requisition. Taking the slug made
    those forty postings one identity, and the store then treated the other
    thirty-nine as withdrawn.
    """
    path = urlsplit(href).path.rstrip('/')
    if provider == 'apple_jobs':
        found = re.search(r'/details/([0-9][\w-]*)', path)
        if found:
            return found.group(1)
    return path.split('/')[-1]


def html_items(text, base, provider):
    soup = BeautifulSoup(text, 'html.parser')
    structured = list(jsonld(soup))
    if structured:
        return structured, soup
    patterns = {
        'achronix_careers': r'/job/[^/]+', 'apple_jobs': r'/details/[^/]+/[^/]+$',
        'jobs2web': r'/job/.+/\d+/?$', 'talentbrew': r'/job/.+/\d+/\d+',
        'avature': r'/job/.+/\d+/\d+|/JobDetail/', 'google_jobs': r'jobs/results/\d+-',
        'jobvite': r'/job/[^/]+', 'tsmc_careers': r'/JobDetail/',
        'hibob': r'/jobs/[\w-]+', 'uplers_company_profile': r'/talent/all-opportunities/HR\d+',
    }
    pattern = patterns.get(provider)
    items = []
    if pattern:
        for a in soup.select('a[href]'):
            href = a['href']
            if not re.search(pattern, urlsplit(href).path, re.I):
                continue
            h = a.select_one('h2,h3,[class*=job-title]')
            title = (h or a).get_text(' ', strip=True)
            row = a.find_parent('tr') or a.find_parent('li') or a.parent
            if provider == 'google_jobs':
                row = a.find_parent('li') or a.parent
                h = row.select_one('h3,h2')
                title = h.get_text(' ', strip=True) if h else title
                href = urljoin('https://www.google.com/about/careers/applications/', href)
            if not title or title.lower() in {'see full role description', "where we're hiring", 'apply', 'apply now'}:
                continue
            loc = row.select_one('[class*=location], [class*=Location]')
            d = row.select_one('[class*=posted-date], [class*=date-posted]')
            items.append({'title': title, 'url': urljoin(base, href), 'location': loc.get_text(' ', strip=True) if loc else None, 'source_job_id': html_job_id(href, provider), 'posted_text': d.get_text(' ', strip=True) if d else None, 'html': str(row)})
    return items, soup


class Collector:
    def __init__(self, source, args):
        self.source, self.args = source, args
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'JobSourceCollector/1.0', 'Accept': 'application/json,text/html,application/xml'})
        self.jobs, self.seen = [], set()
        self.rejected = []
        self.requests = 0
        # Set by main() from the stored per-source state; 'full' until a source
        # has one complete pass behind it.
        self.strategy, self.watermark = 'full', None
        self.etag = self.last_modified = None
        # Postings we already hold, and everything the board advertised this pass.
        # They differ when a per-posting fetch is skipped, and closing must use
        # the advertised set rather than what we downloaded.
        self.known, self.listed = set(), None
        self.policy = SourcePolicy(source, args.delay, getattr(args, 'source_state', SOURCE_STATE))

    def fetch(self, url, method='GET', payload=None):
        self.policy.check()
        if self.requests:
            time.sleep(self.policy.interval)
        # Stop on throttling. Only transient service errors receive bounded retries.
        for attempt in range(self.args.retries + 1):
            self.policy.check()
            self.requests += 1
            r = self.session.request(method, url, json=payload, timeout=self.args.timeout)
            if self.etag is None and r.status_code == 200:
                self.etag = r.headers.get('ETag')
                self.last_modified = r.headers.get('Last-Modified')
            server_wait = retry_after_seconds(r.headers.get('Retry-After'))
            if r.status_code == 429:
                r.close()
                self.policy.pause('HTTP 429 rate limit; source stopped for this run', max(900, server_wait or 0))
            if r.status_code in {401, 403, 405}:
                status = r.status_code
                r.close()
                self.policy.pause(f'HTTP {status} access refused; review before retrying', max(86400, server_wait or 0))
            if r.status_code != 503:
                break
            wait = max(self.policy.interval, 5 * 2 ** attempt, server_wait or 0)
            r.close()
            if attempt == self.args.retries or wait > 60:
                self.policy.pause('HTTP 503 service unavailable; deferred', max(900, wait))
            time.sleep(wait)
        r.raise_for_status()
        if 'json' not in r.headers.get('content-type', '') and 'xml' not in r.headers.get('content-type', ''):
            soup = BeautifulSoup(r.text, 'html.parser')
            visible = soup.get_text(' ', strip=True).lower()
            if any(t in visible for t in ['human verification', 'verify you are human', 'enable javascript and cookies to continue', 'access denied']) or soup.select_one('#challenge-form, #cf-challenge-running'):
                r.close()
                self.policy.pause('Human verification/challenge; review before retrying', 86400)
        return r

    def add(self, items):
        before = len(self.jobs)
        for item in items:
            try:
                row = normalize(self.source, item)
            except ValueError as exc:
                self.rejected.append({'reason': str(exc), 'raw': item})
                continue
            key = row['url']
            if key in self.seen:
                continue
            if len(self.jobs) >= self.args.max_jobs:
                break
            self.seen.add(key)
            self.jobs.append(row)
        return len(self.jobs) - before

    def collect_json(self):
        p = self.source.provider_key
        url, method, payload = request_for(self.source)
        offset = 0
        for page in range(self.args.max_pages):
            target = url
            if p == 'workday':
                payload['offset'] = offset
            elif p == 'phenom':
                payload['from'] = offset
            elif p == 'oracle_cloud':
                target = url.replace('offset%3D0', f'offset%3D{offset}')
            elif p == 'smartrecruiters':
                target = query_url(url, offset=offset, limit=100)
            elif p == 'amazon_jobs':
                target = f'https://www.amazon.jobs/en/search.json?offset={offset}&result_limit=100&sort=recent'
            elif p == 'eightfold':
                target = query_url(url, start=offset, num=10)
            elif p == 'amd_careers':
                target = query_url(url, page=page + 1)
            data = self.fetch(target, method, payload).json()
            items = data.get('jobs', []) if p == 'amazon_jobs' else json_items(p, data)
            expected = {'workday': 'jobPostings', 'greenhouse': 'jobs', 'ashby': 'jobs', 'smartrecruiters': 'content', 'oracle_cloud': 'items', 'phenom': 'refineSearch', 'amazon_jobs': 'jobs', 'eightfold': 'data', 'amd_careers': 'jobs'}[p]
            if not isinstance(data, dict) or expected not in data:
                raise ValueError(f'Unexpected {p} JSON schema')
            if p == 'phenom' and (data['refineSearch'].get('status') != 200 or not isinstance(data['refineSearch'].get('data', {}).get('jobs'), list)):
                raise ValueError('Phenom did not return a successful job list')
            if p == 'oracle_cloud' and data['items'] and not isinstance(data['items'][0].get('requisitionList'), list):
                raise ValueError('Oracle requisitionList missing from response')
            if not items:
                if page:
                    return 'complete', ''
                # A board that lists nothing on its first page looks the same as one
                # that failed to render, and 'complete' is what lets the store retire
                # every posting the company has. Take a blank at face value only when
                # the board also states a count of zero.
                if reported_total(p, data) == 0:
                    return 'complete', ''
                return 'partial', 'First page listed no postings and no count was reported'
            if self.strategy == 'since' and self.watermark and p == 'eightfold':
                fresh = [i for i in items
                         if not isinstance(i.get('postedTs'), (int, float))
                         or datetime.fromtimestamp(i['postedTs'], timezone.utc).isoformat() > self.watermark]
                self.add(fresh)
                if len(fresh) < len(items):
                    return 'complete', ''
                offset += len(items)
                continue
            added = self.add(items)
            offset += len(items)
            total = reported_total(p, data)
            if p in {'greenhouse', 'ashby'}:
                return ('partial', 'Job cap reached') if len(items) > self.args.max_jobs else ('complete', '')
            if isinstance(total, (int, float)) and offset >= total:
                if p == 'amazon_jobs' and total >= 10000:
                    return 'partial', 'Amazon search returned its 10,000-result ceiling; partition searches to establish full coverage'
                return 'complete', ''
            if not added:
                return 'partial', 'Repeated page; provider ignored pagination'
            if len(self.jobs) >= self.args.max_jobs:
                return 'partial', 'Job cap reached; increase --max-jobs'
        return 'partial', 'Page cap reached; increase --max-pages'

    def collect_html(self):
        source = self.source
        url = source.access_url
        seen_pages = set()
        for page in range(self.args.max_pages):
            if url in seen_pages:
                return 'partial', 'Repeated next-page URL'
            seen_pages.add(url)
            r = self.fetch(url)
            items, soup = html_items(r.text, r.url, source.provider_key)
            if not items:
                visible = soup.get_text(' ', strip=True).lower()
                if self.jobs and source.provider_key in {'apple_jobs', 'google_jobs'} and ('there are no results that match your search' in visible or 'no results search again' in visible):
                    return 'complete', ''
                raise ValueError('No structured job records; extractor or public endpoint required')
            if source.provider_key in {'talentbrew', 'avature'}:
                pagination = soup.select_one('[data-total-pages]')
                if pagination and int(pagination['data-total-pages']) <= page + 1:
                    self.add(items)
                    return 'complete', ''
            added = self.add(items)
            if not added:
                return 'partial', 'Repeated job page; pagination requires review'
            if len(self.jobs) >= self.args.max_jobs:
                return 'partial', 'Job cap reached; increase --max-jobs'
            next_link = soup.select_one('a[rel=next], a.next:not(.disabled), a[aria-label="Next"]')
            if not next_link:
                next_link = next((a for a in soup.select('a[href]') if a.get_text(' ', strip=True).lower() in {'next', 'next page'}), None)
            if next_link and next_link.get('href'):
                candidate = urljoin(r.url, next_link['href'])
                if source.provider_key in {'talentbrew', 'avature'}:
                    candidate = query_url(source.access_url, p=page+2)
                if urlsplit(candidate).netloc != urlsplit(r.url).netloc:
                    raise ValueError('Unexpected cross-domain pagination link')
                url = candidate
            elif source.provider_key == 'jobs2web':
                links = [urljoin(r.url, a['href']) for a in soup.select('a[href]') if 'startrow=' in a['href']]
                current = int(dict(parse_qsl(urlsplit(url).query)).get('startrow', 0))
                later = sorted((int(dict(parse_qsl(urlsplit(v).query)).get('startrow', 0)), v) for v in links)
                later = [(n, v) for n, v in later if n > current]
                if not later:
                    return 'complete', ''
                url = later[0][1]
            elif source.provider_key in {'apple_jobs', 'google_jobs'}:
                url = query_url(source.access_url, page=page+2)
            else:
                return ('complete', '') if source.provider_key == 'achronix_careers' else ('partial', 'No next-page link; board completeness unverified')
        return 'partial', 'Page cap reached; increase --max-pages'

    def collect_sitemap(self):
        r = self.fetch(self.source.access_url)
        root = ET.fromstring(r.content)
        if not root.tag.endswith('urlset'):
            raise ValueError('Expected a job URL sitemap')
        urls = []
        for entry in root:
            loc = mod = None
            for child in entry:
                if child.tag.endswith('loc'):
                    loc = child.text
                elif child.tag.endswith('lastmod'):
                    mod = child.text
            if loc:
                urls.append((loc, mod))
        # Every advertised URL is still live even where the detail fetch is skipped.
        self.listed = {u for u, _ in urls}
        if self.strategy == 'lastmod' and self.watermark:
            # A page whose lastmod predates our last complete pass cannot have
            # changed; entries without a lastmod are always refetched.
            urls = [(u, m) for u, m in urls if not m or m > self.watermark]
        # A posting already stored costs a request to re-read and rarely changes,
        # so spend requests only on ones we have never fetched.
        skipped = sum(1 for u, _ in urls if u in self.known)
        urls = [(u, m) for u, m in urls if u not in self.known]
        errors = []
        for url, lastmod in urls[:self.args.max_jobs]:
            try:
                detail = self.fetch(url)
                soup = BeautifulSoup(detail.text, 'html.parser')
                items = list(jsonld(soup))
                if not items:
                    h = soup.select_one('h1')
                    if not h:
                        raise ValueError('Missing job title')
                    items = [{'title': h.get_text(' ', strip=True), 'url': url}]
                for item in items:
                    item.setdefault('url', url)
                    if lastmod:
                        item.setdefault('lastmod', lastmod)
                self.add(items)
            except (requests.RequestException, ValueError) as exc:
                errors.append(f'{url}: {type(exc).__name__}: {exc}')
                if len(errors) >= 3:
                    return 'partial', f'Detail collection stopped after 3 failures; {errors[0]}'
        if errors:
            return 'partial', f'{len(errors)} detail failures; first: {errors[0]}'
        if len(urls) > self.args.max_jobs:
            return 'partial', 'Job cap reached; increase --max-jobs'
        return 'complete', (f'{skipped} already stored, not refetched' if skipped else '')

    def run(self):
        try:
            if self.strategy == 'conditional' and self.watermark:
                # One cheap probe. A 304 ends the source here; anything else means
                # the board moved and the normal pass below reads it properly.
                self.session.headers['If-None-Match'] = self.watermark
                probe = self.fetch(request_for(self.source)[0])
                self.session.headers.pop('If-None-Match', None)
                if probe.status_code == 304:
                    return 'unchanged', ''
            if self.source.provider_key == 'hibob':
                self.session.headers['companyIdentifier'] = self.source.fields['subdomain']
                data = self.fetch(urljoin(self.source.access_url, '/api/job-ad')).json()
                if not isinstance(data.get('jobAdDetails'), list):
                    raise ValueError('Unexpected HiBob job-ad schema')
                items = data['jobAdDetails']
                for item in items:
                    item['url'] = self.source.access_url.rstrip('/') + '/' + item['id']
                    item['location'] = ', '.join(filter(None, [item.get('site'), item.get('country')]))
                self.add(items)
                return ('partial', 'Job cap reached') if len(items) > self.args.max_jobs else ('complete', '')
            if self.source.provider_key == 'ti_careers':
                r = self.fetch(self.source.access_url)
                base = BeautifulSoup(r.text, 'html.parser').select_one('base[data-apibaseurl]')
                if not base:
                    raise ValueError('Oracle API origin missing from TI shell')
                self.source = replace(self.source, provider_key='oracle_cloud', fields={'api_domain': urlsplit(base['data-apibaseurl']).netloc, 'site': base['data-sitenumber']})
            if self.source.provider_key in JSON_PROVIDERS:
                return self.collect_json()
            if self.source.provider_key in {'akeana_careers', 'renesas_careers'}:
                return self.collect_sitemap()
            return self.collect_html()
        except SourcePaused as exc:
            return 'paused', str(exc)
        except Exception as exc:
            return ('partial' if self.jobs else 'failed'), f'{type(exc).__name__}: {exc}'
        finally:
            self.session.close()


def employer_normalize(name):
    text = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
    words = re.findall(r'[a-z0-9]+', text)
    suffixes = {'inc', 'incorporated', 'corp', 'corporation', 'llc', 'ltd', 'limited', 'co', 'company'}
    while words and words[-1] in suffixes:
        words.pop()
    return ' '.join(words)


def employer_matches(name, aliases):
    return bool(name) and employer_normalize(name) in {employer_normalize(a) for a in aliases}


def fallback(source, aliases, args, budget, search):
    """Compatibility helper for a bounded employer search using the shared client."""
    if not os.getenv('JSEARCH_API_KEY'):
        return [], 'missing_credentials', 'Set JSEARCH_API_KEY; JSearch was not called'
    rows, seen, rejected = [], set(), 0
    guard = getattr(args, 'jsearch_guard', None) or RequestGuard()
    names = [n for n in dict.fromkeys(list(aliases) + [source.company_name]) if n]
    names = names[:args.fallback_queries]
    settings = {'country': 'us', 'date_posted': 'today', 'employment_types': ['FULLTIME', 'INTERN']}
    client = jsearch.Client(search, settings, guard, args.jsearch_timeout)
    try:
        for text in names:
            if budget[0] <= 0:
                return rows, 'partial', 'JSearch per-run request budget exhausted'
            query = jsearch.Query(text, 1, 'company', source.company_key, tuple(aliases))
            budget[0] -= 1
            try:
                for item in client.fetch(query):
                    if not isinstance(item, dict) or not employer_matches(item.get('employer_name', ''), aliases + [source.company_name]):
                        rejected += 1
                        continue
                    try:
                        row = jsearch.normalize_job(item, query, {employer_normalize(source.company_name): source.company_key})
                    except (ValueError, TypeError):
                        continue
                    identity = row['source_job_id'] or row['url']
                    if identity not in seen:
                        seen.add(identity)
                        rows.append(row)
            except jsearch.SearchFailure as exc:
                if exc.stop:
                    budget[0] = 0
                return rows, 'partial' if rows else 'failed', str(exc)
    finally:
        client.close()
    return rows, 'query_limited', f'First page of {len(names)} employer-name queries; {rejected} employer mismatches rejected'


def write_csv(path, rows, fields):
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(row[k], ensure_ascii=True) if isinstance(row[k], (dict, list)) else row[k] for k in fields})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', type=Path, default=DB)
    p.add_argument('--output', type=Path, default=None, help='Run directory; defaults to runs/<UTC timestamp>')
    p.add_argument('--company', action='append', help='Repeat to select company keys')
    p.add_argument('--max-pages', type=int, default=400)
    p.add_argument('--max-jobs', type=int, default=10000)
    p.add_argument('--workers', type=int, default=1)
    p.add_argument('--timeout', type=float, default=25)
    p.add_argument('--delay', type=float, default=1.0, help='Minimum delay; Eightfold uses at least 2.5s and Microsoft 3s')
    p.add_argument('--no-store', dest='store', action='store_false', help='Write run files only; leave the job store untouched')
    p.add_argument('--retries', type=int, default=3, help='Retries for 503 only; 429 pauses the source immediately')
    p.add_argument('--fallback-queries', type=int, default=1)
    p.add_argument('--jsearch', action='store_true', help='Enable the fixed functional JSearch discovery plan')
    p.add_argument('--jsearch-only', action='store_true', help='Run functional JSearch only, without direct sources or company fallbacks')
    p.add_argument('--jsearch-query', help='Run one positive phrase instead of the functional catalog')
    p.add_argument('--jsearch-pages', type=int, default=None, help='Pages for --jsearch-query only; default 1, maximum 20')
    p.add_argument('--date-posted', choices=['all', 'today', '3days', 'week', 'month'], help='Temporary JSearch time window; does not edit configuration')
    p.add_argument('--jsearch-plan', action='store_true', help='Print the fixed plan without making requests')
    p.add_argument('--backfill', action='store_true',
                   help="Month-wide sweep of the cycle's remaining credits; run it after a daily pass")
    p.add_argument('--jsearch-config', type=Path, default=CONFIG / 'jsearch_queries.toml')
    p.add_argument('--jsearch-budget', type=int, default=0, help='Page-credit cap; 0 uses config with --jsearch, otherwise disables paid discovery')
    p.add_argument('--jsearch-timeout', type=float, default=90,
                   help='JSearch read timeout; its Google-for-Jobs backend routinely needs 30-60s')
    p.add_argument('--jsearch-max-seconds', type=float, default=0,
                   help='Stop paid paging cleanly after this many seconds; 0 has no runtime limit')
    args = p.parse_args()
    if min(args.max_pages, args.max_jobs, args.workers, args.timeout, args.jsearch_timeout, args.fallback_queries) <= 0 or args.jsearch_budget < 0 or args.jsearch_max_seconds < 0 or args.delay < 0 or args.retries < 0:
        p.error('Caps and timeout must be positive; delay and budget must be nonnegative')
    settings, functional_queries = jsearch.load_plan(args.jsearch_config)
    if args.jsearch_pages is not None and (not args.jsearch_query or not 1 <= args.jsearch_pages <= 20):
        p.error('--jsearch-pages requires --jsearch-query and a value in 1..20')
    if args.jsearch_only or args.jsearch_query:
        args.jsearch = True
    if args.jsearch_query:
        phrase = args.jsearch_query.strip()
        if not phrase or re.search(r'(^|\s)-\w', phrase):
            p.error('--jsearch-query requires a positive nonempty phrase')
        functional_queries = [jsearch.Query(phrase, args.jsearch_pages or 1, 'manual')]
    if args.backfill:
        # Credits do not carry into the next cycle, so a sweep looks a month
        # back, pages far deeper than a daily pass, and is not held to the daily
        # slice -- that slice exists only to pace the month it is now ending.
        settings['date_posted'] = 'month'
        settings['max_pages_per_query'] = settings['backfill_max_pages_per_query']
        settings['tier_pages'] = settings['backfill_tier_pages']
        # The plan is loaded with the daily depths, so a sweep restates them
        # with its own -- per tier, because one depth for everyone is what let
        # tier A spend the whole budget before the rest were reached. A row
        # that set its own depth, and a single --jsearch-query, stay as written.
        def sweep_depth(query):
            daily = settings['tier_pages_daily'].get(
                query.tier, settings['max_pages_per_query_daily'])
            if query.pages != daily:
                return query
            return replace(query, pages=settings['tier_pages'].get(
                query.tier, settings['max_pages_per_query']))
        if not args.jsearch_query:
            functional_queries = [sweep_depth(q) for q in functional_queries]
        if not args.store:
            p.error('--backfill requires durable storage; it cannot be combined with --no-store')
    if args.date_posted:
        settings['date_posted'] = args.date_posted
    enabled = args.jsearch or args.jsearch_plan or args.jsearch_budget > 0 or args.backfill
    run_budget = min(args.jsearch_budget or settings['daily_budget'], settings['daily_budget']) if enabled else 0
    if not args.db.exists() and args.jsearch_plan:
        # Preview authored sources without creating or replaying private state.
        with tempfile.TemporaryDirectory() as folder:
            preview_db = Path(folder) / 'preview.sqlite'
            with closing(sqlite3.connect(preview_db)) as connection:
                connection.executescript((CONFIG / 'schema.sql').read_text(encoding='utf-8'))
                for migration in sorted((CONFIG / 'migrations').glob('*.sql')):
                    connection.executescript(migration.read_text(encoding='utf-8'))
            all_sources = load_sources(preview_db)
    else:
        if not args.db.exists():
            store.bootstrap(args.db)
        all_sources = load_sources(args.db)
    sources = all_sources
    if args.jsearch_only:
        sources = []
        if args.company:
            p.error('--company cannot be combined with --jsearch-only')
    if args.company:
        unknown = set(args.company) - {s.company_key for s in sources}
        if unknown:
            p.error(f'Unknown company keys: {sorted(unknown)}')
        sources = [s for s in sources if s.company_key in args.company]
    discovery = config('discovery_queries.toml')
    fallbacks = {r['company_key']: r for r in discovery.get('company_fallbacks', [])}
    search = config('sources_search.toml')['search']['jsearch']
    company_queries = jsearch.fallback_plan(discovery, all_sources, args.fallback_queries) if enabled and not args.jsearch_only else []
    company_queries = [q for q in company_queries if q.company_key in {s.company_key for s in sources}]
    # A sweep is a functional pass too, and it is the one that spends what the
    # cycle has left: leaving it out here emptied the plan and made it a no-op.
    functional_queries = functional_queries if args.jsearch or args.jsearch_plan or args.backfill else []
    planned_queries = functional_queries + company_queries
    # The plan is checked against the budget the plan is written for, not
    # against whatever one run was told to spend. A run may be deliberately
    # bounded -- a sweep's share of the cycle, or a capped test -- and that is
    # not a misconfigured plan; the guard stops such a run at its own limit.
    jsearch.validate_budget(planned_queries, settings['daily_budget'])
    if args.jsearch_plan:
        # Depth is discovered while paging, so a plan states how many queries it
        # holds and what they may spend, never how many pages it will use.
        print(json.dumps({'queries': [q.__dict__ for q in planned_queries],
                          'queries_planned': len(planned_queries),
                          'max_pages_per_query': settings['max_pages_per_query'],
                          # A sweep's budget is whatever the cycle has left when
                          # it starts, which a preview cannot know.
                          'run_budget': 'computed at run time' if args.backfill else run_budget,
                          'daily_budget': settings['daily_budget'],
                          'date_posted': settings['date_posted'],
                          'monthly_target': settings['monthly_target']}, indent=2))
        return 0
    run_stamp = store.now()
    if args.store and store.sealed(run_stamp):
        p.error('That UTC day is over and sealed in the persistent store; refusing to modify it')
    load_credentials()
    if args.store:
        store.migrate(args.db)
    source_state = store.load_state(args.db) if args.store else {}
    known_by_company = None
    if args.store:
        with closing(store.connect(args.db)) as probe:
            known_by_company = {s.company_key: store.known_urls(probe, s.company_key)
                                for s in sources if s.provider_key in store.LASTMOD_SITEMAP}
    request_guard = RequestGuard(limit=settings['monthly_quota'], target_limit=settings['monthly_target'],
                                 daily_limit=settings['daily_budget'],
                                 cycle_start=settings['cycle_start'],
                                 cycle_days=settings['cycle_days'],
                                 ignore_daily_limit=args.backfill,
                                 run_limit=run_budget if enabled else None)
    if args.backfill:
        # Spread what is left over the days that are left, so an early sweep
        # cannot take a remainder a later day may need to recover in. An
        # explicit budget only lowers that share, which is how the path is
        # tested without spending the cycle.
        left = request_guard.balance()['period_remaining']
        days = max(1, request_guard.days_until_reset())
        run_budget = left if days <= 1 else left // days
        run_budget = min(run_budget, args.jsearch_budget or run_budget)
        request_guard.run_limit = run_budget
        print(f'backfill: {left} credits left in the cycle, {days} days to reset, '
              f'spending up to {run_budget}', flush=True)
    args.jsearch_guard = request_guard
    if args.output is None:
        args.output = RUNS / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    args.output.mkdir(parents=True, exist_ok=True)
    def direct(source):
        with source_lock(source):
            c = Collector(source, args)
            c.strategy, c.watermark = store.plan(source, source_state)
            if source.provider_key in store.LASTMOD_SITEMAP and known_by_company is not None:
                c.known = known_by_company.get(source.company_key, set())
            try:
                status, reason = c.run()
                if c.rejected:
                    status = 'partial'
                    reason = f'{len(c.rejected)} malformed records rejected. ' + reason
                    (args.output/(source.company_key + '_rejected.json')).write_text(json.dumps(c.rejected, ensure_ascii=True), encoding='utf-8')
            finally:
                c.session.close()
            print(f'{source.company_key}: {len(c.jobs)} jobs, {status}', flush=True)
            return source, c.jobs, status, reason, c.requests, c
    jobs, reports = [], []
    # Bound before anything can fail: the seal that runs on the way out of a
    # failed pass needs it, and the pass that motivated the seal died in the
    # direct-source loop, long before the search block would have set it.
    search_stats = {}
    run_id = args.output.name
    totals = {'seen': 0, 'new': 0, 'closed': 0}

    def persist(db, source, rows, status, count, c):
        """Commit one source as soon as it finishes.

        Holding a whole run in memory and writing at the end means an
        interruption loses every board already downloaded, and leaves no record
        of which postings were seen. Each source is committed on its own so
        progress is durable and queryable while the run continues.
        """
        if db is None:
            return None
        strategy = getattr(c, 'strategy', 'full')
        kwargs = {'etag': getattr(c, 'etag', None),
                  'last_modified': getattr(c, 'last_modified', None)}
        if status == 'unchanged':
            delta = store.touch_source(db, source, strategy, count, stamp=run_stamp, **kwargs)
        else:
            delta = store.record_source(db, source, rows, status, strategy, count,
                                        stamp=run_stamp, listed=getattr(c, 'listed', None), **kwargs)
        store.append_log(db, delta['new_urls'] + delta.get('changed_urls', []),
                         delta['closed_urls'], run_stamp, seen_urls=delta.get('seen_urls', []),
                         source_id=source.source_id)
        db.commit()
        for key in ('seen', 'new', 'closed'):
            totals[key] += delta[key]
        if delta.get('closure_fused'):
            print(f"WARNING: {delta['note']}", flush=True)
        print(f"  stored {source.company_key}: +{delta['new']} new, "
              f"-{delta['closed']} closed, {delta['seen']} seen", flush=True)
        return delta

    def seal(db):
        """Leave the day's log and its manifest agreeing, whatever happened.

        Sources are committed one at a time, so an exception anywhere after the
        first board leaves postings appended to the day file. A manifest that
        still describes the file as it was before makes the whole store fail its
        own integrity check, and the next run cannot even rebuild from it. The
        seal is therefore owed by every exit, not only the successful one.
        """
        if db is None:
            return
        store.export_state(db)
        store.write_manifest(db, run_stamp, reports, search_stats)
        db.commit()

    with closing(store.connect(args.db)) if args.store else nullcontext() as db:
      try:
        if db is not None:
            store.start_run(db, run_id)
            db.commit()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for source, rows, status, reason, count, c in pool.map(direct, sources):
                fs, fr = '', ''
                jobs.extend(rows)
                delta = persist(db, source, rows, status, count, c)
                if delta and delta.get('status') != status:
                    status = delta['status']
                    reason = '; '.join(filter(None, [reason, delta.get('note', '')]))
                reports.append({'company_key': source.company_key, 'company_name': source.company_name, 'provider_key': source.provider_key, 'jobs': len(rows), 'direct_status': status, 'requests': count, 'failure_reason': reason, 'fallback_status': fs, 'next_step': '; '.join(filter(None, [reason if status != 'complete' else '', fr])) or 'None'})
        # Functional discovery follows direct sources. Only configured employers
        # qualify for the final fallback phase; no automatic company-wide search.
        direct_results = {r['company_key']: r for r in reports}
        eligible = [q for q in company_queries if
                    fallbacks[q.company_key].get('mode') == 'supplement' or
                    (direct_results[q.company_key]['direct_status'] == 'failed' and
                     direct_results[q.company_key]['jobs'] == 0)]
        from types import SimpleNamespace
        checkpointed_queries = set()

        def query_source(query):
            return Source(query.key, 'discovery', query.company_key or 'jsearch_discovery',
                          query.query, 'jsearch', '', {})

        def checkpoint_query(query, rows, detail):
            source = query_source(query)
            persist(db, source, rows, 'query_limited', 1,
                    SimpleNamespace(strategy='full'))
            checkpointed_queries.add(query.key)

        def persist_query(query, rows, detail):
            source = query_source(query)
            count = 1 if detail['pages_used'] else 0
            if query.key not in checkpointed_queries:
                persist(db, source, rows, detail['status'], count,
                        SimpleNamespace(strategy='full'))
            reports.append({'company_key': source.company_key, 'company_name': query.query,
                            'provider_key': 'jsearch', 'jobs': len(rows), 'direct_status': detail['status'],
                            'requests': count, 'failure_reason': detail['reason'],
                            'fallback_status': 'configured' if query.company_key else '',
                            'next_step': detail['reason'] or 'Query-limited discovery; no closure inference'})
        companies = {employer_normalize(s.company_name): s.company_key for s in all_sources}
        for key, entry in fallbacks.items():
            companies.update({employer_normalize(a): key for a in entry.get('employer_aliases', [])})
        client = jsearch.Client(search, settings, request_guard, args.jsearch_timeout)
        try:
            deadline = (time.monotonic() + args.jsearch_max_seconds
                        if args.jsearch_max_seconds else None)
            discovered, search_stats = jsearch.collect(
                functional_queries + eligible, client, settings, companies, persist_query,
                backfill=args.backfill,
                checkpoint=checkpoint_query if db is not None else None,
                deadline=deadline)
        finally:
            client.close()
        # Same IDs appearing under multiple phrases get one presentation row.
        presented = set()
        for row in discovered:
            identity = row['source_job_id'] or row['url']
            if identity not in presented and row['url'] not in {r['url'] for r in jobs}:
                jobs.append(row)
                presented.add(identity)
        if db is not None:
            store.finish_run(db, run_id, len(reports), totals['seen'], totals['new'],
                             totals['closed'], sum(r['requests'] for r in reports))
            store.export_state(db)
            manifest = store.write_manifest(db, run_stamp, reports, search_stats)
            db.commit()
            print('manifest: %s records=%s sha256=%s' % (
                manifest['run_date'], manifest['records'], (manifest['sha256'] or '-')[:12]), flush=True)
            print(f"store: {totals['new']} new, {totals['closed']} closed, "
                  f"{totals['seen']} seen", flush=True)
      except BaseException:
        # Whatever went wrong, the boards already stored must not be left behind
        # a manifest that disagrees with them.
        try:
            seal(db)
        except Exception as inner:
            print(f'WARNING: could not seal the day after a failure: {inner}', flush=True)
        raise
    jobs.sort(key=lambda r: (r['company_key'], r['url']))
    with (args.output/'jobs.jsonl').open('w', encoding='utf-8') as f:
        for row in jobs:
            f.write(json.dumps(row, ensure_ascii=True)+'\n')
    write_csv(args.output/'jobs.csv', jobs, FIELDS)
    write_csv(args.output/'company_results.csv', reports, list(reports[0]) if reports else ['company_key'])
    manifest = {'collected_at': datetime.now(timezone.utc).isoformat(), 'companies': len(sources), 'jobs': len(jobs), 'max_pages': args.max_pages, 'max_jobs': args.max_jobs, 'jsearch_requests': request_guard.attempts, 'complete_direct_sources': sum(r['direct_status']=='complete' and r['provider_key'] != 'jsearch' for r in reports), 'store_new': totals['new'], 'store_closed': totals['closed'], 'store_seen': totals['seen'], **search_stats}
    (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest), flush=True)
    # A search the budget never reached is not a fault. Spending the budget is
    # what a sweep is for, and it leaves the rest of the plan untouched by
    # design; only a board that failed to read is worth a nonzero exit.
    settled = {'complete', 'unchanged', 'query_limited', 'skipped'}
    return 0 if all(r['direct_status'] in settled for r in reports) else 2


def main_cli():
    """Console-script entry point."""
    return main()


if __name__ == '__main__':
    raise SystemExit(main())
