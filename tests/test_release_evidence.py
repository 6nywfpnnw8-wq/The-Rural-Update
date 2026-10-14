"""Exact-source coverage, safe retrieval, and one reviewed evidence correction."""
import copy
import json
import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch
import release_core as core
import release_evidence as evidence
import release_pipeline as pipeline
from evidence_fixture import fake_source
from test_release import fixture, DATE
from test_release_narration import response

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.cache=Path(self.tmp.name)
    def test_real_content_required_for_every_source(self):
        e=fixture()
        with patch.object(evidence,'fetch_source',side_effect=fake_source):
            docs=evidence.collect_source_evidence(e,self.cache)
        self.assertEqual(evidence.evidence_urls(e,docs),{core.canonical_url(s['url']) for s in e['sources']})
        report=core.read_json(self.cache/'source-evidence.json')
        self.assertTrue(report['complete']); self.assertFalse(report['publication_authorized'])
        self.assertNotIn('text',report['sources'][0])
    def test_unavailable_page_cannot_be_recorded_as_retrieved(self):
        with patch.object(evidence,'fetch_source',side_effect=urllib.error.HTTPError('x',403,'Forbidden',{},None)):
            with self.assertRaisesRegex(RuntimeError,'incomplete'):
                evidence.collect_source_evidence(fixture(),self.cache)
        r=core.read_json(self.cache/'source-evidence.json')
        self.assertFalse(r['complete']); self.assertEqual(r['sources'],[])
        self.assertEqual(r['failures'][0]['http_status'],403)
    def test_wrong_url_coverage_is_rejected(self):
        e=fixture(); docs=[dict(fake_source(s['url']),source_id=s['id']) for s in e['sources']]
        docs[0]['url']='https://www.cms.gov/different'
        with self.assertRaises(ValueError): evidence.evidence_urls(e,docs)
    def test_changed_evidence_text_is_rejected(self):
        e=fixture(); docs=[dict(fake_source(s['url']),source_id=s['id']) for s in e['sources']]
        docs[0]['text']='altered'
        with self.assertRaises(ValueError): evidence.evidence_urls(e,docs)
    def test_private_resolution_is_rejected(self):
        with patch.object(socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError): evidence.require_public_url('https://www.cms.gov/example')
    def test_foreign_host_redirect_is_rejected(self):
        with self.assertRaises(ValueError):
            evidence.PublicRedirects().redirect_request(None,None,302,'',{},'https://attacker.test/')
    def test_mixed_public_private_resolution_is_rejected(self):
        entries=[(2,1,6,'',(ip,443)) for ip in ('8.8.8.8','10.0.0.1')]
        with patch.object(socket,'getaddrinfo',return_value=entries):
            with self.assertRaises(ValueError): evidence.require_public_url('https://www.cms.gov/example')
    def test_retrieval_failure_prevents_paid_audit(self):
        api=Mock(side_effect=[response(fixture(),True)])
        with patch.object(pipeline,'request_api',api),patch.object(evidence,'fetch_source',side_effect=RuntimeError('unavailable')):
            with self.assertRaises(AssertionError): pipeline.research(DATE,{},self.cache)
        self.assertEqual(api.call_count,1); self.assertFalse((self.cache/'approved.json').exists())
    def test_success_is_bound_to_exact_candidate_and_source_record(self):
        api=Mock(side_effect=[response(fixture(),True),response({'approved':True,'issues':[]},True)])
        with patch.object(pipeline,'request_api',api),patch.object(evidence,'fetch_source',side_effect=fake_source):
            record=pipeline.research(DATE,{},self.cache)
        self.assertEqual(record['audit_candidate_sha256'],evidence.fingerprint(record['edition']))
        self.assertEqual(len(record['source_retrieval']),5)
        self.assertIn('EXACT SOURCE CONTENT',api.call_args.args[0]['input'])
        self.assertEqual(core.read_json(self.cache/'audit-bound.json')['candidate_sha256'],record['audit_candidate_sha256'])
    def test_http_success_does_not_override_failed_audit(self):
        api=Mock(side_effect=[response(fixture(),True),response({'approved':False,'issues':['Unsupported assertion']},True)])
        with patch.object(pipeline,'request_api',api),patch.object(evidence,'fetch_source',side_effect=fake_source):
            with self.assertRaisesRegex(RuntimeError,'audit rejected'): pipeline.research(DATE,{},self.cache)
        self.assertFalse((self.cache/'approved.json').exists())
    def test_reservation_is_repeat_safe(self):
        e=fixture(); evidence.reserve_source_audit(self.cache,e)
        with self.assertRaises(FileExistsError): evidence.reserve_source_audit(self.cache,e)
        self.assertFalse(core.read_json(self.cache/'source-recovery-attempt.json')['publication_authorized'])
    def test_actual_http_html_extraction_and_no_authorization_header(self):
        html=b'<html><title>Official source</title><body><nav>Menu</nav><main>'+b'Actual reference content. '*30+b'</main></body></html>'
        from email.message import Message
        headers=Message(); headers['Content-Type']='text/html; charset=utf-8'
        r=Mock(); r.status=200; r.headers=headers; r.read.return_value=html; r.geturl.return_value='https://www.cms.gov/example'
        r.__enter__=Mock(return_value=r); r.__exit__=Mock(return_value=False)
        opener=Mock(); opener.open.return_value=r
        with patch.object(evidence,'require_public_url'),patch.object(evidence.urllib.request,'build_opener',return_value=opener):
            d=evidence.fetch_source('https://www.cms.gov/example')
        self.assertNotIn('Menu',d['text']); self.assertEqual(d['sha256'],core.digest(html))
        self.assertIsNone(opener.open.call_args.args[0].get_header('Authorization'))

class ReviewedSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.cache=self.root/'cache';self.cache.mkdir()
        self.review=self.root/'editorial-review';self.review.mkdir()
        source=Path(__file__).resolve().parents[1]/'editorial-review/2026-10-14.json'
        self.plan=core.read_json(source)
        self.d='2026-10-14'
        self.source_path=self.root/'source-recovery'/(self.d+'.json')
        self.correction=core.read_json(source.parents[1]/'source-recovery'/(self.d+'.json'))
        core.write_json(self.source_path,self.correction)
        old=copy.deepcopy(self.plan['candidate'])
        h=evidence.fingerprint(old)
        self.assertEqual(h,self.correction['previous_candidate_sha256'])
        self.corrected=copy.deepcopy(old)
        next(s for s in self.corrected['sources'] if s['id']=='hhs-tax').update(self.correction['replacement'])
        core.write_json(self.cache/f'candidates/provenance-{h[:16]}.json',{'schema_version':1,'edition_date':self.d,'stage':'provenance',
            'candidate':old,'candidate_sha256':h,'redacted':False,'publication_authorized':False})
        core.write_json(self.cache/'validation-provenance.json',{'edition_date':self.d,'stage':'provenance','rule':'source_provenance','passed':False,'snapshot':{'candidate_sha256':h}})
        core.write_json(self.cache/'attempts.json',{'attempts':2})
        core.write_json(self.cache/'editorial-recovery-attempt.json',{'evidence_audit_reserved':True})
    def test_corrected_reference_still_requires_new_audit(self):
        api=Mock(return_value=response({'approved':True,'issues':[]},True))
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'request_api',api),patch.object(evidence,'fetch_source',side_effect=fake_source):
            r=pipeline.research(self.d,{},self.cache)
        self.assertEqual(api.call_count,1)
        self.assertEqual(r['edition'],self.corrected)
        self.assertEqual(core.read_json(self.cache/'attempts.json')['attempts'],2)
    def test_changed_claim_cannot_use_source_only_recovery(self):
        altered=copy.deepcopy(self.corrected); altered['bluf']='Changed reporting'
        self.correction['corrected_candidate_sha256']=evidence.fingerprint(altered)
        core.write_json(self.source_path,self.correction)
        with self.assertRaisesRegex(ValueError,'reporting'):
            evidence.take_source_recovery(self.cache,self.d,self.review)
    def test_failed_audit_cannot_loop(self):
        api=Mock(return_value=response({'approved':False,'issues':['Unsupported claim']},True))
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'request_api',api),patch.object(evidence,'fetch_source',side_effect=fake_source):
            with self.assertRaisesRegex(RuntimeError,'audit rejected'):pipeline.research(self.d,{},self.cache)
            with self.assertRaisesRegex(RuntimeError,'already reserved'):pipeline.research(self.d,{},self.cache)
        self.assertEqual(api.call_count,1)
        self.assertFalse((self.cache/'approved.json').exists())
    def test_successful_repeat_makes_no_new_api_call(self):
        api=Mock(return_value=response({'approved':True,'issues':[]},True))
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'request_api',api),patch.object(evidence,'fetch_source',side_effect=fake_source):
            a=pipeline.research(self.d,{},self.cache); b=pipeline.research(self.d,{},self.cache)
        self.assertEqual(a,b); self.assertEqual(api.call_count,1)

if __name__=='__main__':unittest.main()
