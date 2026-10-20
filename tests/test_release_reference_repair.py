"""Offline reference correction tests. No source downloads or paid requests."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from release_core import write_json,read_json
from release_editorial import fingerprint,take_reviewed_recovery
from release_reference_repair import take_reference_repair
from test_release import fixture

class ReferenceRepairTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name);self.cache=self.root/'cache';self.cache.mkdir()
        self.plans=self.root/'source-recovery';self.plans.mkdir()
        self.candidate=fixture();self.day=self.candidate['edition_date'];self.sha=fingerprint(self.candidate)
        self.run='99999';source=self.candidate['sources'][0]
        self.snapshot=self.cache/'candidates'/('content-'+self.sha[:16]+'.json')
        write_json(self.snapshot,{'schema_version':1,'edition_date':self.day,'stage':'content',
            'redacted':False,'publication_authorized':False,'candidate':self.candidate,'candidate_sha256':self.sha})
        write_json(self.cache/'validation-content.json',{'edition_date':self.day,'run_id':self.run,
            'passed':True,'snapshot':{'candidate_sha256':self.sha}})
        write_json(self.cache/'validation-exact-source-retrieval.json',{'edition_date':self.day,
            'run_id':self.run,'passed':False,'stage':'exact-source-retrieval'})
        failures=[{'source_id':source['id'],'url':source['url']}]
        write_json(self.cache/'source-evidence.json',{'edition_date':self.day,
            'candidate_sha256':self.sha,'complete':False,'failures':failures})
        self.plan={'schema_version':1,'edition_date':self.day,'failed_run_id':int(self.run),
            'base_candidate_sha256':self.sha,'maximum_audits':1,'additional_generation_calls':0,
            'publication_authorized':False,'expected_failed_sources':failures,
            'source_corrections':[{'source_id':source['id'],'previous_url':source['url'],
                'replacement':{'id':source['id'],'title':'Corrected official reference',
                    'url':'https://www.cms.gov/verified-test-reference','published_date':None}}]}
        self.planpath=self.plans/(self.day+'-exact.json');write_json(self.planpath,self.plan)
        (self.cache/'attempts.json').write_text('{"attempts":2}')
    def run_repair(self):return take_reference_repair(self.cache,self.day,self.plans)
    def test_only_reference_metadata_changes_and_provenance_not_invented(self):
        before=(self.cache/'attempts.json').read_bytes();candidate,urls=self.run_repair()
        self.assertEqual(urls,set());self.assertEqual(candidate['podcast'],self.candidate['podcast'])
        self.assertEqual({k:v for k,v in candidate.items() if k!='sources'},
                         {k:v for k,v in self.candidate.items() if k!='sources'})
        self.assertEqual(candidate['sources'][1:],self.candidate['sources'][1:])
        self.assertEqual((self.cache/'attempts.json').read_bytes(),before)
        record=read_json(self.cache/'editorial-recovery-attempt.json')
        self.assertFalse(record['publication_authorized']);self.assertEqual(record['additional_research_generation_calls'],0)
        self.assertFalse((self.cache/'approved.json').exists())
    def test_repeat_cannot_reserve_another_audit(self):
        self.run_repair()
        with self.assertRaises(RuntimeError):self.run_repair()
    def test_existing_audit_cannot_be_reopened(self):
        write_json(self.cache/'audit.json',{'approved':False})
        with self.assertRaises(RuntimeError):self.run_repair()
    def test_changed_snapshot_rejected(self):
        d=read_json(self.snapshot);d['candidate']['bluf']='Changed claim';write_json(self.snapshot,d)
        with self.assertRaises(ValueError):self.run_repair()
    def test_wrong_run_rejected(self):
        d=read_json(self.cache/'validation-exact-source-retrieval.json');d['run_id']='123';write_json(self.cache/'validation-exact-source-retrieval.json',d)
        with self.assertRaises(ValueError):self.run_repair()
    def test_failure_inventory_cannot_be_guessed(self):
        self.plan['expected_failed_sources'][0]['source_id']='other';write_json(self.planpath,self.plan)
        with self.assertRaises(ValueError):self.run_repair()
    def test_private_replacement_rejected(self):
        self.plan['source_corrections'][0]['replacement']['url']='https://127.0.0.1/secret';write_json(self.planpath,self.plan)
        with self.assertRaises(ValueError):self.run_repair()
    def test_unexpected_original_url_rejected(self):
        self.plan['source_corrections'][0]['previous_url']='https://www.cms.gov/other';write_json(self.planpath,self.plan)
        with self.assertRaises(ValueError):self.run_repair()
    def test_changed_reference_id_rejected(self):
        self.plan['source_corrections'][0]['replacement']['id']='new-id';write_json(self.planpath,self.plan)
        with self.assertRaises(ValueError):self.run_repair()
    def test_no_plan_is_not_an_automatic_repair(self):
        self.planpath.unlink();self.assertIsNone(self.run_repair())
    def test_missing_source_correction_fails(self):
        self.plan['source_corrections']=[];write_json(self.planpath,self.plan)
        with self.assertRaises(ValueError):self.run_repair()
    def test_duplicate_sources_not_allowed(self):
        self.plan['source_corrections'][0]['replacement']['url']=self.candidate['sources'][1]['url'];write_json(self.planpath,self.plan)
        with self.assertRaises(ValueError):self.run_repair()
    def test_publication_or_generation_approval_not_allowed(self):
        for key,value in [('publication_authorized',True),('additional_generation_calls',1),('maximum_audits',2)]:
            d=copy.deepcopy(self.plan);d[key]=value;write_json(self.planpath,d)
            with self.assertRaises(ValueError):self.run_repair()
    def test_existing_reviewed_entry_routes_into_same_audit_path(self):
        with patch('release_editorial.REVIEW_ROOT',self.root/'editorial-review'):
            candidate,urls=take_reviewed_recovery(self.cache,self.day)
        self.assertEqual(candidate['podcast'],self.candidate['podcast']);self.assertEqual(urls,set())
        self.assertFalse((self.cache/'approved.json').exists())

if __name__=='__main__':unittest.main()
