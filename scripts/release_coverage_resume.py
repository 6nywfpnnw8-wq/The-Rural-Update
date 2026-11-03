"""Complete retained pre-reporting work after a reviewed source-reader correction.

No discovery, source selection, ledger reset or editorial approval is permitted.
Every model stage is reserved before submission; ambiguous requests stay spent.
"""
from __future__ import annotations
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from release_core import digest
from release_publication import app_only

METHOD = 'retained-source-coverage-v1'
ROOT = Path(__file__).resolve().parents[1] / 'coverage-resume'
_NO_HASH = object()


def checked(path, expected_hash=_NO_HASH):
    path = Path(path)
    if (not path.is_file() or path.is_symlink() or any(p.is_symlink() for p in path.parents)
            or path.stat().st_size > 2 * 1024 * 1024):
        raise RuntimeError('Coverage continuation prerequisite missing or unsafe')
    raw = path.read_bytes()
    if expected_hash is not _NO_HASH and (not isinstance(expected_hash, str)
            or not re.fullmatch('[a-f0-9]{64}', expected_hash) or digest(raw) != expected_hash):
        raise RuntimeError('Coverage continuation prerequisite hash differs')
    return json.loads(raw)


def prepare(cache, expected, payload, policy_root=ROOT):
    cache = Path(cache); path = Path(policy_root) / (expected + '.json')
    if not path.exists():return None
    policy = checked(path)
    required = {'schema_version': 1, 'edition_date': expected, 'method': METHOD,
        'maximum_recoveries': 1, 'maximum_reporting_plan_requests': 1,
        'maximum_reporting_requests': 1, 'new_discovery_permitted': False,
        'source_selection_model_requests': 0, 'research_counter_reset': False,
        'independent_editorial_review_required': True, 'podcast_generation_permitted': False,
        'publication_authorized': False}
    if (not app_only(expected) or cache.name != expected
            or any(type(policy.get(k)) is not type(v) or policy.get(k) != v for k,v in required.items())):
        raise RuntimeError('Invalid retained coverage continuation policy')
    if os.getenv('RURAL_UPDATE_STRUCTURED_REVIEW') != 'true':
        raise RuntimeError('Coverage continuation requires the independent structured editorial review')
    ledger = checked(cache / 'attempts.json', policy.get('attempt_ledger_sha256'))
    if ledger != {'attempts': 2}:
        raise RuntimeError('Coverage continuation requires the original exhausted research ledger')
    if any((cache / name).exists() for name in ('audit.json', 'audit-bound.json', 'approved.json',
            'editorial-loop-v1', 'coverage-plan-repair-authorized.json', 'corrective-generation-used.json',
            'app-pdf-evidence-recovery-v1-used.json')) or any((cache/'candidates').glob('*.json')):
        raise RuntimeError('Coverage continuation cannot replace started editorial work')
    failure = checked(cache / 'validation-research-coverage.json', policy.get('failure_report_sha256'))
    if (failure.get('edition_date') != expected or failure.get('passed') is not False
            or failure.get('rule') != 'evidence_coverage' or failure.get('api_stage') != 'reporting_plan'
            or str(failure.get('run_id')) != str(policy.get('failure_run_id'))):
        raise RuntimeError('Coverage continuation does not match the recorded source failure')
    finding = {'rule': 'source_retrieval', 'path': '/sources/3',
        'source_id': policy.get('source_id'), 'url': policy.get('source_url'),
        'exception_category': 'ValueError', 'http_status': None}
    if failure.get('findings') != [finding]:
        raise RuntimeError('Coverage continuation requires the exact reviewed source rejection')
    from release_research import ENGINE, _cached, observed_source_urls, validate_source_catalog, staged_request
    identity = digest(json.dumps({'engine': ENGINE, 'model': payload['model'],
                                 'context': payload['input']}, sort_keys=True))
    if identity != policy.get('identity'):
        raise RuntimeError('Coverage continuation request identity differs; no discovery permitted')
    folder = cache / ENGINE
    for name in ('discovery', 'sources'):
        checked(folder / (name + '.json'), policy.get(name + '_file_sha256'))
    discovery = _cached(folder/'discovery.json', identity)
    selected = _cached(folder/'sources.json', identity)
    if discovery is None or selected is None:
        raise RuntimeError('Coverage continuation requires intact retained discovery and sources')
    catalog = validate_source_catalog(selected['sources'], observed_source_urls(discovery))
    if len(catalog) != 9 or catalog[3]['id'] != policy.get('source_id') or catalog[3]['url'] != policy.get('source_url'):
        raise RuntimeError('Coverage continuation source catalog differs')
    from release_evidence import MAX_PDF_PAGES
    if (type(policy.get('observed_pdf_pages')) is not int
            or not 100 < policy['observed_pdf_pages'] <= MAX_PDF_PAGES
            or not re.fullmatch('[a-f0-9]{64}', str(policy.get('verified_pdf_sha256', '')))):
        raise RuntimeError('Coverage continuation PDF review is incomplete')
    reservation = cache / (METHOD + '-used.json')
    record = {**required, 'identity': identity,
              'policy_sha256': digest(json.dumps(policy, sort_keys=True, ensure_ascii=False))}
    if reservation.exists():
        saved = checked(reservation)
        if any(saved.get(k) != v for k,v in record.items()):
            raise RuntimeError('Coverage continuation reservation differs')
    else:
        # No pre-existing report or plan can be replaced by this authorization.
        if (folder/'reporting.json').exists() or (folder/'evidence-coverage-v2/plan.json').exists():
            raise RuntimeError('Coverage continuation requires untouched reporting stages')

    def run(send):
        if not reservation.exists():
            with reservation.open('x', encoding='utf-8') as stream:
                json.dump({**record, 'run_id': os.getenv('GITHUB_RUN_ID', 'local'),
                    'reserved_at': datetime.now(timezone.utc).isoformat()}, stream, indent=2)
        def bounded_send(request):
            stage = request.get('text', {}).get('format', {}).get('name')
            if stage not in {'reporting_plan', 'reporting'} or request.get('tools'):
                raise RuntimeError('Coverage continuation cannot research or select new sources')
            from release_coverage_plan import evidence_identity, validate_documents
            evidence = _cached(folder/'evidence-coverage-v2/sources.json', evidence_identity(identity, catalog))
            if evidence is None:
                raise RuntimeError('Coverage continuation requires complete retrieved evidence')
            documents = evidence['documents'];validate_documents(documents, catalog)
            pdf = [d for d in documents if d['source_id'] == policy['source_id']]
            if (len(pdf) != 1 or pdf[0].get('sha256') != policy['verified_pdf_sha256']
                    or pdf[0].get('extraction', {}).get('page_count') != policy['observed_pdf_pages']):
                raise RuntimeError('Coverage continuation PDF differs from the reviewed document')
            marker = cache / (METHOD + '-' + stage + '-reserved.json')
            with marker.open('x', encoding='utf-8') as stream:
                json.dump({'stage': stage, 'publication_authorized': False,
                    'request_sha256': digest(json.dumps(request, sort_keys=True, ensure_ascii=False)),
                    'reserved_at': datetime.now(timezone.utc).isoformat()}, stream)
            return send(request)
        return staged_request(payload, bounded_send, cache)
    return run
