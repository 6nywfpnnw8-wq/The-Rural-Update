"""Use an explicitly reviewed exact-passage assignment, then independently audit.

Both rejected model plans stay spent and retained. This cannot research, replan,
change source records, approve claims, or repeat a reporting submission.
"""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
from datetime import datetime,timezone

from release_core import digest
from release_retained_app import COMPLETION,_read,_checkpoint,_bound_file
from release_publication import app_only
from release_research import ENGINE,_save,staged_request,observed_source_urls,validate_source_catalog
from release_coverage_plan import METHOD as COVERAGE,evidence_identity,validate_documents,validate_plan,compile_plan,CoverageError

METHOD='reviewed-coverage-reporting-v1'


def prepare(cache,expected,payload,policy_root):
    cache=Path(cache);policy_root=Path(policy_root);path=policy_root/(expected+'.json')
    if not path.exists():return None
    policy=_read(path)
    required={'schema_version':1,'edition_date':expected,'method':METHOD,
        'maximum_reporting_requests':1,'additional_coverage_plan_requests':0,
        'maximum_total_coverage_plan_requests':2,'new_discovery_permitted':False,
        'source_selection_model_requests':0,'research_counter_reset':False,
        'independent_editorial_review_required':True,'podcast_generation_permitted':False,
        'publication_authorized':False}
    if (not app_only(expected) or cache.name!=expected
            or any(type(policy.get(k)) is not type(v) or policy.get(k)!=v for k,v in required.items())
            or os.getenv('RURAL_UPDATE_STRUCTURED_REVIEW')!='true'):
        raise ValueError('Invalid reviewed reporting assignment or independent review disabled')
    ledger=_bound_file(cache/'attempts.json',policy.get('attempt_ledger_sha256'))
    if ledger!={'attempts':2}:raise ValueError('Reviewed reporting requires the original research ledger')
    if any((cache/name).exists() for name in ('approved.json','audit.json','audit-bound.json','editorial-loop-v1')):
        raise ValueError('Reviewed reporting cannot replace started editorial work')
    failure=_bound_file(cache/'validation-research-coverage.json',policy.get('failure_report_sha256'))
    if (failure.get('edition_date')!=expected or failure.get('passed') is not False
            or failure.get('rule')!='evidence_coverage' or failure.get('api_stage')!='reporting_plan'
            or str(failure.get('run_id'))!=str(policy.get('failure_run_id'))):
        raise ValueError('Reviewed reporting does not match the retained plan failure')
    parent_policy=_read(policy_root.parent/'app-evidence-recovery'/(expected+'.json'))
    parent_digest=digest(json.dumps(parent_policy,sort_keys=True,ensure_ascii=False))
    if parent_digest!=policy.get('parent_policy_sha256') or parent_policy.get('method')!=COMPLETION:
        raise ValueError('Reviewed reporting parent authorization differs')
    parent=_bound_file(cache/(COMPLETION+'-used.json'),policy.get('parent_reservation_sha256'))
    if (parent.get('policy_sha256')!=parent_digest or parent.get('publication_authorized') is not False
            or parent.get('maximum_total_reporting_plan_requests')!=2
            or parent.get('maximum_total_reporting_requests')!=1):
        raise ValueError('Reviewed reporting cannot change the consumed plan budget')
    _bound_file(cache/'retained-source-coverage-v1-reporting_plan-reserved.json',
                parent_policy.get('prior_reporting_plan_reservation_sha256'))
    original=digest(json.dumps({'engine':ENGINE,'model':payload['model'],'context':payload['input']},sort_keys=True))
    if original!=parent.get('original_identity'):
        raise ValueError('Reviewed reporting request differs from the retained context')
    payload=copy.deepcopy(payload)
    notes=parent_policy.get('editorial_notes',[])
    if notes:payload['input']+='\nRetained-plan review findings (editorial comments, not source evidence):\n'+'\n'.join(notes)
    identity=digest(json.dumps({'engine':ENGINE,'model':payload['model'],'context':payload['input']},sort_keys=True))
    if identity!=policy.get('parent_identity') or identity!=parent.get('target_identity'):
        raise ValueError('Reviewed reporting parent identity differs')
    parent_workspace=cache/COMPLETION/expected;folder=parent_workspace/ENGINE
    submitted=_bound_file(parent_workspace/'reporting_plan-reserved.json',policy.get('parent_plan_request_sha256'))
    if submitted.get('stage')!='reporting_plan' or submitted.get('publication_authorized') is not False:
        raise ValueError('Reviewed reporting requires the consumed second plan request')
    if ((parent_workspace/'reporting-reserved.json').exists() or (folder/'reporting.json').exists()
            or (cache/'retained-source-coverage-v1-reporting-reserved.json').exists()):
        raise ValueError('Reviewed reporting cannot reopen a spent reporting request')
    discovery=_checkpoint(folder/'discovery.json',identity,policy.get('discovery_sha256'))
    selected=_checkpoint(folder/'sources.json',identity,policy.get('sources_sha256'))
    catalog=validate_source_catalog(selected['sources'],observed_source_urls(discovery))
    bound=evidence_identity(identity,catalog)
    evidence=_checkpoint(folder/COVERAGE/'sources.json',bound,policy.get('evidence_sha256'))
    documents=evidence['documents'];validate_documents(documents,catalog)
    plan_identity=digest(bound+digest(json.dumps(documents,sort_keys=True,ensure_ascii=False)))
    rejected=_checkpoint(folder/COVERAGE/'plan.json',plan_identity,policy.get('rejected_plan_sha256'))
    try:validate_plan(rejected['plan'],catalog,documents)
    except CoverageError:pass
    else:raise ValueError('Reviewed reporting requires a rejected original plan')
    reviewed=compile_plan(json.dumps(policy['reviewed_plan'],ensure_ascii=False),catalog,documents)
    validate_plan(reviewed,catalog,documents)
    if digest(json.dumps(reviewed,sort_keys=True,ensure_ascii=False))!=policy.get('reviewed_plan_sha256'):
        raise ValueError('Reviewed reporting assignment hash differs')
    record={**required,'identity':identity,'reviewed_plan_sha256':policy['reviewed_plan_sha256'],
        'policy_sha256':digest(json.dumps(policy,sort_keys=True,ensure_ascii=False)),
        'original_attempt_ledger_sha256':policy['attempt_ledger_sha256']}
    marker=cache/(METHOD+'-used.json');replay=marker.exists();workspace=cache/METHOD/expected
    if replay:
        saved=_read(marker)
        if any(saved.get(k)!=v for k,v in record.items()):raise ValueError('Reviewed reporting reservation differs')
    else:
        target=workspace/ENGINE
        if target.exists():raise ValueError('Unreserved reviewed reporting workspace exists')
        _save(target/'discovery.json',identity,discovery)
        _save(target/'sources.json',identity,selected)
        _save(target/COVERAGE/'sources.json',bound,evidence)
        _save(target/COVERAGE/'plan.json',plan_identity,{'plan':reviewed,'usage':None,
            'review_method':METHOD,'publication_authorized':False})

    def run(send):
        if not replay:
            with marker.open('x',encoding='utf-8') as stream:
                json.dump({**record,'run_id':os.getenv('GITHUB_RUN_ID','local'),
                    'reserved_at':datetime.now(timezone.utc).isoformat()},stream,indent=2)
        def bounded_send(request):
            name=request.get('text',{}).get('format',{}).get('name')
            if replay or name!='reporting' or request.get('tools'):
                raise RuntimeError('Reviewed reporting cannot research, replan or submit another request')
            with (workspace/'reporting-reserved.json').open('x',encoding='utf-8') as stream:
                json.dump({'stage':'reporting','publication_authorized':False,
                    'request_sha256':digest(json.dumps(request,sort_keys=True,ensure_ascii=False))},stream)
            return send(request)
        try:return staged_request(payload,bounded_send,workspace)
        finally:
            if digest((cache/'attempts.json').read_bytes())!=record['original_attempt_ledger_sha256']:
                raise RuntimeError('Original research ledger changed during reviewed reporting')
    return run
