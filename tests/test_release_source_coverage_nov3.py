"""Replay the retained source responses and the observed 118-page PDF failure."""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from jsonschema import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import release_source_selection as selection
import release_research as research
import release_evidence as evidence
import release_coverage_plan as coverage
import release_coverage_resume as resume
import release_pipeline as pipeline
from release_core import digest, read_json, write_json
from release_diagnostics import error_details
from test_release_staged_research import bounded_fixture, response
from test_release_coverage_plan import documents_for, plan_for, planned_report, plan_response
from test_release_pdf_evidence import pdf_bytes

ROOT = Path(__file__).resolve().parents[1]
INCIDENT = read_json(ROOT / 'tests/fixtures/source-coverage-2026-11-03.json')
DATE = INCIDENT['edition_date']


def retained_catalog(count):
    for snapshot in INCIDENT['selections']:
        assert digest(snapshot['output_text']) == snapshot['sha256']
        catalog = selection.compile_selection(snapshot['output_text'], INCIDENT['observed_urls'])
        if len(catalog) == count:return catalog
    raise AssertionError('Retained incident selection missing')


class ObservedSourceFailures(unittest.TestCase):
    def test_actual_first_response_is_13_items_and_local_gate_correctly_rejects_it(self):
        with self.assertRaises(ValidationError) as caught:
            research.validate_source_catalog(retained_catalog(13), INCIDENT['observed_urls'])
        details = error_details(caught.exception)
        self.assertEqual((details['path'], details['keyword']), ('/sources', 'maxItems'))
        self.assertEqual((details['actual_items'], details['required_limit']), (13, 12))

    def test_actual_retry_is_valid_and_preserves_the_exact_failed_pdf_url(self):
        catalog = research.validate_source_catalog(retained_catalog(9), INCIDENT['observed_urls'])
        self.assertEqual(catalog[3]['id'], INCIDENT['invalid_source_id'])
        self.assertEqual(catalog[3]['url'],
                         'https://public-inspection.federalregister.gov/2026-14897.pdf?1784664910=')

    def test_bounded_generation_cannot_select_a_thirteenth_source(self):
        rows = retained_catalog(13)
        value = {'sources': {'source_' + str(i+1): {k: row[k] for k in ('id','title','published_date')}
                             for i,row in enumerate(rows)}}
        with self.assertRaises(ValidationError):
            selection.compile_bounded_selection(json.dumps(value), INCIDENT['observed_urls'])
        # Twelve is accepted intact; there is no automatic truncation of thirteen.
        value['sources'].pop('source_13')
        self.assertEqual(len(selection.compile_bounded_selection(json.dumps(value), INCIDENT['observed_urls'])), 12)
        value['sources']['source_12'] = value['sources']['source_1']
        with self.assertRaisesRegex(ValueError, 'Duplicate source catalog identifier'):
            selection.compile_bounded_selection(json.dumps(value), INCIDENT['observed_urls'])

    def test_slots_cannot_invent_urls_ids_or_skip_a_required_source(self):
        rows = retained_catalog(9)
        value = {'sources': {'source_' + str(i+1):
            {k: rows[i][k] for k in ('id','title','published_date')} if i<len(rows) else None
            for i in range(12)}}
        self.assertEqual(selection.compile_bounded_selection(json.dumps(value), INCIDENT['observed_urls']), rows)
        for change in ({'id':'invented'}, {'url':'https://www.cms.gov/invented'}):
            bad=copy.deepcopy(value);bad['sources']['source_1'].update(change)
            with self.assertRaises(ValidationError):
                selection.compile_bounded_selection(json.dumps(bad), INCIDENT['observed_urls'])
        value['sources']['source_1'] = None
        with self.assertRaises(ValidationError):
            selection.compile_bounded_selection(json.dumps(value), INCIDENT['observed_urls'])

    def test_118_page_document_previously_failed_and_now_extracts_every_page(self):
        raw=pdf_bytes(pages=118)
        with patch.object(evidence, 'MAX_PDF_PAGES', 100):
            with self.assertRaises(evidence.PDFPageLimitError) as caught:evidence.extract_pdf(raw)
        self.assertEqual(evidence.evidence_failure_details(caught.exception),
            {'failure_code':'pdf_page_limit','observed_pages':118,'maximum_pages':100})
        text,meta=evidence.extract_pdf(raw)
        self.assertEqual(meta['page_count'],118)
        self.assertEqual(len(meta['pages']),118)
        self.assertIn('[PDF page 118 of 118]',text)
        with self.assertRaises(evidence.PDFPageLimitError):evidence.extract_pdf(pdf_bytes(pages=161))

    @unittest.skipUnless(os.getenv('INCIDENT_PDF_PATH'), 'Optional exact public PDF byte replay')
    def test_exact_public_incident_pdf_bytes(self):
        raw=Path(os.environ['INCIDENT_PDF_PATH']).read_bytes()
        self.assertEqual(digest(raw),INCIDENT['pdf_sha256'])
        with patch.object(evidence,'MAX_PDF_PAGES',100):
            with self.assertRaises(evidence.PDFPageLimitError):evidence.extract_pdf(raw)
        text,meta=evidence.extract_pdf(raw)
        self.assertEqual(meta['page_count'],INCIDENT['pdf_pages'])
        self.assertEqual(len(text),INCIDENT['pdf_characters'])
        self.assertEqual(digest(text),INCIDENT['pdf_text_sha256'])

    def test_page_failure_retains_actionable_diagnostics_and_makes_no_model_call(self):
        catalog=retained_catalog(9);documents=documents_for(catalog)
        def fetch(url):
            if url==catalog[3]['url']:raise evidence.PDFPageLimitError(118)
            return copy.deepcopy(next(d for d in documents if d['url']==url))
        with tempfile.TemporaryDirectory() as tmp, patch.object(coverage,'fetch_source',side_effect=fetch), \
                patch.object(evidence,'MAX_PDF_PAGES',100):
            cache=Path(tmp)/DATE;send=Mock()
            with self.assertRaises(coverage.CoverageError):
                coverage.ensure_reporting_plan(catalog,{'notes':'test'},DATE,{'model':'test'},send,cache,'a'*64)
            send.assert_not_called()
            report=read_json(cache/'coverage-source-evidence.json')
            self.assertEqual(len(report['sources']),8)
            self.assertEqual(report['failures'][0]['source_id'],INCIDENT['invalid_source_id'])
            self.assertEqual(report['failures'][0]['failure_code'],'pdf_page_limit')
            self.assertEqual(report['failures'][0]['observed_pages'],118)


class RetainedCoverageContinuation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cache=Path(self.tmp.name)/DATE;self.policies=Path(self.tmp.name)/'policies'
        self.payload={'model':'test','input':'Edition '+DATE,'tools':[{'type':'web_search'}]}
        self.identity=digest(json.dumps({'engine':research.ENGINE,'model':'test','context':self.payload['input']},sort_keys=True))
        self.catalog=retained_catalog(9);self.documents=documents_for(self.catalog)
        self.documents[3].update(sha256=INCIDENT['pdf_sha256'],extraction={'page_count':118})
        self.discovery={'notes':'Synthetic test facts, not editorial approval.','web_search_items':[
            {'type':'web_search_call','action':{'sources':[{'url':u} for u in INCIDENT['observed_urls']]}}]}
        research._save(self.cache/research.ENGINE/'discovery.json',self.identity,self.discovery)
        research._save(self.cache/research.ENGINE/'sources.json',self.identity,{'sources':self.catalog,'usage':None})
        write_json(self.cache/'attempts.json',{'attempts':2})
        write_json(self.cache/'validation-research-coverage.json',{
            'edition_date':DATE,'passed':False,'rule':'evidence_coverage','api_stage':'reporting_plan',
            'run_id':'41628763038','findings':[{'rule':'source_retrieval','path':'/sources/3',
                'source_id':self.catalog[3]['id'],'url':self.catalog[3]['url'],
                'exception_category':'ValueError','http_status':None}]})
        self.policy=read_json(ROOT/'coverage-resume/2026-11-03.json')
        self.policy['identity']=self.identity
        for key,name in [('attempt_ledger_sha256','attempts.json'),('failure_report_sha256','validation-research-coverage.json'),
                         ('discovery_file_sha256',research.ENGINE+'/discovery.json'),('sources_file_sha256',research.ENGINE+'/sources.json')]:
            self.policy[key]=digest((self.cache/name).read_bytes())
        write_json(self.policies/(DATE+'.json'),self.policy)
        review=patch.dict(os.environ,{'RURAL_UPDATE_STRUCTURED_REVIEW':'true'})
        review.start();self.addCleanup(review.stop)
        fetch=patch.object(coverage,'fetch_source',side_effect=lambda u:
            copy.deepcopy(next(d for d in self.documents if d['url']==u)))
        self.fetch=fetch.start();self.addCleanup(fetch.stop)
        edition=bounded_fixture();old=[s['id'] for s in edition['sources']]
        mapping=dict(zip(old,[s['id'] for s in self.catalog]))
        for group in ('stories','actions','deadlines','signals','issue_updates'):
            for item in edition[group]:item['source_ids']=[mapping[i] for i in item['source_ids']]
        edition.pop('podcast');edition.pop('sources');edition['edition_date']=DATE
        for a in edition['actions']:a['due_date']=None
        edition['deadlines']=[]
        self.report=edition;self.plan=plan_for(edition,self.catalog,self.documents)

    def prepare(self, payload=None):
        return resume.prepare(self.cache,DATE,payload or self.payload,self.policies)

    def send(self):
        return Mock(side_effect=[plan_response(self.plan,self.documents),
            response(planned_report(self.report,self.plan,self.catalog))])

    def test_completed_stages_need_only_plan_and_report_and_replay_needs_no_calls(self):
        original={n:(self.cache/n).read_bytes() for n in ('attempts.json',research.ENGINE+'/discovery.json',research.ENGINE+'/sources.json')}
        send=self.send();result=self.prepare()(send)
        self.assertEqual(send.call_count,2)
        self.assertEqual([c.args[0]['text']['format']['name'] for c in send.call_args_list],['reporting_plan','reporting'])
        self.assertTrue(all(not c.args[0].get('tools') for c in send.call_args_list))
        self.assertNotIn('podcast',json.loads(research._text(result)))
        again=Mock(side_effect=AssertionError('No repeated request'))
        self.assertEqual(self.prepare()(again),result);again.assert_not_called()
        for name,raw in original.items():self.assertEqual((self.cache/name).read_bytes(),raw)
        self.assertFalse((self.cache/'approved.json').exists())

    def test_ambiguous_plan_request_remains_spent(self):
        with self.assertRaisesRegex(RuntimeError,'ambiguous'):
            self.prepare()(Mock(side_effect=RuntimeError('ambiguous')))
        send=Mock()
        with self.assertRaises(FileExistsError):self.prepare()(send)
        send.assert_not_called()
        self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':2})

    def test_insufficient_evidence_stays_blocked_before_report(self):
        self.plan['status']='insufficient_evidence';self.plan['stories']['story_5']=None
        send=self.send()
        with self.assertRaises(coverage.CoverageError):self.prepare()(send)
        self.assertEqual(send.call_count,1)
        self.assertFalse((self.cache/research.ENGINE/'reporting.json').exists())

    def test_changed_pdf_stops_before_a_model_request(self):
        self.documents[3]['sha256']='b'*64;send=Mock()
        with self.assertRaisesRegex(RuntimeError,'PDF differs'):self.prepare()(send)
        send.assert_not_called()

    def test_missing_cache_changed_identity_ledger_and_review_disabled_fail_closed(self):
        for key in ('attempt_ledger_sha256','failure_report_sha256','discovery_file_sha256','sources_file_sha256'):
            policy=copy.deepcopy(self.policy);policy.pop(key)
            write_json(self.policies/(DATE+'.json'),policy)
            with self.assertRaisesRegex(RuntimeError,'hash differs'):self.prepare()
        write_json(self.policies/(DATE+'.json'),self.policy)
        with self.assertRaisesRegex(RuntimeError,'identity differs'):
            self.prepare({**self.payload,'model':'changed'})
        with patch.dict(os.environ,{'RURAL_UPDATE_STRUCTURED_REVIEW':'false'}):
            with self.assertRaisesRegex(RuntimeError,'structured'):self.prepare()
        source=self.cache/research.ENGINE/'sources.json';raw=source.read_bytes();source.unlink()
        with self.assertRaisesRegex(RuntimeError,'missing or unsafe'):self.prepare()
        source.write_bytes(raw)
        write_json(self.cache/'attempts.json',{'attempts':0})
        with self.assertRaisesRegex(RuntimeError,'hash differs'):self.prepare()

    def test_policy_cannot_raise_stage_limits_or_approve_publication(self):
        for key,value in [('maximum_reporting_plan_requests',2),('maximum_reporting_requests',2),
                          ('publication_authorized',True),('new_discovery_permitted',True),
                          ('source_selection_model_requests',1),('research_counter_reset',True)]:
            with self.subTest(key=key):
                write_json(self.policies/(DATE+'.json'),{**self.policy,key:value})
                with self.assertRaisesRegex(RuntimeError,'Invalid'):self.prepare()

    def test_pipeline_honors_missing_bound_cache_before_any_new_research(self):
        (self.cache/research.ENGINE/'discovery.json').unlink()
        root=Path(self.tmp.name)
        write_json(root/'coverage-resume'/(DATE+'.json'),self.policy)
        with patch.object(pipeline,'ROOT',root),patch.object(pipeline,'research_payload',return_value=self.payload), \
                patch.object(pipeline,'request_api') as send:
            with self.assertRaisesRegex(AssertionError,'app-evidence-resume'):
                pipeline.research(DATE,{},self.cache)
            send.assert_not_called()


if __name__=='__main__':unittest.main()
