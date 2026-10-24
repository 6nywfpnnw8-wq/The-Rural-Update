"""Bounded second BLUF recovery from exact retained Oct. 24 state."""
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_prose as prose
import release_sectioned_narration as sn

def save(path,identity,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'identity':identity,'value':value,'sha256':sn.fingerprint(value),'publication_authorized':False}))

def load(path,identity):
    if not path.exists():return None
    record=json.loads(path.read_text())
    if record.get('identity')!=identity:return None
    if record.get('sha256')!=sn.fingerprint(record.get('value')) or record.get('publication_authorized') is not False:
        raise RuntimeError('corrupt stage')
    return record['value']

class StructuralFollowupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.cache=Path(self.temp.name);self.engine='staged-research-v3'
        self.folder=self.cache/self.engine;self.date='2026-10-24'
        self.identity='oct24-retained';self.report={'edition_date':self.date,'bluf':'Verified retained reporting.'}
        values={'discovery':{'web_search_items':[{'type':'web_search_call','action':{'sources':[{'url':'https://cms.gov/a'}]}}]},
                'sources':{'sources':[{'id':'a'}]},'reporting':{'edition':self.report}}
        for name,value in values.items():save(self.folder/(name+'.json'),self.identity,value)
        self.section_identity=sn.fingerprint({'method':sn.METHOD,'identity':self.identity,'model':'gpt-5-mini',
                                            'reporting':self.report,'plan':sn.SECTION_PLAN})
        self.work=self.folder/sn.METHOD/self.section_identity
        self.work.mkdir(parents=True)
        sn._write_ledger(self.work/'attempts.json',{'identity':self.section_identity,'requests':5,
            'attempts':{'opening-None':2,'bluf-None':3},'publication_authorized':False})
        opening=' '.join(['word']*59+['ending.'])
        save(self.work/'opening-None.json',self.section_identity,{'section':'opening-None','format':prose.FORMAT,
            'result':{'text':opening},'usage':None})
        hashes={name:hashlib.sha256((self.folder/(name+'.json')).read_bytes()).hexdigest() for name in values}
        (self.cache/'narration-structural-resume-used.json').write_text(json.dumps({
            'edition_date':self.date,'identity':self.identity,'section_identity':self.section_identity,
            'section':'bluf-None','maximum_extra_section_requests':1,'failure_run_id':40084542457,
            'publication_authorized':False,'retained_stage_sha256':hashes,
            'section_ledger_sha256_before':'prior-ledger-hash'}))
        (self.cache/'attempts.json').write_text('{"attempts":2}')
        (self.cache/'api-responses.json').write_text(json.dumps({'responses':[{
            'stage':'narration_section','status':'completed','requested_output_limit':4000,
            'run_id':'40102773243'}]}))
        history=[(1,311,40084542457),(2,222,40084542457),(3,298,40102773243)]
        (self.cache/'validation-narration-sections.json').write_text(json.dumps({'sections':[
            {'section':'bluf-None','attempt':n,'word_count':count,'passed':False,
             'rule':'section_word_count','run_id':str(run)} for n,count,run in history]}))
        validation={'passed':False,'rule':'narration_section','path':'/podcast/bluf','run_id':'40102773243'}
        (self.cache/'validation-narration-section.json').write_text(json.dumps(validation))
        (self.cache/'validation-latest.json').write_text(json.dumps(validation))
        self.plan={'schema_version':1,'edition_date':self.date,'engine':self.engine,
            'maximum_additional_generation_attempts':1,'publication_authorized':False,
            'maximum_narration_structural_resumes':2,'maximum_narration_structural_followups':1,
            'maximum_additional_narration_requests':1,'section':'bluf-None',
            'previous_failure_run_id':40084542457,'failure_run_id':40102773243,
            'observed_words':298,'observed_attempt':3,
            'reason':'A single reviewed narration-only continuation'}
    def reserve(self):
        return prose.reserve_structural_followup(self.cache,self.date,self.plan,self.engine,load,lambda _:None)
    def test_exact_followup_preserves_daily_and_section_ledgers_and_pattern(self):
        ledger=self.work/'attempts.json';daily=self.cache/'attempts.json'
        daily_before=daily.read_bytes()
        self.assertTrue(self.reserve());self.assertFalse(self.reserve())
        self.assertEqual(daily.read_bytes(),daily_before)
        extra=prose.recovery_grant(self.cache,self.identity,self.section_identity)
        self.assertEqual(extra,{'bluf-None':2})
        calls=[]
        def respond(payload):
            label=payload['text']['format']['name']
            field=payload['text']['format']['schema']['properties']['text']
            if label=='narration_section' and 'Target 165 words' in payload['instructions']:
                if payload['input'].find('previous_candidate')!=-1:pass
            if 'section bluf' in payload['instructions'].lower():
                self.assertIn('pattern',field)
            else:self.assertNotIn('pattern',field)
            desc=field['description'];low=int(desc.split('of ')[1].split(' to')[0])
            calls.append(payload)
            return {'status':'completed','text':json.dumps({'text':' '.join(['word']*(low-1)+['ending.'])}),'usage':{}}
        output=sn.generate_sections(self.report,'gpt-5-mini',self.folder,self.identity,
                                    Mock(side_effect=respond),lambda raw:raw['text'],load,save)
        state=json.loads(ledger.read_text())
        self.assertEqual(state['attempts']['bluf-None'],4)
        self.assertEqual(state['requests'],14)
        self.assertEqual(len(calls),9)
        self.assertEqual(output['podcast']['bluf'],' '.join(['word']*154+['ending.']))
        self.assertEqual(daily.read_bytes(),daily_before)
    def test_wrong_latest_run_fails_closed(self):
        d=json.loads((self.cache/'api-responses.json').read_text());d['responses'][-1]['run_id']='40086530563'
        (self.cache/'api-responses.json').write_text(json.dumps(d))
        self.assertFalse(self.reserve())
        self.assertFalse((self.cache/'narration-structural-followup-used.json').exists())
    def test_changed_retained_reporting_fails_closed(self):
        p=self.folder/'reporting.json';d=json.loads(p.read_text());d['value']['edition']['bluf']='changed';p.write_text(json.dumps(d))
        self.assertFalse(self.reserve())
        self.assertFalse((self.cache/'narration-structural-followup-used.json').exists())
    def test_daily_attempt_ledger_must_remain_two(self):
        (self.cache/'attempts.json').write_text('{"attempts":1}')
        self.assertFalse(self.reserve())
    def test_audit_or_candidate_approval_blocks(self):
        (self.cache/'audit.json').write_text('{"approved":false}')
        self.assertFalse(self.reserve())

if __name__=='__main__':unittest.main()
