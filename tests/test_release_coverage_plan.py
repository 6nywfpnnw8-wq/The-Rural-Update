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
    text = {d['source_id']: coverage.normalized(d['text']) for d in documents}
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


def plan_response(plan, documents):
    value = copy.deepcopy(plan)
    choices = {d['source_id']: coverage.passages(d['text']) for d in documents}
    for group in coverage.GROUPS:
        for item in value[group].values():
            if item is None:continue
            item['source_anchors'] = {key: choices[key].index(text) if text is not None else None
                                      for key, text in item['source_anchors'].items()}
    return response(value)


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
        result = self.ensure(Mock(return_value=plan_response(self.plan, self.documents)))
        self.assertEqual(result['plan'], self.plan)
        self.assertFalse((self.cache / 'approved.json').exists())
        self.assertFalse((self.cache / 'source-evidence.json').exists())
        self.assertEqual(self.fetcher.call_count, len(self.catalog))

    def test_model_cannot_inject_a_fabricated_or_reordered_source_passage(self):
        self.plan['signals']['signal_1']['source_anchors'][self.catalog[0]['id']] = 'This fabricated passage does not appear in the actual source text.'
        with self.assertRaises(ValidationError):self.ensure(Mock(return_value=response(self.plan)))
        self.assertFalse((self.cache / research.ENGINE / 'reporting.json').exists())

    def test_complete_negative_plan_is_retained_and_not_automatically_retried(self):
        self.plan['status'] = 'insufficient_evidence';self.plan['stories']['story_5'] = None
        with self.assertRaises(coverage.CoverageError):self.ensure(Mock(return_value=plan_response(self.plan, self.documents)))
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

    def test_passage_index_zero_copies_actual_text_in_source_order(self):
        generated = json.loads(research._text(plan_response(self.plan, self.documents)))
        selected = next(k for k, v in generated['stories']['story_1']['source_anchors'].items() if v is not None)
        self.assertEqual(generated['stories']['story_1']['source_anchors'][selected], 0)
        compiled = coverage.compile_plan(json.dumps(generated), self.catalog, self.documents)
        document = next(d for d in self.documents if d['source_id'] == selected)
        self.assertEqual(compiled['stories']['story_1']['source_anchors'][selected], coverage.normalized(document['text']))

    def test_missing_indexes_boolean_values_and_free_text_are_not_passages(self):
        for invalid in (-1, 100000, True, 'A paraphrased source passage'):
            generated = json.loads(research._text(plan_response(self.plan, self.documents)))
            generated['stories']['story_1']['source_anchors'][self.catalog[0]['id']] = invalid
            with self.assertRaises(ValidationError):
                coverage.compile_plan(json.dumps(generated), self.catalog, self.documents)

    def test_passage_slicing_preserves_normalized_text_and_bounded_context(self):
        text = 'Implementation date follows subject in the original source. ' * 35
        pieces = coverage.passages(text)
        self.assertGreater(len(pieces), 1)
        self.assertEqual(' '.join(pieces), coverage.normalized(text))
        self.assertTrue(all(40 <= len(p) <= 800 for p in pieces))
        token = 'a' * 1500
        self.assertEqual(''.join(coverage.passages(token)), token)

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
        self.ensure(Mock(return_value=plan_response(self.plan, self.documents)))
        p = self.cache / research.ENGINE / coverage.METHOD / 'sources.json'
        saved = read_json(p);saved['value']['documents'][0]['text'] += ' modified';write_json(p, saved)
        send = Mock()
        with self.assertRaises(RuntimeError):self.ensure(send)
        send.assert_not_called()

    def test_plan_compiler_fixes_titles_ids_policy_labels_and_citation_sets(self):
        result = self.ensure(Mock(return_value=plan_response(self.plan, self.documents)))
        before = copy.deepcopy(SCHEMA)
        schema = references.generation_schema(self.schema, self.catalog, result)
        Draft202012Validator.check_schema(schema)
        generated = planned_report(self.report, self.plan, self.catalog)
        compiled = references.compile_report(json.dumps(generated), self.schema, self.catalog, result)
        self.assertEqual(compiled, self.report);self.assertEqual(SCHEMA, before)
        self.assertNotIn('source_ids', schema['properties']['signals']['properties']['signal_1']['properties'])

    def test_generated_output_cannot_replace_a_topic_or_its_citations(self):
        result = self.ensure(Mock(return_value=plan_response(self.plan, self.documents)))
        generated = planned_report(self.report, self.plan, self.catalog)
        generated['stories']['story_5']['source_ids'] = []
        with self.assertRaises(ValidationError):
            references.compile_report(json.dumps(generated), self.schema, self.catalog, result)

    def test_full_staged_generation_plans_before_reporting_and_narration(self):
        send = Mock(side_effect=[response('Unapproved notes.', web=True), selection_response(self.catalog),
            plan_response(self.plan, self.documents), response(planned_report(self.report, self.plan, self.catalog)), response(self.edition['podcast'])])
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
        send = Mock(side_effect=[response('Notes.', web=True), selection_response(self.catalog), plan_response(self.plan, self.documents),
                                response('incomplete report', status='incomplete')])
        with self.assertRaises(research.ResponseStateError):research.staged_request(self.payload, send, self.cache)
        again = Mock(side_effect=[response(planned_report(self.report, self.plan, self.catalog)), response(self.edition['podcast'])])
        self.fetcher.reset_mock();research.staged_request(self.payload, again, self.cache)
        self.assertEqual(again.call_count, 2);self.fetcher.assert_not_called()
        self.assertEqual((self.cache / 'attempts.json').read_bytes(), before)


    def test_one_authorized_plan_repair_reuses_evidence_without_new_discovery(self):
        if len(self.catalog) < 6:
            self.skipTest('fixture needs six sources to exercise the story maximum')
        invalid = copy.deepcopy(self.plan)
        passages = {d['source_id']: coverage.normalized(d['text']) for d in self.documents}
        all_anchors = {source['id']: passages[source['id']] for source in self.catalog}
        invalid['stories']['story_2']['source_anchors'] = copy.deepcopy(all_anchors)
        invalid['signals']['signal_2']['source_anchors'] = copy.deepcopy(all_anchors)
        first_signal_source = next(iter(all_anchors))
        invalid['signals']['signal_3']['source_anchors'] = {
            key: (passages[key] if key == first_signal_source else None) for key in all_anchors}
        first = Mock(side_effect=[response('Unapproved notes.', web=True),
            selection_response(self.catalog), plan_response(invalid, self.documents)])
        with self.assertRaises(coverage.CoverageError):
            research.staged_request(self.payload, first, self.cache)
        self.assertEqual(first.call_count, 3)

        attempts = self.cache / 'attempts.json'
        write_json(attempts, {'attempts': 2})
        ledger_before = attempts.read_bytes()
        policy_root = self.cache / 'repair-authorizations'
        policy_root.mkdir()
        write_json(policy_root / (DATE + '.json'), {
            'schema_version': 1, 'edition_date': DATE, 'engine': research.ENGINE,
            'maximum_additional_generation_attempts': 1,
            'maximum_coverage_plan_repairs': 1,
            'publication_authorized': False,
            'reason': 'One coverage-only repair using the retained evidence.'})
        self.assertTrue(research.reserve_corrective_attempt(self.cache, DATE, policy_root))
        self.assertFalse(research.reserve_corrective_attempt(self.cache, DATE, policy_root))

        second = Mock(side_effect=[plan_response(self.plan, self.documents),
            response(planned_report(self.report, self.plan, self.catalog)),
            response(self.edition['podcast'])])
        fetch_calls = self.fetcher.call_count
        actual = research.staged_request(self.payload, second, self.cache)
        self.assertEqual(json.loads(research._text(actual)), self.edition)
        self.assertEqual(second.call_count, 3)
        repair_request = second.call_args_list[0].args[0]
        self.assertIn('mandatory corrections', repair_request['instructions'])
        repair_input = json.loads(repair_request['input'])
        findings = repair_input['prior_coverage_findings']
        self.assertEqual({finding['path'] for finding in findings},
            {'/stories/1/source_ids', '/signals/1/source_ids', '/signals/2/source_ids'})
        self.assertEqual([finding['actual_items'] for finding in findings], [len(self.catalog), len(self.catalog), 1])
        self.assertEqual(self.fetcher.call_count, fetch_calls)
        self.assertEqual(attempts.read_bytes(), ledger_before)
        self.assertTrue((self.cache / 'coverage-plan-repair-used.json').exists())
        self.assertFalse((self.cache / 'approved.json').exists())



    def test_second_authorized_plan_repair_uses_next_slot_without_resetting_research(self):
        if len(self.catalog) < 6:
            self.skipTest('fixture needs six sources to exercise the story maximum')
        invalid = copy.deepcopy(self.plan)
        passages = {d['source_id']: coverage.normalized(d['text']) for d in self.documents}
        all_anchors = {source['id']: passages[source['id']] for source in self.catalog}
        invalid['stories']['story_2']['source_anchors'] = copy.deepcopy(all_anchors)
        invalid['signals']['signal_2']['source_anchors'] = copy.deepcopy(all_anchors)
        first_signal_source = next(iter(all_anchors))
        invalid['signals']['signal_3']['source_anchors'] = {
            key: (passages[key] if key == first_signal_source else None) for key in all_anchors}
        first = Mock(side_effect=[response('Notes.', web=True), selection_response(self.catalog),
                                  plan_response(invalid, self.documents)])
        with self.assertRaises(coverage.CoverageError):
            research.staged_request(self.payload, first, self.cache)

        attempts = self.cache / 'attempts.json'
        write_json(attempts, {'attempts': 2})
        ledger_before = attempts.read_bytes()
        policy_root = self.cache / 'repair-authorizations'
        policy_root.mkdir()
        write_json(policy_root / (DATE + '.json'), {
            'schema_version': 1, 'edition_date': DATE, 'engine': research.ENGINE,
            'maximum_additional_generation_attempts': 2,
            'maximum_coverage_plan_repairs': 2,
            'publication_authorized': False,
            'reason': 'Two separately authorized coverage-only corrections using retained evidence.'})
        self.assertTrue(research.reserve_corrective_attempt(self.cache, DATE, policy_root))

        repair = Mock(side_effect=[plan_response(self.plan, self.documents),
            response(planned_report(self.report, self.plan, self.catalog)),
            response(self.edition['podcast'])])
        result = research.staged_request(self.payload, repair, self.cache)
        self.assertEqual(json.loads(research._text(result)), self.edition)
        self.assertTrue((self.cache / 'coverage-plan-repair-used.json').exists())

        # Simulate the same integrity-bound plan being rejected again, then use
        # the newly authorized second slot. Source evidence remains byte-for-byte cached.
        plan_path = self.cache / research.ENGINE / coverage.METHOD / 'plan.json'
        saved = read_json(plan_path)
        value = saved['value']
        value['plan'] = invalid
        research._save(plan_path, saved['identity'], value)
        self.assertTrue(research.reserve_corrective_attempt(self.cache, DATE, policy_root))
        second = Mock(side_effect=[plan_response(self.plan, self.documents),
            response(planned_report(self.report, self.plan, self.catalog)),
            response(self.edition['podcast'])])
        result = research.staged_request(self.payload, second, self.cache)
        self.assertEqual(json.loads(research._text(result)), self.edition)
        self.assertTrue((self.cache / 'coverage-plan-repair-used-2.json').exists())
        self.assertFalse(research.reserve_corrective_attempt(self.cache, DATE, policy_root))
        self.assertEqual(attempts.read_bytes(), ledger_before)
        self.assertEqual(second.call_count, 3)
        self.assertEqual(self.fetcher.call_count, len(self.catalog))
        authorization = read_json(self.cache / 'coverage-plan-repair-authorized.json')
        self.assertEqual(authorization['maximum_coverage_plan_repairs'], 2)
        self.assertEqual(read_json(self.cache / 'coverage-plan-repair-used-2.json')['repair_number'], 2)
        self.assertFalse((self.cache / 'approved.json').exists())


if __name__ == '__main__':unittest.main()
