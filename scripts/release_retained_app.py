"""One reviewed app continuation from retained discovery and exact source hashes.

Never resets the research ledger, performs discovery, repeats an ambiguous request,
or approves publication. Added sources must already occur in retained tool events.
"""
from __future__ import annotations
import copy
import json
import os
import re
from datetime import datetime,timezone
from pathlib import Path
from release_core import digest,read_json,write_json
from release_publication import app_only
from release_evidence import fetch_source
from release_coverage_plan import METHOD as COVERAGE, evidence_identity,validate_documents,validate_plan,CoverageError
from release_research import ENGINE,_cached,_save,observed_source_urls,validate_source_catalog,staged_request
from release_source_selection import source_choices

METHOD='app-pdf-evidence-recovery-v1'


def _read(path):
    path=Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents) or not path.is_file() or path.stat().st_size>2097152:
        raise ValueError('Unsafe retained app recovery checkpoint')
    return read_json(path)


def _checkpoint(path,identity,sha):
    raw=_read(path)
    if not isinstance(sha,str) or not re.fullmatch('[a-f0-9]{64}',sha) or raw.get('sha256')!=sha:
        raise ValueError('Retained app recovery checkpoint differs from reviewed hash')
    value=_cached(path,identity)
    if value is None:raise ValueError('Retained app recovery checkpoint identity differs')
    return value


def prepare_continuation(cache,expected,payload,policy_root):
    """Return a bounded reporting callable, or None for the normal publisher path."""
    cache=Path(cache);path=Path(policy_root)/(expected+'.json')
    if not app_only(expected) or not path.exists():return None
    if read_json(cache/'attempts.json')!={'attempts':2}:return None
    policy=_read(path)
    required={'schema_version':1,'edition_date':expected,'method':METHOD,
              'maximum_recoveries':1,'maximum_reporting_plan_requests':1,
              'maximum_reporting_requests':1,'new_discovery_permitted':False,
              'source_selection_model_requests':0,'research_counter_reset':False,
              'independent_editorial_review_required':True,'podcast_generation_permitted':False,
              'publication_authorized':False}
    if cache.name!=expected or any(policy.get(k)!=v for k,v in required.items()):
        raise ValueError('Invalid retained app continuation policy')
    if any(type(policy.get(k)) is not int for k in ('schema_version','maximum_recoveries',
            'maximum_reporting_plan_requests','maximum_reporting_requests','source_selection_model_requests')):
        raise ValueError('Invalid retained app continuation request limits')
    if any((cache/name).exists() for name in ('audit.json','audit-bound.json','approved.json',
              'editorial-loop-v1/original.json','coverage-plan-repair-authorized.json','corrective-generation-used.json')):
        raise ValueError('Retained app continuation cannot replace started editorial work')
    failure_path=cache/'validation-research-coverage.json'
    failure=_read(failure_path)
    if (digest(failure_path.read_bytes())!=policy.get('failure_report_sha256')
            or failure.get('edition_date')!=expected or failure.get('passed') is not False
            or failure.get('rule')!='evidence_coverage' or failure.get('api_stage')!='reporting_plan'
            or str(failure.get('run_id'))!=str(policy.get('failure_run_id'))):
        raise ValueError('Retained app continuation does not match the recorded coverage failure')
    original=policy.get('original_identity','')
    if not re.fullmatch('[a-f0-9]{64}',original):raise ValueError('Invalid retained discovery identity')
    folder=cache/ENGINE
    discovery=_checkpoint(folder/'discovery.json',original,policy.get('discovery_sha256'))
    selected=_checkpoint(folder/'sources.json',original,policy.get('sources_sha256'))
    if not discovery.get('web_search_items'):raise ValueError('Retained app continuation has no observed retrieval events')
    observed=observed_source_urls(discovery)
    catalog=validate_source_catalog(selected['sources'],observed)
    bound=evidence_identity(original,catalog)
    evidence=_checkpoint(folder/COVERAGE/'sources.json',bound,policy.get('coverage_evidence_sha256'))
    documents=evidence['documents'];validate_documents(documents,catalog)
    plan_identity=digest(bound+digest(json.dumps(documents,sort_keys=True,ensure_ascii=False)))
    old_plan=_checkpoint(folder/COVERAGE/'plan.json',plan_identity,policy.get('coverage_plan_sha256'))
    try:validate_plan(old_plan['plan'],catalog,documents)
    except CoverageError:pass
    else:raise ValueError('Retained app continuation requires a rejected coverage plan')
    additions=policy.get('added_sources')
    if not isinstance(additions,list) or not 1<=len(additions)<=2:
        raise ValueError('Retained app continuation permits at most two reviewed source additions')
    choices=source_choices(observed)
    fields={'id','title','url','published_date','sha256','text_sha256'}
    appended=[]
    for source in additions:
        if (not isinstance(source,dict) or set(source)!=fields or choices.get(source['id'])!=source['url']
                or source['id'] in {s['id'] for s in catalog}):
            raise ValueError('Added source was not observed in the retained discovery')
        for key in ('sha256','text_sha256'):
            if not isinstance(source[key],str) or not re.fullmatch('[a-f0-9]{64}',source[key]):
                raise ValueError('Added source has no reviewed content hash')
        appended.append({key:source[key] for key in ('id','title','url','published_date')})
    augmented=validate_source_catalog(copy.deepcopy(catalog)+appended,observed)
    notes=policy.get('editorial_notes',[])
    if not isinstance(notes,list) or len(notes)>6 or any(not isinstance(n,str) or len(n)>1000 for n in notes):
        raise ValueError('Invalid retained app editorial review notes')
    payload=copy.deepcopy(payload)
    if notes:
        payload['input']+='\nRetained-plan review findings (editorial comments, not source evidence):\n'+'\n'.join(notes)
    identity=digest(json.dumps({'engine':ENGINE,'model':payload['model'],'context':payload['input']},sort_keys=True))
    record={**required,'policy_sha256':digest(json.dumps(policy,sort_keys=True,ensure_ascii=False)),
            'original_identity':original,'target_identity':identity,
            'original_attempt_ledger_sha256':digest((cache/'attempts.json').read_bytes())}
    marker=cache/(METHOD+'-used.json');replay=marker.exists()
    workspace=cache/METHOD/expected
    if replay:
        saved=_read(marker)
        if any(saved.get(k)!=v for k,v in record.items()):
            raise ValueError('Retained app continuation reservation differs')
    else:
        documents=copy.deepcopy(documents)
        for source in additions:
            document=fetch_source(source['url'])
            if (document.get('sha256')!=source['sha256'] or document.get('text_sha256')!=source['text_sha256']
                    or document.get('content_type')!='application/pdf'):
                raise ValueError('Added PDF differs from its reviewed evidence')
            document['source_id']=source['id'];documents.append(document)
        validate_documents(documents,augmented)
        target=workspace/ENGINE
        if target.exists():raise ValueError('Unreserved app continuation workspace already exists')
        _save(target/'discovery.json',identity,copy.deepcopy(discovery))
        _save(target/'sources.json',identity,{'sources':augmented,'usage':None,'selection_method':METHOD})
        target_bound=evidence_identity(identity,augmented)
        _save(target/COVERAGE/'sources.json',target_bound,{'documents':documents})
        (workspace/'original-validation-research-coverage.json').write_bytes(failure_path.read_bytes())
        (workspace/'original-attempts.json').write_bytes((cache/'attempts.json').read_bytes())
        migrated=copy.deepcopy(old_plan['plan'])
        for group in ('stories','signals'):
            for item in migrated[group].values():
                if item is not None:
                    item['source_anchors'].update({s['id']:None for s in appended})
        target_plan_identity=digest(target_bound+digest(json.dumps(documents,sort_keys=True,ensure_ascii=False)))
        _save(target/COVERAGE/'plan.json',target_plan_identity,{'plan':migrated,'usage':None,'snapshot':None})
        write_json(workspace/'coverage-plan-repair-authorized.json',{
            'schema_version':1,'edition_date':expected,'identity':identity,
            'coverage_plan_identity':target_plan_identity,'maximum_coverage_plan_repairs':1,
            'publication_authorized':False,'original_attempt_ledger_unchanged':True,
            'new_discovery_prohibited':True,'new_source_selection_prohibited':True})
        write_json(workspace/'coverage-source-evidence.json',{'method':COVERAGE,'complete':True,
            'publication_authorized':False,'sources':[{k:v for k,v in d.items() if k!='text'} for d in documents],
            'failures':[]})

    def run(send):
        if not replay:
            marker.parent.mkdir(parents=True,exist_ok=True)
            with marker.open('x',encoding='utf-8') as stream:
                json.dump({**record,'run_id':os.getenv('GITHUB_RUN_ID','local'),
                    'reserved_at':datetime.now(timezone.utc).isoformat()},stream,indent=2)
        def bounded_send(request):
            name=request.get('text',{}).get('format',{}).get('name')
            if replay or name not in {'reporting_plan','reporting'} or request.get('tools'):
                raise RuntimeError('Retained app continuation cannot submit another request or perform discovery')
            reservation=workspace/(name+'-reserved.json')
            try:
                with reservation.open('x',encoding='utf-8') as stream:
                    json.dump({'publication_authorized':False,'stage':name,
                        'request_sha256':digest(json.dumps(request,sort_keys=True,ensure_ascii=False))},stream)
            except FileExistsError:
                raise RuntimeError('Retained app continuation request already reserved') from None
            return send(request)
        try:return staged_request(payload,bounded_send,workspace)
        finally:
            if digest((cache/'attempts.json').read_bytes())!=record['original_attempt_ledger_sha256']:
                raise RuntimeError('Original research attempt ledger changed during app continuation')
    return run
