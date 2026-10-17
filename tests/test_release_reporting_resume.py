"""A retained reporting step can resume once only after its exact token-limit failure."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from jsonschema import Draft202012Validator,ValidationError
import release_research as sr
from release_core import SCHEMA,write_json
from test_release import fixture,DATE
from test_release_staged_research import response

class ReportingResumeTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name);self.policy=self.root/'policies';self.cache=self.root/'cache'
        self.plan={'schema_version':1,'edition_date':DATE,'engine':sr.ENGINE,
            'maximum_additional_generation_attempts':1,'publication_authorized':False,'reason':'User-requested repair',
            'maximum_output_limit_resumes':1,'resume_stage':'reporting','previous_output_limit':10000,'corrected_output_limit':16000}
        write_json(self.policy/(DATE+'.json'),self.plan)
        write_json(self.cache/'attempts.json',{'attempts':2})
        self.assertTrue(sr.reserve_corrective_attempt(self.cache,DATE,self.policy))
        self.payload={'model':'gpt-5-mini','input':'Edition '+DATE,'tools':[{'type':'web_search'}]}
        raw=response('partial report',status='incomplete');raw['incomplete_details']={'reason':'max_output_tokens'}
        send=Mock(side_effect=[response('Retained source notes',web=True),raw])
        with self.assertRaises(sr.ResponseStateError):sr.staged_request(self.payload,send,self.cache)
        sr.record_response(self.cache,{'max_output_tokens':10000,'text':{'format':{'name':'reporting'}}},raw,10)
    def test_resumes_once_without_discovery_or_counter_reset(self):
        before=(self.cache/'attempts.json').read_bytes()
        self.assertTrue(sr.reserve_corrective_attempt(self.cache,DATE,self.policy))
        self.assertFalse(sr.reserve_corrective_attempt(self.cache,DATE,self.policy))
        e=fixture();brief=copy.deepcopy(e);brief.pop('podcast')
        send=Mock(side_effect=[response(brief),response(e['podcast'])])
        sr.staged_request(self.payload,send,self.cache)
        self.assertEqual(send.call_count,2)
        self.assertNotIn('tools',send.call_args_list[0].args[0])
        self.assertEqual(send.call_args_list[0].args[0]['max_output_tokens'],16000)
        self.assertEqual((self.cache/'attempts.json').read_bytes(),before)
    def test_changed_context_cannot_create_new_discovery(self):
        self.assertTrue(sr.reserve_corrective_attempt(self.cache,DATE,self.policy))
        send=Mock()
        with self.assertRaises(RuntimeError):sr.staged_request({**self.payload,'input':'changed'},send,self.cache)
        send.assert_not_called()
    def test_other_error_does_not_qualify(self):
        raw=response('partial report',status='incomplete');raw['incomplete_details']={'reason':'content_filter'}
        sr.record_response(self.cache,{'text':{'format':{'name':'reporting'}},'max_output_tokens':10000},raw,1)
        self.assertFalse(sr.reserve_corrective_attempt(self.cache,DATE,self.policy))
    def test_audit_rejection_cannot_use_generation_continuation(self):
        write_json(self.cache/'audit.json',{'approved':False})
        self.assertFalse(sr.reserve_corrective_attempt(self.cache,DATE,self.policy))
    def test_missing_cached_evidence_not_researched_again(self):
        (self.cache/sr.ENGINE/'discovery.json').unlink()
        self.assertFalse(sr.reserve_corrective_attempt(self.cache,DATE,self.policy))
    def test_tampered_cached_notes_are_rejected(self):
        p=self.cache/sr.ENGINE/'discovery.json';v=json.loads(p.read_text());v['value']['notes']='modified';write_json(p,v)
        with self.assertRaises(RuntimeError):sr.reserve_corrective_attempt(self.cache,DATE,self.policy)
    def test_generation_caps_do_not_mutate_release_schema(self):
        before=json.dumps(SCHEMA,sort_keys=True);s=sr.reporting_schema()
        self.assertEqual(json.dumps(SCHEMA,sort_keys=True),before)
        self.assertLessEqual(s['properties']['stories']['items']['properties']['what_changed']['maxLength'],850)
    def test_overlong_generation_is_rejected_not_truncated(self):
        e=fixture();e.pop('podcast');e['stories'][0]['what_changed']='x'*851
        with self.assertRaises(ValidationError):Draft202012Validator(sr.reporting_schema()).validate(e)

if __name__=='__main__':unittest.main()
