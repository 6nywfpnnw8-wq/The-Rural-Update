"""One reviewed structural recheck of retained prose, never an editorial approval.

This does not generate, pad, truncate, or change a word. A wider internal section
range still keeps every possible full episode inside 1700-2000 words. Source
retrieval, independent evidence audit and complete-audio checks remain downstream.
"""
from __future__ import annotations
import hashlib,json,os,re
from datetime import datetime,timezone
from pathlib import Path

DAY='2026-10-20'
FAILURE_RUN='39490951990'
MARKER='retained-section-recheck-used.json'
POLICY_ROOT=Path(__file__).resolve().parents[1]/'repair-authorizations'


def reserve_recheck(cache,plan,engine,load,validate_report):
    cache=Path(cache)
    policy_file=POLICY_ROOT/(DAY+'-length.json')
    if cache.name!=DAY or plan.get('edition_date')!=DAY or not policy_file.exists():return False
    policy=json.loads(policy_file.read_text())
    required={'edition_date':DAY,'failure_run_id':int(FAILURE_RUN),
        'section':'developments-0','maximum_revalidations':1,
        'additional_generation_requests':0,'publication_authorized':False,
        'observed_words':287,'observed_characters':2156,'observed_attempt':5}
    if any(policy.get(k)!=v for k,v in required.items()):
        raise RuntimeError('Invalid retained-section revalidation policy')
    marker=cache/MARKER
    if marker.exists():return False
    from release_sectioned_narration import assert_retained_stages,_ledger,MAX_REQUESTS,METHOD
    from release_prose import FORMAT,validate_prose
    from release_prose_pattern import PLAIN_MARKER,extra_attempts
    from release_research import _save
    prior_path=cache/PLAIN_MARKER
    if not prior_path.exists():return False
    prior=json.loads(prior_path.read_text())
    identity=prior.get('identity');sid=prior.get('section_identity')
    if (prior.get('edition_date')!=DAY or prior.get('section')!='developments-0'
        or prior.get('publication_authorized') is not False):return False
    if not isinstance(sid,str) or not re.fullmatch('[a-f0-9]{64}',sid):
        raise RuntimeError('Invalid retained narration identity')
    if extra_attempts(cache,identity,sid)!=3:return False
    if not assert_retained_stages(cache,engine,identity):return False
    folder=cache/engine;work=folder/METHOD/sid
    if any((cache/n).exists() for n in ('approved.json','audit.json','audit-bound.json')):
        return False
    if (folder/'narration.json').exists() or (work/'developments-0.json').exists():return False
    values={name:load(folder/(name+'.json'),identity) for name in ('discovery','sources','reporting')}
    if any(value is None for value in values.values()):return False
    if values['reporting'].get('edition',{}).get('edition_date')!=DAY:return False
    validate_report(values)
    records=json.loads((cache/'api-responses.json').read_text()).get('responses',[])
    if not records:return False
    last=records[-1]
    if not (str(last.get('run_id'))==FAILURE_RUN and last.get('status')=='completed'
        and last.get('stage')=='narration_section' and last.get('requested_output_limit')==4000
        and last.get('output_tokens')==394 and last.get('visible_characters')==2167):return False
    checks=json.loads((cache/'validation-narration-sections.json').read_text()).get('sections',[])
    if not checks:return False
    check=checks[-1]
    expected={'section':'developments-0','attempt':5,'word_count':287,'characters':2156,
        'passed':False,'rule':'section_word_count','publication_authorized':False,'run_id':FAILURE_RUN}
    if any(check.get(k)!=v for k,v in expected.items()):return False
    ledger=work/'attempts.json';original_ledger=ledger.read_bytes()
    state=_ledger(ledger,sid,{'developments-0':3})
    if state['attempts'].get('developments-0')!=5 or state['requests']>=MAX_REQUESTS:return False
    matches=[];paths=list((cache/'section-candidates').glob('*.json'))
    if len(paths)>100:raise RuntimeError('Retained section inventory exceeds recheck limit')
    for path in paths:
        if path.stat().st_size>50000:continue
        value=json.loads(path.read_text())
        if value.get('section')!='developments-0' or value.get('publication_authorized') is not False:continue
        result=value.get('candidate');text=result.get('text') if isinstance(result,dict) else None
        if not isinstance(text,str) or len(text)!=2156 or len(text.split())!=287:continue
        encoded=json.dumps(result,ensure_ascii=False,sort_keys=True).encode()
        if path.stem!=hashlib.sha256(encoded).hexdigest():
            raise RuntimeError('Retained candidate integrity check failed')
        validate_prose(result,310)
        matches.append((path,result))
    if len(matches)!=1:
        raise RuntimeError('Exactly one original retained passage is required; no replacement generated')
    path,result=matches[0]
    record={**required,'identity':identity,'section_identity':sid,
        'candidate_sha256':path.stem,'section_ledger_sha256':hashlib.sha256(original_ledger).hexdigest(),
        'original_attempt_ledger_unchanged':True,'section_ledger_unchanged':True,
        'new_discovery_prohibited':True,'new_reporting_prohibited':True,
        'maximum_total_section_requests':MAX_REQUESTS,
        'reserved_at':datetime.now(timezone.utc).isoformat(),'run_id':os.getenv('GITHUB_RUN_ID','local')}
    try:
        with marker.open('x') as f:json.dump(record,f,indent=2)
    except FileExistsError:return False
    _save(work/'developments-0.json',sid,{'section':'developments-0','format':FORMAT,
        'result':result,'usage':None,'retained_candidate_sha256':path.stem})
    if ledger.read_bytes()!=original_ledger:raise RuntimeError('Recheck changed an attempt ledger')
    (cache/'validation-retained-section-recheck.json').write_text(json.dumps(record,indent=2))
    return True
