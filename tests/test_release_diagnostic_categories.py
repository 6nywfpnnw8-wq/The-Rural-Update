"""Regression checks: opaque errors remain private but distinguishable."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from release_diagnostics import error_details

class SafeExceptionCategoryTests(unittest.TestCase):
    def test_json_parse_failure_category_without_raw_data(self):
        import json
        try:
            json.loads('{private draft text')
        except json.JSONDecodeError as exc:
            report=error_details(exc)
        self.assertEqual(report['exception_category'],'JSONDecodeError')
        self.assertNotIn('private draft',str(report))
    def test_unrecognized_exception_never_exposes_message(self):
        class SecretFailure(Exception): pass
        report=error_details(SecretFailure('secret token 123'))
        self.assertEqual(report['exception_category'],'Other')
        self.assertNotIn('secret',str(report))
    def test_known_validation_reason_preserved(self):
        report=error_details(AssertionError('Executive BLUF is too long'))
        self.assertEqual(report['rule'],'bluf_length')

if __name__=='__main__': unittest.main()
