"""Wrong advisory anchors can bind only by one long, unchanged exact quotation."""
import copy
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from release_quote_binding import finding_binding
from release_audit_loop import validate_review, text_fields
from test_release import fixture

QUOTE='Sources include verified federal publications and state program guidance for this briefing.'

class AdvisoryAnchorTests(unittest.TestCase):
    def setUp(self):
        self.edition=fixture()
        self.edition['bluf']=QUOTE
        self.edition['signals'][0]['summary']='A distinct supported planning signal.'
        self.finding={'id':'meta1','kind':'advisory','path':'/signals/0/summary',
            'quote':QUOTE,'source_ids':[self.edition['sources'][0]['id']],
            'explanation':'Optional source metadata improvement; no unsupported claim found.',
            'required_change':''}
        self.report={'review_complete':True,'findings':[self.finding]}

    def resolve(self):
        return finding_binding(self.finding,text_fields(self.edition))

    def test_unique_exact_advisory_resolves(self):
        self.assertEqual(self.resolve(),'/bluf')

    def test_existing_exact_binding_is_unchanged(self):
        self.finding['path']='/bluf'
        self.assertEqual(self.resolve(),'/bluf')

    def test_blocking_finding_never_relocated(self):
        self.finding.update(kind='unsupported_claim',required_change='Correct this claim.')
        self.assertIsNone(self.resolve())
        with self.assertRaisesRegex(ValueError,'does not quote'):
            validate_review(self.report,self.edition)

    def test_correctly_anchored_blocking_finding_still_blocks(self):
        self.finding.update(kind='unsupported_claim',path='/bluf',required_change='Correct this claim.')
        self.assertEqual(validate_review(self.report,self.edition),[self.finding])

    def test_required_change_prevents_relocation(self):
        self.finding['required_change']='A change is required.'
        self.assertIsNone(self.resolve())

    def test_multiple_matching_fields_rejected(self):
        self.edition['title']=QUOTE
        self.assertIsNone(self.resolve())

    def test_repeated_quote_in_one_field_rejected(self):
        self.edition['bluf']=QUOTE+' '+QUOTE
        self.assertIsNone(self.resolve())

    def test_short_quote_rejected(self):
        self.finding['quote']='Sources include'
        self.assertIsNone(self.resolve())

    def test_paraphrase_and_changed_negation_rejected(self):
        for q in (QUOTE.replace('verified','unverified'),QUOTE.replace('include','do not include')):
            with self.subTest(q=q):
                self.finding['quote']=q
                self.assertIsNone(self.resolve())

    def test_no_cross_field_case_folding(self):
        self.finding['quote']=QUOTE.lower()
        self.assertIsNone(self.resolve())

    def test_unknown_original_path_rejected(self):
        self.finding['path']='/not-a-prose-field'
        self.assertIsNone(self.resolve())

    def test_incomplete_review_remains_rejected(self):
        self.report['review_complete']=False
        with self.assertRaisesRegex(RuntimeError,'incomplete'):
            validate_review(self.report,self.edition)

    def test_duplicate_sources_still_rejected(self):
        self.finding['source_ids']*=2
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError,'Duplicate audit source'):
                validate_review(self.report,self.edition)

    def test_raw_review_and_candidate_unchanged(self):
        before=copy.deepcopy((self.report,self.edition))
        log=io.StringIO()
        with redirect_stdout(log):
            self.assertEqual(validate_review(self.report,self.edition),[])
        self.assertEqual((self.report,self.edition),before)
        self.assertIn('"reported_path": "/signals/0/summary"',log.getvalue())
        self.assertIn('"bound_path": "/bluf"',log.getvalue())
        self.assertNotIn(QUOTE,log.getvalue())

if __name__=='__main__':unittest.main()
