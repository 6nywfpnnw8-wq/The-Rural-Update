"""Source-choice failures remain blocked, replayable, and within the daily cap."""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from jsonschema import Draft202012Validator, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import release_pipeline as rp
import release_research as sr
import release_source_selection as ss
from release_core import digest, read_json, write_json
from release_diagnostics import error_details, summary
from test_release import DATE
from test_release_staged_research import bounded_fixture, response, selection_response


class FixedSourceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup)
        self.cache = Path(self.t.name) / DATE
        self.e = bounded_fixture()
        self.urls = [s['url'] for s in self.e['sources']]
        self.text = sr._text(selection_response(self.e['sources']))
        self.payload = {'model': 'gpt-5-mini', 'input': 'Edition ' + DATE,
                        'tools': [{'type': 'web_search'}]}

    def test_ids_and_urls_are_bound_before_generation(self):
        rows = ss.compile_selection(self.text, self.urls)
        self.assertEqual(rows, self.e['sources'])
        self.assertEqual(ss.source_choices(self.urls), ss.source_choices(list(reversed(self.urls))))
        Draft202012Validator.check_schema(ss.selection_schema(self.urls))

    def test_canonical_alias_cannot_become_another_reference(self):
        aliases = [self.urls[0] + '/', self.urls[0] + '?utm_source=test']
        self.assertEqual(len(ss.source_choices(self.urls + aliases)), 5)
        self.assertEqual(len(ss.compile_selection(self.text, self.urls + aliases)), 5)

    def test_less_than_five_unique_observed_sources_stop_before_request(self):
        with self.assertRaisesRegex(ValueError, 'Fewer than five distinct'):
            ss.source_choices(self.urls[:4] + [self.urls[0] + '/'])

    def test_invented_url_or_identifier_is_rejected(self):
        for field in ('id', 'url'):
            value = json.loads(self.text)
            value['sources'][next(iter(value['sources']))][field] = 'invented'
            with self.assertRaises(ValidationError):
                ss.compile_selection(json.dumps(value), self.urls)
        value = json.loads(self.text); value['sources']['invented'] = None
        with self.assertRaises(ValidationError):ss.compile_selection(json.dumps(value), self.urls)

    def test_duplicate_json_fields_are_not_silently_overwritten(self):
        key = next(iter(ss.source_choices(self.urls)))
        text = '{"sources":{"' + key + '":null,"' + key + '":null}}'
        with self.assertRaisesRegex(ValueError, 'Duplicate source selection field') as caught:
            ss.compile_selection(text, self.urls)
        self.assertEqual(error_details(caught.exception)['rule'], 'source_selection_duplicate_key')

    def test_selection_count_is_still_enforced(self):
        value = json.loads(self.text); value['sources'][next(iter(value['sources']))] = None
        catalog = ss.compile_selection(json.dumps(value), self.urls)
        with self.assertRaises(ValidationError):sr.validate_source_catalog(catalog, self.urls)
        urls = ['https://www.cms.gov/test-' + str(n) for n in range(13)]
        value = {'sources': {key: {'title': 'Test', 'published_date': None}
                             for key in ss.source_choices(urls)}}
        catalog = ss.compile_selection(json.dumps(value), urls)
        with self.assertRaises(ValidationError):sr.validate_source_catalog(catalog, urls)

    def test_excess_correction_cannot_introduce_new_source(self):
        urls = ['https://www.cms.gov/test-' + str(n) for n in range(15)]
        choices = ss.source_choices(urls)
        selected = set(list(choices)[:13])
        schema = ss.excess_selection_schema(urls, selected)
        Draft202012Validator.check_schema(schema)
        value = {'sources': {key: ({'title': 'Known', 'published_date': None}
                                 if key in selected else None) for key in choices}}
        Draft202012Validator(schema).validate(value)
        new_key = next(key for key in choices if key not in selected)
        value['sources'][new_key] = {'title': 'Invented', 'published_date': None}
        with self.assertRaises(ValidationError):
            Draft202012Validator(schema).validate(value)

    def test_corrected_source_count_and_metadata_still_enforced(self):
        urls = ['https://www.cms.gov/test-' + str(n) for n in range(15)]
        choices = ss.source_choices(urls)
        initial = {'sources': {key: {'title': 'Known', 'published_date': None}
                               for key in choices}}
        original = ss.compile_selection(json.dumps(initial), urls)
        with self.assertRaises(ValidationError):
            sr.validate_source_catalog(original, urls)
        keys = list(choices)
        corrected = {'sources': {key: (initial['sources'][key] if key in keys[:12]
                                      else None) for key in keys}}
        subset = ss.compile_selection(json.dumps(corrected), urls)
        self.assertEqual(len(sr.validate_source_catalog(subset, urls)), 12)
        corrected['sources'][keys[0]]['title'] = 'Changed metadata'
        self.assertNotEqual(ss.compile_selection(json.dumps(corrected), urls)[0],
                            original[0])

    def test_legacy_successful_catalog_is_not_rekeyed(self):
        legacy = copy.deepcopy(self.e['sources'])
        for i, row in enumerate(legacy):row['id'] = 'legacy-' + str(i)
        self.assertEqual(sr.validate_source_catalog(legacy, self.urls), legacy)

    def test_rejected_visible_completion_is_retained_without_envelope(self):
        bad = response({'sources': {}})
        send = Mock(side_effect=[response('Observed evidence', web=True), bad])
        with self.assertRaises(ValidationError) as caught:
            sr.staged_request(self.payload, send, self.cache)
        self.assertEqual(send.call_count, 2)
        details = error_details(caught.exception)
        self.assertEqual(details['api_stage'], 'sources')
        saved = read_json(self.cache / details['stage_snapshot']['file'])
        self.assertEqual(saved['output_text'], sr._text(bad))
        self.assertEqual(saved['sha256'], digest(saved['output_text']))
        self.assertIs(saved['publication_authorized'], False)
        self.assertNotIn('usage', saved); self.assertNotIn('output', saved)
        self.assertFalse((self.cache / sr.ENGINE / 'sources.json').exists())
        self.assertFalse((self.cache / 'approved.json').exists())

    def test_secret_screened_snapshot_cannot_claim_original_text(self):
        secret = 'test-selection-secret-123456'
        with patch.dict(os.environ, {'OPENAI_API_KEY': secret}):
            info = ss.retain_selection(secret, self.cache, 'identity')
        saved = read_json(self.cache / info['file'])
        self.assertIs(saved['redacted'], True)
        self.assertNotIn(secret, json.dumps(saved))
        self.assertIs(saved['publication_authorized'], False)

    def test_oversized_completion_not_retained(self):
        info = ss.retain_selection('x' * (ss.MAX_SNAPSHOT_BYTES + 1), self.cache, 'identity')
        self.assertIs(info['retained'], False)
        self.assertFalse((self.cache / 'stage-responses').exists())

    def test_invalid_json_has_replayable_output_and_safe_parse_location(self):
        send = Mock(side_effect=[response('Observed evidence', web=True), response('{private text')])
        with self.assertRaises(json.JSONDecodeError) as caught:
            sr.staged_request(self.payload, send, self.cache)
        details = error_details(caught.exception)
        self.assertEqual(details['rule'], 'response_json')
        self.assertEqual(details['api_stage'], 'sources')
        self.assertNotIn('private text', json.dumps(details))
        self.assertTrue((self.cache / details['stage_snapshot']['file']).exists())

    def test_excessive_source_choices_stop_without_silent_truncation(self):
        urls = ['https://www.cms.gov/test-' + str(n) for n in range(ss.MAX_CHOICES + 1)]
        with self.assertRaisesRegex(ValueError, 'exceeds safe size'):ss.source_choices(urls)

    def test_incomplete_source_response_remains_blocked(self):
        raw = response(json.loads(self.text), status='incomplete')
        raw['incomplete_details'] = {'reason': 'max_output_tokens'}
        send = Mock(side_effect=[response('Observed evidence', web=True), raw])
        with self.assertRaises(sr.ResponseStateError) as caught:
            sr.staged_request(self.payload, send, self.cache)
        self.assertEqual(error_details(caught.exception)['api_stage'], 'sources')
        self.assertFalse((self.cache / sr.ENGINE / 'sources.json').exists())
        self.assertEqual(send.call_count, 2)

    def test_second_attempt_source_failure_does_not_grant_third_attempt(self):
        write_json(self.cache / 'attempts.json', {'attempts': 1})
        with patch.object(rp, 'ROOT', Path(self.t.name)), patch.object(rp, '_request_api',
             side_effect=[response('Observed evidence', web=True), response({'sources': {}})]) as paid:
            with self.assertRaisesRegex(AssertionError, 'schema'):
                rp.research(DATE, {'intelligence': {}, 'signals': []}, self.cache)
            self.assertEqual(paid.call_count, 2)
            report = read_json(self.cache / 'validation-latest.json')
            self.assertEqual(report['stage'], 'research-sources')
            self.assertEqual(report['rule'], 'schema')
            paid.reset_mock()
            with self.assertRaisesRegex(AssertionError, '2 of 2'):
                rp.research(DATE, {'intelligence': {}, 'signals': []}, self.cache)
            paid.assert_not_called()
        self.assertEqual(read_json(self.cache / 'attempts.json'), {'attempts': 2})
        self.assertFalse((self.cache / 'approved.json').exists())

    def test_duplicate_rejections_have_specific_safe_diagnostics(self):
        for message, rule in [('Duplicate source catalog identifier', 'source_identifier_duplicate'),
                              ('Duplicate source catalog URL', 'source_url_duplicate')]:
            report = error_details(ValueError(message))
            self.assertEqual(report['rule'], rule)
            self.assertIn(rule, summary(report))
        self.assertNotIn('private', json.dumps(error_details(ValueError('private source draft'))))

    def test_workflow_exports_ledger_and_screened_stage_output(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / '.github/workflows/publish.yml').read_text()
        self.assertIn('.release-cache/*/attempts.json', text)
        self.assertIn('.release-cache/*/stage-responses/*.json', text)
        self.assertNotIn('schedule:', text)
        self.assertIn('group: rural-update-single-publisher', text)


if __name__ == '__main__':unittest.main()
