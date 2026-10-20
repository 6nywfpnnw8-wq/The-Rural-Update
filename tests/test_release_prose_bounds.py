"""Verify that every accepted prose boundary satisfies the existing podcast schema."""
import sys,unittest
from pathlib import Path
from jsonschema import Draft202012Validator
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from release_narration import bounded_podcast_schema
from release_prose import validate_prose,lower_words,TOLERANCE
from release_sectioned_narration import SECTION_PLAN

class ProseBoundaryTests(unittest.TestCase):
    def test_low_and_high_bounds_match_original_release_schema(self):
        for upper in (False,True):
            value={'developments':[]}
            for name,index,target in SECTION_PLAN:
                count=target+TOLERANCE if upper else lower_words(target)
                text=' '.join(['word']*(count-1)+['ending.'])
                checked=validate_prose({'text':text},target)
                if index is None:value[name]=checked
                else:value[name].append(checked)
            Draft202012Validator(bounded_podcast_schema()).validate(value)
            words=sum(len(s.split()) for k,v in value.items() for s in (v if isinstance(v,list) else [v]))
            self.assertGreaterEqual(words,1700);self.assertLessEqual(words,2000)
    def test_closing_minimum_is_not_relaxed(self):
        for count in (45,49):
            with self.assertRaises(ValueError):validate_prose({'text':' '.join(['word']*(count-1)+['ending.'])},55)
        self.assertEqual(len(validate_prose({'text':' '.join(['word']*49+['ending.'])},55).split()),50)

if __name__=='__main__':unittest.main()
