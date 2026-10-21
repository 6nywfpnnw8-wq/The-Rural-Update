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


def take_reviewed_recovery(cache: Path, expected: str):
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
