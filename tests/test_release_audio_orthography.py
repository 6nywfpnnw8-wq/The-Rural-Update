"""The October 20 rejection was a compound-word boundary, not missing tail text."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from release_audio import tokens,coverage,ending_check

EXPECTED='Why it matters: if finalized as proposed, states would face limits on commonly used provider-tax strategies and related supplemental-payment constructs that have supported Medicaid funding for rural hospitals. Oklahoma’s exposure depends on state tax structures, existing supplemental-payment contracts and managed-care passthrough arrangements.'
RECOGNIZED='Why it matters: If finalized as proposed, states would face limits on commonly used provider tax strategies and related supplemental payment constructs that have supported Medicaid funding for rural hospitals. Oklahoma’s exposure depends on state tax structures, existing supplemental payment contracts, and managed care pass-through arrangements.'

class AudioOrthographyTests(unittest.TestCase):
    def test_actual_oct20_transcription_passes_without_lower_threshold(self):
        result=coverage(EXPECTED,RECOGNIZED)
        self.assertTrue(result['passed']);self.assertEqual(result['coverage'],1.0)
        self.assertEqual(result['final_words'],1.0)
    def test_spaced_compound_equivalent(self):self.assertEqual(tokens('passthrough'),tokens('pass through'))
    def test_hyphenated_compound_equivalent(self):self.assertEqual(tokens('passthrough'),tokens('pass-through'))
    def test_straight_and_curly_apostrophes_equivalent(self):self.assertEqual(tokens("Oklahoma's"),tokens('Oklahoma’s'))
    def test_real_mid_sentence_cutoff_still_fails(self):
        self.assertFalse(coverage(EXPECTED,RECOGNIZED.split('Oklahoma')[0])['passed'])
    def test_missing_final_word_still_fails(self):
        self.assertFalse(coverage(EXPECTED,RECOGNIZED.replace(' arrangements.','.'))['passed'])
    def test_missing_compound_half_still_fails(self):
        self.assertFalse(coverage(EXPECTED,RECOGNIZED.replace('pass-through','pass'))['passed'])
    def test_unrelated_compounds_are_not_fuzzily_merged(self):
        self.assertNotEqual(tokens('managedcare'),tokens('managed care'))
    def test_ending_match_preserves_complete_closing(self):self.assertTrue(ending_check(EXPECTED,RECOGNIZED)['passed'])
    def test_ending_match_rejects_lost_last_word(self):
        self.assertFalse(ending_check(EXPECTED,RECOGNIZED.replace(' arrangements.','.'))['passed'])

if __name__=='__main__':unittest.main()
