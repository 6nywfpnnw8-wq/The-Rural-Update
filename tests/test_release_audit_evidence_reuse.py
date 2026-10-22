"""Identical retrievals may reuse timestamps, never stale contents or approvals."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from release_core import read_json,write_json,digest
from release_editorial import fingerprint
from release_audit_evidence import bound_evidence_documents
from release_evidence import evidence_prompt
from release_audit_loop import _call
from evidence_fixture import fake_source

class AuditEvidenceReuseTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.folder=self.root/'cache'/'review';self.folder.mkdir(parents=True)
        self.plans=self.root/'plans';self.plans.mkdir()
        self.edition={'edition_date':'2026-10-22','sources':[{'id':'one','url':'https://www.cms.gov/test'}]}
        self.docs=[fake_source(self.edition['sources'][0]['url'])]
        self.docs[0]['source_id']='one';self.docs[0]['retrieved_at']='2026-10-22T10:00:00+00:00'

    def bind(self):
        return bound_evidence_documents(self.folder,self.edition,self.docs,self.plans)

    def seed(self):
        report={'schema_version':1,'edition_date':self.edition['edition_date'],
            'candidate_sha256':fingerprint(self.edition),'publication_authorized':False,
            'complete':True,'failures':[],'sources':[{k:v for k,v in d.items() if k!='text'} for d in self.docs]}
        write_json(self.plans/'evidence-2026-10-22.json',report)
        return report

    def test_first_request_checkpoint_then_timestamp_only_reuse(self):
        first=self.bind();original=copy.deepcopy(self.docs)
        self.docs[0]['retrieved_at']='2026-10-22T11:00:00+00:00'
        second=self.bind()
        self.assertEqual(first,second)
        self.assertEqual(self.docs[0]['retrieved_at'],'2026-10-22T11:00:00+00:00')
        self.assertEqual(second,original)

    def test_exact_saved_request_signature_is_reused_without_api(self):
        old=self.seed();p={'input':evidence_prompt(self.docs)};value={'review_complete':True,'findings':[]}
        write_json(self.folder/'full-source-review-reserved.json',{'payload_sha256':fingerprint(p)})
        saved={'payload_sha256':fingerprint(p),'value_sha256':fingerprint(value),'value':value,'retrieved_urls':[],'usage':None}
        write_json(self.folder/'full-source-review-result.json',saved)
        self.docs[0]['retrieved_at']='2026-10-22T11:00:00+00:00'
        new={'input':evidence_prompt(self.bind())}
        self.assertEqual(p,new)
        def deny(*a,**k):raise AssertionError('No repeated API call permitted')
        self.assertEqual(_call(self.folder,'full-source-review',new,deny,deny)[0],value)
        self.assertEqual(read_json(self.folder/'full-source-review-result.json'),saved)
        self.assertEqual(read_json(self.folder/'request-evidence.json'),old)

    def test_saved_reservation_without_result_still_cannot_repeat(self):
        self.seed();write_json(self.folder/'full-source-review-reserved.json',{})
        self.bind()
        with self.assertRaisesRegex(RuntimeError,'already reserved'):
            _call(self.folder,'full-source-review',{},lambda *a:None,lambda *a:None)

    def test_existing_request_without_reviewed_snapshot_is_rejected(self):
        write_json(self.folder/'full-source-review-result.json',{})
        with self.assertRaises(ValueError):self.bind()

    def test_changed_text_is_rejected_even_with_updated_hash(self):
        self.bind();self.docs[0]['text']+=' Changed policy.'
        self.docs[0]['text_sha256']=digest(self.docs[0]['text'])
        with self.assertRaisesRegex(ValueError,'contents changed'):self.bind()

    def test_forged_text_hash_rejected(self):
        self.bind();self.docs[0]['text']+=' Changed policy.'
        with self.assertRaisesRegex(ValueError,'text digest'):self.bind()

    def test_changed_raw_bytes_or_url_or_status_rejected(self):
        self.bind();base=copy.deepcopy(self.docs)
        for key,value in (('sha256','0'*64),('bytes',5),('url','https://www.cms.gov/other'),('http_status',403)):
            with self.subTest(key=key):
                self.docs=copy.deepcopy(base);self.docs[0][key]=value
                with self.assertRaises(ValueError):self.bind()

    def test_candidate_change_is_rejected(self):
        self.bind();self.edition['title']='Changed candidate'
        with self.assertRaisesRegex(ValueError,'identity'):self.bind()

    def test_missing_source_is_rejected(self):
        self.bind();self.docs=[]
        with self.assertRaisesRegex(ValueError,'coverage'):self.bind()

    def test_future_or_naive_original_time_rejected(self):
        self.bind();self.docs[0]['retrieved_at']='2026-10-22T09:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'chronology'):self.bind()
        self.docs[0]['retrieved_at']='2026-10-22T11:00:00'
        with self.assertRaisesRegex(ValueError,'chronology'):self.bind()

    def test_symlink_checkpoint_rejected(self):
        self.bind();p=self.folder/'request-evidence.json';target=self.root/'original.json'
        p.rename(target);p.symlink_to(target)
        with self.assertRaisesRegex(ValueError,'Unsafe'):self.bind()

    def test_reports_never_authorize_publication(self):
        self.bind();r=read_json(self.folder.parent/'validation-audit-evidence-reuse.json')
        self.assertIs(r['publication_authorized'],False)
        self.assertIs(r['original_request_signature_still_required'],True)

if __name__=='__main__':unittest.main()
