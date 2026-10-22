"""Project dated records into the next-30-day watch without changing their facts.

Expired and more distant records are retained in the original diagnostic snapshot.
This calendar-only selection never approves content, invents dates or resets a ledger.
Every selected candidate must still pass the full source and editorial review.
"""
from __future__ import annotations
import copy
import re
from datetime import date
from pathlib import Path
from release_core import read_json, write_json, validate_edition, canonical_url, allowed_url
from release_editorial import fingerprint
from release_diagnostics import Diagnostics
from release_resume import _read_snapshot
from release_typography import normalize_edition_typography, normalize_source_identifiers

WINDOW_ERROR = 'Deadline is not within the next 30 days'


def select_upcoming_deadlines(edition: dict, cache: Path) -> dict:
    """Select only dated rows in the edition-relative view; leave prose untouched."""
    expected = edition.get('edition_date')
    try:
        validate_edition(edition, expected)
    except AssertionError as error:
        if str(error) != WINDOW_ERROR:
            return edition  # The normal validator must explain this other failure.
    else:
        return edition
    original = copy.deepcopy(edition)
    base = date.fromisoformat(expected)
    kept, excluded = [], []
    for index, item in enumerate(original['deadlines']):
        delta = (date.fromisoformat(item['date']) - base).days
        if 0 <= delta <= 30:
            kept.append(item)
        else:
            excluded.append({'path': '/deadlines/'+str(index), 'date': item['date'],
                             'days_from_edition': delta,
                             'reason': 'expired' if delta < 0 else 'beyond_30_days'})
    selected = copy.deepcopy(original)
    selected['deadlines'] = kept
    # A generated internal checkpoint is a recommendation, not a recorded staff
    # commitment or statutory deadline. When its date has passed, leave the
    # replacement date unknown. Never carry this rule over to official deadlines.
    expired_internal = [d for d in original['deadlines']
                        if d['kind'] == 'Editorial checkpoint'
                        and date.fromisoformat(d['date']) < base]
    cleared = []
    for index, action in enumerate(selected['actions']):
        previous = action['due_date']
        if previous and date.fromisoformat(previous) < base and any(
                d['date'] == previous and set(d['source_ids']) & set(action['source_ids'])
                for d in expired_internal):
            action['due_date'] = None
            cleared.append({'path': '/actions/'+str(index)+'/due_date',
                            'previous_date': previous,
                            'reason': 'expired_internal_checkpoint_no_replacement_assigned'})
    snapshot = Diagnostics(Path(cache), expected).capture('deadline-watch-input', original)
    write_json(Path(cache)/'validation-deadline-watch.json', {
        'schema_version': 1, 'edition_date': expected,
        'operation': 'calendar_view_selection',
        'original_candidate_sha256': fingerprint(original),
        'selected_candidate_sha256': fingerprint(selected),
        'retained_original': snapshot, 'excluded': excluded,
        'kept_count': len(kept), 'deadline_dates_changed': False,
        'action_dates_cleared': cleared, 'new_dates_assigned': False,
        'prose_changed': False, 'source_records_changed': False,
        'publication_authorized': False, 'evidence_review_required': True,
    })
    return selected


def take_deadline_recovery(cache: Path, expected: str):
    """Reuse one exact same-date pre-audit draft, without new research generation."""
    cache = Path(cache)
    if any((cache/name).exists() for name in ('audit.json', 'audit-bound.json', 'approved.json',
                                             'editorial-loop-v1/original.json')):
        return None  # A completed or started evidence review owns subsequent recovery.
    report = read_json(cache/'validation-content.json', {})
    if (report.get('edition_date') != expected or report.get('stage') != 'content'
            or report.get('passed') is not False or report.get('rule') != 'deadline_window'
            or report.get('publication_authorized') is not False):
        return None
    if cache.is_symlink() or (cache/'candidates').is_symlink():
        raise ValueError('Unsafe deadline recovery directory')
    saved = report.get('snapshot', {})
    sha = saved.get('candidate_sha256', '')
    if (not re.fullmatch(r'[a-f0-9]{64}', sha)
            or saved.get('retained') is not True or saved.get('redacted') is not False
            or saved.get('file') != 'candidates/content-'+sha[:16]+'.json'):
        raise ValueError('Invalid deadline recovery reference')
    item = _read_snapshot(cache/'candidates'/('content-'+sha[:16]+'.json'), expected, 'content')
    if not item or item['candidate_sha256'] != sha:
        raise ValueError('Deadline recovery snapshot integrity differs')
    original = item['candidate']
    try:
        validate_edition(original, expected)
    except AssertionError as error:
        if str(error) != WINDOW_ERROR:
            raise ValueError('Recorded deadline failure does not match retained draft') from None
    else:
        raise ValueError('Retained draft does not have the recorded deadline failure')
    # Content snapshots may omit provenance. Recover it only from the matching
    # original tool-observed generated snapshot, never arbitrary URLs in prose.
    facts = {k: v for k, v in original.items() if k != 'podcast'}
    provenance = None
    for path in sorted((cache/'candidates').glob('generated-*.json')):
        generated = _read_snapshot(path, expected, 'generated')
        if not generated:
            continue
        normalized, _ = normalize_edition_typography(generated['candidate'])
        normalized, _ = normalize_source_identifiers(normalized)
        if {k: v for k, v in normalized.items() if k != 'podcast'} == facts:
            urls = generated.get('retrieved_urls')
            if isinstance(urls, list) and urls and all(isinstance(u, str) for u in urls):
                provenance = {canonical_url(u) for u in urls if allowed_url(u)}
                if provenance:
                    break
    if provenance is None:
        raise ValueError('Deadline recovery lacks matching original retrieval provenance')
    candidate = select_upcoming_deadlines(original, cache)
    validate_edition(candidate, expected)
    return candidate, provenance
