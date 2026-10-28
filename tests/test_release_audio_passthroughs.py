"""The October 28 retained recordings end with the complete plural compound."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from release_audio import tokens,coverage,ending_check,collect_verified_segments,speech_payload
from release_core import digest,write_json,read_json

EXPECTED='The national announcement does not by itself confirm Oklahoma-executed implementation terms, which are necessary to change pharmacy accounting or operational practices in state Medicaid, MCO contracting or 340B passthroughs.'
RECOGNIZED=(
    'The national announcement does not by itself confirm Oklahoma-executed implementation terms which are necessary to change pharmacy accounting or operational practices in state Medicaid, MCO contracting, or 340B pass-throughs.',
    'The national announcement does not by itself confirm Oklahoma executed implementation terms, which are necessary to change pharmacy accounting or operational practices in state Medicaid, MCO contracting, or 340B pass-throughs.',
)


class PassthroughOrthographyTests(unittest.TestCase):
    def test_both_retained_transcripts_match_without_lower_thresholds(self):
        for actual in RECOGNIZED:
            with self.subTest(actual=actual):
                self.assertEqual(tokens(EXPECTED),tokens(actual))
                result=coverage(EXPECTED,actual)
                self.assertTrue(result['passed'])
                self.assertEqual(result['coverage'],1.0)
                self.assertEqual(result['final_words'],1.0)
                self.assertTrue(ending_check(EXPECTED,actual)['passed'])

    def test_singular_and_plural_spaced_and_hyphenated_forms(self):
        for suffix in ('','s'):
            for form in ('passthrough','pass-through','pass through'):
                self.assertEqual(tokens(form+suffix),['pass','through'+suffix])

    def test_number_and_unrelated_words_are_preserved(self):
        self.assertNotEqual(tokens('passthrough'),tokens('passthroughs'))
        self.assertEqual(tokens('nonpassthroughs passthroughsplus'),
                         ['nonpassthroughs','passthroughsplus'])

    def test_incomplete_or_changed_final_compound_still_fails(self):
        for ending in ('','pass','throughs','pass-through','deductions'):
            actual=RECOGNIZED[0].replace('pass-throughs',ending)
            with self.subTest(ending=ending):
                self.assertFalse(coverage(EXPECTED,actual)['passed'])
                self.assertFalse(ending_check(EXPECTED,actual)['passed'])

    def test_exhausted_payload_reuses_existing_audio_and_asr_without_provider_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp);folder=cache/'audio-v2';folder.mkdir()
            key=digest(json.dumps(speech_payload(EXPECTED,'model','voice'),sort_keys=True))
            ledger=folder/(key+'-attempts.json')
            write_json(ledger,{'attempts':2})
            retained=[]
            for attempt,actual in enumerate(RECOGNIZED):
                audio=b'retained-speech-'+str(attempt).encode()
                part=folder/(key+f'-{attempt}.wav');part.write_bytes(audio)
                asr=folder/('asr-'+digest(audio)+'.json')
                write_json(asr,{'audio_sha256':digest(audio),'text':actual})
                retained.extend([part,asr])
            before={p:p.read_bytes() for p in [ledger,*retained]}
            with patch('release_audio.urllib.request.urlopen',side_effect=AssertionError('Network forbidden')) as network:
                def no_speech(*args):raise AssertionError('Speech request forbidden')
                accepted,reports,count=collect_verified_segments(EXPECTED,cache,no_speech,'model','voice')
            network.assert_not_called()
            self.assertEqual(count,1)
            self.assertEqual(accepted,[retained[0]])
            self.assertEqual(len(reports),1)
            self.assertTrue(reports[0]['passed'])
            self.assertEqual(reports[0]['end_word'],len(EXPECTED.split()))
            self.assertEqual(read_json(ledger)['attempts'],2)
            self.assertEqual(before,{p:p.read_bytes() for p in before})


if __name__=='__main__':unittest.main()
