"""Retained-audio isolation, checksum gates and audio-only provider limits."""
import copy
import io
import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / name) for name in ('ops', 'scripts')]
import audio_acceptance as acceptance
from release_core import digest, write_json, read_json, podcast_body
from release_integration_budget import DevelopmentBudgetExceeded
from test_release_staged_research import bounded_fixture


class Response(io.BytesIO):
    status = 200
    headers = {}
    def geturl(self):return 'https://api.openai.com/v1/audio/speech'


def speech():
    return urllib.request.Request('https://api.openai.com/v1/audio/speech', data=json.dumps({
        'model': 'gpt-4o-mini-tts', 'voice': 'cedar', 'input': 'Retained script.'}).encode(), method='POST')


class AudioAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name);self.state = self.root / '.audio-integration-state'
        e = bounded_fixture();self.date = e['edition_date'];self.cache = self.root / '.release-cache' / self.date
        record = {'edition': e, 'audit': {'approved': True, 'issues': []},
                  'retrieved_urls': [s['url'] for s in e['sources']]}
        write_json(self.root / 'release.json', {'edition_date': self.date, 'audio_status': 'unavailable'})
        write_json(self.root / 'editions' / (self.date + '.json'), record)
        write_json(self.cache / 'attempts.json', {'attempts': 2})
        write_json(self.cache / 'source-evidence.json', {'complete': True})
        sha = digest(json.dumps(e, sort_keys=True, ensure_ascii=False))
        evidence_sha = digest((self.cache / 'source-evidence.json').read_bytes())
        write_json(self.cache / 'audit-bound.json', {'candidate_sha256': sha,
            'source_evidence_sha256': evidence_sha, 'audit': record['audit']})
        write_json(self.cache / 'audio-v2' / ('a' * 64 + '-attempts.json'), {'attempts': 2})
        self.wave = self.cache / 'audio-v2' / ('a' * 64 + '-0.wav');self.wave.write_bytes(b'Retained wave')
        self.plan = {'schema_version': 1, 'kind': 'retained_audio', 'request_id': 'test-audio-1',
            'edition_date': self.date, 'publication_authorized': False, 'new_research_prohibited': True,
            'release_sha256': digest((self.root / 'release.json').read_bytes()),
            'edition_file_sha256': digest((self.root / 'editions' / (self.date + '.json')).read_bytes()),
            'candidate_sha256': sha, 'script_sha256': digest(podcast_body(e)),
            'research_ledger_sha256': digest((self.cache / 'attempts.json').read_bytes()),
            'source_evidence_sha256': evidence_sha, 'minimum_retained_speech_requests': 2,
            'maximum_new_speech_requests': 1, 'maximum_new_transcription_requests': 1,
            'failed_audio_sha256': [digest(self.wave.read_bytes())]}

    def test_prepare_copies_speech_attempts_and_preserves_production(self):
        before = acceptance.production_inventory(self.root, self.date)
        workspace, spent = acceptance.prepare(self.root, self.state, self.plan)
        self.assertEqual(spent, 2)
        self.assertEqual((workspace / '.release-cache' / self.date / 'attempts.json').read_bytes(),
                         (self.cache / 'attempts.json').read_bytes())
        self.assertEqual(acceptance.speech_spent(workspace / '.release-cache' / self.date), 2)
        self.assertEqual(acceptance.production_inventory(self.root, self.date), before)

    def test_missing_speech_counter_or_wave_cannot_create_fresh_budget(self):
        ledger = next((self.cache / 'audio-v2').glob('*-attempts.json'))
        original = ledger.read_bytes();ledger.unlink()
        with self.assertRaisesRegex(RuntimeError, 'counters are missing'):
            acceptance.prepare(self.root, self.state, self.plan)
        ledger.write_bytes(original);self.wave.unlink()
        with self.assertRaisesRegex(RuntimeError, 'speech files are missing'):
            acceptance.prepare(self.root, self.state, self.plan)

    def test_changed_research_ledger_or_approved_record_blocks_before_provider(self):
        write_json(self.cache / 'attempts.json', {'attempts': 0})
        with self.assertRaisesRegex(RuntimeError, 'checksum'):
            acceptance.prepare(self.root, self.state, self.plan)

    def test_plan_cannot_authorize_publication_or_another_edition(self):
        self.plan['publication_authorized'] = True
        with self.assertRaises(RuntimeError):acceptance.prepare(self.root, self.state, self.plan)
        self.plan['publication_authorized'] = False
        write_json(self.root / 'release.json', {'edition_date': '2099-01-01'})
        with self.assertRaisesRegex(RuntimeError, 'different current edition'):
            acceptance.prepare(self.root, self.state, self.plan)

    def test_changed_test_identity_does_not_replace_existing_workspace(self):
        acceptance.prepare(self.root, self.state, self.plan)
        self.plan['request_id'] = 'another-audio-test'
        with self.assertRaisesRegex(RuntimeError, 'another test plan'):
            acceptance.prepare(self.root, self.state, self.plan)

    def test_partial_or_reset_development_workspace_cannot_resume(self):
        workspace = self.state / 'workspace';workspace.mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'Unbound partial'):
            acceptance.prepare(self.root, self.state, self.plan)
        workspace.rmdir();acceptance.prepare(self.root, self.state, self.plan)
        path = workspace / '.release-cache' / self.date / 'audio-v2' / ('a' * 64 + '-attempts.json')
        path.unlink()
        with self.assertRaisesRegex(RuntimeError, 'lost spent speech'):
            acceptance.prepare(self.root, self.state, self.plan)

    def test_audio_transport_rejects_research_and_nonprovider_writes(self):
        upstream = Mock();transport = acceptance.AudioTransport(self.state, upstream, 1, 1)
        for url in ('https://api.openai.com/v1/responses', 'https://api.github.com/repos/example/repo'):
            with self.assertRaises(RuntimeError):
                transport(urllib.request.Request(url, data=b'{}', method='POST'))
        upstream.assert_not_called()

    def test_audio_transport_limits_actual_submissions_including_http_errors(self):
        upstream = Mock(side_effect=urllib.error.HTTPError('https://api.openai.com', 429, '', {}, None))
        transport = acceptance.AudioTransport(self.state, upstream, 1, 1)
        with self.assertRaises(urllib.error.HTTPError):transport(speech())
        with self.assertRaises(DevelopmentBudgetExceeded):transport(speech())
        self.assertEqual(upstream.call_count, 1)

    def test_successful_cached_test_preparation_makes_no_provider_calls(self):
        write_json(self.root / '.integration-output/offline-controls.json', {'schema_version': 1, 'successful': True,
            'code_sha': 'a' * 40, 'errors': 0, 'failures': 0, 'unexpected_successes': 0,
            'tests_run': 1, 'skipped': 0})
        with patch.object(acceptance.subprocess, 'check_output', return_value='a' * 40), \
             patch.object(urllib.request, 'urlopen') as provider:
            report = acceptance.run(self.root, self.plan, live=False)
        provider.assert_not_called()
        self.assertEqual(report['result'], 'not_run')
        self.assertEqual(report['stages']['production_unchanged']['status'], 'pass')

    def test_workflow_has_no_publication_permissions_or_production_cache_save(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / '.github/workflows/audio-integration.yml').read_text()
        for forbidden in ('contents: write', 'pages: write', 'id-token: write', 'schedule:', '--commit'):
            self.assertNotIn(forbidden, text)
        self.assertIn('retired', text.lower())
        self.assertNotIn('secrets.OPENAI_API_KEY', text)
        self.assertNotIn('ops/audio_acceptance.py', text)
        self.assertNotIn('  push:', text)


if __name__ == '__main__':unittest.main()

