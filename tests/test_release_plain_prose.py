"""Offline tests. No live API calls, secret access or publication."""
import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_prose as prose
import release_prose_pattern as pattern
import release_sectioned_narration as sn
from test_release_prose import save,load,response,extract

class PlainProseTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.cache=Path(t.name)/'2026-10-20';self.cache.mkdir()
        self.engine='staged-research-v3';self.folder=self.cache/self.engine
        self.report={'edition_date':'2026-10-20','bluf':'Synthetic report for offline checks.'}
        self.identity='fixed';self.model='gpt-5-mini'
        self.sid=sn.fingerprint({'method':sn.METHOD,'identity':self.identity,'model':self.model,
            'reporting':self.report,'plan':sn.SECTION_PLAN})
        self.work=self.folder/sn.METHOD/self.sid
    def good(self,p):
        field=p['text']['format']['schema']['properties']['text']
        self.assertNotIn('pattern',field)
        self.assertNotIn('tools',p)
        self.assertEqual(p['max_output_tokens'],4000)
        return response(field['minLength']//2+prose.TOLERANCE)
    def generate(self,send):
        return prose.generate(self.report,self.model,self.folder,self.identity,send,extract,load,save)
    def seed(self):
        values={'discovery':{'web_search_items':[{'type':'web_search_call'}]},
            'sources':{'sources':[]},'reporting':{'edition':self.report}}
        for n,v in values.items():save(self.folder/(n+'.json'),self.identity,v)
        hashes={n:hashlib.sha256((self.folder/(n+'.json')).read_bytes()).hexdigest() for n in values}
        (self.cache/'narration-limit-resume-used.json').write_text(json.dumps({
            'identity':self.identity,'engine':self.engine,'method':sn.METHOD,
            'publication_authorized':False,'cached_files':hashes}))
        (self.cache/'narration-prose-resume-used.json').write_text(json.dumps({
            'edition_date':'2026-10-20','identity':self.identity,'section_identity':self.sid,
            'publication_authorized':False,'format':prose.FORMAT,
            'section':'developments-0','maximum_extra_section_requests':1}))
        (self.cache/pattern.MARKER).write_text(json.dumps({
            'edition_date':'2026-10-20','identity':self.identity,'section_identity':self.sid,
            'publication_authorized':False,'section':'developments-0',
            'maximum_extra_section_requests':2}))
        (self.cache/'api-responses.json').write_text(json.dumps({'responses':[{
            'run_id':str(pattern.PLAIN_FAILURE_RUN),'stage':'narration_section',
            'status':'incomplete','incomplete_reason':'max_output_tokens',
            'requested_output_limit':4000,'input_tokens':0,'output_tokens':0,'visible_characters':0}]}))
        (self.cache/'attempts.json').write_text('{"attempts":2}')
        sn._write_ledger(self.work/'attempts.json',{'identity':self.sid,'requests':7,
            'attempts':{'opening-None':1,'bluf-None':2,'developments-0':4},'publication_authorized':False})
        for n,i,c in sn.SECTION_PLAN[:2]:
            save(self.work/f'{n}-{i}.json',self.sid,{'section':f'{n}-{i}',
                'result':{'words':['Legacy']*(c-1)+['ending.']},'usage':{}})
        return {'edition_date':'2026-10-20','maximum_plain_prose_resumes':1,
            'plain_prose_failure_run_id':pattern.PLAIN_FAILURE_RUN,
            'plain_prose_maximum_extra_section_requests':3}
    def reserve(self,p):
        return pattern.reserve_plain(self.cache,p,self.engine,load,lambda _:None)
    def test_generation_removes_only_constraint_not_local_requirements(self):
        schema=pattern.generation_schema(310)
        self.assertNotIn('pattern',schema['properties']['text'])
        self.assertIn('pattern',prose.prose_schema(310)['properties']['text'])
        for text in ['Short.', ' '.join(['word']*310), ' '.join(['word']*309)+ ' https://example.com.']:
            with self.assertRaises(ValueError):prose.validate_prose({'text':text},310)
    def test_successful_complete_sections_are_reused(self):
        calls=Mock(side_effect=self.good);v=self.generate(calls)
        self.assertEqual(calls.call_count,10)
        self.assertEqual(sum(len(x.split()) for k,vv in v['podcast'].items() for x in (vv if isinstance(vv,list) else [vv])),1855)
        later=Mock(side_effect=RuntimeError('must not call'))
        self.assertEqual(self.generate(later),v);later.assert_not_called()
    def test_revision_receives_actual_count_and_unapproved_candidate(self):
        calls=[]
        def send(p):
            calls.append(p)
            return response(20) if len(calls)==1 else self.good(p)
        self.generate(send)
        self.assertIn('observed 20 words',calls[1]['instructions'])
        data=json.loads(calls[1]['input'])
        self.assertEqual(len(data['previous_candidate'].split()),20)
        self.assertEqual(data['reporting'],self.report)
        self.assertEqual(len(calls),11)
    def test_exact_recovery_does_not_reset_either_ledger(self):
        plan=self.seed();ledger=self.work/'attempts.json';old=ledger.read_bytes()
        research=(self.cache/'attempts.json').read_bytes()
        self.assertTrue(self.reserve(plan));self.assertFalse(self.reserve(plan))
        self.assertEqual(ledger.read_bytes(),old)
        calls=Mock(side_effect=self.good);self.generate(calls)
        self.assertEqual(calls.call_count,8)
        state=json.loads(ledger.read_text())
        self.assertEqual(state['attempts']['developments-0'],5)
        self.assertEqual(state['requests'],15)
        self.assertEqual((self.cache/'attempts.json').read_bytes(),research)
    def test_failed_extra_request_stops_and_cannot_loop(self):
        p=self.seed();self.assertTrue(self.reserve(p));calls=Mock(return_value=response(1))
        with self.assertRaises(RuntimeError):self.generate(calls)
        with self.assertRaises(RuntimeError):self.generate(calls)
        self.assertEqual(calls.call_count,1)
        self.assertFalse(self.reserve(p))
    def test_no_automatic_extra_allowance(self):
        self.seed();self.assertFalse(self.reserve({'edition_date':'2026-10-20'}))
        calls=Mock(side_effect=self.good)
        with self.assertRaises(RuntimeError):self.generate(calls)
        calls.assert_not_called()
    def test_changed_source_binding_blocks_recovery(self):
        p=self.seed();f=self.folder/'sources.json';f.write_text(f.read_text()+' ')
        with self.assertRaises(RuntimeError):self.reserve(p)
    def test_audit_rejection_is_not_reopened(self):
        p=self.seed();(self.cache/'audit.json').write_text('{"approved":false}')
        self.assertFalse(self.reserve(p))
    def test_nonzero_output_or_other_failure_not_eligible(self):
        p=self.seed();f=self.cache/'api-responses.json';d=json.loads(f.read_text())
        d['responses'][0]['output_tokens']=4000;f.write_text(json.dumps(d))
        self.assertFalse(self.reserve(p))
        d['responses'][0]['output_tokens']=0;d['responses'][0]['incomplete_reason']='content_filter';f.write_text(json.dumps(d))
        self.assertFalse(self.reserve(p))
    def test_wrong_date_is_not_eligible(self):
        p=self.seed();p['edition_date']='2026-10-21'
        with self.assertRaises(RuntimeError):self.reserve(p)
    def test_completed_section_cannot_be_replaced(self):
        p=self.seed();save(self.work/'developments-0.json',self.sid,{'section':'developments-0'})
        self.assertFalse(self.reserve(p))
    def test_grant_cannot_change_aggregate_limit(self):
        p=self.seed();self.assertTrue(self.reserve(p));f=self.cache/pattern.PLAIN_MARKER
        d=json.loads(f.read_text());d['maximum_total_section_requests']=21;f.write_text(json.dumps(d))
        with self.assertRaises(RuntimeError):self.generate(self.good)

if __name__=='__main__':unittest.main()
