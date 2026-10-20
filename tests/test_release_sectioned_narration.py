"""Offline bounds, cache, and review-gate tests for narration continuation."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import release_sectioned_narration as sn
from release_prose import TOLERANCE


def save(path,identity,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'identity':identity,'value':value,'sha256':sn.fingerprint(value),
                                'publication_authorized':False}))


def load(path,identity):
    if not path.exists():return None
    d=json.loads(path.read_text())
    if d['identity']!=identity:return None
    if d['sha256']!=sn.fingerprint(d['value']) or d['publication_authorized'] is not False:
        raise RuntimeError('corrupt cache')
    return d['value']


def response(count):
    return {'status':'completed','text':json.dumps({'words':['Synthetic']*(count-1)+['ending.']}),'usage':{}}


def extract(raw):
    if raw.get('status')!='completed':raise RuntimeError('incomplete response')
    return raw['text']


class SectionedNarrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.report={'edition_date':'2026-10-20','bluf':'Synthetic offline reporting.'}
        self.model='gpt-5-mini';self.identity='synthetic-context'

    def good(self,payload):
        self.assertNotIn('tools',payload)
        self.assertEqual(payload['max_output_tokens'],4000)
        self.assertEqual(payload['reasoning']['effort'],'minimal')
        field=payload['text']['format']['schema']['properties']['text']
        n=field['minLength']//2+TOLERANCE
        return {'status':'completed','text':json.dumps({'text':' '.join(['Synthetic']*(n-1)+['ending.'])}),'usage':{}}

    def generate(self,send):
        return sn.generate_sections(self.report,self.model,self.root,self.identity,send,extract,load,save)

    def test_ten_short_sections_exact_total_and_no_new_reporting(self):
        original=copy.deepcopy(self.report);send=Mock(side_effect=self.good)
        result=self.generate(send)
        strings=[v for k,v in result['podcast'].items() if k!='developments']+result['podcast']['developments']
        self.assertEqual(sum(len(x.split()) for x in strings),1855)
        self.assertEqual(send.call_count,10);self.assertEqual(self.report,original)
        self.assertEqual(len(result['podcast']['developments']),3)
        self.assertFalse((self.root/'approved.json').exists())

    def test_successful_repeat_has_no_paid_calls(self):
        first=self.generate(self.good);send=Mock(side_effect=RuntimeError('No paid calls'))
        self.assertEqual(self.generate(send),first);send.assert_not_called()

    def test_word_array_schema_bounds_are_equal(self):
        field=sn.word_schema(310)['properties']['words']
        self.assertEqual(field['minItems'],field['maxItems']);self.assertEqual(field['maxItems'],310)

    def test_short_section_not_padded_or_approved(self):
        send=Mock(return_value=response(1))
        with self.assertRaisesRegex(RuntimeError,'bounded structural'):self.generate(send)
        self.assertEqual(send.call_count,2)
        with self.assertRaises(RuntimeError):self.generate(send)
        self.assertEqual(send.call_count,2)

    def test_two_calls_per_section_maximum_twenty(self):
        calls=[]
        def send(payload):
            calls.append(payload)
            return response(1) if len(calls)%2 else self.good(payload)
        result=self.generate(send)
        self.assertEqual(len(calls),20);self.assertIn('closing',result['podcast'])

    def test_partial_response_is_never_parsed_or_accepted(self):
        send=Mock(return_value={'status':'incomplete','text':response(60)['text']})
        with self.assertRaisesRegex(RuntimeError,'incomplete'):self.generate(send)
        self.assertEqual(send.call_count,1)
        self.assertFalse(any(self.root.rglob('opening-None.json')))

    def test_transport_failure_is_not_retried_inside_section(self):
        send=Mock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError):self.generate(send)
        self.assertEqual(send.call_count,1)

    def test_completed_sections_reused_after_later_failure(self):
        calls=[]
        def send(p):
            calls.append(p)
            if len(calls)==4:raise TimeoutError()
            return self.good(p)
        with self.assertRaises(TimeoutError):self.generate(send)
        resumed=Mock(side_effect=self.good);self.generate(resumed)
        self.assertEqual(resumed.call_count,7)

    def test_cache_tampering_stops_before_network(self):
        self.generate(self.good)
        p=next(self.root.rglob('opening-None.json'))
        d=json.loads(p.read_text());d['value']['result']['text']='Tampered';p.write_text(json.dumps(d))
        send=Mock(side_effect=self.good)
        with self.assertRaises(RuntimeError):self.generate(send)
        send.assert_not_called()

    def test_ledger_tampering_is_not_reset(self):
        self.generate(self.good);p=next(self.root.rglob('attempts.json'))
        d=json.loads(p.read_text());d['requests']=0;p.write_text(json.dumps(d))
        send=Mock(side_effect=self.good)
        with self.assertRaises(RuntimeError):self.generate(send)
        send.assert_not_called()

    def test_embedded_whitespace_cannot_fake_word_count(self):
        with self.assertRaises(ValueError):sn.validate_words({'words':['two words','end.']},2)

    def test_longer_section_is_not_truncated(self):
        with self.assertRaises(ValueError):sn.validate_words(json.loads(response(61)['text']),60)

    def test_unfinished_sentence_is_rejected(self):
        with self.assertRaises(ValueError):sn.validate_words({'words':['unfinished']},1)

    def test_url_or_markup_not_spoken(self):
        for word in ('https://example.test.','<script>.','TODO.'):
            with self.subTest(word=word):
                with self.assertRaises(ValueError):sn.validate_words({'words':[word]},1)

    def test_closing_uses_requested_edition_not_wall_clock(self):
        send=Mock(side_effect=self.good);self.generate(send)
        self.assertIn('2026-10-20',send.call_args_list[-1].args[0]['instructions'])


class NarrationReservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.engine='staged-research-v3';self.identity='fixed-identity'
        self.plan={'edition_date':'2026-10-20','maximum_narration_limit_resumes':1,
                   'narration_recovery_method':sn.METHOD,'previous_narration_output_limit':8000}
        for name,value in [('discovery',{'web_search_items':[{'type':'web_search_call'}]}),
                           ('sources',{'sources':[]}),('reporting',{'edition':{'edition_date':'2026-10-20'}})]:
            save(self.root/self.engine/(name+'.json'),self.identity,value)
        self.metadata={'responses':[{'stage':'narration','status':'incomplete','incomplete_reason':'max_output_tokens','requested_output_limit':8000}]}
        (self.root/'api-responses.json').write_text(json.dumps(self.metadata))
        (self.root/'attempts.json').write_text('{"attempts":2}')
        (self.root/'corrective-generation-used.json').write_text('{"used":true}')
        self.validator=Mock()

    def reserve(self):return sn.reserve_narration_resume(self.root,self.plan,self.engine,load,self.validator)

    def test_single_reviewed_resume_without_reset(self):
        before={n:(self.root/n).read_bytes() for n in ('attempts.json','corrective-generation-used.json')}
        self.assertTrue(self.reserve());self.assertFalse(self.reserve())
        for name,data in before.items():self.assertEqual((self.root/name).read_bytes(),data)
        marker=json.loads((self.root/'narration-limit-resume-used.json').read_text())
        self.assertIs(marker['publication_authorized'],False)
        self.assertTrue(sn.assert_retained_stages(self.root,self.engine,self.identity))
        self.validator.assert_called_once()

    def test_prior_stage_cannot_be_missing(self):
        (self.root/self.engine/'reporting.json').unlink();self.assertFalse(self.reserve())

    def test_different_error_does_not_qualify(self):
        self.metadata['responses'][0]['incomplete_reason']='content_filter'
        (self.root/'api-responses.json').write_text(json.dumps(self.metadata));self.assertFalse(self.reserve())

    def test_other_stage_does_not_qualify(self):
        self.metadata['responses'][0]['stage']='reporting'
        (self.root/'api-responses.json').write_text(json.dumps(self.metadata));self.assertFalse(self.reserve())

    def test_complete_narration_cannot_be_replaced(self):
        (self.root/self.engine/'narration.json').write_text('{}');self.assertFalse(self.reserve())

    def test_rejected_audit_cannot_be_reopened(self):
        (self.root/'audit.json').write_text('{"approved":false}');self.assertFalse(self.reserve())

    def test_wrong_date_stays_blocked(self):
        self.plan['edition_date']='2026-10-21';self.assertFalse(self.reserve())

    def test_missing_authorization_stays_blocked(self):
        self.plan.pop('maximum_narration_limit_resumes');self.assertFalse(self.reserve())

    def test_wrong_recovery_method_rejected(self):
        self.plan['narration_recovery_method']='unlimited'
        with self.assertRaises(RuntimeError):self.reserve()

    def test_report_validation_failure_blocks_reservation(self):
        self.validator.side_effect=ValueError('Unresolved source')
        with self.assertRaises(ValueError):self.reserve()
        self.assertFalse((self.root/'narration-limit-resume-used.json').exists())

    def test_changed_identity_cannot_restart_discovery(self):
        self.assertTrue(self.reserve())
        with self.assertRaises(RuntimeError):sn.assert_retained_stages(self.root,self.engine,'different')

    def test_changed_source_bytes_cannot_restart_reporting(self):
        self.assertTrue(self.reserve())
        p=self.root/self.engine/'sources.json';p.write_text(p.read_text()+' ')
        with self.assertRaises(RuntimeError):sn.assert_retained_stages(self.root,self.engine,self.identity)

    def test_missing_source_bytes_fail_closed(self):
        self.assertTrue(self.reserve());(self.root/self.engine/'sources.json').unlink()
        with self.assertRaises(RuntimeError):sn.assert_retained_stages(self.root,self.engine,self.identity)


if __name__=='__main__':unittest.main()
