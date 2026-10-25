"""Non-publishing diagnostics. Reports contain paths/rules, never draft prose.

Snapshots contain public-source candidate data, with known credentials redacted.
Actions caches are NOT confidential storage. Nothing here grants publication
approval, spends API credits, edits an attempt ledger, or repairs reporting.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Deliberately identical to the existing release_core validator. This module
# explains that gate; it does not narrow, relax, or replace its matching policy.
MARKERS = re.compile(r'draft pending|\bTODO\b|\bTBD\b|lorem ipsum|placeholder', re.I)
TERMS = {'draft pending', 'todo', 'tbd', 'lorem ipsum', 'placeholder'}
FIELDS = set('edition_date title bluf stories actions deadlines signals issue_updates sources '
             'podcast id what_changed why_it_matters executive_question category change '
             'policy_state source_ids due_date next_step suggested_function issue_id direction '
             'confidence horizon executiveRisk summary why status risk relevance nextMilestone '
             'history_note url published_date date description kind opening developments '
             'oklahoma closing'.split())
MAX_SNAPSHOT_BYTES = 1024 * 1024
MAX_FINDINGS = 30


def pointer(parts) -> str:
    """Do not echo arbitrary keys from a malformed model response into logs."""
    return ''.join('/' + (str(p) if isinstance(p, int) and p >= 0 else
                         p if isinstance(p, str) and p in FIELDS else '*') for p in parts) or '/'


def placeholder_findings(candidate: Any) -> list[dict]:
    findings = []

    def walk(value, path=()):
        if len(findings) >= MAX_FINDINGS:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                for m in MARKERS.finditer(json.dumps(str(key), ensure_ascii=False)):
                    if len(findings) < MAX_FINDINGS:
                        findings.append({'path': pointer(path + (key,)), 'match': m.group().lower(),
                                         'location': 'key'})
                walk(child, path + (key,))
        elif isinstance(value, list):
            for i, child in enumerate(value):
                walk(child, path + (i,))
        elif isinstance(value, str):
            # Match the JSON-escaped string, just as the unchanged gate does.
            for m in MARKERS.finditer(json.dumps(value, ensure_ascii=False)):
                if len(findings) < MAX_FINDINGS:
                    findings.append({'path': pointer(path), 'match': m.group().lower(),
                                     'location': 'value'})

    walk(candidate)
    return findings


def redact(value: Any) -> Any:
    secrets = [os.getenv(name, '') for name in ('OPENAI_API_KEY', 'GH_TOKEN', 'GITHUB_TOKEN')]
    secrets = sorted((v for v in secrets if len(v) >= 8), key=len, reverse=True)

    def text(s):
        for secret in secrets:
            s = s.replace(secret, '[REDACTED]')
        s = re.sub(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----',
                   '[REDACTED PRIVATE KEY]', s, flags=re.S)
        s = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*', 'Bearer [REDACTED]', s)
        return re.sub(r'\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,}|'
                      r'github_pat_[A-Za-z0-9_]{8,})', '[REDACTED]', s)

    def walk(v):
        if isinstance(v, str): return text(v)
        if isinstance(v, list): return [walk(x) for x in v]
        if isinstance(v, dict): return {text(str(k)): walk(x) for k, x in v.items()}
        return v
    return walk(value)


def write_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def read_attempts(cache: Path) -> int | None:
    try:
        value = json.loads((cache / 'attempts.json').read_text())['attempts']
        return value if type(value) is int and value >= 0 else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def word_count(candidate) -> int | None:
    try:
        p = candidate['podcast']
        body = [p['opening'], p['bluf'], *p['developments'], p['oklahoma'],
                p['signals'], p['actions'], p['deadlines'], p['closing']]
        return len('\n\n'.join(body).split())
    except (KeyError, TypeError):
        return None


def error_details(error: Exception, candidate=None) -> dict:
    result = _error_details(error, candidate)
    stage = getattr(error, 'research_stage', None)
    if stage in {'sources', 'reporting_plan', 'reporting', 'narration'}:
        result['api_stage'] = stage
        snapshot = getattr(error, 'stage_response_snapshot', None) or getattr(error, 'source_selection_snapshot', None)
        if isinstance(snapshot, dict):
            result['stage_snapshot'] = snapshot
    return result


def _error_details(error: Exception, candidate=None) -> dict:
    # str(ValidationError) contains the rejected instance. Never use it in a log.
    coverage = getattr(error, 'coverage_findings', None)
    if isinstance(coverage, list):
        return {'rule': 'evidence_coverage', 'message': 'Source material does not support a complete coverage plan',
                'path': '/', 'findings': coverage[:MAX_FINDINGS]}
    api = getattr(error, 'api_response', None)
    if isinstance(api, dict):
        status = api.get('status')
        reason = api.get('incomplete_reason')
        code = api.get('error_code')
        statuses = {'completed','incomplete','failed','cancelled','queued','in_progress','unknown'}
        reasons = {'max_output_tokens','max_messages','content_filter','steered','other',None}
        codes = {'server_error','rate_limit_exceeded','invalid_prompt','vector_store_timeout',
                 'invalid_request_error','insufficient_quota','other',None}
        safe = {'status':status if status in statuses else 'unknown',
                'incomplete_reason':reason if reason in reasons else 'other',
                'error_code':code if code in codes else 'other'}
        for key in ('input_tokens','output_tokens','reasoning_tokens','visible_characters'):
            value=api.get(key)
            safe[key]=value if type(value) is int and value>=0 else None
        result={'rule':'api_response','message':'Model response did not complete',
                'path':'/','response':safe}
        if api.get('stage') in {'discovery','sources','reporting_plan','reporting','narration','editorial_audit',
                                'rural_update_narration','narration_section','other'}:
            result['api_stage']=api['stage']
        return result
    keyword = getattr(error, 'validator', None)
    if isinstance(keyword, str) and re.fullmatch(r'[a-zA-Z]{1,32}', keyword):
        return {'rule': 'schema', 'message': 'Candidate does not match the required schema',
                'path': pointer(getattr(error, 'absolute_path', ())), 'keyword': keyword}
    if isinstance(error, json.JSONDecodeError):
        return {'rule': 'response_json', 'message': 'Model completion is not valid JSON',
                'path': '/', 'line': error.lineno, 'column': error.colno,
                'exception_category': 'JSONDecodeError'}
    raw = str(error) if isinstance(error, (AssertionError, RuntimeError, ValueError)) else ''
    reference = re.fullmatch(r'Unresolved reference at (stories|actions|deadlines|signals|issue_updates)/([0-9]+)/source_ids', raw)
    if reference:
        return {'rule': 'source_reference', 'message': 'Missing, duplicate, or unresolved source reference',
                'path': '/' + reference.group(1) + '/' + reference.group(2) + '/source_ids'}
    api_error = re.fullmatch(r'OpenAI (responses|audio/speech) HTTP ([0-9]{3}); credentials, model access or service request failed', raw)
    if api_error:
        return {'rule': 'api_request', 'message': 'External API request failed',
                'endpoint': api_error.group(1), 'http_status': int(api_error.group(2))}
    narration_section = re.fullmatch(r'Narration section failed its bounded structural checks: (opening-None|bluf-None|developments-[012]|oklahoma-None|signals-None|actions-None|deadlines-None|closing-None)', raw)
    if narration_section:
        section = narration_section.group(1).split('-')[0]
        path = '/podcast/' + section
        if section == 'developments': path += '/' + narration_section.group(1).rsplit('-', 1)[1]
        return {'rule': 'narration_section', 'message': 'Narration section failed bounded structural checks', 'path': path}
    if raw == 'Audit rejected candidate':
        return {'rule': 'evidence_audit', 'message': 'Editorial audit rejected candidate', 'path': '/'}
    if raw == 'Placeholder text':
        return {'rule': 'placeholder_text', 'message': 'Placeholder text',
                'findings': placeholder_findings(candidate)}
    messages = {
        'Duplicate source catalog identifier': ('source_identifier_duplicate', '/sources'),
        'Duplicate source catalog URL': ('source_url_duplicate', '/sources'),
        'Duplicate source selection field': ('source_selection_duplicate_key', '/sources'),
        'Duplicate reporting response field': ('reporting_duplicate_key', '/'),
        'Duplicate coverage plan field': ('coverage_duplicate_key', '/'),
        'Fewer than five observed readable-source URLs': ('source_observation_count', '/sources'),
        'Fewer than five distinct observed source URLs': ('source_observation_count', '/sources'),
        'Source selection contains an unapproved URL': ('source_domain', '/sources'),
        'Source selection catalog exceeds safe size': ('source_selection_size', '/sources'),
        'Source selection identifier collision': ('source_identifier_duplicate', '/sources'),
        'Edition date does not match requested date': ('edition_date', '/edition_date'),
        'Spoken body must contain 1700 to 2000 words': ('spoken_word_count', '/podcast'),
        'Use punctuation other than em dashes': ('punctuation', '/'),
        'Spoken body contains URLs or markup': ('spoken_markup', '/podcast'),
        'Need multiple source domains': ('source_diversity', '/sources'),
        'Source URL outside approved public domains': ('source_domain', '/sources'),
        'Future-dated source': ('future_source', '/sources'),
        'Source not observed in research tool results': ('source_provenance', '/sources'),
        'Unresolved source reference': ('source_reference', '/'),
        'Deadline is not within the next 30 days': ('deadline_window', '/deadlines'),
        'Action due date is already past': ('action_date', '/actions'),
        'Executive BLUF is too long': ('bluf_length', '/bluf'),
    }
    if raw in messages:
        rule, path = messages[raw]
        return {'rule': rule, 'message': raw, 'path': path}
    for field in ('stories','actions','signals','issue_updates','sources'):
        if raw in ('Duplicate '+field+' IDs','Unsafe '+field+' ID'):
            return {'rule':'identifier','message':'Invalid or duplicate identifier','path':'/'+field}
    if raw in ('Model response incomplete or failed','Model returned no output text','Research did not use web search'):
        return {'rule':'research_response','message':raw,'path':'/'}
    if re.fullmatch(r'Spoken body has [0-9]+ words after 2 revisions; required 1700 to 2000. Publication blocked.',raw):
        return {'rule':'spoken_word_count','message':raw,'path':'/podcast'}
    # Report a safe exception category without leaking source text or raw API payloads.
    # Unknown exceptions remain blocked, but are no longer indistinguishable.
    category = type(error).__name__
    if category not in ('AssertionError', 'RuntimeError', 'ValueError', 'TypeError',
                        'KeyError', 'JSONDecodeError', 'HTTPError', 'URLError',
                        'TimeoutError', 'CalledProcessError'):
        category = 'Other'
    return {'rule': 'stage_failure', 'message': 'Processing stopped; inspect the named stage',
            'path': '/', 'exception_category': category}


def summary(report: dict) -> str:
    rule = report.get('rule')
    if rule == 'api_response':
        d=report.get('response',{})
        status=d.get('status')
        reason=d.get('incomplete_reason') or d.get('error_code') or 'unspecified'
        if status not in ('completed','incomplete','failed','cancelled','queued','in_progress','unknown'):status='unknown'
        if reason not in ('max_output_tokens','max_messages','content_filter','steered','other','server_error','rate_limit_exceeded','invalid_prompt','vector_store_timeout','invalid_request_error','insufficient_quota','unspecified'):reason='other'
        return 'API response '+status+'; stopping reason: '+reason
    if rule == 'placeholder_text':
        matches = report.get('findings', [])[:MAX_FINDINGS]
        parts = []
        for finding in matches:
            p = finding.get('path', '/')
            safe = p.startswith('/') and all(t in FIELDS or t.isdigit() or t in ('', '*') for t in p.split('/'))
            term = finding.get('match')
            if safe and term in TERMS:
                parts.append(f'{p} (matched "{term}")')
        return 'Placeholder text: ' + ('; '.join(parts[:5]) if parts else 'field unavailable')
    if rule == 'research_attempt_limit':
        return 'Daily research attempt limit reached (2 of 2). No additional API call was made.'
    if rule == 'schema':
        return 'Candidate schema validation failed at ' + pointer_from_report(report.get('path', '/'))
    if rule == 'api_request' and report.get('endpoint') in ('responses', 'audio/speech') and type(report.get('http_status')) is int:
        return f'OpenAI {report["endpoint"]} request failed (HTTP {report["http_status"]})'
    if rule == 'narration_section':
        return 'Narration section validation failed at ' + pointer_from_report(report.get('path', '/'))
    if rule == 'evidence_audit':
        return 'Editorial audit rejected candidate; publication remains blocked.'
    if rule == 'evidence_coverage':
        return 'Evidence coverage incomplete before report generation; inspect the retained coverage findings.'
    if rule in ('identifier','research_response','spoken_word_count','response_json','source_reference','reporting_duplicate_key',
                'source_identifier_duplicate','source_url_duplicate','source_selection_duplicate_key',
                'source_observation_count','source_selection_size'):
        return 'Validation rule '+rule+' failed at '+pointer_from_report(report.get('path','/'))
    stage = report.get('stage', 'validation')
    if not isinstance(stage, str) or not re.fullmatch(r'[a-z-]{1,40}', stage): stage = 'validation'
    return 'Candidate validation stopped at ' + stage


def pointer_from_report(path) -> str:
    if isinstance(path, str) and path.startswith('/'):
        return '/' + '/'.join(x if x in FIELDS or x.isdigit() else '*' for x in path.split('/')[1:])
    return '/'


class DiagnosedFailure(AssertionError):
    def __init__(self, report):
        self.report = report
        super().__init__(summary(report))


class Diagnostics:
    def __init__(self, cache: Path, expected: str):
        date.fromisoformat(expected)
        self.cache, self.expected = Path(cache), expected

    def report(self, stage: str, **data) -> dict:
        if not re.fullmatch(r'[a-z-]{1,40}', stage): raise ValueError('Invalid diagnostic stage')
        report = {'schema_version': 1, 'edition_date': self.expected, 'stage': stage,
                  'run_id': os.getenv('GITHUB_RUN_ID', 'local'),
                  'checked_at': datetime.now(timezone.utc).isoformat(),
                  'publication_authorized': False, 'research_attempts': read_attempts(self.cache), **data}
        write_json(self.cache / f'validation-{stage}.json', report)
        write_json(self.cache / 'validation-latest.json', report)
        return report

    def capture(self, stage: str, candidate: Any, retrieved=()) -> dict:
        if not re.fullmatch(r'[a-z-]{1,40}', stage): raise ValueError('Invalid diagnostic stage')
        raw = json.dumps(candidate, ensure_ascii=False, sort_keys=True).encode()
        fingerprint = hashlib.sha256(raw).hexdigest()
        if len(raw) > MAX_SNAPSHOT_BYTES:
            return {'retained': False, 'reason': 'size_limit', 'candidate_sha256': fingerprint}
        sanitized = redact(candidate)
        # No prompts, environment dumps, raw API responses, or credentials are saved.
        snapshot = {'schema_version': 1, 'edition_date': self.expected, 'stage': stage,
                    'candidate_sha256': fingerprint, 'publication_authorized': False,
                    'redacted': sanitized != candidate, 'candidate': sanitized,
                    'retrieved_urls': redact(sorted(set(retrieved)))}
        name = stage + '-' + fingerprint[:16] + '.json'
        write_json(self.cache / 'candidates' / name, snapshot)
        return {'retained': True, 'file': 'candidates/' + name,
                'redacted': snapshot['redacted'], 'candidate_sha256': fingerprint}

    def fail(self, stage: str, error: Exception, candidate=None) -> DiagnosedFailure:
        report = self.report(stage, passed=False, word_count=word_count(candidate),
                             **error_details(error, candidate))
        return DiagnosedFailure(report)

    def validate(self, candidate, validator: Callable, stage: str, retrieved=None):
        saved = self.capture(stage, candidate, retrieved or ())
        try:
            result = validator(candidate, self.expected, retrieved)
        except Exception as exc:
            report = self.report(stage, passed=False, snapshot=saved, word_count=word_count(candidate),
                                 **error_details(exc, candidate))
            raise DiagnosedFailure(report) from None
        self.report(stage, passed=True, snapshot=saved, word_count=word_count(candidate))
        return result

    def limit_reached(self):
        return DiagnosedFailure(self.report('research-limit', passed=False, rule='research_attempt_limit'))


def diagnose_cache(cache: Path, expected: str) -> dict:
    """Read diagnostics without importing the publisher or invoking any API.

    Do not revalidate a redacted snapshot as if it were the original candidate,
    or treat an old schema pass as source verification/approval.
    """
    date.fromisoformat(expected)
    cache = Path(cache)
    retained = sorted((cache / 'candidates').glob('*.json')) if (cache / 'candidates').is_dir() else []
    count = read_attempts(cache)
    report = {'schema_version': 1, 'edition_date': expected, 'operation': 'diagnostics-only',
              'publication_authorized': False, 'publication_verified': False,
              'api_calls_made': 0, 'research_attempts': count, 'research_attempt_limit': 2,
              'candidate_count': len(retained),
              'candidate_status': 'retained' if retained else 'not-retained', 'checks': []}
    for path in sorted(cache.glob('validation-*.json')):
        if path.name == 'validation-latest.json': continue
        try:
            item = json.loads(path.read_text())
            if item.get('edition_date') == expected and item.get('passed') is False:
                report['checks'].append({'file': path.name, 'summary': summary(item)})
        except (OSError, ValueError, TypeError):
            report['checks'].append({'file': path.name, 'summary': 'Diagnostic report unreadable'})
    write_json(cache / 'diagnostic-summary.json', report)
    return report


def current_failure_summary(cache: Path) -> str | None:
    try:
        report = json.loads((Path(cache) / 'validation-latest.json').read_text())
        if report.get('run_id') == os.getenv('GITHUB_RUN_ID', 'local') and report.get('passed') is False:
            return summary(report)
    except (OSError, ValueError, TypeError):
        pass
    return None
