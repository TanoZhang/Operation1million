"""Build private split autofill files and export them without personal defaults."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRECTORY = ROOT / '.local/autofill/data'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.autofill-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def combine(directory):
    profile = read_json(directory / 'profile.json')
    questions = read_json(directory / 'questions.json')
    if profile.get('version') != 1 or not isinstance(profile.get('fields'), dict):
        raise ValueError('Invalid profile version or fields')
    if questions.get('version') != 1 or not isinstance(questions.get('questions'), dict):
        raise ValueError('Invalid questions version or questions')
    for key, field in profile['fields'].items():
        if not isinstance(field, dict) or field.get('type') not in ('text', 'integer', 'boolean', 'choice', 'multi_choice'):
            raise ValueError(f'Invalid field definition: {key}')
    profile['questions'] = questions['questions']
    for key, question in profile['questions'].items():
        if question.get('field_key') and question['field_key'] not in profile['fields']:
            raise ValueError(f'Question references unknown field: {key}')
    return profile


def initialize(directory, sources):
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError('Data directory is not empty; initialization will not overwrite it')
    combined = {'version': 1, 'fields': {}, 'questions': {}}
    conflicts = []
    provenance = {}
    for source in sources:
        data = read_json(source)
        if data.get('version') != 1 or not isinstance(data.get('fields'), dict) or not isinstance(data.get('questions'), dict):
            raise ValueError(f'Invalid source profile: {source.name}')
        for collection in ('fields', 'questions'):
            for key, value in data[collection].items():
                if key not in combined[collection]:
                    combined[collection][key] = value
                    provenance[f'{collection}.{key}'] = str(source)
                elif combined[collection][key] != value:
                    conflicts.append({'collection': collection, 'key': key,
                                      'retained': combined[collection][key], 'alternative': value,
                                      'alternative_source': str(source)})
        for key, value in data.items():
            if key in ('version', 'fields', 'questions'):
                continue
            if key not in combined:
                combined[key] = value
            elif combined[key] != value:
                conflicts.append({'collection': 'profile', 'key': key,
                                  'retained': combined[key], 'alternative': value,
                                  'alternative_source': str(source)})
    question_data = {'version': 1, 'questions': combined.pop('questions')}
    # Exact originals are retained privately, including fields absent from the current UI.
    original_data = [{'path': str(source), 'document': read_json(source)} for source in sources]
    write_json(directory / 'profile.json', combined)
    write_json(directory / 'questions.json', question_data)
    write_json(directory / 'sources.json', {'sources': original_data, 'provenance': provenance})
    write_json(directory / 'conflicts.json', {'conflicts': conflicts})
    stamp = datetime.now(timezone.utc).isoformat()
    (directory / 'history.jsonl').write_text(json.dumps({'at': stamp, 'actor': 'codex',
        'action': 'initialize-from-existing-files', 'sources': [str(source) for source in sources],
        'conflicts': len(conflicts)}) + '\n', encoding='utf-8')
    schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema',
              'title': 'Private autofill split files',
              'oneOf': [
                  {'type': 'object', 'required': ['version', 'fields'], 'properties': {
                      'version': {'const': 1}, 'fields': {'type': 'object', 'additionalProperties': {
                          'type': 'object', 'required': ['label', 'type', 'policy'], 'properties': {
                              'label': {'type': 'string'},
                              'type': {'enum': ['text', 'integer', 'boolean', 'choice', 'multi_choice']},
                              'policy': {'enum': ['fill', 'review']}}}}}},
                  {'type': 'object', 'required': ['version', 'questions'], 'properties': {
                      'version': {'const': 1}, 'questions': {'type': 'object', 'additionalProperties': {
                          'type': 'object', 'required': ['label', 'site', 'kind', 'options']}}}}]}
    write_json(directory / 'schema.json', schema)
    (directory / 'README.md').write_text(README, encoding='utf-8')
    combine(directory)
    return len(combined['fields']), len(question_data['questions']), len(conflicts)


README = '''# Private autofill data — instructions for Muse and other assistants

This folder is the editable source for future personal-answer updates. Read
profile.json and questions.json first. These are UTF-8 JSON, version 1.
schema.json describes their structure. sources.json holds exact original files
and provenance; conflicts.json preserves differing source entries. No source
file was deleted. Unanswered facts must stay null; do not guess personal facts.

## Files and update rules

- profile.json: fields (stable canonical keys), facts, conditions, education and
  other existing profile properties. Do not erase unknown keys.
- questions.json: exact question-to-field mappings and site/position constraints.
- history.jsonl: append one JSON object per change, with at (UTC ISO timestamp),
  actor, action, changed keys, and before/after values. Never rewrite old lines.
- sources.json: archival migration source; do not edit it as a working profile.
- conflicts.json: unresolved alternatives; preserve until the user decides.

Use the existing field representation: label, type, policy, aliases, answer,
updated_at, and optional reuse_scope, source_site, source_position_id,
context_answers. Retain exact question wording, negation, country and time.
Do not broaden an answer's scope. Keep current authorization, current sponsorship,
future sponsorship and now-or-future sponsorship separate. Contextual answers
require the actual position's confirmed work route. Never infer these answers.
School, degree, major and dates are separate. Add stable IDs to new education
and employment array records; never select a form row solely by its order.
LLM drafts are not confirmed facts. Ask the user about conflicts or missing facts.

Read the latest files before editing. Use a temporary file and atomic replacement
for JSON writes. Serialize edits: this folder does not provide a cross-agent lock
service. Append history after saving a confirmed change. Keep everything private.
Fill only known matching answers, preserve existing form values, and leave
submission, agreements and file uploads to the user unless separately authorized.

## Browser usage

After Muse edits these files, build an importable memory file from the repository:

    .venv/Scripts/python.exe application-autofill/data-files.py export

This writes memory-for-extension.json in this folder. Use the extension settings
button "Import confirmed memory JSON" to import it. Existing browser answers
are not overwritten on conflict: resolve their confirmed value in settings.
This command does not automatically sync browser storage or Python answers.json.
For a browser snapshot, export to browser-memory.json separately. Do NOT select
profile.json, questions.json or memory-for-extension.json as the extension's
continuous output target: that feature writes a browser-owned snapshot.

Muse can read and edit this directory only if its environment has access to it.
If Muse runs remotely, provide these files using its supported transfer tools.
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init', 'validate', 'export'))
    parser.add_argument('--directory', type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument('--source', type=Path, action='append')
    args = parser.parse_args()
    if args.action == 'init':
        sources = args.source or [ROOT / 'application-autofill/extension/local-profile.json',
                                  ROOT / '.local/autofill/answers.json']
        fields, questions, conflicts = initialize(args.directory, sources)
        print(f'Initialized: {fields} fields, {questions} questions, {conflicts} preserved alternatives.')
    else:
        profile = combine(args.directory)
        if args.action == 'export':
            history = [json.loads(line) for line in (args.directory / 'history.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
            profile['data_file_history'] = history
            write_json(args.directory / 'memory-for-extension.json', {
                'format': 'jobdisco-autofill-memory', 'schema_version': 1,
                'exported_at': datetime.now(timezone.utc).isoformat(),
                'profile': profile, 'pending_captures': {}})
        print(f'{args.action}: {len(profile["fields"])} fields, {len(profile["questions"])} questions; no values printed.')


if __name__ == '__main__':
    main()
