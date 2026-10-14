"""Eligibility diagnostics expose fixed reasons, not unpublished draft prose."""
import json
import unittest
import test_release_resume as fixtures
from test_release import DATE
from release_resume import take_style_recovery

class RecoveryReasonTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.StyleRecoveryTests(methodName='test_no_candidate_is_not_invented')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.cache=self.fixture.cache

    def test_secondary_content_failure_is_named_without_draft(self):
        self.fixture.candidate['actions'][0]['due_date']='2026-10-01'
        self.fixture.save(self.fixture.candidate)
        self.assertIsNone(take_style_recovery(self.cache,DATE))
        report=json.loads((self.cache/'validation-style-recovery.json').read_text())
        self.assertEqual(report['reason'],'normalized_draft_has_another_validation_failure')
        self.assertEqual(report['validation_message'],'Action due date is already past')
        self.assertNotIn('Review',json.dumps(report))
        self.assertFalse(report['publication_authorized'])

    def test_missing_generated_snapshot_is_explicit(self):
        for p in (self.cache/'candidates').glob('generated-*.json'):p.unlink()
        self.assertIsNone(take_style_recovery(self.cache,DATE))
        report=json.loads((self.cache/'validation-style-recovery.json').read_text())
        self.assertEqual(report['reason'],'matching_original_retrieval_evidence_missing')
        self.assertEqual(json.loads((self.cache/'attempts.json').read_text())['attempts'],2)

    def test_snapshot_integrity_failure_is_explicit(self):
        p=next((self.cache/'candidates').glob('content-*.json'));p.unlink()
        self.assertIsNone(take_style_recovery(self.cache,DATE))
        report=json.loads((self.cache/'validation-style-recovery.json').read_text())
        self.assertEqual(report['reason'],'snapshot_missing_redacted_or_integrity_mismatch')
        self.assertFalse((self.cache/'style-recovery-attempt.json').exists())

if __name__=='__main__':unittest.main()
