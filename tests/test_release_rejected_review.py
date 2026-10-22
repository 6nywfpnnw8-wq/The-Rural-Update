"""Changed evidence cannot reuse an approval, but can retain exact rejection feedback."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from release_core import read_json, write_json
from release_editorial import fingerprint
from release_rejected_review import call_with_rejected_feedback
import test_release_reference_followup as fixtures
from test_release_audit_loop import response
import release_audit_loop as loop


class RefreshedRejectionTests(unittest.TestCase):
    setUp = fixtures.ReviewedReferenceFollowupTests.setUp
    run_loop = fixtures.ReviewedReferenceFollowupTests.run_loop
    assert_originals_preserved = fixtures.ReviewedReferenceFollowupTests.assert_originals_preserved

    def retain_blocked_review(self):
        original_call=loop._call
        def stop_before_correction(folder,slot,*args):
            if slot=='reference-correction':
                raise RuntimeError('Synthetic stop before correction reservation')
            return original_call(folder,slot,*args)
        api=Mock(return_value=response(self.blocked))
        with patch.object(loop,'_call',side_effect=stop_before_correction):
            with self.assertRaisesRegex(RuntimeError,'Synthetic stop'):
                self.run_loop(api)
        self.assertEqual(api.call_count,1)
        self.old_bytes={p:p.read_bytes() for p in
            (self.folder/'final-result.json',self.folder/'final-reserved.json')}

    def changed_evidence(self):
        from evidence_fixture import fake_source
        from release_core import digest
        def fetch(url):
            item=fake_source(url)
            item['text']+=' A newly retrieved source sentence requires fresh review.'
            item['text_sha256']=digest(item['text'])
            return item
        return patch('release_evidence.fetch_source',side_effect=fetch)

    def test_changed_sources_use_rejection_only_then_fresh_audit(self):
        self.retain_blocked_review()
        api=Mock(side_effect=[response(self.plan,False),response(self.clean)])
        with self.changed_evidence():
            out=self.run_loop(api)
        self.assertTrue(out['audit']['approved']);self.assertEqual(api.call_count,2)
        for p,b in self.old_bytes.items():self.assertEqual(p.read_bytes(),b)
        report=read_json(self.cache/'validation-reviewed-evidence-refresh.json')
        self.assertEqual(report['use'],'blocking_feedback_only')
        self.assertFalse(report['publication_authorized'])
        self.assertTrue(report['fresh_post_correction_audit_required'])
        self.assert_originals_preserved()

    def test_changed_sources_and_fresh_blocker_cannot_approve(self):
        self.retain_blocked_review()
        final=copy.deepcopy(self.blocked)
        final['findings'][0]['quote']=self.plan['replacements'][0]['after']
        api=Mock(side_effect=[response(self.plan,False),response(final)])
        with self.changed_evidence():
            with self.assertRaisesRegex(RuntimeError,'Blocking findings remain'):
                self.run_loop(api)
        self.assertFalse((self.cache/'approved.json').exists())
        self.assertEqual(api.call_count,2)

    def test_changed_sources_and_no_live_final_retrieval_cannot_approve(self):
        self.retain_blocked_review()
        api=Mock(side_effect=[response(self.plan,False),response(self.clean,False)])
        with self.changed_evidence():
            with self.assertRaisesRegex(RuntimeError,'live web'):
                self.run_loop(api)
        self.assertFalse((self.cache/'approved.json').exists())

    def fallback(self):
        return call_with_rejected_feedback(self.folder,'final',{'input':'new evidence'},
            None,None,self.corrected,
            Mock(side_effect=ValueError('Editorial checkpoint differs from request')),
            loop.validate_review)

    def test_prior_approval_never_uses_feedback_exception(self):
        self.retain_blocked_review()
        p=self.folder/'final-result.json';d=read_json(p)
        d['value']=self.clean;d['value_sha256']=fingerprint(self.clean);write_json(p,d)
        with self.assertRaisesRegex(ValueError,'Only completed blocking'):
            self.fallback()

    def test_incomplete_review_never_uses_feedback_exception(self):
        self.retain_blocked_review()
        p=self.folder/'final-result.json';d=read_json(p)
        d['value']['review_complete']=False;d['value_sha256']=fingerprint(d['value']);write_json(p,d)
        with self.assertRaisesRegex(RuntimeError,'incomplete'):
            self.fallback()

    def test_other_candidate_cannot_borrow_rejection(self):
        self.retain_blocked_review();self.corrected['title']='A different candidate'
        with self.assertRaisesRegex(ValueError,'bound to the current candidate'):
            self.fallback()

    def test_modified_summary_cannot_borrow_review(self):
        self.retain_blocked_review()
        p=self.cache/'validation-structured-review.json';d=read_json(p)
        d['findings'][0]['required_change']='Different instruction';write_json(p,d)
        with self.assertRaisesRegex(ValueError,'bound to the current candidate'):
            self.fallback()

    def test_modified_result_is_rejected(self):
        self.retain_blocked_review()
        p=self.folder/'final-result.json';d=read_json(p)
        d['value']['findings'][0]['quote']='Changed';write_json(p,d)
        with self.assertRaisesRegex(ValueError,'integrity mismatch'):
            self.fallback()

    def test_unrelated_exception_is_not_intercepted(self):
        with self.assertRaisesRegex(ValueError,'unrelated error'):
            call_with_rejected_feedback(self.folder,'final',{},None,None,self.corrected,
                Mock(side_effect=ValueError('unrelated error')),loop.validate_review)

    def test_nonfinal_slot_cannot_bypass_payload_match(self):
        with self.assertRaisesRegex(ValueError,'checkpoint differs'):
            call_with_rejected_feedback(self.folder,'reference-corrected-final',{},None,None,self.corrected,
                Mock(side_effect=ValueError('Editorial checkpoint differs from request')),loop.validate_review)

if __name__=='__main__':unittest.main()
