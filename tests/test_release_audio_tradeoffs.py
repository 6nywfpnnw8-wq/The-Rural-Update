"""Retained orthographic differences cannot hide real missing ending words."""
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from release_audio import tokens, coverage, ending_check, inspect_ending, NORMALIZATION_VERSION
from release_core import digest, read_json, write_json


class ObservedSpeechOrthographyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = read_json(Path(__file__).parent / 'fixtures/audio-orthography-2026-10-26.json')
        self.expected = self.fixture['expected'];self.recognized = self.fixture['recognized']

    def test_retained_failure_passes_without_provider_calls_or_script_changes(self):
        self.assertEqual(digest(self.expected), self.fixture['expected_sha256'])
        with patch.object(urllib.request, 'urlopen') as provider:
            result = coverage(self.expected, self.recognized)
        provider.assert_not_called()
        self.assertEqual(tokens(self.expected), tokens(self.recognized))
        self.assertEqual(result, {'coverage': 1.0, 'opening': 1.0, 'ending': 1.0,
                                  'final_words': 1.0, 'passed': True})
        self.assertTrue(ending_check(self.expected, self.recognized)['passed'])

    def test_tradeoff_hyphenation_keeps_singular_and_plural_distinct(self):
        for value in ('tradeoff', 'trade-off', 'trade off'):
            self.assertEqual(tokens(value), ['trade', 'off'])
        for value in ('tradeoffs', 'trade-offs', 'trade offs'):
            self.assertEqual(tokens(value), ['trade', 'offs'])
        self.assertNotEqual(tokens('tradeoff'), tokens('tradeoffs'))

    def test_only_observed_whole_word_spellings_are_rewritten(self):
        self.assertEqual(tokens('forgo'), tokens('forego'))
        self.assertEqual(tokens('foregone foregoing tradeoffish'), ['foregone', 'foregoing', 'tradeoffish'])

    def test_missing_last_word_or_material_ending_word_still_fails(self):
        for changed in (self.recognized.removesuffix(' benefits.') + '.',
                        self.recognized.replace('forego', ''),
                        self.recognized.replace('forego', 'fund'),
                        self.recognized.replace('benefits', 'closures')):
            with self.subTest(changed=changed):
                self.assertFalse(coverage(self.expected, changed)['passed'])
                self.assertFalse(ending_check(self.expected, changed)['passed'])

    def test_truncated_retained_passage_still_fails(self):
        truncated = self.recognized.split('or require')[0]
        self.assertFalse(coverage(self.expected, truncated)['passed'])
        self.assertFalse(ending_check(self.expected, truncated)['passed'])

    def test_old_ending_result_reuses_cached_asr_without_a_paid_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);audio = root / 'episode.mp3';audio.write_bytes(b'existing-episode')
            tail = root / 'inspection-tail.wav';tail.write_bytes(b'existing-tail')
            write_json(root / ('asr-' + digest(tail.read_bytes()) + '.json'),
                       {'audio_sha256': digest(tail.read_bytes()), 'text': self.recognized})
            write_json(root / ('ending-' + digest(audio.read_bytes()) + '.json'),
                       {'script_sha256': digest(self.expected), 'normalization_version': 3,
                        'result': {'passed': False}})
            with patch('release_audio.run'), patch.object(urllib.request, 'urlopen') as provider:
                result = inspect_ending(audio, self.expected, root)
            provider.assert_not_called()
            self.assertEqual(result['normalization_version'], NORMALIZATION_VERSION)
            self.assertTrue(result['result']['passed'])


if __name__ == '__main__':unittest.main()
