"""Read actual PDF bytes offline; source minimums and independent audit still apply."""
import io
import json
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from pypdf import PdfWriter
from pypdf.generic import NameObject,DictionaryObject,DecodedStreamObject
import release_evidence as evidence
import release_research as research
import release_audit_loop as audit
from release_core import digest,write_json,read_json
from test_release import fixture

TEXT='Verified synthetic billing guidance: effective October 1, 2026; implementation October 5, 2026. '


def pdf_bytes(pages=2,blank=False,encrypted=False):
    writer=PdfWriter()
    for n in range(pages):
        page=writer.add_blank_page(width=612,height=792)
        if not blank:
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),
                NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):
                DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
            stream=DecodedStreamObject()
            stream.set_data(('BT /F1 12 Tf 50 700 Td ('+TEXT*2+str(n)+') Tj ET').encode())
            page[NameObject('/Contents')]=writer._add_object(stream)
    if encrypted:writer.encrypt('fixture-password')
    result=io.BytesIO();writer.write(result);return result.getvalue()


class PDFEvidenceTests(unittest.TestCase):
    def fetch(self,raw,mime='application/pdf',url='https://www.cms.gov/verified.pdf'):
        headers=Message();headers['Content-Type']=mime
        response=Mock(status=200,headers=headers)
        response.geturl.return_value=url;response.read.return_value=raw
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        opener=Mock();opener.open.return_value=response
        with patch.object(evidence,'require_public_url'),patch.object(evidence.urllib.request,'build_opener',return_value=opener):
            return evidence.fetch_source(url)

    def test_all_pages_and_both_byte_and_text_hashes_are_retained(self):
        raw=pdf_bytes();document=self.fetch(raw)
        self.assertEqual(document['sha256'],digest(raw))
        self.assertEqual(document['text_sha256'],digest(document['text']))
        self.assertIn('October 1, 2026',document['text'])
        self.assertIn('[PDF page 2 of 2]',document['text'])
        self.assertEqual(document['extraction']['page_count'],2)
        self.assertEqual([p['page'] for p in document['extraction']['pages']],[1,2])
        self.assertFalse(document['extraction']['ocr_used'])

    def test_image_only_and_encrypted_documents_are_rejected(self):
        for raw,reason in [(pdf_bytes(blank=True),'readable text'),(pdf_bytes(encrypted=True),'Encrypted')]:
            with self.subTest(reason=reason),self.assertRaisesRegex(ValueError,reason):self.fetch(raw)

    def test_pdf_disguised_as_html_or_invalid_bytes_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'non-PDF'):self.fetch(b'<html>Blocked</html>','text/html')
        with self.assertRaisesRegex(ValueError,'signature'):self.fetch(b'<html>Blocked</html>')

    def test_page_stream_text_and_response_size_limits_are_enforced(self):
        raw=pdf_bytes()
        with patch.object(evidence,'MAX_PDF_PAGES',1),self.assertRaisesRegex(ValueError,'page count'):self.fetch(raw)
        with patch.object(evidence,'MAX_PDF_PAGE_STREAM_BYTES',10),self.assertRaisesRegex(ValueError,'stream'):self.fetch(raw)
        with patch.object(evidence,'MAX_SOURCE_CHARS',100),self.assertRaisesRegex(ValueError,'size limit'):self.fetch(raw)
        with patch.object(evidence,'MAX_BYTES',100),self.assertRaisesRegex(ValueError,'byte limit'):self.fetch(raw)

    def test_original_redirect_and_public_address_checks_are_preserved(self):
        with self.assertRaises(ValueError):
            evidence.PublicRedirects().redirect_request(None,None,302,'',{},'https://private.example/file.pdf')

    def test_pdf_sources_are_observed_tool_events_not_urls_in_notes(self):
        urls=[s['url'] for s in fixture()['sources']]
        pdf='https://www.govinfo.gov/content/pkg/FR-2026-07-23/pdf/2026-14897.pdf'
        discovery={'notes':'https://www.cms.gov/invented.pdf','web_search_items':[
            {'type':'web_search_call','action':{'sources':[{'url':u} for u in urls+[pdf]]}}]}
        self.assertIn(pdf,research.observed_source_urls(discovery))
        self.assertNotIn(pdf,research.observed_html_urls(discovery))
        self.assertNotIn('https://www.cms.gov/invented.pdf',research.observed_source_urls(discovery))

    def test_pdf_retrieval_does_not_create_an_approval(self):
        document=self.fetch(pdf_bytes())
        self.assertNotIn('approved',document)
        self.assertEqual(document['method'],'direct_https')

    def test_reviewer_gets_explicit_text_only_extraction_limits(self):
        document=self.fetch(pdf_bytes());document['source_id']='pdf-source'
        for prompt in (evidence.evidence_prompt([document]),audit.evidence_prompt([document])):
            self.assertIn('"text_only": true',prompt)
            self.assertIn('"images_reviewed": false',prompt)

    def test_changed_format_cannot_turn_a_retained_repair_into_new_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)/'2026-10-31'
            write_json(cache/'attempts.json',{'attempts':2})
            write_json(cache/'coverage-plan-repair-authorized.json',{
                'identity':'a'*64,'edition_date':'2026-10-31','publication_authorized':False,
                'new_discovery_prohibited':True,'new_source_selection_prohibited':True})
            send=Mock()
            with self.assertRaisesRegex(RuntimeError,'identity differs'):
                research.staged_request({'model':'test','input':'App format after migration','tools':[]},send,cache)
            send.assert_not_called()
            self.assertEqual(read_json(cache/'attempts.json'),{'attempts':2})


if __name__=='__main__':unittest.main()
