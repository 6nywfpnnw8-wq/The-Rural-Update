"""Fault tests for narration completeness and sustainable generation limits."""
import json,sys,tempfile,unittest,copy
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from release_audio import coverage,ending_check,segments,inspect_ending
from release_editorial import take_reviewed_recovery
from release_narration import WORD_BOUNDS,bounded_podcast_schema,generation_schema
from release_core import SCHEMA,digest
from jsonschema import Draft202012Validator,ValidationError

class AudioCompletenessTests(unittest.TestCase):
 def test_complete_passes(self):
  s='The financing question is distinct from the operational question. This concludes the rural update for October sixteenth twenty twenty six.'
  self.assertTrue(coverage(s,s)['passed'])
 def test_final_sentence_missing_fails(self):
  s='The financing question is distinct from the operational question. This concludes the rural update for October sixteenth twenty twenty six.'
  self.assertFalse(coverage(s,s.split('This concludes')[0])['passed'])
 def test_mid_sentence_cutoff_fails(self):
  s='The review must reach the complete final sentence before the episode is approved for publication.'
  self.assertFalse(ending_check(s,'The review must reach the complete final')['passed'])
 def test_numbers_and_punctuation(self):
  self.assertTrue(ending_check('This concludes The Rural Update for October sixteenth, twenty twenty-six.','This concludes the Rural Update for October 16, 2026.')['passed'])
 def test_segmentation_preserves_all_words(self):
  s=' '.join('The complete sentence number '+str(i)+' ends here.' for i in range(100))
  p=segments(s);self.assertEqual(' '.join(p),s)
  self.assertTrue(all(len(x.split())<=170 for x in p))
 def test_missing_chunk_detected_by_coverage(self):
  s='This policy changes financing requirements. Distinct operating examples require evidence. Finally the episode reaches its closing statement.'
  self.assertFalse(coverage(s,s.replace('Distinct operating examples require evidence.',''))['passed'])
 def test_unreasonable_long_sentence_rejected(self):
  with self.assertRaises(ValueError):segments('word '*171)
 def test_empty_rejected(self):self.assertFalse(coverage('closing statement','')['passed'])
 def test_unrelated_tail_rejected(self):self.assertFalse(ending_check('This is the complete conclusion','Audio cuts off in an unrelated phrase')['passed'])
 def test_generated_plan_still_requires_hash_match(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Path(tmp);(r/'2026-10-16.json').write_text(json.dumps({'schema_version':1,'edition_date':'2026-10-16','publication_authorized':False,'base_stage':'generated','base_snapshot':'candidates/generated-wrong.json'}))
   with patch('release_editorial.REVIEW_ROOT',r):
    with self.assertRaises(ValueError):take_reviewed_recovery(r/'cache','2026-10-16')
 def test_ending_cache_cannot_approve_another_script(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Path(tmp);audio=r/'audio.mp3';audio.write_bytes(b'synthetic-test-only')
   old={'audio_sha256':digest(audio.read_bytes()),'script_sha256':digest('different script'),'result':{'passed':True},'recognized_tail':'old'}
   (r/('ending-'+digest(audio.read_bytes())+'.json')).write_text(json.dumps(old))
   with patch('release_audio.run'),patch('release_audio.transcribe',return_value='A different unrelated tail') as asr:
    report=inspect_ending(audio,'The complete intended ending must be present in this episode.',r)
   self.assertFalse(report['result']['passed']);asr.assert_called_once()

class GenerationBudgetTests(unittest.TestCase):
 def sample(self,maximum=False):
  result={}
  for name,(low,high) in WORD_BOUNDS.items():
   text=' '.join(['word']*(high if maximum else low))
   result[name]=[text,text,text] if name=='developments' else text
  return result
 def test_lower_budget_is_valid_and_above_total_minimum(self):
  candidate=self.sample();Draft202012Validator(bounded_podcast_schema()).validate(candidate)
  total=sum(len(x.split()) if isinstance(x,str) else sum(len(v.split()) for v in x) for x in candidate.values())
  self.assertEqual(total,1705)
  self.assertGreaterEqual(total,1700)
 def test_upper_budget_is_valid_and_below_total_maximum(self):
  candidate=self.sample(True);Draft202012Validator(bounded_podcast_schema()).validate(candidate)
  total=sum(len(x.split()) if isinstance(x,str) else sum(len(v.split()) for v in x) for x in candidate.values())
  self.assertEqual(total,1995)
  self.assertLessEqual(total,2000)
 def test_short_section_rejected_before_paid_revision_is_wasted(self):
  candidate=self.sample();candidate['closing']='too short'
  with self.assertRaises(ValidationError):Draft202012Validator(bounded_podcast_schema()).validate(candidate)
 def test_oversized_section_rejected(self):
  candidate=self.sample(True);candidate['developments'][0]+=' extra'
  with self.assertRaises(ValidationError):Draft202012Validator(bounded_podcast_schema()).validate(candidate)
 def test_generation_schema_does_not_mutate_approved_record_schema(self):
  original=copy.deepcopy(SCHEMA);generation_schema();self.assertEqual(SCHEMA,original)
 def test_generation_identifiers_constrained(self):
  schema=generation_schema()['properties']['sources']['items']['properties']['id']
  Draft202012Validator(schema).validate('cms-source-1')
  with self.assertRaises(ValidationError):Draft202012Validator(schema).validate('CMS source')

if __name__=='__main__':unittest.main()
