"""One explicitly authorized continuation from an exact retained discovery.

This helper cannot approve evidence, reset a ledger, or discover replacement
material. It reserves the allowance before submission and rejects later replay.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from release_core import digest, read_json

METHOD = 'retained-discovery-continuation-v1'
MARKER = 'retained-discovery-continuation-used.json'


def _bytes(path: Path) -> bytes:
    if (not path.is_file() or path.is_symlink() or any(p.is_symlink() for p in path.parents)
            or path.stat().st_size > 2 * 1024 * 1024):
        raise RuntimeError('Retained discovery prerequisite is missing or unsafe')
    return path.read_bytes()


def _verify(cache, binding, engine, load, observe):
    cache = Path(cache)
    expected = binding.get('edition_date')
    if not isinstance(expected, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', expected):
        raise RuntimeError('Invalid retained discovery continuation date')
    if cache.name != expected or binding.get('engine') != engine:
        raise RuntimeError('Retained discovery continuation context differs')
    for key in ('identity', 'discovery_file_sha256', 'discovery_value_sha256', 'attempt_ledger_sha256'):
        if not isinstance(binding.get(key), str) or not re.fullmatch(r'[a-f0-9]{64}', binding[key]):
            raise RuntimeError('Invalid retained discovery continuation binding')
    ledger = _bytes(cache / 'attempts.json')
    attempts = json.loads(ledger).get('attempts')
    if type(attempts) is not int or attempts != 2 or digest(ledger) != binding['attempt_ledger_sha256']:
        raise RuntimeError('Original research attempt ledger differs')
    path = cache / engine / 'discovery.json'
    if digest(_bytes(path)) != binding['discovery_file_sha256']:
        raise RuntimeError('Retained discovery file differs from authorization')
    discovery = load(path, binding['identity'])
    if (not isinstance(discovery, dict) or not isinstance(discovery.get('notes'), str)
            or not discovery['notes'].strip() or not discovery.get('web_search_items')
            or digest(json.dumps(discovery, sort_keys=True, ensure_ascii=False)) != binding['discovery_value_sha256']):
        raise RuntimeError('Retained discovery value differs from authorization')
    observe(discovery)  # Preserve the real observed-source and allowed-domain gate.
    return discovery


def reserve(cache, expected, plan, engine, load, observe):
    required = {'continuation_method': METHOD, 'edition_date': expected, 'engine': engine,
                'maximum_retained_discovery_continuations': 1,
                'maximum_additional_generation_attempts': 1,
                'publication_authorized': False, 'new_discovery_prohibited': True,
                'research_counter_reset': False, 'validation_override': False}
    if any(type(plan.get(k)) is not type(v) or plan.get(k) != v for k, v in required.items()):
        raise RuntimeError('Invalid retained discovery continuation authorization')
    cache = Path(cache)
    if (cache / MARKER).exists():
        return False
    _verify(cache, plan, engine, load, observe)
    # A new candidate or an editorial rejection needs its own appropriate path.
    if any((cache / engine / (n + '.json')).exists() for n in ('sources', 'reporting', 'narration')):
        return False
    if any((cache / name).exists() for name in
           ('approved.json', 'audit.json', 'audit-bound.json', 'corrective-generation-used.json')):
        return False
    if (cache / 'editorial-loop-v1').exists() or any((cache / 'candidates').glob('*.json')):
        return False
    failure = json.loads(_bytes(cache / 'validation-research-response.json'))
    if (failure.get('edition_date') != expected or failure.get('stage') != 'research-response'
            or failure.get('run_id') != plan.get('failure_run_id')
            or failure.get('passed') is not False or failure.get('exception_category') != 'ValueError'):
        raise RuntimeError('Retained source-selection failure does not match authorization')
    marker = {k: plan[k] for k in required}
    marker.update({k: plan[k] for k in
                   ('identity', 'discovery_file_sha256', 'discovery_value_sha256', 'attempt_ledger_sha256')})
    marker.update(schema_version=1, failure_run_id=plan['failure_run_id'],
                  original_attempt_ledger_unchanged=True,
                  authorization_sha256=digest(json.dumps(plan, sort_keys=True, ensure_ascii=False)),
                  reserved_at=datetime.now(timezone.utc).isoformat(),
                  run_id=os.getenv('GITHUB_RUN_ID', 'local'))
    try:
        with (cache / MARKER).open('x', encoding='utf-8') as f:
            json.dump(marker, f, indent=2)
    except FileExistsError:
        return False
    return True


def requires_bound_cache(cache, expected, policy_root, engine, load, observe):
    plan = read_json(Path(policy_root) / (expected + '.json'), {})
    if 'continuation_method' not in plan:
        return False
    if plan['continuation_method'] != METHOD or plan.get('edition_date') != expected:
        raise RuntimeError('Invalid retained discovery continuation authorization')
    # Run before the publisher's default empty-ledger handling. Cache loss must
    # never silently restore an ordinary first attempt for an authorized recovery.
    _verify(cache, plan, engine, load, observe)
    return True


def assert_bound(cache, engine, identity, load, observe):
    path = Path(cache) / MARKER
    if not path.exists():
        return False
    marker = json.loads(_bytes(path))
    if (marker.get('continuation_method') != METHOD or marker.get('publication_authorized') is not False
            or marker.get('new_discovery_prohibited') is not True or marker.get('identity') != identity):
        raise RuntimeError('Retained discovery continuation cannot start new discovery')
    _verify(cache, marker, engine, load, observe)
    return True
