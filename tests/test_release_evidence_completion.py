"""A reviewed completion adds observed evidence, never approval or fresh discovery."""
import copy
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_retained_app as recovery
import release_coverage_resume as prior_recovery
import release_research as research
import release_coverage_plan as coverage
import release_pipeline as pipeline
import release_evidence as evidence
from release_core import digest,read_json,write_json
from release_source_selection import source_choices
import test_release_retained_app as legacy
from test_release_coverage_plan import documents_for,plan_for
from test_release_staged_research import response
from evidence_fixture import fake_source


class VerifiedEvidenceCompletionTests(unittest.TestCase):
    def setUp(self):
        legacy.RetainedAppTests.setUp(self)
        self.original=digest(json.dumps({'engine':research.ENGINE,'model':self.payload['model'],
                                        'context':self.payload['input']},sort_keys=True))
        observed=self.discovery['web_search_items'][0]['action']['sources']
        url='https://oklahoma.gov/rural-workforce-programs'
        observed.append({'url':url});choices=source_choices([s['url'] for s in observed])
        source={'id':next(k for k,v in choices.items() if v==url),'url':url,
                'title':'Synthetic state workforce programs','published_date':None}
        document=documents_for([source])[0];document['content_type']='text/html'
        self.pdf_documents.append(document)
        self.additions.append({**source,'sha256':document['sha256'],'text_sha256':document['text_sha256']})
        for s,d in zip(self.additions,self.pdf_documents):
            s['content_type']=d['content_type'];s['accepted_sha256']=[s['sha256']]
        folder=self.cache/research.ENGINE
        research._save(folder/'discovery.json',self.original,self.discovery)
        research._save(folder/'sources.json',self.original,{'sources':self.catalog})
        bound=coverage.evidence_identity(self.original,self.catalog)
        research._save(folder/coverage.METHOD/'sources.json',bound,{'documents':self.documents})
        plan_identity=digest(bound+digest(json.dumps(self.documents,sort_keys=True,ensure_ascii=False)))
        rejected=plan_for(self.report,self.catalog,self.documents)
        rejected['stories']['story_5']=None;rejected['signals']['signal_4']=None
        rejected['status']='insufficient_evidence'
        research._save(folder/coverage.METHOD/'plan.json',plan_identity,{'plan':rejected})
        write_json(self.cache/'retained-source-coverage-v1-used.json',{
            'method':'retained-source-coverage-v1','identity':self.original,
            'maximum_reporting_plan_requests':1,'publication_authorized':False})
        write_json(self.cache/'retained-source-coverage-v1-reporting_plan-reserved.json',{
            'stage':'reporting_plan','request_sha256':'a'*64,'publication_authorized':False})
        self.policy.update(method=recovery.COMPLETION,original_identity=self.original,
            prior_reporting_plan_requests=1,maximum_total_reporting_plan_requests=2,
            maximum_total_reporting_requests=1,
            attempt_ledger_sha256=digest((self.cache/'attempts.json').read_bytes()),
            prior_coverage_reservation_sha256=digest((self.cache/'retained-source-coverage-v1-used.json').read_bytes()),
            prior_reporting_plan_reservation_sha256=digest((self.cache/'retained-source-coverage-v1-reporting_plan-reserved.json').read_bytes()),
            discovery_sha256=read_json(folder/'discovery.json')['sha256'],
            sources_sha256=read_json(folder/'sources.json')['sha256'],
            coverage_evidence_sha256=read_json(folder/coverage.METHOD/'sources.json')['sha256'],
            coverage_plan_sha256=read_json(folder/coverage.METHOD/'plan.json')['sha256'],
            added_sources=self.additions)
        self.save_policy()
        self.original_files={p:p.read_bytes() for p in self.cache.rglob('*.json')}
        review=patch.dict(os.environ,{'RURAL_UPDATE_STRUCTURED_REVIEW':'true'})
        review.start();self.addCleanup(review.stop)

    def save_policy(self):legacy.RetainedAppTests.save_policy(self)
    def prepare(self):return legacy.RetainedAppTests.prepare(self)
    def good_responses(self):return legacy.RetainedAppTests.good_responses(self)

    def test_mixed_html_pdf_completion_keeps_predecessor_and_ledger_unchanged(self):
        send=Mock(side_effect=self.good_responses());run=self.prepare();result=run(send)
        self.assertEqual(send.call_count,2)
        self.assertEqual([c.args[0]['text']['format']['name'] for c in send.call_args_list],['reporting_plan','reporting'])
        self.assertTrue(all(not c.args[0].get('tools') for c in send.call_args_list))
        self.assertEqual(len(json.loads(research._text(result))['sources']),8)
        self.assertEqual(self.fetch.call_count,3)
        for p,before in self.original_files.items():self.assertEqual(p.read_bytes(),before)
        unused=Mock();self.assertEqual(self.prepare()(unused),result);unused.assert_not_called()
        self.assertFalse((self.cache/'approved.json').exists())

    def test_missing_or_changed_predecessor_binding_blocks_before_source_fetch(self):
        for key in ('prior_coverage_reservation_sha256','prior_reporting_plan_reservation_sha256',
                    'attempt_ledger_sha256'):
            changed=copy.deepcopy(self.policy);changed.pop(key)
            write_json(self.policy_root/(self.policy['edition_date']+'.json'),changed)
            with self.assertRaisesRegex(ValueError,'file hash differs'):self.prepare()
        self.fetch.assert_not_called()

    def test_missing_ledger_or_disabled_structured_review_cannot_start_normal_research(self):
        with patch.dict(os.environ,{'RURAL_UPDATE_STRUCTURED_REVIEW':'false'}):
            with self.assertRaisesRegex(ValueError,'structured review'):self.prepare()
        (self.cache/'attempts.json').unlink()
        with self.assertRaisesRegex(ValueError,'original exhausted ledger'):self.prepare()
        self.fetch.assert_not_called()

    def test_total_stage_budget_and_policy_types_are_fixed(self):
        for key,value in [('prior_reporting_plan_requests',0),('maximum_total_reporting_plan_requests',3),
                          ('maximum_total_reporting_requests',2),('maximum_reporting_plan_requests',2),
                          ('maximum_recoveries',True),('publication_authorized',True)]:
            changed={**self.policy,key:value};write_json(self.policy_root/(self.policy['edition_date']+'.json'),changed)
            with self.subTest(key=key),self.assertRaises(ValueError):self.prepare()
        self.fetch.assert_not_called()

    def test_fourth_source_addition_and_changed_media_type_are_rejected(self):
        self.policy['added_sources']=self.additions+[copy.deepcopy(self.additions[0])];self.save_policy()
        with self.assertRaisesRegex(ValueError,'source-addition limit'):self.prepare()
        self.policy['added_sources']=self.additions;self.additions[2]['content_type']='application/zip';self.save_policy()
        with self.assertRaisesRegex(ValueError,'unsupported reviewed media type'):self.prepare()
        self.fetch.assert_not_called()

    def test_changed_html_evidence_cannot_enter_reporting(self):
        self.pdf_documents[2]['text_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'Added source differs'):self.prepare()
        self.assertFalse((self.cache/(recovery.COMPLETION+'-used.json')).exists())

    def test_only_reviewed_html_variants_with_identical_full_text_are_allowed(self):
        self.additions[2]['accepted_sha256'].append('b'*64);self.save_policy()
        document=copy.deepcopy(self.pdf_documents[2]);document['sha256']='b'*64
        self.assertTrue(recovery.matches_reviewed_source(document,self.additions[2]))
        document['text_sha256']='c'*64
        self.assertFalse(recovery.matches_reviewed_source(document,self.additions[2]))
        for index,hashes in ((0,['a'*64,'b'*64]),(2,['a'*64,'b'*64,'c'*64])):
            self.additions[index]['accepted_sha256']=hashes;self.save_policy()
            with self.assertRaisesRegex(ValueError,'invalid reviewed byte variants'):self.prepare()
            self.additions[index]['accepted_sha256']=[self.additions[index]['sha256']]
        self.fetch.assert_not_called()

    def test_unobserved_source_and_changed_context_are_rejected(self):
        self.policy['added_sources'][2]['url']='https://oklahoma.gov/unobserved';self.save_policy()
        with self.assertRaisesRegex(ValueError,'not observed'):self.prepare()
        self.policy['added_sources'][2]['url']=self.pdf_documents[2]['url'];self.save_policy()
        self.payload['input']='Changed editorial context'
        with self.assertRaisesRegex(ValueError,'retained context'):self.prepare()
        self.fetch.assert_not_called()

    def test_ambiguous_new_plan_remains_consumed(self):
        send=Mock(side_effect=TimeoutError('ambiguous'))
        with self.assertRaises(TimeoutError):self.prepare()(send)
        unused=Mock()
        with self.assertRaises((RuntimeError,coverage.CoverageError)):self.prepare()(unused)
        unused.assert_not_called();self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':2})

    def test_started_reporting_cannot_be_replaced(self):
        for name in ('retained-source-coverage-v1-reporting-reserved.json',recovery.METHOD+'-used.json'):
            write_json(self.cache/name,{'stage':'reporting'})
            with self.assertRaisesRegex(ValueError,'spent reporting stages'):self.prepare()
            (self.cache/name).unlink()
        self.fetch.assert_not_called()

    def test_pipeline_supersedes_only_prior_reader_recovery_and_still_requires_audit(self):
        root=self.root;date=self.policy['edition_date']
        write_json(root/'app-evidence-recovery'/(date+'.json'),self.policy)
        api=Mock(side_effect=self.good_responses()+[response({'review_complete':True,'findings':[]},web=True)])
        with patch.object(pipeline,'ROOT',root),patch.object(pipeline,'research_payload',return_value=self.payload), \
             patch.object(pipeline,'request_api',api),patch.object(evidence,'fetch_source',side_effect=fake_source), \
             patch.object(prior_recovery,'prepare',side_effect=AssertionError('Prior reader allowance must stay spent')):
            record=pipeline.research(date,{},self.cache)
        self.assertTrue(record['audit']['approved']);self.assertTrue(api.call_args.args[0]['tools'])
        self.assertEqual(api.call_count,3);self.assertNotIn('podcast',record['edition'])
        self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':2})

    def test_incomplete_independent_audit_still_prevents_approval(self):
        root=self.root;date=self.policy['edition_date']
        write_json(root/'app-evidence-recovery'/(date+'.json'),self.policy)
        api=Mock(side_effect=self.good_responses()+[response({'review_complete':False,'findings':[]},web=True)])
        with patch.object(pipeline,'ROOT',root),patch.object(pipeline,'research_payload',return_value=self.payload), \
             patch.object(pipeline,'request_api',api),patch.object(evidence,'fetch_source',side_effect=fake_source):
            with self.assertRaisesRegex(RuntimeError,'incomplete'):pipeline.research(date,{},self.cache)
        self.assertFalse((self.cache/'approved.json').exists());self.assertEqual(api.call_count,3)


if __name__=='__main__':unittest.main()
