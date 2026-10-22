"""Timing recovery never replaces script-coverage or final-narration validation."""
import copy
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from release_audio_timing import timing_plan,encoder_arguments,validate_output_duration
import release_audio as audio
from release_core import read_json
from test_release import fixture


class TimingTests(unittest.TestCase):
    def test_actual_observed_long_episode(self):
        plan=timing_plan(940.9)
        self.assertAlmostEqual(plan['tempo_factor'],1.12011905)
        self.assertAlmostEqual(plan['expected_output_seconds'],840,places=4)
        self.assertFalse(plan['trim_applied']);self.assertFalse(plan['padding_applied'])
        validate_output_duration(840.048,plan)

    def test_existing_acceptable_duration_unchanged(self):
        for seconds in (540.,700.,899.,900.):
            plan=timing_plan(seconds)
            self.assertEqual(plan['tempo_factor'],1.)
            self.assertEqual(encoder_arguments(plan),[])
            validate_output_duration(seconds,plan)

    def test_short_audio_is_not_padded_or_approved(self):
        plan=timing_plan(500.)
        self.assertEqual(encoder_arguments(plan),[])
        with self.assertRaisesRegex(RuntimeError,'9 to 15'):validate_output_duration(500.,plan)

    def test_extreme_slow_narration_stays_blocked(self):
        with self.assertRaisesRegex(RuntimeError,'15 percent'):timing_plan(1000.)

    def test_invalid_source_duration_rejected(self):
        for seconds in (0.,-1.,math.nan,math.inf):
            with self.subTest(seconds=seconds):
                with self.assertRaises(ValueError):timing_plan(seconds)

    def test_wrong_encoded_duration_is_not_approved(self):
        with self.assertRaisesRegex(RuntimeError,'decoded segments'):
            validate_output_duration(700.,timing_plan(940.9))

    def test_output_still_must_obey_hard_limits(self):
        with self.assertRaisesRegex(RuntimeError,'9 to 15'):
            validate_output_duration(900.1,timing_plan(900.))

    def test_encoder_uses_tempo_not_cutoff_or_sample_rate_change(self):
        args=encoder_arguments(timing_plan(940.9))
        self.assertEqual(args,['-af','atempo=1.12011905'])
        self.assertFalse(any(x in ' '.join(args) for x in ['atrim','asetrate','-t ','-to ','-ss ']))

    def test_invalid_factor_cannot_reach_encoder(self):
        for factor in (.9,1.2,math.nan,math.inf):
            with self.assertRaises(ValueError):encoder_arguments({'tempo_factor':factor})


class AudioTimingIntegrationTests(unittest.TestCase):
    def test_final_ending_gate_remains_mandatory(self):
        self.run_build(False)

    def test_full_script_record_is_bound_after_timing(self):
        self.run_build(True)

    def run_build(self,ending_ok):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'audio-v2';folder.mkdir()
            part=folder/'verified.wav';part.write_bytes(b'synthetic')
            pcm=folder/'pcm-0.wav'
            with wave.open(str(pcm),'wb') as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000)
                w.writeframes(b'\0\0'*24000)
            output=root/'episode.mp3';e=fixture();before=copy.deepcopy(e)
            request=Mock(side_effect=AssertionError('No new speech generation'))
            def command(args):
                if args[-1].endswith('.mp3'):Path(args[-1]).write_bytes(b'ID3synthetic')
            fake_plan={'source_duration_seconds':940.9,'tempo_factor':1.12011905,
                       'expected_output_seconds':840.,'filter':'atempo',
                       'trim_applied':False,'padding_applied':False,'maximum_tempo_factor':1.15}
            tail=Mock(return_value={'result':{'passed':ending_ok,'ending':1. if ending_ok else .2,'final_words':1. if ending_ok else 0.}})
            with patch.object(audio,'collect_verified_segments',return_value=([part],[{'passed':True}],1)), \
                 patch.object(audio,'run',side_effect=command), \
                 patch.object(audio,'probe_audio',return_value=840.048), \
                 patch.object(audio,'inspect_ending',tail), \
                 patch('release_audio_timing.timing_plan',return_value=fake_plan):
                if ending_ok:
                    audio.build_audio(e,root,output,request)
                    report=read_json(root/'audio-quality.json')
                    self.assertTrue(report['complete'])
                    self.assertEqual(report['timing_adjustment'],fake_plan)
                else:
                    with self.assertRaisesRegex(RuntimeError,'closing narration'):
                        audio.build_audio(e,root,output,request)
                    self.assertFalse(output.exists())
                    self.assertFalse((root/'audio-quality.json').exists())
            tail.assert_called_once();request.assert_not_called();self.assertEqual(e,before)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'Requires FFmpeg')
class ActualEncoderTest(unittest.TestCase):
    def test_short_synthetic_signal_is_not_cut_at_tempo_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'tempo.wav';plan=timing_plan(940.9)
            subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','sine=frequency=440:duration=3',
                *encoder_arguments(plan),'-ar','24000','-ac','1',str(output)],check=True,timeout=20)
            with wave.open(str(output),'rb') as w:duration=w.getnframes()/w.getframerate()
            self.assertLess(abs(duration-3/plan['tempo_factor']),.08)

if __name__=='__main__':unittest.main()
