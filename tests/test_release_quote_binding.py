"""Deterministic regression checks for observed reviewer formatting differences."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from release_quote_binding import quote_binding
from release_audit_loop import validate_review
from test_release import fixture


class QuoteBindingTests(unittest.TestCase):
    def test_exact_quote(self):
        self.assertEqual(quote_binding('the policy', 'Check the policy.', '/bluf'), 'exact')

    def test_excerpt_first_letter_capitalization(self):
        self.assertEqual(quote_binding('The source states October 1.',
            'Background; the source states October 1.', '/stories/1/what_changed'),
            'initial_sentence_capitalization')

    def test_no_general_case_insensitivity(self):
        self.assertIsNone(quote_binding('The amount is 5 ML.',
            'Background; the amount is 5 mL.', '/stories/1/what_changed'))

    def test_no_changed_date(self):
        self.assertIsNone(quote_binding('The source states October 5.',
            'Background; the source states October 1.', '/stories/1/what_changed'))

    def test_no_removed_negation(self):
        self.assertIsNone(quote_binding('The change is effective.',
            'Background; the change is not effective.', '/bluf'))

    def test_no_paraphrase(self):
        self.assertIsNone(quote_binding('The policy starts in October.',
            'The policy takes effect in October.', '/bluf'))

    def test_no_ellipsis(self):
        self.assertIsNone(quote_binding('The source ... October 1.',
            'The source states October 1.', '/bluf'))

    def test_exact_labeled_date(self):
        self.assertEqual(quote_binding('due_date: "2026-10-21"',
            '2026-10-21', '/actions/0/due_date'), 'exact_labeled_date')

    def test_single_quote_labeled_date(self):
        self.assertEqual(quote_binding("due_date: '2026-10-21'",
            '2026-10-21', '/actions/0/due_date'), 'exact_labeled_date')

    def test_other_date_cannot_bind(self):
        self.assertIsNone(quote_binding('due_date: "2026-10-22"',
            '2026-10-21', '/actions/0/due_date'))

    def test_wrong_label_cannot_bind(self):
        self.assertIsNone(quote_binding('effective_date: "2026-10-21"',
            '2026-10-21', '/actions/0/due_date'))

    def test_wrong_field_cannot_bind(self):
        self.assertIsNone(quote_binding('due_date: "2026-10-21"',
            '2026-10-21', '/deadlines/0/date'))

    def test_extra_claim_cannot_bind(self):
        self.assertIsNone(quote_binding('due_date: "2026-10-21" is mandatory',
            '2026-10-21', '/actions/0/due_date'))

    def test_empty_quote_cannot_bind(self):
        self.assertIsNone(quote_binding('  ', 'anything', '/bluf'))

    def test_blocking_finding_remains_blocking_and_unchanged(self):
        edition=fixture();edition['bluf']='Background; the policy is uncertain.'
        finding={'id':'f1','kind':'unsupported_claim','path':'/bluf',
            'quote':'The policy is uncertain.','source_ids':['s1'],
            'explanation':'Synthetic source mismatch.','required_change':'Correct the claim.'}
        report={'review_complete':True,'findings':[finding]}
        before=copy.deepcopy(report);candidate=copy.deepcopy(edition)
        self.assertEqual(validate_review(report,edition),[finding])
        self.assertEqual(report,before);self.assertEqual(edition,candidate)

    def test_advisory_date_is_preserved_not_deleted(self):
        edition=fixture();edition['actions'][0]['due_date']='2026-10-21'
        finding={'id':'f1','kind':'advisory','path':'/actions/0/due_date',
            'quote':'due_date: "2026-10-21"','source_ids':['s1'],
            'explanation':'Synthetic internal checkpoint.','required_change':'none'}
        report={'review_complete':True,'findings':[finding]};before=copy.deepcopy(report)
        self.assertEqual(validate_review(report,edition),[])
        self.assertEqual(report,before)

    def test_other_invalid_finding_is_not_hidden(self):
        edition=fixture();edition['bluf']='Background; the policy is uncertain.'
        report={'review_complete':True,'findings':[{'id':'f1','kind':'advisory',
            'path':'/bluf','quote':'The policy is certain.','source_ids':['s1'],
            'explanation':'Synthetic.','required_change':'none'}]}
        with self.assertRaisesRegex(ValueError,'does not quote'):validate_review(report,edition)

if __name__=='__main__':unittest.main()
