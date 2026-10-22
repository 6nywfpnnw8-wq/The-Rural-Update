"""Metadata clarification never converts an incomplete audit into approval."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_audit_loop as loop
import release_source_dates as dates
import release_evidence as evidence
import release_pipeline as pipeline
from release_core import read_json, write_json
from release_editorial import fingerprint
from test_release import fixture, DATE
from test_release_audit_loop import response, finding
from evidence_fixture import fake_source

class SourceDateReviewTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.cache=self.root/'cache';self.reviews=self.root/'plans'
        self.folder=self.cache/'editorial-loop-v1';self.folder.mkdir(parents=True)
        self.original=fixture();self.original['sources'][0]['published_date']=None
        self.candidate=copy.deepcopy(self.original);self.candidate['title']='Previously corrected test candidate'
        self.candidate['sources'][1]['published_date']=None
        self.updated=copy.deepcopy(self.candidate);self.updated['sources'][0]['published_date']='2026-10-10'
        self.incomplete={'review_complete':False,'findings':[]}
        sha=fingerprint(self.candidate)
        write_json(self.cache/'candidates'/('editorial-corrected-'+sha[:16]+'.json'),{
            'candidate':self.candidate,'candidate_sha256':sha,'redacted':False,'publication_authorized':False})
        write_json(self.folder/'reference-corrected-final-reserved.json',{'payload_sha256':'retained-request'})
        write_json(self.folder/'reference-corrected-final-result.json',{
            'payload_sha256':'retained-request','value_sha256':fingerprint(self.incomplete),'value':self.incomplete})
        write_json(self.cache/'attempts.json',{'attempts':2})
        source=self.candidate['sources'][0]
        self.plan={'schema_version':1,'edition_date':DATE,'base_candidate_sha256':fingerprint(self.original),
            'candidate_sha256':sha,'incomplete_review_sha256':fingerprint(self.incomplete),
            'updated_candidate_sha256':fingerprint(self.updated),'publication_authorized':False,
            'maximum_additional_audits':1,'source_update':{'id':source['id'],'url':source['url'],
                                                       'before':None,'after':'2026-10-10'}}
        self.planpath=self.reviews/(DATE+'.json');write_json(self.planpath,self.plan)
        for item in (patch.object(dates,'REVIEW_ROOT',self.reviews),
                     patch.object(evidence,'fetch_source',side_effect=fake_source)):
            item.start();self.addCleanup(item.stop)
        self.preserved={p:p.read_bytes() for p in [self.cache/'attempts.json',
            self.folder/'reference-corrected-final-reserved.json',self.folder/'reference-corrected-final-result.json']}
    def execute(self,api):
        return dates.take_source_date_review(self.original,self.cache,'test-model',api,pipeline.output_text,
            set(),None,'Full independent audit.\n'+dates.DATE_POLICY,loop.audit_schema,loop.validate_review,loop._call)
    def test_no_plan_does_not_make_a_call(self):
        self.planpath.unlink();api=Mock();self.assertIsNone(self.execute(api));api.assert_not_called()
    def test_only_publication_metadata_changes_and_fresh_review_passes(self):
        api=Mock(return_value=response({'review_complete':True,'findings':[]}))
        result=self.execute(api)
        self.assertEqual(api.call_count,1);self.assertEqual(result['edition'],self.updated)
        self.assertTrue(result['audit']['approved'])
        self.assertIsNone(result['edition']['sources'][1]['published_date'])
        for p,data in self.preserved.items():self.assertEqual(p.read_bytes(),data)
        self.assertIn(dates.DATE_POLICY,api.call_args.args[0]['input'])
        self.assertEqual(read_json(self.cache/'audit-bound.json')['candidate_sha256'],fingerprint(self.updated))
    def test_repeated_identical_review_uses_saved_result(self):
        api=Mock(return_value=response({'review_complete':True,'findings':[]}))
        self.execute(api);self.execute(api);self.assertEqual(api.call_count,1)
    def test_incomplete_fresh_review_cannot_approve(self):
        api=Mock(return_value=response(self.incomplete))
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError,'review is incomplete'):self.execute(api)
        self.assertEqual(api.call_count,1);self.assertFalse((self.cache/'approved.json').exists())
    def test_blocking_fresh_review_cannot_approve(self):
        api=Mock(return_value=response({'review_complete':True,'findings':[finding()]}))
        with self.assertRaisesRegex(RuntimeError,'still has blocking'):self.execute(api)
        self.assertFalse((self.cache/'approved.json').exists())
    def test_no_live_retrieval_cannot_approve_or_retry(self):
        api=Mock(return_value=response({'review_complete':True,'findings':[]},False))
        with self.assertRaisesRegex(RuntimeError,'live web'):self.execute(api)
        with self.assertRaisesRegex(RuntimeError,'already reserved'):self.execute(api)
        self.assertEqual(api.call_count,1)
    def test_ambiguous_request_is_not_repeated(self):
        api=Mock(side_effect=TimeoutError('simulated'))
        with self.assertRaises(TimeoutError):self.execute(api)
        with self.assertRaisesRegex(RuntimeError,'already reserved'):self.execute(api)
        self.assertEqual(api.call_count,1)
    def test_plan_cannot_approve(self):
        self.plan['publication_authorized']=True;write_json(self.planpath,self.plan)
        api=Mock()
        with self.assertRaisesRegex(ValueError,'authorization differs'):self.execute(api)
        api.assert_not_called()
    def test_future_date_cannot_be_added(self):
        self.plan['source_update']['after']='2099-01-01';write_json(self.planpath,self.plan)
        with self.assertRaisesRegex(ValueError,'reviewed publication date'):self.execute(Mock())
    def test_other_candidate_cannot_use_recovery(self):
        self.original['title']='Other'
        with self.assertRaisesRegex(ValueError,'authorization differs'):self.execute(Mock())
    def test_tampered_review_cannot_use_recovery(self):
        p=self.folder/'reference-corrected-final-result.json';d=read_json(p)
        d['value']['findings']=[finding()];write_json(p,d)
        with self.assertRaisesRegex(ValueError,'incomplete source-date review differs'):self.execute(Mock())
    def test_recovery_cannot_edit_source_url(self):
        self.plan['source_update']['url']='https://www.cms.gov/not-the-original';write_json(self.planpath,self.plan)
        with self.assertRaisesRegex(ValueError,'reviewed publication date'):self.execute(Mock())
    def test_ordinary_audit_has_date_role_policy(self):
        self.planpath.unlink();edition=fixture();docs=evidence.collect_source_evidence(edition,self.cache)
        api=Mock(return_value=response({'review_complete':True,'findings':[]}))
        out=loop.audit_and_correct(edition,self.cache,'test-model',api,pipeline.output_text,docs,set(),None)
        self.assertTrue(out['audit']['approved'])
        self.assertIn(dates.DATE_POLICY,api.call_args.args[0]['input'])

if __name__=='__main__':unittest.main()
