"""Keep each development focused and normalize typography before spending a retry."""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_prose as prose
import test_release_prose as fixtures


class SectionScopeTests(unittest.TestCase):
    def test_developments_receive_their_own_story_and_actions(self):
        report={'edition_date':'2026-10-24','bluf':'Whole report summary',
                'stories':[{'id':str(i),'title':'Story '+str(i)} for i in range(3)],
                'actions':[{'issue_id':str(i),'next_step':'Action '+str(i)} for i in range(3)]}
        before=copy.deepcopy(report)
        for i in range(3):
            scoped=prose.section_input(report,'developments',i)
            self.assertEqual(scoped['story'],report['stories'][i])
            self.assertEqual(scoped['actions'],[report['actions'][i]])
            self.assertNotIn('bluf',scoped)
            self.assertNotIn('stories',scoped)
        self.assertEqual(report,before)

    def test_typography_keeps_numbers_and_words_while_removing_em_dash(self):
        raw={'text':' '.join(['Supported']*153+['2026','\u2014','ending.'])}
        before=copy.deepcopy(raw)
        normalized=prose.normalize_section(raw)
        self.assertEqual(normalized['text'],raw['text'].replace('\u2014','-'))
        prose.validate_prose(normalized,165)
        self.assertEqual(raw,before)

    def test_normalization_does_not_accept_links_markup_or_bad_length(self):
        for ending in ('https://cms.gov/a.','<b>ending.</b>','TODO.'):
            value={'text':' '.join(['word']*154+[ending])}
            with self.assertRaises(ValueError):prose.validate_prose(prose.normalize_section(value),165)
        with self.assertRaises(ValueError):
            prose.validate_prose(prose.normalize_section({'text':'Too short \u2014 ending.'}),165)

    def test_completed_typography_error_uses_one_request_and_retains_raw_text(self):
        f=fixtures.ProseTests(methodName='test_compact_schema_and_passes_exact_target')
        f.setUp();self.addCleanup(f.doCleanups)
        calls=[]
        def respond(payload):
            calls.append(payload)
            field=payload['text']['format']['schema']['properties']['text']
            count=field['minLength']//2+prose.TOLERANCE
            value=' '.join(['Supported']*(count-3)+['2026','\u2014','ending.'])
            return {'status':'completed','text':json.dumps({'text':value}),'usage':{}}
        output=f.generate(Mock(side_effect=respond))
        self.assertEqual(len(calls),10)
        self.assertNotIn('\u2014',json.dumps(output,ensure_ascii=False))
        candidates=list((f.cache/'section-candidates').glob('*.json'))
        self.assertTrue(any('\u2014' in p.read_text() for p in candidates))


if __name__=='__main__':unittest.main()
