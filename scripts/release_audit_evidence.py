"""Reuse an audit only when its full extracted source-text input is identical.

The saved request keeps its original retrieval timestamps. Current retrieval
metadata remains in source-evidence.json. This helper never approves a review
or changes its request/result signature, reservations, or attempt counters.
"""
from __future__ import annotations
import copy
import re
from datetime import date, datetime
from pathlib import Path
from release_core import read_json, write_json, digest
from release_editorial import fingerprint


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100000:
        raise ValueError('Unsafe audit evidence checkpoint')
    return read_json(path)


def bound_evidence_documents(folder, edition, documents, reviewed_root):
    folder=Path(folder); reviewed_root=Path(reviewed_root)
    day=edition['edition_date'];date.fromisoformat(day)
    if folder.is_symlink() or reviewed_root.is_symlink():
        raise ValueError('Unsafe audit evidence directory')
    checkpoint=folder/'request-evidence.json'
    fresh={'schema_version':1,'edition_date':day,'candidate_sha256':fingerprint(edition),
           'publication_authorized':False,'complete':True,'failures':[],
           'sources':[{k:v for k,v in d.items() if k!='text'} for d in documents]}
    if checkpoint.exists():
        original=_read(checkpoint)
    elif ((folder/'full-source-review-result.json').exists()
          or (folder/'full-source-review-reserved.json').exists()):
        # Bootstrap only from the explicitly reviewed original run artifact.
        original=_read(reviewed_root/('evidence-'+day+'.json'))
    else:
        original=copy.deepcopy(fresh)
    if (original.get('schema_version')!=1 or original.get('edition_date')!=day
            or original.get('candidate_sha256')!=fingerprint(edition)
            or original.get('publication_authorized') is not False
            or original.get('complete') is not True or original.get('failures')!=[]):
        raise ValueError('Audit evidence checkpoint identity differs')
    sources=edition['sources']; saved=original.get('sources',[])
    if len(documents)!=len(sources) or len(saved)!=len(sources) or not sources:
        raise ValueError('Audit evidence source coverage differs')
    if len({d.get('source_id') for d in documents})!=len(documents):
        raise ValueError('Duplicate audit evidence source')
    bound=copy.deepcopy(documents);raw_changes=[]
    for source,previous,current,result in zip(sources,saved,documents,bound):
        if (current.get('source_id')!=source['id'] or current.get('url')!=source['url']
                or current.get('http_status')!=200 or not current.get('text')
                or digest(current['text'])!=current.get('text_sha256')):
            raise ValueError('Fresh evidence does not match its source or text digest')
        # HTML wrappers may change without changing any text given to the reviewer.
        # Retain fresh raw hashes/lengths; require identical source identity and text.
        for item in (previous,current):
            if (not isinstance(item.get('sha256'),str)
                    or not re.fullmatch(r'[a-f0-9]{64}',item['sha256'])
                    or type(item.get('bytes')) is not int or not 0<item['bytes']<=2097152):
                raise ValueError('Invalid raw source retrieval metadata')
        excluded={'retrieved_at','sha256','bytes'}
        old_metadata={k:v for k,v in previous.items() if k not in excluded}
        new_metadata={k:v for k,v in current.items() if k not in excluded|{'text'}}
        if old_metadata!=new_metadata:
            raise ValueError('Source contents changed since the audit; reviewed re-audit required')
        if any(previous[k]!=current[k] for k in ('sha256','bytes')):
            raw_changes.append(current['source_id'])
        old_time=datetime.fromisoformat(previous['retrieved_at'])
        new_time=datetime.fromisoformat(current['retrieved_at'])
        if old_time.tzinfo is None or new_time.tzinfo is None or old_time>new_time:
            raise ValueError('Audit evidence retrieval chronology differs')
        result['retrieved_at']=previous['retrieved_at']
    if not checkpoint.exists():write_json(checkpoint,original)
    write_json(folder.parent/'validation-audit-evidence-reuse.json',{
        'edition_date':day,'candidate_sha256':fingerprint(edition),
        'original_evidence_sha256':fingerprint(original),
        'fresh_evidence_sha256':fingerprint(fresh),'source_count':len(sources),
        'fresh_audited_source_text_identical':True,'raw_metadata_changed_sources':raw_changes,
        'current_raw_metadata_preserved':True,'original_retrieval_times_used_for_request_only':True,
        'original_request_signature_still_required':True,'publication_authorized':False})
    return bound
