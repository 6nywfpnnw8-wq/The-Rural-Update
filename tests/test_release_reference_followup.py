"""A citation repair is not the unused, bounded factual correction cycle."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import release_audit_loop as loop
import release_reviewed_reference as reference
import release_evidence as evidence
import release_pipeline as pipeline
from release_core import read_json, write_json
from release_editorial import fingerprint
from test_release import fixture, DATE
from test_release_audit_loop import response, finding
from evidence_fixture import fake_source


class ReviewedReferenceFollowupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.cache, self.reviews = root / 'cache', root / 'reviews'
        self.folder = self.cache / 'editorial-loop-v1'
        self.folder.mkdir(parents=True)
        self.reviews.mkdir()
        self.original = fixture()
        self.original['sources'].append({'id':'s6', 'title':'Wrong-topic test source',
            'url':'https://www.cms.gov/test-6', 'published_date':None})
        self.original['stories'][0]['source_ids'].append('s6')
        self.corrected = copy.deepcopy(self.original)
        self.corrected['sources'] = self.corrected['sources'][:-1]
        self.corrected['stories'][0]['source_ids'].remove('s6')
        self.corrected['title'] = 'Reviewed synthetic fixture'
        self.initial = {'review_complete':False, 'findings':[{
            **finding('citation_mismatch'), 'source_ids':['s6']}]}
        write_json(self.folder/'original.json', {'edition_date':DATE,
            'candidate_sha256':fingerprint(self.original), 'candidate':self.original,
            'retrieved_urls':[], 'publication_authorized':False})
        write_json(self.folder/'initial-reserved.json', {'payload_sha256':'initial-signature',
            'publication_authorized':False})
        write_json(self.folder/'initial-result.json', {'payload_sha256':'initial-signature',
            'value_sha256':fingerprint(self.initial), 'value':self.initial})
        write_json(self.reviews/(DATE+'.json'), {'schema_version':1, 'edition_date':DATE,
            'base_candidate_sha256':fingerprint(self.original),
            'initial_review_sha256':fingerprint(self.initial),
            'candidate_sha256':fingerprint(self.corrected), 'publication_authorized':False,
            'use_existing_final_audit_only':True,
            'remove_sources':[{'id':'s6','url':'https://www.cms.gov/test-6','reason':'Wrong topic.'}],
            'replacements':[{'path':'/title','before':self.original['title'],
                             'after':self.corrected['title']}]})
        write_json(self.cache/'attempts.json', {'attempts':2})
        self.clean = {'review_complete':True,'findings':[]}
        self.blocked = {'review_complete':True,'findings':[finding()]}
        self.plan = {'replacements':[{'path':'/stories/0/why_it_matters',
            'before':'Tests the compiler.',
            'after':'Leadership should test the compiler before relying on its output.',
            'addresses':['f1']}]}
        for item in (patch.object(reference,'REVIEW_ROOT',self.reviews),
                     patch.object(evidence,'fetch_source',side_effect=fake_source)):
            item.start(); self.addCleanup(item.stop)
        self.docs = evidence.collect_source_evidence(self.original,self.cache)
        self.preserved = {p: p.read_bytes() for p in (
            self.folder/'initial-reserved.json',self.folder/'initial-result.json',
            self.folder/'original.json',self.cache/'attempts.json')}

    def run_loop(self, api):
        return loop.audit_and_correct(self.original,self.cache,'test-model',api,
                                      pipeline.output_text,self.docs,set(),None)

    def assert_originals_preserved(self):
        for path, data in self.preserved.items():
            self.assertEqual(path.read_bytes(),data)
        self.assertFalse((self.folder/'correction-reserved.json').exists())

    def test_clean_reference_review_spends_no_claim_correction(self):
        api=Mock(return_value=response(self.clean))
        out=self.run_loop(api)
        self.assertTrue(out['audit']['approved']); self.assertEqual(api.call_count,1)
        self.assertEqual(out['structured_review']['correction_calls'],0)
        self.assertFalse((self.folder/'reference-correction-reserved.json').exists())
        self.assert_originals_preserved()

    def test_completed_reference_review_can_use_one_claim_correction(self):
        api=Mock(side_effect=[response(self.blocked),response(self.plan,False),response(self.clean)])
        out=self.run_loop(api)
        self.assertTrue(out['audit']['approved']); self.assertEqual(api.call_count,3)
        self.assertEqual(out['structured_review']['correction_calls'],1)
        self.assertEqual(out['edition']['sources'],self.corrected['sources'])
        self.assertEqual(read_json(self.cache/'audit-bound.json')['candidate_sha256'],fingerprint(out['edition']))
        self.assertEqual(read_json(self.folder/'final-result.json')['value'],self.blocked)
        for slot in ('reference-correction','reference-corrected-final'):
            self.assertTrue((self.folder/(slot+'-reserved.json')).exists())
        self.assert_originals_preserved()

    def test_preexisting_final_review_reused_without_repeating_request(self):
        original_call=loop._call
        def stop_before_correction(folder,slot,*args):
            if slot=='reference-correction':
                raise RuntimeError('Synthetic stop before new reservation')
            return original_call(folder,slot,*args)
        first_api=Mock(return_value=response(self.blocked))
        with patch.object(loop,'_call',side_effect=stop_before_correction):
            with self.assertRaisesRegex(RuntimeError,'Synthetic stop'):
                self.run_loop(first_api)
        before={n:(self.folder/n).read_bytes() for n in ('final-result.json','final-reserved.json')}
        api=Mock(side_effect=[response(self.plan,False),response(self.clean)])
        self.assertTrue(self.run_loop(api)['audit']['approved'])
        self.assertEqual(api.call_count,2)
        self.assertTrue(self.run_loop(api)['audit']['approved'])
        self.assertEqual(api.call_count,2)
        for name,data in before.items():self.assertEqual((self.folder/name).read_bytes(),data)
        self.assert_originals_preserved()

    def test_post_correction_blockers_stop_without_another_cycle(self):
        final=copy.deepcopy(self.blocked)
        final['findings'][0]['quote']=self.plan['replacements'][0]['after']
        api=Mock(side_effect=[response(self.blocked),response(self.plan,False),response(final)])
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError,'single editorial correction'):
                self.run_loop(api)
        self.assertEqual(api.call_count,3)
        self.assertFalse((self.cache/'approved.json').exists())
        self.assert_originals_preserved()

    def test_incomplete_post_correction_review_is_never_approval(self):
        api=Mock(side_effect=[response(self.blocked),response(self.plan,False),
                             response({'review_complete':False,'findings':[]})])
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError,'review is incomplete'):
                self.run_loop(api)
        self.assertEqual(api.call_count,3)
        self.assertFalse((self.cache/'approved.json').exists())

    def test_post_correction_review_requires_live_web_retrieval(self):
        api=Mock(side_effect=[response(self.blocked),response(self.plan,False),response(self.clean,False)])
        with self.assertRaisesRegex(RuntimeError,'live web'):self.run_loop(api)
        with self.assertRaisesRegex(RuntimeError,'already reserved'):self.run_loop(api)
        self.assertEqual(api.call_count,3)
        self.assertFalse((self.cache/'approved.json').exists())

    def test_ambiguous_correction_request_is_not_repeated(self):
        api=Mock(side_effect=[response(self.blocked),TimeoutError('synthetic timeout')])
        with self.assertRaises(TimeoutError):self.run_loop(api)
        with self.assertRaisesRegex(RuntimeError,'already reserved'):self.run_loop(api)
        self.assertEqual(api.call_count,2)
        self.assertFalse((self.folder/'reference-corrected-final-reserved.json').exists())

    def test_existing_ordinary_correction_cannot_be_replaced(self):
        write_json(self.folder/'correction-reserved.json', {'reserved':True})
        api=Mock()
        with self.assertRaisesRegex(RuntimeError,'automated correction cannot be replaced'):
            self.run_loop(api)
        api.assert_not_called()

    def test_changed_correction_cannot_reuse_completed_audit(self):
        api=Mock(side_effect=[response(self.blocked),response(self.plan,False),response(self.clean)])
        self.run_loop(api)
        path=self.folder/'reference-correction-result.json'
        record=read_json(path);record['value']['replacements'][0]['after']='Tampered prose.'
        write_json(path,record)
        with self.assertRaisesRegex(ValueError,'integrity mismatch'):self.run_loop(api)
        self.assertEqual(api.call_count,3)

    def test_new_source_url_cannot_be_inserted_by_correction(self):
        bad=copy.deepcopy(self.plan);bad['replacements'][0]['path']='/sources/0/url'
        api=Mock(side_effect=[response(self.blocked),response(bad,False)])
        with self.assertRaises(Exception):self.run_loop(api)
        self.assertEqual(api.call_count,2)
        self.assertFalse((self.folder/'reference-corrected-final-reserved.json').exists())
        self.assertFalse((self.cache/'approved.json').exists())

if __name__=='__main__':unittest.main()
