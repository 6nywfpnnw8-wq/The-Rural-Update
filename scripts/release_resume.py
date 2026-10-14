"""Resume one retained style-only rejection; never grant editorial approval.

This module makes no API calls. A selected draft still enters the publisher's
unchanged full evidence audit and source-provenance check before approved.json.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from release_core import read_json, write_json, validate_edition, canonical_url, allowed_url
from release_typography import normalize_edition_typography

MAX_BYTES = 1024 * 1024


def _read_snapshot(path: Path, expected: str, stage: str):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        data = read_json(path)
        if (data.get('schema_version') != 1 or data.get('edition_date') != expected
                or data.get('stage') != stage or data.get('redacted') is not False
                or data.get('publication_authorized') is not False):
            return None
        candidate = data['candidate']
        if not isinstance(candidate, dict) or candidate.get('edition_date') != expected:
            return None
        raw = json.dumps(candidate, ensure_ascii=False, sort_keys=True).encode()
        fingerprint = hashlib.sha256(raw).hexdigest()
        if data.get('candidate_sha256') != fingerprint:
            return None
        if path.name != stage + '-' + fingerprint[:16] + '.json':
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def take_style_recovery(cache: Path, expected: str):
    """Return (normalized candidate, original retrieval URLs) once per date.

    Only an explicitly recorded punctuation rejection is eligible. It must have
    an intact, unredacted same-date snapshot plus a matching original generated
    snapshot carrying retrieval provenance. All non-podcast facts must match.
    Both the saved draft and normalized draft remain unapproved. No research
    counter is reset or incremented. The caller must run a fresh evidence audit.
    """
    cache = Path(cache)
    report = read_json(cache / 'validation-content.json', {})

    def skip(reason, error=None):
        if report.get('edition_date') == expected:
            # Only fixed reasons and known validator messages are exposed.
            message = None
            known = {
                'Edition date does not match requested date',
                'Spoken body must contain 1700 to 2000 words',
                'Placeholder text', 'Use punctuation other than em dashes',
                'Spoken body contains URLs or markup', 'Need multiple source domains',
                'Source URL outside approved public domains', 'Future-dated source',
                'Source not observed in research tool results', 'Unresolved source reference',
                'Deadline is not within the next 30 days', 'Action due date is already past',
                'Executive BLUF is too long',
            }
            known.update(f'{prefix} {group} {suffix}'
                         for group in ('stories','actions','signals','issue_updates','sources')
                         for prefix,suffix in (('Unsafe','ID'),('Duplicate','IDs')))
            if isinstance(error, AssertionError) and str(error) in known:
                message = str(error)
            write_json(cache / 'validation-style-recovery.json', {
                'schema_version': 1, 'edition_date': expected, 'stage': 'style-recovery',
                'passed': False, 'publication_authorized': False,
                'reason': reason, 'validation_message': message,
            })
        return None
    if (report.get('edition_date') != expected or report.get('stage') != 'content'
            or report.get('passed') is not False or report.get('rule') != 'punctuation'):
        return skip('not_a_same_date_punctuation_rejection')
    if (cache / 'style-recovery-attempt.json').exists():
        return skip('audit_already_reserved')
    saved = report.get('snapshot', {})
    relative = saved.get('file', '')
    if (not isinstance(relative, str) or not relative.startswith('candidates/content-')
            or len(Path(relative).parts) != 2 or '..' in Path(relative).parts
            or saved.get('retained') is not True or saved.get('redacted') is not False):
        return skip('unsafe_or_redacted_snapshot_reference')
    if (cache / 'candidates').is_symlink():
        return skip('snapshot_directory_is_symlink')
    snapshot = _read_snapshot(cache / relative, expected, 'content')
    if not snapshot or saved.get('candidate_sha256') != snapshot['candidate_sha256']:
        return skip('snapshot_missing_redacted_or_integrity_mismatch')
    # Do not let a forged reason make another rejected category eligible.
    try:
        validate_edition(snapshot['candidate'], expected)
    except AssertionError as error:
        if str(error) != 'Use punctuation other than em dashes':
            return skip('original_rejection_is_not_punctuation', error)
    except Exception as error:
        return skip('original_snapshot_does_not_validate', error)
    else:
        return skip('original_snapshot_has_no_punctuation_rejection')
    candidate, changed = normalize_edition_typography(snapshot['candidate'])
    if not changed:
        return skip('no_prose_typography_change')
    try:
        validate_edition(candidate, expected)
    except Exception as error:
        return skip('normalized_draft_has_another_validation_failure', error)
    facts = {k: v for k, v in candidate.items() if k != 'podcast'}
    provenance = None
    for path in sorted((cache / 'candidates').glob('generated-*.json')):
        generated = _read_snapshot(path, expected, 'generated')
        if not generated:
            continue
        original, _ = normalize_edition_typography(generated['candidate'])
        if {k: v for k, v in original.items() if k != 'podcast'} != facts:
            continue
        urls = generated.get('retrieved_urls')
        if not isinstance(urls, list) or not urls or not all(isinstance(u, str) for u in urls):
            continue
        provenance = {canonical_url(u) for u in urls if allowed_url(u)}
        if provenance:
            break
    if not provenance:
        return skip('matching_original_retrieval_evidence_missing')
    # Mark before the caller can spend on auditing; a failed audit is not retried
    # indefinitely, and this file is restored with the existing workflow cache.
    write_json(cache / 'style-recovery-attempt.json', {
        'edition_date': expected, 'candidate_sha256': snapshot['candidate_sha256'],
        'evidence_audit_reserved': True, 'publication_authorized': False,
        'additional_research_generation_calls': 0, 'changed_fields': changed,
    })
    return candidate, provenance
