"""Repository paths shared by the job discovery package."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
CONFIG = DATA / 'config'
RAW = DATA / 'raw'
DB = DATA / 'db' / 'job_discovery.sqlite'
RUNS = ROOT / 'runs'
