"""Finding label formatting must not discard a completed evidence review."""
import copy,unittest
from unittest.mock import Mock,patch
import test_release_audit_loop as fixtures
import release_audit_loop as loop
from release_core import read_json
response=fixtures.response

class AuditFindingLabelTests(unittest.TestCase):
    setUp=fixtures.AuditLoopTests.setUp
    run_loop=fixtures.AuditLoopTests.run_loop
    def test_safe_underscore_label_preserves_the_finding(self):
        report=copy.deepcopy(self.fail);report['findings'][0]['id']='telehealth-what_changed'
        blocking=loop.validate_review(report,self.e)
        self.assertEqual(blocking,report['findings'])
    def test_safe_uppercase_label_preserved_exactly(self):
        report=copy.deepcopy(self.fail);report['findings'][0]['id']='FINDING_01'
        self.assertEqual(loop.validate_review(report,self.e)[0]['id'],'FINDING_01')
    def test_label_path_traversal_still_rejected(self):
        report=copy.deepcopy(self.fail);report['findings'][0]['id']='../f1'
        with self.assertRaises(ValueError):loop.validate_review(report,self.e)
    def test_fixed_label_format_reuses_completed_audit(self):
        report=copy.deepcopy(self.fail);report['findings'][0]['id']='telehealth-what_changed'
        plan=copy.deepcopy(self.plan);plan['replacements'][0]['addresses']=['telehealth-what_changed']
        api=Mock(return_value=response(report))
        actual_validate=loop.validate_review
        def old_format_bug(value,edition):
            if value['findings'] and '_' in value['findings'][0]['id']:
                raise ValueError('Old label restriction')
            return actual_validate(value,edition)
        with patch.object(loop,'validate_review',side_effect=old_format_bug):
            with self.assertRaises(ValueError):self.run_loop(api)
        self.assertEqual(api.call_count,1)
        # The already completed paid review remains intact. Only the previously
        # unused correction and final audit slots may make requests.
        api.reset_mock();api.side_effect=[response(plan,False),response(self.clean)]
        result=self.run_loop(api)
        self.assertEqual(api.call_count,2)
        self.assertTrue(result['audit']['approved'])
        self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':2})

if __name__=="__main__":unittest.main()
