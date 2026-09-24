"""Refresh the ignored extension seed from the workstation answer bank."""

import argparse
import json
import os
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / '.local' / 'autofill' / 'answers.json'
DEFAULT_TARGET = Path(__file__).resolve().parent / 'extension' / 'local-profile.json'


def copy_profile(source, target):
    data = json.loads(Path(source).read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or data.get('version') != 1
            or not isinstance(data.get('fields'), dict)
            or not isinstance(data.get('questions'), dict)):
        raise ValueError('Unsupported or damaged answer profile')
    target = Path(target)
    descriptor, temporary = tempfile.mkstemp(prefix='profile-', suffix='.json', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(data, handle, ensure_ascii=True, separators=(',', ':'))
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return len(data['fields']), len(data['questions'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--target', type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args(argv)
    fields, questions = copy_profile(args.source, args.target)
    print(f'Prepared local extension profile: {fields} fields, {questions} questions.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
