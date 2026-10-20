"""One metadata-bound compact-prose retry; all previous requests remain spent."""
from __future__ import annotations
import hashlib,json,os
from datetime import datetime,timezone
from pathlib import Path

MARKER='narration-prose-pattern-resume-used.json'
FAILURE_RUN=39484398316


def extra_attempts(cache,identity,section_identity):
    p=Path(cache)/MARKER
    if not p.exists():return 1
    d=json.loads(p.read_text())
    if (d.get('identity')!=identity or d.get('section_identity')!=section_identity
        or d.get('section')!='developments-0' or d.get('maximum_extra_section_requests')!=2
        or d.get('publication_authorized') is not False):
        raise RuntimeError('Invalid prose-pattern recovery marker')
    return 2


def reserve(cache,plan,engine,load,validate_report):
    from release_sectioned_narration import assert_retained_stages,_ledger,MAX_REQUESTS,METHOD
    cache=Path(cache);p=cache/MARKER
    if plan.get('maximum_prose_pattern_resumes')!=1 or p.exists():return False
    if (plan.get('prose_pattern_failure_run_id')!=FAILURE_RUN
        or plan.get('prose_pattern_maximum_extra_section_requests')!=2):
        raise RuntimeError('Invalid prose-pattern recovery authorization')
    prior=json.loads((cache/'narration-prose-resume-used.json').read_text())
    if prior.get('edition_date')!=plan['edition_date'] or prior.get('section')!='developments-0':return False
    identity=prior.get('identity');assert_retained_stages(cache,engine,identity)
    folder=cache/engine
    if any((cache/n).exists() for n in ['audit.json','audit-bound.json','approved.json']) or (folder/'narration.json').exists():return False
    rows=json.loads((cache/'api-responses.json').read_text()).get('responses',[])
    if not rows:return False
    last=rows[-1]
    if (str(last.get('run_id'))!=str(FAILURE_RUN) or last.get('stage')!='narration_section'
        or last.get('status')!='completed' or last.get('requested_output_limit')!=4000):return False
    values={n:load(folder/(n+'.json'),identity) for n in ['discovery','sources','reporting']}
    if any(v is None for v in values.values()):return False
    if values['reporting'].get('edition',{}).get('edition_date')!=plan['edition_date']:return False
    validate_report(values)
    path=folder/METHOD/prior['section_identity']/'attempts.json'
    state=_ledger(path,prior['section_identity'],{'developments-0':1})
    if state['requests']>=MAX_REQUESTS or state['attempts'].get('developments-0')!=3:return False
    if (path.parent/'developments-0.json').exists():return False
    record={'edition_date':plan['edition_date'],'identity':identity,'section_identity':prior['section_identity'],
        'section':'developments-0','maximum_extra_section_requests':2,'maximum_total_section_requests':MAX_REQUESTS,
        'original_attempt_ledger_unchanged':True,'section_ledger_unchanged':True,'publication_authorized':False,
        'previous_ledger_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'reserved_at':datetime.now(timezone.utc).isoformat(),'run_id':os.getenv('GITHUB_RUN_ID','local')}
    try:
        with p.open('x') as f:json.dump(record,f,indent=2)
    except FileExistsError:return False
    return True


def record_section(cache,label,attempt,result,error=None):
    """Retain unpublished completed sections separately; expose numeric results only."""
    cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
    text=result.get('text') if isinstance(result,dict) else None
    payload=json.dumps(result,ensure_ascii=False,sort_keys=True)
    if len(payload.encode())<=50000:
        folder=cache/'section-candidates';folder.mkdir(exist_ok=True)
        p=folder/(hashlib.sha256(payload.encode()).hexdigest()+'.json')
        p.write_text(json.dumps({'section':label,'candidate':result,'publication_authorized':False},ensure_ascii=False))
    safe={'section_shape','section_characters','section_word_count','section_word_shape','section_spoken_prose','section_sentence_ending'}
    path=cache/'validation-narration-sections.json'
    rows=json.loads(path.read_text()).get('sections',[]) if path.exists() else []
    rows.append({'section':label,'attempt':attempt,'word_count':len(text.split()) if isinstance(text,str) else None,
        'characters':len(text) if isinstance(text,str) else None,'passed':error is None,
        'rule':str(error) if str(error) in safe else ('unrecognized_section_failure' if error else None),
        'publication_authorized':False,'run_id':os.getenv('GITHUB_RUN_ID','local')})
    path.write_text(json.dumps({'sections':rows[-30:],'publication_authorized':False},indent=2))
