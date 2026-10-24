"""Reviewed extraction of an existing BLUF; no new research or BLUF requests.

The original report, rejected passages, and attempt ledgers stay immutable. A
derived edition still requires exact source retrieval, a full independent audit,
complete audio, and the single publisher's delivery checks.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

DAY = '2026-10-24'
FAILURE_RUN = '40104289530'
ENGINE = 'staged-research-v3'
MARKER = 'retained-bluf-recovery-used.json'
POLICY = DAY + '-retained-bluf.json'


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _read(path):
    path = Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise RuntimeError('Unsafe retained BLUF path')
    if not path.is_file() or path.stat().st_size > 2000000:
        raise RuntimeError('Missing or oversized retained BLUF record')
    return json.loads(path.read_text(encoding='utf-8'))


def _policy(root):
    path = Path(root) / POLICY
    policy = _read(path)
    required = {'edition_date': DAY, 'failure_run_id': int(FAILURE_RUN),
                'maximum_recoveries': 1, 'additional_bluf_requests': 0,
                'additional_research_attempts': 0, 'publication_authorized': False,
                'section': 'bluf-None', 'method': 'complete-sentence-prefix'}
    if any(policy.get(k) != v for k, v in required.items()):
        raise RuntimeError('Invalid retained BLUF recovery policy')
    if policy.get('model') != os.getenv('RURAL_UPDATE_MODEL', 'gpt-5-mini'):
        raise RuntimeError('Retained BLUF model identity changed')
    return policy, _hash(path.read_bytes())


def reserve(cache, expected, plan, policy_root, engine, load, validate_report):
    """Reserve one local edit, with all previous requests still charged."""
    cache = Path(cache)
    if (plan.get('maximum_retained_bluf_recoveries') != 1 or expected != DAY
        or cache.name != DAY or engine != ENGINE):
        return False
    marker = cache / MARKER
    if marker.exists() or any((cache / n).exists() for n in
                             ('audit.json', 'audit-bound.json', 'approved.json')):
        return False
    policy, policy_sha = _policy(policy_root)
    folder = cache / ENGINE
    if (folder / 'narration.json').exists():
        return False
    records = _read(cache / 'api-responses.json').get('responses') or []
    last = records[-1] if records else {}
    required = {'run_id': FAILURE_RUN, 'stage': 'narration_section',
                'status': 'incomplete', 'incomplete_reason': 'max_output_tokens',
                'requested_output_limit': 4000, 'input_tokens': 0,
                'output_tokens': 0, 'reasoning_tokens': 0, 'visible_characters': 0}
    if any(last.get(k) != v for k, v in required.items()):
        return False
    validation = _read(cache / 'validation-latest.json')
    if (validation.get('passed') is not False or validation.get('rule') != 'api_response'
        or str(validation.get('run_id')) != FAILURE_RUN):
        return False
    original = {}
    for name, sha in policy['retained_file_sha256'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise RuntimeError('Retained BLUF record escaped edition cache')
        path = cache / relative
        _read(path)
        original[path] = path.read_bytes()
        if _hash(original[path]) != sha:
            raise RuntimeError('Retained BLUF prerequisite changed')
    required_files = {'attempts.json', 'narration-structural-resume-used.json',
                      'narration-structural-followup-used.json'}
    required_files.update(ENGINE + '/' + n + '.json' for n in
                          ('discovery', 'sources', 'reporting'))
    if not required_files.issubset(policy['retained_file_sha256']):
        raise RuntimeError('Retained BLUF policy omitted a prerequisite')
    identity = policy['identity']
    values = {n: load(folder / (n + '.json'), identity) for n in
              ('discovery', 'sources', 'reporting')}
    if any(v is None for v in values.values()):
        raise RuntimeError('Retained BLUF lost reporting identity')
    validate_report(values)
    from release_sectioned_narration import METHOD, SECTION_PLAN, fingerprint, _ledger
    from release_prose import FORMAT, validate_prose, recovery_grant
    report = values['reporting']['edition']
    sid = fingerprint({'method': METHOD, 'identity': identity, 'model': policy['model'],
                       'reporting': report, 'plan': SECTION_PLAN})
    if report.get('edition_date') != DAY or sid != policy['section_identity']:
        raise RuntimeError('Retained BLUF section identity changed')
    work = folder / METHOD / sid
    ledger = work / 'attempts.json'
    opening = work / 'opening-None.json'
    if not {str(ledger.relative_to(cache)), str(opening.relative_to(cache))}.issubset(policy['retained_file_sha256']):
        raise RuntimeError('Retained BLUF policy omitted section state')
    state = _ledger(ledger, sid, {'bluf-None': 2})
    if (state['requests'] != 6 or state['attempts'] != {'opening-None': 2, 'bluf-None': 4}
        or _read(cache / 'attempts.json') != {'attempts': 2}
        or (work / 'bluf-None.json').exists()):
        return False
    if recovery_grant(cache, identity, sid) != {'bluf-None': 2}:
        raise RuntimeError('Retained BLUF recovery lineage changed')
    completed_opening = load(opening, sid)
    if not completed_opening or completed_opening.get('section') != 'opening-None':
        raise RuntimeError('Retained opening is missing')
    validate_prose(completed_opening['result'], 60)
    candidate_sha = policy['candidate_sha256']
    if not re.fullmatch('[a-f0-9]{64}', candidate_sha):
        raise RuntimeError('Invalid retained BLUF candidate hash')
    record = _read(cache / 'section-candidates' / (candidate_sha + '.json'))
    candidate = record.get('candidate')
    if (record.get('section') != 'bluf-None' or record.get('publication_authorized') is not False
        or not isinstance(candidate, dict) or set(candidate) != {'text'}
        or _hash(json.dumps(candidate, sort_keys=True, ensure_ascii=False).encode()) != candidate_sha):
        raise RuntimeError('Retained BLUF candidate integrity differs')
    text = candidate['text']
    observed = {'section': 'bluf-None', 'attempt': 2, 'word_count': 222,
                'characters': len(text), 'passed': False, 'rule': 'section_word_count',
                'run_id': '40084542457', 'publication_authorized': False}
    history = _read(cache / 'validation-narration-sections.json').get('sections', [])
    if not any(all(row.get(k) == v for k, v in observed.items()) for row in history):
        raise RuntimeError('Retained BLUF does not match its recorded completed attempt')
    end = policy['retained_characters']
    if type(end) is not int or not 0 < end < len(text):
        raise RuntimeError('Invalid retained BLUF sentence boundary')
    passage = text[:end]
    if (not passage.endswith('.') or not text[end:].startswith(' Recommendations and operational implications:')
        or len(text.split()) != 222 or _hash(passage.encode()) != policy['retained_text_sha256']):
        raise RuntimeError('Retained BLUF is not the reviewed complete passage')
    validate_prose({'text': passage}, 165)
    if len(passage.split()) > 180 or _hash(report['bluf'].encode()) != policy['original_web_bluf_sha256']:
        raise RuntimeError('Retained executive BLUF differs')
    citation = policy['citation_replacement']
    from release_core import allowed_url
    selected = [s for s in values['sources']['sources'] if s['id'] == citation['source_id']]
    if (len(selected) != 1 or selected[0]['url'] != citation['before_url']
        or citation['after_url'] not in values['discovery']['notes']
        or not allowed_url(citation['after_url']) or '.pdf' in citation['after_url'].lower()):
        raise RuntimeError('Retained citation replacement lacks the original reporting context')
    result = {'edition_date': DAY, 'identity': identity, 'section_identity': sid,
              'policy_sha256': policy_sha, 'retained_text_sha256': policy['retained_text_sha256'],
              'failure_run_id': int(FAILURE_RUN), 'additional_bluf_requests': 0,
              'additional_research_attempts': 0, 'publication_authorized': False,
              'existing_remaining_section_budget_only': True,
              'reserved_at': datetime.now(timezone.utc).isoformat(),
              'run_id': os.getenv('GITHUB_RUN_ID', 'local')}
    try:
        with marker.open('x', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
    except FileExistsError:
        return False
    from release_research import _save
    _save(work / 'bluf-None.json', sid, {'section': 'bluf-None', 'format': FORMAT,
          'result': {'text': passage}, 'usage': None, 'retained_candidate_sha256': candidate_sha})
    if any(path.read_bytes() != data for path, data in original.items()):
        raise RuntimeError('Retained BLUF recovery changed an original record')
    return True


def apply(edition, cache, policy_root):
    """Derive the complete web BLUF and corrected citation before the full audit."""
    cache = Path(cache)
    if not (cache / MARKER).exists():
        return edition
    policy, sha = _policy(policy_root)
    marker = _read(cache / MARKER)
    if (marker.get('publication_authorized') is not False or marker.get('policy_sha256') != sha
        or edition.get('edition_date') != DAY):
        raise RuntimeError('Retained BLUF edit authorization differs')
    from release_research import _cached
    from release_prose import validate_prose
    from release_sectioned_narration import METHOD
    value = _cached(cache / ENGINE / METHOD / marker['section_identity'] / 'bluf-None.json',
                    marker['section_identity'])
    if value is None:
        raise RuntimeError('Retained BLUF section is missing')
    passage = validate_prose(value['result'], 165)
    if (_hash(passage.encode()) != policy['retained_text_sha256']
        or edition['podcast']['bluf'] != passage
        or _hash(edition['bluf'].encode()) != policy['original_web_bluf_sha256']):
        raise RuntimeError('Retained BLUF edit no longer matches the candidate')
    derived = copy.deepcopy(edition)
    derived['bluf'] = passage
    citation = policy['citation_replacement']
    matches = [s for s in derived['sources'] if s['id'] == citation['source_id']]
    if len(matches) != 1 or matches[0]['url'] != citation['before_url']:
        raise RuntimeError('Retained citation no longer matches the candidate')
    matches[0].update(url=citation['after_url'], title=citation['title'], published_date=None)
    # The new URL must pass real HTTPS retrieval and the independent evidence
    # audit below. No synthetic search events or publication approval are added.
    return derived
