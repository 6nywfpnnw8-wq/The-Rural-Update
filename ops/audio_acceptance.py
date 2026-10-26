"""Test retained, approved reporting and speech in a nonpublishing workspace."""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import release_pipeline as publisher
from release_core import digest, read_json, write_json, podcast_body, validate_edition, TZ
from release_diagnostics import error_details
from release_integration_budget import DevelopmentTransport, DevelopmentBudgetExceeded
from integration_acceptance import STATIC_FILES, STATIC_DIRS, production_inventory, local_verify, write_report


def speech_spent(cache):
    total = 0
    for path in (cache / 'audio-v2').glob('*-attempts.json'):
        value = read_json(path, {}).get('attempts')
        if type(value) is not int or not 0 <= value <= 2:raise RuntimeError('Invalid retained speech attempt ledger')
        total += value
    if total > 64:raise RuntimeError('Retained speech allowance exceeded')
    return total


def prepare(root, state, plan):
    if (plan.get('publication_authorized') is not False or plan.get('new_research_prohibited') is not True
            or plan.get('schema_version') != 1 or plan.get('kind') != 'retained_audio'):
        raise RuntimeError('Invalid nonpublishing audio plan')
    edition = plan['edition_date'];cache = root / '.release-cache' / edition
    release = read_json(root / 'release.json', {})
    if release.get('edition_date') != edition:raise RuntimeError('Audio test cannot replace a different current edition')
    for filename, expected in ((root / 'release.json', plan['release_sha256']),
                               (root / 'editions' / (edition + '.json'), plan['edition_file_sha256']),
                               (cache / 'attempts.json', plan['research_ledger_sha256']),
                               (cache / 'source-evidence.json', plan['source_evidence_sha256'])):
        if not filename.is_file() or filename.is_symlink() or digest(filename.read_bytes()) != expected:
            raise RuntimeError('Retained audio test input checksum differs')
    record = read_json(root / 'editions' / (edition + '.json'));value = record['edition']
    candidate = digest(json.dumps(value, sort_keys=True, ensure_ascii=False))
    bound = read_json(cache / 'audit-bound.json', {})
    if (candidate != plan['candidate_sha256'] or digest(podcast_body(value)) != plan['script_sha256']
            or bound.get('candidate_sha256') != candidate or bound.get('audit') != record.get('audit')
            or record.get('audit') != {'approved': True, 'issues': []}
            or bound.get('source_evidence_sha256') != plan['source_evidence_sha256']):
        raise RuntimeError('Retained editorial or script binding differs')
    validate_edition(value, edition, set(record['retrieved_urls']))
    spent = speech_spent(cache)
    if spent < plan['minimum_retained_speech_requests']:raise RuntimeError('Retained speech counters are missing')
    wavs = list((cache / 'audio-v2').glob('*.wav'))
    found = {digest(path.read_bytes()) for path in wavs if path.is_file() and not path.is_symlink()}
    if not set(plan['failed_audio_sha256']).issubset(found):raise RuntimeError('Required retained speech files are missing')
    binding = {'request_id': plan['request_id'], 'plan_sha256': digest(json.dumps(plan, sort_keys=True)),
               'baseline_speech_requests': spent, 'publication_authorized': False}
    old = read_json(state / 'binding.json')
    if old is not None and old != binding:raise RuntimeError('Audio workspace belongs to another test plan')
    seed = {path.relative_to(cache).as_posix(): digest(path.read_bytes())
            for path in sorted((cache / 'audio-v2').rglob('*')) if path.is_file()}
    old_seed = read_json(state / 'seed-audio-inventory.json')
    if old is not None and old_seed != seed:raise RuntimeError('Original speech cache changed since the audio test began')
    workspace = state / 'workspace'
    if workspace.exists() and old is None:raise RuntimeError('Unbound partial audio workspace cannot resume')
    if not workspace.exists():
        workspace.mkdir(parents=True)
        for name in STATIC_FILES:
            if (root / name).is_file():shutil.copy2(root / name, workspace / name)
        for name in STATIC_DIRS:
            if (root / name).is_dir():
                shutil.copytree(root / name, workspace / name, ignore=shutil.ignore_patterns('.*', '*.tmp*', '__pycache__'))
        for path in cache.rglob('*'):
            if path.is_symlink():raise RuntimeError('Retained audio cache cannot contain symlinks')
        shutil.copytree(cache, workspace / '.release-cache' / edition)
    for path, expected in ((workspace / 'editions' / (edition + '.json'), plan['edition_file_sha256']),
                           (workspace / '.release-cache' / edition / 'attempts.json', plan['research_ledger_sha256']),
                           (workspace / '.release-cache' / edition / 'source-evidence.json', plan['source_evidence_sha256'])):
        if not path.is_file() or digest(path.read_bytes()) != expected:
            raise RuntimeError('Resumed audio workspace lost its retained edition or evidence')
    if speech_spent(workspace / '.release-cache' / edition) < spent:
        raise RuntimeError('Resumed audio workspace lost spent speech counters')
    write_json(state / 'seed-audio-inventory.json', seed)
    write_json(state / 'binding.json', binding)
    return workspace, spent


class AudioTransport:
    def __init__(self, state, upstream, speech_limit, transcription_limit):
        self.inner = DevelopmentTransport(state, upstream)
        self.limits = {'speech': speech_limit, 'transcription': transcription_limit}

    def __call__(self, request, *args, **kwargs):
        from urllib.parse import urlsplit
        url = request.full_url if hasattr(request, 'full_url') else str(request)
        parsed = urlsplit(url)
        if parsed.netloc == 'api.openai.com':
            kind = {'/v1/audio/speech': 'speech', '/v1/audio/transcriptions': 'transcription'}.get(parsed.path)
            if kind is None:raise RuntimeError('Audio integration prohibits new research, narration and audit responses')
            rows = read_json(self.inner.ledger, {}).get('requests', [])
            if sum(r.get('kind') == kind for r in rows) >= self.limits[kind]:
                raise DevelopmentBudgetExceeded('Retained audio integration request ceiling reached')
        return self.inner(request, *args, **kwargs)


def run(root, plan, live=False):
    state = root / '.audio-integration-state';output = root / '.audio-integration-output'
    date = plan['edition_date'];before = production_inventory(root, date)
    code = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    stages = ('offline_controls', 'retained_edition_and_budget', 'audio_completeness', 'site_assembly',
              'local_artifact_verification', 'repeat_without_provider', 'production_unchanged')
    report = {'schema_version': 1, 'edition_date': date, 'code_sha': code, 'result': 'not_run',
        'checked_at': datetime.now(TZ).isoformat(), 'publication_authorized': False, 'publication_attempted': False,
        'production_ready': False, 'scope': 'Retained approved October 26 reporting; isolated audio and local site test',
        'stages': {name: {'status': 'not_run'} for name in stages}}
    active = 'offline_controls';workspace = None
    try:
        controls = read_json(root / '.integration-output/offline-controls.json', {})
        if (controls.get('schema_version') != 1 or controls.get('successful') is not True or controls.get('code_sha') != code
                or controls.get('errors') != 0 or controls.get('failures') != 0 or controls.get('unexpected_successes') != 0):
            raise RuntimeError('Audio integration requires successful offline controls for its commit')
        report['stages'][active] = {'status': 'pass', 'detail': str(controls['tests_run']) + ' tests; ' + str(controls.get('skipped', 0)) + ' skipped'}
        active = 'retained_edition_and_budget';workspace, spent = prepare(root, state, plan)
        report['baseline_speech_requests'] = spent
        report['seed_audio_inventory_sha256'] = digest((state / 'seed-audio-inventory.json').read_bytes())
        report['stages'][active] = {'status': 'pass', 'detail': 'Approved candidate, script, source evidence and research ledger hashes match; ' + str(spent) + ' speech attempts retained'}
        if not live:return report
        if not os.getenv('OPENAI_API_KEY') or os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN'):
            raise RuntimeError('Audio integration requires only the provider credential')
        transport = AudioTransport(state, urllib.request.urlopen,
            min(plan['maximum_new_speech_requests'], 64 - spent), plan['maximum_new_transcription_requests'])
        env = {'REQUESTED_DATE': date, 'OPENAI_TTS_MODEL': 'gpt-4o-mini-tts', 'OPENAI_TTS_VOICE': 'cedar'}
        def forbidden(*args, **kwargs):raise RuntimeError('Publication is disabled in audio integration')
        active = 'audio_completeness'
        with patch.object(publisher, 'ROOT', workspace), patch.object(publisher, 'commit_outputs', forbidden), \
             patch.dict(os.environ, env), patch.object(urllib.request, 'urlopen', transport):
            manifest = publisher.build(date, code_sha=code)
            if manifest['audio_status'] != 'complete':raise RuntimeError('Retained audio build did not complete')
            report['stages']['audio_completeness'] = {'status': 'pass', 'detail': 'All speech segments and assembled closing passed the original ASR thresholds'}
            report['stages']['site_assembly'] = {'status': 'pass', 'detail': 'Compiled in the private workspace'}
            active = 'local_artifact_verification';report['local_verification'] = local_verify(workspace, manifest)
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(workspace / '.site/audio' / (date + '.mp3')),
                            '-f', 'null', '-'], check=True, capture_output=True, timeout=120)
            report['stages'][active] = {'status': 'pass', 'detail': 'Manifest, script/audio hashes, MP3 decode, transcript, archive and RSS verified locally'}
            first = transport.inner.ledger.read_bytes();active = 'repeat_without_provider'
            if publisher.build(date, code_sha=code) != manifest or transport.inner.ledger.read_bytes() != first:
                raise RuntimeError('Completed audio rebuild repeated provider work or changed the bundle')
            report['stages'][active] = {'status': 'pass', 'detail': 'Completed rebuild used zero additional provider requests'}
        cache = workspace / '.release-cache' / date
        if digest((cache / 'attempts.json').read_bytes()) != plan['research_ledger_sha256']:
            raise RuntimeError('Isolated build changed its retained research ledger')
        output.mkdir(parents=True, exist_ok=True)
        shutil.copy2(workspace / '.site/audio' / (date + '.mp3'), output / (date + '.mp3'))
        with zipfile.ZipFile(output / 'prepared-audio-cache.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(cache.rglob('*')):
                if path.is_file():archive.write(path, path.relative_to(workspace).as_posix())
        report['prepared_manifest'] = manifest;report['result'] = 'pass'
    except Exception as error:
        report['result'] = 'fail';report['error'] = error_details(error)
        report['stages'][active] = {'status': 'fail', 'detail': report['error'].get('rule', 'audio_integration')}
    finally:
        unchanged = production_inventory(root, date) == before
        report['stages']['production_unchanged'] = {'status': 'pass' if unchanged else 'fail', 'detail': 'Production files and cache are byte-identical' if unchanged else 'Production inventory differs'}
        if not unchanged:report['result'] = 'fail'
        rows = read_json(state / 'development-requests.json', {}).get('requests', [])
        report['request_counts'] = {kind: sum(r.get('kind') == kind for r in rows) for kind in ('responses', 'speech', 'transcription')}
        try:report['speech_requests_after'] = speech_spent(workspace / '.release-cache' / date) if workspace else None
        except Exception as error:
            report['result'] = 'fail';report['checkpoint_inspection_error'] = error_details(error)
        report['checked_at'] = datetime.now(TZ).isoformat();write_report(output, report)
        write_json(state / 'acceptance.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('--live', action='store_true')
    result = run(ROOT, read_json(ROOT / 'audio-integration-request.json'), parser.parse_args().live)
    print(json.dumps({'result': result['result'], 'stages': result['stages'], 'request_counts': result['request_counts']}))
    raise SystemExit(0 if result['result'] in ('pass', 'not_run') else 1)
