"""Fault-injection coverage for the bounded, source-bound editorial loop."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_audit_loop as loop
import release_pipeline as pipeline
import release_evidence as evidence
from release_core import write_json,read_json
from release_editorial import fingerprint
from release_diagnostics import Diagnostics
from test_release import fixture,DATE
from evidence_fixture import fake_source


def response(value,web=True,status='completed'):
    return {'status':status,'output':([
        {'type':'web_search_call','action':{'sources':[{'url':'https://www.cms.gov/test-1'}]}}
    ] if web else [])+[
        {'type':'message','content':[{'type':'output_text','text':json.dumps(value)}]}]}


def finding(kind='unsupported_claim',path='/stories/0/why_it_matters'):
    return {'id':'f1','kind':kind,'path':path,'quote':'Tests the compiler.',
            'source_ids':['s1'],'explanation':'Synthetic claim requires qualification.',
            'required_change':'Identify this as a proposed check, not a verified result.'}


class AuditLoopTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.cache=Path(tmp.name);self.e=fixture()
        p=patch.object(evidence,'fetch_source',side_effect=fake_source);p.start();self.addCleanup(p.stop)
        self.docs=evidence.collect_source_evidence(self.e,self.cache)
        self.fail={'review_complete':True,'findings':[finding()]}
        self.clean={'review_complete':True,'findings':[]}
        self.plan={'replacements':[{'path':'/stories/0/why_it_matters','before':'Tests the compiler.',
                    'after':'Leadership should test the compiler before relying on its output.','addresses':['f1']}]}
        write_json(self.cache/'attempts.json',{'attempts':2})
    def run_loop(self,api):
        return loop.audit_and_correct(self.e,self.cache,'test-model',api,pipeline.output_text,
                                      self.docs,set(),None)
    def test_clean_review_does_not_generate_correction(self):
        api=Mock(return_value=response(self.clean));out=self.run_loop(api)
        self.assertEqual(api.call_count,1);self.assertTrue(out['audit']['approved'])
        self.assertEqual(out['edition'],self.e)
    def test_advisory_is_not_false_factual_rejection(self):
        report={'review_complete':True,'findings':[finding('advisory')]}
        api=Mock(return_value=response(report));out=self.run_loop(api)
        self.assertTrue(out['audit']['approved']);self.assertEqual(api.call_count,1)
        self.assertEqual(out['structured_review']['advisory_count'],1)
    def test_blocking_findings_require_correction_and_fresh_audit(self):
        api=Mock(side_effect=[response(self.fail),response(self.plan,False),response(self.clean)])
        out=self.run_loop(api)
        self.assertEqual(api.call_count,3);self.assertTrue(out['audit']['approved'])
        self.assertNotEqual(out['edition']['stories'][0]['why_it_matters'],self.e['stories'][0]['why_it_matters'])
        self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':2})
        self.assertEqual(read_json(self.cache/'audit-bound.json')['candidate_sha256'],fingerprint(out['edition']))
    def test_every_blocking_kind_is_blocking(self):
        for kind in loop.BLOCKING:
            self.assertEqual(len(loop.validate_review({'review_complete':True,'findings':[finding(kind)]},self.e)),1)
    def test_repeated_rejection_stays_blocked(self):
        corrected=copy.deepcopy(self.fail);corrected['findings'][0]['quote']=self.plan['replacements'][0]['after']
        api=Mock(side_effect=[response(self.fail),response(self.plan,False),response(corrected)])
        with self.assertRaisesRegex(RuntimeError,'single editorial correction'):self.run_loop(api)
        with self.assertRaisesRegex(RuntimeError,'single editorial correction'):self.run_loop(api)
        self.assertEqual(api.call_count,3);self.assertFalse((self.cache/'approved.json').exists())
    def test_incomplete_review_cannot_approve(self):
        api=Mock(return_value=response({'review_complete':False,'findings':[]}))
        with self.assertRaises(RuntimeError):self.run_loop(api)
        self.assertFalse((self.cache/'approved.json').exists())
    def test_uncompleted_response_cannot_approve(self):
        api=Mock(return_value=response(self.clean,status='incomplete'))
        with self.assertRaises(AssertionError):self.run_loop(api)
        self.assertFalse((self.cache/'approved.json').exists())
    def test_missing_web_retrieval_cannot_approve(self):
        api=Mock(return_value=response(self.clean,False))
        with self.assertRaisesRegex(RuntimeError,'live web'):self.run_loop(api)
    def test_final_audit_needs_new_web_retrieval(self):
        api=Mock(side_effect=[response(self.fail),response(self.plan,False),response(self.clean,False)])
        with self.assertRaisesRegex(RuntimeError,'live web'):self.run_loop(api)
        self.assertFalse((self.cache/'approved.json').exists())
    def test_ambiguous_request_not_resent(self):
        api=Mock(side_effect=TimeoutError('transport'))
        with self.assertRaises(TimeoutError):self.run_loop(api)
        with self.assertRaisesRegex(RuntimeError,'already reserved'):self.run_loop(api)
        self.assertEqual(api.call_count,1)
    def test_repeated_success_reuses_paid_results(self):
        api=Mock(side_effect=[response(self.fail),response(self.plan,False),response(self.clean)])
        first=self.run_loop(api);again=self.run_loop(api)
        self.assertEqual(first['edition'],again['edition']);self.assertEqual(api.call_count,3)
    def test_new_fetch_timestamp_does_not_spend_again(self):
        api=Mock(return_value=response(self.clean));self.run_loop(api)
        self.docs=copy.deepcopy(self.docs)
        for d in self.docs:d['retrieved_at']='2026-10-11T08:59:00Z'
        self.run_loop(api);self.assertEqual(api.call_count,1)
    def test_changed_evidence_invalidates_cached_request(self):
        api=Mock(return_value=response(self.clean));self.run_loop(api)
        self.docs=copy.deepcopy(self.docs);self.docs[0]['text']+='Changed guidance.'
        from release_core import digest
        self.docs[0]['text_sha256']=digest(self.docs[0]['text'])
        with self.assertRaisesRegex(ValueError,'checkpoint differs'):self.run_loop(api)
        self.assertEqual(api.call_count,1)
    def test_invented_quote_rejected(self):
        bad=copy.deepcopy(self.fail);bad['findings'][0]['quote']='Not in this field'
        with self.assertRaises(ValueError):loop.validate_review(bad,self.e)
    def test_unknown_source_rejected(self):
        bad=copy.deepcopy(self.fail);bad['findings'][0]['source_ids']=['invented']
        with self.assertRaises(Exception):loop.validate_review(bad,self.e)
    def test_duplicate_findings_rejected(self):
        bad=copy.deepcopy(self.fail);bad['findings']*=2
        with self.assertRaises(ValueError):loop.validate_review(bad,self.e)
    def test_source_urls_not_editable(self):
        plan=copy.deepcopy(self.plan);plan['replacements'][0]['path']='/sources/0/url'
        with self.assertRaises(Exception):loop.apply_replacements(self.e,self.fail,plan)
    def test_edition_date_not_editable(self):
        self.assertFalse(loop.editable('/edition_date'))
    def test_references_not_editable(self):
        self.assertFalse(loop.editable('/stories/0/source_ids/0'))
    def test_old_value_must_match(self):
        plan=copy.deepcopy(self.plan);plan['replacements'][0]['before']='Different'
        with self.assertRaises(ValueError):loop.apply_replacements(self.e,self.fail,plan)
    def test_missing_blocking_field_is_not_repaired(self):
        plan=copy.deepcopy(self.plan);plan['replacements'][0].update(path='/bluf',before=self.e['bluf'])
        with self.assertRaises(ValueError):loop.apply_replacements(self.e,self.fail,plan)
    def test_duplicate_patch_is_not_allowed(self):
        plan=copy.deepcopy(self.plan);plan['replacements']*=2
        with self.assertRaises(ValueError):loop.apply_replacements(self.e,self.fail,plan)
    def test_correction_cannot_invent_official_deadline(self):
        e=copy.deepcopy(self.e);e['deadlines'][0]['kind']='Editorial checkpoint'
        f=finding(path='/deadlines/0/kind');f['quote']='Editorial checkpoint'
        p={'replacements':[{'path':f['path'],'before':f['quote'],'after':'Official deadline','addresses':['f1']}]}
        with self.assertRaises(ValueError):loop.apply_replacements(e,{'review_complete':True,'findings':[f]},p)
    def test_bad_word_count_after_correction_is_blocked(self):
        p=copy.deepcopy(self.plan);p['replacements'].append({'path':'/podcast/opening',
            'before':self.e['podcast']['opening'],'after':'An incomplete section.','addresses':['f1']})
        with self.assertRaises(AssertionError):loop.apply_replacements(self.e,self.fail,p)
    def test_source_records_preserved(self):
        e=loop.apply_replacements(self.e,self.fail,self.plan);self.assertEqual(e['sources'],self.e['sources'])
    def test_missing_evidence_stops_before_audit(self):
        self.docs=[];api=Mock()
        with self.assertRaises(ValueError):self.run_loop(api)
        api.assert_not_called()
    def test_error_cannot_expose_credential(self):
        bad={'review_complete':True,'findings':[finding('advisory')]}
        bad['findings'][0]['explanation']='sk-proj-'+'s'*30
        with self.assertRaisesRegex(ValueError,'credential'):self.run_loop(Mock(return_value=response(bad)))
    def test_tampered_cached_result_rejected(self):
        api=Mock(return_value=response(self.clean));self.run_loop(api)
        p=self.cache/'editorial-loop-v1/initial-result.json';v=read_json(p);v['value']['review_complete']=False;write_json(p,v)
        with self.assertRaisesRegex(ValueError,'integrity'):self.run_loop(api)
    def test_new_draft_cannot_reset_daily_editorial_budget(self):
        api=Mock(return_value=response(self.clean));self.run_loop(api);self.e['title']='Changed title'
        with self.assertRaisesRegex(ValueError,'another candidate'):self.run_loop(api)
        self.assertEqual(api.call_count,1)


class RetainedAuditTests(unittest.TestCase):
    setUp = AuditLoopTests.setUp
    def rejected_cache(self):
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'777'}):
            d=Diagnostics(self.cache,DATE);d.validate(self.e,lambda e,x,r:None,'content',set())
            d.fail('evidence-audit',RuntimeError('Audit rejected candidate'),self.e)
        write_json(self.cache/'audit.json',{'approved':False,'issues':['Synthetic rejection']})
    def test_load_retained_candidate_after_exhaustion(self):
        self.rejected_cache();loaded=loop.load_rejected_candidate(self.cache,DATE)
        self.assertEqual(loaded[0],self.e);self.assertEqual(read_json(self.cache/'attempts.json')['attempts'],2)
    def test_wrong_date_is_not_reused(self):
        self.rejected_cache();self.assertIsNone(loop.load_rejected_candidate(self.cache,'2026-10-12'))
    def test_changed_retained_snapshot_is_rejected(self):
        self.rejected_cache();p=next((self.cache/'candidates').glob('content-*.json'))
        v=read_json(p);v['candidate']['bluf']='Tampered';write_json(p,v)
        with self.assertRaises(ValueError):loop.load_rejected_candidate(self.cache,DATE)
    def test_actual_pipeline_resumes_without_research_or_counter_reset(self):
        self.rejected_cache();api=Mock(side_effect=[response(self.fail),response(self.plan,False),response(self.clean)])
        with patch.dict(os.environ,{'RURAL_UPDATE_STRUCTURED_REVIEW':'true'}),patch.object(pipeline,'request_api',api):
            out=pipeline.research(DATE,{},self.cache)
        self.assertTrue(out['audit']['approved']);self.assertEqual(api.call_count,3)
        self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':2})
        self.assertTrue(all('rural_update_edition'!=c.args[0]['text']['format']['name'] for c in api.call_args_list))

if __name__=='__main__':unittest.main()
