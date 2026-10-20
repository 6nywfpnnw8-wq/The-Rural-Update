"""Finite paragraph output and cross-format request accounting, offline only."""
import copy,json,re,sys,tempfile,unittest,os
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_paragraph_narration as pn
import release_sectioned_narration as sn
import test_release_sectioned_narration as fx

class ParagraphNarrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.report={'edition_date':'2026-10-20','bluf':'Synthetic factual report.'}
        self.identity='context';self.model='gpt-5-mini'
        self.section_id=sn.fingerprint({'method':sn.METHOD,'identity':self.identity,'model':self.model,'reporting':self.report,'plan':sn.SECTION_PLAN})
        self.legacy=self.root/sn.METHOD/self.section_id
        self.current=self.root/pn.PLAIN_METHOD/self.section_id
    def good(self,payload):
        self.assertNotIn('tools',payload)
        self.assertEqual(payload['max_output_tokens'],1800)
        self.assertNotIn('pattern',payload['text']['format']['schema']['properties']['text'])
        count=int(re.search(r'Target (\d+) words',payload['instructions']).group(1))
        return {'status':'completed','text':json.dumps({'text':' '.join(['Synthetic']*(count-1)+['ending.'])}),'usage':{}}
    def generate(self,send):
        return pn.generate_paragraph_sections(self.report,self.model,self.root,self.identity,send,fx.extract,fx.load,fx.save)
    def write_legacy(self,attempts):
        self.legacy.mkdir(parents=True,exist_ok=True)
        (self.legacy/'attempts.json').write_text(json.dumps({'identity':self.section_id,'attempts':attempts,'requests':sum(attempts.values()),'publication_authorized':False}))
    def test_plain_string_sections_finish_at_original_target(self):
        send=Mock(side_effect=self.good);before=copy.deepcopy(self.report);result=self.generate(send)
        texts=[v for k,v in result['podcast'].items() if k!='developments']+result['podcast']['developments']
        self.assertEqual(sum(len(s.split()) for s in texts),1855)
        self.assertEqual(self.report,before);self.assertEqual(send.call_count,10)
        self.assertFalse((self.root/'approved.json').exists())
    def test_cached_repeat_uses_no_network(self):
        first=self.generate(self.good);send=Mock(side_effect=AssertionError('no request'))
        self.assertEqual(first,self.generate(send));send.assert_not_called()
    def test_reuses_accepted_legacy_without_resetting_its_ledger(self):
        self.write_legacy({'opening-None':1,'bluf-None':2,'developments-0':2})
        before=(self.legacy/'attempts.json').read_bytes()
        for name,count in [('opening-None',60),('bluf-None',165)]:
            fx.save(self.legacy/(name+'.json'),self.section_id,{'section':name,'result':json.loads(fx.response(count)['text']),'usage':{}})
        send=Mock(side_effect=self.good);self.generate(send)
        self.assertEqual(send.call_count,8)
        self.assertEqual((self.legacy/'attempts.json').read_bytes(),before)
        self.assertEqual(json.loads((self.current/'attempts.json').read_text())['requests'],8)
    def test_both_format_counts_share_twenty_request_ceiling(self):
        attempts={f'{n}-{i}':2 for n,i,_ in sn.SECTION_PLAN};attempts['closing-None']=1
        self.write_legacy(attempts);send=Mock(side_effect=self.good)
        with self.assertRaisesRegex(RuntimeError,'Combined narration request budget'):self.generate(send)
        self.assertEqual(send.call_count,1)
        self.assertEqual(json.loads((self.legacy/'attempts.json').read_text())['requests'],19)
    def test_failed_plain_section_has_only_two_attempts(self):
        send=Mock(return_value={'status':'completed','text':json.dumps({'text':'Too short.'})})
        with self.assertRaises(RuntimeError):self.generate(send)
        with self.assertRaises(RuntimeError):self.generate(send)
        self.assertEqual(send.call_count,2)
    def test_revision_gets_true_word_count_and_previous_prose(self):
        calls=[]
        def send(p):
            calls.append(p)
            if len(calls)==1:return {'status':'completed','text':json.dumps({'text':'Too short.'})}
            return self.good(p)
        self.generate(send)
        data=json.loads(calls[1]['input'])['previous_attempt_for_revision']
        self.assertEqual(data['actual_words'],2);self.assertEqual(data['text'],'Too short.')
    def test_incomplete_reply_is_never_partially_accepted(self):
        send=Mock(return_value={'status':'incomplete','text':json.dumps({'text':'Synthetic ' *59+'ending.'})})
        with self.assertRaises(RuntimeError):self.generate(send)
        self.assertEqual(send.call_count,1)
        self.assertFalse((self.current/'opening-None.json').exists())
    def test_auth_or_network_error_not_locally_retried(self):
        send=Mock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError):self.generate(send)
        self.assertEqual(send.call_count,1)
    def test_word_range_is_not_waived(self):
        with self.assertRaises(ValueError):pn.paragraph({'text':'Synthetic '*72+'ending.'},'opening')
    def test_missing_final_sentence_stays_blocked(self):
        with self.assertRaises(ValueError):pn.paragraph({'text':' '.join(['Synthetic']*60)},'opening')
    def test_urls_and_markup_blocked(self):
        for token in ('https://example.test','<script>','TODO'):
            with self.assertRaises(ValueError):pn.paragraph({'text':'Synthetic '*58+token+' ending.'},'opening')
    def test_tampered_legacy_section_not_used(self):
        self.write_legacy({'opening-None':1})
        fx.save(self.legacy/'opening-None.json',self.section_id,{'section':'opening-None','result':json.loads(fx.response(60)['text'])})
        d=json.loads((self.legacy/'opening-None.json').read_text());d['value']['result']['words'][0]='Changed'
        (self.legacy/'opening-None.json').write_text(json.dumps(d));send=Mock(side_effect=self.good)
        with self.assertRaises(RuntimeError):self.generate(send)
        send.assert_not_called()
    def test_production_route_selects_plain_prose(self):
        with patch.dict(os.environ,{'RURAL_UPDATE_PARAGRAPH_NARRATION':'true'}):
            result=sn.generate_sections(self.report,self.model,self.root,self.identity,self.good,fx.extract,fx.load,fx.save)
        self.assertEqual(result['method'],pn.PLAIN_METHOD)
    def test_plain_section_bounds_equal_existing_release_bounds(self):
        from release_narration import WORD_BOUNDS
        self.assertEqual(pn.BOUNDS,WORD_BOUNDS)

class ParagraphFormatReservationTests(unittest.TestCase):
    def setUp(self):
        fixture=fx.NarrationReservationTests(methodName='test_single_reviewed_resume_without_reset')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.root=fixture.root;self.plan=fixture.plan;self.engine=fixture.engine;self.validator=fixture.validator
        self.assertTrue(fixture.reserve())
        (self.root/'narration-capacity-resume-used.json').write_text('{"publication_authorized":false}')
        self.plan.update(maximum_paragraph_format_resumes=1,paragraph_request_ceiling=20,paragraph_generation_method=pn.PLAIN_METHOD)
        self.last={'stage':'narration_section','status':'incomplete','incomplete_reason':'max_output_tokens','requested_output_limit':4000,'reasoning_tokens':0,'visible_characters':12459}
        self.metadata=self.root/'api-responses.json';self.metadata.write_text(json.dumps({'responses':[self.last]}))
        self.ledger=self.root/self.engine/sn.METHOD/'test'/'attempts.json';self.ledger.parent.mkdir(parents=True)
        self.ledger.write_text(json.dumps({'identity':'test','requests':5,'attempts':{'opening-None':1,'bluf-None':2,'developments-0':2},'publication_authorized':False}))
    def reserve(self):return pn.reserve_plain_resume(self.root,self.plan,self.engine,fx.load,self.validator)
    def test_single_migration_preserves_all_existing_counts(self):
        original=self.ledger.read_bytes();self.assertTrue(self.reserve());self.assertFalse(self.reserve())
        self.assertEqual(self.ledger.read_bytes(),original)
        self.assertIs(json.loads((self.root/'paragraph-format-resume-used.json').read_text())['publication_authorized'],False)
    def test_without_reviewed_plan_not_allowed(self):
        self.plan.pop('maximum_paragraph_format_resumes');self.assertFalse(self.reserve())
    def test_cannot_raise_global_ceiling(self):
        self.plan['paragraph_request_ceiling']=100
        with self.assertRaises(RuntimeError):self.reserve()
    def test_other_error_cannot_use_format_migration(self):
        self.last['incomplete_reason']='content_filter';self.metadata.write_text(json.dumps({'responses':[self.last]}));self.assertFalse(self.reserve())
    def test_an_audit_cannot_be_reopened(self):
        (self.root/'audit.json').write_text('{"approved":false}');self.assertFalse(self.reserve())
    def test_retained_report_must_match(self):
        (self.root/self.engine/'reporting.json').write_text('{}')
        with self.assertRaises(RuntimeError):self.reserve()

if __name__=='__main__':unittest.main()
