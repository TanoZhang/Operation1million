"""Repository paths shared by the job discovery package."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
CONFIG = DATA / 'config'
RAW = DATA / 'raw'
DB = DATA / 'db' / 'job_discovery.sqlite'
RUNS = ROOT / 'runs'


def latest_run_pointer():
    """Return the relative run id recorded by runs/latest.json."""
    import json
    pointer = RUNS / 'latest.json'
    if not pointer.is_file():
        return None
    return json.loads(pointer.read_text(encoding='utf-8')).get('run_id')
