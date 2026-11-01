"""Incomplete app reviews remain rejected; only a pinned unused final slot resumes."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_app_review as recovery
import release_audit_loop as loop
import release_pipeline as pipeline
import release_evidence as evidence
import release_research as research
from release_core import digest,read_json,write_json
from release_editorial import fingerprint
from test_release import fixture
from test_release_audit_loop import response
from test_release_coverage_plan import plan_for
from evidence_fixture import fake_source

DATE='2026-11-03'


class AppReviewTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.cache=self.root/DATE
        self.folder=self.cache/'editorial-loop-v1';self.folder.mkdir(parents=True)
        self.policy_root=self.root/'policy';self.policy_root.mkdir()
        self.edition=fixture();self.edition.pop('podcast');self.edition['edition_date']=DATE
        for row in self.edition['actions']:row['due_date']=DATE
        for row in self.edition['deadlines']:row['date']='2026-11-05'
        self.corrected=copy.deepcopy(self.edition);self.corrected['bluf']='A complete reviewed summary for independent verification.'
        self.corrected['sources'][0]['published_date']=None
        # Deliberately malformed quotation feedback cannot be promoted to approval.
        self.review={'review_complete':False,'findings':[{'id':'source-date',
            'kind':'unsupported_claim','path':'/title','quote':'Serialized source record, not candidate prose.',
            'source_ids':['s1'],'explanation':'Unverified metadata assertion.',
            'required_change':'Verify the primary source independently.'}]}
        self.request_sha='a'*64
        write_json(self.folder/'original.json',{'edition_date':DATE,'candidate':self.edition,
            'candidate_sha256':fingerprint(self.edition),'retrieved_urls':[], 'publication_authorized':False})
        write_json(self.folder/'initial-result.json',{'payload_sha256':self.request_sha,
            'value_sha256':fingerprint(self.review),'value':self.review,'retrieved_urls':[]})
        write_json(self.folder/'initial-reserved.json',{'payload_sha256':self.request_sha,
            'run_id':'123','publication_authorized':False})
        write_json(self.cache/'attempts.json',{'attempts':1})
        self.docs=[{**fake_source(s['url']),'source_id':s['id']} for s in self.edition['sources']]
        self.evidence_path=self.cache/research.ENGINE/'evidence-coverage-v2/sources.json'
        research._save(self.evidence_path,'b'*64,{'documents':self.docs})
        self.policy={'schema_version':1,'edition_date':DATE,'method':recovery.METHOD,
            'maximum_total_audit_requests':2,'use_existing_slot':'final',
            'additional_research_generation_calls':0,'additional_reporting_generation_calls':0,
            'additional_correction_generation_calls':0,'research_counter_reset':False,
            'podcast_generation_permitted':False,'independent_full_source_review_required':True,
            'publication_authorized':False,'original_research_attempts':1,'failure_run_id':123,
            'base_candidate_sha256':fingerprint(self.edition),
            'initial_review_sha256':fingerprint(self.review),'initial_request_sha256':self.request_sha,
            'coverage_evidence_file_sha256':digest(self.evidence_path.read_bytes()),
            'coverage_evidence_identity':'b'*64,'candidate_sha256':fingerprint(self.corrected),
            'replacements':[{'path':'/bluf','before':self.edition['bluf'],'after':self.corrected['bluf']},
                {'path':'/sources/0/published_date','before':'2026-10-10','after':None}],
            'coverage_plan':plan_for(self.corrected,self.edition['sources'],self.docs)}
        self.save_policy();self.preparer=recovery.prepare
        fetch=patch.object(evidence,'fetch_source',side_effect=fake_source);self.fetch=fetch.start();self.addCleanup(fetch.stop)

    def save_policy(self):write_json(self.policy_root/(DATE+'.json'),self.policy)
    def prepare(self):return self.preparer(self.edition,self.cache,self.policy_root)
    def run_pipeline(self,api):
        with patch.object(recovery,'prepare',side_effect=lambda e,c,p:self.preparer(e,c,self.policy_root)), \
             patch.dict(os.environ,{'RURAL_UPDATE_STRUCTURED_REVIEW':'true'}), \
             patch.object(pipeline,'request_api',api),patch.object(pipeline,'ensure_narration_length') as narration:
            result=pipeline.research(DATE,{},self.cache)
        narration.assert_not_called();return result

    def test_offline_preparation_preserves_originals_and_does_not_approve(self):
        originals={p:p.read_bytes() for p in self.cache.rglob('*.json')}
        first=self.prepare();again=self.prepare()
        self.assertEqual(first,again);self.assertEqual(first[0],self.corrected)
        self.fetch.assert_not_called()
        for p,data in originals.items():self.assertEqual(p.read_bytes(),data)
        self.assertFalse((self.cache/'approved.json').exists())
        self.assertFalse((self.folder/'final-reserved.json').exists())

    def test_full_pipeline_requires_only_final_live_audit_and_reuses_success(self):
        api=Mock(return_value=response({'review_complete':True,'findings':[]}))
        first=self.run_pipeline(api);again=self.run_pipeline(api)
        self.assertEqual(first['edition'],self.corrected);self.assertEqual(first,again)
        self.assertTrue(first['audit']['approved']);self.assertEqual(api.call_count,1)
        payload=api.call_args.args[0]
        self.assertEqual(payload['text']['format']['name'],'editorial_audit_structured')
        self.assertEqual(payload['tool_choice'],'required')
        self.assertIn('Review completion and publication approval are different',payload['input'])
        self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':1})
        self.assertFalse((self.folder/'correction-reserved.json').exists())
        self.assertEqual(first['structured_review']['correction_method'],'reviewed-incomplete-app')

    def test_incomplete_final_review_stays_rejected_without_another_call(self):
        api=Mock(return_value=response({'review_complete':False,'findings':[]}))
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError,'incomplete'):self.run_pipeline(api)
        self.assertEqual(api.call_count,1);self.assertFalse((self.cache/'approved.json').exists())
        self.assertEqual(read_json(self.cache/'validation-structured-review.json')['rule'],'structured_review_incomplete')

    def test_final_blocking_review_cannot_open_correction_or_extra_audit(self):
        report={'review_complete':True,'findings':[{'id':'f1','kind':'unsupported_claim',
            'path':'/bluf','quote':self.corrected['bluf'],'source_ids':['s1'],
            'explanation':'Not verified.','required_change':'Remove the unsupported claim.'}]}
        api=Mock(return_value=response(report))
        with self.assertRaisesRegex(RuntimeError,'final evidence review'):self.run_pipeline(api)
        self.assertFalse((self.cache/'approved.json').exists());self.assertEqual(api.call_count,1)
        self.assertFalse((self.folder/'correction-reserved.json').exists())

    def test_ambiguous_final_submission_is_never_repeated(self):
        api=Mock(side_effect=TimeoutError('transport'))
        with self.assertRaises(TimeoutError):self.run_pipeline(api)
        with self.assertRaisesRegex(RuntimeError,'already reserved'):self.run_pipeline(api)
        self.assertEqual(api.call_count,1)

    def test_final_audit_without_live_retrieval_cannot_approve(self):
        api=Mock(return_value=response({'review_complete':True,'findings':[]},False))
        with self.assertRaisesRegex(RuntimeError,'live web'):self.run_pipeline(api)
        self.assertFalse((self.cache/'approved.json').exists())

    def test_source_retrieval_failure_blocks_before_model_request(self):
        self.fetch.side_effect=TimeoutError('source unavailable');api=Mock()
        with self.assertRaises(Exception):self.run_pipeline(api)
        api.assert_not_called()

    def test_plan_cannot_expand_generation_audits_or_publication(self):
        for key,value in [('maximum_total_audit_requests',3),('additional_research_generation_calls',1),
                ('additional_reporting_generation_calls',1),('additional_correction_generation_calls',1),
                ('publication_authorized',True),('research_counter_reset',True),
                ('podcast_generation_permitted',True),('schema_version',True)]:
            before=self.policy[key];self.policy[key]=value;self.save_policy()
            with self.subTest(key=key),self.assertRaises(ValueError):self.prepare()
            self.policy[key]=before
        self.assertFalse((self.folder/'final-reserved.json').exists())

    def test_attempt_ledger_cannot_be_changed(self):
        write_json(self.cache/'attempts.json',{'attempts':2})
        with self.assertRaisesRegex(ValueError,'research attempts'):self.prepare()

    def test_changed_original_candidate_is_rejected(self):
        self.edition['bluf']='Tampered.'
        with self.assertRaisesRegex(ValueError,'original candidate'):self.prepare()

    def test_changed_raw_review_is_rejected(self):
        p=self.folder/'initial-result.json';raw=read_json(p);raw['value']['findings']=[];write_json(p,raw)
        with self.assertRaisesRegex(ValueError,'review identity'):self.prepare()

    def test_changed_evidence_is_rejected(self):
        p=self.evidence_path;raw=read_json(p);raw['value']['documents'][0]['text']='Altered';write_json(p,raw)
        with self.assertRaisesRegex(ValueError,'original evidence'):self.prepare()

    def test_fabricated_anchor_is_rejected(self):
        self.policy['coverage_plan']['signals']['signal_1']['source_anchors']['s1']='Fabricated supporting passage that was never retrieved.'
        self.save_policy()
        with self.assertRaises(Exception):self.prepare()

    def test_corrected_reference_cannot_escape_coverage(self):
        self.policy['replacements'].append({'path':'/signals/0/source_ids','before':['s1','s2'],'after':['s1','s3']})
        changed=copy.deepcopy(self.corrected);changed['signals'][0]['source_ids']=['s1','s3']
        self.policy['candidate_sha256']=fingerprint(changed);self.save_policy()
        with self.assertRaisesRegex(ValueError,'coverage plan'):self.prepare()

    def test_source_urls_are_not_editable(self):
        self.policy['replacements'].append({'path':'/sources/0/url','before':self.edition['sources'][0]['url'],'after':'https://www.cms.gov/other'})
        self.save_policy()
        with self.assertRaisesRegex(ValueError,'replacement path'):self.prepare()

    def test_spent_final_or_correction_slot_cannot_be_reopened(self):
        for name in ['final-reserved.json','correction-reserved.json']:
            p=self.folder/name;write_json(p,{'publication_authorized':False})
            with self.subTest(name=name),self.assertRaises(ValueError):self.prepare()
            p.unlink()

    def test_symlink_checkpoint_is_rejected(self):
        p=self.folder/'initial-result.json';target=self.root/'saved.json'
        target.write_bytes(p.read_bytes());p.unlink();p.symlink_to(target)
        with self.assertRaisesRegex(ValueError,'Unsafe'):self.prepare()


if __name__=='__main__':unittest.main()
