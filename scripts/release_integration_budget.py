"""Persistent development request ceilings and pre-validation response capture."""
from __future__ import annotations
import io
import json
import copy
import urllib.error
from pathlib import Path
from urllib.parse import urlsplit
from release_core import digest, read_json, write_json
from release_diagnostics import redact
from release_research import response_metadata, _web_items

LIMITS = {'responses': 32, 'speech': 64, 'transcription': 80}
LEGACY_NAME_LIMITS = {'reporting': 2, 'narration': 2, 'narration_section': 20,
               'rural_update_narration': 2, 'editorial_audit_structured': 4,
               'editorial_audit': 2, 'editorial_field_correction': 2,
               'editorial_bluf_budget': 1}
LEGACY_TOKEN_LIMITS = {'reporting': 16000, 'narration': 8000, 'narration_section': 4000,
                'rural_update_narration': 8000, 'editorial_audit_structured': 7000,
                'editorial_audit': 5000, 'editorial_field_correction': 10000,
                'editorial_bluf_budget': 2500}
NAME_LIMITS = {**LEGACY_NAME_LIMITS, 'reporting_plan': 1}
TOKEN_LIMITS = {**LEGACY_TOKEN_LIMITS, 'reporting_plan': 6000}
CONTINUATION = 'coverage-plan-development-continuation-v1'
PASSAGE_CONTINUATION = 'coverage-passage-development-continuation-v1'
PASSAGE_NAME_LIMITS = {**NAME_LIMITS, 'reporting_plan': 2}


def continue_reporting_plan(state, expected_sha256, method=CONTINUATION):
    """Add one planning submission, retaining every spent count and overall cap."""
    state = Path(state);ledger_path = state / 'development-requests.json'
    if method not in {CONTINUATION, PASSAGE_CONTINUATION}:raise RuntimeError('Unknown development continuation')
    passage = method == PASSAGE_CONTINUATION
    backup = state / ('development-requests-before-passage-plan.json' if passage else 'development-requests-before-reporting-plan.json')
    if not ledger_path.is_file():raise RuntimeError('Retained development request ledger is unavailable')
    original = (backup if backup.exists() else ledger_path).read_bytes()
    if digest(original) != expected_sha256:raise RuntimeError('Development continuation ledger checksum differs')
    old = json.loads(original)
    if (old.get('limits') != LIMITS or old.get('name_limits') != (NAME_LIMITS if passage else LEGACY_NAME_LIMITS)
            or old.get('token_limits') != (TOKEN_LIMITS if passage else LEGACY_TOKEN_LIMITS) or old.get('publication_authorized') is not False
            or not isinstance(old.get('requests'), list)):
        raise RuntimeError('Development continuation does not match the original budget')
    continued = copy.deepcopy(old)
    continued.update({'name_limits': PASSAGE_NAME_LIMITS if passage else NAME_LIMITS, 'token_limits': TOKEN_LIMITS,
        'development_continuation': {'method': method, 'previous_ledger_sha256': expected_sha256,
                                     'overall_limit_unchanged': True}})
    current = read_json(ledger_path)
    if current != old:
        unchanged = {k: v for k, v in current.items() if k != 'requests'}
        expected = {k: v for k, v in continued.items() if k != 'requests'}
        if (unchanged != expected or current['requests'][:len(old['requests'])] != old['requests']
                or len(current['requests']) < len(old['requests'])):
            raise RuntimeError('Development continuation cannot replace or reset spent requests')
    if not backup.exists():
        with backup.open('xb') as f:f.write(original)
    if current == old:write_json(ledger_path, continued)


class DevelopmentBudgetExceeded(RuntimeError):pass


class BufferedResponse(io.BytesIO):
    def __init__(self, raw, original):
        super().__init__(raw)
        self.status = original.status
        self.headers = original.headers
        self.url = original.geturl()
    def geturl(self):return self.url
    def getcode(self):return self.status


class DevelopmentTransport:
    def __init__(self, state, upstream):
        self.state = Path(state);self.upstream = upstream
        self.ledger = self.state / 'development-requests.json'
        self.state.mkdir(parents=True, exist_ok=True)

    def reserve(self, kind, name=None, output_limit=None):
        if not self.ledger.exists() and any((self.state / 'provider-responses').glob('*')):
            raise RuntimeError('Development request ledger is missing after provider work')
        ledger = read_json(self.ledger, {'schema_version': 1, 'limits': LIMITS,
            'name_limits': NAME_LIMITS, 'token_limits': TOKEN_LIMITS,
            'requests': [], 'publication_authorized': False})
        names = NAME_LIMITS
        extension = ledger.get('development_continuation', {})
        if extension.get('method') == PASSAGE_CONTINUATION:
            backup = self.state / 'development-requests-before-passage-plan.json'
            if not backup.is_file() or digest(backup.read_bytes()) != extension.get('previous_ledger_sha256'):
                raise RuntimeError('Passage continuation requires the original spent ledger')
            old = read_json(backup)
            if ledger['requests'][:len(old['requests'])] != old['requests']:
                raise RuntimeError('Passage continuation cannot reset spent requests')
            names = PASSAGE_NAME_LIMITS
        if (ledger.get('limits') != LIMITS or ledger.get('name_limits') != names
                or ledger.get('token_limits') != TOKEN_LIMITS
                or ledger.get('publication_authorized') is not False
                or not isinstance(ledger.get('requests'), list)):
            raise RuntimeError('Development budget identity differs')
        rows = ledger['requests']
        for i, row in enumerate(rows):
            if (row.get('number') != i + 1 or row.get('kind') not in LIMITS
                    or row.get('name') is not None and row['name'] not in NAME_LIMITS
                    or row.get('state') not in {'reserved', 'ambiguous', 'http-error', 'response-retained'}):
                raise RuntimeError('Development request ledger is malformed')
        if any(r.get('name') == name and r['kind'] == kind and r['state'] in {'reserved', 'ambiguous'} for r in rows):
            raise RuntimeError('Ambiguous development request cannot be automatically resubmitted')
        if sum(r['kind'] == kind for r in rows) >= LIMITS[kind]:
            raise DevelopmentBudgetExceeded('Development endpoint request limit reached: ' + kind)
        if name is not None and sum(r.get('name') == name for r in rows) >= names[name]:
            raise DevelopmentBudgetExceeded('Development stage request limit reached: ' + name)
        row = {'number': len(rows) + 1, 'kind': kind, 'name': name,
               'requested_output_limit': output_limit, 'state': 'reserved'}
        rows.append(row);write_json(self.ledger, ledger)
        return row['number']

    def __call__(self, request, *args, **kwargs):
        url = request.full_url if hasattr(request, 'full_url') else str(request)
        method = request.get_method() if hasattr(request, 'get_method') else 'GET'
        parsed = urlsplit(url)
        if parsed.netloc != 'api.openai.com':
            if method not in {'GET', 'HEAD'}:
                raise RuntimeError('Integration workflow prohibits external write requests')
            return self.upstream(request, *args, **kwargs)
        if parsed.scheme != 'https' or method != 'POST':
            raise RuntimeError('Unexpected development provider request')
        path = parsed.path
        kind = {'/v1/responses': 'responses', '/v1/audio/speech': 'speech',
                '/v1/audio/transcriptions': 'transcription'}.get(path)
        if kind is None:raise RuntimeError('Unexpected development provider endpoint')
        name = None;payload = {}
        if kind == 'responses':
            payload = json.loads(request.data)
            name = ((payload.get('text') or {}).get('format') or {}).get('name')
            if name not in NAME_LIMITS:
                raise RuntimeError('New discovery or source selection is prohibited in this integration test')
            limit = payload.get('max_output_tokens')
            if type(limit) is not int or not 1 <= limit <= TOKEN_LIMITS[name]:
                raise RuntimeError('Development output-token allowance exceeded')
            if payload.get('tools') and (type(payload.get('max_tool_calls')) is not int
                                        or not 1 <= payload['max_tool_calls'] <= 12):
                raise RuntimeError('Development tool-call allowance exceeded')
        elif kind == 'speech':
            payload = json.loads(request.data)
            if (payload.get('model') != 'gpt-4o-mini-tts' or payload.get('voice') != 'cedar'
                    or not isinstance(payload.get('input'), str) or len(payload['input']) > 6000):
                raise RuntimeError('Development speech request exceeds the configured contract')
        elif len(request.data) > 25 * 1024 * 1024:
            raise RuntimeError('Development transcription input exceeds the configured contract')
        number = self.reserve(kind, name, payload.get('max_output_tokens'))
        try:
            response = self.upstream(request, *args, **kwargs)
        except Exception as error:
            ledger = read_json(self.ledger);row = ledger['requests'][number - 1]
            row['state'] = 'http-error' if isinstance(error, urllib.error.HTTPError) else 'ambiguous'
            if isinstance(error, urllib.error.HTTPError):row['http_status'] = error.code
            write_json(self.ledger, ledger)
            raise
        with response:
            raw = response.read(35 * 1024 * 1024 + 1)
            if len(raw) > 35 * 1024 * 1024:raise RuntimeError('Development response exceeds size limit')
            folder = self.state / 'provider-responses';folder.mkdir(exist_ok=True)
            saved = {'schema_version': 1, 'request_number': number, 'kind': kind,
                     'stage': name, 'sha256': digest(raw), 'publication_authorized': False}
            if kind == 'speech':
                binary = folder / (str(number).zfill(3) + '.wav');binary.write_bytes(raw)
                saved['audio_file'] = binary.name
            else:
                value = json.loads(raw)
                if kind == 'responses':
                    saved['metadata'] = response_metadata(value, payload)
                    saved['visible_text'] = '\n'.join(c.get('text', '')
                        for item in value.get('output', []) if item.get('type') == 'message'
                        for c in item.get('content', []) if c.get('type') == 'output_text')
                    saved['web_search_items'] = _web_items(value)
                else:
                    saved['visible_text'] = value.get('text')
                    saved['usage'] = value.get('usage')
            cleaned = redact(saved);cleaned['redacted'] = cleaned != saved
            write_json(folder / (str(number).zfill(3) + '.json'), cleaned)
            ledger = read_json(self.ledger)
            ledger['requests'][number - 1]['state'] = 'response-retained'
            ledger['requests'][number - 1]['response_sha256'] = digest(raw)
            write_json(self.ledger, ledger)
            return BufferedResponse(raw, response)
