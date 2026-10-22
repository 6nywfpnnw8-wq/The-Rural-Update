"""A documented hyphenation variant must not resemble a missing spoken word."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from release_audio import tokens,coverage,ending_check,inspect_ending,NORMALIZATION_VERSION
from release_core import digest,write_json

EXPECTED='This briefing sets immediate operational priorities for Oklahoma rural hospital leaders centered on telehealth claims reconciliation, state confirmation of GENEROUS participation and modeling provider-tax downside while formalizing RHTP subaward terms and sustainability planning.'
RECOGNIZED='This briefing sets immediate operational priorities for Oklahoma rural hospital leaders centered on telehealth claims reconciliation, state confirmation of generous participation, and modeling provider tax downside, while formalizing RHTP sub-award terms and sustainability planning.'

class SubawardOrthographyTests(unittest.TestCase):
    def test_observed_complete_passage_matches_exactly_after_normalization(self):
        self.assertEqual(tokens(EXPECTED),tokens(RECOGNIZED))
        result=coverage(EXPECTED,RECOGNIZED)
        self.assertTrue(result['passed'])
        self.assertEqual(result['final_words'],1.0)

    def test_singular_hyphenated_and_spaced_forms(self):
        for value in ('subaward','sub-award','sub award'):
            self.assertEqual(tokens(value),['sub','award'])

    def test_plural_hyphenated_and_spaced_forms(self):
        for value in ('subawards','sub-awards','sub awards'):
            self.assertEqual(tokens(value),['sub','awards'])

    def test_plural_not_collapsed_into_singular(self):
        self.assertNotEqual(tokens('subaward'),tokens('subawards'))

    def test_unrelated_words_not_rewritten(self):
        self.assertEqual(tokens('nonsubaward subawarded'),['nonsubaward','subawarded'])

    def test_missing_last_word_still_fails(self):
        text=RECOGNIZED.removesuffix(' planning.')+'.'
        self.assertFalse(coverage(EXPECTED,text)['passed'])
        self.assertFalse(ending_check(EXPECTED,text)['passed'])

    def test_missing_sub_prefix_still_fails(self):
        self.assertFalse(coverage(EXPECTED,RECOGNIZED.replace('sub-award','award'))['passed'])

    def test_missing_award_word_still_fails(self):
        self.assertFalse(coverage(EXPECTED,RECOGNIZED.replace('sub-award','sub'))['passed'])

    def test_changed_final_content_word_still_fails(self):
        self.assertFalse(coverage(EXPECTED,RECOGNIZED.replace('sustainability','closure'))['passed'])

    def test_truncated_original_remains_rejected(self):
        self.assertFalse(coverage(EXPECTED,RECOGNIZED.split('while')[0])['passed'])

    def test_old_assembled_ending_check_is_recomputed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);audio=root/'test.mp3';audio.write_bytes(b'test-audio')
            saved=root/('ending-'+digest(audio.read_bytes())+'.json')
            write_json(saved,{'script_sha256':digest(EXPECTED),'normalization_version':2,
                             'result':{'passed':False}})
            with patch('release_audio.run'),patch('release_audio.transcribe',return_value=RECOGNIZED) as transcribe:
                report=inspect_ending(audio,EXPECTED,root)
            transcribe.assert_called_once()
            self.assertEqual(report['normalization_version'],NORMALIZATION_VERSION)
            self.assertTrue(report['result']['passed'])

if __name__=='__main__':unittest.main()
