"""Fixed field coverage, exact quotations, and bounded protocol recovery."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_field_review as review
import release_audit_loop as loop
import release_pipeline as pipeline
import release_evidence as evidence
from release_core import write_json,read_json
from release_editorial import fingerprint
from test_release import fixture
from test_release_audit_loop import response
from evidence_fixture import fake_source

DATE='2026-11-05'

def app_fixture():
    e=fixture();e.pop('podcast');e['edition_date']=DATE
    for row in e['actions']:row['due_date']=DATE
    for row in e['deadlines']:row['date']='2026-11-06'
    return e

def clean(candidate):
    return {'review_complete':True,'fields':{p:{'review_complete':True,'findings':[]}
        for p in review.fields(candidate)}}

def defect(quote='Synthetic validation fixture only.'):
    return {'kind':'unsupported_claim','quote':quote,'source_ids':['s1'],
            'explanation':'This premise is unsupported.','required_change':'Qualify the unsupported premise.'}


class FixedFieldTests(unittest.TestCase):
    def setUp(self):self.e=app_fixture();self.raw=clean(self.e)
    def test_all_prose_and_source_fields_are_explicitly_checked(self):
        out=review.compile_review(self.raw,self.e)
        self.assertEqual(out,{'review_complete':True,'findings':[]})
        for key in ('title','url','published_date'):self.assertIn('/sources/0/'+key,self.raw['fields'])
    def test_missing_field_cannot_imply_complete_review(self):
        del self.raw['fields']['/bluf']
        with self.assertRaises(Exception):review.compile_review(self.raw,self.e)
    def test_one_incomplete_field_blocks_even_if_global_flag_is_true(self):
        self.raw['fields']['/bluf']['review_complete']=False
        with self.assertRaisesRegex(RuntimeError,'incomplete'):review.compile_review(self.raw,self.e)
    def test_path_and_id_are_assigned_by_code_and_findings_are_preserved(self):
        f=defect();self.raw['fields']['/bluf']['findings']=[f]
        out=review.compile_review(self.raw,self.e)
        self.assertEqual(out['findings'],[{'id':'field-1','path':'/bluf',**f}])
        self.assertEqual(loop.validate_review(out,self.e,readonly_metadata=True),out['findings'])
    def test_quote_in_another_field_is_not_relocated(self):
        self.raw['fields']['/stories/2/what_changed']['findings']=[defect()]
        with self.assertRaisesRegex(ValueError,'differs from its candidate'):review.compile_review(self.raw,self.e)
    def test_model_cannot_supply_an_alternative_path(self):
        f=defect();f['path']='/title';self.raw['fields']['/bluf']['findings']=[f]
        with self.assertRaises(Exception):review.compile_review(self.raw,self.e)
    def test_null_initial_date_is_a_reviewable_explicit_unknown(self):
        self.e['sources'][0]['published_date']=None
        self.assertEqual(review.fields(self.e)['/sources/0/published_date'],'null')
        self.assertEqual(review.compile_review(clean(self.e),self.e)['findings'],[])
        self.assertIn('An Updated or Last Modified timestamp does not establish the initial',review.POLICY)
    def test_metadata_defect_stays_at_its_actual_read_only_field(self):
        self.raw['fields']['/sources/0/published_date']['findings']=[defect('2026-10-10')]
        out=review.compile_review(self.raw,self.e)
        self.assertEqual(loop.validate_review(out,self.e,readonly_metadata=True),out['findings'])
        self.assertFalse(loop.editable(out['findings'][0]['path']))
    def test_confirmation_is_not_a_substantive_blocking_change(self):
        f=defect();f['required_change']='none';self.raw['fields']['/bluf']['findings']=[f]
        with self.assertRaisesRegex(ValueError,'substantive'):review.compile_review(self.raw,self.e)
    def test_unknown_source_cannot_be_cited(self):
        f=defect();f['source_ids']=['invented'];self.raw['fields']['/bluf']['findings']=[f]
        with self.assertRaises(Exception):review.compile_review(self.raw,self.e)
    def test_ordinary_future_app_uses_fixed_fields_and_live_retrieval(self):
        with tempfile.TemporaryDirectory() as t,patch.object(evidence,'fetch_source',side_effect=fake_source):
            cache=Path(t);docs=evidence.collect_source_evidence(self.e,cache)
            api=Mock(return_value=response(clean(self.e)))
            result=loop.audit_and_correct(self.e,cache,'model',api,pipeline.output_text,docs,set(),None)
        self.assertTrue(result['audit']['approved']);self.assertEqual(api.call_count,1)
        self.assertEqual(api.call_args.args[0]['text']['format']['name'],'editorial_audit_fields')
        self.assertEqual(api.call_args.args[0]['tool_choice'],'required')
    def test_future_app_keeps_one_correction_and_a_fresh_final_audit(self):
        failed=clean(self.e);failed['fields']['/stories/0/why_it_matters']['findings']=[defect('Tests the compiler.')]
        corrected=copy.deepcopy(self.e);corrected['stories'][0]['why_it_matters']='Leadership should test the compiler before relying on its output.'
        plan={'replacements':[{'path':'/stories/0/why_it_matters','before':'Tests the compiler.',
            'after':corrected['stories'][0]['why_it_matters'],'addresses':['field-1']}]}
        api=Mock(side_effect=[response(failed),response(plan,False),response(clean(corrected))])
        with tempfile.TemporaryDirectory() as t,patch.object(evidence,'fetch_source',side_effect=fake_source):
            cache=Path(t);docs=evidence.collect_source_evidence(self.e,cache)
            result=loop.audit_and_correct(self.e,cache,'model',api,pipeline.output_text,docs,set(),None)
        self.assertEqual(result['edition'],corrected);self.assertEqual(api.call_count,3)
    def test_source_metadata_blocker_cannot_trigger_an_automatic_prose_edit(self):
        failed=clean(self.e);failed['fields']['/sources/0/published_date']['findings']=[defect('2026-10-10')]
        api=Mock(return_value=response(failed))
        with tempfile.TemporaryDirectory() as t,patch.object(evidence,'fetch_source',side_effect=fake_source):
            cache=Path(t);docs=evidence.collect_source_evidence(self.e,cache)
            with self.assertRaisesRegex(RuntimeError,'metadata requires'):
                loop.audit_and_correct(self.e,cache,'model',api,pipeline.output_text,docs,set(),None)
            self.assertFalse((cache/'approved.json').exists())
        self.assertEqual(api.call_count,1)


class FieldProtocolRecoveryTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name);self.cache=self.root/DATE;self.prior=self.cache/'editorial-loop-v1'
        self.prior.mkdir(parents=True);self.policy_root=self.root/'policy';self.policy_root.mkdir()
        self.e=app_fixture();self.c=copy.deepcopy(self.e);self.c['bluf']='A complete candidate for independent review.'
        malformed={'review_complete':True,'findings':[{'id':'bad-path',
            'path':'/stories/2/what_changed',**defect(self.c['bluf'])}]}
        sha='c'*64
        write_json(self.prior/'final-result.json',{'value':malformed,'value_sha256':fingerprint(malformed),'payload_sha256':sha})
        write_json(self.prior/'final-reserved.json',{'payload_sha256':sha,'run_id':'789','publication_authorized':False})
        write_json(self.cache/'attempts.json',{'attempts':1})
        self.plan={'schema_version':1,'edition_date':DATE,'method':review.METHOD,
            'maximum_total_audit_requests':3,'maximum_protocol_repair_requests':1,
            'additional_research_generation_calls':0,'additional_reporting_generation_calls':0,
            'additional_correction_generation_calls':0,'research_counter_reset':False,
            'podcast_generation_permitted':False,'publication_authorized':False,'failure_run_id':789,
            'base_candidate_sha256':fingerprint(self.e),'candidate_sha256':fingerprint(self.c),
            'malformed_review_sha256':fingerprint(malformed),'malformed_request_sha256':sha}
        self.save()
        p=patch.object(evidence,'fetch_source',side_effect=fake_source);self.fetch=p.start();self.addCleanup(p.stop)
    def save(self):write_json(self.policy_root/(DATE+'.json'),self.plan)
    def run_review(self,api):
        return review.take_protocol_recovery(self.e,self.c,self.cache,self.policy_root,'model',api,pipeline.output_text,set(),None)
    def test_one_new_format_audit_preserves_old_results_and_research(self):
        before={p:p.read_bytes() for p in self.prior.glob('*.json')}
        api=Mock(return_value=response(clean(self.c)));result=self.run_review(api)
        self.assertTrue(result['audit']['approved']);self.assertEqual(api.call_count,1)
        for p,raw in before.items():self.assertEqual(p.read_bytes(),raw)
        self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':1})
        self.assertFalse((self.prior/'correction-reserved.json').exists())
        self.assertEqual(result['structured_review']['maximum_total_audit_requests'],3)
    def test_incomplete_new_format_is_not_resubmitted(self):
        raw=clean(self.c);raw['fields']['/bluf']['review_complete']=False
        api=Mock(return_value=response(raw))
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError,'incomplete'):self.run_review(api)
        self.assertEqual(api.call_count,1);self.assertFalse((self.cache/'approved.json').exists())
    def test_ambiguous_new_format_is_not_resubmitted(self):
        api=Mock(side_effect=TimeoutError('transport'))
        with self.assertRaises(TimeoutError):self.run_review(api)
        with self.assertRaisesRegex(RuntimeError,'already reserved'):self.run_review(api)
        self.assertEqual(api.call_count,1)
    def test_no_live_retrieval_cannot_approve(self):
        with self.assertRaisesRegex(RuntimeError,'live web'):
            self.run_review(Mock(return_value=response(clean(self.c),False)))
        self.assertFalse((self.cache/'approved.json').exists())
    def test_valid_old_blocking_review_cannot_take_protocol_exception(self):
        p=self.prior/'final-result.json';raw=read_json(p)
        raw['value']['findings'][0]['path']='/bluf';raw['value_sha256']=fingerprint(raw['value']);write_json(p,raw)
        self.plan['malformed_review_sha256']=raw['value_sha256'];self.save()
        api=Mock()
        with self.assertRaisesRegex(ValueError,'requires a malformed'):self.run_review(api)
        api.assert_not_called()
    def test_no_review_or_research_budget_expansion(self):
        for key,value in [('maximum_total_audit_requests',4),('maximum_protocol_repair_requests',2),
            ('additional_research_generation_calls',1),('publication_authorized',True),('research_counter_reset',True)]:
            old=self.plan[key];self.plan[key]=value;self.save();api=Mock()
            with self.subTest(key=key),self.assertRaises(ValueError):self.run_review(api)
            api.assert_not_called();self.plan[key]=old
    def test_changed_candidate_is_rejected_before_a_request(self):
        self.c['bluf']='Another candidate.';api=Mock()
        with self.assertRaisesRegex(ValueError,'binding'):self.run_review(api)
        api.assert_not_called()


if __name__=='__main__':unittest.main()
