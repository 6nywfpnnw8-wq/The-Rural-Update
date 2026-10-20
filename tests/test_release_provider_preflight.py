"""Offline provider-preflight regression checks. No live calls or credentials."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops"))
import publisher_provider_check as pre
from check_openai_access import CheckFailure

DATE = "2026-10-21"


class PublisherProviderPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root / ".release-cache" / DATE / "attempts.json"
        self.ledger.parent.mkdir(parents=True)
        self.ledger.write_text('{"attempts": 2}\n')
        self.original = self.ledger.read_bytes()
        self.env = patch.dict(os.environ, {"GITHUB_RUN_ID": "test-123"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_check(self, passed=False, status=401):
        result = {"passed": passed, "checks": [
            {"stage": "research_and_web_search", "passed": passed,
             "http_status": status}]}
        checker = Mock(return_value=result)
        report = pre.preflight(self.root, DATE, checker, Mock())
        return report, checker

    def complete_release(self, edition=DATE):
        names = ["index.html", "podcast.xml", "archive/catalog.json",
                 f"archive/{edition}.html", f"audio/{edition}.mp3",
                 f"podcast-script/{edition}.txt", f"transcript/{edition}.html",
                 f"data/audio-quality-{edition}.json"]
        for name in names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture")
        manifest = {"schema_version": 1, "edition_date": edition,
                    "audio_status": "complete", "files": {n: {} for n in names}}
        (self.root / "release.json").write_text(json.dumps(manifest))

    def test_401_preserves_generation_ledger_and_stops(self):
        report, checker = self.run_check()
        self.assertFalse(report["passed"])
        checker.assert_called_once()
        self.assertEqual(self.ledger.read_bytes(), self.original)
        self.assertFalse(report["research_budget_modified"])
        self.assertFalse(report["publication_attempted"])
        self.assertIn("HTTP 401", pre.failure_message(self.root, DATE))

    def test_success_also_preserves_generation_ledger(self):
        report, _ = self.run_check(True, None)
        self.assertTrue(report["passed"])
        self.assertEqual(self.ledger.read_bytes(), self.original)

    def test_complete_release_redeploy_needs_no_paid_test(self):
        self.complete_release()
        checker = Mock()
        report = pre.preflight(self.root, DATE, checker, Mock())
        checker.assert_not_called()
        self.assertTrue(report["skipped"])
        self.assertIsNone(report["passed"])

    def test_previous_edition_does_not_skip(self):
        self.complete_release("2026-10-20")
        _, checker = self.run_check(True, None)
        checker.assert_called_once()

    def test_missing_audio_does_not_skip(self):
        self.complete_release()
        (self.root / f"audio/{DATE}.mp3").unlink()
        _, checker = self.run_check()
        checker.assert_called_once()

    def test_corrupt_manifest_does_not_skip(self):
        (self.root / "release.json").write_text("not json")
        _, checker = self.run_check()
        checker.assert_called_once()

    def test_missing_key_stops_without_echoing_credentials(self):
        factory = Mock(side_effect=CheckFailure("missing_or_malformed_key"))
        checker = Mock()
        report = pre.preflight(self.root, DATE, checker, factory)
        checker.assert_not_called()
        self.assertFalse(report["passed"])
        self.assertEqual(self.ledger.read_bytes(), self.original)

    def test_unexpected_failure_message_is_not_retained(self):
        checker = Mock(side_effect=RuntimeError("synthetic-private-key"))
        report = pre.preflight(self.root, DATE, checker, Mock())
        self.assertNotIn("synthetic-private-key", json.dumps(report))
        self.assertEqual(report["checks"][0]["reason"], "preflight_local_error")

    def test_alert_does_not_use_another_runs_report(self):
        self.run_check()
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "other"}):
            self.assertNotIn("HTTP 401", pre.failure_message(self.root, DATE))

    def test_alert_does_not_use_another_dates_report(self):
        self.run_check()
        self.assertNotIn("HTTP 401", pre.failure_message(self.root, "2026-10-22"))

    def test_alert_does_not_echo_unrecognized_stage_or_body(self):
        report = {"run_id": "test-123", "edition_date": DATE, "passed": False,
                  "checks": [{"passed": False, "stage": "synthetic-private-key",
                              "reason": "synthetic-private-key", "http_status": "token"}]}
        (self.root / pre.REPORT).write_text(json.dumps(report))
        self.assertNotIn("synthetic-private-key", pre.failure_message(self.root, DATE))

    def test_old_report_is_replaced(self):
        (self.root / pre.REPORT).write_text("old report")
        report, _ = self.run_check()
        self.assertEqual(json.loads((self.root / pre.REPORT).read_text()), report)

    def test_invalid_date_makes_no_request(self):
        checker = Mock()
        with self.assertRaises(ValueError):
            pre.preflight(self.root, "not-a-date", checker, Mock())
        checker.assert_not_called()


class ProviderWorkflowOrderTests(unittest.TestCase):
    def test_readiness_precedes_generation_and_uses_same_secret(self):
        source=(ROOT/'.github/workflows/publish.yml').read_text()
        readiness=source.index('id: provider_access')
        preparation=source.index('id: prepare')
        self.assertLess(readiness,preparation)
        self.assertIn('OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}',source[readiness:preparation])
        self.assertNotIn('continue-on-error: true',source[readiness:source.index('Inspect cached diagnostics')])
        self.assertIn("steps.provider_access.outcome == 'success'",source)
        self.assertIn('credential-check-report.json',source)


if __name__ == "__main__":
    unittest.main()
