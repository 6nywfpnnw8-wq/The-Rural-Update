"""Bounded narration sections; cached words remain compatible with natural prose.

No section generator retrieves new facts or grants editorial approval. Original
stage fingerprints and all existing request ledgers remain authoritative.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

METHOD = 'sectioned-narration-v1'
MAX_REQUESTS = 20
MAX_SECTION_ATTEMPTS = 2
OUTPUT_TOKENS = 4000
SECTION_PLAN = (
    ('opening', None, 60), ('bluf', None, 165),
    ('developments', 0, 310), ('developments', 1, 310),
    ('developments', 2, 310), ('oklahoma', None, 235),
    ('signals', None, 170), ('actions', None, 160),
    ('deadlines', None, 80), ('closing', None, 55),
)


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def word_schema(count: int) -> dict:
    """Legacy format retained solely to validate already cached word arrays."""
    return {'type':'object', 'properties':{'words':{'type':'array',
        'items':{'type':'string','pattern':r'^\S+$'},
        'minItems':count,'maxItems':count}},
        'required':['words'],'additionalProperties':False}


def validate_words(value, count: int) -> str:
    if not isinstance(value, dict) or set(value) != {'words'}:
        raise ValueError('section_shape')
    words = value['words']
    if not isinstance(words,list) or len(words) != count:
        raise ValueError('section_word_count')
    if any(not isinstance(w,str) or not re.fullmatch(r'\S{1,100}',w) for w in words):
        raise ValueError('section_word_shape')
    text = ' '.join(words)
    if re.search(r'https?://|<[^>]*>|\b(?:TODO|TBD)\b',text,re.I):
        raise ValueError('section_spoken_prose')
    if not re.search(r'[.!?][\"\x27\u201d\u2019]?$',text):
        raise ValueError('section_sentence_ending')
    return text


def _ledger(path: Path, identity: str, extra_sections=None) -> dict:
    extra_sections=set(extra_sections or ())
    if not extra_sections.issubset({'developments-1'}):
        raise RuntimeError('Invalid section repair allowance')
    if not path.exists():
        return {'identity':identity,'requests':0,'attempts':{},'publication_authorized':False}
    state=json.loads(path.read_text(encoding='utf-8'))
    attempts=state.get('attempts')
    valid=isinstance(attempts,dict) and all(
        k in {f'{n}-{i}' for n,i,_ in SECTION_PLAN}
        and type(v) is int and 0 <= v <= MAX_SECTION_ATTEMPTS+(1 if k in extra_sections else 0)
        for k,v in attempts.items())
    if (state.get('identity') != identity or state.get('publication_authorized') is not False
        or not valid or type(state.get('requests')) is not int
        or state['requests'] != sum(attempts.values()) or not 0 <= state['requests'] <= MAX_REQUESTS):
        raise RuntimeError('Invalid sectioned narration attempt ledger')
    return state


def _write_ledger(path: Path, state: dict):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8')
    tmp.replace(path)


def generate_sections(reporting: dict, model: str, folder: Path, identity: str,
                      send: Callable, extract: Callable, load: Callable, save: Callable) -> dict:
    from release_prose import generate
    return generate(reporting,model,folder,identity,send,extract,load,save)


def reserve_narration_resume(cache: Path, plan: dict, engine: str,
                             load: Callable, validate_report: Callable) -> bool:
    """A single reviewed continuation of an observed 8000-token narration stop.

    Never authorizes discovery/reporting, replaces a completed narration, or
    reopens an audit rejection. All three prerequisite files must be intact.
    """
    if plan.get('maximum_narration_limit_resumes') != 1:return False
    if plan.get('narration_recovery_method') != METHOD or plan.get('previous_narration_output_limit') != 8000:
        raise RuntimeError('Invalid narration continuation authorization')
    cache=Path(cache); marker=cache/'narration-limit-resume-used.json'
    if marker.exists():return reserve_capacity_resume(cache,plan,engine,load,validate_report)
    records=json.loads((cache/'api-responses.json').read_text()) if (cache/'api-responses.json').exists() else {}
    rows=records.get('responses',[])
    if not rows:return False
    last=rows[-1]
    if not (last.get('stage')=='narration' and last.get('status')=='incomplete'
            and last.get('incomplete_reason')=='max_output_tokens'
            and last.get('requested_output_limit')==8000):return False
    folder=cache/engine
    if any((cache/n).exists() for n in ('audit.json','audit-bound.json','approved.json')) or (folder/'narration.json').exists():return False
    first=folder/'discovery.json'
    if not first.exists():return False
    identity=json.loads(first.read_text()).get('identity')
    if not isinstance(identity,str):return False
    values={name:load(folder/(name+'.json'),identity) for name in ('discovery','sources','reporting')}
    if any(value is None for value in values.values()):return False
    if values['reporting'].get('edition',{}).get('edition_date') != plan['edition_date']:return False
    validate_report(values)
    inventory={name:hashlib.sha256((folder/(name+'.json')).read_bytes()).hexdigest() for name in values}
    reservation={'engine':engine,'edition_date':plan['edition_date'],'identity':identity,
                 'cached_files':inventory,'method':METHOD,'publication_authorized':False,
                 'new_discovery_prohibited':True,'new_reporting_prohibited':True,
                 'reserved_at':datetime.now(timezone.utc).isoformat(),
                 'run_id':os.getenv('GITHUB_RUN_ID','local'),'original_attempt_ledger_unchanged':True}
    try:
        with marker.open('x',encoding='utf-8') as f:json.dump(reservation,f,indent=2)
    except FileExistsError:return False
    return True


def assert_retained_stages(cache: Path, engine: str, identity: str):
    path=Path(cache)/'narration-limit-resume-used.json'
    if not path.exists():return False
    marker=json.loads(path.read_text())
    if (marker.get('identity')!=identity or marker.get('engine')!=engine
        or marker.get('method')!=METHOD or marker.get('publication_authorized') is not False
        or set(marker.get('cached_files',{}))!={'discovery','sources','reporting'}):
        raise RuntimeError('Narration continuation does not match the retained reporting')
    for name,sha in marker['cached_files'].items():
        retained=Path(cache)/engine/(name+'.json')
        if not retained.is_file() or hashlib.sha256(retained.read_bytes()).hexdigest()!=sha:
            raise RuntimeError('Narration continuation lost a prerequisite; new research is prohibited')
    return True


def reserve_capacity_resume(cache: Path, plan: dict, engine: str,
                            load: Callable, validate_report: Callable) -> bool:
    """One reviewed return to unspent section attempts after a measured reasoning stop."""
    if plan.get('maximum_narration_capacity_resumes') != 1:return False
    if (plan.get('previous_section_output_limit') != 2200
        or plan.get('corrected_section_output_limit') != OUTPUT_TOKENS
        or plan.get('corrected_section_reasoning_effort') != 'minimal'):
        raise RuntimeError('Invalid narration-capacity continuation authorization')
    marker=cache/'narration-capacity-resume-used.json'
    if marker.exists():
        from release_prose import reserve
        return reserve(cache,plan,engine,load,validate_report)
    previous=json.loads((cache/'narration-limit-resume-used.json').read_text())
    identity=previous.get('identity')
    assert_retained_stages(cache,engine,identity)
    folder=cache/engine
    if any((cache/n).exists() for n in ('audit.json','audit-bound.json','approved.json')) or (folder/'narration.json').exists():return False
    if previous.get('edition_date') != plan['edition_date']:return False
    records=json.loads((cache/'api-responses.json').read_text()).get('responses',[])
    if not records:return False
    last=records[-1]
    reasoning=last.get('reasoning_tokens')
    if not (last.get('stage')=='narration_section' and last.get('status')=='incomplete'
        and last.get('incomplete_reason')=='max_output_tokens'
        and last.get('requested_output_limit')==2200
        and type(reasoning) is int and reasoning>=2000):return False
    values={name:load(folder/(name+'.json'),identity) for name in ('discovery','sources','reporting')}
    if any(value is None for value in values.values()):return False
    validate_report(values)
    ledgers=list((folder/METHOD).glob('*/attempts.json'))
    if len(ledgers)!=1:return False
    ledger=ledgers[0];state=_ledger(ledger,ledger.parent.name)
    remaining=[f'{name}-{index}' for name,index,_ in SECTION_PLAN
        if state['attempts'].get(f'{name}-{index}',0)<MAX_SECTION_ATTEMPTS
        and not (ledger.parent/(f'{name}-{index}'+'.json')).exists()]
    if state['requests']>=MAX_REQUESTS or not remaining:return False
    try:
        with marker.open('x',encoding='utf-8') as f:
            json.dump({'edition_date':plan['edition_date'],'identity':identity,
                'reserved_at':datetime.now(timezone.utc).isoformat(),
                'observed_section_requests':state['requests'],'maximum_total_section_requests':MAX_REQUESTS,
                'section_ledgers_unchanged':True,'original_attempt_ledger_unchanged':True,
                'publication_authorized':False,'run_id':os.getenv('GITHUB_RUN_ID','local')},f,indent=2)
    except FileExistsError:return False
    return True
