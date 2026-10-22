"""Distinguish source date roles and re-review one explicitly reviewed metadata fix."""
from __future__ import annotations
import copy
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from release_core import DOMAINS, read_json, write_json, digest, validate_edition
from release_editorial import fingerprint
from release_evidence import collect_source_evidence, evidence_prompt, evidence_urls
from release_diagnostics import Diagnostics

REVIEW_ROOT = Path(__file__).resolve().parents[1] / 'source-date-review'
DATE_POLICY = '''
SOURCE DATE CONTRACT: sources[].published_date represents the source's actual initial
publication or issue date, when verified. JSON null is explicitly allowed when that
date has not been established; it is not itself a claim that the source is undated.
Do not substitute a page's Last Modified timestamp, retrieval timestamp, contractor
implementation date, or policy-effective date for its initial publication date.
Those roles are distinct. Use dated statements in the fetched primary-source contents
and live retrieval to verify every temporal claim and deadline. A missing optional
publication-date field alone does not prevent review when that evidence supports the
claim. It also does not excuse an unsupported date, a false newness claim, a stale
policy, or an unverified deadline: these still block. Record metadata-only improvement
suggestions as advisory only when no material assertion is unsupported. Review the
entire briefing and narration; do not assume that fixing metadata resolves other facts.
'''


def _read(path, limit=2097152):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Unsafe source-date recovery record')
    return read_json(path)


def take_source_date_review(edition, cache, model, request, output_text, provenance,
                            generation_usage, policy, schema, validate, call):
    """One new audit of a pinned metadata correction, never an override of a review."""
    cache=Path(cache); day=edition['edition_date']; path=REVIEW_ROOT/(day+'.json')
    if not path.exists(): return None
    plan=_read(path,16000)
    if (plan.get('schema_version')!=1 or plan.get('edition_date')!=day
            or plan.get('base_candidate_sha256')!=fingerprint(edition)
            or plan.get('maximum_additional_audits')!=1
            or plan.get('publication_authorized') is not False):
        raise ValueError('Source-date recovery authorization differs')
    prior=cache/'editorial-loop-v1'; sha=plan.get('candidate_sha256','')
    import re
    if not re.fullmatch('[a-f0-9]{64}',sha): raise ValueError('Invalid source-date candidate hash')
    if prior.is_symlink() or (cache/'candidates').is_symlink():
        raise ValueError('Unsafe source-date candidate directory')
    snapshot=_read(cache/'candidates'/('editorial-corrected-'+sha[:16]+'.json'))
    candidate=copy.deepcopy(snapshot.get('candidate'))
    if (snapshot.get('candidate_sha256')!=sha or fingerprint(candidate)!=sha
            or snapshot.get('publication_authorized') is not False
            or snapshot.get('redacted') is not False or candidate.get('edition_date')!=day):
        raise ValueError('Source-date candidate identity differs')
    result=_read(prior/'reference-corrected-final-result.json')
    reservation=_read(prior/'reference-corrected-final-reserved.json')
    review=result.get('value')
    if (result.get('payload_sha256')!=reservation.get('payload_sha256')
            or result.get('value_sha256')!=fingerprint(review)
            or fingerprint(review)!=plan.get('incomplete_review_sha256')
            or not isinstance(review,dict) or review.get('review_complete') is not False):
        raise ValueError('Expected incomplete source-date review differs')
    update=plan.get('source_update',{})
    if set(update)!={'id','url','before','after'}:
        raise ValueError('Unexpected source-date correction fields')
    matches=[s for s in candidate['sources'] if s['id']==update['id']]
    if (len(matches)!=1 or matches[0]['url']!=update['url']
            or matches[0]['published_date']!=update['before'] or update['before'] is not None
            or date.fromisoformat(update['after'])>date.fromisoformat(day)):
        raise ValueError('Source-date correction is not the reviewed publication date')
    matches[0]['published_date']=update['after']
    if fingerprint(candidate)!=plan.get('updated_candidate_sha256'):
        raise ValueError('Source-date correction changed unreviewed content')
    validate_edition(candidate,day)
    folder=cache/'source-date-review-v1'
    if folder.is_symlink(): raise ValueError('Unsafe source-date review directory')
    folder.mkdir(exist_ok=True)
    marker={'plan_sha256':fingerprint(plan),'candidate_sha256':fingerprint(candidate),
            'publication_authorized':False,'maximum_additional_audits':1}
    identity=folder/'identity.json'
    if identity.exists():
        if _read(identity)!=marker: raise ValueError('Source-date review identity changed')
    else: write_json(identity,marker)
    documents=collect_source_evidence(candidate,cache)
    urls=set(provenance)|evidence_urls(candidate,documents)
    prompt=policy+'\nCANDIDATE:\n'+json.dumps(candidate,ensure_ascii=False)+evidence_prompt(documents)
    payload={'model':model,'store':False,'reasoning':{'effort':'low'},'max_output_tokens':7000,
        'max_tool_calls':10,'tools':[{'type':'web_search','filters':{'allowed_domains':DOMAINS}}],
        'tool_choice':'required','include':['web_search_call.action.sources'],'input':prompt,
        'text':{'format':{'type':'json_schema','name':'editorial_audit_structured','strict':True,'schema':schema(candidate)}}}
    report,retrieved,usage=call(folder,'full-source-review',payload,request,output_text)
    write_json(cache/'validation-source-date-review.json',{'edition_date':day,
        'candidate_sha256':fingerprint(candidate),'review_complete':report.get('review_complete'),
        'findings':report.get('findings',[]),'publication_authorized':False,
        'additional_audits':1,'prior_reviews_preserved':True})
    blocking=validate(report,candidate)
    verdict={'approved':not blocking,'issues':[f['explanation'] for f in blocking]}
    write_json(cache/'audit.json',verdict)
    if blocking:
        raise RuntimeError('Source-date recovery still has blocking findings; no further audit authorized')
    urls.update(retrieved);validate_edition(candidate,day,urls)
    structured={'schema_version':1,'edition_date':day,'stage':'structured-review',
        'candidate_sha256':fingerprint(candidate),'review_complete':True,'blocking_count':0,
        'advisory_count':len(report['findings']),'findings':report['findings'],
        'correction_calls':1,'correction_method':'reviewed-source-publication-date',
        'additional_audits':1,'publication_authorized':False}
    write_json(cache/'validation-structured-review.json',structured)
    write_json(cache/'audit-bound.json',{'edition_date':day,'candidate_sha256':fingerprint(candidate),
        'audit':verdict,'source_evidence_sha256':digest((cache/'source-evidence.json').read_bytes()),
        'retrieved_urls':sorted(urls),'run_id':os.getenv('GITHUB_RUN_ID'),
        'correction_method':'reviewed-source-publication-date','additional_audits':1})
    Diagnostics(cache,day).capture('source-date-corrected',candidate,urls)
    record={'edition':candidate,'audit':verdict,'retrieved_urls':sorted(urls),'model':model,
        'audit_candidate_sha256':fingerprint(candidate),
        'source_retrieval':read_json(cache/'source-evidence.json')['sources'],
        'research_at':datetime.now(timezone.utc).isoformat(),
        'usage':{'research':generation_usage,'audit':[usage]},'structured_review':structured}
    write_json(cache/'approved.json',record)
    return record
