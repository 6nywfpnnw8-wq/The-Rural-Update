"""Repository integration checks for fallback and reviewed narration continuation."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_research as sr
from release_core import validate_edition, write_json
from release_prose import TOLERANCE
from test_release_staged_research import bounded_fixture, response, selection_response, reporting_response, DATE


class NarrationContinuationIntegrationTests(unittest.TestCase):
    def setUp(self):
        gate=patch.object(sr,'ensure_reporting_plan',return_value=None)
        gate.start();self.addCleanup(gate.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.e=bounded_fixture()
        self.report=copy.deepcopy(self.e);self.report.pop('podcast');self.report.pop('sources')
        self.payload={'model':'gpt-5-mini','input':'Edition '+DATE,'tools':[{'type':'web_search'}]}
        self.policy=self.root/'policies'

    def section(self,payload):
        self.assertEqual(payload['text']['format']['name'],'narration_section')
        self.assertNotIn('tools',payload)
        field=payload['text']['format']['schema']['properties']['text']
        count=field['minLength']//2+TOLERANCE
        return response({'text':' '.join(['Synthetic']*(count-1)+['ending.'])})

    def prepare(self):
        incomplete=response('partial text',status='incomplete')
        incomplete['incomplete_details']={'reason':'max_output_tokens'}
        first=[response('Observed evidence',web=True),selection_response(self.e['sources']),reporting_response(self.report),incomplete]
        calls=[]
        def send(payload):
            calls.append(payload)
            if first:return first.pop(0)
            raise TimeoutError('Stop before first section for a retained-work fixture')
        with self.assertRaises(TimeoutError):sr.staged_request(self.payload,send,self.root)
        write_json(self.root/'api-responses.json',{'responses':[{'stage':'narration','status':'incomplete','incomplete_reason':'max_output_tokens','requested_output_limit':8000}]})
        write_json(self.root/'attempts.json',{'attempts':2})
        write_json(self.root/'corrective-generation-used.json',{'used':True})
        plan={'schema_version':1,'edition_date':DATE,'engine':sr.ENGINE,
              'maximum_additional_generation_attempts':1,'publication_authorized':False,
              'reason':'Synthetic reviewed narration recovery','maximum_narration_limit_resumes':1,
              'narration_recovery_method':'sectioned-narration-v1','previous_narration_output_limit':8000}
        write_json(self.policy/(DATE+'.json'),plan)

    def test_known_output_limit_uses_bounded_sections_not_partial_text(self):
        incomplete=response('partial text',status='incomplete');incomplete['incomplete_details']={'reason':'max_output_tokens'}
        first=[response('Observed evidence',web=True),selection_response(self.e['sources']),reporting_response(self.report),incomplete]
        send=Mock(side_effect=lambda p:first.pop(0) if first else self.section(p))
        out=sr.staged_request(self.payload,send,self.root)
        e=json.loads(sr._text(out))
        self.assertEqual(e['sources'],self.e['sources'])
        self.assertEqual(e['stories'],self.e['stories'])
        self.assertEqual(send.call_count,14)
        self.assertNotIn('partial text',json.dumps(e))
        with self.assertRaises(AssertionError):validate_edition(e,DATE,set())
        self.assertFalse((self.root/'approved.json').exists())

    def test_reviewed_resume_reuses_three_stages_and_preserves_ledgers(self):
        self.prepare()
        original={n:(self.root/n).read_bytes() for n in ('attempts.json','corrective-generation-used.json')}
        self.assertTrue(sr.reserve_corrective_attempt(self.root,DATE,self.policy))
        send=Mock(side_effect=self.section)
        e=json.loads(sr._text(sr.staged_request(self.payload,send,self.root)))
        self.assertEqual(send.call_count,10)
        self.assertEqual(e['stories'],self.e['stories'])
        self.assertFalse(sr.reserve_corrective_attempt(self.root,DATE,self.policy))
        for n,v in original.items():self.assertEqual((self.root/n).read_bytes(),v)
        self.assertFalse((self.root/'approved.json').exists())
        self.assertFalse((self.root/'audit.json').exists())

    def test_context_change_cannot_force_new_discovery_after_reservation(self):
        self.prepare();self.assertTrue(sr.reserve_corrective_attempt(self.root,DATE,self.policy))
        send=Mock(side_effect=self.section)
        with self.assertRaises(RuntimeError):sr.staged_request({**self.payload,'input':'Changed date/context'},send,self.root)
        send.assert_not_called()

    def test_retained_source_loss_cannot_generate_replacement(self):
        self.prepare();self.assertTrue(sr.reserve_corrective_attempt(self.root,DATE,self.policy))
        (self.root/sr.ENGINE/'sources.json').unlink()
        send=Mock(side_effect=self.section)
        with self.assertRaises(RuntimeError):sr.staged_request(self.payload,send,self.root)
        send.assert_not_called()

    def test_existing_valid_narration_reused_without_new_generation(self):
        send=Mock(side_effect=[response('Observed evidence',web=True),selection_response(self.e['sources']),reporting_response(self.report),response(self.e['podcast'])])
        first=sr.staged_request(self.payload,send,self.root)
        repeat=Mock(side_effect=AssertionError('No new calls'))
        self.assertEqual(sr.staged_request(self.payload,repeat,self.root),first)
        repeat.assert_not_called()


if __name__=='__main__':unittest.main()
