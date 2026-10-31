"""A reviewed PDF-source continuation never reopens discovery or spent requests."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts')]
import release_retained_app as recovery
import release_research as research
import release_pipeline as pipeline
import release_evidence as evidence
import release_coverage_plan as coverage
from release_core import digest,read_json,write_json
from release_source_selection import source_choices
from test_release_app_only import app_fixture,DATE
from test_release_coverage_plan import documents_for,plan_for,planned_report,plan_response
from test_release_staged_research import response
from evidence_fixture import fake_source


class RetainedAppTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.cache=self.root/DATE;self.policy_root=self.root/'policy'
        self.original='a'*64;self.payload={'model':'test','input':'App briefing '+DATE,'tools':[{'type':'web_search'}]}
        self.edition=app_fixture(True);self.catalog=copy.deepcopy(self.edition['sources'])
        self.report=copy.deepcopy(self.edition);self.report.pop('sources')
        self.documents=documents_for(self.catalog)
        pdfs=['https://www.cms.gov/retained-guidance.pdf','https://www.govinfo.gov/retained-rule.pdf']
        observed=[s['url'] for s in self.catalog]+pdfs
        self.discovery={'notes':'Retained synthetic notes.','web_search_items':[
            {'type':'web_search_call','action':{'sources':[{'url':url} for url in observed]}}]}
        folder=self.cache/research.ENGINE
        research._save(folder/'discovery.json',self.original,self.discovery)
        research._save(folder/'sources.json',self.original,{'sources':self.catalog})
        bound=coverage.evidence_identity(self.original,self.catalog)
        research._save(folder/coverage.METHOD/'sources.json',bound,{'documents':self.documents})
        identity=digest(bound+digest(json.dumps(self.documents,sort_keys=True,ensure_ascii=False)))
        rejected=plan_for(self.report,self.catalog,self.documents)
        chosen=next(k for k,v in rejected['signals']['signal_2']['source_anchors'].items() if v is not None)
        rejected['signals']['signal_2']['source_anchors']={k:(v if k==chosen else None)
            for k,v in rejected['signals']['signal_2']['source_anchors'].items()}
        research._save(folder/coverage.METHOD/'plan.json',identity,{'plan':rejected})
        write_json(self.cache/'attempts.json',{'attempts':2})
        write_json(self.cache/'validation-research-coverage.json',{'edition_date':DATE,'run_id':'777',
            'passed':False,'rule':'evidence_coverage','api_stage':'reporting_plan'})
        choices=source_choices(observed);self.additions=[];self.pdf_documents=[]
        for i,url in enumerate(pdfs):
            key=next(key for key,value in choices.items() if value==url)
            source={'id':key,'url':url,'title':'Synthetic verified PDF '+str(i),'published_date':None}
            document=documents_for([source])[0];document['content_type']='application/pdf'
            document['extraction']={'format':'pdf','text_only':True,'images_reviewed':False,'page_count':1}
            self.pdf_documents.append(document)
            self.additions.append({**source,'sha256':document['sha256'],'text_sha256':document['text_sha256']})
        self.policy={'schema_version':1,'edition_date':DATE,'method':recovery.METHOD,
            'maximum_recoveries':1,'maximum_reporting_plan_requests':1,'maximum_reporting_requests':1,
            'new_discovery_permitted':False,'source_selection_model_requests':0,'research_counter_reset':False,
            'independent_editorial_review_required':True,'podcast_generation_permitted':False,
            'publication_authorized':False,'failure_run_id':777,'original_identity':self.original,
            'failure_report_sha256':digest((self.cache/'validation-research-coverage.json').read_bytes()),
            'discovery_sha256':read_json(folder/'discovery.json')['sha256'],
            'sources_sha256':read_json(folder/'sources.json')['sha256'],
            'coverage_evidence_sha256':read_json(folder/coverage.METHOD/'sources.json')['sha256'],
            'coverage_plan_sha256':read_json(folder/coverage.METHOD/'plan.json')['sha256'],
            'added_sources':self.additions,'editorial_notes':['Recheck all supporting passages.']}
        self.save_policy()
        self.fetcher=patch.object(recovery,'fetch_source',side_effect=lambda url:
            copy.deepcopy(next(d for d in self.pdf_documents if d['url']==url)))
        self.fetch=self.fetcher.start();self.addCleanup(self.fetcher.stop)
        self.original_files={p:p.read_bytes() for p in self.cache.rglob('*.json')}

    def save_policy(self):write_json(self.policy_root/(DATE+'.json'),self.policy)

    def prepare(self):return recovery.prepare_continuation(self.cache,DATE,self.payload,self.policy_root)

    def good_responses(self):
        catalog=self.catalog+[{k:s[k] for k in ('id','title','url','published_date')} for s in self.additions]
        documents=self.documents+self.pdf_documents
        report=copy.deepcopy(self.report)
        report['signals'][1]['source_ids']=[self.catalog[0]['id'],self.additions[0]['id']]
        plan=plan_for(report,catalog,documents)
        return [plan_response(plan,documents),response(planned_report(report,plan,catalog))]

    def test_two_reporting_requests_no_discovery_and_original_files_unchanged(self):
        run=self.prepare();send=Mock(side_effect=self.good_responses());out=run(send)
        names=[c.args[0]['text']['format']['name'] for c in send.call_args_list]
        self.assertEqual(names,['reporting_plan','reporting'])
        self.assertTrue(all(not c.args[0].get('tools') for c in send.call_args_list))
        self.assertNotIn('podcast',json.loads(research._text(out)))
        for p,before in self.original_files.items():self.assertEqual(p.read_bytes(),before)
        self.assertFalse((self.cache/'approved.json').exists())
        self.assertEqual(self.fetch.call_count,2)
        repeat=self.prepare();unused=Mock(side_effect=AssertionError('No replay request'))
        self.assertEqual(repeat(unused),out);unused.assert_not_called()
        self.assertEqual(self.fetch.call_count,2)

    def test_bad_pdf_hash_blocks_before_a_model_call_or_reservation(self):
        self.pdf_documents[0]['sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'differs from its reviewed evidence'):self.prepare()
        self.assertFalse((self.cache/(recovery.METHOD+'-used.json')).exists())
        self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':2})

    def test_unobserved_source_cannot_be_added(self):
        self.policy['added_sources'][0]['url']='https://www.cms.gov/unobserved.pdf';self.save_policy()
        with self.assertRaisesRegex(ValueError,'not observed'):self.prepare()
        self.fetch.assert_not_called()

    def test_changed_original_stage_blocks_before_fetch(self):
        p=self.cache/research.ENGINE/'sources.json';raw=read_json(p);raw['value']['sources'][0]['title']='Altered'
        write_json(p,raw)
        with self.assertRaisesRegex(RuntimeError,'integrity'):self.prepare()
        self.fetch.assert_not_called()

    def test_policy_cannot_expand_requests_or_approve_publication(self):
        for key,value in [('maximum_recoveries',2),('maximum_reporting_requests',2),
                          ('new_discovery_permitted',True),('publication_authorized',True),
                          ('source_selection_model_requests',1),('research_counter_reset',True)]:
            original=self.policy[key];self.policy[key]=value;self.save_policy()
            with self.subTest(key=key),self.assertRaises(ValueError):self.prepare()
            self.policy[key]=original
        self.fetch.assert_not_called()

    def test_incomplete_plan_is_not_submitted_again(self):
        run=self.prepare();send=Mock(return_value=response('unfinished',status='incomplete'))
        with self.assertRaises(research.ResponseStateError):run(send)
        with self.assertRaises((RuntimeError,coverage.CoverageError)):self.prepare()(send)
        self.assertEqual(send.call_count,1)
        self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':2})

    def test_ambiguous_reporting_submission_is_not_repeated(self):
        run=self.prepare();send=Mock(side_effect=[self.good_responses()[0],TimeoutError('transport')])
        with self.assertRaises(TimeoutError):run(send)
        with self.assertRaisesRegex(RuntimeError,'another request'):self.prepare()(send)
        self.assertEqual(send.call_count,2)

    def test_changed_target_context_cannot_reuse_reservation(self):
        self.prepare()(Mock(side_effect=self.good_responses()))
        self.payload['input']='Changed app request'
        with self.assertRaisesRegex(ValueError,'reservation differs'):self.prepare()

    def test_started_audit_cannot_open_the_continuation(self):
        write_json(self.cache/'audit.json',{'approved':False,'issues':['rejected']})
        with self.assertRaisesRegex(ValueError,'started editorial'):self.prepare()
        self.fetch.assert_not_called()

    def test_symlink_checkpoint_is_rejected(self):
        p=self.cache/research.ENGINE/'sources.json';target=self.root/'saved.json'
        target.write_bytes(p.read_bytes());p.unlink();p.symlink_to(target)
        with self.assertRaisesRegex(ValueError,'Unsafe'):self.prepare()

    def test_pipeline_continuation_still_requires_independent_audit(self):
        policy_root=self.root/'app-evidence-recovery';write_json(policy_root/(DATE+'.json'),self.policy)
        api=Mock(side_effect=self.good_responses()+[response({'review_complete':True,'findings':[]},web=True)])
        with patch.object(pipeline,'ROOT',self.root),patch.dict(os.environ,{'RURAL_UPDATE_STRUCTURED_REVIEW':'true'}), \
             patch.object(pipeline,'request_api',api),patch.object(evidence,'fetch_source',side_effect=fake_source), \
             patch.object(pipeline,'ensure_narration_length') as narration:
            record=pipeline.research(DATE,{},self.cache)
        self.assertTrue(record['audit']['approved']);self.assertNotIn('podcast',record['edition'])
        self.assertEqual(api.call_count,3);self.assertTrue(api.call_args.args[0]['tools'])
        narration.assert_not_called();self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':2})


if __name__=='__main__':unittest.main()
