from __future__ import annotations

import csv
import json
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from .paths import DB, RAW
from .collection_policy import SourcePolicy, SourcePaused, retry_after_seconds, html_challenge
from bs4 import BeautifulSoup
from typing import Any
from urllib.parse import urlencode

import requests


DB_PATH = DB
OUT_CSV = RAW / "source_validation_results.csv"

USER_AGENT = "JobSourceCollector/1.0"


@dataclass
class Source:
    source_id: str
    table_name: str
    company_key: str
    company_name: str
    provider_key: str
    access_url: str
    fields: dict[str, Any]


def load_sources() -> list[Source]:
    rows: list[Source] = []
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        for table_name, id_col in (
            ("company_sources", "source_instance_id"),
            ("company_direct_sources", "direct_source_id"),
        ):
            sql = f"""
                SELECT s.{id_col} AS source_id, c.name AS company_name, s.*
                FROM {table_name} s
                JOIN companies c ON c.company_key = s.company_key
                WHERE s.enabled = 1
                ORDER BY s.provider_key, s.company_key
            """
            for row in con.execute(sql):
                rows.append(
                    Source(
                        source_id=row["source_id"],
                        table_name=table_name,
                        company_key=row["company_key"],
                        company_name=row["company_name"],
                        provider_key=row["provider_key"],
                        access_url=row["access_url"],
                        fields=json.loads(row["instance_fields_json"] or "{}"),
                    )
                )
    return rows


def workday_request(source: Source) -> tuple[str, str, dict[str, Any] | None]:
    tenant = source.fields["tenant"]
    site = source.fields["site"]
    host = source.fields["workday_host"]
    if source.fields.get("path_style") == "recruiting":
        base = f"https://{host}.myworkdaysite.com"
    else:
        base = f"https://{tenant}.{host}.myworkdayjobs.com"
    url = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    payload = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
    return url, "POST", payload


def oracle_request(source: Source) -> tuple[str, str, dict[str, str] | None]:
    api_domain = source.fields["api_domain"]
    site = source.fields["site"]
    params = {
        "onlyData": "true",
        "expand": "requisitionList",
        "finder": (
            "findReqs;"
            f"siteNumber={site},"
            "facetsList=LOCATIONS;WORK_LOCATIONS;TITLES;CATEGORIES;ORGANIZATIONS;POSTING_DATES,"
            "limit=20,offset=0,sortBy=POSTING_DATES_DESC"
        ),
    }
    return (
        f"https://{api_domain}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?"
        + urlencode(params),
        "GET",
        None,
    )


def phenom_request(source: Source) -> tuple[str, str, dict[str, Any]]:
    url = f"https://{source.fields['career_domain']}/widgets"
    payload = {
        "ddoKey": "refineSearch",
        "pageName": "search-results",
        "siteType": "external",
        "locale": source.fields.get("locale", "en_global"),
        "from": 0,
        "size": 20,
        "sortBy": "",
        "jobs": True,
        "counts": True,
        "keywords": "",
        "all_fields": ["category", "country", "state", "city", "type"],
    }
    return url, "POST", payload


def request_for(source: Source) -> tuple[str, str, dict[str, Any] | None]:
    if source.provider_key == "workday":
        return workday_request(source)
    if source.provider_key == "oracle_cloud":
        return oracle_request(source)
    if source.provider_key == "phenom":
        return phenom_request(source)
    return source.access_url, "GET", None


def json_items(provider: str, data: Any) -> list[Any]:
    if provider in {"greenhouse", "ashby"}:
        return data.get("jobs", []) if isinstance(data, dict) else []
    if provider == "smartrecruiters":
        return data.get("content", []) if isinstance(data, dict) else []
    if provider == "workday":
        return data.get("jobPostings", []) if isinstance(data, dict) else []
    if provider == "oracle_cloud":
        if not isinstance(data, dict):
            return []
        items = data.get("items") or []
        if items and isinstance(items[0], dict):
            return items[0].get("requisitionList") or []
    if provider == "amd_careers":
        if not isinstance(data, dict):
            return []
        # Each row wraps its fields in a nested "data" object.
        return [j.get("data") or j for j in data.get("jobs") or [] if isinstance(j, dict)]
    if provider == "eightfold":
        if not isinstance(data, dict):
            return []
        payload = data.get("data")
        return payload.get("positions") or [] if isinstance(payload, dict) else []
    if provider == "phenom":
        if not isinstance(data, dict):
            return []
        refine = data.get("refineSearch") or {}
        refine_data = refine.get("data") if isinstance(refine, dict) else {}
        return refine_data.get("jobs", []) if isinstance(refine_data, dict) else []
    return []


def xml_items(provider: str, text: str) -> list[dict[str, str]]:
    if provider not in {"akeana_careers", "renesas_careers"}:
        return []
    locs = re.findall(r"<loc>(.*?)</loc>", text, flags=re.IGNORECASE)
    items = []
    for loc in locs:
        if re.search(r"/job|/jobs|vacanc|opening|jid-", loc, flags=re.IGNORECASE):
            items.append({"url": loc, "title": loc.rstrip("/").split("/")[-1]})
    return items


def apple_items(text: str) -> list[dict[str, str]]:
    return [{'url': 'https://jobs.apple.com' + anchor['href'],
             'title': anchor.get_text(' ', strip=True)}
            for anchor in BeautifulSoup(text, 'html.parser').select('a[href]')
            if anchor['href'].startswith('/en-us/details/') and anchor.get_text(' ', strip=True)]


def achronix_items(text: str) -> list[dict[str, str]]:
    items = []
    pattern = re.compile(
        r'<td[^>]+views-field-title[^>]*>\s*<a href="(?P<href>/job/[^"]+)"[^>]*>(?P<title>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        title = re.sub(r"<[^>]+>", "", match.group("title")).strip()
        items.append({"url": "https://www.achronix.com" + match.group("href"), "title": title})
    return items


def html_signal(text: str) -> tuple[bool, str]:
    lowered = text.lower()
    challenge = html_challenge(text)
    if challenge:
        return False, challenge

    signals = [
        "/job/",
        "/jobs/",
        "job-title",
        "job title",
        "search-results",
        "jobsearch",
        "requisition",
        "career",
        "careers",
        "position",
        "opening",
    ]
    hits = [signal for signal in signals if signal in lowered]
    if hits:
        return True, "html signals: " + ", ".join(hits[:4])
    return False, "downloaded but no obvious job signal"


def validate(source: Source, session: requests.Session) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_id": source.source_id,
        "table": source.table_name,
        "company": source.company_name,
        "company_key": source.company_key,
        "provider": source.provider_key,
        "method": "",
        "tested_url": source.access_url,
        "status_code": "",
        "verdict": "fail",
        "item_count": "",
        "evidence": "",
    }
    try:
        url, method, payload = request_for(source)
        result.update(method=method, tested_url=url)
        policy = SourcePolicy(source, 1.0)
        policy.check()
        time.sleep(policy.interval)
        if method == "POST":
            response = session.post(url, json=payload, timeout=25)
        else:
            response = session.get(url, timeout=25)
        result["status_code"] = response.status_code
        content_type = response.headers.get("content-type", "")
        text = response.text or ""
        server_wait = retry_after_seconds(response.headers.get('Retry-After')) or 0
        if response.status_code in {429, 503}:
            policy.pause(f'HTTP {response.status_code} during validation', max(900, server_wait))
        if response.status_code in {401, 403, 405}:
            policy.pause(f'HTTP {response.status_code} access refused; review before retrying', max(86400, server_wait))
        if response.status_code >= 400:
            result["evidence"] = text[:180].replace("\n", " ")
            return result

        if 'json' not in content_type and 'xml' not in content_type:
            challenge = html_challenge(text)
            if challenge:
                policy.pause(challenge, 86400)

        if "xml" in content_type or text.lstrip().startswith("<?xml"):
            items = xml_items(source.provider_key, text)
            result["item_count"] = len(items)
            if items:
                result["verdict"] = "usable"
                result["evidence"] = items[0]["title"][:180]
            else:
                result["verdict"] = "download_ok_needs_extractor"
                result["evidence"] = "XML downloaded but no job URL pattern matched"
            return result

        if "json" in content_type or text.strip().startswith(("{", "[")):
            data = response.json()
            items = json_items(source.provider_key, data)
            result["item_count"] = len(items)
            if items:
                result["verdict"] = "usable"
                first = items[0]
                if isinstance(first, dict):
                    title = (
                        first.get("title")
                        or first.get("jobTitle")
                        or first.get("Title")
                        or first.get("externalPath")
                        or str(first)[:120]
                    )
                    result["evidence"] = str(title)[:180]
                else:
                    result["evidence"] = str(first)[:180]
            else:
                result["verdict"] = "download_ok_needs_check"
                result["evidence"] = "JSON parsed but no items found at expected path"
            return result

        if source.provider_key == "apple_jobs":
            items = apple_items(text)
            result["item_count"] = len(items)
            if items:
                result["verdict"] = "usable"
                result["evidence"] = items[0]["title"][:180]
                return result

        if source.provider_key == "achronix_careers":
            items = achronix_items(text)
            result["item_count"] = len(items)
            if items:
                result["verdict"] = "usable"
                result["evidence"] = items[0]["title"][:180]
                return result

        ok, evidence = html_signal(text)
        if ok:
            result["verdict"] = "download_ok_needs_extractor"
            result["evidence"] = evidence
        else:
            result["evidence"] = evidence
            if evidence.startswith('block/challenge signal:'):
                policy.pause(evidence, 86400)
        return result
    except SourcePaused as exc:
        result['verdict'] = 'paused'
        result['evidence'] = str(exc)
        return result
    except Exception as exc:  # noqa: BLE001 - CLI validation should preserve source-level errors.
        result["evidence"] = f"{type(exc).__name__}: {exc}"
        return result


def main() -> int:
    sources = load_sources()
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    # Before the probes, not after them: this directory is gitignored, so a
    # fresh checkout does not have it, and creating it at the write below meant
    # a full validation run -- every source, every request -- ended by throwing
    # its own report away.
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, source in enumerate(sources, start=1):
        print(f"[{index}/{len(sources)}] {source.source_id}", flush=True)
        rows.append(validate(source, session))

    temporary = OUT_CSV.with_suffix('.csv.tmp')
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        columns = list(rows[0]) if rows else ['source_id', 'table', 'company', 'company_key',
            'provider', 'method', 'tested_url', 'status_code', 'verdict', 'item_count', 'evidence']
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(OUT_CSV)

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    print(json.dumps(counts, indent=2, sort_keys=True))
    print(OUT_CSV)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
