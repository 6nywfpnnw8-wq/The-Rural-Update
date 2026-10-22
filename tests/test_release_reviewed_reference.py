"""Incomplete reviews can never authorize publication, even after reviewed edits."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from test_release import fixture, DATE
from release_core import write_json, read_json
from release_editorial import fingerprint
from release_reviewed_reference import take_reviewed_reference
import release_audit_loop as loop

class ReviewedReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.cache=self.root/'cache';self.folder=self.cache/'editorial-loop-v1'
        self.review_root=self.root/'review';self.review_root.mkdir()
        self.edition=fixture()
        redundant=copy.deepcopy(self.edition['sources'][0]);redundant['id']='redundant'
        redundant['url']='https://www.cms.gov/redundant-public-reference'
        self.edition['sources'].append(redundant)
        self.edition['stories'][0]['source_ids'].append('redundant')
        self.initial={'review_complete':False,'findings':[{'id':'F1','kind':'citation_mismatch',
            'path':'/stories/0/what_changed','quote':'An unbound preliminary observation',
            'source_ids':['redundant'],'explanation':'Reference does not substantiate the claim.',
            'required_change':'Remove unsupported citation and independently review all remaining claims.'}]}
        self.corrected=copy.deepcopy(self.edition)
        self.corrected['sources']=self.corrected['sources'][:-1]
        self.corrected['stories'][0]['source_ids'].remove('redundant')
        old=self.corrected['stories'][0]['what_changed']
        self.corrected['stories'][0]['what_changed']='Source review remains required for this operational update.'
        self.plan={'schema_version':1,'edition_date':DATE,'publication_authorized':False,
            'use_existing_final_audit_only':True,'base_candidate_sha256':fingerprint(self.edition),
            'candidate_sha256':fingerprint(self.corrected),'initial_review_sha256':fingerprint(self.initial),
            'remove_sources':[{'id':'redundant','url':redundant['url'],'reason':'Checked against the actual primary page.'}],
            'replacements':[{'path':'/stories/0/what_changed','before':old,'after':self.corrected['stories'][0]['what_changed']}]}
        self.plan_path=self.review_root/(DATE+'.json')
        write_json(self.plan_path,self.plan)
        write_json(self.folder/'original.json',{'edition_date':DATE,'candidate_sha256':fingerprint(self.edition),
            'candidate':self.edition,'publication_authorized':False})
        write_json(self.folder/'initial-reserved.json',{'payload_sha256':'initial','publication_authorized':False})
        write_json(self.folder/'initial-result.json',{'payload_sha256':'initial','value_sha256':fingerprint(self.initial),'value':self.initial})
        write_json(self.cache/'attempts.json',{'attempts':2})
        write_json(self.cache/'source-evidence.json',{'sources':[],'complete':True})
    def take(self):return take_reviewed_reference(self.edition,self.cache,self.review_root)
    def test_absent_plan_does_nothing(self):
        self.plan_path.unlink();self.assertIsNone(self.take())
        self.assertFalse((self.folder/'reviewed-reference-correction.json').exists())
    def test_exact_reviewed_patch_preserves_initial_and_attempts(self):
        original=copy.deepcopy(self.edition)
        before={n:(self.folder/n).read_bytes() for n in ('original.json','initial-reserved.json','initial-result.json')}
        self.assertEqual(self.take(),self.corrected)
        self.assertEqual(self.edition,original)
        for n,data in before.items():self.assertEqual((self.folder/n).read_bytes(),data)
        self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':2})
        self.assertFalse(read_json(self.folder/'initial-result.json')['value']['review_complete'])
        self.assertFalse((self.cache/'approved.json').exists())
    def test_identical_replay_does_not_change_reservation(self):
        self.take();before=(self.folder/'reviewed-reference-correction.json').read_bytes()
        self.assertEqual(self.take(),self.corrected)
        self.assertEqual(before,(self.folder/'reviewed-reference-correction.json').read_bytes())
    def test_changed_operator_plan_rejected_after_reservation(self):
        self.take();self.plan['remove_sources'][0]['reason']='Different explanation.'
        write_json(self.plan_path,self.plan)
        with self.assertRaisesRegex(ValueError,'reservation differs'):self.take()
    def test_changed_candidate_rejected(self):
        self.edition['title']='Changed'
        with self.assertRaisesRegex(ValueError,'identity mismatch'):self.take()
    def test_changed_initial_review_rejected(self):
        p=self.folder/'initial-result.json';d=read_json(p);d['value']['review_complete']=True;write_json(p,d)
        with self.assertRaisesRegex(ValueError,'initial review differs'):self.take()
    def test_wrong_reference_url_rejected(self):
        self.plan['remove_sources'][0]['url']='https://www.cms.gov/different'
        write_json(self.plan_path,self.plan)
        with self.assertRaisesRegex(ValueError,'observed mismatch'):self.take()
    def test_unflagged_reference_cannot_be_removed(self):
        self.plan['remove_sources'][0]={'id':'s2','url':self.edition['sources'][1]['url'],'reason':'Unflagged'}
        write_json(self.plan_path,self.plan)
        with self.assertRaisesRegex(ValueError,'observed mismatch'):self.take()
    def test_stale_exact_replacement_rejected(self):
        self.plan['replacements'][0]['before']='Not the current field'
        write_json(self.plan_path,self.plan)
        with self.assertRaisesRegex(ValueError,'stale or invalid'):self.take()
    def test_source_url_edit_cannot_enter_prose_patch(self):
        self.plan['replacements'][0]['path']='/sources/0/url'
        write_json(self.plan_path,self.plan)
        with self.assertRaisesRegex(ValueError,'stale or invalid'):self.take()
    def test_cannot_reopen_existing_final_audit(self):
        write_json(self.folder/'final-reserved.json',{'payload_sha256':'spent'})
        with self.assertRaisesRegex(RuntimeError,'cannot be reopened'):self.take()
    def test_cannot_replace_automated_correction(self):
        write_json(self.folder/'correction-reserved.json',{'payload_sha256':'spent'})
        with self.assertRaisesRegex(RuntimeError,'cannot be replaced'):self.take()
    def test_plan_cannot_approve(self):
        self.plan['publication_authorized']=True;write_json(self.plan_path,self.plan)
        with self.assertRaisesRegex(ValueError,'identity mismatch'):self.take()
    def run_audit(self,report):
        urls={s['url'] for s in self.corrected['sources']}
        with patch('release_reviewed_reference.REVIEW_ROOT',self.review_root), \
             patch.object(loop,'collect_source_evidence',return_value=[]), \
             patch.object(loop,'evidence_urls',return_value=urls), \
             patch.object(loop,'_call',return_value=(report,urls,None)) as call:
            result=loop.audit_and_correct(self.edition,self.cache,'test-model',None,None,[],urls,None)
        self.assertEqual(call.call_count,1)
        self.assertEqual(call.call_args.args[1],'final')
        return result
    def test_fresh_complete_final_audit_is_required(self):
        out=self.run_audit({'review_complete':True,'findings':[]})
        self.assertEqual(out['edition'],self.corrected)
        self.assertTrue(out['audit']['approved'])
        self.assertEqual(out['structured_review']['correction_calls'],0)
        self.assertEqual(out['structured_review']['correction_method'],'reviewed-reference')
        self.assertFalse(read_json(self.folder/'initial-result.json')['value']['review_complete'])
    def test_incomplete_final_audit_still_blocks(self):
        with self.assertRaisesRegex(RuntimeError,'incomplete'):
            self.run_audit({'review_complete':False,'findings':[]})
        self.assertFalse((self.cache/'approved.json').exists())
    def test_final_blocking_claim_still_blocks(self):
        f=copy.deepcopy(self.initial['findings'][0]);f['quote']=self.corrected['stories'][0]['what_changed']
        f['source_ids']=['s1'];f['kind']='unsupported_claim'
        report={'review_complete':True,'findings':[f]}
        replacement='Leadership should independently verify this operational update.'
        plan={'replacements':[{'path':f['path'],'before':f['quote'],
                              'after':replacement,'addresses':['F1']}]}
        final=copy.deepcopy(report);final['findings'][0]['quote']=replacement
        urls={s['url'] for s in self.corrected['sources']}
        # Model each stage distinctly: a valid correction is not final approval.
        with patch('release_reviewed_reference.REVIEW_ROOT',self.review_root), \
             patch.object(loop,'collect_source_evidence',return_value=[]), \
             patch.object(loop,'evidence_urls',return_value=urls), \
             patch.object(loop,'_call',side_effect=[(report,urls,None),
                 (plan,set(),None),(final,urls,None)]) as call:
            with self.assertRaisesRegex(RuntimeError,'Blocking findings remain'):
                loop.audit_and_correct(self.edition,self.cache,'test-model',None,None,[],urls,None)
        self.assertEqual([c.args[1] for c in call.call_args_list],
                         ['final','reference-correction','reference-corrected-final'])
        self.assertFalse((self.cache/'approved.json').exists())
        self.assertEqual(read_json(self.cache/'attempts.json'),{'attempts':2})
        self.assertFalse(read_json(self.folder/'initial-result.json')['value']['review_complete'])
    def test_final_unbound_quote_still_blocks(self):
        f=copy.deepcopy(self.initial['findings'][0]);f['source_ids']=['s1']
        with self.assertRaisesRegex(ValueError,'does not quote'):
            self.run_audit({'review_complete':True,'findings':[f]})
        self.assertFalse((self.cache/'approved.json').exists())
    def test_recorded_plan_cannot_reset_final_request(self):
        self.take();write_json(self.folder/'final-reserved.json',{'payload_sha256':'spent'})
        self.assertEqual(self.take(),self.corrected)
        with self.assertRaisesRegex(RuntimeError,'already reserved'):
            loop._call(self.folder,'final',{},lambda p: self.fail('Repeated request'),None)

if __name__=='__main__':unittest.main()
