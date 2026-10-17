"""Optional clock tests. No network access or secrets."""
import sys,unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ops'))
from trigger_publisher import decide,run_once,TZ,API,PUBLIC,Client

class ExternalClockTests(unittest.TestCase):
    def now(self,stamp='2026-10-18T10:05:00+00:00'):return datetime.fromisoformat(stamp)
    def job(self,**kw):
        return {'head_branch':'main','status':'completed','run_attempt':1,
                'run_started_at':'2026-10-18T10:02:00Z',**kw}
    def test_dst_summer_clock(self):self.assertEqual(decide(self.now(),None,[])['action'],'dispatch')
    def test_dst_winter_clock(self):self.assertEqual(decide(self.now('2026-11-02T11:05:00+00:00'),None,[])['action'],'dispatch')
    def test_early_winter_utc_skipped(self):self.assertEqual(decide(self.now('2026-11-02T10:05:00+00:00'),None,[])['action'],'skip')
    def test_outside_window_skips_without_network(self):
        client=Mock();result=run_once(client,self.now('2026-10-18T15:00:00+00:00'),True)
        self.assertEqual(result['action'],'skip');client.get.assert_not_called();client.dispatch.assert_not_called()
    def test_complete_manifest_not_called_delivery_verification(self):
        result=decide(self.now(),{'edition_date':'2026-10-18','audio_status':'complete'},[])
        self.assertEqual(result['action'],'skip');self.assertFalse(result['public_delivery_verified'])
    def test_active_publisher_prevents_duplicate(self):self.assertEqual(decide(self.now(),None,[self.job(status='in_progress')])['action'],'skip')
    def test_waiting_for_approval_prevents_duplicate(self):self.assertEqual(decide(self.now(),None,[self.job(status='waiting')])['action'],'skip')
    def test_two_observed_attempts_do_not_reset_budget(self):self.assertEqual(decide(self.now(),None,[self.job(run_attempt=2)])['action'],'alert')
    def test_old_failures_not_counted_as_today(self):self.assertEqual(decide(self.now(),None,[self.job(run_started_at='2026-10-17T10:05:00Z',run_attempt=2)])['action'],'dispatch')
    def test_dry_run_does_not_dispatch(self):
        client=Mock();client.get.side_effect=[{'edition_date':'2026-10-17'}, {'workflow_runs':[]}]
        result=run_once(client,self.now());self.assertTrue(result['dry_run']);client.dispatch.assert_not_called()
    def test_concurrent_publisher_recheck_stops_dispatch(self):
        client=Mock();client.get.side_effect=[{}, {'workflow_runs':[]}, {'workflow_runs':[self.job(status='queued')]}]
        result=run_once(client,self.now(),True);self.assertEqual(result['action'],'skip');client.dispatch.assert_not_called()
    def test_one_dispatch_to_existing_publisher(self):
        client=Mock();client.get.side_effect=[{}, {'workflow_runs':[]}, {'workflow_runs':[]}]
        client.dispatch.return_value={'dispatch_accepted':True,'publication_complete':False}
        result=run_once(client,self.now(),True);client.dispatch.assert_called_once_with('2026-10-18')
        self.assertFalse(result['publication_complete'])
    def test_unknown_post_failure_not_retried(self):
        client=Mock();client.get.side_effect=[{}, {'workflow_runs':[]}, {'workflow_runs':[]}];client.dispatch.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):run_once(client,self.now(),True)
        self.assertEqual(client.dispatch.call_count,1)
    def test_malformed_run_history_stops(self):
        client=Mock();client.get.side_effect=[{}, {'unexpected':True}]
        with self.assertRaises(RuntimeError):run_once(client,self.now(),True)
        client.dispatch.assert_not_called()
    def test_no_token_to_public_server(self):
        with self.assertRaises(ValueError):Client('synthetic').get(PUBLIC,authenticated=True)
    def test_future_release_alerts(self):self.assertEqual(decide(self.now(),{'edition_date':'2026-10-19'},[])['action'],'alert')
    def test_naive_clock_rejected(self):
        with self.assertRaises(ValueError):decide(datetime(2026,10,18),None,[])

if __name__=='__main__':unittest.main()
