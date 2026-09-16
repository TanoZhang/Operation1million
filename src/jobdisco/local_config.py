"""Load supported API keys from ignored local configuration without logging."""
import os
from .paths import ROOT


def load_credentials():
    path = ROOT / '.env.local'
    if not path.is_file():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        name, sep, value = line.partition('=')
        name = name.strip()
        if sep and name in {'OPENAI_API_KEY', 'JSEARCH_API_KEY'} and not os.getenv(name):
            os.environ[name] = value.strip().strip('\"\'')
