"""Regression tests for the live overlong-BLUF correction failure; no network."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from jsonschema import ValidationError
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from release_audit_loop import apply_replacements, _call, audit_and_correct
from release_editorial_budget import apply_with_bluf_budget, SLOT
from release_core import write_json, read_json, canonical_url
from test_release import fixture

SHORT = ' '.join(['This synthetic summary retains the documented qualification and verification requirement.'] * 6)
LONG = ' '.join(['This synthetic summary retains the documented qualification and verification requirement.'] * 20)


class EditorialBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name)
        self.folder = self.cache / 'editorial-loop-v1'
        self.folder.mkdir()
        self.edition = fixture()
        self.report = {'review_complete': True, 'findings': [{
            'id': 'finding_1', 'kind': 'unsupported_claim', 'path': '/bluf',
            'quote': self.edition['bluf'], 'source_ids': ['s1'],
            'explanation': 'Synthetic blocking issue.', 'required_change': 'Qualify the summary.'}]}
        self.plan = {'replacements': [{'path': '/bluf', 'before': self.edition['bluf'],
                                      'after': LONG, 'addresses': ['finding_1']}]}
        self.documents = [{'source_id': 's1', 'url': self.edition['sources'][0]['url'],
                           'text': 'Synthetic reference, not a real publication.'}]
        self.request = Mock(return_value={'bluf': SHORT})
        self.output = lambda result: json.dumps(result)
        write_json(self.cache / 'attempts.json', {'attempts': 2})

    def apply(self, plan=None):
        return apply_with_bluf_budget(self.edition, self.report, plan or self.plan,
            apply=apply_replacements, call=_call, folder=self.folder, model='test-model',
            documents=self.documents, request=self.request, output_text=self.output)

    def test_reproduces_original_failure(self):
        with self.assertRaisesRegex(AssertionError, 'Executive BLUF is too long'):
            apply_replacements(self.edition, self.report, self.plan)

    def test_repairs_only_bluf_and_preserves_attempts(self):
        original = copy.deepcopy(self.edition); plan = copy.deepcopy(self.plan)
        result = self.apply()
        self.assertEqual(result['bluf'], SHORT)
        result['bluf'] = original['bluf']
        self.assertEqual(result, original)
        self.assertEqual(self.edition, original); self.assertEqual(self.plan, plan)
        self.assertEqual(read_json(self.cache/'attempts.json'), {'attempts': 2})
        note = read_json(self.cache/'validation-editorial-budget.json')
        self.assertFalse(note['publication_authorized'])
        self.assertTrue(note['independent_final_audit_required'])
        self.assertFalse((self.cache/'approved.json').exists())

    def test_repeat_reuses_result_without_paid_request(self):
        self.apply(); self.apply()
        self.request.assert_called_once()

    def test_failed_submission_is_not_retried(self):
        self.request.side_effect = TimeoutError('simulated')
        with self.assertRaises(TimeoutError): self.apply()
        self.request.side_effect = None
        with self.assertRaisesRegex(RuntimeError, 'already reserved'): self.apply()
        self.request.assert_called_once()

    def test_acceptable_plan_uses_no_extra_call(self):
        plan = copy.deepcopy(self.plan); plan['replacements'][0]['after'] = SHORT
        self.apply(plan); self.request.assert_not_called()

    def test_placeholder_rejection_never_requests_compression(self):
        plan = copy.deepcopy(self.plan); plan['replacements'][0]['after'] = LONG + ' TBD'
        with self.assertRaises(AssertionError): self.apply(plan)
        self.request.assert_not_called()

    def test_immutable_source_edit_never_requests_compression(self):
        plan = copy.deepcopy(self.plan)
        plan['replacements'].append({'path': '/sources/0/url', 'before': 'x',
                                     'after': 'y', 'addresses': ['finding_1']})
        with self.assertRaises(ValidationError): self.apply(plan)
        self.request.assert_not_called()

    def test_oversized_return_remains_blocked(self):
        self.request.return_value = {'bluf': LONG}
        with self.assertRaises(ValidationError): self.apply()
        with self.assertRaises(ValidationError): self.apply()
        self.request.assert_called_once()

    def test_unexpected_response_field_rejected(self):
        self.request.return_value = {'bluf': SHORT, 'approved': True}
        with self.assertRaises(ValidationError): self.apply()

    def test_new_placeholder_is_still_rejected(self):
        self.request.return_value = {'bluf': SHORT + ' TBD'}
        with self.assertRaises(AssertionError): self.apply()
        self.assertFalse((self.cache/'approved.json').exists())

    def test_markup_is_still_rejected(self):
        self.request.return_value = {'bluf': SHORT + ' <script>unsafe</script>'}
        with self.assertRaises(ValueError): self.apply()

    def test_source_change_cannot_reuse_checkpoint(self):
        self.apply(); self.documents[0]['text'] = 'Changed source material.'
        with self.assertRaisesRegex(ValueError, 'differs from request'): self.apply()
        self.request.assert_called_once()

    def test_full_loop_reaudits_corrected_candidate(self):
        docs = [{'source_id': s['id'], 'url': s['url'], 'text': 'Synthetic evidence.'}
                for s in self.edition['sources']]
        urls = {canonical_url(s['url']) for s in self.edition['sources']}
        final_candidates = []
        def response(payload):
            name = payload['text']['format']['name']
            if name == 'editorial_audit_structured':
                if not final_candidates:
                    final_candidates.append('initial')
                    value = self.report
                else:
                    self.assertIn(SHORT, payload['input'])
                    final_candidates.append('final')
                    value = {'review_complete': True, 'findings': []}
                return {'output': [{'type': 'web_search_call', 'action': {'sources': []}}],
                        'test_value': value}
            if name == 'editorial_field_correction':
                return {'test_value': self.plan}
            if name == 'editorial_bluf_budget':
                return {'test_value': {'bluf': SHORT}}
            raise AssertionError(name)
        write_json(self.cache/'source-evidence.json', {'sources': docs})
        with patch('release_audit_loop.collect_source_evidence', return_value=docs), \
             patch('release_audit_loop.evidence_urls', return_value=urls):
            result = audit_and_correct(self.edition, self.cache, 'test-model',
                response, lambda r: json.dumps(r['test_value']), docs, urls, None)
        self.assertEqual(final_candidates, ['initial', 'final'])
        self.assertTrue(result['audit']['approved'])
        self.assertEqual(result['edition']['bluf'], SHORT)

    def test_rejected_final_audit_never_writes_approval(self):
        docs = self.documents
        urls = {canonical_url(s['url']) for s in self.edition['sources']}
        calls = []
        def response(payload):
            name = payload['text']['format']['name']; calls.append(name)
            if name == 'editorial_audit_structured':
                report = copy.deepcopy(self.report)
                if calls.count(name) == 2: report['findings'][0]['quote'] = SHORT
                return {'output':[{'type':'web_search_call','action':{'sources':[]}}],
                        'test_value':report}
            return {'test_value': self.plan if name=='editorial_field_correction' else {'bluf':SHORT}}
        write_json(self.cache/'source-evidence.json', {'sources':docs})
        with patch('release_audit_loop.collect_source_evidence', return_value=docs), \
             patch('release_audit_loop.evidence_urls', return_value=urls):
            with self.assertRaisesRegex(RuntimeError, 'Blocking findings remain'):
                audit_and_correct(self.edition,self.cache,'test-model',response,
                    lambda r:json.dumps(r['test_value']),docs,urls,None)
        self.assertFalse((self.cache/'approved.json').exists())
        self.assertEqual(calls.count('editorial_bluf_budget'),1)

if __name__ == '__main__': unittest.main()
