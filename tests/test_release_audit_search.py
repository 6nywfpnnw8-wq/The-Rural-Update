"""Do not mistake a content verdict without actual search for a complete audit."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from release_core import read_json,write_json
from release_editorial import fingerprint
from release_audit_search import require_audit_search,take_tool_omission_recovery
from test_release import fixture,DATE
from evidence_fixture import fake_source
from test_release_resume_integration import audit_response
import release_editorial,release_evidence,release_pipeline as pipeline

class AuditSearchTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.cache=self.root/'cache';self.cache.mkdir()
        self.plans=self.root/'audit-tool-recovery';self.plans.mkdir()
        self.e=fixture();self.sha=fingerprint(self.e)
        self.plan={'schema_version':1,'edition_date':DATE,'failed_run_id':777,
            'candidate_sha256':self.sha,'publication_authorized':False,
            'maximum_audit_calls':1,'generation_calls':0}
        write_json(self.plans/(DATE+'.json'),self.plan)
        self.snapshot=self.cache/'candidates'/('resumed-content-'+self.sha[:16]+'.json')
        write_json(self.snapshot,{'schema_version':1,'edition_date':DATE,'stage':'resumed-content',
            'redacted':False,'publication_authorized':False,'candidate':self.e,'candidate_sha256':self.sha})
        write_json(self.cache/'validation-resumed-content.json',{'edition_date':DATE,
            'run_id':'777','passed':True,'snapshot':{'candidate_sha256':self.sha}})
        write_json(self.cache/'source-evidence.json',{'candidate_sha256':self.sha,'complete':True})
        write_json(self.cache/'audit.json',{'approved':True,'issues':[]})
        write_json(self.cache/'api-responses.json',{'responses':[{'stage':'editorial_audit',
            'run_id':'777','status':'completed','incomplete_reason':None,'output_types':{'message':1}}]})
        write_json(self.cache/'attempts.json',{'attempts':2})
        write_json(self.cache/'claim-correction-used.json',{'used':True})
    def invoke(self):return take_tool_omission_recovery(self.cache,DATE,self.plans)
    def test_exact_snapshot_not_changed_and_counters_preserved(self):
        counters=[(p,p.read_bytes()) for p in (self.cache/'attempts.json',self.cache/'claim-correction-used.json')]
        e,urls=self.invoke();self.assertEqual(e,self.e);self.assertEqual(urls,set())
        for p,raw in counters:self.assertEqual(raw,p.read_bytes())
        self.assertFalse((self.cache/'approved.json').exists())
    def test_cannot_repeat(self):
        self.invoke()
        with self.assertRaises(RuntimeError):self.invoke()
    def test_rejected_verdict_is_not_eligible(self):
        write_json(self.cache/'audit.json',{'approved':False,'issues':['unsupported']})
        with self.assertRaises(ValueError):self.invoke()
    def test_actual_searched_audit_is_not_eligible(self):
        p=self.cache/'api-responses.json';v=read_json(p);v['responses'][-1]['output_types']['web_search_call']=1;write_json(p,v)
        with self.assertRaises(ValueError):self.invoke()
    def test_other_run_is_not_eligible(self):
        p=self.cache/'api-responses.json';v=read_json(p);v['responses'][-1]['run_id']='888';write_json(p,v)
        with self.assertRaises(ValueError):self.invoke()
    def test_incomplete_response_is_not_eligible(self):
        p=self.cache/'api-responses.json';v=read_json(p);v['responses'][-1]['status']='incomplete';write_json(p,v)
        with self.assertRaises(ValueError):self.invoke()
    def test_tampered_candidate_rejected(self):
        v=read_json(self.snapshot);v['candidate']['bluf']='changed';write_json(self.snapshot,v)
        with self.assertRaises(ValueError):self.invoke()
    def test_other_date_not_authorized(self):
        self.assertIsNone(take_tool_omission_recovery(self.cache,'2026-10-12',self.plans))
    def test_new_audit_still_can_reject(self):
        api=Mock(return_value=audit_response(False))
        with patch.object(release_editorial,'REVIEW_ROOT',self.root/'editorial-review'),patch.object(pipeline,'request_api',api),patch.object(release_evidence,'fetch_source',side_effect=fake_source):
            with self.assertRaisesRegex(RuntimeError,'audit rejected'):pipeline.research(DATE,{},self.cache)
            with self.assertRaises(RuntimeError):pipeline.research(DATE,{},self.cache)
        self.assertEqual(api.call_count,1);self.assertFalse((self.cache/'approved.json').exists())
    def test_still_requires_actual_search_result(self):
        response=audit_response(True);response['output']=[x for x in response['output'] if x.get('type')!='web_search_call']
        api=Mock(return_value=response)
        with patch.object(release_editorial,'REVIEW_ROOT',self.root/'editorial-review'),patch.object(pipeline,'request_api',api),patch.object(release_evidence,'fetch_source',side_effect=fake_source):
            with self.assertRaisesRegex(AssertionError,'retrieve evidence'):pipeline.research(DATE,{},self.cache)
        self.assertFalse((self.cache/'approved.json').exists())
    def test_fresh_sources_and_audit_required(self):
        api=Mock(return_value=audit_response(True))
        with patch.object(release_editorial,'REVIEW_ROOT',self.root/'editorial-review'),patch.object(pipeline,'request_api',api),patch.object(release_evidence,'fetch_source',side_effect=fake_source) as fetch:
            result=pipeline.research(DATE,{},self.cache)
        self.assertTrue(result['audit']['approved']);self.assertEqual(fetch.call_count,5);self.assertEqual(api.call_count,1)
    def test_enforced_at_request_boundary(self):
        payload={'text':{'format':{'name':'editorial_audit'}},'tools':[{'type':'web_search'}]}
        with patch.object(pipeline,'_request_api',return_value={}) as api:pipeline.request_api(payload)
        self.assertEqual(api.call_args.args[0]['tool_choice'],'required')
        self.assertNotIn('tool_choice',payload)
    def test_non_audit_calls_unchanged(self):
        payload={'model':'test','input':'test'}
        self.assertIs(require_audit_search(payload),payload)
    def test_no_offered_search_is_not_accepted(self):
        with self.assertRaises(ValueError):require_audit_search({'text':{'format':{'name':'editorial_audit'}}})

if __name__=='__main__':unittest.main()
