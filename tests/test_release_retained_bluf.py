"""Offline retained-material recovery, including counter and audit boundaries."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import release_retained_bluf as rb
import release_research as sr
import release_prose as prose
import release_sectioned_narration as sn


class RetainedBlufTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name) / rb.DAY
        self.cache.mkdir()
        self.policy_root = Path(tmp.name) / 'policies'
        self.policy_root.mkdir()
        self.folder = self.cache / rb.ENGINE
        self.identity = 'retained-fixture'
        self.before_url = 'https://www.oklahoma.gov/hwtc/rural-health-transformation-program.html'
        self.after_url = 'https://www.oklahoma.gov/rhtp/rhtp-funding-recipients.html'
        self.report = {'edition_date': rb.DAY, 'bluf': 'A retained summary ending if'}
        self.sources = [{'id': 'oklahoma-rhtp-program', 'url': self.before_url,
                         'title': 'Original source', 'published_date': None}]
        stages = {'discovery': {'notes': 'Retained source: ' + self.after_url,
                               'web_search_items': [{'type': 'web_search_call'}]},
                  'sources': {'sources': self.sources}, 'reporting': {'edition': self.report}}
        for name, value in stages.items():
            sr._save(self.folder / (name + '.json'), self.identity, value)
        self.sid = sn.fingerprint({'method': sn.METHOD, 'identity': self.identity,
                                   'model': 'gpt-5-mini', 'reporting': self.report, 'plan': sn.SECTION_PLAN})
        self.work = self.folder / sn.METHOD / self.sid
        sn._write_ledger(self.work / 'attempts.json', {'identity': self.sid, 'requests': 6,
                         'attempts': {'opening-None': 2, 'bluf-None': 4}, 'publication_authorized': False})
        sr._save(self.work / 'opening-None.json', self.sid, {'section': 'opening-None',
                 'format': prose.FORMAT, 'result': {'text': ' '.join(['Opening'] * 59 + ['ending.'])}})
        stage_hashes = {n: rb._hash((self.folder / (n + '.json')).read_bytes()) for n in stages}
        self.write('attempts.json', {'attempts': 2})
        self.write('narration-structural-resume-used.json', {'identity': self.identity,
                   'section_identity': self.sid, 'section': 'bluf-None', 'maximum_extra_section_requests': 1,
                   'publication_authorized': False, 'retained_stage_sha256': stage_hashes})
        self.write('narration-structural-followup-used.json', {'identity': self.identity,
                   'section_identity': self.sid, 'section': 'bluf-None',
                   'maximum_additional_section_requests': 1, 'publication_authorized': False})
        self.prefix = ' '.join(['Supported'] * 154 + ['ending.'])
        text = self.prefix + ' Recommendations and operational implications:' + ' trailing' * 62 + ' done.'
        self.assertEqual(len(text.split()), 222)
        candidate = {'text': text}
        candidate_sha = rb._hash(json.dumps(candidate, sort_keys=True, ensure_ascii=False).encode())
        self.candidate_path = self.cache / 'section-candidates' / (candidate_sha + '.json')
        self.write(str(self.candidate_path.relative_to(self.cache)), {'section': 'bluf-None',
                   'candidate': candidate, 'publication_authorized': False})
        self.write('api-responses.json', {'responses': [{'run_id': rb.FAILURE_RUN,
                   'stage': 'narration_section', 'status': 'incomplete', 'incomplete_reason': 'max_output_tokens',
                   'requested_output_limit': 4000, 'input_tokens': 0, 'output_tokens': 0,
                   'reasoning_tokens': 0, 'visible_characters': 0}]})
        self.write('validation-latest.json', {'run_id': rb.FAILURE_RUN, 'passed': False, 'rule': 'api_response'})
        self.write('validation-narration-sections.json', {'sections': [{'section': 'bluf-None',
                   'attempt': 2, 'word_count': 222, 'characters': len(text), 'passed': False,
                   'rule': 'section_word_count', 'run_id': '40084542457', 'publication_authorized': False}]})
        paths = ['attempts.json', 'narration-structural-resume-used.json',
                 'narration-structural-followup-used.json']
        paths += [rb.ENGINE + '/' + n + '.json' for n in stages]
        paths += [str((self.work / n).relative_to(self.cache)) for n in ('attempts.json', 'opening-None.json')]
        self.original = {name: (self.cache / name).read_bytes() for name in paths}
        self.policy = {'edition_date': rb.DAY, 'failure_run_id': int(rb.FAILURE_RUN), 'maximum_recoveries': 1,
                       'additional_bluf_requests': 0, 'additional_research_attempts': 0,
                       'publication_authorized': False, 'section': 'bluf-None',
                       'method': 'complete-sentence-prefix', 'model': 'gpt-5-mini',
                       'identity': self.identity, 'section_identity': self.sid,
                       'candidate_sha256': candidate_sha, 'retained_characters': len(self.prefix),
                       'retained_text_sha256': rb._hash(self.prefix.encode()),
                       'original_web_bluf_sha256': rb._hash(self.report['bluf'].encode()),
                       'retained_file_sha256': {p: rb._hash(v) for p, v in self.original.items()},
                       'citation_replacement': {'source_id': 'oklahoma-rhtp-program',
                           'before_url': self.before_url, 'after_url': self.after_url, 'title': 'Reviewed funding recipients'}}
        self.save_policy()
        self.plan = {'maximum_retained_bluf_recoveries': 1}

    def write(self, name, value):
        path = self.cache / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def save_policy(self):
        (self.policy_root / rb.POLICY).write_text(json.dumps(self.policy))

    def reserve(self):
        return rb.reserve(self.cache, rb.DAY, self.plan, self.policy_root, rb.ENGINE,
                          sr._cached, lambda values: self.assertEqual(values['reporting']['edition'], self.report))

    def test_local_recovery_is_single_use_and_keeps_every_original_record(self):
        self.assertTrue(self.reserve())
        self.assertFalse(self.reserve())
        for name, data in self.original.items():
            self.assertEqual((self.cache / name).read_bytes(), data)
        section = sr._cached(self.work / 'bluf-None.json', self.sid)
        self.assertEqual(section['result']['text'], self.prefix)
        self.assertFalse((self.cache / 'approved.json').exists())

    def test_only_eight_pending_sections_use_existing_allowances(self):
        self.assertTrue(self.reserve())
        def respond(payload):
            self.assertNotIn('section bluf', payload['instructions'])
            self.assertNotIn('tools', payload)
            self.assertNotIn('pattern', payload['text']['format']['schema']['properties']['text'])
            target = int(payload['instructions'].split('Target ')[1].split(' words')[0])
            value = {'text': ' '.join(['Supported'] * (target - 1) + ['ending.'])}
            return {'status': 'completed', 'output': [{'type': 'message', 'content': [
                    {'type': 'output_text', 'text': json.dumps(value)}]}]}
        send = Mock(side_effect=respond)
        result = sn.generate_sections(self.report, 'gpt-5-mini', self.folder, self.identity,
                                      send, sr._text, sr._cached, sr._save)
        self.assertEqual(send.call_count, 8)
        self.assertEqual(result['podcast']['bluf'], self.prefix)
        state = json.loads((self.work / 'attempts.json').read_text())
        self.assertEqual(state['requests'], 14)
        self.assertEqual(state['attempts']['bluf-None'], 4)
        self.assertEqual((self.cache / 'attempts.json').read_bytes(), self.original['attempts.json'])

    def test_web_edit_and_citation_are_derived_without_mutating_report(self):
        self.assertTrue(self.reserve())
        edition = {**copy.deepcopy(self.report), 'sources': copy.deepcopy(self.sources),
                   'podcast': {'bluf': self.prefix}}
        before = copy.deepcopy(edition)
        derived = rb.apply(edition, self.cache, self.policy_root)
        self.assertEqual(edition, before)
        self.assertEqual(derived['bluf'], self.prefix)
        self.assertEqual(derived['sources'][0]['url'], self.after_url)
        self.assertEqual((self.folder / 'reporting.json').read_bytes(),
                         self.original[rb.ENGINE + '/reporting.json'])
        self.assertFalse((self.cache / 'audit.json').exists())
        self.assertFalse((self.cache / 'approved.json').exists())

    def test_changed_retained_reporting_stops_before_recovery(self):
        path = self.folder / 'reporting.json'
        path.write_text(path.read_text() + ' ')
        with self.assertRaises(RuntimeError):
            self.reserve()
        self.assertFalse((self.cache / rb.MARKER).exists())

    def test_wrong_response_or_spent_state_cannot_open_another_attempt(self):
        responses = json.loads((self.cache / 'api-responses.json').read_text())
        responses['responses'][0]['output_tokens'] = 1
        self.write('api-responses.json', responses)
        self.assertFalse(self.reserve())
        self.assertFalse((self.cache / rb.MARKER).exists())

    def test_corrupt_candidate_or_unreviewed_extraction_fails(self):
        candidate = json.loads(self.candidate_path.read_text())
        candidate['candidate']['text'] += ' changed'
        self.candidate_path.write_text(json.dumps(candidate))
        with self.assertRaises(RuntimeError):
            self.reserve()
        self.assertFalse((self.cache / rb.MARKER).exists())

    def test_rejected_audit_cannot_be_reopened(self):
        self.write('audit.json', {'approved': False})
        self.assertFalse(self.reserve())

    def test_citation_outside_retained_context_is_rejected(self):
        self.policy['citation_replacement']['after_url'] = 'https://www.oklahoma.gov/unseen.html'
        self.save_policy()
        with self.assertRaises(RuntimeError):
            self.reserve()
        self.assertFalse((self.cache / rb.MARKER).exists())


if __name__ == '__main__':
    unittest.main()
