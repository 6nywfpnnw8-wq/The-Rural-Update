"""Citation generation cannot emit repeated IDs; evidence minima remain intact."""
import copy
import json
import os
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch
from jsonschema import Draft202012Validator, ValidationError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_research as sr
import release_reporting_references as rr
from release_core import digest, read_json, write_json
from release_diagnostics import error_details
from test_release_staged_research import (bounded_fixture, response, selection_response,
                                        reporting_response, DATE)


class ReportingReferenceTests(unittest.TestCase):
    def setUp(self):
        gate=patch.object(sr,'ensure_reporting_plan',return_value=None)
        gate.start();self.addCleanup(gate.stop)
        self.e=bounded_fixture(); self.catalog=self.e['sources']
        self.report=copy.deepcopy(self.e);self.report.pop('sources');self.report.pop('podcast')
        self.schema=sr.reporting_schema(self.catalog,DATE)
        self.text=sr._text(reporting_response(self.report))

    def retained_rejection(self):
        return read_json(Path(__file__).parent/'fixtures/reporting-rejection-2026-10-25.json')

    def test_real_provider_rejection_replays_all_missing_citations_without_api(self):
        fixture=self.retained_rejection();text=fixture['visible_text']
        self.assertTrue(fixture['test_only']);self.assertIs(fixture['publication_authorized'],False)
        self.assertEqual(digest(text),fixture['response_text_sha256'])
        schema=sr.reporting_schema(fixture['source_catalog'],fixture['edition_date'])
        with patch.object(urllib.request,'urlopen') as network:
            replay=rr.replay_report(text,schema,fixture['source_catalog'])
        network.assert_not_called()
        self.assertEqual(replay['api_calls_made'],0)
        self.assertIs(replay['publication_authorized'],False)
        self.assertTrue(replay['generation_schema_passed'])
        self.assertFalse(replay['publication_schema_passed'])
        keys=('path','keyword','actual_items','required_minimum')
        self.assertEqual([{k:f[k] for k in keys} for f in replay['findings']],fixture['expected_findings'])
        self.assertEqual(digest(text),fixture['response_text_sha256'])

    def test_real_rejected_output_cannot_be_promoted_by_compiler(self):
        fixture=self.retained_rejection();text=fixture['visible_text']
        schema=sr.reporting_schema(fixture['source_catalog'],fixture['edition_date'])
        with self.assertRaises(ValidationError):rr.compile_report(text,schema,fixture['source_catalog'])
        self.assertEqual(digest(text),fixture['response_text_sha256'])

    def test_reporting_replay_identifies_duplicate_json_without_overwriting_it(self):
        replay=rr.replay_report('{"title":"first","title":"second"}',self.schema,self.catalog)
        self.assertEqual(replay['findings'][0]['rule'],'reporting_duplicate_key')
        self.assertEqual(replay['api_calls_made'],0)

    def test_fixed_keys_compile_to_the_same_publication_references(self):
        self.assertEqual(rr.compile_report(self.text,self.schema,self.catalog),self.report)
        Draft202012Validator.check_schema(rr.generation_schema(self.schema,self.catalog))

    def test_generation_does_not_change_the_publication_schema(self):
        before=copy.deepcopy(self.schema);rr.generation_schema(self.schema,self.catalog)
        self.assertEqual(before,self.schema)
        self.assertEqual(self.schema['properties']['signals']['items']['properties']['source_ids']['minItems'],2)

    def test_duplicate_json_key_cannot_silently_overwrite_a_citation(self):
        with self.assertRaisesRegex(ValueError,'Duplicate reporting response field') as caught:
            rr.compile_report('{"title":"first","title":"second"}',self.schema,self.catalog)
        self.assertEqual(error_details(caught.exception)['rule'],'reporting_duplicate_key')

    def test_invented_reference_key_and_array_format_are_rejected(self):
        for refs in ({'invented':True},[self.catalog[0]['id']]*2):
            value=json.loads(self.text);value['stories'][0]['source_ids']=refs
            with self.assertRaises(ValidationError):rr.compile_report(json.dumps(value),self.schema,self.catalog)

    def test_signal_still_requires_two_distinct_sources(self):
        value=json.loads(self.text)
        value['signals'][0]['source_ids']={s['id']:i==0 for i,s in enumerate(self.catalog)}
        with self.assertRaises(ValidationError) as caught:
            rr.compile_report(json.dumps(value),self.schema,self.catalog)
        self.assertEqual(caught.exception.validator,'minItems')
        self.assertEqual(list(caught.exception.absolute_path),['signals',0,'source_ids'])

    def test_signal_cannot_exceed_four_distinct_sources(self):
        value=json.loads(self.text);value['signals'][0]['source_ids']={s['id']:True for s in self.catalog}
        with self.assertRaises(ValidationError) as caught:
            rr.compile_report(json.dumps(value),self.schema,self.catalog)
        self.assertEqual(caught.exception.validator,'maxItems')

    def test_empty_story_citations_remain_blocked(self):
        value=json.loads(self.text);value['stories'][0]['source_ids']={s['id']:False for s in self.catalog}
        with self.assertRaises(ValidationError):rr.compile_report(json.dumps(value),self.schema,self.catalog)

    def test_legacy_duplicate_array_has_a_precise_safe_path(self):
        bad=copy.deepcopy(self.report);bad['signals'][2]['source_ids']=[self.catalog[0]['id']]*2
        with self.assertRaises(ValueError) as caught:sr.validate_reference_bindings(bad,self.catalog)
        report=error_details(caught.exception)
        self.assertEqual(report['rule'],'source_reference')
        self.assertEqual(report['path'],'/signals/2/source_ids')

    def test_failed_report_completion_retained_before_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            cache=Path(temp)/DATE
            raw=response({'title':'Synthetic rejected report'})
            send=Mock(side_effect=[response('Evidence notes',web=True),selection_response(self.catalog),raw])
            with self.assertRaises(ValidationError) as caught:
                sr.staged_request({'model':'gpt-5-mini','input':'Edition '+DATE,
                                   'tools':[{'type':'web_search'}]},send,cache)
            report=error_details(caught.exception)
            self.assertEqual(report['api_stage'],'reporting')
            self.assertEqual(send.call_count,3)
            saved=read_json(cache/report['stage_snapshot']['file'])
            self.assertEqual(saved['stage'],'reporting')
            self.assertEqual(saved['output_text'],sr._text(raw))
            self.assertIs(saved['publication_authorized'],False)
            self.assertFalse((cache/sr.ENGINE/'reporting.json').exists())
            self.assertFalse((cache/'approved.json').exists())

    def test_reporting_snapshot_redacts_known_credentials(self):
        from release_source_selection import retain_stage_output
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'OPENAI_API_KEY':'reporting-test-secret-123456'}):
            cache=Path(temp);info=retain_stage_output('reporting-test-secret-123456',cache,'identity','reporting')
            saved=read_json(cache/info['file'])
            self.assertIs(saved['redacted'],True)
            self.assertNotIn('reporting-test-secret-123456',json.dumps(saved))

    def test_failed_narration_completion_is_retained_at_its_own_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            cache=Path(temp)/DATE
            bad=response({'opening':'Synthetic incomplete script.'})
            send=Mock(side_effect=[response('Evidence notes',web=True),selection_response(self.catalog),
                                  reporting_response(self.report),bad])
            with self.assertRaises(ValidationError) as caught:
                sr.staged_request({'model':'gpt-5-mini','input':'Edition '+DATE,
                                   'tools':[{'type':'web_search'}]},send,cache)
            report=error_details(caught.exception)
            self.assertEqual(report['api_stage'],'narration')
            saved=read_json(cache/report['stage_snapshot']['file'])
            self.assertEqual(saved['stage'],'narration')
            self.assertEqual(saved['output_text'],sr._text(bad))
            self.assertFalse((cache/sr.ENGINE/'narration.json').exists())

    def test_existing_valid_report_cache_is_reused_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            cache=Path(temp)/DATE
            payload={'model':'gpt-5-mini','input':'Edition '+DATE,'tools':[{'type':'web_search'}]}
            send=Mock(side_effect=[response('Evidence notes',web=True),selection_response(self.catalog),
                                  reporting_response(self.report),response(self.e['podcast'])])
            first=sr.staged_request(payload,send,cache)
            again=Mock(side_effect=AssertionError('No additional request'))
            self.assertEqual(sr.staged_request(payload,again,cache),first)
            again.assert_not_called()


if __name__=='__main__':unittest.main()
