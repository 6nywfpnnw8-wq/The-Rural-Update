"""Synthetic correction tests; no real content generation, credentials or publishing."""
import copy, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, Mock
import test_release as fixtures
import release_core as core
import release_pipeline as pipeline
import release_editorial as editorial
from test_release_narration import response


class EditorialRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.cache = self.root / 'cache'; self.cache.mkdir()
        self.review = self.root / 'review'; self.review.mkdir()
        self.patcher = patch.object(editorial, 'REVIEW_ROOT', self.review)
        self.patcher.start(); self.addCleanup(self.patcher.stop)
        original = fixtures.fixture(); original['signals'][2]['source_ids'].append('unresolved')
        checksum = editorial.fingerprint(original)
        relative = 'candidates/content-' + checksum[:16] + '.json'
        core.write_json(self.cache / relative, {'schema_version': 1, 'edition_date': fixtures.DATE,
            'stage': 'content', 'candidate_sha256': checksum, 'publication_authorized': False,
            'redacted': False, 'candidate': original, 'retrieved_urls': []})
        candidate = fixtures.fixture()
        self.plan = {'schema_version': 1, 'edition_date': fixtures.DATE,
            'base_snapshot': relative, 'base_candidate_sha256': checksum,
            'candidate': candidate, 'candidate_sha256': editorial.fingerprint(candidate),
            'publication_authorized': False, 'reviewed_source_urls': [s['url'] for s in candidate['sources']]}
        self.save()
        core.write_json(self.cache / 'attempts.json', {'attempts': 2})
    def save(self): core.write_json(self.review / (fixtures.DATE + '.json'), self.plan)
    def take(self): return editorial.take_reviewed_recovery(self.cache, fixtures.DATE)
    def test_reviewed_draft_still_has_no_api_provenance_or_approval(self):
        candidate, urls = self.take(); self.assertEqual(urls, set())
        core.validate_edition(candidate, fixtures.DATE)
        self.assertFalse((self.cache / 'approved.json').exists())
        self.assertEqual(core.read_json(self.cache / 'attempts.json')['attempts'], 2)
    def test_cannot_spend_second_retained_audit(self):
        self.take()
        with self.assertRaisesRegex(RuntimeError, 'allowance'): self.take()
    def test_style_reservation_is_respected(self):
        core.write_json(self.cache / 'style-recovery-attempt.json', {})
        with self.assertRaises(RuntimeError): self.take()
    def test_stale_base_hash_rejected(self):
        self.plan['base_candidate_sha256'] = '0' * 64; self.save()
        with self.assertRaises(ValueError): self.take()
    def test_changed_content_without_new_checksum_rejected(self):
        self.plan['candidate']['bluf'] = 'Altered'; self.save()
        with self.assertRaises(ValueError): self.take()
    def test_invalid_content_remains_blocked(self):
        self.plan['candidate']['signals'][2]['source_ids'].append('unknown')
        self.plan['candidate_sha256'] = editorial.fingerprint(self.plan['candidate']); self.save()
        with self.assertRaises(AssertionError): self.take()
    def test_correction_cannot_authorize_publication(self):
        self.plan['publication_authorized'] = True; self.save()
        with self.assertRaises(ValueError): self.take()
    def test_path_traversal_rejected(self):
        self.plan['base_snapshot'] = '../outside'; self.save()
        with self.assertRaises(ValueError): self.take()
    def test_different_date_has_no_plan(self):
        self.assertIsNone(editorial.take_reviewed_recovery(self.cache, '2026-10-15'))
    def test_rejected_audit_still_blocks_publication(self):
        api = Mock(return_value=response({'approved': False, 'issues': ['Unsupported statement']}, True))
        with patch.object(pipeline, 'request_api', api):
            with self.assertRaisesRegex(RuntimeError, 'audit rejected'): pipeline.research(fixtures.DATE, {}, self.cache)
        self.assertEqual(api.call_count, 1); self.assertFalse((self.cache / 'approved.json').exists())
    def test_full_audit_and_retrieval_are_required(self):
        api = Mock(return_value=response({'approved': True, 'issues': []}, True))
        with patch.object(pipeline, 'request_api', api): record = pipeline.research(fixtures.DATE, {}, self.cache)
        self.assertEqual(api.call_count, 1); self.assertTrue(record['audit']['approved'])
        self.assertEqual(core.read_json(self.cache / 'attempts.json')['attempts'], 2)
    def test_audit_cannot_skip_source_provenance(self):
        result = response({'approved': True, 'issues': []}, True)
        result['output'][0]['action']['sources'] = []
        with patch.object(pipeline, 'request_api', return_value=result):
            with self.assertRaises(AssertionError): pipeline.research(fixtures.DATE, {}, self.cache)
        self.assertFalse((self.cache / 'approved.json').exists())

if __name__ == '__main__': unittest.main()
