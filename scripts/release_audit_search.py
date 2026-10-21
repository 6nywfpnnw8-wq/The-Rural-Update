"""Require real web retrieval and resume only an exact tool-omission failure."""
from __future__ import annotations
import json,os,re
from pathlib import Path
from release_core import read_json,write_json,validate_edition
from release_resume import _read_snapshot

def require_audit_search(payload):
    name=((payload.get('text') or {}).get('format') or {}).get('name')
    if name!='editorial_audit': return payload
    if len(payload.get('tools',[]))!=1 or payload['tools'][0].get('type')!='web_search':
        raise ValueError('Evidence audit must offer exactly the web-search tool')
    return {**payload,'tool_choice':'required'}

def take_tool_omission_recovery(cache:Path,expected:str,root:Path):
    from release_editorial import fingerprint
    cache=Path(cache);path=Path(root)/(expected+'.json')
    if not path.exists():return None
    if path.is_symlink() or path.stat().st_size>8000:raise ValueError('Unsafe tool recovery plan')
    plan=read_json(path)
    if (plan.get('schema_version')!=1 or plan.get('edition_date')!=expected
        or plan.get('publication_authorized') is not False
        or plan.get('maximum_audit_calls')!=1 or plan.get('generation_calls')!=0):
        raise ValueError('Tool recovery cannot authorize publication or generation')
    sha=plan.get('candidate_sha256','');run=str(plan.get('failed_run_id',''))
    if not re.fullmatch('[a-f0-9]{64}',sha) or not re.fullmatch('[0-9]+',run):
        raise ValueError('Invalid tool recovery identity')
    marker=cache/'audit-tool-recovery-used.json'
    if marker.exists() or (cache/'approved.json').exists() or (cache/'audit-bound.json').exists():
        raise RuntimeError('Tool recovery already used or a completed audit exists')
    if (cache/'candidates').is_symlink():raise ValueError('Unsafe candidate directory')
    snapshot=_read_snapshot(cache/'candidates'/('resumed-content-'+sha[:16]+'.json'),expected,'resumed-content')
    checked=read_json(cache/'validation-resumed-content.json',{})
    evidence=read_json(cache/'source-evidence.json',{})
    verdict=read_json(cache/'audit.json',{})
    responses=read_json(cache/'api-responses.json',{}).get('responses',[])
    latest=responses[-1] if responses else {}
    if (not snapshot or snapshot.get('candidate_sha256')!=sha
        or checked.get('edition_date')!=expected or checked.get('passed') is not True
        or str(checked.get('run_id'))!=run or checked.get('snapshot',{}).get('candidate_sha256')!=sha
        or evidence.get('candidate_sha256')!=sha or evidence.get('complete') is not True
        or verdict!={'approved':True,'issues':[]}
        or latest.get('stage')!='editorial_audit' or str(latest.get('run_id'))!=run
        or latest.get('status')!='completed' or latest.get('incomplete_reason') is not None
        or latest.get('output_types',{}).get('web_search_call',0)!=0):
        raise ValueError('This is not the exact recorded audit tool-omission failure')
    candidate=snapshot['candidate'];validate_edition(candidate,expected)
    history=cache/'incomplete-audits'/run
    write_json(history/'audit.json',verdict)
    write_json(history/'response-metadata.json',latest)
    write_json(history/'source-evidence.json',evidence)
    record={'edition_date':expected,'failed_run_id':run,'candidate_sha256':sha,
        'publication_authorized':False,'maximum_audit_calls':1,'generation_calls':0,
        'old_ledgers_preserved':True,'new_search_required':True,'plan_sha256':fingerprint(plan),
        'run_id':os.getenv('GITHUB_RUN_ID','local')}
    with marker.open('x',encoding='utf-8') as f:json.dump(record,f,indent=2)
    write_json(cache/'validation-audit-tool-recovery.json',record)
    return candidate,set()
