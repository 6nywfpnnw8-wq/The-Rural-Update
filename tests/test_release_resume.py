"""Fault tests: a retained draft is not an approved edition."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from test_release import fixture, DATE
from release_core import write_json
from release_resume import take_style_recovery


class StyleRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name)
        self.candidate = fixture(); self.candidate['bluf'] = 'Review\u2014then act.'
        self.save(self.candidate)
        write_json(self.cache / 'attempts.json', {'attempts': 2})

    def snapshot(self, stage, candidate, urls=None):
        fingerprint = hashlib.sha256(json.dumps(candidate, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        relative = f'candidates/{stage}-{fingerprint[:16]}.json'
        write_json(self.cache / relative, {'schema_version':1,'edition_date':DATE,
                   'stage':stage,'redacted':False,'publication_authorized':False,
                   'candidate_sha256':fingerprint,'candidate':candidate,
                   'retrieved_urls':urls or []})
        return {'retained':True,'file':relative,'redacted':False,'candidate_sha256':fingerprint}

    def save(self, e):
        saved = self.snapshot('content', e)
        self.snapshot('generated', e, [s['url'] for s in e['sources']])
        write_json(self.cache / 'validation-content.json', {'edition_date':DATE,
                   'stage':'content','passed':False,'rule':'punctuation','snapshot':saved})

    def test_reuses_only_typography_without_approval_or_counter_reset(self):
        candidate, urls = take_style_recovery(self.cache, DATE)
        self.assertEqual(candidate['bluf'], 'Review - then act.')
        self.assertEqual(candidate['sources'], self.candidate['sources'])
        self.assertEqual(len(urls), 5)
        self.assertEqual(json.loads((self.cache/'attempts.json').read_text()), {'attempts':2})
        self.assertFalse((self.cache/'approved.json').exists())
        self.assertFalse(json.loads((self.cache/'style-recovery-attempt.json').read_text())['publication_authorized'])

    def test_only_one_reserved_audit_per_date(self):
        self.assertIsNotNone(take_style_recovery(self.cache, DATE))
        self.assertIsNone(take_style_recovery(self.cache, DATE))

    def test_no_candidate_is_not_invented(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(take_style_recovery(Path(td), DATE))
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_other_date_not_reused(self):
        self.assertIsNone(take_style_recovery(self.cache, '2026-10-12'))

    def test_other_rejection_not_reused(self):
        p=self.cache/'validation-content.json'; data=json.loads(p.read_text())
        data['rule']='evidence_audit';write_json(p,data)
        self.assertIsNone(take_style_recovery(self.cache, DATE))

    def test_redacted_snapshot_rejected(self):
        p=next((self.cache/'candidates').glob('content-*.json'));data=json.loads(p.read_text())
        data['redacted']=True;write_json(p,data)
        self.assertIsNone(take_style_recovery(self.cache, DATE))

    def test_tampered_snapshot_rejected(self):
        p=next((self.cache/'candidates').glob('content-*.json'));data=json.loads(p.read_text())
        data['candidate']['title']='Tampered';write_json(p,data)
        self.assertIsNone(take_style_recovery(self.cache, DATE))

    def test_generated_provenance_must_match_facts(self):
        for p in (self.cache/'candidates').glob('generated-*.json'):p.unlink()
        other=copy.deepcopy(self.candidate);other['stories'][0]['title']='Different facts'
        self.snapshot('generated',other,[s['url'] for s in other['sources']])
        self.assertIsNone(take_style_recovery(self.cache, DATE))

    def test_missing_original_retrieval_evidence_rejected(self):
        for p in (self.cache/'candidates').glob('generated-*.json'):p.unlink()
        self.assertIsNone(take_style_recovery(self.cache, DATE))

    def test_placeholder_remains_blocked(self):
        e=copy.deepcopy(self.candidate);e['bluf']+=' TBD'
        self.save(e)
        self.assertIsNone(take_style_recovery(self.cache, DATE))

    def test_short_narration_remains_blocked(self):
        e=copy.deepcopy(self.candidate);e['podcast']['opening']='Too short.'
        self.save(e)
        self.assertIsNone(take_style_recovery(self.cache, DATE))

    def test_normalization_cannot_rewrite_url(self):
        e=copy.deepcopy(self.candidate);e['sources'][0]['url']+='\u2014test'
        self.save(e)
        self.assertIsNone(take_style_recovery(self.cache, DATE))

    def test_unsafe_reference_path_rejected(self):
        p=self.cache/'validation-content.json';data=json.loads(p.read_text())
        data['snapshot']['file']='candidates/../outside.json';write_json(p,data)
        self.assertIsNone(take_style_recovery(self.cache, DATE))

if __name__=='__main__':unittest.main()
