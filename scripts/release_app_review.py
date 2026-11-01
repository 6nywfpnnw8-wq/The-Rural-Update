"""One reviewed local correction followed by the existing final app audit.

An incomplete review is never approval or automatic correction authority. A
committed, date-scoped plan binds the original draft, response, evidence, and
research ledger. No original checkpoint is edited and no generation is requested.
The caller must independently retrieve all sources and use its reserved final slot.
"""
from __future__ import annotations
import copy
import json
import re
from datetime import date
from pathlib import Path
from release_core import digest, read_json, write_json, validate_edition
from release_editorial import fingerprint
from release_publication import app_only
from release_diagnostics import Diagnostics, redact

METHOD = 'reviewed-incomplete-app-v1'


def _read(path):
    path = Path(path)
    if (path.is_symlink() or any(p.is_symlink() for p in path.parents)
            or not path.is_file() or path.stat().st_size > 2097152):
        raise ValueError('Unsafe app review continuation checkpoint')
    return read_json(path)


def prepare(edition, cache, policy_root):
    """Return a reviewed candidate and feedback, or None on the ordinary path."""
    cache = Path(cache); day = edition['edition_date']
    path = Path(policy_root) / (day + '.json')
    if not path.exists(): return None
    policy = _read(path)
    required = {'schema_version': 1, 'edition_date': day, 'method': METHOD,
                'maximum_total_audit_requests': 2, 'use_existing_slot': 'final',
                'additional_research_generation_calls': 0,
                'additional_reporting_generation_calls': 0,
                'additional_correction_generation_calls': 0,
                'research_counter_reset': False, 'podcast_generation_permitted': False,
                'independent_full_source_review_required': True,
                'publication_authorized': False}
    if (not app_only(day) or cache.name != day or not isinstance(policy, dict)
            or any(type(policy.get(k)) is not type(v) or policy.get(k) != v
                   for k, v in required.items())):
        raise ValueError('Invalid app review continuation policy')
    count = policy.get('original_research_attempts')
    if type(count) is not int or not 1 <= count <= 2:
        raise ValueError('Invalid original app research count')
    ledger = _read(cache / 'attempts.json')
    if ledger != {'attempts': count}:
        raise ValueError('App continuation cannot reset research attempts')
    folder = cache / 'editorial-loop-v1'
    original = _read(folder / 'original.json')
    base_sha = fingerprint(edition)
    if (original.get('candidate') != edition or original.get('candidate_sha256') != base_sha
            or base_sha != policy.get('base_candidate_sha256')
            or original.get('edition_date') != day
            or original.get('publication_authorized') is not False):
        raise ValueError('App continuation original candidate differs')
    saved = _read(folder / 'initial-result.json')
    reserved = _read(folder / 'initial-reserved.json')
    review = saved.get('value')
    if (not isinstance(review, dict) or review.get('review_complete') is not False
            or fingerprint(review) != saved.get('value_sha256')
            or saved.get('value_sha256') != policy.get('initial_review_sha256')
            or saved.get('payload_sha256') != policy.get('initial_request_sha256')
            or reserved.get('payload_sha256') != policy.get('initial_request_sha256')
            or str(reserved.get('run_id')) != str(policy.get('failure_run_id'))
            or reserved.get('publication_authorized') is not False):
        raise ValueError('App continuation incomplete review identity differs')
    # The initial review may have invalid quotation anchors. It is retained as
    # unapproved feedback, never passed off as a valid completed review.
    if any(p.name not in {'initial-reserved.json', 'final-reserved.json'}
           for p in folder.glob('*-reserved.json')):
        raise ValueError('App continuation cannot expand spent correction slots')
    if any((cache / n).exists() for n in ('audit.json', 'audit-bound.json', 'approved.json')):
        raise ValueError('App continuation cannot replace a completed audit')
    evidence_path = cache / 'staged-research-v3/evidence-coverage-v2/sources.json'
    evidence = _read(evidence_path)
    if digest(evidence_path.read_bytes()) != policy.get('coverage_evidence_file_sha256'):
        raise ValueError('App continuation original evidence differs')
    from release_research import _cached
    evidence = _cached(evidence_path, policy.get('coverage_evidence_identity'))
    if evidence is None: raise ValueError('App continuation evidence context differs')
    documents = evidence['documents']
    from release_coverage_plan import validate_documents, validate_plan, references
    validate_documents(documents, edition['sources'])
    coverage = policy.get('coverage_plan')
    validate_plan(coverage, edition['sources'], documents)
    patches = policy.get('replacements')
    if not isinstance(patches, list) or not 1 <= len(patches) <= 40:
        raise ValueError('App continuation has no bounded reviewed corrections')
    from release_audit_loop import editable
    candidate = copy.deepcopy(edition); seen = set()
    for patch in patches:
        if not isinstance(patch, dict) or set(patch) != {'path', 'before', 'after'}:
            raise ValueError('Invalid reviewed app replacement')
        pointer = patch['path']
        prose = isinstance(pointer, str) and editable(pointer)
        metadata = isinstance(pointer, str) and re.fullmatch(r'/sources/[0-9]+/published_date', pointer)
        signal = isinstance(pointer, str) and re.fullmatch(r'/signals/[0-3]/(?:id|source_ids)', pointer)
        if not (prose or metadata or signal) or pointer in seen:
            raise ValueError('Unreviewable or duplicate app replacement path')
        parts = pointer.split('/')[1:]; owner = candidate
        for part in parts[:-1]: owner = owner[int(part)] if isinstance(owner, list) else owner[part]
        key = int(parts[-1]) if isinstance(owner, list) else parts[-1]
        if owner[key] != patch['before'] or patch['before'] == patch['after']:
            raise ValueError('Stale or unchanged reviewed app replacement')
        if prose and (not isinstance(patch['after'], str) or not patch['after'].strip()
                      or len(patch['after']) > 12000):
            raise ValueError('Invalid reviewed app prose')
        if metadata and patch['after'] is not None:
            if date.fromisoformat(patch['after']) > date.fromisoformat(day):
                raise ValueError('Future reviewed source date')
        owner[key] = copy.deepcopy(patch['after']); seen.add(pointer)
    # Source identity and URLs can never change, even through reviewed patches.
    for before, after in zip(edition['sources'], candidate['sources']):
        if {k:v for k,v in before.items() if k != 'published_date'} != {
                k:v for k,v in after.items() if k != 'published_date'}:
            raise ValueError('App continuation changed source identity')
    validate_edition(candidate, day)
    if redact(candidate) != candidate: raise ValueError('Potential credential in reviewed app')
    if fingerprint(candidate) != policy.get('candidate_sha256'):
        raise ValueError('App continuation corrected candidate differs')
    # A locally revised topic/reference still has to pass the ordinary coverage
    # gate with exact retained primary-source anchors, not reviewer assertions.
    for group in ('stories', 'signals'):
        for i, row in enumerate(candidate[group], 1):
            planned = coverage[group][('story' if group == 'stories' else 'signal') + '_' + str(i)]
            keys = ['id', 'title'] + (['change', 'policy_state'] if group == 'stories' else [])
            if (any(row[k] != planned[k] for k in keys)
                    or row['source_ids'] != references(planned, edition['sources'])):
                raise ValueError('Reviewed app differs from its verified coverage plan')
    record = {**required, 'policy_sha256': fingerprint(policy),
              'base_candidate_sha256': base_sha, 'candidate_sha256': fingerprint(candidate),
              'original_research_attempts': count, 'prior_review_preserved': True}
    marker = cache / (METHOD + '-used.json')
    if marker.exists():
        if _read(marker) != record: raise ValueError('App continuation reservation differs')
    else:
        if (folder / 'final-reserved.json').exists() or (folder / 'final-result.json').exists():
            raise ValueError('App continuation final review slot was already used')
        with marker.open('x', encoding='utf-8') as f: json.dump(record, f, indent=2)
    Diagnostics(cache, day).capture('reviewed-app-corrected', candidate)
    write_json(cache / 'validation-reviewed-app-correction.json', {
        **record, 'changed_paths': sorted(seen), 'additional_generation_calls': 0})
    return candidate, {'prior_incomplete_review': review,
                       'operator_review_notes': policy.get('editorial_notes', [])}
