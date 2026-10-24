"""Long reviewed sentences may split at explicit clauses without changing the script."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_audio as audio

BLUF='; '.join(' '.join(['Verified']*30+[f'clause{i}']) for i in range(5))+'.'


class ClauseAudioTests(unittest.TestCase):
    def test_long_sentence_is_partitioned_without_losing_any_word_or_qualifier(self):
        self.assertEqual(len(BLUF.split()),155)
        parts=audio.segments(BLUF,max_words=90,max_parts=32,allow_clauses=True)
        self.assertEqual(' '.join(parts),BLUF)
        self.assertTrue(all(len(part.split())<=90 for part in parts))
        self.assertEqual(len(parts),3)
        with self.assertRaises(ValueError):audio.segments(BLUF,max_words=90)

    def test_no_arbitrary_word_cut_or_extra_depth(self):
        with self.assertRaises(ValueError):
            audio.segments(' '.join(['word']*155)+'.',max_words=90,allow_clauses=True)
        with self.assertRaises(RuntimeError):audio.split_failed_segment('One complete short sentence.')
        children=audio.split_failed_segment('; '.join(['A complete clause']*4)+'.')
        self.assertEqual(' '.join(children),'; '.join(['A complete clause']*4)+'.')

    def test_verified_clause_audio_is_reused_and_counters_are_not_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)
            request=Mock(side_effect=lambda payload,*args:payload['input'].encode())
            with patch.object(audio,'probe_audio',return_value=30),patch.object(audio,'transcribe',side_effect=lambda path,cache:path.read_text()):
                files,reports,count=audio.collect_verified_segments(BLUF,cache,request,'model','voice')
                before={p:p.read_bytes() for p in (cache/'audio-v2').glob('*-attempts.json')}
                other=Mock(side_effect=AssertionError('No repeated speech request'))
                again,_,_=audio.collect_verified_segments(BLUF,cache,other,'model','voice')
            self.assertEqual(' '.join(p.read_text() for p in files),BLUF)
            self.assertEqual(files,again);other.assert_not_called()
            self.assertEqual(request.call_count,count)
            self.assertTrue(all(row['passed'] for row in reports))
            self.assertTrue(all(p.read_bytes()==value for p,value in before.items()))


if __name__=='__main__':unittest.main()
