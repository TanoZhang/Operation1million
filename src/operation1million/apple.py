"""Apple's public detail-page evidence, independent of list-page inventory."""
import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .job_text import readable_text
from .job_details import candidate

HYDRATION = re.compile(r'window\.__staticRouterHydrationData\s*=\s*JSON\.parse\(')
DETAIL_FIELDS = {
    'jobSummary': 'summary', 'description': 'description',
    'minimumQualifications': 'minimum_qualifications',
    'preferredQualifications': 'preferred_qualifications',
}


def detail_fields(text, url):
    """Decode captured React Router JSON, never execute script or infer a JD.

    Bind the payload to the exact requested posting, including location suffix.
    An HTML shell, redirect to a search page, or another role supplies no evidence.
    """
    match = re.search(r'/details/([\d-]+)(?:/|$)', urlsplit(url).path)
    if not match:
        raise ValueError('Not an Apple posting URL')
    soup = BeautifulSoup(text, 'html.parser')
    for script in soup.find_all('script'):
        body = script.string or script.get_text()
        marker = HYDRATION.search(body)
        if not marker:
            continue
        encoded, _ = json.JSONDecoder().raw_decode(body[marker.end():].lstrip())
        data = json.loads(encoded)['loaderData']['jobDetails']['jobsData']
        if not isinstance(data, dict):
            raise ValueError('Apple detail job data is absent')
        if data.get('jobNumber') != match.group(1):
            raise ValueError('Apple detail posting does not match requested requisition')
        if not readable_text(data.get('minimumQualifications')):
            raise ValueError('Apple detail has no minimum qualifications')
        return {target: data.get(source) or '' for source, target in DETAIL_FIELDS.items()}
    raise ValueError('Apple detail hydration is absent')


def enrich(collector, db_path=None):
    from .job_details import enrich_inventory

    def read(collector, row):
        with collector.fetch(row['url']) as response:
            return detail_fields(response.text, row['url'])

    return enrich_inventory(collector, db_path, reader=read, provider='apple_jobs',
                            metadata='apple_detail', fields=tuple(DETAIL_FIELDS.values()),
                            evidence='minimum_qualifications', skip_full=False)
