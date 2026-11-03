"""Retain a complete report and reduce one reviewed citation set without generation."""
import copy,json,os,sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from jsonschema import Draft202012Validator,ValidationError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_reporting_plan_review as recovery
import release_reporting_references as references
import release_research as research
import release_pipeline as pipeline
import release_evidence as evidence
from release_core import digest,read_json,write_json
from release_typography import normalize_edition_typography,normalize_source_identifiers
import test_release_retained_app as legacy
import test_release_reporting_plan_review as parent_tests
from test_release_staged_research import response
from evidence_fixture import fake_source


class ReportReferenceReviewTests(unittest.TestCase):
    def save_policy(self):legacy.RetainedAppTests.save_policy(self)
    def good_responses(self):return legacy.RetainedAppTests.good_responses(self)
    def save_review(self):parent_tests.ReviewedReportingPlanTests.save_review(self)

    def setUp(self):
        parent_tests.ReviewedReportingPlanTests.setUp(self)
        raw=json.loads(research._text(self.reporting_response))
        template=copy.deepcopy(raw['actions'][0]);raw['actions']=[]
        for i in range(3):
            item=copy.deepcopy(template);item['id']='review-action-'+str(i)
            if i==2:item['source_ids']={s['id']:n<6 for n,s in enumerate(self.catalog)}
            raw['actions'].append(item)
        bad=response(raw)
        with self.assertRaises(ValidationError):
            recovery.prepare(self.cache,self.date,self.payload,self.review_root)(Mock(return_value=bad))
        self.workspace=self.cache/recovery.METHOD/self.date;folder=self.workspace/research.ENGINE
        snapshot=next((self.workspace/'stage-responses').glob('reporting-*.json'));saved=read_json(snapshot)
        self.api_record={'run_id':'999','stage':'reporting','status':'completed','incomplete_reason':None,
                         'error_code':None,'requested_output_limit':16000}
        write_json(self.cache/'api-responses.json',{'responses':[self.api_record]})
        write_json(self.cache/'validation-research-reporting.json',{'edition_date':self.date,'run_id':'999',
            'passed':False,'rule':'schema','keyword':'maxItems','path':'/actions/2/source_ids',
            'actual_items':6,'required_limit':5,'api_stage':'reporting'})
        selected=read_json(folder/'sources.json')['value'];catalog=selected['sources']
        plan=read_json(folder/'evidence-coverage-v2/plan.json')['value']['plan'];coverage={'plan':plan}
        schema=research.reporting_schema(catalog,self.date)
        compiled=references._bind_plan(references._compile_references(raw,catalog),catalog,coverage)
        before=compiled['actions'][2]['source_ids'];after=before[:2]
        compiled['actions'][2]['source_ids']=after;Draft202012Validator(schema).validate(compiled)
        compiled['sources']=catalog;compiled,_=normalize_edition_typography(compiled);compiled,_=normalize_source_identifiers(compiled)
        self.expected=compiled
        self.reference_root=self.root/'reporting-response-review'
        self.reference={'schema_version':1,'edition_date':self.date,'method':recovery.REFERENCE_METHOD,
            'additional_reporting_requests':0,'additional_coverage_plan_requests':0,'new_discovery_permitted':False,
            'source_selection_model_requests':0,'maximum_reference_corrections':1,'maximum_total_reporting_requests':1,
            'research_counter_reset':False,'independent_editorial_review_required':True,
            'podcast_generation_permitted':False,'publication_authorized':False,'failure_run_id':999,
            'failure_report_sha256':digest((self.cache/'validation-research-reporting.json').read_bytes()),
            'attempt_ledger_sha256':digest((self.cache/'attempts.json').read_bytes()),
            'parent_policy_sha256':digest(json.dumps(self.review,sort_keys=True,ensure_ascii=False)),
            'parent_reservation_sha256':digest((self.cache/(recovery.METHOD+'-used.json')).read_bytes()),
            'reporting_request_sha256':digest((self.workspace/'reporting-reserved.json').read_bytes()),
            'api_record_sha256':digest(json.dumps(self.api_record,sort_keys=True,ensure_ascii=False)),
            'parent_identity':read_json(folder/'discovery.json')['identity'],
            'discovery_sha256':read_json(folder/'discovery.json')['sha256'],
            'sources_sha256':read_json(folder/'sources.json')['sha256'],
            'evidence_sha256':read_json(folder/'evidence-coverage-v2/sources.json')['sha256'],
            'plan_sha256':read_json(folder/'evidence-coverage-v2/plan.json')['sha256'],
            'snapshot_file':snapshot.name,'snapshot_sha256':saved['sha256'],
            'correction':{'path':'/actions/2/source_ids','action_id':compiled['actions'][2]['id'],'before':before,'after':after},
            'corrected_candidate_sha256':digest(json.dumps(compiled,sort_keys=True,ensure_ascii=False))}
        self.save_reference();self.original_files={p:p.read_bytes() for p in self.cache.rglob('*.json')}

    def save_reference(self):write_json(self.reference_root/(self.date+'.json'),self.reference)
    def take(self):return recovery.take_report_reference(self.cache,self.date,self.reference_root)

    def test_completed_report_replays_without_models_and_preserves_original(self):
        with patch.object(research,'staged_request',side_effect=AssertionError('No generation')):
            edition,provenance=self.take();self.assertEqual(edition,self.expected)
            self.assertEqual(self.take(),(edition,provenance))
        for p,data in self.original_files.items():self.assertEqual(p.read_bytes(),data)
        self.assertFalse((self.cache/'approved.json').exists())

    def test_incomplete_error_or_duplicate_api_record_cannot_be_replayed(self):
        for changes in ({'status':'incomplete'},{'incomplete_reason':'max_output_tokens'},{'error_code':'server_error'}):
            record={**self.api_record,**changes}
            write_json(self.cache/'api-responses.json',{'responses':[record]})
            self.reference['api_record_sha256']=digest(json.dumps(record,sort_keys=True,ensure_ascii=False));self.save_reference()
            with self.assertRaisesRegex(ValueError,'uniquely completed'):self.take()
        write_json(self.cache/'api-responses.json',{'responses':[self.api_record,self.api_record]})
        with self.assertRaisesRegex(ValueError,'uniquely completed'):self.take()

    def test_correction_cannot_add_sources_change_words_or_edit_another_field(self):
        original=copy.deepcopy(self.reference)
        for changes in ({'after':[self.catalog[-1]['id']]},{'after':[]},{'after':original['correction']['before']},
                        {'path':'/stories/0/title'},{'action_id':'different-action'}):
            self.reference=copy.deepcopy(original);self.reference['correction'].update(changes);self.save_reference()
            with self.subTest(changes=changes),self.assertRaisesRegex(ValueError,'reduce only'):self.take()
        self.reference=copy.deepcopy(original);self.reference['correction']['after']=original['correction']['before'][1:3];self.save_reference()
        with self.assertRaisesRegex(ValueError,'changed unreviewed content'):self.take()

    def test_snapshot_and_parent_bindings_are_mandatory(self):
        for key in ('snapshot_sha256','parent_policy_sha256','parent_reservation_sha256','reporting_request_sha256',
                    'failure_report_sha256','attempt_ledger_sha256','evidence_sha256','plan_sha256'):
            original=self.reference.pop(key);self.save_reference()
            with self.subTest(key=key),self.assertRaises((ValueError,RuntimeError)):self.take()
            self.reference[key]=original

    def test_generation_budget_and_independent_review_cannot_be_relaxed(self):
        for key,value in [('additional_reporting_requests',1),('additional_coverage_plan_requests',1),
                          ('source_selection_model_requests',1),('publication_authorized',True),('research_counter_reset',True)]:
            original=self.reference[key];self.reference[key]=value;self.save_reference()
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'Invalid'):self.take()
            self.reference[key]=original
        self.save_reference()
        with patch.dict(os.environ,{'RURAL_UPDATE_STRUCTURED_REVIEW':'false'}):
            with self.assertRaisesRegex(ValueError,'review disabled'):self.take()

    def test_unsafe_snapshot_or_started_editorial_review_remains_blocking(self):
        self.reference['snapshot_file']='../report.json';self.save_reference()
        with self.assertRaisesRegex(ValueError,'Unsafe'):self.take()
        write_json(self.cache/'editorial-loop-v1/initial-reserved.json',{'publication_authorized':False})
        with self.assertRaisesRegex(ValueError,'started editorial'):self.take()

    def test_pipeline_makes_only_the_independent_audit_call(self):
        api=Mock(return_value=response({'review_complete':True,'findings':[]},web=True))
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'request_api',api), \
             patch.object(evidence,'fetch_source',side_effect=fake_source):
            result=pipeline.research(self.date,{},self.cache)
        self.assertTrue(result['audit']['approved']);self.assertEqual(api.call_count,1)
        self.assertTrue(api.call_args.args[0]['tools']);self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':2})

    def test_incomplete_independent_audit_never_approves_the_corrected_report(self):
        api=Mock(return_value=response({'review_complete':False,'findings':[]},web=True))
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'request_api',api), \
             patch.object(evidence,'fetch_source',side_effect=fake_source):
            with self.assertRaisesRegex(RuntimeError,'incomplete'):pipeline.research(self.date,{},self.cache)
        self.assertEqual(api.call_count,1);self.assertFalse((self.cache/'approved.json').exists())


if __name__=='__main__':unittest.main()
