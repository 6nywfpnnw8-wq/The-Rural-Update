"""Metadata-bound prose recovery; spent requests and release gates stay intact."""
from __future__ import annotations
import hashlib,json,os
from datetime import datetime,timezone
from pathlib import Path

MARKER='narration-prose-pattern-resume-used.json'
FAILURE_RUN=39484398316
PLAIN_MARKER='narration-plain-prose-resume-used.json'
PLAIN_FAILURE_RUN=39485880713


def generation_schema(count):
    """Avoid a large word-count regex in constrained decoding.

    The unchanged validate_prose function still checks the exact word range,
    finished ending, URLs, markup and placeholders before any section is cached.
    """
    from release_prose import prose_schema
    schema=prose_schema(count)
    schema['properties']['text'].pop('pattern',None)
    return schema


def extra_attempts(cache,identity,section_identity):
    p=Path(cache)/MARKER
    if not p.exists():return 1
    d=json.loads(p.read_text())
    if (d.get('identity')!=identity or d.get('section_identity')!=section_identity
        or d.get('section')!='developments-0' or d.get('maximum_extra_section_requests')!=2
        or d.get('publication_authorized') is not False):
        raise RuntimeError('Invalid prose-pattern recovery marker')
    p=Path(cache)/PLAIN_MARKER
    if not p.exists():return 2
    d=json.loads(p.read_text())
    if (d.get('edition_date')!=Path(cache).name or d.get('identity')!=identity
        or d.get('section_identity')!=section_identity or d.get('section')!='developments-0'
        or d.get('maximum_extra_section_requests')!=3
        or d.get('maximum_total_section_requests')!=20
        or d.get('publication_authorized') is not False
        or d.get('failure_run_id')!=PLAIN_FAILURE_RUN):
        raise RuntimeError('Invalid plain-prose recovery marker')
    return 3


def reserve(cache,plan,engine,load,validate_report):
    from release_sectioned_narration import assert_retained_stages,_ledger,MAX_REQUESTS,METHOD
    cache=Path(cache);p=cache/MARKER
    if p.exists():return reserve_plain(cache,plan,engine,load,validate_report)
    if plan.get('maximum_prose_pattern_resumes')!=1:return False
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


def reserve_plain(cache,plan,engine,load,validate_report):
    """One last section request after the verified zero-output API response.

    This is an explicit October 20 repair, not an automatic extension of future
    days' limits. It reuses all three source/reporting files, preserves the four
    spent first-development requests, and cannot reopen an audit or restart news.
    """
    from release_sectioned_narration import assert_retained_stages,_ledger,MAX_REQUESTS,METHOD
    cache=Path(cache);p=cache/PLAIN_MARKER
    if plan.get('maximum_plain_prose_resumes')!=1 or p.exists():return False
    if (plan.get('edition_date')!='2026-10-20' or cache.name!='2026-10-20'
        or plan.get('plain_prose_failure_run_id')!=PLAIN_FAILURE_RUN
        or plan.get('plain_prose_maximum_extra_section_requests')!=3):
        raise RuntimeError('Invalid plain-prose recovery authorization')
    prior_path=cache/MARKER
    if not prior_path.exists():return False
    prior=json.loads(prior_path.read_text())
    if (prior.get('edition_date')!=plan['edition_date'] or prior.get('section')!='developments-0'
        or prior.get('maximum_extra_section_requests')!=2
        or prior.get('publication_authorized') is not False):return False
    identity=prior.get('identity');section_identity=prior.get('section_identity')
    if not isinstance(section_identity,str) or not __import__('re').fullmatch(r'[a-f0-9]{64}',section_identity):
        raise RuntimeError('Invalid retained section identity')
    assert_retained_stages(cache,engine,identity)
    folder=cache/engine
    if any((cache/n).exists() for n in ['audit.json','audit-bound.json','approved.json']) or (folder/'narration.json').exists():return False
    rows=json.loads((cache/'api-responses.json').read_text()).get('responses',[])
    if not rows:return False
    last=rows[-1]
    if not (str(last.get('run_id'))==str(PLAIN_FAILURE_RUN)
        and last.get('stage')=='narration_section' and last.get('status')=='incomplete'
        and last.get('incomplete_reason')=='max_output_tokens'
        and last.get('requested_output_limit')==4000
        and last.get('input_tokens')==0 and last.get('output_tokens')==0
        and last.get('visible_characters')==0):return False
    values={n:load(folder/(n+'.json'),identity) for n in ['discovery','sources','reporting']}
    if any(v is None for v in values.values()):return False
    if values['reporting'].get('edition',{}).get('edition_date')!=plan['edition_date']:return False
    validate_report(values)
    path=folder/METHOD/section_identity/'attempts.json'
    state=_ledger(path,section_identity,{'developments-0':2})
    if state['requests']>=MAX_REQUESTS or state['attempts'].get('developments-0')!=4:return False
    if (path.parent/'developments-0.json').exists():return False
    record={'edition_date':plan['edition_date'],'identity':identity,'section_identity':section_identity,
        'section':'developments-0','maximum_extra_section_requests':3,'maximum_total_section_requests':MAX_REQUESTS,
        'failure_run_id':PLAIN_FAILURE_RUN,'original_attempt_ledger_unchanged':True,
        'section_ledger_unchanged':True,'publication_authorized':False,
        'new_discovery_prohibited':True,'new_reporting_prohibited':True,
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
