"""Source-only repair after a recorded retrieval failure, never factual approval.

The reviewed plan pins the original candidate, failed run and exact old URLs.
Every reporting/narration byte and reference ID stays unchanged. Replacement
sources must be retrieved again and the caller must run a new evidence audit.
"""
from __future__ import annotations
import copy,json,re,os
from datetime import datetime,timezone
from pathlib import Path
from release_core import read_json,write_json,validate_edition,allowed_url,canonical_url
from release_resume import _read_snapshot


def take_reference_repair(cache:Path,expected:str,root:Path):
    from release_editorial import fingerprint
    cache=Path(cache);path=Path(root)/(expected+'-exact.json')
    if not path.exists():return None
    if path.is_symlink() or path.stat().st_size>16000:
        raise ValueError('Reference repair metadata is unsafe')
    plan=read_json(path)
    if (plan.get('schema_version')!=1 or plan.get('edition_date')!=expected
        or plan.get('publication_authorized') is not False
        or plan.get('maximum_audits')!=1 or plan.get('additional_generation_calls')!=0):
        raise ValueError('Reference repair cannot approve publication or generation')
    sha=plan.get('base_candidate_sha256','');run=str(plan.get('failed_run_id',''))
    if not re.fullmatch('[a-f0-9]{64}',sha) or not re.fullmatch('[0-9]+',run):
        raise ValueError('Reference repair identity is invalid')
    for name in ('approved.json','audit.json','audit-bound.json','editorial-recovery-attempt.json',
                 'style-recovery-attempt.json','source-recovery-attempt.json'):
        if (cache/name).exists():
            raise RuntimeError('Reference repair cannot reopen completed or reserved evidence review')
    content=read_json(cache/'validation-content.json',{})
    failure=read_json(cache/'validation-exact-source-retrieval.json',{})
    evidence=read_json(cache/'source-evidence.json',{})
    if (content.get('edition_date')!=expected or content.get('passed') is not True
        or str(content.get('run_id'))!=run or content.get('snapshot',{}).get('candidate_sha256')!=sha
        or failure.get('edition_date')!=expected or failure.get('passed') is not False
        or failure.get('stage')!='exact-source-retrieval' or str(failure.get('run_id'))!=run
        or evidence.get('edition_date')!=expected or evidence.get('candidate_sha256')!=sha
        or evidence.get('complete') is not False):
        raise ValueError('Reference repair does not match the recorded retrieval failure')
    wanted={(x['source_id'],x['url']) for x in plan.get('expected_failed_sources',[])}
    observed={(x.get('source_id'),x.get('url')) for x in evidence.get('failures',[])}
    if not wanted or wanted!=observed:raise ValueError('Reference repair failure inventory differs')
    if (cache/'candidates').is_symlink():raise ValueError('Unsafe retained candidate directory')
    snapshot=_read_snapshot(cache/'candidates'/('content-'+sha[:16]+'.json'),expected,'content')
    if not snapshot or snapshot['candidate_sha256']!=sha:
        raise ValueError('Reference repair requires the exact original retained candidate')
    original=snapshot['candidate'];candidate=copy.deepcopy(original)
    patches=plan.get('source_corrections')
    if not isinstance(patches,list) or not 1<=len(patches)<=3:
        raise ValueError('Reference repair requires a bounded explicit source list')
    applied=set();changes=[]
    for patch in patches:
        if set(patch)!={'source_id','previous_url','replacement'}:
            raise ValueError('Reference correction fields are invalid')
        source_id=patch['source_id'];replacement=patch['replacement']
        matches=[s for s in candidate['sources'] if s['id']==source_id]
        if (source_id in applied or len(matches)!=1 or matches[0]['url']!=patch['previous_url']
            or not isinstance(replacement,dict) or set(replacement)!={'id','title','url','published_date'}
            or replacement['id']!=source_id or not allowed_url(replacement['url'])):
            raise ValueError('Reference correction cannot alter IDs or unexpected sources')
        changes.append({'source_id':source_id,'previous_url':matches[0]['url'],'url':replacement['url']})
        matches[0].update(replacement);applied.add(source_id)
    if not {x[0] for x in wanted}.issubset(applied):
        raise ValueError('The recorded failed sources were not corrected')
    if {k:v for k,v in candidate.items() if k!='sources'}!={k:v for k,v in original.items() if k!='sources'}:
        raise ValueError('Reference repair changed reporting or narration')
    if len({canonical_url(s['url']) for s in candidate['sources']})!=len(candidate['sources']):
        raise ValueError('Duplicate source URLs cannot serve as independent references')
    validate_edition(candidate,expected)
    record={'schema_version':1,'edition_date':expected,'base_candidate_sha256':sha,
        'candidate_sha256':fingerprint(candidate),'source_corrections':changes,
        'maximum_audits':1,'evidence_audit_reserved':True,'publication_authorized':False,
        'additional_research_generation_calls':0,'narration_unchanged':True,
        'run_id':os.getenv('GITHUB_RUN_ID','local'),'reserved_at':datetime.now(timezone.utc).isoformat()}
    # The same exclusive marker used by the existing reviewed-audit path prevents
    # an alternate entry point from granting this candidate repeated audits.
    with (cache/'editorial-recovery-attempt.json').open('x',encoding='utf-8') as f:
        json.dump(record,f,indent=2)
    write_json(cache/'validation-reference-repair.json',record)
    return candidate,set()  # Operator review is not invented web-retrieval provenance.
