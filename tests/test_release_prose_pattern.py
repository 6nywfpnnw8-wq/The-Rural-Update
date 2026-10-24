"""A finite pattern-constrained retry and content-free section diagnostics."""
import json,re,unittest
from unittest.mock import Mock
import test_release_prose as fixtures
import release_prose as prose
import release_prose_pattern as pattern
import release_sectioned_narration as sn

class ProsePatternTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ProseTests(methodName='test_compact_schema_and_passes_exact_target');self.f.setUp();self.addCleanup(self.f.doCleanups)
    def seed(self):
        plan=self.f.seed_repair();self.assertTrue(self.f.reserve(plan))
        send=Mock(return_value=fixtures.response(1))
        with self.assertRaises(RuntimeError):self.f.generate(send)
        self.assertEqual(send.call_count,1)
        (self.f.cache/'api-responses.json').write_text(json.dumps({'responses':[{'run_id':str(pattern.FAILURE_RUN),'stage':'narration_section','status':'completed','requested_output_limit':4000}]}))
        plan.update(maximum_prose_pattern_resumes=1,prose_pattern_failure_run_id=pattern.FAILURE_RUN,prose_pattern_maximum_extra_section_requests=2)
        return plan
    def test_regex_enforces_every_existing_word_range(self):
        for _,_,count in sn.SECTION_PLAN:
            rule=prose.prose_schema(count)['properties']['text']['pattern']
            for n in (prose.lower_words(count),count,count+prose.TOLERANCE):
                self.assertIsNotNone(re.fullmatch(rule,' '.join(['word']*(n-1)+['end.'])))
            self.assertIsNone(re.fullmatch(rule,' '.join(['word']*(count+prose.TOLERANCE+1))))
    def test_provider_schema_enforces_bluf_word_range(self):
        field=pattern.generation_schema(165,constrain_words=True)['properties']['text']
        self.assertNotIn('pattern',pattern.generation_schema(165)['properties']['text'])
        rule=prose.prose_schema(165)['properties']['text']['pattern']
        self.assertEqual(field['pattern'],rule)
        valid=' '.join(['word']*154+['ending.'])
        overlong=' '.join(['word']*297+['ending.'])
        self.assertIsNotNone(re.fullmatch(field['pattern'],valid))
        self.assertIsNone(re.fullmatch(field['pattern'],overlong))

    def test_single_repair_preserves_prior_ledgers_and_total_limit(self):
        plan=self.seed();p=self.f.work/'attempts.json';before=p.read_bytes();parent=(self.f.cache/'narration-prose-resume-used.json').read_bytes()
        self.assertTrue(self.f.reserve(plan));self.assertFalse(self.f.reserve(plan));self.assertEqual(p.read_bytes(),before)
        send=Mock(side_effect=self.f.good);self.f.generate(send);self.assertEqual(send.call_count,8)
        state=json.loads(p.read_text());self.assertEqual(state['requests'],14);self.assertEqual(state['attempts']['developments-0'],4)
        self.assertEqual((self.f.cache/'narration-prose-resume-used.json').read_bytes(),parent)
        self.assertEqual(json.loads((self.f.cache/'attempts.json').read_text()),{'attempts':2})
        self.assertFalse((self.f.cache/'approved.json').exists())
    def test_failed_final_repair_cannot_loop(self):
        plan=self.seed();self.assertTrue(self.f.reserve(plan));send=Mock(return_value=fixtures.response(1))
        with self.assertRaises(RuntimeError):self.f.generate(send)
        with self.assertRaises(RuntimeError):self.f.generate(send)
        self.assertEqual(send.call_count,1);self.assertFalse(self.f.reserve(plan))
    def test_absent_pattern_authorization_never_extends(self):
        plan=self.seed();plan.pop('maximum_prose_pattern_resumes');self.assertFalse(self.f.reserve(plan))
    def test_other_response_failure_is_not_pattern_repair(self):
        plan=self.seed();p=self.f.cache/'api-responses.json';d=json.loads(p.read_text());d['responses'][0]['status']='incomplete';p.write_text(json.dumps(d));self.assertFalse(self.f.reserve(plan))
    def test_audited_draft_cannot_be_reopened(self):
        plan=self.seed();(self.f.cache/'audit.json').write_text('{"approved":false}');self.assertFalse(self.f.reserve(plan))
    def test_changed_prerequisite_blocks(self):
        plan=self.seed();p=self.f.folder/'reporting.json';p.write_text(p.read_text()+' ')
        with self.assertRaises(RuntimeError):self.f.reserve(plan)
    def test_section_reports_do_not_expose_prose_or_arbitrary_errors(self):
        pattern.record_section(self.f.cache,'developments-0',1,{'text':'Unpublished sample material.'},ValueError('private error contents'))
        text=(self.f.cache/'validation-narration-sections.json').read_text();self.assertNotIn('Unpublished sample',text);self.assertNotIn('private error',text)
        d=json.loads(text)['sections'][-1];self.assertEqual(d['word_count'],3);self.assertEqual(d['rule'],'unrecognized_section_failure')
    def test_global_twenty_request_ceiling_is_unchanged(self):self.assertEqual(sn.MAX_REQUESTS,20)

if __name__=='__main__':unittest.main()
