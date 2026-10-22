"""Calendar projection cannot authorize facts, reset attempts or change dates."""
import copy
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from test_release import fixture, DATE
import release_core as core
import release_pipeline as pipeline
from release_diagnostics import Diagnostics, DiagnosedFailure
from release_deadline_watch import select_upcoming_deadlines, take_deadline_recovery

class DeadlineWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name)
    def expired(self):
        e = fixture()
        old = copy.deepcopy(e['deadlines'][0]); old['date'] = '2026-10-10'
        e['deadlines'].insert(0, old)
        return e
    def retained(self, e=None):
        e = e or self.expired()
        core.write_json(self.cache/'attempts.json', {'attempts': 2})
        d = Diagnostics(self.cache, DATE)
        d.capture('generated', e, [s['url'] for s in e['sources']])
        with self.assertRaises(DiagnosedFailure):
            d.validate(e, core.validate_edition, 'content')
        return e
    def test_reproduces_expired_entry(self):
        with self.assertRaisesRegex(AssertionError, 'next 30 days'):
            core.validate_edition(self.expired(), DATE)
    def test_only_calendar_rows_change(self):
        e=self.expired(); original=copy.deepcopy(e)
        out=select_upcoming_deadlines(e,self.cache)
        self.assertEqual(e,original)
        self.assertEqual(out['deadlines'],original['deadlines'][1:])
        self.assertEqual({k:v for k,v in out.items() if k!='deadlines'},
                         {k:v for k,v in original.items() if k!='deadlines'})
        core.validate_edition(out,DATE)
    def test_window_boundaries_and_long_range(self):
        e=fixture(); row=e['deadlines'][0]
        e['deadlines']=[dict(row,date=(date.fromisoformat(DATE)+timedelta(days=n)).isoformat()) for n in [-1,0,30,31]]
        out=select_upcoming_deadlines(e,self.cache)
        self.assertEqual(out['deadlines'],e['deadlines'][1:3])
    def test_empty_watch_needs_no_invented_event(self):
        e=self.expired(); e['deadlines']=e['deadlines'][:1]
        out=select_upcoming_deadlines(e,self.cache)
        self.assertEqual(out['deadlines'],[])
        core.validate_edition(out,DATE)
    def test_valid_watch_is_noop(self):
        e=fixture()
        self.assertIs(select_upcoming_deadlines(e,self.cache),e)
        self.assertEqual(list(self.cache.iterdir()),[])
    def test_original_retained_without_approval(self):
        e=self.expired(); out=select_upcoming_deadlines(e,self.cache)
        report=core.read_json(self.cache/'validation-deadline-watch.json')
        original=core.read_json(self.cache/report['retained_original']['file'])
        self.assertEqual(original['candidate'],e)
        self.assertFalse(report['publication_authorized'])
        self.assertTrue(report['evidence_review_required'])
        self.assertFalse(report['dates_changed'])
        self.assertFalse((self.cache/'approved.json').exists())
        self.assertNotEqual(report['original_candidate_sha256'],report['selected_candidate_sha256'])
    def test_unresolved_source_in_expired_row_not_discarded(self):
        e=self.expired(); e['deadlines'][0]['source_ids']=['invented']
        out=select_upcoming_deadlines(e,self.cache)
        self.assertIs(out,e)
        with self.assertRaisesRegex(AssertionError,'Unresolved source'):
            core.validate_edition(out,DATE)
    def test_other_earlier_validation_error_is_not_hidden(self):
        e=self.expired(); e['sources'][0]['url']='https://127.0.0.1/private'
        self.assertIs(select_upcoming_deadlines(e,self.cache),e)
        with self.assertRaisesRegex(AssertionError,'approved public domains'):
            core.validate_edition(e,DATE)
    def test_other_later_validation_error_stays_blocked(self):
        e=self.expired(); e['actions'][0]['due_date']='2026-10-10'
        out=select_upcoming_deadlines(e,self.cache)
        with self.assertRaisesRegex(AssertionError,'Action due date is already past'):
            core.validate_edition(out,DATE)
    def test_same_date_recovery_preserves_ledger_and_provenance(self):
        self.retained(); before=(self.cache/'attempts.json').read_bytes()
        out,urls=take_deadline_recovery(self.cache,DATE)
        self.assertEqual(out['deadlines'],fixture()['deadlines'])
        self.assertEqual(urls,{core.canonical_url(s['url']) for s in out['sources']})
        self.assertEqual(before,(self.cache/'attempts.json').read_bytes())
        self.assertFalse((self.cache/'approved.json').exists())
    def test_missing_matching_generated_snapshot_fails(self):
        self.retained()
        for p in (self.cache/'candidates').glob('generated-*.json'):p.unlink()
        with self.assertRaisesRegex(ValueError,'provenance'):
            take_deadline_recovery(self.cache,DATE)
    def test_changed_facts_cannot_borrow_provenance(self):
        self.retained()
        for p in (self.cache/'candidates').glob('generated-*.json'):p.unlink()
        different=self.expired(); different['stories'][0]['what_changed']='Different factual statement.'
        Diagnostics(self.cache,DATE).capture('generated',different,[s['url'] for s in different['sources']])
        with self.assertRaisesRegex(ValueError,'provenance'):
            take_deadline_recovery(self.cache,DATE)
    def test_changed_retained_snapshot_fails(self):
        self.retained()
        p=next((self.cache/'candidates').glob('content-*.json'))
        obj=core.read_json(p);obj['candidate']['title']='Changed';core.write_json(p,obj)
        with self.assertRaisesRegex(ValueError,'integrity'):
            take_deadline_recovery(self.cache,DATE)
    def test_wrong_date_is_not_recovered(self):
        self.retained();self.assertIsNone(take_deadline_recovery(self.cache,'2026-10-12'))
    def test_existing_audit_or_reservation_cannot_be_reopened(self):
        self.retained()
        for name in ('audit.json','approved.json','audit-bound.json','editorial-loop-v1/original.json'):
            p=self.cache/name;core.write_json(p,{'approved':False})
            self.assertIsNone(take_deadline_recovery(self.cache,DATE));p.unlink()
    def test_no_research_generation_and_full_audit_still_required(self):
        self.retained(); sentinel=object()
        with patch.dict('os.environ',{'RURAL_UPDATE_STRUCTURED_REVIEW':'true'}), \
             patch.object(pipeline,'request_api',side_effect=AssertionError('No generation')), \
             patch.object(pipeline,'collect_source_evidence',return_value=[]) as collect, \
             patch.object(pipeline,'evidence_urls',return_value=set()), \
             patch('release_audit_loop.audit_and_correct',return_value=sentinel) as audit:
            self.assertIs(pipeline.research(DATE,{},self.cache),sentinel)
        collect.assert_called_once();audit.assert_called_once()
        self.assertEqual(core.read_json(self.cache/'attempts.json'),{'attempts':2})
    def test_source_failure_stops_before_audit(self):
        self.retained()
        with patch.dict('os.environ',{'RURAL_UPDATE_STRUCTURED_REVIEW':'true'}), \
             patch.object(pipeline,'request_api',side_effect=AssertionError('No generation')), \
             patch.object(pipeline,'collect_source_evidence',side_effect=RuntimeError('Source unavailable')), \
             patch('release_audit_loop.audit_and_correct') as audit:
            with self.assertRaises(DiagnosedFailure):pipeline.research(DATE,{},self.cache)
        audit.assert_not_called()
    def test_editorial_rejection_does_not_become_approval(self):
        self.retained()
        with patch.dict('os.environ',{'RURAL_UPDATE_STRUCTURED_REVIEW':'true'}), \
             patch.object(pipeline,'request_api',side_effect=AssertionError('No generation')), \
             patch.object(pipeline,'collect_source_evidence',return_value=[]), \
             patch.object(pipeline,'evidence_urls',return_value=set()), \
             patch('release_audit_loop.audit_and_correct',side_effect=RuntimeError('Blocking findings')):
            with self.assertRaisesRegex(RuntimeError,'Blocking findings'):
                pipeline.research(DATE,{},self.cache)
        self.assertFalse((self.cache/'approved.json').exists())

if __name__=='__main__':unittest.main()
