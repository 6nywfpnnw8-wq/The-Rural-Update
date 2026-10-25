"""A date-specific cache continuation cannot become another discovery attempt."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import release_discovery_continuation as dc
import release_research as sr
import release_pipeline as rp
from release_core import digest, read_json, write_json
from test_release_staged_research import bounded_fixture, response, selection_response, reporting_response, DATE


class DiscoveryContinuationTests(unittest.TestCase):
    def setUp(self):
        gate=patch.object(sr,'ensure_reporting_plan',return_value=None)
        gate.start();self.addCleanup(gate.stop)
        self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name); self.cache = self.root / DATE
        self.policy = self.root / 'authorizations'
        self.payload = {'model': 'gpt-5-mini', 'input': 'Edition ' + DATE,
                        'tools': [{'type': 'web_search'}]}
        identity = digest(json.dumps({'engine': sr.ENGINE, 'model': self.payload['model'],
                                     'context': self.payload['input']}, sort_keys=True))
        self.discovery = {'notes': 'Retained synthetic evidence only.',
                          'web_search_items': sr._web_items(response('notes', web=True)), 'usage': None}
        self.file = self.cache / sr.ENGINE / 'discovery.json'
        sr._save(self.file, identity, self.discovery)
        write_json(self.cache / 'attempts.json', {'attempts': 2})
        write_json(self.cache / 'validation-research-response.json', {
            'edition_date': DATE, 'stage': 'research-response', 'run_id': 'failed-run',
            'passed': False, 'exception_category': 'ValueError'})
        self.plan = {'schema_version': 1, 'edition_date': DATE, 'engine': sr.ENGINE,
                     'continuation_method': dc.METHOD, 'maximum_retained_discovery_continuations': 1,
                     'maximum_additional_generation_attempts': 1, 'publication_authorized': False,
                     'new_discovery_prohibited': True, 'research_counter_reset': False,
                     'validation_override': False, 'failure_run_id': 'failed-run', 'identity': identity,
                     'discovery_file_sha256': digest(self.file.read_bytes()),
                     'discovery_value_sha256': digest(json.dumps(self.discovery, sort_keys=True, ensure_ascii=False)),
                     'attempt_ledger_sha256': digest((self.cache / 'attempts.json').read_bytes()),
                     'reason': 'Explicit synthetic one-time cache continuation authorization'}
        self.save_plan()

    def save_plan(self):write_json(self.policy / (DATE + '.json'), self.plan)
    def reserve(self):return sr.reserve_corrective_attempt(self.cache, DATE, self.policy)

    def test_reserves_once_preserving_original_files(self):
        before = {p: p.read_bytes() for p in (self.file, self.cache / 'attempts.json')}
        self.assertTrue(self.reserve()); self.assertFalse(self.reserve())
        for p, value in before.items():self.assertEqual(p.read_bytes(), value)
        marker = read_json(self.cache / dc.MARKER)
        self.assertIs(marker['new_discovery_prohibited'], True)
        self.assertIs(marker['publication_authorized'], False)
        self.assertIs(marker['original_attempt_ledger_unchanged'], True)

    def test_successful_continuation_has_no_discovery_request(self):
        self.assertTrue(self.reserve())
        e = bounded_fixture(); report = copy.deepcopy(e); report.pop('podcast'); report.pop('sources')
        send = Mock(side_effect=[selection_response(e['sources']), reporting_response(report), response(e['podcast'])])
        result = sr.staged_request(self.payload, send, self.cache)
        self.assertEqual(json.loads(sr._text(result)), e)
        self.assertEqual(send.call_count, 3)
        for call in send.call_args_list:self.assertNotIn('tools', call.args[0])
        self.assertEqual(read_json(self.cache / 'attempts.json'), {'attempts': 2})
        self.assertFalse((self.cache / 'approved.json').exists())
        self.assertFalse(self.reserve())

    def test_changed_context_or_model_cannot_start_discovery(self):
        self.assertTrue(self.reserve())
        for payload in ({**self.payload, 'input': 'Different context'},
                        {**self.payload, 'model': 'different-model'}):
            send = Mock()
            with self.assertRaises(RuntimeError):sr.staged_request(payload, send, self.cache)
            send.assert_not_called()

    def test_missing_discovery_cannot_be_replaced(self):
        self.assertTrue(self.reserve()); self.file.unlink(); send = Mock()
        with self.assertRaises(RuntimeError):sr.staged_request(self.payload, send, self.cache)
        send.assert_not_called()

    def test_cache_loss_cannot_revert_to_default_first_attempt(self):
        self.cache.joinpath('attempts.json').unlink()
        write_json(self.root / 'repair-authorizations' / (DATE + '.json'), self.plan)
        with patch.object(rp, 'ROOT', self.root), patch.object(rp, 'request_api') as send:
            with self.assertRaises(RuntimeError):
                rp.research(DATE, {'intelligence': {}, 'signals': []}, self.cache)
            send.assert_not_called()
        self.assertFalse((self.cache / 'attempts.json').exists())

    def test_missing_bound_discovery_stops_publisher_before_any_request(self):
        self.file.unlink()
        write_json(self.root / 'repair-authorizations' / (DATE + '.json'), self.plan)
        before = (self.cache / 'attempts.json').read_bytes()
        with patch.object(rp, 'ROOT', self.root), patch.object(rp, 'request_api') as send:
            with self.assertRaises(RuntimeError):
                rp.research(DATE, {'intelligence': {}, 'signals': []}, self.cache)
            send.assert_not_called()
        self.assertEqual((self.cache / 'attempts.json').read_bytes(), before)

    def test_changed_discovery_stops_before_reservation(self):
        self.file.write_text(self.file.read_text() + '\n')
        with self.assertRaises(RuntimeError):self.reserve()
        self.assertFalse((self.cache / dc.MARKER).exists())

    def test_changed_discovery_stops_after_reservation(self):
        self.assertTrue(self.reserve()); self.file.write_text(self.file.read_text() + '\n'); send = Mock()
        with self.assertRaises(RuntimeError):sr.staged_request(self.payload, send, self.cache)
        send.assert_not_called()

    def test_original_ledger_cannot_be_reset_or_reformatted(self):
        for value in ({'attempts': 0}, {'attempts': 1}, {'attempts': 3}, {'attempts': True}):
            write_json(self.cache / 'attempts.json', value)
            with self.assertRaises(RuntimeError):self.reserve()
        (self.cache / 'attempts.json').write_text('{"attempts":2}')
        with self.assertRaises(RuntimeError):self.reserve()

    def test_altered_ledger_after_reservation_stops_calls(self):
        self.assertTrue(self.reserve()); write_json(self.cache / 'attempts.json', {'attempts': 0}); send = Mock()
        with self.assertRaises(RuntimeError):sr.staged_request(self.payload, send, self.cache)
        send.assert_not_called()

    def test_another_date_or_missing_authorization_cannot_resume(self):
        self.assertFalse(sr.reserve_corrective_attempt(self.cache, '2026-10-12', self.policy))
        (self.policy / (DATE + '.json')).unlink()
        self.assertFalse(self.reserve())

    def test_other_stage_or_audit_state_cannot_use_this_allowance(self):
        for p in (self.cache / sr.ENGINE / 'sources.json', self.cache / sr.ENGINE / 'reporting.json',
                  self.cache / sr.ENGINE / 'narration.json', self.cache / 'audit.json',
                  self.cache / 'audit-bound.json', self.cache / 'approved.json'):
            write_json(p, {}); self.assertFalse(self.reserve()); p.unlink()
        write_json(self.cache / 'candidates' / 'generated-example.json', {})
        self.assertFalse(self.reserve())

    def test_failure_identity_cannot_be_substituted(self):
        self.plan['failure_run_id'] = 'different-run'; self.save_plan()
        with self.assertRaises(RuntimeError):self.reserve()

    def test_plan_cannot_approve_or_expand_the_allowance(self):
        for key, value in [('new_discovery_prohibited', False), ('publication_authorized', True),
                           ('research_counter_reset', True), ('validation_override', True),
                           ('maximum_retained_discovery_continuations', 2),
                           ('maximum_additional_generation_attempts', 2)]:
            old = self.plan[key]; self.plan[key] = value; self.save_plan()
            with self.assertRaises(RuntimeError):self.reserve()
            self.plan[key] = old

    def test_failed_source_selection_spends_the_single_allowance(self):
        self.assertTrue(self.reserve()); send = Mock(return_value=response({'sources': {}}))
        with self.assertRaises(Exception):sr.staged_request(self.payload, send, self.cache)
        self.assertEqual(send.call_count, 1)
        self.assertFalse(self.reserve())
        self.assertEqual(read_json(self.cache / 'attempts.json'), {'attempts': 2})

    def test_production_authorization_is_exactly_cache_bound(self):
        root = Path(__file__).resolve().parents[1]
        plan = read_json(root / 'repair-authorizations/2026-10-25.json')
        self.assertEqual(plan['continuation_method'], dc.METHOD)
        self.assertEqual(plan['maximum_retained_discovery_continuations'], 1)
        self.assertEqual(plan['failure_run_id'], '40185398122')
        for key in ('publication_authorized', 'research_counter_reset', 'validation_override'):
            self.assertIs(plan[key], False)
        self.assertIs(plan['new_discovery_prohibited'], True)


if __name__ == '__main__':unittest.main()
