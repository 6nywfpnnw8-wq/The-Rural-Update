"""Explicit editorial correction must never become a validation bypass."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from release_core import write_json,read_json
from release_editorial import fingerprint
from release_claim_correction import take_claim_correction
from test_release import fixture,DATE
import release_editorial,release_evidence,release_pipeline as pipeline
from evidence_fixture import fake_source
from test_release_resume_integration import audit_response

class ClaimCorrectionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.cache=self.root/'cache';self.cache.mkdir()
        self.plans=self.root/'claim-review';self.plans.mkdir()
        self.original=fixture();self.sha=fingerprint(self.original)
        self.corrected=copy.deepcopy(self.original);self.corrected['bluf']='State implementation remains unverified; assess only conditional effects.'
        self.audit={'approved':False,'issues':['State implementation is not supported by the cited source.']}
        self.plan={'schema_version':1,'edition_date':DATE,'maximum_fresh_audits':1,
                   'additional_generation_calls':0,'publication_authorized':False,
                   'rejected_run_id':'123','base_stage':'resumed-content',
                   'base_candidate_sha256':self.sha,'rejected_audit_sha256':fingerprint(self.audit),
                   'candidate_sha256':fingerprint(self.corrected),'patches':[
                     {'path':['bluf'],'expected':self.original['bluf'],'replacement':self.corrected['bluf'],
                      'reason':'Qualify unsupported state-specific implications.','source_ids':['s1']}]}
        self.path=self.plans/(DATE+'.json');self.save()
        self.snapshot=self.cache/'candidates'/('resumed-content-'+self.sha[:16]+'.json')
        write_json(self.snapshot,{'schema_version':1,'edition_date':DATE,'stage':'resumed-content',
                   'redacted':False,'publication_authorized':False,'candidate':self.original,'candidate_sha256':self.sha})
        write_json(self.cache/'audit.json',self.audit)
        write_json(self.cache/'validation-evidence-audit.json',{'edition_date':DATE,'run_id':'123',
                   'stage':'evidence-audit','passed':False})
        write_json(self.cache/'source-evidence.json',{'candidate_sha256':self.sha,'complete':True})
        write_json(self.cache/'attempts.json',{'attempts':2})
        write_json(self.cache/'editorial-recovery-attempt.json',{'spent':True})
    def save(self):write_json(self.path,self.plan)
    def invoke(self):return take_claim_correction(self.cache,DATE,self.plans)
    def test_exact_correction_without_approval_or_budget_reset(self):
        counters=[(p,p.read_bytes()) for p in (self.cache/'attempts.json',self.cache/'editorial-recovery-attempt.json')]
        edition,urls=self.invoke();self.assertEqual(edition,self.corrected);self.assertEqual(urls,set())
        for p,b in counters:self.assertEqual(p.read_bytes(),b)
        self.assertFalse((self.cache/'approved.json').exists());self.assertEqual(read_json(self.cache/'audit.json'),self.audit)
        self.assertEqual(read_json(self.cache/'rejected-audits/123/audit.json'),self.audit)
    def test_second_correction_cannot_loop(self):
        self.invoke()
        with self.assertRaises(RuntimeError):self.invoke()
    def test_different_date_not_applied(self):self.assertIsNone(take_claim_correction(self.cache,'2026-10-12',self.plans))
    def test_absent_plan_does_nothing(self):self.path.unlink();self.assertIsNone(self.invoke())
    def test_forged_publication_approval_rejected(self):
        self.plan['publication_authorized']=True;self.save()
        with self.assertRaises(ValueError):self.invoke()
    def test_extra_generation_rejected(self):
        self.plan['additional_generation_calls']=1;self.save()
        with self.assertRaises(ValueError):self.invoke()
    def test_more_than_one_audit_rejected(self):
        self.plan['maximum_fresh_audits']=2;self.save()
        with self.assertRaises(ValueError):self.invoke()
    def test_changed_rejected_verdict_rejected(self):
        write_json(self.cache/'audit.json',{'approved':False,'issues':['Different rejection']})
        with self.assertRaises(ValueError):self.invoke()
    def test_successful_verdict_not_reopened(self):
        write_json(self.cache/'audit.json',{'approved':True,'issues':[]})
        with self.assertRaises(ValueError):self.invoke()
    def test_changed_candidate_rejected(self):
        v=read_json(self.snapshot);v['candidate']['title']='Tampered';write_json(self.snapshot,v)
        with self.assertRaises(ValueError):self.invoke()
    def test_changed_expected_field_rejected(self):
        self.plan['patches'][0]['expected']='Wrong';self.save()
        with self.assertRaises(ValueError):self.invoke()
    def test_changed_corrected_hash_rejected(self):
        self.plan['candidate_sha256']='0'*64;self.save()
        with self.assertRaises(ValueError):self.invoke()
    def test_source_record_mutation_rejected(self):
        self.plan['patches'][0]['path']=['sources',0,'url'];self.save()
        with self.assertRaises(ValueError):self.invoke()
    def test_redating_rejected(self):
        self.plan['patches'][0]['path']=['edition_date'];self.save()
        with self.assertRaises(ValueError):self.invoke()
    def test_invented_reference_rejected(self):
        self.plan['patches'][0]['source_ids']=['unknown'];self.save()
        with self.assertRaises(ValueError):self.invoke()
    def test_duplicate_path_rejected(self):
        self.plan['patches'].append(copy.deepcopy(self.plan['patches'][0]));self.save()
        with self.assertRaises(ValueError):self.invoke()
    def test_reservation_does_not_exist_after_bad_plan(self):
        self.plan['patches'][0]['expected']='wrong';self.save()
        with self.assertRaises(ValueError):self.invoke()
        self.assertFalse((self.cache/'claim-correction-used.json').exists())
    def test_full_source_retrieval_and_new_audit_required(self):
        api=Mock(return_value=audit_response(True))
        with patch.object(release_editorial,'REVIEW_ROOT',self.root/'editorial-review'),patch.object(pipeline,'request_api',api),patch.object(release_evidence,'fetch_source',side_effect=fake_source) as fetch:
            result=pipeline.research(DATE,{},self.cache)
        self.assertTrue(result['audit']['approved']);self.assertEqual(result['edition'],self.corrected)
        self.assertEqual(fetch.call_count,len(self.original['sources']));self.assertEqual(api.call_count,1)
        self.assertEqual(api.call_args.args[0]['text']['format']['name'],'editorial_audit')
    def test_new_audit_rejection_stays_blocked(self):
        api=Mock(return_value=audit_response(False))
        with patch.object(release_editorial,'REVIEW_ROOT',self.root/'editorial-review'),patch.object(pipeline,'request_api',api),patch.object(release_evidence,'fetch_source',side_effect=fake_source):
            with self.assertRaisesRegex(RuntimeError,'audit rejected'):pipeline.research(DATE,{},self.cache)
            with self.assertRaises(RuntimeError):pipeline.research(DATE,{},self.cache)
        self.assertEqual(api.call_count,1);self.assertFalse((self.cache/'approved.json').exists())
    def test_missing_source_prevents_audit(self):
        api=Mock()
        with patch.object(release_editorial,'REVIEW_ROOT',self.root/'editorial-review'),patch.object(pipeline,'request_api',api),patch.object(release_evidence,'fetch_source',side_effect=RuntimeError('Unavailable')):
            with self.assertRaises(AssertionError):pipeline.research(DATE,{},self.cache)
        api.assert_not_called();self.assertFalse((self.cache/'approved.json').exists())

    def test_hash_pinned_exact_substitution(self):
        original=self.original['bluf']
        self.plan['patches'][0]['expected']={'sha256':fingerprint(original)}
        self.plan['patches'][0]['replacement']={'replace':original,'with':self.corrected['bluf']}
        self.save()
        self.assertEqual(self.invoke()[0],self.corrected)
    def test_unmatched_substitution_does_not_reserve(self):
        self.plan['patches'][0]['expected']={'sha256':fingerprint(self.original['bluf'])}
        self.plan['patches'][0]['replacement']={'replace':'not present','with':'not authorized'}
        self.save()
        with self.assertRaises(ValueError):self.invoke()
        self.assertFalse((self.cache/'claim-correction-used.json').exists())

if __name__=='__main__':unittest.main()
