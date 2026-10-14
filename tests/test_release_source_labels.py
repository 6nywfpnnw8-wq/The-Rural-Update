"""Source identity remapping must preserve evidence and reference relationships."""
import copy
import unittest
from test_release import fixture, DATE
from release_core import validate_edition
from release_typography import normalize_source_identifiers

class SourceLabelTests(unittest.TestCase):
    def case(self):
        e=fixture()
        for source in e['sources']:source['id']=source['id'].upper()
        for group in ('stories','actions','deadlines','signals','issue_updates'):
            for item in e[group]:item['source_ids']=[v.upper() for v in item['source_ids']]
        return e

    def test_case_normalization_preserves_urls_facts_and_links(self):
        e=self.case();before=copy.deepcopy(e);out,changes=normalize_source_identifiers(e)
        self.assertEqual(e,before)
        self.assertEqual(out,fixture())
        self.assertTrue(changes);validate_edition(out,DATE)

    def test_valid_identifiers_make_no_change(self):
        e=fixture();out,changes=normalize_source_identifiers(e)
        self.assertEqual(out,e);self.assertEqual(changes,[])

    def test_collision_is_not_merged(self):
        e=self.case();e['sources'][1]['id']='s1'
        with self.assertRaisesRegex(ValueError,'collide'):normalize_source_identifiers(e)

    def test_duplicate_source_not_merged(self):
        e=self.case();e['sources'][1]['id']='S1'
        with self.assertRaisesRegex(ValueError,'duplicated'):normalize_source_identifiers(e)

    def test_unknown_reference_not_repaired_by_coincidence(self):
        e=self.case();e['stories'][0]['source_ids']=['s1']
        with self.assertRaisesRegex(ValueError,'unresolved'):normalize_source_identifiers(e)

    def test_source_url_and_prose_containing_id_are_unchanged(self):
        e=self.case();e['sources'][0]['url']='https://www.cms.gov/S1'
        e['bluf']='S1 is an internal label, not a verified assertion.'
        out,_=normalize_source_identifiers(e)
        self.assertEqual(out['sources'][0]['url'],e['sources'][0]['url'])
        self.assertEqual(out['bluf'],e['bluf'])

    def test_repeat_is_noop(self):
        out,_=normalize_source_identifiers(self.case());again,changes=normalize_source_identifiers(out)
        self.assertEqual(out,again);self.assertEqual(changes,[])

    def test_unknown_source_is_not_created(self):
        e=self.case();e['stories'][0]['source_ids']=['MISSING']
        with self.assertRaises(ValueError):normalize_source_identifiers(e)

    def test_non_ascii_only_id_rejected(self):
        e=self.case();e['sources'][0]['id']='!!!'
        with self.assertRaises(ValueError):normalize_source_identifiers(e)

if __name__=='__main__':unittest.main()
