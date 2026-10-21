"""One explicit, hash-bound correction of a rejected candidate, never approval.

The failed verdict and all spent ledgers remain intact. Only reviewed field
changes can enter one fresh full-source audit. No research or narration API calls
are made here, and a second rejected audit cannot loop through this entry point.
"""
from __future__ import annotations
import copy
import json
import os
import re
from pathlib import Path
from release_core import read_json, write_json, validate_edition
from release_resume import _read_snapshot


def _allowed(path):
    if path in (['bluf'], ['title']): return True
    if len(path) == 2 and path[0] == 'podcast':
        return path[1] in {'opening','bluf','oklahoma','signals','actions','deadlines','closing'}
    if len(path) == 3 and path[:2] == ['podcast','developments']:
        return type(path[2]) is int and 0 <= path[2] <= 2
    fields = {'stories': {'title','what_changed','why_it_matters','executive_question','change'},
              'signals': {'title','summary','why','source_ids'},
              'actions': {'title','next_step'},
              'deadlines': {'title','description','kind'}}
    return (len(path) == 3 and path[0] in fields and type(path[1]) is int
            and 0 <= path[1] < 30 and path[2] in fields[path[0]])


def take_claim_correction(cache: Path, expected: str, root: Path):
    from release_editorial import fingerprint
    cache=Path(cache); path=Path(root)/(expected+'.json')
    if not path.exists(): return None
    if path.is_symlink() or path.stat().st_size > 131072:
        raise ValueError('Claim correction plan is unsafe or oversized')
    plan=read_json(path)
    required={'schema_version':1,'edition_date':expected,'maximum_fresh_audits':1,
              'additional_generation_calls':0,'publication_authorized':False}
    if any(plan.get(k)!=v for k,v in required.items()):
        raise ValueError('Claim correction cannot approve publication or generation')
    sha=plan.get('base_candidate_sha256',''); run=plan.get('rejected_run_id','')
    stage=plan.get('base_stage')
    if not re.fullmatch('[a-f0-9]{64}',sha) or not re.fullmatch('[0-9]+',str(run)) or stage not in {'content','resumed-content'}:
        raise ValueError('Claim correction identity is invalid')
    marker=cache/'claim-correction-used.json'
    if marker.exists() or (cache/'approved.json').exists() or (cache/'audit-bound.json').exists():
        raise RuntimeError('Claim correction already consumed or edition already audited')
    if (cache/'candidates').is_symlink(): raise ValueError('Unsafe candidate directory')
    snapshot=_read_snapshot(cache/'candidates'/(stage+'-'+sha[:16]+'.json'),expected,stage)
    if not snapshot or snapshot['candidate_sha256']!=sha:
        raise ValueError('Claim correction does not match the exact retained candidate')
    failure=read_json(cache/'validation-evidence-audit.json',{})
    audit=read_json(cache/'audit.json',{})
    evidence=read_json(cache/'source-evidence.json',{})
    if (failure.get('edition_date')!=expected or str(failure.get('run_id'))!=str(run)
        or failure.get('stage')!='evidence-audit' or failure.get('passed') is not False
        or audit.get('approved') is not False or not audit.get('issues')
        or fingerprint(audit)!=plan.get('rejected_audit_sha256')
        or evidence.get('candidate_sha256')!=sha or evidence.get('complete') is not True):
        raise ValueError('Claim correction does not match the rejected evidence review')
    original=snapshot['candidate']; candidate=copy.deepcopy(original)
    source_ids={s['id'] for s in original['sources']}
    patches=plan.get('patches'); seen=set()
    if not isinstance(patches,list) or not 1 <= len(patches) <= 24:
        raise ValueError('Claim correction needs a bounded explicit change list')
    for patch in patches:
        if set(patch)!={'path','expected','replacement','reason','source_ids'}:
            raise ValueError('Unexpected claim correction fields')
        target=patch['path']
        if not isinstance(target,list) or not _allowed(target) or tuple(target) in seen:
            raise ValueError('Unapproved or duplicate field path')
        if not isinstance(patch['reason'],str) or not patch['reason'].strip():
            raise ValueError('Claim correction needs a review reason')
        refs=patch['source_ids']
        if not isinstance(refs,list) or not refs or not all(s in source_ids for s in refs):
            raise ValueError('Claim correction evidence IDs must already exist')
        owner=candidate
        for part in target[:-1]: owner=owner[part]
        old=owner[target[-1]]; new=patch['replacement']
        expected_value=patch['expected']
        if isinstance(expected_value,dict):
            matches=set(expected_value)=={'sha256'} and fingerprint(old)==expected_value['sha256']
        else:
            matches=old==expected_value
        if not matches:
            raise ValueError('Claim correction old value differs')
        if isinstance(new,dict):
            if set(new)!={'replace','with'} or not isinstance(old,str):
                raise ValueError('Invalid exact prose substitution')
            needle=new['replace']; replacement=new['with']
            if not isinstance(needle,str) or not needle or not isinstance(replacement,str) or old.count(needle)!=1:
                raise ValueError('Prose substitution must match exactly once')
            new=old.replace(needle,replacement,1)
        if new==old:
            raise ValueError('Claim correction makes no change')
        if target[-1]=='source_ids':
            if not isinstance(new,list) or len(new)!=len(set(new)) or not all(s in source_ids for s in new):
                raise ValueError('Claim correction cannot invent source IDs')
        elif not isinstance(new,str) or not new.strip():
            raise ValueError('Corrected prose must be complete text')
        if target[-1]=='kind' and (old!='Official deadline' or new!='Editorial checkpoint'):
            raise ValueError('A correction cannot invent an official deadline')
        owner[target[-1]]=copy.deepcopy(new); seen.add(tuple(target))
    if candidate['sources']!=original['sources'] or candidate['edition_date']!=expected:
        raise ValueError('Claim correction cannot replace sources or redate an edition')
    new_sha=fingerprint(candidate)
    if new_sha==sha or new_sha!=plan.get('candidate_sha256'):
        raise ValueError('Corrected candidate checksum differs')
    validate_edition(candidate,expected)
    # Retain exact earlier evidence and verdict. No prior attempt marker is removed.
    history=cache/'rejected-audits'/str(run)
    write_json(history/'audit.json',audit)
    write_json(history/'validation-evidence-audit.json',failure)
    write_json(history/'source-evidence.json',evidence)
    record={**required,'base_candidate_sha256':sha,'candidate_sha256':new_sha,
            'rejected_run_id':str(run),'run_id':os.getenv('GITHUB_RUN_ID','local'),
            'plan_sha256':fingerprint(plan),'changed_paths':[p['path'] for p in patches],
            'old_attempt_ledgers_preserved':True,'fresh_evidence_audit_required':True}
    with marker.open('x',encoding='utf-8') as f: json.dump(record,f,indent=2)
    write_json(cache/'validation-claim-correction.json',record)
    return candidate,set()  # Human review is not invented retrieval provenance.
