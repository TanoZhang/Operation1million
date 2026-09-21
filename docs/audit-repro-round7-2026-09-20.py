"""Offline paid-intake and Review diagnostics for explicit experience requirements."""
from pathlib import Path
import json
import runpy
from tempfile import TemporaryDirectory
from unittest.mock import patch

from jobdisco import applications, experience, jsearch, store


def main():
    run = runpy.run_path(str(Path(__file__).with_name('audit-repro-round5-2026-09-20.py')))['run']
    cases = {
        'B31_optional_skill_erases_mandatory_years': '5 years experience required, FPGA knowledge preferred.',
        'B32_required_heading_loses_scope': 'Required qualifications:\n3 years of RTL design.',
        'B33_hyphenated_year_unit': 'Minimum 3-year experience in RTL design.',
        'B33_fractional_years': 'Minimum 2.5 years of professional experience.',
    }
    results = {'source': str(Path(experience.__file__).resolve()), 'cases': {}}
    with TemporaryDirectory() as directory, patch('requests.sessions.Session.request',
            side_effect=AssertionError('External HTTP prohibited')):
        root = Path(directory)
        with patch.object(store, 'ROOT', root):
            for name, text in cases.items():
                folder = root / name
                folder.mkdir()
                job = {'job_id': name, 'job_title': 'RTL Engineer', 'employer_name': 'Fixture',
                       'job_apply_link': 'https://example.test/' + name, 'job_description': text}
                assert run(folder, 'collection', [], paid=[job])[0] == 0
                state = applications.queue(folder / 'jobs.sqlite', folder / 'applications.ndjson')
                facts = experience.evaluate('RTL Engineer', text)
                assert facts['effective_experience_years'] is None and not facts['entry_override']
                assert len(state['pending']) == 1
                results['cases'][name] = {'text': text, 'detected_years': None,
                                        'pending_groups': len(state['pending'])}
            # Control both sides of the intended gate using actual paid collection.
            for name, text, expected in [('mandatory_control', '5 years experience required.', 0),
                                         ('optional_control', '5 years experience preferred.', 1),
                                         ('two_year_control', '2 years experience required.', 1)]:
                folder = root / name
                folder.mkdir()
                job = {'job_id': name, 'job_title': 'RTL Engineer', 'employer_name': 'Fixture',
                       'job_apply_link': 'https://example.test/' + name, 'job_description': text}
                assert run(folder, 'collection', [], paid=[job])[0] == 0
                pending = applications.queue(folder / 'jobs.sqlite', folder / 'applications.ndjson')['pending']
                assert len(pending) == expected
            results['controls'] = '5 mandatory rejected; 5 preferred and 2 mandatory accepted'
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
