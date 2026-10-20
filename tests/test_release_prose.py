"""Prose representation and precise recovery authorization regression tests."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_sectioned_narration as sn
import release_prose as prose


def save(path,identity,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'identity':identity,'value':value,'sha256':sn.fingerprint(value),'publication_authorized':False}))

def load(path,identity):
    if not path.exists():return None
    d=json.loads(path.read_text())
    if d['identity']!=identity:return None
    if d['sha256']!=sn.fingerprint(d['value']) or d['publication_authorized'] is not False:raise RuntimeError('corrupt cache')
    return d['value']

def response(n):return {'status':'completed','text':json.dumps({'text':' '.join(['Synthetic']*(n-1)+['ending.'])}),'usage':{}}

def extract(raw):
    if raw.get('status')!='completed':raise RuntimeError('incomplete response')
    return raw['text']

class ProseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cache=Path(self.tmp.name);self.folder=self.cache/'staged-research-v3'
        self.report={'edition_date':'2026-10-20','bluf':'Synthetic offline reporting.'}
        self.identity='fixed';self.model='gpt-5-mini'
        self.section_identity=sn.fingerprint({'method':sn.METHOD,'identity':self.identity,'model':self.model,'reporting':self.report,'plan':sn.SECTION_PLAN})
        self.work=self.folder/sn.METHOD/self.section_identity
    def good(self,p):
        field=p['text']['format']['schema']['properties']['text']
        n=field['minLength']//2+prose.TOLERANCE
        self.assertNotIn('words',p['text']['format']['schema']['properties'])
        self.assertNotIn('tools',p);self.assertEqual(p['max_output_tokens'],4000)
        return response(n)
    def generate(self,send):return sn.generate_sections(self.report,self.model,self.folder,self.identity,send,extract,load,save)
    def test_compact_schema_and_passes_exact_target(self):
        send=Mock(side_effect=self.good);value=self.generate(send)
        parts=[v for k,v in value['podcast'].items() if k!='developments']+value['podcast']['developments']
        self.assertEqual(sum(len(p.split()) for p in parts),1855);self.assertEqual(send.call_count,10)
    def test_all_tolerances_stay_within_episode_limits(self):
        self.assertGreaterEqual(sum(c-prose.TOLERANCE for _,_,c in sn.SECTION_PLAN),1700)
        self.assertLessEqual(sum(c+prose.TOLERANCE for _,_,c in sn.SECTION_PLAN),2000)
    def test_large_serialized_output_rejected(self):
        with self.assertRaises(ValueError):prose.validate_prose({'text':'a'*12459+'.'},310)
    def test_short_output_never_padded(self):
        send=Mock(return_value=response(1))
        with self.assertRaises(RuntimeError):self.generate(send)
        self.assertEqual(send.call_count,2)
        with self.assertRaises(RuntimeError):self.generate(send)
        self.assertEqual(send.call_count,2)
    def test_partial_json_never_used(self):
        send=Mock(return_value={'status':'incomplete','text':response(60)['text']})
        with self.assertRaisesRegex(RuntimeError,'incomplete'):self.generate(send)
        self.assertFalse(any(self.folder.rglob('opening-None.json')))
    def test_missing_ending_rejected(self):
        with self.assertRaises(ValueError):prose.validate_prose({'text':' '.join(['word']*60)},60)
    def test_legacy_approved_section_reused_exactly(self):
        text=['Legacy']*59+['ending.']
        save(self.work/'opening-None.json',self.section_identity,{'section':'opening-None','result':{'words':text},'usage':{}})
        send=Mock(side_effect=self.good);value=self.generate(send)
        self.assertEqual(send.call_count,9);self.assertEqual(value['podcast']['opening'],' '.join(text))
    def test_no_paid_calls_after_complete(self):
        original=self.generate(self.good);send=Mock(side_effect=RuntimeError('unexpected'))
        self.assertEqual(self.generate(send),original);send.assert_not_called()
    def test_tamper_or_lost_reporting_fails_closed(self):
        self.generate(self.good)
        p=self.work/'opening-None.json';d=json.loads(p.read_text());d['value']['result']['text']='different';p.write_text(json.dumps(d))
        send=Mock(side_effect=self.good)
        with self.assertRaises(RuntimeError):self.generate(send)
        send.assert_not_called()
    def test_third_section_attempt_not_normally_allowed(self):
        self.work.mkdir(parents=True);p=self.work/'attempts.json'
        sn._write_ledger(p,{'identity':self.section_identity,'requests':3,'attempts':{'developments-0':3},'publication_authorized':False})
        with self.assertRaises(RuntimeError):self.generate(self.good)
    def seed_repair(self):
        values={'discovery':{'web_search_items':[]},'sources':{'sources':[]},'reporting':{'edition':self.report}}
        for n,v in values.items():save(self.folder/(n+'.json'),self.identity,v)
        import hashlib
        marker={'identity':self.identity,'engine':'staged-research-v3','method':sn.METHOD,'publication_authorized':False,
            'cached_files':{n:hashlib.sha256((self.folder/(n+'.json')).read_bytes()).hexdigest() for n in values}}
        (self.cache/'narration-limit-resume-used.json').write_text(json.dumps(marker))
        (self.cache/'narration-capacity-resume-used.json').write_text(json.dumps({'identity':self.identity,'edition_date':'2026-10-20'}))
        (self.cache/'api-responses.json').write_text(json.dumps({'responses':[{'stage':'narration_section','status':'incomplete','incomplete_reason':'max_output_tokens','requested_output_limit':4000,'run_id':'39477476587'}]}))
        (self.cache/'attempts.json').write_text('{"attempts":2}')
        sn._write_ledger(self.work/'attempts.json',{'identity':self.section_identity,'requests':5,'attempts':{'opening-None':1,'bluf-None':2,'developments-0':2},'publication_authorized':False})
        for n,i,c in sn.SECTION_PLAN[:2]:save(self.work/f'{n}-{i}.json',self.section_identity,{'section':f'{n}-{i}','result':{'words':['Legacy']*(c-1)+['ending.']},'usage':{}})
        return {'edition_date':'2026-10-20','maximum_prose_serialization_resumes':1,'prose_format':prose.FORMAT,
            'prose_failure_run_id':39477476587,'prose_replacement_section':'developments-0','maximum_extra_section_requests':1}
    def reserve(self,plan):return prose.reserve(self.cache,plan,'staged-research-v3',load,lambda _:None)
    def test_precise_repair_preserves_spent_attempts_and_overall_cap(self):
        plan=self.seed_repair();before=(self.work/'attempts.json').read_bytes();old=(self.cache/'attempts.json').read_bytes()
        self.assertTrue(self.reserve(plan));self.assertFalse(self.reserve(plan))
        self.assertEqual((self.work/'attempts.json').read_bytes(),before)
        send=Mock(side_effect=self.good);self.generate(send);self.assertEqual(send.call_count,8)
        ledger=json.loads((self.work/'attempts.json').read_text())
        self.assertEqual(ledger['requests'],13);self.assertEqual(ledger['attempts']['developments-0'],3)
        self.assertEqual((self.cache/'attempts.json').read_bytes(),old)
    def test_failed_extra_request_cannot_repeat(self):
        plan=self.seed_repair();self.assertTrue(self.reserve(plan))
        send=Mock(return_value=response(1))
        with self.assertRaises(RuntimeError):self.generate(send)
        self.assertEqual(send.call_count,1)
        with self.assertRaises(RuntimeError):self.generate(send)
        self.assertEqual(send.call_count,1)
    def test_prior_audit_blocks_repair(self):
        plan=self.seed_repair();(self.cache/'audit.json').write_text('{"approved":false}')
        self.assertFalse(self.reserve(plan))
    def test_other_failure_not_authorized(self):
        plan=self.seed_repair();p=self.cache/'api-responses.json';d=json.loads(p.read_text());d['responses'][0]['incomplete_reason']='content_filter';p.write_text(json.dumps(d))
        self.assertFalse(self.reserve(plan))
    def test_wrong_date_not_authorized(self):
        plan=self.seed_repair();plan['edition_date']='2026-10-21';self.assertFalse(self.reserve(plan))
    def test_changed_sources_stop_repair(self):
        plan=self.seed_repair();p=self.folder/'sources.json';p.write_text(p.read_text()+' ')
        with self.assertRaises(RuntimeError):self.reserve(plan)
    def test_no_repair_without_plan(self):
        self.seed_repair();self.assertFalse(self.reserve({'edition_date':'2026-10-20'}))
    def test_grant_cannot_change_other_section_limit(self):
        plan=self.seed_repair();self.assertTrue(self.reserve(plan));p=self.cache/'narration-prose-resume-used.json'
        d=json.loads(p.read_text());d['section']='opening-None';p.write_text(json.dumps(d))
        with self.assertRaises(RuntimeError):self.generate(self.good)

if __name__=='__main__':unittest.main()
