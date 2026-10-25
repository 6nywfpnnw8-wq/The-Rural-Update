"""Run the real compiler in an isolated workspace with publication disabled."""
from __future__ import annotations
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import release_pipeline as publisher
import release_research as research
from release_core import (digest, read_json, write_json, safe_path, podcast_body,
                          validate_catalog, probe_audio, TZ)
from release_diagnostics import error_details
from release_integration_budget import DevelopmentTransport, DevelopmentBudgetExceeded, LIMITS, NAME_LIMITS, TOKEN_LIMITS
from release_verify import validate_audio_quality

STAGES = ('offline_controls', 'seed_integrity', 'reporting', 'interruption_and_resume',
          'narration', 'content_validation', 'source_retrieval', 'independent_evidence_audit',
          'audio_completeness', 'site_assembly', 'local_artifact_verification', 'repeat_without_provider',
          'artifact_corruption_guard', 'production_unchanged')
STATIC_FILES = ('index.html', 'release.json', 'manifest.webmanifest', 'sw.js', 'podcast.xml',
                'podcast-art.png', 'the-rural-update-logo.png', 'intelligence.js', 'signals-reference.js')
STATIC_DIRS = ('archive', 'data', 'editions', 'web', 'icons', 'templates', 'audio',
               'transcript', 'podcast-script', 'releases')


class ControlledInterruption(Exception):pass


def production_inventory(root, edition):
    files = [root / name for name in STATIC_FILES if (root / name).is_file()]
    for name in STATIC_DIRS:
        if (root / name).is_dir():files += [p for p in (root / name).rglob('*') if p.is_file()]
    cache = root / '.release-cache' / edition
    files += list(cache.rglob('*.json')) if cache.exists() else []
    return {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in sorted(files)}


def prepare_workspace(root, state, plan):
    if (plan.get('schema_version') != 1 or plan.get('publication_authorized') is not False
            or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(plan.get('edition_date', '')))
            or not re.fullmatch(r'[A-Za-z0-9-]{1,100}', str(plan.get('request_id', '')))
            or type(plan.get('source_count')) is not int or not 5 <= plan['source_count'] <= 12):
        raise RuntimeError('Invalid nonpublishing integration plan')
    for key in ('identity', 'discovery_sha256', 'sources_sha256', 'production_ledger_sha256'):
        if not re.fullmatch(r'[a-f0-9]{64}', str(plan.get(key, ''))):
            raise RuntimeError('Invalid nonpublishing integration seed binding')
    edition = plan['edition_date'];cache = root / '.release-cache' / edition
    current = read_json(root / 'release.json', {})
    if current.get('edition_date', '') >= edition:
        raise RuntimeError('Integration seed must describe an unpublished edition after the current release')
    expected = {'attempts.json': plan['production_ledger_sha256'],
                research.ENGINE + '/discovery.json': plan['discovery_sha256'],
                research.ENGINE + '/sources.json': plan['sources_sha256']}
    for name, fingerprint in expected.items():
        path = cache / name
        if (not path.is_file() or path.is_symlink() or any(p.is_symlink() for p in path.parents)
                or path.stat().st_size > 2 * 1024 * 1024 or digest(path.read_bytes()) != fingerprint):
            raise RuntimeError('Retained integration seed is missing, unsafe, or altered')
    discovery = research._cached(cache / research.ENGINE / 'discovery.json', plan['identity'])
    sources = research._cached(cache / research.ENGINE / 'sources.json', plan['identity'])
    if discovery is None or sources is None:raise RuntimeError('Integration seed context differs')
    research.validate_source_catalog(sources['sources'], research.observed_html_urls(discovery))
    if len(sources['sources']) != plan['source_count']:raise RuntimeError('Integration seed source count differs')
    binding = {'request_id': plan['request_id'], 'plan_sha256': digest(json.dumps(plan, sort_keys=True)),
               'identity': plan['identity'], 'publication_authorized': False}
    old = read_json(state / 'binding.json')
    if old is not None and old != binding:raise RuntimeError('Development cache belongs to another test plan')
    write_json(state / 'binding.json', binding)
    workspace = state / 'workspace'
    if not workspace.exists():
        workspace.mkdir(parents=True)
        for name in STATIC_FILES:
            if (root / name).is_file():shutil.copy2(root / name, workspace / name)
        for name in STATIC_DIRS:
            if (root / name).is_dir():
                shutil.copytree(root / name, workspace / name,
                                ignore=shutil.ignore_patterns('.*', '*.tmp*', '__pycache__'))
    # The actual compiler imports code from the tested checkout. Refresh only
    # static application assets when resuming development on a later code commit.
    for name in ('web', 'templates'):
        if (root / name).is_dir():shutil.copytree(root / name, workspace / name, dirs_exist_ok=True)
    target = workspace / '.release-cache' / edition / research.ENGINE
    target.mkdir(parents=True, exist_ok=True)
    for name in ('discovery.json', 'sources.json'):
        data = (cache / research.ENGINE / name).read_bytes();destination = target / name
        if destination.exists() and destination.read_bytes() != data:
            raise RuntimeError('Development upstream checkpoint differs from the retained seed')
        destination.write_bytes(data)
    # Neither production attempts nor recovery/approval markers are copied.
    previous = publisher.migrate_legacy(workspace)
    payload = publisher.research_payload(edition, previous)
    identity = digest(json.dumps({'engine': research.ENGINE, 'model': payload['model'],
                                  'context': payload['input']}, sort_keys=True))
    if identity != plan['identity']:raise RuntimeError('Production editorial context differs from retained integration seed')
    return workspace, payload


def local_verify(workspace, manifest):
    site = workspace / '.site';edition = manifest['edition_date']
    if read_json(site / 'release.json') != manifest:raise AssertionError('Local manifest differs')
    for name, info in manifest['files'].items():
        raw = safe_path(site, name).read_bytes()
        if len(raw) != info['bytes'] or digest(raw) != info['sha256']:
            raise AssertionError('Local artifact hash or size mismatch')
    if any((site / name).exists() for name in ('.release-cache', 'scripts', 'ops', 'repair-authorizations')):
        raise AssertionError('Private working material entered the compiled site')
    validate_catalog(site, read_json(site / 'archive/catalog.json'))
    if manifest['audio_status'] != 'complete':raise AssertionError('Local release lacks complete audio')
    quality = read_json(site / ('data/audio-quality-' + edition + '.json'))
    script = (site / ('podcast-script/' + edition + '.txt')).read_text()
    audio = site / ('audio/' + edition + '.mp3')
    validate_audio_quality(quality, script, edition, digest(audio.read_bytes()))
    seconds = probe_audio(audio)
    if not 540 <= seconds <= 900:raise AssertionError('Local audio duration is outside the release bounds')
    items = [i for i in ET.parse(site / 'podcast.xml').findall('./channel/item')
             if i.findtext('guid') == 'the-rural-update-' + edition]
    if len(items) != 1:raise AssertionError('Local RSS episode missing or duplicated')
    enclosure = items[0].find('enclosure')
    if enclosure is None or '/audio/' + edition + '.mp3' not in enclosure.get('url', ''):
        raise AssertionError('Local RSS audio reference differs')
    transcript = items[0].find('{https://podcastindex.org/namespace/1.0}transcript')
    if transcript is None or '/transcript/' + edition + '.html' not in transcript.get('url', ''):
        raise AssertionError('Local RSS transcript reference differs')
    return {'checked_files': len(manifest['files']), 'audio_duration_seconds': seconds,
            'narration_parts': quality['accepted_parts'], 'public_http_verified': False}


def write_report(output, report):
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / 'acceptance.json', report)
    esc = lambda value: html.escape(str(value))
    rows = ''.join('<tr><td>' + esc(name.replace('_', ' ')) + '</td><td class="' + esc(item['status']) + '">'
                   + esc(item['status'].upper()) + '</td><td>' + esc(item.get('detail', '')) + '</td></tr>'
                   for name, item in report['stages'].items())
    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1"><title>Rural Update integration acceptance</title>'
            '<style>body{font:16px/1.5 system-ui,sans-serif;max-width:1050px;margin:40px auto;padding:0 24px;color:#17313a}'
            'h1{font-size:30px}table{border-collapse:collapse;width:100%}td,th{text-align:left;vertical-align:top;'
            'border-bottom:1px solid #ccd7db;padding:10px}.pass{color:#17653c}.fail{color:#a52525}.not_run{color:#6a7377}'
            'code{overflow-wrap:anywhere}p{max-width:85ch}</style><h1>The Rural Update: integration acceptance</h1>'
            '<p><b>Result: ' + esc(report['result'].upper()) + '</b><br>Test cohort: ' + esc(report['edition_date'])
            + '<br>Checked: ' + esc(report['checked_at']) + '<br>Source commit: <code>' + esc(report['code_sha'])
            + '</code></p><p>This is a nonpublishing development run. Generated working material is not a published '
            'edition. Production attempt limits and recovery reservations remain separate and unchanged.</p>'
            '<table><thead><tr><th>Stage</th><th>Outcome</th><th>Evidence or limitation</th></tr></thead><tbody>'
            + rows + '</tbody></table><h2>Request use</h2><pre>' + esc(json.dumps(report.get('request_counts', {}), indent=2))
            + '</pre><p>Ceilings count actual provider HTTP submissions, including retries. They are not dollar-denominated '
            'billing limits. Passing local artifact checks does not establish public HTTP delivery or unattended scheduling.</p>'
            '<p>Public deployment: disabled. Render publication clock: unchanged. Human editorial approval, '
            'public HTTP delivery and unattended scheduling are not established by this test.</p></html>')
    (output / 'acceptance.html').write_text(page)


def collect_stages(report, workspace, state):
    cache = workspace / '.release-cache' / report['edition_date'];folder = cache / research.ENGINE
    checks = {'reporting': folder / 'reporting.json', 'narration': folder / 'narration.json'}
    for name, path in checks.items():
        if path.exists():report['stages'][name] = {'status': 'pass', 'detail': 'Validated stage checkpoint: ' + digest(path.read_bytes())}
    for stage, filename, key in (('content_validation', 'validation-content.json', 'passed'),
                                  ('source_retrieval', 'source-evidence.json', 'complete'),
                                  ('audio_completeness', 'audio-quality.json', 'complete')):
        value = read_json(cache / filename, {})
        if key in value:report['stages'][stage] = {'status': 'pass' if value[key] is True else 'fail',
                                                'detail': filename}
    approved = read_json(cache / 'approved.json', {})
    if approved.get('audit', {}).get('approved') is True and not approved['audit'].get('issues'):
        report['stages']['independent_evidence_audit'] = {'status': 'pass', 'detail': 'Independent audit and candidate/source bindings passed'}
    elif (cache / 'audit.json').exists() or any((cache / 'editorial-loop-v1').glob('*-reserved.json')):
        report['stages']['independent_evidence_audit'] = {'status': 'fail', 'detail': 'Audit was attempted; no fully approved candidate was retained'}
    resume = read_json(state / 'resume-exercise.json', {})
    requests = read_json(state / 'development-requests.json', {}).get('requests', [])
    path = folder / 'reporting.json'
    if (resume and path.exists() and resume.get('reporting_sha256') == digest(path.read_bytes())
            and resume.get('reporting_submissions') == sum(r.get('name') == 'reporting' for r in requests)
            and any(r.get('name') in {'narration', 'narration_section'} for r in requests)):
        report['stages']['interruption_and_resume'] = {'status': 'pass', 'detail': 'Stop before narration; resumed reporting made no additional reporting submission'}
    if (cache / 'audio-error.json').exists():
        report['stages']['audio_completeness'] = {'status': 'fail', 'detail': 'Audio generation or completeness gate rejected output; see retained evidence'}
    failure = read_json(cache / 'validation-latest.json', {})
    if failure.get('passed') is False:
        report['failure'] = {k: v for k, v in failure.items() if k not in {'snapshot', 'stage_snapshot'}}
        mapping = {'research-reporting': 'reporting', 'narration': 'narration', 'narration-section': 'narration',
                   'content': 'content_validation', 'exact-source-retrieval': 'source_retrieval',
                   'evidence-audit': 'independent_evidence_audit'}
        if failure.get('stage') in mapping:
            report['stages'][mapping[failure['stage']]] = {'status': 'fail',
                'detail': str(failure.get('rule', 'validation')) + ' at ' + str(failure.get('path', '/'))}


def run(root, plan, *, live=False):
    root = Path(root).resolve();state = root / '.integration-state';output = root / '.integration-output'
    edition = plan['edition_date'];code = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    report = {'schema_version': 1, 'edition_date': edition, 'code_sha': code,
              'checked_at': datetime.now(TZ).isoformat(), 'publication_authorized': False,
              'publication_attempted': False, 'result': 'not_run', 'limits': LIMITS, 'name_limits': NAME_LIMITS,
              'token_limits': TOKEN_LIMITS,
              'production_ready': False, 'human_editorial_review': 'not_performed',
              'scope': 'One retained ' + str(plan['source_count']) + '-source test cohort; public delivery and scheduled reliability are not established',
              'stages': {name: {'status': 'not_run'} for name in STAGES}}
    before = production_inventory(root, edition);workspace = None
    active = 'offline_controls'
    try:
        offline = output / 'offline-tests.log'
        log = offline.read_text() if offline.exists() else ''
        controls = read_json(output / 'offline-controls.json', {})
        if (controls.get('schema_version') != 1 or controls.get('code_sha') != code
                or controls.get('successful') is not True or controls.get('failures') != 0
                or controls.get('errors') != 0 or controls.get('unexpected_successes') != 0
                or type(controls.get('tests_run')) is not int or controls['tests_run'] < 1
                or not log):
            raise RuntimeError('Integration requires successful structured offline controls for the tested commit')
        report['offline_controls'] = controls
        report['stages']['offline_controls'] = {'status': 'pass',
            'detail': str(controls['tests_run']) + ' tests; ' + str(controls.get('skipped', 0)) + ' skipped; log SHA256 ' + digest(log)}
        active = 'seed_integrity'
        workspace, payload = prepare_workspace(root, state, plan)
        report['stages']['seed_integrity'] = {'status': 'pass', 'detail': str(plan['source_count']) + ' retained sources; original context and file hashes match'}
        if not live:return report
        if not os.getenv('OPENAI_API_KEY'):raise RuntimeError('Development provider credential is missing')
        if os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN'):
            raise RuntimeError('Integration child process must not receive repository-write credentials')
        cache = workspace / '.release-cache' / edition
        transport = DevelopmentTransport(state, urllib.request.urlopen)
        env = {'REQUESTED_DATE': edition, 'RURAL_UPDATE_STRUCTURED_REVIEW': 'true',
               'OPENAI_TTS_MODEL': 'gpt-4o-mini-tts', 'OPENAI_TTS_VOICE': 'cedar'}
        def forbidden(*args, **kwargs):raise RuntimeError('Publication is disabled in integration acceptance')
        with patch.object(publisher, 'ROOT', workspace), patch.object(publisher, 'commit_outputs', forbidden), \
             patch.dict(os.environ, env), patch.object(urllib.request, 'urlopen', transport):
            active = 'reporting'
            marker = state / 'resume-exercise.json'
            if not marker.exists():
                def interrupt(payload):
                    name = ((payload.get('text') or {}).get('format') or {}).get('name')
                    if name in {'narration', 'narration_section'}:raise ControlledInterruption()
                    return publisher._request_api(payload)
                try:research.staged_request(payload, interrupt, cache)
                except ControlledInterruption:
                    path = cache / research.ENGINE / 'reporting.json'
                    write_json(marker, {'reporting_sha256': digest(path.read_bytes()),
                        'reporting_submissions': sum(r.get('name') == 'reporting' for r in read_json(transport.ledger)['requests']),
                        'publication_authorized': False})
            active = 'narration'
            manifest = publisher.build(edition, code_sha=code)
            report['stages']['site_assembly'] = {'status': 'pass', 'detail': 'Allowlisted local site and release manifest assembled'}
            active = 'local_artifact_verification'
            report['local_verification'] = local_verify(workspace, manifest)
            report['stages']['local_artifact_verification'] = {'status': 'pass', 'detail': 'Manifest, archive, script/audio bindings, decoded MP3 and RSS verified locally'}
            first = read_json(transport.ledger, {}).get('requests', [])
            active = 'repeat_without_provider'
            repeated = publisher.build(edition, code_sha=code)
            if repeated != manifest or read_json(transport.ledger, {}).get('requests', []) != first:
                raise AssertionError('Completed integration rebuild repeated provider work or changed the release')
            report['stages']['repeat_without_provider'] = {'status': 'pass', 'detail': 'Exact completed rebuild made zero provider requests'}
            saved = read_json(marker, {})
            path = cache / research.ENGINE / 'reporting.json'
            submissions = sum(r.get('name') == 'reporting' for r in first)
            if saved and saved['reporting_sha256'] == digest(path.read_bytes()) and saved['reporting_submissions'] == submissions:
                report['stages']['interruption_and_resume'] = {'status': 'pass', 'detail': 'Intentional stop before narration; reporting reused without resubmission'}
            # A corrupted built file must fail local verification without a paid call.
            target = workspace / '.site/index.html';original = target.read_bytes()
            active = 'artifact_corruption_guard'
            try:
                target.write_bytes(original + b'\ncorruption-test')
                try:local_verify(workspace, manifest)
                except AssertionError:report['stages']['artifact_corruption_guard'] = {'status': 'pass', 'detail': 'Corrupted local file was rejected without another provider call'}
                else:raise AssertionError('Corrupt local artifact was accepted')
            finally:target.write_bytes(original)
    except Exception as exc:
        report['result'] = 'fail';report['error'] = error_details(exc)
        report['stages'][active] = {'status': 'fail', 'detail': report['error'].get('rule', 'stage_failure')}
        if isinstance(exc, DevelopmentBudgetExceeded):report['error']['rule'] = 'development_budget_exhausted'
    finally:
        if workspace is not None:collect_stages(report, workspace, state)
        after = production_inventory(root, edition)
        unchanged = before == after
        report['stages']['production_unchanged'] = {'status': 'pass' if unchanged else 'fail',
            'detail': 'Production files and attempt/recovery checkpoints are byte-identical' if unchanged else 'Production inventory differs'}
        ledger = read_json(state / 'development-requests.json', {})
        rows = ledger.get('requests', [])
        report['request_counts'] = {kind: sum(r['kind'] == kind for r in rows) for kind in LIMITS}
        report['stage_request_counts'] = {name: sum(r.get('name') == name for r in rows) for name in NAME_LIMITS}
        metadata = [read_json(p, {}).get('metadata', {}) for p in (state / 'provider-responses').glob('*.json')]
        report['response_token_usage'] = {key: sum(m.get(key) or 0 for m in metadata)
                                          for key in ('input_tokens', 'output_tokens', 'reasoning_tokens')}
        report['checked_at'] = datetime.now(TZ).isoformat()
        if live and report['result'] != 'fail':
            report['result'] = 'pass' if all(s['status'] == 'pass' for s in report['stages'].values()) else 'fail'
        write_report(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true');args = parser.parse_args()
    plan = read_json(ROOT / 'integration-request.json')
    result = run(ROOT, plan, live=args.live)
    print(json.dumps({'result': result['result'], 'publication_attempted': False,
                      'stages': result['stages'], 'request_counts': result['request_counts']}))
    return 0 if result['result'] in {'pass', 'not_run'} else 1


if __name__ == '__main__':sys.exit(main())
