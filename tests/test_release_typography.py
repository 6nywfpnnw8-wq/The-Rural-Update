"""Reproduce the October 14 formatting stop without weakening release checks."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from test_release import fixture, DATE
from release_core import validate_edition
from release_narration import ensure_narration_length
from release_typography import normalize_edition_typography


class TypographyTests(unittest.TestCase):
    def test_prose_normalized_without_mutating_original(self):
        e=fixture();e['bluf']='Financing\u2014not staffing\u2014is the concern.'
        before=copy.deepcopy(e); result, changes=normalize_edition_typography(e)
        self.assertEqual(e,before)
        self.assertEqual(result['bluf'],'Financing - not staffing - is the concern.')
        self.assertEqual(changes,[{'path':'/bluf','replacements':2}])
        validate_edition(result,DATE)

    def test_numeric_facts_and_dates_preserved(self):
        e=fixture();e['stories'][0]['what_changed']='$12.5 million\u2014proposed, not final; 6.2% on October 1.'
        result,_=normalize_edition_typography(e)
        self.assertEqual(result['stories'][0]['what_changed'],
                         e['stories'][0]['what_changed'].replace('\u2014',' - '))
        self.assertEqual(result['deadlines'],e['deadlines'])
        self.assertEqual(result['edition_date'],DATE)

    def test_urls_ids_and_source_references_never_rewritten(self):
        e=fixture();e['sources'][0]['url']='https://www.cms.gov/a\u2014b'
        e['stories'][0]['id']='a\u2014b';e['stories'][0]['source_ids']=['a\u2014b']
        result,_=normalize_edition_typography(e)
        self.assertEqual(result,e)
        with self.assertRaises(AssertionError): validate_edition(result,DATE)

    def test_source_display_title_normalized_not_url(self):
        e=fixture();e['sources'][0]['title']='CMS\u2014source title'
        result,_=normalize_edition_typography(e)
        self.assertEqual(result['sources'][0]['title'],'CMS - source title')
        self.assertEqual(result['sources'][0]['url'],e['sources'][0]['url'])

    def test_nested_podcast_normalized(self):
        e=fixture();e['podcast']['developments'][1]+=' Review\u2014then act.'
        result,changes=normalize_edition_typography(e)
        self.assertNotIn('\u2014',result['podcast']['developments'][1])
        self.assertEqual(changes[0]['path'],'/podcast/developments/1')
        validate_edition(result,DATE)

    def test_repeated_normalization_is_noop(self):
        e=fixture();e['bluf']='Review \u2014 act.'
        once,_=normalize_edition_typography(e);twice,changes=normalize_edition_typography(once)
        self.assertEqual(once,twice);self.assertEqual(changes,[])

    def test_placeholder_and_provenance_checks_remain(self):
        e=fixture();e['bluf']='Draft pending\u2014finish this.'
        result,_=normalize_edition_typography(e)
        with self.assertRaisesRegex(AssertionError,'Placeholder'): validate_edition(result,DATE)
        result,_=normalize_edition_typography(fixture())
        with self.assertRaisesRegex(AssertionError,'not observed'): validate_edition(result,DATE,set())

    def test_normalization_precedes_validation_with_no_extra_api_call(self):
        e=fixture();e['podcast']['closing']+=' Review\u2014then act.'
        api=Mock()
        with tempfile.TemporaryDirectory() as td:
            result=ensure_narration_length(e,Path(td),'test',api,lambda r:json.dumps(r))
            validate_edition(result,DATE);api.assert_not_called()
            report=json.loads((Path(td)/'typography-check.json').read_text())
            self.assertFalse(report['publication_authorized'])
            self.assertEqual(report['changed_fields'][0]['path'],'/podcast/closing')
            self.assertNotIn('Review',json.dumps(report))

    def test_revision_output_normalized_too(self):
        e=fixture();e['podcast']['opening']='Short.'
        podcast=fixture()['podcast'];podcast['closing']+=' Review\u2014then act.'
        api=Mock(return_value=podcast)
        with tempfile.TemporaryDirectory() as td:
            result=ensure_narration_length(e,Path(td),'test',api,lambda r:json.dumps(r))
            validate_edition(result,DATE)
        self.assertEqual(api.call_count,1)
        self.assertEqual(result['stories'],e['stories'])

    def test_unsafe_markup_not_removed_or_approved(self):
        e=fixture();e['podcast']['closing']+=' <script>x</script>\u2014unsafe'
        result,_=normalize_edition_typography(e)
        with self.assertRaisesRegex(AssertionError,'URLs or markup'):validate_edition(result,DATE)

if __name__=='__main__':unittest.main()
