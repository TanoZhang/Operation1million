"""Offline optimization experiments; never patch application source or real data.

Run: python docs/review-benchmark-2026-09-23.py
Prototypes are compiled in separate namespaces. Exact outputs and existing
description/ranking tests must agree before timings are printed.
"""
import copy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import inspect
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from types import FunctionType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
from jobdisco import job_text, ranking, review
import test_review_description as description_tests


def description_prototype():
    """Reuse selection's parsed text without altering the public return tuple."""
    namespace = vars(job_text).copy()
    helper = inspect.getsource(job_text._with_qualifications)
    helper = helper.replace('def _with_qualifications(description, raw):',
                            'def _with_qualifications(description, raw, plain=None):')
    helper = helper.replace('[readable_text(description)]',
                            '[plain if plain is not None else readable_text(description)]')
    selection = inspect.getsource(job_text.display_description)
    selection = selection.replace('if readable_text(value):', 'if (plain := readable_text(value)):')
    selection = selection.replace('_with_qualifications(value, raw)',
                                  '_with_qualifications(value, raw, plain)')
    exec(compile(helper + '\n' + selection, '<description prototype>', 'exec'), namespace)
    return namespace['display_description']


def order_prototype(groups):
    """Per-sort bounded caches; preserve original rank computation and ordering."""
    namespace = vars(ranking).copy()
    for name in ('bucket', 'posted_day', '_seconds'):
        original = namespace[name]
        cached = lru_cache(maxsize=4096)(original)
        def reuse(value, original=original, cached=cached):
            # Existing date helpers accept values that are not hashable.
            return cached(value) if isinstance(value, str) else original(value)
        namespace[name] = reuse
    key = FunctionType(ranking.rank.__code__, namespace, ranking.rank.__name__,
                       ranking.rank.__defaults__, ranking.rank.__closure__)
    return sorted(groups, key=key)


def timing_pair(baseline, candidate, rounds=5):
    before, after = [], []
    for index in range(rounds):
        pair = ((baseline, before), (candidate, after))
        for function, results in pair if index % 2 == 0 else reversed(pair):
            start = perf_counter()
            function()
            results.append(perf_counter() - start)
    old, new = median(before), median(after)
    return {'baseline_ms': round(old * 1000, 3), 'prototype_ms': round(new * 1000, 3),
            'speedup': round(old / new, 3), 'rounds': rounds}


def main():
    optimized = description_prototype()
    html = '<h2>RTL design</h2>' + '<p>Build <strong>UVM</strong> blocks &amp; verify RTL.</p>' * 45
    samples = [None, {}, {'description': ''}, {'description': '<p></p>'},
               {'description': 'Use vector<T> &amp; RTL.'},
               {'description': html},
               {'description': html, 'requirements': ['BS in EE', 'SystemVerilog']},
               {'description': html, 'requirements': {'skills': ['UVM', ['RTL']], 'count': 2}},
               {'descriptionTeaser': 'RTL teaser', 'responsibilities': 'Build blocks'},
               {'requirements': 'BS in EE', 'jsearch': {'job_description': html}},
               {'description': 'Python preferred', 'required_qualifications': 'Python'},
               {'description': html, 'descriptionTeaser': html},
               {'requirements': [True, False, 0, 4, {'nested': ['vector<T>', None]}]}]
    preserved = copy.deepcopy(samples)
    for raw in samples:
        before, after = job_text.display_description(raw), optimized(raw)
        assert before == after, (before, after)
        assert job_text.readable_text(before[0]) == job_text.readable_text(after[0])
    assert samples == preserved

    # Existing HTTP/storage tests exercise the real endpoint with the prototype.
    suite = unittest.defaultTestLoader.loadTestsFromModule(description_tests)
    suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_ranking.py'))
    with patch.object(review, 'display_description', optimized), \
            patch.object(description_tests, 'display_description', optimized), \
            patch.object(ranking, 'order', order_prototype):
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)

    output = {'source': str(Path(job_text.__file__).resolve()),
              'existing_tests': result.testsRun, 'exact_description_cases': len(samples),
              'description': {}, 'sorting': {}}
    for label, raw in (('html_with_qualifications', samples[6]), ('html_without_qualifications', samples[5])):
        def details(function):
            for _ in range(100):
                value, kind = function(raw)
                job_text.readable_text(value)
        output['description'][label] = timing_pair(
            lambda: details(job_text.display_description), lambda: details(optimized))

    # Count parser calls separately, excluding instrumentation from timing.
    raw = samples[6]
    for label, function in (('baseline', job_text.display_description), ('prototype', optimized)):
        with patch.object(job_text, 'BeautifulSoup', wraps=job_text.BeautifulSoup) as parser:
            job_text.readable_text(function(raw)[0])
            output['description'][label + '_html_parses'] = parser.call_count

    for profile, distinct_titles in (('repeated_titles', 25), ('unique_titles', 2000),
                                     ('unique_titles_and_timestamps', 2000)):
        groups = [{'id': str(i), 'title': 'RTL Design Engineer ' + str(i % distinct_titles),
                   'confidence': i % 101, 'jobs': [{'posted_at': '2026-09-%02d' % (1 + i % 20),
                                                 'first_seen': '2026-09-22T12:%02d:00+00:00' % (i % 10)}]}
                  for i in range(2000)]
        if profile == 'unique_titles_and_timestamps':
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            for i, group in enumerate(groups):
                group['jobs'][0]['posted_at'] = (start + timedelta(days=i)).isoformat()
                group['jobs'][0]['first_seen'] = (start + timedelta(seconds=i)).isoformat()
        groups.extend([{'id': 'missing', 'jobs': []},
                       {'id': 'odd-date', 'title': 'RTL Intern', 'jobs': [{'posted_at': []}]}])
        original = copy.deepcopy(groups)
        assert ranking.order(groups) == order_prototype(groups)
        assert groups == original
        output['sorting'][profile] = dict(timing_pair(
            lambda: ranking.order(groups), lambda: order_prototype(groups)), groups=len(groups))
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
