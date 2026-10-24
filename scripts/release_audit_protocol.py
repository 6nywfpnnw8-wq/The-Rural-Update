"""One unused final review of a hash-bound malformed initial response.

The malformed response stays intact and cannot approve publication. The normal
final slot still reserves before calling and cannot be repeated or extended.
"""
from __future__ import annotations
import json
from pathlib import Path
from release_editorial import fingerprint
from release_retained_bluf import _read

DEFECT_ONLY_POLICY = '''
Return findings only for actual defects or actionable non-blocking observations.
Do not create findings to document checks that passed. An empty findings array is
valid after a complete review with no problems. Do not fill the array to its limit.
Use citation_mismatch only when a candidate claim and its cited evidence actually
disagree. A supported claim is not a citation mismatch. A blocking finding must
specify a substantive change; "none", "no change" and "n/a" are invalid changes.
Quote an exact substring of the named CANDIDATE field, not text from a source and
not a summary or paraphrase. A scalar date quote must be the date value itself.
Explicit internal planning checkpoints are not claims of statutory deadlines.
Review every field and every podcast section using the complete sources and live
retrieval. Unsupported material still blocks. Return review_complete=false if the
evidence is insufficient to finish; do not infer approval from an earlier review.
'''


def use_final_review(candidate, cache, policy_root, validate_review):
    cache=Path(cache)
    if candidate.get('edition_date')!='2026-10-24' or cache.name!='2026-10-24':return False
    path=Path(policy_root)/'2026-10-24.json'
    if not path.exists():return False
    policy=_read(path)
    required={'edition_date':'2026-10-24','failure_run_id':40108030234,
              'maximum_total_audit_requests':2,'use_existing_slot':'final',
              'additional_research_generation_calls':0,'additional_narration_generation_calls':0,
              'publication_authorized':False}
    if any(policy.get(k)!=v for k,v in required.items()):
        raise ValueError('Invalid audit-protocol continuation policy')
    if fingerprint(candidate)!=policy.get('candidate_sha256'):
        raise ValueError('Audit-protocol continuation candidate differs')
    folder=cache/'editorial-loop-v1'
    saved=_read(folder/'initial-result.json');reserved=_read(folder/'initial-reserved.json')
    if (saved.get('value_sha256')!=policy.get('initial_review_sha256')
        or fingerprint(saved.get('value'))!=policy['initial_review_sha256']
        or saved.get('payload_sha256')!=policy.get('initial_request_sha256')
        or reserved.get('payload_sha256')!=policy['initial_request_sha256']
        or str(reserved.get('run_id'))!=str(policy['failure_run_id'])
        or reserved.get('publication_authorized') is not False):
        raise ValueError('Malformed audit response identity differs')
    if any((folder/(slot+'-reserved.json')).exists() for slot in
           ('correction','reference-correction','reference-corrected-final')):
        raise ValueError('Audit-protocol continuation cannot expand spent review slots')
    try:validate_review(saved['value'],candidate)
    except (ValueError,RuntimeError):pass
    else:raise ValueError('Audit-protocol continuation requires a malformed initial review')
    if _read(cache/'attempts.json')!={'attempts':2}:
        raise ValueError('Audit-protocol continuation cannot reset research attempts')
    marker=cache/'audit-protocol-recovery-used.json'
    record={**required,'candidate_sha256':policy['candidate_sha256'],
            'initial_review_sha256':policy['initial_review_sha256'],
            'raw_review_unchanged':True,'existing_final_slot_only':True}
    if marker.exists():
        if _read(marker)!=record:raise ValueError('Audit-protocol continuation marker differs')
    else:
        try:
            with marker.open('x',encoding='utf-8') as f:json.dump(record,f,indent=2)
        except FileExistsError:
            raise RuntimeError('Audit-protocol continuation was concurrently reserved') from None
    return True
