"""Reuse a bound rejection as correction feedback, never as evidence or approval.

A source-page change invalidates a cached request. A completed rejection can
still identify claims to correct when it is independently bound to the same
candidate. The existing correction and fresh audit reservations are unchanged.
"""
from __future__ import annotations
import copy
import re
from pathlib import Path
from release_core import read_json, write_json
from release_editorial import fingerprint


def _read(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1048576:
        raise ValueError('Unsafe retained rejection record')
    return read_json(path)


def call_with_rejected_feedback(folder, slot, payload, request, output_text,
                                candidate, call, validate):
    """The fallback is limited to an already rejected reviewed-reference draft."""
    try:
        return call(folder, slot, payload, request, output_text)
    except ValueError as exc:
        if slot != 'final' or str(exc) != 'Editorial checkpoint differs from request':
            raise
    folder = Path(folder)
    saved = _read(folder / 'final-result.json')
    reservation = _read(folder / 'final-reserved.json')
    summary = _read(folder.parent / 'validation-structured-review.json')
    old_signature = saved.get('payload_sha256', '')
    current_signature = fingerprint(payload)
    if (not re.fullmatch(r'[a-f0-9]{64}', old_signature)
            or reservation.get('payload_sha256') != old_signature
            or old_signature == current_signature):
        raise ValueError('Retained rejection request identity mismatch')
    value = saved.get('value')
    if saved.get('value_sha256') != fingerprint(value):
        raise ValueError('Retained rejection result integrity mismatch')
    blocking = validate(value, candidate)
    # A prior approval or an incomplete review must never use this exception.
    if not blocking:
        raise ValueError('Only completed blocking feedback can be retained')
    if (summary.get('candidate_sha256') != fingerprint(candidate)
            or summary.get('edition_date') != candidate['edition_date']
            or summary.get('review_complete') is not True
            or summary.get('publication_authorized') is not False
            or summary.get('correction_method') != 'reviewed-reference'
            or summary.get('correction_calls') != 0
            or summary.get('findings') != value['findings']
            or summary.get('blocking_count') != len(blocking)
            or summary.get('advisory_count') != len(value['findings']) - len(blocking)):
        raise ValueError('Retained rejection is not bound to the current candidate')
    write_json(folder.parent / 'validation-reviewed-evidence-refresh.json', {
        'schema_version': 1, 'edition_date': candidate['edition_date'],
        'candidate_sha256': fingerprint(candidate),
        'prior_request_sha256': old_signature,
        'current_request_sha256': current_signature,
        'prior_review_sha256': fingerprint(value),
        'use': 'blocking_feedback_only', 'blocking_count': len(blocking),
        'fresh_post_correction_audit_required': True,
        'publication_authorized': False, 'additional_review_requested': False,
        'original_reservations_preserved': True})
    print('Retained blocking findings used only as correction feedback; refreshed evidence and a new full audit remain mandatory.', flush=True)
    # Old retrieval URLs are not promoted as current evidence.
    return copy.deepcopy(value), set(), saved.get('usage')
