"""Offline checks for the reviewed October 20 provider-access recovery.

These tests use temporary state only. They never invoke a provider or publish.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from release_research import ENGINE, reserve_corrective_attempt

DATE = '2026-10-20'
POLICIES = ROOT / 'repair-authorizations'


class October20RecoveryTests(unittest.TestCase):
    def test_reviewed_plan_cannot_approve_content(self):
        plan = json.loads((POLICIES / (DATE + '.json')).read_text())
        self.assertEqual(plan['edition_date'], DATE)
        self.assertEqual(plan['engine'], ENGINE)
        self.assertEqual(plan['maximum_additional_generation_attempts'], 1)
        self.assertIs(plan['publication_authorized'], False)
        self.assertIs(plan['validation_override'], False)
        self.assertIs(plan['research_counter_reset'], False)
        self.assertEqual(plan['credential_check_run_id'], 39470409283)
        self.assertNotIn('maximum_output_limit_resumes', plan)

    def test_one_reservation_preserves_original_attempt_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            ledger = cache / 'attempts.json'
            original = '{"attempts": 2}\n'
            ledger.write_text(original)
            self.assertTrue(reserve_corrective_attempt(cache, DATE, POLICIES))
            self.assertFalse(reserve_corrective_attempt(cache, DATE, POLICIES))
            self.assertEqual(ledger.read_text(), original)
            marker = json.loads((cache / 'corrective-generation-used.json').read_text())
            self.assertTrue(marker['original_attempt_ledger_unchanged'])
            self.assertIs(marker['publication_authorized'], False)

    def test_authorization_cannot_extend_another_date(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            self.assertFalse(reserve_corrective_attempt(cache, '2026-10-21', POLICIES))
            self.assertFalse((cache / 'corrective-generation-used.json').exists())


if __name__ == '__main__':
    unittest.main()
