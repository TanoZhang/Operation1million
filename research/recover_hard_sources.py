"""Fetch hard-to-access SQL company sources and emit normalized JSONL.

This script is deliberately narrow: it covers the company sources that were
not reachable through plain requests during the SQL-source verification pass.
It does not read or modify TOML source files.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlencode

import requests

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - optional parser fallback
    BeautifulSoup = None  # type: ignore[assignment]


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


@dataclass
class JobLead:
    company_key: str
    source: str
    job_id: str
    title: str
    url: str
    location: str | None = None
    posted_at: str | None = None
    description: str | None = None
    raw: dict[str, Any] | None = None

    def as_json(self) -> dict[str, Any]:
        data = {
            "company_key": self.company_key,
            "source": self.source,
            "job_id": self.job_id,
            "title": self.title,
            "url": self.url,
            "location": self.location,
            "posted_at": self.posted_at,
            "description": self.description,
        }
        if self.raw is not None:
            data["raw"] = self.raw
        return data


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def city_path(city_info: dict[str, Any] | None) -> str | None:
    if not city_info:
        return None
    parts: list[str] = []
    node: dict[str, Any] | None = city_info
    while isinstance(node, dict):
        name = node.get("en_name") or node.get("i18n_name") or node.get("name")
        if name:
            parts.append(str(name))
        node = node.get("parent")
    return ", ".join(parts)


def fetch_bytedance(keyword: str, limit: int, max_pages: int) -> Iterable[JobLead]:
    session = make_session()
    url = "https://jobs.bytedance.com/api/v1/public/supplier/search/job/posts"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://joinbytedance.com",
        "Referer": "https://joinbytedance.com/search",
        "accept-language": "en",
        "website-path": "en",
    }
    for page in range(max_pages):
        payload = {
            "keyword": keyword,
            "limit": limit,
            "offset": page * limit,
            "job_category_id_list": [],
            "location_code_list": [],
            "recruitment_id_list": [],
            "subject_id_list": [],
            "tag_id_list": [],
        }
        response = session.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        body = response.json()
        jobs = ((body.get("data") or {}).get("job_post_list")) or []
        if not jobs:
            return
        for job in jobs:
            job_id = str(job.get("id") or "")
            if not job_id:
                continue
            yield JobLead(
                company_key="bytedance",
                source="bytedance_public_supplier",
                job_id=job_id,
                title=str(job.get("title") or ""),
                url=job.get("url")
                or f"https://joinbytedance.com/search/{job_id}",
                location=city_path(job.get("city_info")),
                description=job.get("description"),
                raw=job,
            )
        count = int((body.get("data") or {}).get("count") or 0)
        if count and (page + 1) * limit >= count:
            return


def fetch_mediatek(keyword: str, limit: int, max_pages: int) -> Iterable[JobLead]:
    session = make_session()
    endpoint = "https://careers.mediatek.com/api/trpc/job.getJobs"
    headers = {
        "Accept": "application/json",
        "Referer": "https://careers.mediatek.com/en/jobs",
    }
    for page in range(1, max_pages + 1):
        trpc_input = {
            "json": {
                "locales": "en_US",
                "page": page,
                "jobQueryInfo": {
                    "keywords": [keyword] if keyword else [],
                    "relation": "AND",
                },
                "filters": {
                    "categorys": [],
                    "workExperiences": [],
                    "locations": [],
                    "programs": [],
                },
                "sortBy": "publishedDate",
                "order": "DESC",
                "limit": limit,
            }
        }
        response = session.get(
            endpoint,
            headers=headers,
            params={"input": json.dumps(trpc_input, separators=(",", ":"))},
            timeout=30,
        )
        response.raise_for_status()
        payload = (
            ((response.json().get("result") or {}).get("data") or {}).get("json")
            or {}
        )
        jobs = payload.get("jobs") or []
        if not jobs:
            return
        for job in jobs:
            job_id = str(job.get("id") or "")
            if not job_id:
                continue
            props = job.get("properties") or {}
            location = (props.get("location") or {}).get("code")
            yield JobLead(
                company_key="mediatek",
                source="mediatek_trpc_job_getJobs",
                job_id=job_id,
                title=str(job.get("title") or ""),
                url=f"https://careers.mediatek.com/en/jobs/{job_id}",
                location=location,
                posted_at=job.get("publishedDate"),
                description=job.get("description"),
                raw=job,
            )


def fetch_meta(keyword: str, limit: int, max_pages: int) -> Iterable[JobLead]:
    session = make_session()
    # Meta currently rejects the longer Chrome-like UA with a 400 HTML error,
    # while the shorter UA returns the public GraphQL JSON.
    session.headers["User-Agent"] = "Mozilla/5.0"
    endpoint = "https://www.metacareers.com/graphql"
    emitted = 0
    for page in range(1, max_pages + 1):
        variables = {
            "search_input": {
                "q": keyword or "",
                "divisions": [],
                "offices": [],
                "roles": [],
                "leadership_levels": [],
                "saved_jobs": [],
                "saved_searches": [],
                "sub_teams": [],
                "teams": [],
                "is_leadership": False,
                "is_remote_only": False,
                "sort_by_new": True,
                "page": page,
                "results_per_page": None,
            }
        }
        form = {
            "av": "0",
            "__user": "0",
            "__a": "1",
            "__req": "2",
            "__hs": "19750.BP:DEFAULT.2.0..0.0",
            "dpr": "2",
            "__ccg": "EXCELLENT",
            "__rev": "1011068810",
            "__s": "onwp8s:8wzj16:ug026m",
            "__hsi": "7329001175475786609",
            "__dyn": (
                "7xeUmwkHgmwn8K2Wmhwn84a2i5U4e1Fx-ewSwMxW4E5S2WdwJw5ux60"
                "Vo1upE4W0OE2WxO2O1Vwooa85ufw5Zx61vw4iwBgao881FU2IzXw9S5"
                "ryE3bwkE5G0zE5W0HUvw4Jwp8oxa0YU2ZwrU6C0L836w8i6E3ew"
            ),
            "__csr": "",
            "lsd": "AVrwz4iKI1M",
            "jazoest": "2937",
            "__spin_r": "1011068810",
            "__spin_b": "trunk",
            "__spin_t": "1706416060",
            "__jssesw": "1",
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": "CareersJobSearchResultsQuery",
            "variables": json.dumps(variables, separators=(",", ":")),
            "server_timestamps": "true",
            "doc_id": "9114524511922157",
        }
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.metacareers.com",
            "Referer": "https://www.metacareers.com/jobs/",
            "X-FB-Friendly-Name": "CareersJobSearchResultsQuery",
            "X-FB-LSD": form["lsd"],
        }
        response = session.post(endpoint, data=form, headers=headers, timeout=30)
        response.raise_for_status()
        body = response.text
        if body.startswith("for (;;);"):
            body = body[len("for (;;);") :]
        payload = json.loads(body)
        jobs = (payload.get("data") or {}).get("job_search") or []
        if not jobs:
            return
        for job in jobs:
            job_id = str(job.get("id") or "")
            if not job_id:
                continue
            yield JobLead(
                company_key="meta",
                source="meta_careers_graphql",
                job_id=job_id,
                title=str(job.get("title") or ""),
                url=job.get("url") or f"https://www.metacareers.com/jobs/{job_id}/",
                location=", ".join(job.get("locations") or []) or None,
                raw=job,
            )
            emitted += 1
            if limit > 0 and emitted >= limit:
                return
        if len(jobs) == 0:
            return


def ampere_get(url: str) -> str:
    try:
        from curl_cffi import requests as curl_requests
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "Ampere requires curl_cffi because the site is behind Cloudflare. "
            "Install dependencies from requirements.txt."
        ) from exc
    response = curl_requests.get(
        url,
        timeout=30,
        impersonate="chrome124",
        allow_redirects=True,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    response.raise_for_status()
    return response.text


def title_from_slug(url: str) -> str:
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"^\d+-", "", slug)
    return html.unescape(slug.replace("-", " ")).title()


def ampere_links(document: str) -> list[tuple[str, str]]:
    links: dict[str, str] = {}
    if BeautifulSoup is not None:
        soup = BeautifulSoup(document, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href"))
            if "/jobs/" not in href:
                continue
            if href.startswith("/"):
                href = "https://careers.amperecomputing.com" + href
            if not href.startswith("https://careers.amperecomputing.com/jobs/"):
                continue
            text = " ".join(anchor.get_text(" ", strip=True).split())
            links[href] = text or title_from_slug(href)
    else:
        for href in re.findall(r'href=["\']([^"\']*/jobs/[^"\']+)["\']', document):
            if href.startswith("/"):
                href = "https://careers.amperecomputing.com" + href
            links[href] = title_from_slug(href)
    return sorted(links.items())


def fetch_ampere(keyword: str, limit: int, max_pages: int) -> Iterable[JobLead]:
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        params = {"q": keyword, "location": ""}
        if page > 1:
            params["page"] = str(page)
        url = "https://careers.amperecomputing.com/search/jobs?" + urlencode(params)
        document = ampere_get(url)
        links = ampere_links(document)
        if not links:
            return
        yielded_on_page = 0
        for href, title in links:
            job_id = href.rstrip("/").rsplit("/", 1)[-1].split("-", 1)[0]
            if href in seen:
                continue
            seen.add(href)
            yielded_on_page += 1
            yield JobLead(
                company_key="ampere_computing",
                source="ampere_talemetry_cloudflare_html",
                job_id=job_id,
                title=title,
                url=href,
            )
        if yielded_on_page == 0 or len(seen) >= limit * max_pages:
            return


def fetch_tesla(_: str, __: int, ___: int) -> Iterable[JobLead]:
    try:
        from curl_cffi import requests as curl_requests
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("Tesla probe requires curl_cffi.") from exc
    response = curl_requests.get(
        "https://www.tesla.com/cua-api/apps/careers/state",
        timeout=30,
        impersonate="chrome124",
        headers={"Accept": "application/json"},
    )
    if response.status_code == 200 and response.text.lstrip().startswith("{"):
        payload = response.json()
        listings = payload.get("listings") or payload.get("jobs") or []
        for entry in listings:
            job_id = str(entry.get("id") or entry.get("jobId") or "")
            if not job_id:
                continue
            yield JobLead(
                company_key="tesla",
                source="tesla_cua_api_probe",
                job_id=job_id,
                title=str(entry.get("title") or entry.get("jobTitle") or ""),
                url=f"https://www.tesla.com/careers/search/job/{job_id}",
                location=entry.get("location"),
                raw=entry,
            )
        return
    raise RuntimeError(
        "Tesla returned an Akamai challenge instead of JSON. "
        "Use a challenge-capable browser backend as documented in "
        "docs/job-source-attribution.md."
    )


FETCHERS = {
    "ampere": fetch_ampere,
    "bytedance": fetch_bytedance,
    "mediatek": fetch_mediatek,
    "meta": fetch_meta,
    "tesla": fetch_tesla,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        choices=sorted([*FETCHERS.keys(), "all"]),
        default="all",
    )
    parser.add_argument("--keyword", default="")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--include-raw", action="store_true")
    args = parser.parse_args(argv)

    sources = FETCHERS.keys() if args.source == "all" else [args.source]
    had_error = False
    for source in sources:
        try:
            for lead in FETCHERS[source](args.keyword, args.limit, args.max_pages):
                row = lead.as_json()
                if not args.include_raw:
                    row.pop("raw", None)
                print(json.dumps(row, ensure_ascii=False, sort_keys=True))
        except Exception as exc:
            had_error = True
            print(
                json.dumps(
                    {
                        "source": source,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
