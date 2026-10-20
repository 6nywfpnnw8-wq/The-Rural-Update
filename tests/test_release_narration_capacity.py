"""No API calls: an observed reasoning-capacity stop cannot reset budgets."""
import json
import unittest
from pathlib import Path
import test_release_sectioned_narration as fixtures
import release_sectioned_narration as sn


class NarrationCapacityTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.NarrationReservationTests(methodName='test_single_reviewed_resume_without_reset')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.root=fixture.root;self.plan=fixture.plan;self.engine=fixture.engine
        self.validator=fixture.validator
        self.assertTrue(fixture.reserve())
        self.plan.update(maximum_narration_capacity_resumes=1,
                         previous_section_output_limit=2200,
                         corrected_section_output_limit=4000,
                         corrected_section_reasoning_effort='minimal')
        self.row={'stage':'narration_section','status':'incomplete',
                  'incomplete_reason':'max_output_tokens','requested_output_limit':2200,
                  'reasoning_tokens':2176}
        self.metadata=self.root/'api-responses.json';self.save_metadata()
        self.ledger=self.root/self.engine/sn.METHOD/'synthetic-section'/'attempts.json'
        self.ledger.parent.mkdir(parents=True)
        self.state={'identity':'synthetic-section','attempts':{'opening-None':1},
                    'requests':1,'publication_authorized':False}
        self.ledger.write_text(json.dumps(self.state))

    def save_metadata(self):self.metadata.write_text(json.dumps({'responses':[self.row]}))
    def reserve(self):return sn.reserve_narration_resume(self.root,self.plan,self.engine,fixtures.load,self.validator)

    def test_resume_once_with_existing_section_and_editorial_counts(self):
        names=['attempts.json','corrective-generation-used.json','narration-limit-resume-used.json']
        before={n:(self.root/n).read_bytes() for n in names};section=self.ledger.read_bytes()
        self.assertTrue(self.reserve());self.assertFalse(self.reserve())
        for n,old in before.items():self.assertEqual((self.root/n).read_bytes(),old)
        self.assertEqual(self.ledger.read_bytes(),section)
        result=json.loads((self.root/'narration-capacity-resume-used.json').read_text())
        self.assertIs(result['publication_authorized'],False)
        self.assertEqual(result['observed_section_requests'],1)
        self.assertEqual(result['maximum_total_section_requests'],20)

    def test_no_second_capacity_allowance(self):
        self.assertTrue(self.reserve());self.assertFalse(self.reserve())

    def test_no_cap_review_plan_means_no_resume(self):
        self.plan.pop('maximum_narration_capacity_resumes');self.assertFalse(self.reserve())

    def test_wrong_cap_not_silently_accepted(self):
        self.plan['corrected_section_output_limit']=100000
        with self.assertRaises(RuntimeError):self.reserve()

    def test_another_failure_is_not_a_capacity_repair(self):
        self.row['incomplete_reason']='content_filter';self.save_metadata()
        self.assertFalse(self.reserve())

    def test_visible_output_limit_without_measured_reasoning_does_not_qualify(self):
        self.row['reasoning_tokens']=0;self.save_metadata()
        self.assertFalse(self.reserve())

    def test_exhausted_section_budget_is_not_reset(self):
        self.state['attempts']={f'{n}-{i}':2 for n,i,_ in sn.SECTION_PLAN}
        self.state['requests']=20;self.ledger.write_text(json.dumps(self.state))
        self.assertFalse(self.reserve())

    def test_prior_audit_blocks_capacity_replay(self):
        (self.root/'audit.json').write_text('{"approved":false}')
        self.assertFalse(self.reserve())

    def test_changed_prerequisite_does_not_trigger_new_reporting(self):
        (self.root/self.engine/'reporting.json').write_text('{}')
        with self.assertRaises(RuntimeError):self.reserve()

    def test_same_reservation_cannot_cross_dates(self):
        self.plan['edition_date']='2026-10-21';self.assertFalse(self.reserve())


if __name__=='__main__':unittest.main()
