"""Collect public SQL job sources; report incomplete boards and safe fallbacks."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import time
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit, quote

import requests
from bs4 import BeautifulSoup
try:
    import tomllib
except ImportError:
    import tomli as tomllib

from .validate_sources import Source, request_for, json_items
from .paths import ROOT, CONFIG, DB, RUNS
from .jsearch_access import RequestGuard, QuotaExhausted, load_credentials

FIELDS = ['company_key', 'company_name', 'provider_key', 'title', 'location', 'url', 'source_job_id', 'posted_at', 'raw']
JSON_PROVIDERS = {'workday', 'greenhouse', 'ashby', 'oracle_cloud', 'smartrecruiters', 'phenom', 'amazon_jobs'}


def config(name):
    with (CONFIG / name).open('rb') as f:
        return tomllib.load(f)


def load_sources(db):
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as con:
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


def normalize(source, item):
    p = source.provider_key
    title = item.get('title') or item.get('Title') or item.get('jobTitle') or item.get('name')
    ident = item.get('id') or item.get('Id') or item.get('jobId') or item.get('jobSeqNo') or item.get('source_job_id')
    url = item.get('absolute_url') or item.get('jobUrl') or item.get('url') or item.get('detail_url')
    location = item.get('location') or item.get('locationsText') or item.get('PrimaryLocation') or item.get('jobLocation') or item.get('cityState')
    posted = item.get('datePosted') or item.get('publishedAt') or item.get('PostedDate') or item.get('posted_at') or item.get('postedDate')
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
            items.append({'title': title, 'url': urljoin(base, href), 'location': loc.get_text(' ', strip=True) if loc else None, 'source_job_id': urlsplit(href).path.rstrip('/').split('/')[-1], 'html': str(row)})
    return items, soup


class Collector:
    def __init__(self, source, args):
        self.source, self.args = source, args
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'JobSourceCollector/1.0', 'Accept': 'application/json,text/html,application/xml'})
        self.jobs, self.seen = [], set()
        self.rejected = []
        self.requests = 0

    def fetch(self, url, method='GET', payload=None):
        if self.requests:
            time.sleep(self.args.delay)
        self.requests += 1
        r = self.session.request(method, url, json=payload, timeout=self.args.timeout)
        r.raise_for_status()
        if 'json' not in r.headers.get('content-type', '') and 'xml' not in r.headers.get('content-type', ''):
            soup = BeautifulSoup(r.text, 'html.parser')
            visible = soup.get_text(' ', strip=True).lower()
            if any(t in visible for t in ['human verification', 'verify you are human', 'enable javascript and cookies to continue', 'access denied']) or soup.select_one('#challenge-form, #cf-challenge-running'):
                raise ValueError('Human verification/challenge: use JSearch fallback')
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
            data = self.fetch(target, method, payload).json()
            items = data.get('jobs', []) if p == 'amazon_jobs' else json_items(p, data)
            expected = {'workday': 'jobPostings', 'greenhouse': 'jobs', 'ashby': 'jobs', 'smartrecruiters': 'content', 'oracle_cloud': 'items', 'phenom': 'refineSearch', 'amazon_jobs': 'jobs'}[p]
            if not isinstance(data, dict) or expected not in data:
                raise ValueError(f'Unexpected {p} JSON schema')
            if p == 'phenom' and (data['refineSearch'].get('status') != 200 or not isinstance(data['refineSearch'].get('data', {}).get('jobs'), list)):
                raise ValueError('Phenom did not return a successful job list')
            if p == 'oracle_cloud' and data['items'] and not isinstance(data['items'][0].get('requisitionList'), list):
                raise ValueError('Oracle requisitionList missing from response')
            if not items:
                return 'complete', ''
            added = self.add(items)
            offset += len(items)
            total = data.get('total') or data.get('totalFound') or data.get('hits')
            if p == 'oracle_cloud':
                total = (data.get('items') or [{}])[0].get('TotalJobsCount')
            if p == 'phenom':
                total = data.get('refineSearch', {}).get('totalHits')
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
        urls = [e.text for e in root.iter() if e.tag.endswith('}loc') or e.tag == 'loc']
        if self.source.provider_key == 'eightfold':
            urls = [u for u in urls if u and '/job/' in u]
        errors = []
        for url in urls[:self.args.max_jobs]:
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
                self.add(items)
            except (requests.RequestException, ValueError) as exc:
                errors.append(f'{url}: {type(exc).__name__}: {exc}')
                if len(errors) >= 3:
                    return 'partial', f'Detail collection stopped after 3 failures; {errors[0]}'
        if errors:
            return 'partial', f'{len(errors)} detail failures; first: {errors[0]}'
        if len(urls) > self.args.max_jobs:
            return 'partial', 'Job cap reached; increase --max-jobs'
        return 'complete', ''

    def run(self):
        try:
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
            if self.source.provider_key in {'akeana_careers', 'renesas_careers', 'eightfold'}:
                return self.collect_sitemap()
            return self.collect_html()
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
    key = os.getenv('JSEARCH_API_KEY')
    if not key:
        return [], 'missing_credentials', 'Set JSEARCH_API_KEY; JSearch was not called'
    rows, seen, rejected = [], set(), 0
    conn = search['connection']
    headers = {conn['auth_header']: key}
    guard = getattr(args, 'jsearch_guard', None) or RequestGuard()
    names = [n for n in dict.fromkeys(list(aliases) + [source.company_name]) if n]
    names = names[:args.fallback_queries]
    with requests.Session() as session:
        for text in names:
            if budget[0] <= 0:
                return rows, 'partial', 'JSearch per-run request budget exhausted'
            url = search['endpoint_template'].format(query=quote(text, safe=''), page=1)
            url = query_url(url, country='us')
            try:
                r = guard.get(session, url, headers=headers, timeout=args.jsearch_timeout)
                budget[0] -= 1
                if r.status_code in {401, 403, 429}:
                    budget[0] = 0
                if 300 <= r.status_code < 400:
                    raise ValueError("Unexpected API redirect")
                r.raise_for_status()
                data = r.json()
                if not isinstance(data, dict) or data.get('status') != 'OK':
                    raise ValueError('JSearch API did not report OK')
                payload = data.get('data')
                if not isinstance(payload, dict) or not isinstance(payload.get('jobs'), list):
                    raise ValueError('Expected search-v2 data.jobs list')
                for item in payload['jobs']:
                    if not employer_matches(item.get(search['employer_field'], ''), aliases + [source.company_name]):
                        rejected += 1
                        continue
                    ident = item.get('job_id')
                    url = item.get('job_apply_link') or item.get('job_google_link')
                    if not ident or not url or not item.get('job_title') or ident in seen:
                        continue
                    seen.add(ident)
                    row = normalize(replace(source, provider_key='jsearch'), {'title': item['job_title'], 'url': url, 'id': ident, 'location': ', '.join(filter(None, [item.get('job_city'), item.get('job_state'), item.get('job_country')])), 'posted_at': item.get('job_posted_at_datetime_utc')})
                    row['raw'] = item
                    rows.append(row)
            except QuotaExhausted as exc:
                return rows, 'quota_exhausted', str(exc)
            except (requests.RequestException, ValueError) as exc:
                if not isinstance(exc, requests.Timeout):
                    budget[0] = 0
                return rows, 'partial' if rows else 'failed', f'JSearch {type(exc).__name__}' + (f' HTTP {exc.response.status_code}' if isinstance(exc, requests.HTTPError) and exc.response is not None else '') + '; check credentials, quota and connectivity'
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
    p.add_argument('--max-pages', type=int, default=100)
    p.add_argument('--max-jobs', type=int, default=10000)
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--timeout', type=float, default=25)
    p.add_argument('--delay', type=float, default=0.15)
    p.add_argument('--fallback-queries', type=int, default=1)
    p.add_argument('--jsearch-budget', type=int, default=30)
    p.add_argument('--jsearch-timeout', type=float, default=90,
                   help='JSearch read timeout; its Google-for-Jobs backend routinely needs 30-60s')
    args = p.parse_args()
    if min(args.max_pages, args.max_jobs, args.workers, args.timeout, args.jsearch_timeout, args.fallback_queries) <= 0 or args.jsearch_budget < 0 or args.delay < 0:
        p.error('Caps and timeout must be positive; delay and budget must be nonnegative')
    load_credentials()
    sources = load_sources(args.db)
    if args.company:
        unknown = set(args.company) - {s.company_key for s in sources}
        if unknown:
            p.error(f'Unknown company keys: {sorted(unknown)}')
        sources = [s for s in sources if s.company_key in args.company]
    discovery = config('discovery_queries.toml')
    fallbacks = {r['company_key']: r for r in discovery['company_fallbacks']}
    search = config('sources_search.toml')['search']['jsearch']
    budget = [min(args.jsearch_budget, search['limits']['requests']['requests_per_day'])]
    request_guard = RequestGuard()
    args.jsearch_guard = request_guard
    if args.output is None:
        args.output = RUNS / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    args.output.mkdir(parents=True, exist_ok=True)
    def direct(source):
        c = Collector(source, args)
        if source.company_key in fallbacks:
            status, reason = 'fallback', fallbacks[source.company_key]['reason']
        else:
            status, reason = c.run()
            if c.rejected:
                status = 'partial'
                reason = f'{len(c.rejected)} malformed records rejected. ' + reason
                (args.output/(source.company_key + '_rejected.json')).write_text(json.dumps(c.rejected, ensure_ascii=True), encoding='utf-8')
        print(f'{source.company_key}: {len(c.jobs)} jobs, {status}', flush=True)
        return source, c.jobs, status, reason, c.requests
    jobs, reports = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for source, rows, status, reason, count in pool.map(direct, sources):
            fs, fr = '', ''
            if status in {'fallback', 'failed', 'partial'}:
                aliases = fallbacks.get(source.company_key, {}).get('employer_aliases', [source.company_name])
                more, fs, fr = fallback(source, aliases, args, budget, search)
                urls = {row['url'] for row in rows}
                rows.extend(row for row in more if row['url'] not in urls)
            jobs.extend(rows)
            reports.append({'company_key': source.company_key, 'company_name': source.company_name, 'provider_key': source.provider_key, 'jobs': len(rows), 'direct_status': status, 'requests': count, 'failure_reason': reason, 'fallback_status': fs, 'next_step': '; '.join(filter(None, [reason if status != 'complete' else '', fr])) or 'None'})
    jobs.sort(key=lambda r: (r['company_key'], r['url']))
    with (args.output/'jobs.jsonl').open('w', encoding='utf-8') as f:
        for row in jobs:
            f.write(json.dumps(row, ensure_ascii=True)+'\n')
    write_csv(args.output/'jobs.csv', jobs, FIELDS)
    write_csv(args.output/'company_results.csv', reports, list(reports[0]) if reports else ['company_key'])
    manifest = {'collected_at': datetime.now(timezone.utc).isoformat(), 'companies': len(reports), 'jobs': len(jobs), 'max_pages': args.max_pages, 'max_jobs': args.max_jobs, 'jsearch_requests': request_guard.attempts, 'complete_direct_sources': sum(r['direct_status']=='complete' for r in reports)}
    (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest), flush=True)
    return 0 if all(r['direct_status']=='complete' for r in reports) else 2


def main_cli():
    """Console-script entry point."""
    return main()


if __name__ == '__main__':
    raise SystemExit(main())
