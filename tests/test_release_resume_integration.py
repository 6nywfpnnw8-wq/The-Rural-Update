"""The retained-candidate route must use the unchanged full audit/provenance gates."""
import json
import unittest
from unittest.mock import Mock, patch
import test_release_resume as fixtures
import release_pipeline as pipeline
from test_release import DATE
from release_core import write_json


def audit_response(approved=True, urls=()):
    return {'status':'completed','output':[
        {'type':'web_search_call','action':{'sources':[{'url':u} for u in urls]}},
        {'type':'message','content':[{'type':'output_text','text':json.dumps({
            'approved':approved,'issues':[] if approved else ['Unsupported material claim']})}]}]}


class ResumeAuditTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.StyleRecoveryTests(methodName='test_no_candidate_is_not_invented')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.cache=self.fixture.cache

    def test_exhausted_generation_can_finish_audit_without_new_draft(self):
        api=Mock(return_value=audit_response())
        with patch.object(pipeline,'request_api',api):
            record=pipeline.research(DATE,{},self.cache)
        self.assertTrue(record['audit']['approved'])
        self.assertEqual(record['edition']['bluf'],'Review - then act.')
        self.assertEqual(api.call_count,1)
        self.assertEqual(api.call_args.args[0]['text']['format']['name'],'editorial_audit')
        self.assertEqual(json.loads((self.cache/'attempts.json').read_text())['attempts'],2)

    def test_rejected_audit_cannot_be_approved_or_retried_forever(self):
        api=Mock(return_value=audit_response(False))
        with patch.object(pipeline,'request_api',api):
            with self.assertRaisesRegex(RuntimeError,'audit rejected'):
                pipeline.research(DATE,{},self.cache)
            with self.assertRaises(AssertionError):pipeline.research(DATE,{},self.cache)
        self.assertEqual(api.call_count,1)
        self.assertFalse((self.cache/'approved.json').exists())

    def test_claimed_audit_without_web_retrieval_rejected(self):
        response=audit_response();response['output']=response['output'][1:]
        with patch.object(pipeline,'request_api',Mock(return_value=response)):
            with self.assertRaisesRegex(AssertionError,'did not retrieve'):
                pipeline.research(DATE,{},self.cache)
        self.assertFalse((self.cache/'approved.json').exists())

    def test_missing_provenance_still_blocks_approval(self):
        for p in (self.cache/'candidates').glob('generated-*.json'):
            data=json.loads(p.read_text());data['retrieved_urls']=data['retrieved_urls'][:1]
            write_json(p,data)
        with patch.object(pipeline,'request_api',Mock(return_value=audit_response())):
            with self.assertRaises(AssertionError):pipeline.research(DATE,{},self.cache)
        self.assertFalse((self.cache/'approved.json').exists())

if __name__=='__main__':unittest.main()
