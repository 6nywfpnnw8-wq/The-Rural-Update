"""No network or production writes. Rechecking prose cannot approve an edition."""
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from jsonschema import Draft202012Validator
import release_section_recheck as rc
import release_prose as prose
import release_prose_pattern as pattern
import release_sectioned_narration as sn
from release_narration import WORD_BOUNDS,bounded_podcast_schema
from test_release_plain_prose import PlainProseTests
from test_release_prose import load

class SectionRecheckTests(unittest.TestCase):
    def setUp(self):
        self.f=PlainProseTests(methodName='test_exact_recovery_does_not_reset_either_ledger')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        p=self.f.seed();self.assertTrue(self.f.reserve(p))
        ledger=self.f.work/'attempts.json';state=json.loads(ledger.read_text())
        state['attempts']['developments-0']=5;state['requests']=8
        sn._write_ledger(ledger,state)
        self.candidate={'text':' '.join(['testing']*147+['sample']*139+['ending.'])}
        self.assertEqual(len(self.candidate['text']),2156)
        self.assertEqual(len(self.candidate['text'].split()),287)
        with patch.dict('os.environ',{'GITHUB_RUN_ID':rc.FAILURE_RUN}):
            pattern.record_section(self.f.cache,'developments-0',5,self.candidate,ValueError('section_word_count'))
        (self.f.cache/'api-responses.json').write_text(json.dumps({'responses':[{
            'run_id':rc.FAILURE_RUN,'status':'completed','stage':'narration_section',
            'requested_output_limit':4000,'output_tokens':394,'visible_characters':2167}]}))
        self.policy=self.f.cache/'policy';self.policy.mkdir()
        self.plan={'edition_date':'2026-10-20'}
        self.policy_file=self.policy/'2026-10-20-length.json'
        self.policy_file.write_text(json.dumps({'edition_date':'2026-10-20',
            'failure_run_id':int(rc.FAILURE_RUN),'section':'developments-0',
            'maximum_revalidations':1,'additional_generation_requests':0,
            'publication_authorized':False,'observed_words':287,'observed_characters':2156,'observed_attempt':5}))
    def reserve(self):
        with patch.object(rc,'POLICY_ROOT',self.policy):
            return rc.reserve_recheck(self.f.cache,self.plan,self.f.engine if hasattr(self.f,'engine') else 'staged-research-v3',load,lambda _:None)
    def test_exact_retained_words_saved_without_ledger_change(self):
        ledger=self.f.work/'attempts.json';before=ledger.read_bytes()
        old=(self.f.cache/'attempts.json').read_bytes()
        self.assertTrue(self.reserve());self.assertFalse(self.reserve())
        self.assertEqual(ledger.read_bytes(),before)
        self.assertEqual((self.f.cache/'attempts.json').read_bytes(),old)
        saved=load(self.f.work/'developments-0.json',self.f.sid)
        self.assertEqual(saved['result'],self.candidate)
        self.assertFalse((self.f.cache/'approved.json').exists())
        marker=json.loads((self.f.cache/rc.MARKER).read_text())
        self.assertFalse(marker['publication_authorized']);self.assertEqual(marker['additional_generation_requests'],0)
    def test_remaining_generation_never_rewrites_retained_section(self):
        self.assertTrue(self.reserve());calls=Mock(side_effect=self.f.good)
        value=self.f.generate(calls)
        self.assertEqual(calls.call_count,7)
        self.assertEqual(value['podcast']['developments'][0],self.candidate['text'])
        state=json.loads((self.f.work/'attempts.json').read_text())
        self.assertEqual(state['attempts']['developments-0'],5);self.assertEqual(state['requests'],15)
        Draft202012Validator(bounded_podcast_schema()).validate(value['podcast'])
        self.assertFalse((self.f.cache/'approved.json').exists())
    def test_missing_policy_cannot_reuse_rejected_work(self):
        self.policy_file.unlink();self.assertFalse(self.reserve())
    def test_missing_candidate_does_not_generate_replacement(self):
        for p in (self.f.cache/'section-candidates').glob('*.json'):p.unlink()
        with self.assertRaises(RuntimeError):self.reserve()
    def test_rejected_audit_is_not_reopened(self):
        (self.f.cache/'audit.json').write_text('{"approved":false}');self.assertFalse(self.reserve())
    def test_changed_prerequisites_stop_before_recheck(self):
        p=self.f.folder/'sources.json';p.write_text(p.read_text()+' ')
        with self.assertRaises(RuntimeError):self.reserve()
    def test_incomplete_response_not_rechecked(self):
        p=self.f.cache/'api-responses.json';d=json.loads(p.read_text());d['responses'][0]['status']='incomplete';p.write_text(json.dumps(d))
        self.assertFalse(self.reserve())
    def test_other_validation_error_not_rechecked(self):
        p=self.f.cache/'validation-narration-sections.json';d=json.loads(p.read_text());d['sections'][0]['rule']='section_sentence_ending';p.write_text(json.dumps(d))
        self.assertFalse(self.reserve())
    def test_another_date_not_rechecked(self):
        self.plan['edition_date']='2026-10-21';self.assertFalse(self.reserve())
    def test_candidate_hash_not_optional(self):
        p=next((self.f.cache/'section-candidates').glob('*.json'));p.rename(p.with_name('0'*64+'.json'))
        with self.assertRaises(RuntimeError):self.reserve()
    def test_all_section_bound_extremes_preserve_episode_requirement(self):
        for i in (0,1):
            value={'developments':[]}
            for name,(low,high) in WORD_BOUNDS.items():
                n=(low,high)[i];text=' '.join(['word']*(n-1)+['ending.'])
                value[name]=[text]*3 if name=='developments' else text
            Draft202012Validator(bounded_podcast_schema()).validate(value)
            n=sum(len(t.split()) for v in value.values() for t in (v if isinstance(v,list) else [v]))
            self.assertEqual(n,(1705,1995)[i])
    def test_development_ending_markup_and_limits_remain_mandatory(self):
        self.assertEqual(prose.validate_prose(self.candidate,310),self.candidate['text'])
        for n in (284,331):
            with self.assertRaises(ValueError):prose.validate_prose({'text':' '.join(['word']*(n-1)+['ending.'])},310)
        for text in (' '.join(['word']*287),' '.join(['word']*286+['<script>.'])):
            with self.assertRaises(ValueError):prose.validate_prose({'text':text},310)

if __name__=='__main__':unittest.main()
