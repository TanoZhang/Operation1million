"""Read-only employer alias report. Domain coincidences are leads, not merges."""
import argparse
from collections import defaultdict
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import urlsplit

from . import employers
from .paths import DB


def report(rows):
    names, domains = defaultdict(set), defaultdict(set)
    for row in rows:
        name = row['name'] or ''
        if not isinstance(name, str):
            continue
        if not name:
            continue
        identity = employers.identity(name)
        names[identity].add(name)
        website = row.get('website') or ''
        if not isinstance(website, str):
            website = ''
        try:
            host = urlsplit(website if '://' in website else 'https://' + website).hostname
        except ValueError:
            host = None
        if host and '.' in host and not any(char.isspace() for char in host):
            domains[host.removeprefix('www.')].add(identity)
    labels = employers.display_names(name for values in names.values() for name in values)
    return {
        'identities': len(names),
        'aliases': [{'identity': key, 'display': labels[key], 'names': sorted(values)}
                    for key, values in sorted(names.items()) if len(values) > 1],
        'unregistered': [{'identity': key, 'display': labels[key], 'names': sorted(values)}
                         for key, values in sorted(names.items())
                         if not any(employers._plain(name) in employers.ALIASES for name in values)],
        'domain_candidates': [{'reported_domain': domain, 'identities': sorted(keys)}
                              for domain, keys in sorted(domains.items()) if len(keys) > 1],
    }


def inspect(db_path):
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        # Aggregate before Python; neither job details nor application records
        # are needed. Use all open inventory, not only jobs surviving filters.
        rows = db.execute('''SELECT DISTINCT
            COALESCE(c.name, json_extract(j.raw, '$.employer_name'), j.company_key) AS name,
            json_extract(j.raw, '$.employer_website') AS website
            FROM jobs j LEFT JOIN companies c USING(company_key)
            WHERE j.closed_at IS NULL''')
        return report(dict(row) for row in rows)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='company-audit-', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=True, indent=2)
            handle.write('\n')
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DB)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.db)
    write(args.output, result)
    print(f"Company audit: {result['identities']} identities, "
          f"{len(result['domain_candidates'])} domain candidates; no automatic merges")


if __name__ == '__main__':
    main()
