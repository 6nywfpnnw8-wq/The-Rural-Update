"""Shorter bounded audio can recover missing endings without lowering thresholds."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_audio as a
import release_verify as v
from release_core import digest,write_json

BODY=('The community review considers access quality staffing payment and ongoing operating costs before approving the next service commitment. '*8).strip()

class AdaptiveAudioTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.cache=Path(self.tmp.name);self.folder=self.cache/'audio-v2';self.folder.mkdir()
 def collect(self,transcribe,request=None):
  request=request or Mock(side_effect=lambda payload,*args:payload['input'].encode())
  with patch.object(a,'probe_audio',return_value=30),patch.object(a,'transcribe',side_effect=transcribe):
   result=a.collect_verified_segments(BODY,self.cache,request,'test','voice')
  return result,request
 def seed_exhausted_legacy(self):
  text=a.segments(BODY)[0];key=digest(json.dumps(a.speech_payload(text,'test','voice'),sort_keys=True))
  write_json(self.folder/(key+'-attempts.json'),{'attempts':2})
  for n in range(2):(self.folder/(key+f'-{n}.wav')).write_bytes(text.encode())
  return self.folder/(key+'-attempts.json')
 def test_short_initial_plan_preserves_every_word(self):
  (files,reports,_),calls=self.collect(lambda path,cache:path.read_text())
  self.assertGreater(len(files),1)
  self.assertTrue(all(len(c.args[0]['input'].split())<=90 for c in calls.call_args_list))
  self.assertEqual(' '.join(p.read_text() for p in files),BODY)
 def test_exhausted_parent_subdivided_without_reset(self):
  ledger=self.seed_exhausted_legacy();before=ledger.read_bytes()
  def asr(path,cache):
   text=path.read_text();return ' '.join(text.split()[:-12]) if len(text.split())>90 else text
  (files,reports,_),calls=self.collect(asr)
  self.assertEqual(ledger.read_bytes(),before)
  self.assertEqual(' '.join(p.read_text() for p in files),BODY)
  self.assertTrue(any(p['split_depth']==1 and p['passed'] for p in reports))
  self.assertTrue(all(len(c.args[0]['input'].split())<=90 for c in calls.call_args_list))
 def test_successful_repeat_reuses_valid_audio(self):
  self.collect(lambda p,c:p.read_text())
  request=Mock(side_effect=AssertionError('No extra speech request'))
  self.collect(lambda p,c:p.read_text(),request);request.assert_not_called()
 def test_failed_children_stay_blocked(self):
  self.seed_exhausted_legacy()
  with self.assertRaises(RuntimeError):self.collect(lambda p,c:'Unrelated cut off message')
 def test_no_single_sentence_truncation(self):
  with self.assertRaises(RuntimeError):a.split_failed_segment('A single sentence that must never be truncated.')
 def test_global_speech_budget_is_enforced(self):
  write_json(self.folder/'old-attempts.json',{'attempts':64})
  request=Mock()
  with self.assertRaises(RuntimeError):self.collect(lambda p,c:p.read_text(),request)
  request.assert_not_called()

class PublicQualityBindingTests(unittest.TestCase):
 def setUp(self):
  self.body='The complete approved narration reaches every final word.'
  self.script='Episode title: Test\nEdition date: 2026-10-17\n\n'+self.body+'\n'
  part={'index':0,'passed':True,'coverage':1.,'opening':1.,'ending':1.,'final_words':1.,'start_word':0,'end_word':len(self.body.split()),'normalized_text_sha256':digest(self.body)}
  self.q={'schema_version':2,'complete':True,'edition_date':'2026-10-17','audio_sha256':'audio-hash','script_sha256':digest(self.body),'expected_parts':1,'accepted_parts':1,'parts':[part],'ending_check':{'passed':True,'ending':1.,'final_words':1.}}
 def test_valid_source_partition(self):self.assertTrue(v.validate_audio_quality(self.q,self.script,'2026-10-17','audio-hash'))
 def test_wrong_script_is_rejected(self):
  with self.assertRaises(AssertionError):v.validate_audio_quality(self.q,self.script.replace('approved','unapproved'),'2026-10-17','audio-hash')
 def test_missing_final_words_rejected(self):
  self.q['parts'][0]['end_word']-=1
  self.q['parts'][0]['normalized_text_sha256']=digest(' '.join(self.body.split()[:-1]))
  with self.assertRaises(AssertionError):v.validate_audio_quality(self.q,self.script,'2026-10-17','audio-hash')
 def test_forged_complete_flag_without_segments_rejected(self):
  self.q['parts']=[]
  with self.assertRaises(AssertionError):v.validate_audio_quality(self.q,self.script,'2026-10-17','audio-hash')
 def test_failed_ending_rejected(self):
  self.q['ending_check']['passed']=False
  with self.assertRaises(AssertionError):v.validate_audio_quality(self.q,self.script,'2026-10-17','audio-hash')
 def test_other_mp3_is_rejected(self):
  with self.assertRaises(AssertionError):v.validate_audio_quality(self.q,self.script,'2026-10-17','different-audio')

if __name__=='__main__':unittest.main()
