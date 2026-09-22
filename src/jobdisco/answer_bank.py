"""Local answer knowledge: durable JSON, disposable SQLite, no browser writes."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unicodedata
from urllib.parse import urlsplit

from .applications import locked
from .paths import ROOT


TYPES = ('text', 'integer', 'boolean', 'choice', 'multi_choice')
KINDS = ('text', 'number', 'select', 'radio', 'multiselect', 'checkbox')
# Only unambiguous labels are automatic. Bare "name" and "formal name" need
# context, and preferred names are deliberately distinct from legal names.
DEFAULT_FIELDS = {
    'name.first': ('First name', 'text', 'fill', ['First name', 'Given name']),
    'name.last': ('Last name', 'text', 'fill', ['Last name', 'Surname', 'Family name']),
    'name.legal_full': ('Legal full name', 'text', 'fill', ['Legal full name', 'Full legal name']),
    'name.preferred': ('Preferred name', 'text', 'fill', ['Preferred name']),
    'contact.email': ('Email', 'text', 'fill', ['Email', 'Email address']),
    'contact.phone': ('Phone', 'text', 'fill', ['Phone', 'Phone number']),
    'address.street': ('Street address', 'text', 'fill', []),
    'address.city': ('City', 'text', 'fill', []),
    'address.state': ('State', 'choice', 'fill', []),
    'address.postal_code': ('Postal code', 'text', 'fill', []),
    'address.country': ('Country', 'choice', 'fill', []),
    'education.graduation_month': ('Graduation month', 'choice', 'review', []),
    'education.graduation_year': ('Graduation year', 'integer', 'review', []),
    'personal.gender': ('Gender response', 'choice', 'review', []),
    'personal.ethnicity': ('Race or ethnicity response', 'choice', 'review', []),
    'personal.veteran_status': ('Veteran response', 'choice', 'review', []),
    'personal.disability_status': ('Disability response', 'choice', 'review', []),
}


def normalize(label):
    """Cosmetic normalization only: preserve negation and qualifiers."""
    if not isinstance(label, str) or not label.strip():
        raise ValueError('A nonempty question label is required')
    text = unicodedata.normalize('NFKC', label).casefold().strip()
    return re.sub(r'\s+', ' ', text).rstrip(' *:').strip()


def origin(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use an HTTP(S) page URL without credentials')
    port = parsed.port
    host = parsed.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    if port and (parsed.scheme, port) not in (('https', 443), ('http', 80)):
        host += ':' + str(port)
    return parsed.scheme + '://' + host


def _now():
    return datetime.now(timezone.utc).isoformat()


def _validate_answer(field, value):
    if value is None:
        return  # Explicit clearing is supported; None never means "No".
    kind = field['type']
    good = ((kind in ('text', 'choice') and isinstance(value, str) and bool(value.strip()))
            or (kind == 'integer' and type(value) is int)
            or (kind == 'boolean' and type(value) is bool)
            or (kind == 'multi_choice' and isinstance(value, list) and bool(value)
                and all(isinstance(v, str) and v.strip() for v in value)
                and len(set(value)) == len(value)))
    if not good:
        raise ValueError(f'Answer must match field type {kind}')


class AnswerBank:
    """All mutations lock and atomically replace the authoritative JSON file.

    A SQLite view is rebuilt after each write for inspection/integration. Never use
    it to write answers or as the only backup. No personal values are seeded.
    """
    def __init__(self, directory=None):
        self.directory = Path(directory or os.environ.get('JOBDISCO_ANSWERS', ROOT / '.local/autofill'))
        self.path = self.directory / 'answers.json'
        self.index = self.directory / 'answers.sqlite'

    def _read(self):
        if not self.path.exists():
            return {'version': 1, 'fields': {}, 'questions': {}}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or data.get('version') != 1
                or not isinstance(data.get('fields'), dict) or not isinstance(data.get('questions'), dict)):
            raise ValueError('Unsupported or damaged answer bank; preserve it for recovery')
        return data

    def _write(self, data):
        fd, temporary = tempfile.mkstemp(prefix='answers-', suffix='.tmp', dir=self.directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
                json.dump(data, handle, ensure_ascii=True, indent=2, allow_nan=False)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self._build_index(data)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def initialize(self):
        with locked(self.path):
            data = self._read()
            for key, (label, kind, policy, aliases) in DEFAULT_FIELDS.items():
                data['fields'].setdefault(key, dict(label=label, type=kind, policy=policy,
                                                   aliases=aliases, answer=None, updated_at=None))
            self._write(data)
        return {'fields': len(data['fields']), 'questions': len(data['questions'])}

    def add_field(self, key, label, kind='text', policy='review'):
        if not re.fullmatch(r'[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+', key):
            raise ValueError('Use a dotted lowercase field key, for example personal.enrolled')
        normalize(label)
        if kind not in TYPES or policy not in ('fill', 'review'):
            raise ValueError('Invalid field type or policy')
        with locked(self.path):
            data = self._read()
            if key in data['fields']:
                raise ValueError('Field already exists; existing answers were preserved')
            data['fields'][key] = dict(label=label, type=kind, policy=policy, aliases=[],
                                       answer=None, updated_at=None)
            self._write(data)

    def set_answer(self, key, value):
        with locked(self.path):
            data = self._read()
            field = data['fields'][key]
            _validate_answer(field, value)
            field.update(answer=value, updated_at=_now())
            self._write(data)

    def observe(self, label, *, site, section='', kind='text', options=()):
        """Register an encountered heading, then resolve only approved meaning.

        New wording is stored even when no answer is available. Exact built-in
        aliases apply only to ordinary text controls. Personal/custom questions
        require explicit site/section/control/options-specific binding.
        """
        normalized = normalize(label)
        if not isinstance(section, str) or kind not in KINDS:
            raise ValueError('Invalid section or control kind')
        if not isinstance(options, (list, tuple)) or any(not isinstance(v, str) or not v.strip() for v in options):
            raise ValueError('Options must be a list of nonempty display labels')
        if kind in ('select', 'radio', 'multiselect') and not options:
            raise ValueError('Capture the actual options before registering a choice control')
        options = sorted(set(options))
        identity = [origin(site), normalize(section) if section.strip() else '', normalized, kind, options]
        ident = hashlib.sha256(json.dumps(identity, ensure_ascii=True).encode()).hexdigest()
        with locked(self.path):
            data = self._read()
            if ident not in data['questions']:
                candidates = [key for key, f in data['fields'].items()
                              if kind == 'text' and f['type'] == 'text'
                              and identity[1] in ('', 'contact information', 'personal information', 'applicant information', 'about you')
                              and normalized in {normalize(a) for a in f['aliases']}]
                data['questions'][ident] = dict(site=identity[0], section=section, label=label,
                    normalized=normalized, kind=kind, options=options,
                    field_key=candidates[0] if len(candidates) == 1 else None,
                    binding='builtin' if len(candidates) == 1 else None,
                    first_seen=_now(), last_seen=_now(), observations=0)
            question = data['questions'][ident]
            question['last_seen'] = _now()
            question['observations'] += 1
            self._write(data)
            return self._resolve(data, ident)

    def bind(self, question_id, field_key):
        with locked(self.path):
            data = self._read()
            if field_key not in data['fields']:
                raise KeyError(field_key)
            question = data['questions'][question_id]
            if question['field_key'] not in (None, field_key):
                raise ValueError('Question is already bound to a different field')
            question.update(field_key=field_key, binding='confirmed')
            self._write(data)
            return self._resolve(data, question_id)

    def resolve(self, question_id):
        with locked(self.path):
            return self._resolve(self._read(), question_id)

    @staticmethod
    def _resolve(data, ident):
        q = data['questions'][ident]
        result = {'question_id': ident, 'label': q['label'], 'field_key': q['field_key'],
                  'status': 'unknown', 'answer': None}
        if not q['field_key']:
            return result
        field = data['fields'][q['field_key']]
        value = field['answer']
        if value is None:
            return dict(result, status='missing_answer')
        kind = q['kind']
        compatible = ((kind == 'text' and field['type'] == 'text')
                      or (kind == 'number' and field['type'] == 'integer')
                      or (kind in ('select', 'radio') and field['type'] in ('text', 'choice'))
                      or (kind == 'multiselect' and field['type'] == 'multi_choice')
                      or (kind == 'checkbox' and field['type'] == 'boolean'))
        if not compatible:
            return dict(result, status='incompatible_control')
        if kind in ('select', 'radio', 'multiselect'):
            selected = value if isinstance(value, list) else [value]
            if any(v not in q['options'] for v in selected):
                return dict(result, status='option_mismatch')
        if field['policy'] == 'review':
            return dict(result, status='requires_review')
        return dict(result, status='ready', answer=value)

    def pending(self):
        with locked(self.path):
            data = self._read()
            return [dict(question_id=k, **q) for k, q in data['questions'].items() if not q['field_key']]

    def rebuild_index(self):
        """Recreate the SQLite view atomically; never modify the job index."""
        with locked(self.path):
            data = self._read()
            return self._build_index(data)

    def _build_index(self, data):
        fd, temporary = tempfile.mkstemp(prefix='index-', suffix='.sqlite', dir=self.directory)
        os.close(fd)
        try:
            with closing(sqlite3.connect(temporary)) as db, db:
                db.executescript('''
                    CREATE TABLE fields (field_key TEXT PRIMARY KEY, label TEXT, type TEXT,
                        policy TEXT, answer_json TEXT, updated_at TEXT);
                    CREATE TABLE aliases (field_key TEXT, label TEXT);
                    CREATE TABLE questions (question_id TEXT PRIMARY KEY, site TEXT, section TEXT,
                        label TEXT, kind TEXT, options_json TEXT, field_key TEXT, binding TEXT,
                        first_seen TEXT, last_seen TEXT, observations INTEGER);
                    CREATE TABLE metadata (source_sha256 TEXT);
                ''')
                for key, f in data['fields'].items():
                    db.execute('INSERT INTO fields VALUES (?,?,?,?,?,?)',
                               (key, f['label'], f['type'], f['policy'], json.dumps(f['answer']), f['updated_at']))
                    db.executemany('INSERT INTO aliases VALUES (?,?)', [(key, a) for a in f['aliases']])
                for key, q in data['questions'].items():
                    db.execute('INSERT INTO questions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (key, q['site'], q['section'], q['label'], q['kind'], json.dumps(q['options']),
                         q['field_key'], q['binding'], q['first_seen'], q['last_seen'], q['observations']))
                db.execute('INSERT INTO metadata VALUES (?)',
                           (hashlib.sha256(self.path.read_bytes()).hexdigest(),))
            os.replace(temporary, self.index)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return str(self.index)



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    sub.add_parser('pending')
    sub.add_parser('reindex')
    add = sub.add_parser('add-field')
    add.add_argument('key')
    add.add_argument('label')
    add.add_argument('--type', choices=TYPES, default='text')
    add.add_argument('--policy', choices=('fill', 'review'), default='review')
    answer = sub.add_parser('set-answer')
    answer.add_argument('key')
    answer.add_argument('--file', type=Path, required=True, help='UTF-8 JSON value file; avoid answers in shell history')
    observe = sub.add_parser('observe')
    observe.add_argument('label')
    observe.add_argument('--site', required=True)
    observe.add_argument('--section', default='')
    observe.add_argument('--kind', choices=KINDS, default='text')
    observe.add_argument('--options', nargs='*', default=[])
    bind = sub.add_parser('bind')
    bind.add_argument('question_id')
    bind.add_argument('field_key')
    resolve = sub.add_parser('resolve')
    resolve.add_argument('question_id')
    args = parser.parse_args(argv)
    bank = AnswerBank(args.directory)
    try:
        if args.command == 'init':
            result = bank.initialize()
            result['index'] = str(bank.index)
        elif args.command == 'pending':
            result = bank.pending()
        elif args.command == 'reindex':
            result = {'index': bank.rebuild_index()}
        elif args.command == 'add-field':
            bank.add_field(args.key, args.label, args.type, args.policy)
            result = {'field_key': args.key, 'status': 'created'}
        elif args.command == 'set-answer':
            bank.set_answer(args.key, json.loads(args.file.read_text(encoding='utf-8')))
            result = {'field_key': args.key, 'status': 'saved'}
        elif args.command == 'observe':
            result = bank.observe(args.label, site=args.site, section=args.section,
                                  kind=args.kind, options=args.options)
        elif args.command == 'bind':
            result = bank.bind(args.question_id, args.field_key)
        else:
            result = bank.resolve(args.question_id)
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f'Answer bank error: {exc}\n')
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
