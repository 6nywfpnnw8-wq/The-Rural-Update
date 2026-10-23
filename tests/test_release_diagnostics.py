"""Public-source synthetic fixtures only. No remote calls or production edits."""
import copy
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import release_core as core
import release_pipeline as pipeline
import release_diagnostics as diag
from test_release import fixture, DATE


def response(data, search=True):
    out = [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(data)}]}]
    if search:
        out.insert(0, {'type': 'web_search_call', 'action': {'sources': [
            {'url': s['url']} for s in fixture()['sources']]}})
    return {'status': 'completed', 'output': out}


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        from evidence_fixture import fake_source
        import release_evidence
        source_patch = patch.object(release_evidence, 'fetch_source', side_effect=fake_source)
        source_patch.start(); self.addCleanup(source_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name)
        self.d = diag.Diagnostics(self.cache, DATE)

    def rejected(self, candidate):
        with self.assertRaises(diag.DiagnosedFailure) as cm:
            self.d.validate(candidate, core.validate_edition, 'content')
        return cm.exception

    def test_pinpoints_nested_narration_field_and_term(self):
        e = fixture(); e['podcast']['developments'][1] += ' TBD'
        err = self.rejected(e)
        self.assertIn('/podcast/developments/1', str(err))
        self.assertIn('matched "tbd"', str(err))
        self.assertNotIn(e['podcast']['developments'][1], str(err))

    def test_pinpoints_nonpodcast_field(self):
        e = fixture(); e['actions'][0]['next_step'] = 'TODO'
        self.assertIn('/actions/0/next_step', str(self.rejected(e)))

    def test_url_marker_is_identified_without_exposing_url(self):
        e = fixture(); e['sources'][0]['url'] = 'https://www.cms.gov/placeholder-test'
        err = self.rejected(e)
        self.assertIn('/sources/0/url', str(err)); self.assertNotIn('https:', str(err))

    def test_broad_ordinary_prose_match_is_not_silently_exempted(self):
        e = fixture(); e['stories'][0]['what_changed'] = 'The final rule replaces a placeholder estimate.'
        self.assertEqual(self.rejected(e).report['rule'], 'placeholder_text')
        with self.assertRaisesRegex(AssertionError, 'Placeholder text'):
            core.validate_edition(e, DATE)

    def test_all_legacy_patterns_keep_their_decision(self):
        for text in ['TODO', 'TBD', 'draft pending', 'lorem ipsum', 'placeholder',
                     'Placeholders appear here', 'Methods remain unannounced', '\nTODO', 'Do not use TBD.']:
            with self.subTest(text=text):
                e = fixture(); e['bluf'] = text
                legacy = bool(re.search(r'draft pending|\bTODO\b|\bTBD\b|lorem ipsum|placeholder',
                                        json.dumps(e, ensure_ascii=False), re.I))
                self.assertEqual(bool(diag.placeholder_findings(e)), legacy)
                if legacy: self.rejected(e)
                else: self.d.validate(e, core.validate_edition, 'content')

    def test_multiple_matches_have_separate_paths(self):
        e = fixture(); e['bluf'] = 'TBD'; e['actions'][0]['title'] = 'TODO'
        findings = self.rejected(e).report['findings']
        self.assertEqual({f['path'] for f in findings}, {'/bluf', '/actions/0/title'})

    def test_schema_error_does_not_dump_candidate(self):
        e = fixture(); e['stories'][1]['policy_state'] = 'SENSITIVE_DRAFT_CONTENT'
        err = self.rejected(e)
        self.assertEqual(err.report['rule'], 'schema')
        self.assertIn('/stories/1/policy_state', str(err))
        self.assertNotIn('SENSITIVE_DRAFT_CONTENT', str(err))
        self.assertNotIn('SENSITIVE_DRAFT_CONTENT', (self.cache/'validation-content.json').read_text())

    def test_unexpected_keys_not_echoed_into_report(self):
        e = fixture(); e['SENSITIVE_DRAFT_KEY'] = 'TBD'
        err = self.rejected(e)
        self.assertNotIn('SENSITIVE_DRAFT_KEY', str(err))
        self.assertNotIn('SENSITIVE_DRAFT_KEY', json.dumps(err.report))

    def test_content_checks_remain_in_force(self):
        e = fixture(); e['podcast']['opening'] = 'Short.'
        self.assertEqual(self.rejected(e).report['rule'], 'spoken_word_count')
        e = fixture(); e['sources'][0]['published_date'] = '2099-01-01'
        self.assertEqual(self.rejected(e).report['rule'], 'future_source')

    def test_unpublished_snapshot_survives_rejection(self):
        e = fixture(); e['bluf'] = 'TBD'
        before = copy.deepcopy(e); err = self.rejected(e)
        saved = json.loads((self.cache/err.report['snapshot']['file']).read_text())
        self.assertEqual(saved['candidate'], e); self.assertEqual(e, before)
        self.assertFalse(saved['publication_authorized'])
        self.assertFalse((self.cache/'approved.json').exists())

    def test_configured_and_known_credentials_redacted_from_snapshot(self):
        e = fixture(); secret = 'actual-secret-value-used-only-for-test'
        e['bluf'] = 'TBD ' + secret + ' sk-testcredential123 ghp_testcredential123 Bearer test.token.here'
        with patch.dict(os.environ, {'OPENAI_API_KEY': secret}):
            err = self.rejected(e)
        text = (self.cache/err.report['snapshot']['file']).read_text()
        for forbidden in [secret, 'sk-testcredential123', 'ghp_testcredential123', 'test.token.here']:
            self.assertNotIn(forbidden, text)
            self.assertNotIn(forbidden, json.dumps(err.report))
        self.assertTrue(err.report['snapshot']['redacted'])

    def test_oversized_snapshot_is_not_saved(self):
        saved = self.d.capture('generated', {'text': 'x' * (diag.MAX_SNAPSHOT_BYTES + 1)})
        self.assertFalse(saved['retained']); self.assertFalse((self.cache/'candidates').exists())

    def test_missing_candidate_is_reported_not_recreated(self):
        report = diag.diagnose_cache(self.cache, DATE)
        self.assertEqual(report['candidate_status'], 'not-retained')
        self.assertEqual(report['api_calls_made'], 0)
        self.assertFalse(report['publication_authorized'])

    def test_diagnostics_do_not_modify_attempt_counter_or_approval(self):
        (self.cache/'attempts.json').write_text('{"attempts": 2}\n')
        before = (self.cache/'attempts.json').read_bytes()
        self.d.capture('generated', fixture())
        report = diag.diagnose_cache(self.cache, DATE)
        self.assertEqual((self.cache/'attempts.json').read_bytes(), before)
        self.assertEqual(report['research_attempts'], 2)
        self.assertFalse(report['publication_authorized'])
        self.assertFalse((self.cache/'approved.json').exists())

    def test_exhausted_research_budget_makes_zero_api_calls(self):
        (self.cache/'attempts.json').write_text('{"attempts": 2}\n')
        before = (self.cache/'attempts.json').read_bytes()
        with patch.object(pipeline, 'request_api') as api:
            with self.assertRaisesRegex(diag.DiagnosedFailure, '2 of 2'):
                pipeline.research(DATE, {}, self.cache)
        api.assert_not_called()
        self.assertEqual((self.cache/'attempts.json').read_bytes(), before)

    def test_diagnose_cli_cannot_build_or_commit(self):
        with patch.object(pipeline, 'ROOT', self.cache), patch.object(pipeline, 'build') as build, \
             patch.object(pipeline, 'request_api') as api, patch.object(pipeline, 'commit_outputs') as commit, \
             patch.object(sys, 'argv', ['publisher', '--date', DATE, '--diagnose-cached']), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pipeline.main(), 0)
        build.assert_not_called(); api.assert_not_called(); commit.assert_not_called()

    def test_diagnose_and_commit_combination_is_rejected(self):
        with patch.object(pipeline, 'ROOT', self.cache), \
             patch.object(sys, 'argv', ['publisher', '--date', DATE, '--diagnose-cached', '--commit']):
            with self.assertRaisesRegex(ValueError, 'cannot commit'):
                pipeline.main()

    def test_alert_uses_only_same_run_failure(self):
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '123'}):
            e = fixture(); e['bluf'] = 'TBD'; self.rejected(e)
            self.assertIn('/bluf', diag.current_failure_summary(self.cache))
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '124'}):
            self.assertIsNone(diag.current_failure_summary(self.cache))

    def test_research_retains_candidate_before_validation_and_no_audit_on_failure(self):
        e = fixture(); e['stories'][0]['what_changed'] = 'TBD'
        api = Mock(return_value=response(e))
        with patch.object(pipeline, 'request_api', api):
            with self.assertRaisesRegex(diag.DiagnosedFailure, '/stories/0/what_changed'):
                pipeline.research(DATE, {}, self.cache)
        self.assertEqual(api.call_count, 1)
        self.assertGreaterEqual(len(list((self.cache/'candidates').glob('*.json'))), 2)
        self.assertFalse((self.cache/'approved.json').exists())

    def test_successful_structure_does_not_bypass_audit_or_provenance(self):
        api = Mock(side_effect=[response(fixture()), response({'approved': True, 'issues': []})])
        with patch.object(pipeline, 'request_api', api):
            record = pipeline.research(DATE, {}, self.cache)
        self.assertEqual(api.call_count, 2)
        core.validate_edition(record['edition'], DATE, set(record['retrieved_urls']))
        for file in self.cache.glob('validation-*.json'):
            self.assertFalse(json.loads(file.read_text())['publication_authorized'])

    def test_schema_failure_before_narration_is_retained_without_raw_error(self):
        e = fixture(); e['actions'][0]['due_date'] = {'secret': 'SENSITIVE_VALUE'}
        with patch.object(pipeline, 'request_api', return_value=response(e)):
            with self.assertRaises(diag.DiagnosedFailure) as cm:
                pipeline.research(DATE, {}, self.cache)
        self.assertNotIn('SENSITIVE_VALUE', str(cm.exception))
        self.assertTrue(list((self.cache/'candidates').glob('*.json')))

    def test_unapproved_snapshot_cannot_be_used_as_approved_cache(self):
        self.d.capture('generated', fixture())
        (self.cache/'attempts.json').write_text('{"attempts": 2}')
        with patch.object(pipeline, 'request_api') as api:
            with self.assertRaises(diag.DiagnosedFailure): pipeline.research(DATE, {}, self.cache)
        api.assert_not_called(); self.assertFalse((self.cache/'approved.json').exists())

    def test_artifact_patterns_do_not_include_full_candidates(self):
        workflow = (Path(__file__).resolve().parents[1]/'.github/workflows/publish.yml').read_text()
        artifact_section = workflow.split('      - name: Preserve validation and delivery reports')[1]
        self.assertIn('validation-*.json', artifact_section)
        self.assertNotIn('candidates', artifact_section)
        self.assertNotIn('approved.json', artifact_section)
        self.assertIn('      - name: Diagnose blocked recovery without generation', workflow)
        self.assertIn("if: always() && steps.prepare.outcome == 'failure' && (env.MODE == 'publish' || env.MODE == 'recover')", workflow)
        self.assertIn("run: python3 scripts/release_pipeline.py --date '${{ steps.edition.outputs.date }}' --diagnose-cached", workflow)
        self.assertLess(workflow.index('Diagnose blocked recovery without generation'), workflow.index('Configure Pages'))


if __name__ == '__main__': unittest.main()
