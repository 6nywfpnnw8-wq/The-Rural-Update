"""Malformed reviews never approve; the existing final slot is reusable, not repeatable."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_audit_protocol as protocol
import release_audit_loop as loop
from release_editorial import fingerprint
from release_research import _text


class AuditProtocolTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.cache=Path(t.name)/'2026-10-24';self.folder=self.cache/'editorial-loop-v1'
        self.folder.mkdir(parents=True);self.policy_root=Path(t.name)/'policy';self.policy_root.mkdir()
        self.candidate={'edition_date':'2026-10-24','bluf':'Supported statement.', 'sources':[{'id':'a'}]}
        self.review={'review_complete':True,'findings':[{'id':'f1','kind':'unsupported_claim',
            'path':'/bluf','quote':'Supported statement.','source_ids':['a'],
            'explanation':'This is supported; no correction required.','required_change':'none'}]}
        self.request_sha='a'*64
        self.policy={'edition_date':'2026-10-24','failure_run_id':40108030234,
            'maximum_total_audit_requests':2,'use_existing_slot':'final',
            'additional_research_generation_calls':0,'additional_narration_generation_calls':0,
            'publication_authorized':False,'candidate_sha256':fingerprint(self.candidate),
            'initial_review_sha256':fingerprint(self.review),'initial_request_sha256':self.request_sha}
        self.save_review()
        (self.folder/'initial-reserved.json').write_text(json.dumps({'payload_sha256':self.request_sha,
            'publication_authorized':False,'run_id':'40108030234'}))
        (self.cache/'attempts.json').write_text('{"attempts":2}')

    def save_review(self):
        (self.folder/'initial-result.json').write_text(json.dumps({'value':self.review,
            'value_sha256':fingerprint(self.review),'payload_sha256':self.request_sha}))
        (self.policy_root/'2026-10-24.json').write_text(json.dumps(self.policy))

    def reserve(self):
        return protocol.use_final_review(self.candidate,self.cache,self.policy_root,loop.validate_review)

    def test_confirmation_cannot_be_classified_as_a_blocking_finding(self):
        with self.assertRaisesRegex(ValueError,'substantive correction'):
            loop.validate_review(self.review,self.candidate)

    def test_malformed_review_remains_intact_without_approval(self):
        before=(self.folder/'initial-result.json').read_bytes()
        self.assertTrue(self.reserve());self.assertTrue(self.reserve())
        self.assertEqual((self.folder/'initial-result.json').read_bytes(),before)
        self.assertFalse((self.cache/'approved.json').exists())
        self.assertFalse((self.folder/'correction-reserved.json').exists())

    def test_valid_blocking_review_cannot_take_protocol_continuation(self):
        self.review['findings'][0]['required_change']='Remove the unsupported statement.'
        self.policy['initial_review_sha256']=fingerprint(self.review);self.save_review()
        with self.assertRaisesRegex(ValueError,'malformed initial review'):self.reserve()

    def test_candidate_tampering_stops_before_final_review(self):
        self.candidate['bluf']='A different statement.'
        with self.assertRaisesRegex(ValueError,'candidate differs'):self.reserve()
        self.assertFalse((self.folder/'final-reserved.json').exists())

    def test_one_final_submission_is_reused_without_another_api_call(self):
        self.assertTrue(self.reserve())
        value={'review_complete':True,'findings':[]}
        payload={'input':'fresh complete review','tools':[{'type':'web_search'}]}
        raw={'status':'completed','output':[{'type':'web_search_call','action':{'sources':[
             {'url':'https://cms.gov/a'}]}},{'type':'message','content':[{
             'type':'output_text','text':json.dumps(value)}]}]}
        request=Mock(return_value=raw)
        first=loop._call(self.folder,'final',payload,request,_text)
        self.assertTrue(self.reserve())
        second=loop._call(self.folder,'final',payload,request,_text)
        self.assertEqual(first,second);self.assertEqual(request.call_count,1)
        self.assertEqual(loop.validate_review(first[0],self.candidate),[])
        self.assertEqual(json.loads((self.cache/'attempts.json').read_text()),{'attempts':2})


if __name__=='__main__':unittest.main()
