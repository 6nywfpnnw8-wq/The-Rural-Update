"""A prepared recording can be promoted once without generation or budget resets."""
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / name) for name in ('scripts', 'ops')]
import release_prepared_audio as prepared
import publisher_provider_check as preflight
from release_core import digest, podcast_body, read_json, write_json
from test_release_staged_research import bounded_fixture


class PreparedAudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name);self.state = self.root / '.prepared'
        self.edition = bounded_fixture();self.date = self.edition['edition_date']
        self.cache = self.root / '.release-cache' / self.date
        self.retained = self.state / 'workspace/.release-cache' / self.date
        self.auth_path = self.root / 'audio-recovery-authorizations' / (self.date + '.json')
        write_json(self.root / 'release.json', {'edition_date': self.date, 'audio_status': 'unavailable'})
        write_json(self.root / 'editions' / (self.date + '.json'), {
            'edition': self.edition, 'audit': {'approved': True, 'issues': []}})
        write_json(self.cache / 'attempts.json', {'attempts': 2})
        write_json(self.cache / 'source-evidence.json', {'sources': ['retained']})
        write_json(self.cache / 'audio-v2/original-attempts.json', {'attempts': 2})
        (self.cache / 'audio-v2/original.wav').write_bytes(b'original paid speech')
        seed = prepared.inventory(self.cache)
        shutil.copytree(self.cache, self.retained)
        write_json(self.retained / 'audio-v2/new-attempts.json', {'attempts': 1})
        (self.retained / 'audio-v2/new.wav').write_bytes(b'new accepted speech')
        self.audio = self.state / 'workspace/audio' / (self.date + '.mp3')
        self.audio.parent.mkdir(parents=True);self.audio.write_bytes(b'approved MP3 fixture')
        write_json(self.retained / 'audio-quality.json', {'complete': True})
        stages = ('offline_controls', 'retained_edition_and_budget', 'audio_completeness',
                  'site_assembly', 'local_artifact_verification', 'repeat_without_provider', 'production_unchanged')
        write_json(self.state / 'acceptance.json', {'result': 'pass', 'edition_date': self.date,
            'publication_attempted': False, 'speech_requests_after': 3,
            'stages': {name: {'status': 'pass'} for name in stages}})
        write_json(self.state / 'seed-audio-inventory.json', seed)
        script = self.root / 'podcast-script' / (self.date + '.txt')
        script.parent.mkdir();script.write_text('Edition date: ' + self.date + '\n\n' + podcast_body(self.edition))
        self.plan = {'schema_version': 1, 'edition_date': self.date, 'request_id': 'test-promotion-1',
            'publication_authorized': True, 'maximum_publication_continuations': 1,
            'new_model_requests_permitted': 0, 'prepared_cache_key': 'rural-audio-integration-v1-test-123-1',
            'candidate_sha256': digest(json.dumps(self.edition, sort_keys=True, ensure_ascii=False)),
            'script_sha256': digest(podcast_body(self.edition))}
        for key, path in {
            'source_release': self.root / 'release.json',
            'edition_file': self.root / 'editions' / (self.date + '.json'),
            'research_ledger': self.cache / 'attempts.json',
            'source_evidence': self.cache / 'source-evidence.json',
            'prepared_audio': self.audio, 'prepared_quality': self.retained / 'audio-quality.json',
            'acceptance': self.state / 'acceptance.json',
            'seed_inventory': self.state / 'seed-audio-inventory.json',
        }.items():self.plan[key + '_sha256'] = digest(path.read_bytes())
        write_json(self.auth_path, self.plan)
        self.env = patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'})
        self.env.start();self.addCleanup(self.env.stop)
        # Real media validation is also rehearsed against the complete retained MP3.
        self.quality = patch.object(prepared, 'validate_audio_quality', return_value=True)
        self.quality.start();self.addCleanup(self.quality.stop)

    def stage(self):prepared.stage(self.root, self.state, self.date)

    def complete_result(self):
        return {'edition_date': self.date, 'audio_status': 'complete', 'files': {
            'audio/' + self.date + '.mp3': {'sha256': self.plan['prepared_audio_sha256']}}}

    def test_inactive_proposal_grants_no_permission_or_provider_skip(self):
        self.auth_path.unlink()
        write_json(self.root / 'audio-recovery-proposals' / (self.date + '.json'), self.plan)
        self.assertEqual(prepared.resolve(self.root, self.date), {'enabled': 'false'})
        self.assertFalse(prepared.cache_ready(self.root, self.date))
        self.assertIsNone(prepared.reuse(self.root, self.edition, self.cache, self.root / 'output.mp3'))

    def test_malformed_or_unapproved_authorization_is_rejected(self):
        for key, value in [('publication_authorized', False), ('maximum_publication_continuations', True),
                           ('new_model_requests_permitted', 1), ('request_id', '../escape'),
                           ('prepared_cache_key', 'unbound-cache')]:
            with self.subTest(key=key):
                write_json(self.auth_path, {**self.plan, key: value})
                with self.assertRaises(RuntimeError):prepared.resolve(self.root, self.date)

    def test_stage_preserves_original_ledgers_and_adds_only_paid_work(self):
        old = {p: p.read_bytes() for p in self.cache.rglob('*') if p.is_file()}
        self.stage()
        for path, raw in old.items():self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(read_json(self.cache / prepared.MARKER)['speech_requests_preserved'], 3)
        self.assertEqual((self.cache / 'prepared-audio.mp3').read_bytes(), self.audio.read_bytes())
        self.assertTrue(prepared.cache_ready(self.root, self.date))

    def test_changed_retained_evidence_stops_before_spending_or_copying(self):
        (self.cache / 'source-evidence.json').write_text('changed')
        with self.assertRaises(RuntimeError):self.stage()
        self.assertFalse((self.cache / prepared.MARKER).exists())
        self.assertFalse((self.cache / 'audio-v2/new.wav').exists())

    def test_original_speech_or_prepared_media_cannot_be_changed(self):
        (self.retained / 'audio-v2/original.wav').write_bytes(b'changed')
        with self.assertRaises(RuntimeError):self.stage()
        self.assertFalse((self.cache / prepared.MARKER).exists())

    def test_speech_counter_reset_is_rejected_before_promotion(self):
        write_json(self.retained / 'audio-v2/new-attempts.json', {'attempts': 0})
        with self.assertRaisesRegex(RuntimeError, 'budget differs'):self.stage()
        self.assertFalse((self.cache / prepared.MARKER).exists())

    def test_same_or_another_run_cannot_consume_the_continuation_twice(self):
        self.stage()
        with self.assertRaisesRegex(RuntimeError, 'already consumed'):self.stage()
        with patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '2'}):
            with self.assertRaisesRegex(RuntimeError, 'not been staged'):prepared.cache_ready(self.root, self.date)

    def test_post_stage_changes_to_source_or_research_ledger_stop(self):
        self.stage();write_json(self.cache / 'attempts.json', {'attempts': 0})
        with self.assertRaisesRegex(RuntimeError, 'checksum'):prepared.cache_ready(self.root, self.date)

    def test_reuse_keeps_exact_bytes_and_requires_unchanged_editorial_content(self):
        self.stage();output = self.root / 'output.mp3'
        with patch.object(prepared.subprocess, 'run') as decode, patch.object(prepared, 'probe_audio', return_value=800):
            self.assertEqual(prepared.reuse(self.root, self.edition, self.cache, output), 800)
        decode.assert_called_once();self.assertEqual(output.read_bytes(), self.audio.read_bytes())
        changed = {**self.edition, 'title': 'Changed reporting'}
        with self.assertRaisesRegex(RuntimeError, 'cannot change'):prepared.reuse(self.root, changed, self.cache, output)

    def test_prepared_publication_blocks_every_new_provider_request(self):
        self.stage()
        with patch.object(urllib.request, 'urlopen') as upstream:
            def call():
                return urllib.request.urlopen(urllib.request.Request('https://api.openai.com/v1/responses', data=b'{}'))
            with self.assertRaisesRegex(RuntimeError, 'prohibits new model'):
                prepared.guarded_build(self.root, self.date, call)
        upstream.assert_not_called()

    def test_guard_rejects_text_only_or_different_audio_result(self):
        self.stage()
        for result in ({'audio_status': 'unavailable'}, {**self.complete_result(), 'files': {}}):
            with self.assertRaisesRegex(RuntimeError, 'did not retain'):
                prepared.guarded_build(self.root, self.date, lambda: result)

    def test_completed_exact_bundle_can_retry_deployment_without_repromotion(self):
        target = self.root / 'audio' / (self.date + '.mp3')
        target.parent.mkdir();shutil.copy2(self.audio, target)
        result = self.complete_result();write_json(self.root / 'release.json', result)
        self.assertEqual(prepared.resolve(self.root, self.date), {'enabled': 'false'})
        self.assertEqual(prepared.guarded_build(self.root, self.date, lambda: result), result)
        self.assertFalse((self.cache / prepared.MARKER).exists())

    def test_changed_complete_audio_or_newer_edition_cannot_be_replaced(self):
        write_json(self.root / 'release.json', {**self.complete_result(), 'edition_date': '2099-01-01'})
        with self.assertRaisesRegex(RuntimeError, 'another edition'):prepared.resolve(self.root, self.date)

    def test_readiness_skips_all_paid_probes_only_for_valid_staged_material(self):
        self.stage();checker = Mock();factory = Mock()
        report = preflight.preflight(self.root, self.date, checker, factory)
        self.assertTrue(report['skipped']);self.assertIsNone(report['passed'])
        checker.assert_not_called();factory.assert_not_called()

    def test_invalid_prepared_material_has_no_provider_fallback(self):
        checker = Mock();factory = Mock()
        report = preflight.preflight(self.root, self.date, checker, factory)
        self.assertFalse(report['passed']);self.assertFalse(report['skipped'])
        checker.assert_not_called();factory.assert_not_called()


if __name__ == '__main__':unittest.main()
