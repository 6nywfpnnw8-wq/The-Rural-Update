"""A reviewed passage assignment can use only the unused reporting request."""
import copy,json,os,sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from jsonschema import ValidationError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_reporting_plan_review as review
import release_retained_app as parent
import release_pipeline as pipeline
import release_research as research
import release_coverage_plan as coverage
import release_evidence as evidence
from release_core import digest,write_json,read_json
import test_release_evidence_completion as completion
import test_release_retained_app as legacy
from test_release_coverage_plan import plan_response
from test_release_staged_research import response
from evidence_fixture import fake_source


class ReviewedReportingPlanTests(unittest.TestCase):
    def save_policy(self):legacy.RetainedAppTests.save_policy(self)
    def good_responses(self):return legacy.RetainedAppTests.good_responses(self)

    def setUp(self):
        completion.VerifiedEvidenceCompletionTests.setUp(self)
        self.date=self.policy['edition_date']
        parent_root=self.root/'app-evidence-recovery'
        write_json(parent_root/(self.date+'.json'),self.policy)
        self.parent_workspace=self.cache/parent.COMPLETION/self.date
        self.catalog=self.catalog+[{k:s[k] for k in ('id','title','url','published_date')} for s in self.additions]
        docs=self.documents+self.pdf_documents
        original=read_json(self.cache/research.ENGINE/coverage.METHOD/'plan.json')['value']['plan']
        for group in ('stories','signals'):
            for item in original[group].values():
                if item is not None:item['source_anchors'].update({s['id']:None for s in self.additions})
        call=parent.prepare_continuation(self.cache,self.date,self.payload,parent_root)
        with self.assertRaises(coverage.CoverageError):
            call(Mock(return_value=plan_response(original,docs)))
        write_json(self.cache/'validation-research-coverage.json',{'edition_date':self.date,'run_id':'888',
            'passed':False,'rule':'evidence_coverage','api_stage':'reporting_plan'})
        self.review_root=self.root/'reporting-plan-review'
        folder=self.parent_workspace/research.ENGINE
        self.complete=copy.deepcopy(self.report)
        self.complete['signals'][1]['source_ids']=[self.catalog[0]['id'],self.additions[0]['id']]
        from test_release_coverage_plan import plan_for,planned_report
        ready=plan_for(self.complete,self.catalog,docs)
        visible=research._text(plan_response(ready,docs))
        compiled=coverage.compile_plan(visible,self.catalog,docs)
        self.reporting_response=response(planned_report(self.complete,ready,self.catalog))
        self.review={'schema_version':1,'edition_date':self.date,'method':review.METHOD,
            'maximum_reporting_requests':1,'additional_coverage_plan_requests':0,
            'maximum_total_coverage_plan_requests':2,'new_discovery_permitted':False,
            'source_selection_model_requests':0,'research_counter_reset':False,
            'independent_editorial_review_required':True,'podcast_generation_permitted':False,
            'publication_authorized':False,'failure_run_id':888,
            'failure_report_sha256':digest((self.cache/'validation-research-coverage.json').read_bytes()),
            'attempt_ledger_sha256':digest((self.cache/'attempts.json').read_bytes()),
            'parent_policy_sha256':digest(json.dumps(self.policy,sort_keys=True,ensure_ascii=False)),
            'parent_reservation_sha256':digest((self.cache/(parent.COMPLETION+'-used.json')).read_bytes()),
            'parent_plan_request_sha256':digest((self.parent_workspace/'reporting_plan-reserved.json').read_bytes()),
            'parent_identity':read_json(folder/'discovery.json')['identity'],
            'discovery_sha256':read_json(folder/'discovery.json')['sha256'],
            'sources_sha256':read_json(folder/'sources.json')['sha256'],
            'evidence_sha256':read_json(folder/coverage.METHOD/'sources.json')['sha256'],
            'rejected_plan_sha256':read_json(folder/coverage.METHOD/'plan.json')['sha256'],
            'reviewed_plan_sha256':digest(json.dumps(compiled,sort_keys=True,ensure_ascii=False)),
            'reviewed_plan':json.loads(visible)}
        self.save_review();self.original_files={p:p.read_bytes() for p in self.cache.rglob('*.json')}

    def save_review(self):write_json(self.review_root/(self.date+'.json'),self.review)
    def prepare(self):return review.prepare(self.cache,self.date,self.payload,self.review_root)

    def test_only_reporting_is_submitted_and_prior_records_are_unchanged(self):
        send=Mock(return_value=self.reporting_response);result=self.prepare()(send)
        self.assertEqual(send.call_count,1)
        self.assertEqual(send.call_args.args[0]['text']['format']['name'],'reporting')
        self.assertFalse(send.call_args.args[0].get('tools'))
        self.assertNotIn('podcast',json.loads(research._text(result)))
        for p,before in self.original_files.items():self.assertEqual(p.read_bytes(),before)
        again=Mock();self.assertEqual(self.prepare()(again),result);again.assert_not_called()
        self.assertFalse((self.cache/'approved.json').exists())

    def test_actual_second_plan_repeats_missing_topics_and_exceeds_source_caps(self):
        root=Path(__file__).resolve().parents[1]
        saved=read_json(root/'tests/fixtures/coverage-completion-rejection-2026-11-03.json')
        self.assertEqual(digest(saved['output_text']),saved['sha256'])
        raw=json.loads(saved['output_text']);ids=list(raw['stories']['story_1']['source_anchors'])
        from release_source_selection import source_choices
        observed=read_json(root/'tests/fixtures/source-coverage-2026-11-03.json')['observed_urls']
        choices=source_choices(observed);catalog=[{'id':key,'url':choices[key]} for key in ids]
        documents=[{'source_id':key,'text':('Synthetic fixture evidence for '+key+'. ')*60} for key in ids]
        compiled=coverage.compile_plan(saved['output_text'],catalog,documents)
        with self.assertRaises(coverage.CoverageError) as caught:coverage.validate_plan(compiled,catalog,documents)
        self.assertEqual([(f['rule'],f['path']) for f in caught.exception.coverage_findings],[
            ('source_count','/stories/story_3/source_ids'),('missing_topic','/stories/story_5'),
            ('source_count','/signals/signal_1/source_ids'),('missing_topic','/signals/signal_4'),
            ('insufficient_evidence','/')])

    def test_ambiguous_reporting_is_never_submitted_again(self):
        with self.assertRaises(TimeoutError):self.prepare()(Mock(side_effect=TimeoutError('ambiguous')))
        send=Mock()
        with self.assertRaisesRegex(RuntimeError,'another request'):self.prepare()(send)
        send.assert_not_called();self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':2})

    def test_review_cannot_supply_missing_topics_or_single_source_signals(self):
        original=copy.deepcopy(self.review)
        for change in ('missing','one-source','bad-passage'):
            self.review=copy.deepcopy(original)
            if change=='missing':self.review['reviewed_plan']['stories']['story_5']=None
            if change=='one-source':
                item=self.review['reviewed_plan']['signals']['signal_4'];first=next(k for k,v in item['source_anchors'].items() if v is not None)
                item['source_anchors']={k:(v if k==first else None) for k,v in item['source_anchors'].items()}
            if change=='bad-passage':self.review['reviewed_plan']['stories']['story_1']['source_anchors'][self.catalog[0]['id']]=9999
            self.save_review()
            with self.subTest(change=change),self.assertRaises((coverage.CoverageError,ValidationError)):self.prepare()

    def test_reviewed_assignment_checksum_is_mandatory(self):
        self.review['reviewed_plan']['stories']['story_1']['title']='An altered reporting assignment title';self.save_review()
        with self.assertRaisesRegex(ValueError,'assignment hash differs'):self.prepare()

    def test_prior_plans_and_source_integrity_are_bound(self):
        for key in ('parent_reservation_sha256','parent_plan_request_sha256','attempt_ledger_sha256',
                    'failure_report_sha256','parent_policy_sha256','evidence_sha256','rejected_plan_sha256'):
            original=self.review.pop(key);self.save_review()
            with self.subTest(key=key),self.assertRaises((ValueError,RuntimeError)):self.prepare()
            self.review[key]=original

    def test_reporting_already_reserved_in_parent_cannot_be_reopened(self):
        write_json(self.parent_workspace/'reporting-reserved.json',{'stage':'reporting'})
        with self.assertRaisesRegex(ValueError,'spent reporting request'):self.prepare()

    def test_context_and_independent_review_cannot_be_changed(self):
        with patch.dict(os.environ,{'RURAL_UPDATE_STRUCTURED_REVIEW':'false'}):
            with self.assertRaisesRegex(ValueError,'review disabled'):self.prepare()
        self.payload['input']='Different context'
        with self.assertRaisesRegex(ValueError,'retained context'):self.prepare()

    def test_no_budget_reset_additional_planning_or_publication_override(self):
        for key,value in [('maximum_reporting_requests',2),('additional_coverage_plan_requests',1),
                          ('maximum_total_coverage_plan_requests',3),('publication_authorized',True),
                          ('source_selection_model_requests',1),('research_counter_reset',True)]:
            original=self.review[key];self.review[key]=value;self.save_review()
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'Invalid'):self.prepare()
            self.review[key]=original

    def test_started_editorial_work_blocks_a_new_reporting_assignment(self):
        write_json(self.cache/'editorial-loop-v1/original.json',{'unapproved':True})
        with self.assertRaisesRegex(ValueError,'started editorial'):self.prepare()

    def test_pipeline_requires_real_independent_audit_after_reviewed_assignment(self):
        api=Mock(side_effect=[self.reporting_response,response({'review_complete':True,'findings':[]},web=True)])
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'research_payload',return_value=self.payload), \
             patch.object(pipeline,'request_api',api),patch.object(evidence,'fetch_source',side_effect=fake_source), \
             patch.object(parent,'prepare_continuation',side_effect=AssertionError('Consumed planner must not reopen')):
            result=pipeline.research(self.date,{},self.cache)
        self.assertEqual(api.call_count,2);self.assertTrue(api.call_args.args[0]['tools'])
        self.assertTrue(result['audit']['approved']);self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':2})

    def test_incomplete_independent_review_still_blocks_approval(self):
        api=Mock(side_effect=[self.reporting_response,response({'review_complete':False,'findings':[]},web=True)])
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'research_payload',return_value=self.payload), \
             patch.object(pipeline,'request_api',api),patch.object(evidence,'fetch_source',side_effect=fake_source):
            with self.assertRaisesRegex(RuntimeError,'incomplete'):pipeline.research(self.date,{},self.cache)
        self.assertFalse((self.cache/'approved.json').exists());self.assertEqual(api.call_count,2)


if __name__=='__main__':unittest.main()
