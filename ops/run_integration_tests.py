"""Run offline controls and write their actual structured unittest outcome."""
from __future__ import annotations
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_result(result, path, code_sha):
    report = {'schema_version': 1, 'code_sha': code_sha, 'successful': result.wasSuccessful(),
              'tests_run': result.testsRun, 'skipped': len(result.skipped),
              'failures': len(result.failures), 'errors': len(result.errors),
              'expected_failures': len(result.expectedFailures),
              'unexpected_successes': len(result.unexpectedSuccesses)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    code_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_release*.py')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    write_result(result, ROOT / '.integration-output/offline-controls.json', code_sha)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':raise SystemExit(main())
