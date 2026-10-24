"""Submit an explicitly reviewed, hash-bound correction to the normal evidence audit.

This is not an approval path. It cannot generate research, reset the daily ledger,
reuse an audit from another draft, or publish without the caller's full audit.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from release_core import read_json, write_json, validate_edition, allowed_url
from release_resume import _read_snapshot

REVIEW_ROOT = Path(__file__).resolve().parents[1] / 'editorial-review'
MAX_BYTES = 1024 * 1024


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def take_retained_reporting_recovery(cache: Path, expected: str, review_root: Path):
    """Submit one reviewed full script from intact reporting, without generation."""
    if expected != '2026-10-24' or Path(cache).name != expected:
        return None
    path = Path(review_root) / (expected + '.json')
    if not path.exists():
        return None
    from release_retained_bluf import _read, _hash, MARKER, POLICY
    from release_prose import validate_prose
    from release_sectioned_narration import METHOD, SECTION_PLAN, fingerprint as section_fingerprint, _ledger
    cache = Path(cache)
    plan = _read(path)
    if plan.get('base_staged_reporting') is not True:
        return None
    required = {'schema_version': 1, 'edition_date': expected, 'failure_run_id': 40106342027,
                'maximum_recoveries': 1, 'publication_authorized': False,
                'additional_research_generation_calls': 0, 'additional_narration_generation_calls': 0}
    if any(plan.get(k) != v for k, v in required.items()):
        raise ValueError('Retained-reporting review metadata is invalid')
    if any((cache / n).exists() for n in ('audit.json', 'audit-bound.json', 'approved.json')):
        return None
    reservation = cache / 'editorial-recovery-attempt.json'
    if reservation.exists() or (cache / 'style-recovery-attempt.json').exists():
        raise RuntimeError('The retained-reporting audit allowance is already reserved')
    original = {}
    for name, sha in plan['retained_file_sha256'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Retained-reporting review path escaped the edition')
        target = cache / relative
        _read(target)
        original[target] = target.read_bytes()
        if _hash(original[target]) != sha:
            raise ValueError('Retained-reporting review prerequisite changed')
    engine = 'staged-research-v3'
    necessary = {'attempts.json', 'api-responses.json', 'validation-latest.json'}
    necessary.update(engine + '/' + n + '.json' for n in ('discovery', 'sources', 'reporting'))
    if not necessary.issubset(plan['retained_file_sha256']):
        raise ValueError('Retained-reporting review omitted original state')
    if _read(cache / 'attempts.json') != {'attempts': 2}:
        raise ValueError('Retained-reporting review cannot reset the research ledger')
    failure = _read(cache / 'validation-latest.json')
    if (failure.get('passed') is not False or str(failure.get('run_id')) != '40106342027'
        or failure.get('rule') != 'narration_section' or failure.get('path') != '/podcast/developments/2'):
        raise ValueError('Retained-reporting review does not match the recorded failure')
    from release_research import _cached, observed_html_urls, validate_source_catalog, reporting_schema, validate_reference_bindings
    from jsonschema import Draft202012Validator
    identity = plan['reporting_identity']
    stages = {n: _cached(cache / engine / (n + '.json'), identity) for n in ('discovery', 'sources', 'reporting')}
    if any(v is None for v in stages.values()):
        raise ValueError('Retained-reporting review identity differs')
    catalog = validate_source_catalog(stages['sources']['sources'], observed_html_urls(stages['discovery']))
    report = stages['reporting']['edition']
    Draft202012Validator(reporting_schema(catalog, expected)).validate(report)
    validate_reference_bindings(report, catalog)
    sid = section_fingerprint({'method': METHOD, 'identity': identity, 'model': plan['model'],
                               'reporting': report, 'plan': SECTION_PLAN})
    ledger = cache / engine / METHOD / sid / 'attempts.json'
    if str(ledger.relative_to(cache)) not in plan['retained_file_sha256']:
        raise ValueError('Retained-reporting review omitted the section ledger')
    state = _ledger(ledger, sid, {'bluf-None': 2})
    if (state['requests'] != 10 or state['attempts'] != {'opening-None': 2, 'bluf-None': 4,
        'developments-0': 1, 'developments-1': 1, 'developments-2': 2}):
        raise ValueError('Retained-reporting review cannot change spent section requests')
    prior = _read(cache / MARKER)
    prior_policy = Path(review_root).parent / 'repair-authorizations' / POLICY
    if (prior.get('publication_authorized') is not False or prior.get('identity') != identity
        or prior.get('policy_sha256') != _hash(prior_policy.read_bytes())):
        raise ValueError('Retained-reporting review lost the prior recovery binding')
    candidate = plan['candidate']
    if fingerprint(candidate) != plan.get('candidate_sha256'):
        raise ValueError('Retained-reporting review checksum differs')
    validate_edition(candidate, expected)
    for name, index, count in SECTION_PLAN:
        passage = candidate['podcast'][name] if index is None else candidate['podcast'][name][index]
        validate_prose({'text': passage}, count)
    urls = plan.get('reviewed_source_urls')
    if (not isinstance(urls, list) or set(urls) != {s['url'] for s in candidate['sources']}
        or not all(allowed_url(url) for url in urls)):
        raise ValueError('Retained-reporting reviewed evidence inventory differs')
    from release_diagnostics import redact
    if redact(candidate) != candidate:
        raise ValueError('Retained-reporting review failed credential screening')
    record = {**required, 'base_reporting_sha256': fingerprint(report),
              'candidate_sha256': plan['candidate_sha256'], 'evidence_audit_reserved': True,
              'original_research_and_section_ledgers_unchanged': True,
              'source_of_correction': 'Assistant editorial review under user recovery request'}
    try:
        with reservation.open('x', encoding='utf-8') as f:
            json.dump(record, f, indent=2)
    except FileExistsError:
        raise RuntimeError('The retained-reporting audit allowance is already reserved') from None
    if any(target.read_bytes() != data for target, data in original.items()):
        raise RuntimeError('Retained-reporting review changed an original record')
    return candidate, set()


def take_reviewed_recovery(cache: Path, expected: str):
    retained = take_retained_reporting_recovery(cache, expected, REVIEW_ROOT)
    if retained is not None:
        return retained
    from release_audit_search import take_tool_omission_recovery
    retry = take_tool_omission_recovery(cache, expected, REVIEW_ROOT.parent / 'audit-tool-recovery')
    if retry is not None:
        return retry
    from release_claim_correction import take_claim_correction
    corrected = take_claim_correction(cache, expected, REVIEW_ROOT.parent / 'claim-review')
    if corrected is not None:
        return corrected
    path = REVIEW_ROOT / (expected + '.json')
    if not path.exists():
        from release_reference_repair import take_reference_repair
        return take_reference_repair(cache, expected, REVIEW_ROOT.parent / 'source-recovery')
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('Reviewed correction file is unsafe or oversized')
    plan = read_json(path)
    if (plan.get('schema_version') != 1 or plan.get('edition_date') != expected
            or plan.get('publication_authorized') is not False):
        raise ValueError('Reviewed correction metadata is invalid; it cannot authorize publication')
    relative = plan.get('base_snapshot', '')
    stage = plan.get('base_stage', 'content')
    if stage not in ('content','generated'):
        raise ValueError('Reviewed correction stage is invalid')
    parts = Path(relative).parts
    if (len(parts) != 2 or parts[0] != 'candidates' or '..' in parts
            or not parts[1].startswith(stage+'-') or (cache / 'candidates').is_symlink()):
        raise ValueError('Reviewed correction base path is invalid')
    snapshot = _read_snapshot(cache / relative, expected, stage)
    if not snapshot or snapshot['candidate_sha256'] != plan.get('base_candidate_sha256'):
        raise ValueError('Reviewed correction does not match the retained draft')
    candidate = plan.get('candidate')
    if fingerprint(candidate) != plan.get('candidate_sha256'):
        raise ValueError('Reviewed correction checksum mismatch')
    validate_edition(candidate, expected)
    urls = plan.get('reviewed_source_urls')
    if (not isinstance(urls, list) or set(urls) != {s['url'] for s in candidate['sources']}
            or not all(allowed_url(u) for u in urls)):
        raise ValueError('Reviewed correction evidence inventory mismatch')
    reservation = cache / 'editorial-recovery-attempt.json'
    if reservation.exists() or (cache / 'style-recovery-attempt.json').exists():
        raise RuntimeError('The retained-draft audit allowance is already reserved; no additional API call was made')
    write_json(reservation, {'edition_date': expected,
        'base_candidate_sha256': snapshot['candidate_sha256'],
        'candidate_sha256': plan['candidate_sha256'], 'evidence_audit_reserved': True,
        'publication_authorized': False, 'additional_research_generation_calls': 0,
        'source_of_correction': 'Explicit assistant editorial review under user deployment request',
        'reviewed_source_count': len(urls)})
    # The live auditor must retrieve all cited sources. Operator-supplied URLs
    # are deliberately NOT represented as API retrieval provenance.
    return candidate, set()

