"""Apply a reviewed citation correction before an unused final evidence audit.

An incomplete initial review never authorizes publication. This path accepts only
an exact repository-reviewed plan, preserves original results and ledgers, and
uses the existing final-review slot. It cannot reopen a spent correction or audit.
"""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
from release_core import read_json, write_json, validate_edition, allowed_url
from release_editorial import fingerprint
from release_diagnostics import redact

REVIEW_ROOT = Path(__file__).resolve().parents[1] / 'reference-review'


def _read(path: Path, limit: int = 1048576):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Unsafe reviewed-reference checkpoint')
    result = read_json(path)
    if redact(result) != result:
        raise ValueError('Potential credential in reviewed-reference checkpoint')
    return result


def take_reviewed_reference(edition: dict, cache: Path, review_root: Path | None = None):
    expected = edition['edition_date']
    root = Path(review_root) if review_root is not None else REVIEW_ROOT
    path = root / (expected + '.json')
    if not path.exists():
        return None
    folder = Path(cache) / 'editorial-loop-v1'
    if root.is_symlink() or Path(cache).is_symlink() or folder.is_symlink():
        raise ValueError('Unsafe reviewed-reference directory')
    plan = _read(path, 65536)
    if (plan.get('schema_version') != 1 or plan.get('edition_date') != expected
            or plan.get('publication_authorized') is not False
            or plan.get('use_existing_final_audit_only') is not True
            or plan.get('base_candidate_sha256') != fingerprint(edition)):
        raise ValueError('Reviewed-reference plan identity mismatch')
    original = _read(folder / 'original.json')
    if (original.get('candidate_sha256') != fingerprint(edition)
            or fingerprint(original.get('candidate')) != fingerprint(edition)
            or original.get('edition_date') != expected
            or original.get('publication_authorized') is not False):
        raise ValueError('Reviewed-reference original differs')
    saved = _read(folder / 'initial-result.json')
    reserved = _read(folder / 'initial-reserved.json')
    review = saved.get('value')
    if (not isinstance(review, dict) or review.get('review_complete') is not False
            or saved.get('value_sha256') != fingerprint(review)
            or plan.get('initial_review_sha256') != fingerprint(review)
            or saved.get('payload_sha256') != reserved.get('payload_sha256')):
        raise ValueError('Reviewed-reference initial review differs')
    marker_path = folder / 'reviewed-reference-correction.json'
    marker = _read(marker_path) if marker_path.exists() else None
    if any((folder / n).exists() for n in ('correction-reserved.json', 'correction-result.json')):
        raise RuntimeError('Existing automated correction cannot be replaced')
    if marker is None and any((folder / n).exists() for n in ('final-reserved.json', 'final-result.json')):
        raise RuntimeError('Existing final audit cannot be reopened')
    removals = plan.get('remove_sources')
    if not isinstance(removals, list) or not 1 <= len(removals) <= 2:
        raise ValueError('Reviewed-reference removal count invalid')
    cited = {ref for f in review.get('findings', []) if f.get('kind') == 'citation_mismatch'
             for ref in f.get('source_ids', [])}
    source_map = {s['id']: s for s in edition['sources']}
    removed = set()
    for row in removals:
        sid = row.get('id')
        if (sid in removed or sid not in cited or sid not in source_map
                or row.get('url') != source_map[sid]['url']
                or not allowed_url(row.get('url'))
                or not isinstance(row.get('reason'), str) or not row['reason'].strip()):
            raise ValueError('Reviewed source removal differs from the observed mismatch')
        removed.add(sid)
    candidate = copy.deepcopy(edition)
    candidate['sources'] = [s for s in candidate['sources'] if s['id'] not in removed]
    for group in ('stories', 'actions', 'deadlines', 'signals', 'issue_updates'):
        for row in candidate[group]:
            row['source_ids'] = [sid for sid in row['source_ids'] if sid not in removed]
    from release_audit_loop import text_fields
    fields = text_fields(edition)
    replacements = plan.get('replacements')
    if not isinstance(replacements, list) or not 1 <= len(replacements) <= 12:
        raise ValueError('Reviewed-reference prose correction count invalid')
    seen = set()
    for patch in replacements:
        key = patch.get('path')
        text = patch.get('after')
        if (key not in fields or key in seen or patch.get('before') != fields[key]
                or not isinstance(text, str) or not text.strip() or text == fields[key]
                or len(text) > 12000):
            raise ValueError('Reviewed-reference prose correction is stale or invalid')
        seen.add(key)
        owner = candidate
        parts = key.split('/')[1:]
        for part in parts[:-1]:
            owner = owner[int(part)] if isinstance(owner, list) else owner[part]
        owner[int(parts[-1]) if isinstance(owner, list) else parts[-1]] = text
    if fingerprint(candidate) != plan.get('candidate_sha256'):
        raise ValueError('Reviewed-reference corrected candidate differs')
    validate_edition(candidate, expected)
    record = {'edition_date': expected, 'plan_sha256': fingerprint(plan),
              'base_candidate_sha256': fingerprint(edition),
              'candidate_sha256': fingerprint(candidate),
              'initial_review_sha256': fingerprint(review),
              'publication_authorized': False, 'new_research_calls': 0,
              'new_correction_calls': 0, 'use_existing_final_audit_only': True,
              'original_attempt_ledgers_preserved': True,
              'removed_source_ids': sorted(removed), 'changed_prose_paths': sorted(seen)}
    if marker is not None:
        if marker != record:
            raise ValueError('Reviewed-reference reservation differs')
    else:
        with marker_path.open('x', encoding='utf-8') as f:
            json.dump(record, f, indent=2)
    write_json(Path(cache) / 'validation-reviewed-reference.json', record)
    return candidate
