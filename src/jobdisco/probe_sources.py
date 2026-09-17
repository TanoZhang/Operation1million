from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from .paths import ROOT, RAW
from typing import Any

import requests


OUT_CSV = RAW / "failed_source_probe_results.csv"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)


@dataclass
class Probe:
    company_key: str
    provider: str
    label: str
    method: str
    url: str
    payload: dict[str, Any] | None = None


def probes() -> list[Probe]:
    rows: list[Probe] = []

    for domain, company in [
        ("careers.micron.com", "micron"),
        ("careers.qualcomm.com", "qualcomm"),
    ]:
        rows.extend(
            [
                Probe(company, "eightfold", "eightfold_apply_v2", "GET", f"https://{domain}/api/apply/v2/jobs?domain={domain}&start=0&num=20"),
                Probe(company, "eightfold", "eightfold_apply_v2_search", "GET", f"https://{domain}/api/apply/v2/jobs?domain={domain}&start=0&num=20&query=engineer"),
                Probe(company, "eightfold", "eightfold_app_host_apply_v2", "GET", f"https://app.eightfold.ai/api/apply/v2/jobs?domain={domain}&start=0&num=20"),
                Probe(company, "eightfold", "eightfold_app_host_apply_v2_search", "GET", f"https://app.eightfold.ai/api/apply/v2/jobs?domain={domain}&start=0&num=20&query=engineer"),
                Probe(company, "eightfold", "eightfold_sitemap", "GET", f"https://{domain}/sitemap.xml"),
            ]
        )

    for sub, company in [
        ("careers-amd", "amd"),
    ]:
        base = f"https://{sub}.icims.com"
        rows.extend(
            [
                Probe(company, "icims", "icims_search_iframe", "GET", f"{base}/jobs/search?ss=1&in_iframe=1"),
                Probe(company, "icims", "icims_search_pr", "GET", f"{base}/jobs/search?pr=0&schemaId=&o="),
                Probe(company, "icims", "icims_search_desktop_params", "GET", f"{base}/jobs/search?ss=1&mobile=false&width=1200&height=500&bga=true&needsRedirect=false"),
                Probe(company, "icims", "icims_sitemap", "GET", f"{base}/sitemap.xml"),
                Probe(company, "icims", "icims_jobs_xml_guess", "GET", f"{base}/jobs/search?ss=1&mode=xml"),
            ]
        )

    rows.extend(
        [
            Probe(
                "apple",
                "apple_jobs",
                "apple_locale_role_search_all",
                "GET",
                "https://jobs.apple.com/en-us/api/role/search?location=united-states-USA&page=1&sort=relevance",
            ),
            Probe(
                "apple",
                "apple_jobs",
                "apple_locale_role_search_engineer",
                "GET",
                "https://jobs.apple.com/en-us/api/role/search?search=engineer&location=united-states-USA&page=1&sort=relevance",
            ),
            Probe(
                "apple",
                "apple_jobs",
                "apple_role_search_all",
                "GET",
                "https://jobs.apple.com/api/role/search?location=united-states-USA&page=1&sort=relevance",
            ),
            Probe(
                "apple",
                "apple_jobs",
                "apple_role_search_engineer",
                "GET",
                "https://jobs.apple.com/api/role/search?search=engineer&location=united-states-USA&page=1&sort=relevance",
            ),
            Probe(
                "microsoft",
                "microsoft_careers",
                "microsoft_gcs_search_all",
                "GET",
                "https://gcsservices.careers.microsoft.com/search/api/v1/search?lc=United%20States&l=en_us&pg=1&pgSz=20&o=Relevance&flt=true",
            ),
            Probe(
                "microsoft",
                "microsoft_careers",
                "microsoft_gcs_search_engineer",
                "GET",
                "https://gcsservices.careers.microsoft.com/search/api/v1/search?q=engineer&lc=United%20States&l=en_us&pg=1&pgSz=20&o=Relevance&flt=true",
            ),
            Probe(
                "cisco",
                "phenom",
                "cisco_widgets_refine_search_get",
                "GET",
                "https://careers.cisco.com/widgets?lang=en_global&deviceType=desktop&country=global&ddoKey=refineSearch",
            ),
            Probe(
                "cisco",
                "phenom",
                "cisco_widgets_refine_search_post",
                "POST",
                "https://careers.cisco.com/widgets",
                {
                    "ddoKey": "refineSearch",
                    "pageName": "search-results",
                    "siteType": "external",
                    "locale": "en_global",
                    "from": 0,
                    "size": 20,
                    "sortBy": "",
                    "jobs": True,
                    "counts": True,
                    "keywords": "",
                    "all_fields": ["category", "country", "state", "city", "type"],
                },
            ),
        ]
    )

    rows.extend(
        [
            Probe("renesas", "renesas_careers", "renesas_search_path", "GET", "https://jobs.renesas.com/search/?createNewAlert=false&q=&locationsearch="),
            Probe("renesas", "renesas_careers", "renesas_services_search_guess", "GET", "https://jobs.renesas.com/services/search/jobs?locale=en_US&sortBy=postedDate&limit=20&offset=0"),
            Probe("renesas", "renesas_careers", "renesas_sitemap", "GET", "https://jobs.renesas.com/sitemap.xml"),
            Probe("renesas", "renesas_careers", "renesas_vacancies_sitemap", "GET", "https://jobs.renesas.com/vacanciessitemap.xml"),
        ]
    )
    return rows


def summarize(response: requests.Response) -> tuple[str, str, int | str]:
    text = response.text or ""
    lowered = text.lower()
    content_type = response.headers.get("content-type", "")

    if any(term in lowered for term in ["captcha", "human verification", "access denied", "cf-chl", "akamai"]):
        return "blocked", "captcha/challenge/access denied", ""

    if "json" in content_type or text.lstrip().startswith(("{", "[")):
        try:
            data = response.json()
        except Exception:
            return "download_ok", "looks like JSON but parse failed", ""
        count = count_json_items(data)
        evidence = json.dumps(first_json_evidence(data), ensure_ascii=False)[:180]
        return ("usable" if count else "download_ok"), evidence, count

    job_terms = [term for term in ["/job/", "/jobs/", "job-title", "requisition", "position", "opening", "career"] if term in lowered]
    if job_terms:
        return "download_ok", "html signals: " + ", ".join(job_terms[:4]), ""
    return "no_signal", text[:160].replace("\n", " "), ""


def count_json_items(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    if not isinstance(data, dict):
        return 0
    for key in ["jobs", "data", "results", "value", "positions"]:
        value = data.get(key)
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            nested = count_json_items(value)
            if nested:
                return nested
    for value in data.values():
        if isinstance(value, (dict, list)):
            nested = count_json_items(value)
            if nested:
                return nested
    return 0


def first_json_evidence(data: Any) -> Any:
    if isinstance(data, list):
        return data[0] if data else data
    if not isinstance(data, dict):
        return data
    for key in ["jobs", "data", "results", "value", "positions"]:
        value = data.get(key)
        if isinstance(value, list) and value:
            return value[0]
        if isinstance(value, dict):
            nested = first_json_evidence(value)
            if nested:
                return nested
    return {key: data[key] for key in list(data)[:6]}


def main() -> int:
    # Keep historical probes as evidence, but never rerun obsolete endpoint guesses.
    print('Legacy endpoint probing is disabled. Use job-collect --company <key> '
          '--max-pages 1 --max-jobs 10 --jsearch-budget 0 for a guarded check.')
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
