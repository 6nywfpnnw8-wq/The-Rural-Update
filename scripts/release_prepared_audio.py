"""One explicitly authorized promotion of an already validated audio cache.

The inactive proposal grants no permission. Active, date-specific authorizations
pin the source release and prepared evidence. Publication performs no model calls.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from release_core import digest, read_json, write_json, podcast_body, probe_audio
from release_verify import validate_audio_quality

MARKER = 'prepared-audio-promotion-used.json'


def authorization(root, date):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):raise RuntimeError('Invalid prepared-audio date')
    plan = read_json(Path(root) / 'audio-recovery-authorizations' / (date + '.json'))
    if plan is None:return None
    if (type(plan.get('schema_version')) is not int or plan['schema_version'] != 1 or plan.get('edition_date') != date
            or plan.get('publication_authorized') is not True
            or type(plan.get('maximum_publication_continuations')) is not int or plan['maximum_publication_continuations'] != 1
            or type(plan.get('new_model_requests_permitted')) is not int or plan['new_model_requests_permitted'] != 0
            or not re.fullmatch(r'[A-Za-z0-9-]{1,120}', str(plan.get('request_id', '')))
            or not re.fullmatch(r'rural-audio-integration-v1-[A-Za-z0-9-]+-\d+-\d+', str(plan.get('prepared_cache_key', '')))):
        raise RuntimeError('Prepared audio requires a valid one-time publication authorization')
    return plan


def checked(path, sha):
    path = Path(path)
    if (not re.fullmatch(r'[a-f0-9]{64}', str(sha)) or not path.is_file() or path.is_symlink()
            or any(parent.is_symlink() for parent in path.parents)
            or digest(path.read_bytes()) != sha):
        raise RuntimeError('Prepared audio input checksum differs')
    return path


def source_record(root, plan):
    date = plan['edition_date']
    path = checked(root / 'editions' / (date + '.json'), plan['edition_file_sha256'])
    record = read_json(path);e = record['edition']
    if (digest(json.dumps(e, sort_keys=True, ensure_ascii=False)) != plan['candidate_sha256']
            or digest(podcast_body(e)) != plan['script_sha256']
            or record.get('audit') != {'approved': True, 'issues': []}):
        raise RuntimeError('Prepared audio does not match the approved edition')
    return e


def already_complete(root, plan):
    release = read_json(root / 'release.json', {})
    if release.get('edition_date') != plan['edition_date']:raise RuntimeError('Prepared audio cannot replace another edition')
    if release.get('audio_status') != 'complete':return False
    path = 'audio/' + plan['edition_date'] + '.mp3'
    if release.get('files', {}).get(path, {}).get('sha256') != plan['prepared_audio_sha256']:
        raise RuntimeError('Complete release differs from authorized audio')
    checked(root / path, plan['prepared_audio_sha256']);source_record(root, plan)
    return True


def resolve(root, date):
    root = Path(root);plan = authorization(root, date)
    if plan is None:return {'enabled': 'false'}
    if already_complete(root, plan):return {'enabled': 'false'}
    checked(root / 'release.json', plan['source_release_sha256']);source_record(root, plan)
    if (root / '.release-cache' / date / MARKER).exists():
        raise RuntimeError('The one-time prepared-audio continuation is already consumed')
    return {'enabled': 'true', 'cache_key': plan['prepared_cache_key']}


def inventory(cache):
    result = {}
    for path in sorted((cache / 'audio-v2').rglob('*')):
        if path.is_symlink():raise RuntimeError('Speech cache cannot contain symlinks')
        if path.is_file():result[path.relative_to(cache).as_posix()] = digest(path.read_bytes())
    return result


def stage(root, state, date):
    root, state = Path(root), Path(state);plan = authorization(root, date)
    if plan is None:raise RuntimeError('Prepared audio has no publication authorization')
    if resolve(root, date)['enabled'] != 'true':return
    cache = root / '.release-cache' / date;prepared = state / 'workspace/.release-cache' / date
    checked(cache / 'attempts.json', plan['research_ledger_sha256'])
    checked(cache / 'source-evidence.json', plan['source_evidence_sha256'])
    checked(state / 'acceptance.json', plan['acceptance_sha256'])
    checked(state / 'seed-audio-inventory.json', plan['seed_inventory_sha256'])
    report = read_json(state / 'acceptance.json');seed = read_json(state / 'seed-audio-inventory.json')
    if (report.get('result') != 'pass' or report.get('publication_attempted') is not False
            or report.get('edition_date') != date or inventory(cache) != seed):
        raise RuntimeError('Prepared audio acceptance or original speech cache differs')
    if any(v.get('status') != 'pass' for v in report.get('stages', {}).values()):
        raise RuntimeError('Prepared audio acceptance has unpassed stages')
    required = {'offline_controls', 'retained_edition_and_budget', 'audio_completeness',
                'site_assembly', 'local_artifact_verification', 'repeat_without_provider', 'production_unchanged'}
    if not required.issubset(report.get('stages', {})):
        raise RuntimeError('Prepared audio acceptance is missing required stages')
    for relative, sha in seed.items():
        if not relative.startswith('audio-v2/') or '..' in Path(relative).parts:
            raise RuntimeError('Invalid retained speech path')
        checked(prepared / relative, sha)
    spent = 0
    for path in (prepared / 'audio-v2').glob('*-attempts.json'):
        value = read_json(path, {}).get('attempts')
        if type(value) is not int or not 0 <= value <= 2:raise RuntimeError('Invalid prepared speech counter')
        spent += value
    if spent > 64 or spent != report.get('speech_requests_after'):
        raise RuntimeError('Prepared speech budget differs')
    audio = checked(state / 'workspace/audio' / (date + '.mp3'), plan['prepared_audio_sha256'])
    quality_path = checked(prepared / 'audio-quality.json', plan['prepared_quality_sha256'])
    quality = read_json(quality_path)
    validate_audio_quality(quality, (root / 'podcast-script' / (date + '.txt')).read_text(), date, plan['prepared_audio_sha256'])
    files = []
    for path in (prepared / 'audio-v2').rglob('*'):
        if path.is_symlink():raise RuntimeError('Prepared speech cannot contain symlinks')
        if path.is_file():
            target = cache / path.relative_to(prepared)
            if target.exists():checked(target, digest(path.read_bytes()))
            files.append((path, target))
    receipt = {'request_id': plan['request_id'], 'authorization_sha256': digest(json.dumps(plan, sort_keys=True)),
        'audio_sha256': plan['prepared_audio_sha256'], 'research_counter_reset': False,
        'speech_requests_preserved': spent, 'new_model_requests_permitted': 0,
        'run_id': os.getenv('GITHUB_RUN_ID', 'local'), 'run_attempt': os.getenv('GITHUB_RUN_ATTEMPT', '1')}
    with (cache / MARKER).open('x') as output:json.dump(receipt, output, indent=2)
    # All original files are byte-identical. Add the validated paid work; never
    # replace or reset an existing speech counter or ASR record.
    for source, target in files:
        if not target.exists():target.parent.mkdir(parents=True, exist_ok=True);shutil.copy2(source, target)
    shutil.copy2(audio, cache / 'prepared-audio.mp3')
    shutil.copy2(quality_path, cache / 'prepared-audio-quality.json')


def cache_ready(root, date):
    root = Path(root);plan = authorization(root, date)
    if plan is None:return False
    if already_complete(root, plan):return True
    receipt = read_json(root / '.release-cache' / date / MARKER, {})
    if (receipt.get('authorization_sha256') != digest(json.dumps(plan, sort_keys=True))
            or receipt.get('run_id') != os.getenv('GITHUB_RUN_ID', 'local')
            or receipt.get('run_attempt') != os.getenv('GITHUB_RUN_ATTEMPT', '1')):
        raise RuntimeError('Prepared audio has not been staged for this publication attempt')
    checked(root / 'release.json', plan['source_release_sha256'])
    source_record(root, plan)
    checked(root / '.release-cache' / date / 'attempts.json', plan['research_ledger_sha256'])
    checked(root / '.release-cache' / date / 'source-evidence.json', plan['source_evidence_sha256'])
    checked(root / '.release-cache' / date / 'prepared-audio.mp3', plan['prepared_audio_sha256'])
    checked(root / '.release-cache' / date / 'prepared-audio-quality.json', plan['prepared_quality_sha256'])
    return True


def reuse(root, edition, cache, output):
    plan = authorization(root, edition['edition_date'])
    if plan is None:return None
    if digest(json.dumps(edition, sort_keys=True, ensure_ascii=False)) != plan['candidate_sha256']:
        raise RuntimeError('Prepared audio cannot change approved reporting')
    if not cache_ready(root, edition['edition_date']):raise RuntimeError('Prepared audio is not ready')
    quality = read_json(checked(cache / 'prepared-audio-quality.json', plan['prepared_quality_sha256']))
    audio = checked(cache / 'prepared-audio.mp3', plan['prepared_audio_sha256'])
    validate_audio_quality(quality, (root / 'podcast-script' / (edition['edition_date'] + '.txt')).read_text(),
                           edition['edition_date'], plan['prepared_audio_sha256'])
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(audio), '-f', 'null', '-'], check=True, capture_output=True, timeout=120)
    output.parent.mkdir(parents=True, exist_ok=True);shutil.copy2(audio, output)
    write_json(cache / 'audio-quality.json', quality)
    return probe_audio(output)


def guarded_build(root, date, build):
    plan = authorization(root, date)
    if plan is None:return build()
    if not cache_ready(root, date):raise RuntimeError('Prepared audio continuation is not ready')
    original = urllib.request.urlopen
    def no_model(request, *args, **kwargs):
        url = request.full_url if hasattr(request, 'full_url') else str(request)
        if urlsplit(url).hostname == 'api.openai.com':raise RuntimeError('Prepared publication prohibits new model requests')
        return original(request, *args, **kwargs)
    with patch.object(urllib.request, 'urlopen', no_model):result = build()
    if (result.get('audio_status') != 'complete'
            or result.get('files', {}).get('audio/' + date + '.mp3', {}).get('sha256') != plan['prepared_audio_sha256']):
        raise RuntimeError('Prepared publication did not retain the approved audio')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['resolve', 'stage']);parser.add_argument('--date', required=True)
    args = parser.parse_args();root = Path(__file__).resolve().parents[1]
    if args.operation == 'stage':stage(root, root / '.audio-integration-state', args.date)
    else:
        result = resolve(root, args.date)
        if os.getenv('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                for key, value in result.items():output.write(key + '=' + value + '\n')
        print(json.dumps(result))
