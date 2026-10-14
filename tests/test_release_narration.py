"""No live API calls. Narration repair cannot bypass content verification."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from test_release import fixture, DATE
import release_pipeline as pipeline
from release_core import validate_edition, canonical_url
from release_narration import ensure_narration_length


def response(text, with_search=False):
    outputs = [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(text)}]}]
    if with_search:
        outputs.insert(0, {'type': 'web_search_call', 'action': {'sources': [
            {'url': s['url']} for s in fixture()['sources']]}})
    return {'status': 'completed', 'output': outputs}


class NarrationTests(unittest.TestCase):
    def setUp(self):
        from evidence_fixture import fake_source
        import release_evidence
        source_patch = patch.object(release_evidence, 'fetch_source', side_effect=fake_source)
        source_patch.start(); self.addCleanup(source_patch.stop)
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.cache=Path(self.temp.name)
    def repair(self,e,api):
        return ensure_narration_length(e,self.cache,'test-model',api,pipeline.output_text)
    def test_valid_script_makes_no_revision_call(self):
        api=Mock(); e=fixture()
        self.assertEqual(self.repair(e,api),e);api.assert_not_called()
    def test_short_script_revised_without_changing_facts(self):
        e=fixture(); e['podcast']['opening']='Short opening.'; original=copy.deepcopy(e)
        api=Mock(return_value=response(fixture()['podcast']))
        result=self.repair(e,api)
        validate_edition(result,DATE)
        self.assertEqual(e,original)
        for key in e:
            if key!='podcast':self.assertEqual(result[key],e[key])
        self.assertEqual(api.call_count,1)
    def test_long_script_is_revised_not_truncated(self):
        e=fixture(); e['podcast']['opening']+=' '+('long '*250)
        api=Mock(return_value=response(fixture()['podcast']))
        validate_edition(self.repair(e,api),DATE);self.assertEqual(api.call_count,1)
    def test_retries_are_bounded_and_do_not_lower_requirement(self):
        e=fixture(); e['podcast']['opening']='Short.'
        api=Mock(return_value=response(e['podcast']))
        with self.assertRaisesRegex(RuntimeError,'Publication blocked'):
            self.repair(e,api)
        self.assertEqual(api.call_count,2)
        diagnostic=json.loads((self.cache/'narration-check.json').read_text())
        self.assertFalse(diagnostic['within_range'])
    def test_invalid_response_cannot_replace_news(self):
        e=fixture();e['podcast']['opening']='Short.'
        api=Mock(return_value=response({'stories': []}))
        with self.assertRaises(Exception):self.repair(e,api)
    def test_full_validation_still_rejects_unsafe_narration(self):
        e=fixture();e['podcast']['opening']='Short.'
        p=fixture()['podcast'];p['opening']+=' https://example.test/'
        api=Mock(return_value=response(p))
        result=self.repair(e,api)
        with self.assertRaisesRegex(AssertionError,'URLs or markup'):validate_edition(result,DATE)
    def test_repaired_narration_still_requires_successful_audit(self):
        e=fixture();e['podcast']['opening']='Short.'
        api=Mock(side_effect=[response(e,True),response(fixture()['podcast']),
                             response({'approved':False,'issues':['Unsupported claim']},True)])
        with patch.object(pipeline,'request_api',api):
            with self.assertRaisesRegex(RuntimeError,'audit rejected'):
                pipeline.research(DATE,{},self.cache)
        self.assertFalse((self.cache/'approved.json').exists())
        self.assertEqual(api.call_count,3)
    def test_repaired_narration_passes_existing_provenance_gate(self):
        e=fixture();e['podcast']['opening']='Short.'
        api=Mock(side_effect=[response(e,True),response(fixture()['podcast']),
                             response({'approved':True,'issues':[]},True)])
        with patch.object(pipeline,'request_api',api):
            record=pipeline.research(DATE,{},self.cache)
        validate_edition(record['edition'],DATE,set(record['retrieved_urls']))
        self.assertTrue(record['audit']['approved'])
        self.assertEqual(json.loads((self.cache/'attempts.json').read_text())['attempts'],1)

if __name__=='__main__':unittest.main()
