"""Exact-text planning, citation binding, negative plans, and bounded resume."""
import copy
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch
from jsonschema import Draft202012Validator, ValidationError
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts')]
import release_coverage_plan as coverage
import release_research as research
import release_reporting_references as references
from release_core import SCHEMA, digest, read_json, write_json
from release_diagnostics import error_details
from test_release_staged_research import bounded_fixture, response, selection_response, DATE


def documents_for(catalog):
    return [dict(source_id=s['id'], url=s['url'], final_url=s['url'], http_status=200,
        method='direct_https', text=('Synthetic supporting public-source facts for ' + s['id'] + '. ') * 4,
        sha256='a' * 64, text_sha256=digest(('Synthetic supporting public-source facts for ' + s['id'] + '. ') * 4))
        for s in catalog]


def plan_for(report, catalog, documents):
    text = {d['source_id']: d['text'][:120] for d in documents}
    value = {'status': 'ready', 'shortfall': ''}
    for group in coverage.GROUPS:
        value[group] = {}
        for slot, item in zip(coverage.slots(group), report[group]):
            refs = item['source_ids']
            if isinstance(refs, dict):refs = [k for k, v in refs.items() if v]
            value[group][slot] = {'id': item['id'], 'title': item['title'],
                'angle': item['title'] + ': assess the specific operating implications for rural executives.',
                'change': item.get('change', 'Continuing'), 'policy_state': item.get('policy_state', 'Monitoring'),
                'source_anchors': {s['id']: text[s['id']] if s['id'] in refs else None for s in catalog}}
    return value


def planned_report(report, plan, catalog):
    value = copy.deepcopy(report)
    for group in coverage.GROUPS:
        fields = ('id', 'title', 'source_ids', 'change', 'policy_state') if group == 'stories' else ('id', 'title', 'source_ids')
        value[group] = {slot: {k: v for k, v in item.items() if k not in fields}
                        for slot, item in zip(coverage.slots(group), value[group])}
    for group in ('actions', 'deadlines', 'issue_updates'):
        for item in value.get(group, []):
            item['source_ids'] = {s['id']: s['id'] in item['source_ids'] for s in catalog}
    return value


class CoveragePlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / DATE
        self.edition = bounded_fixture();self.catalog = self.edition['sources']
        self.report = copy.deepcopy(self.edition);self.report.pop('sources');self.report.pop('podcast')
        self.documents = documents_for(self.catalog);self.plan = plan_for(self.report, self.catalog, self.documents)
        self.fetch = patch.object(coverage, 'fetch_source', side_effect=lambda url: copy.deepcopy(next(d for d in self.documents if d['url'] == url)))
        self.fetcher = self.fetch.start();self.addCleanup(self.fetch.stop)
        self.schema = research.reporting_schema(self.catalog, DATE)
        self.payload = {'model': 'gpt-5-mini', 'input': 'Edition ' + DATE, 'tools': [{'type': 'web_search'}]}

    def ensure(self, send):
        return coverage.ensure_reporting_plan(self.catalog, {'notes': 'Unapproved research notes.'},
            'Edition ' + DATE, {'model': 'gpt-5-mini'}, send, self.cache, 'a' * 64)

    def test_ready_plan_requires_exact_passages_but_does_not_approve_publication(self):
        result = self.ensure(Mock(return_value=response(self.plan)))
        self.assertEqual(result['plan'], self.plan)
        self.assertFalse((self.cache / 'approved.json').exists())
        self.assertFalse((self.cache / 'source-evidence.json').exists())
        self.assertEqual(self.fetcher.call_count, len(self.catalog))

    def test_nonexistent_anchor_is_rejected_before_reporting(self):
        self.plan['signals']['signal_1']['source_anchors'][self.catalog[0]['id']] = 'This fabricated passage does not appear in the actual source text.'
        with self.assertRaises(coverage.CoverageError) as caught:self.ensure(Mock(return_value=response(self.plan)))
        self.assertIn('missing_source_anchor', [f['rule'] for f in caught.exception.coverage_findings])
        self.assertFalse((self.cache / research.ENGINE / 'reporting.json').exists())

    def test_complete_negative_plan_is_retained_and_not_automatically_retried(self):
        self.plan['status'] = 'insufficient_evidence';self.plan['stories']['story_5'] = None
        with self.assertRaises(coverage.CoverageError):self.ensure(Mock(return_value=response(self.plan)))
        self.fetcher.reset_mock();again = Mock(side_effect=AssertionError('No further provider request'))
        with self.assertRaises(coverage.CoverageError):self.ensure(again)
        again.assert_not_called();self.fetcher.assert_not_called()

    def test_failed_source_retrieval_makes_zero_provider_requests(self):
        self.fetcher.side_effect = urllib.error.HTTPError(self.catalog[0]['url'], 404, '', {}, None)
        send = Mock()
        with self.assertRaises(coverage.CoverageError) as caught:self.ensure(send)
        send.assert_not_called()
        info = error_details(caught.exception)
        self.assertEqual(info['api_stage'], 'reporting_plan')
        self.assertEqual(info['findings'][0]['http_status'], 404)
        self.assertFalse(read_json(self.cache / 'coverage-source-evidence.json')['complete'])

    def test_duplicate_json_plan_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate coverage plan field'):
            self.ensure(Mock(return_value=response('{"status":"ready","status":"insufficient_evidence"}')))

    def test_incomplete_plan_response_is_not_parsed_or_used(self):
        with self.assertRaises(research.ResponseStateError):
            self.ensure(Mock(return_value=response(self.plan, status='incomplete')))
        self.assertFalse((self.cache / research.ENGINE / coverage.METHOD / 'plan.json').exists())

    def test_retained_october25_gaps_are_rejected_before_drafting(self):
        fixture = read_json(Path(__file__).parent / 'fixtures/reporting-rejection-2026-10-25.json')
        catalog = fixture['source_catalog'];documents = documents_for(catalog)
        plan = plan_for(json.loads(fixture['visible_text']), catalog, documents)
        with self.assertRaises(coverage.CoverageError) as caught:coverage.validate_plan(plan, catalog, documents)
        counts = [f for f in caught.exception.coverage_findings if f['rule'] == 'source_count']
        self.assertEqual([(f['path'], f['actual_items'], f['required_minimum']) for f in counts],
            [(f['path'], f['actual_items'], f['required_minimum']) for f in fixture['expected_findings']])

    def test_plan_rejects_duplicate_angles_and_source_substitution(self):
        self.plan['stories']['story_2']['angle'] = self.plan['stories']['story_1']['angle']
        with self.assertRaises(coverage.CoverageError):coverage.validate_plan(self.plan, self.catalog, self.documents)
        bad = copy.deepcopy(self.documents);bad[0]['url'] = self.catalog[1]['url']
        with self.assertRaises(RuntimeError):coverage.validate_documents(bad, self.catalog)

    def test_source_text_tampering_is_rejected_without_another_request(self):
        self.ensure(Mock(return_value=response(self.plan)))
        p = self.cache / research.ENGINE / coverage.METHOD / 'sources.json'
        saved = read_json(p);saved['value']['documents'][0]['text'] += ' modified';write_json(p, saved)
        send = Mock()
        with self.assertRaises(RuntimeError):self.ensure(send)
        send.assert_not_called()

    def test_plan_compiler_fixes_titles_ids_policy_labels_and_citation_sets(self):
        result = self.ensure(Mock(return_value=response(self.plan)))
        before = copy.deepcopy(SCHEMA)
        schema = references.generation_schema(self.schema, self.catalog, result)
        Draft202012Validator.check_schema(schema)
        generated = planned_report(self.report, self.plan, self.catalog)
        compiled = references.compile_report(json.dumps(generated), self.schema, self.catalog, result)
        self.assertEqual(compiled, self.report);self.assertEqual(SCHEMA, before)
        self.assertNotIn('source_ids', schema['properties']['signals']['properties']['signal_1']['properties'])

    def test_generated_output_cannot_replace_a_topic_or_its_citations(self):
        result = self.ensure(Mock(return_value=response(self.plan)))
        generated = planned_report(self.report, self.plan, self.catalog)
        generated['stories']['story_5']['source_ids'] = []
        with self.assertRaises(ValidationError):
            references.compile_report(json.dumps(generated), self.schema, self.catalog, result)

    def test_full_staged_generation_plans_before_reporting_and_narration(self):
        send = Mock(side_effect=[response('Unapproved notes.', web=True), selection_response(self.catalog),
            response(self.plan), response(planned_report(self.report, self.plan, self.catalog)), response(self.edition['podcast'])])
        actual = research.staged_request(self.payload, send, self.cache)
        self.assertEqual(json.loads(research._text(actual)), self.edition)
        self.assertEqual(send.call_count, 5)
        self.assertEqual(send.call_args_list[2].args[0]['text']['format']['name'], 'reporting_plan')
        self.assertNotIn('tools', send.call_args_list[2].args[0])
        again = Mock(side_effect=AssertionError('Completed cache must be reused'))
        self.fetcher.reset_mock()
        self.assertEqual(research.staged_request(self.payload, again, self.cache), actual)
        again.assert_not_called();self.fetcher.assert_not_called()

    def test_report_resume_reuses_validated_plan_and_original_attempt_ledger(self):
        write_json(self.cache / 'attempts.json', {'attempts': 2});before = (self.cache / 'attempts.json').read_bytes()
        send = Mock(side_effect=[response('Notes.', web=True), selection_response(self.catalog), response(self.plan),
                                response('incomplete report', status='incomplete')])
        with self.assertRaises(research.ResponseStateError):research.staged_request(self.payload, send, self.cache)
        again = Mock(side_effect=[response(planned_report(self.report, self.plan, self.catalog)), response(self.edition['podcast'])])
        self.fetcher.reset_mock();research.staged_request(self.payload, again, self.cache)
        self.assertEqual(again.call_count, 2);self.fetcher.assert_not_called()
        self.assertEqual((self.cache / 'attempts.json').read_bytes(), before)


if __name__ == '__main__':unittest.main()
