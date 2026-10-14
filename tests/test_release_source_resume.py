"""Citation-label repair of a retained draft still enters the full evidence audit."""
import unittest
from unittest.mock import Mock, patch
import test_release_resume as fixtures
from test_release_resume_integration import audit_response
from test_release import DATE
import release_pipeline as pipeline

class SourceResumeTests(unittest.TestCase):
    def test_punctuation_and_label_repair_preserves_sources_and_audits(self):
        f=fixtures.StyleRecoveryTests(methodName='test_no_candidate_is_not_invented')
        f.setUp();self.addCleanup(f.doCleanups)
        for source in f.candidate['sources']:source['id']=source['id'].upper()
        for group in ('stories','actions','deadlines','signals','issue_updates'):
            for item in f.candidate[group]:item['source_ids']=[v.upper() for v in item['source_ids']]
        f.save(f.candidate)
        api=Mock(return_value=audit_response())
        with patch.object(pipeline,'request_api',api):
            record=pipeline.research(DATE,{},f.cache)
        self.assertEqual(api.call_count,1)
        self.assertEqual(api.call_args.args[0]['text']['format']['name'],'editorial_audit')
        self.assertEqual([s['url'] for s in record['edition']['sources']],
                         [s['url'] for s in f.candidate['sources']])
        self.assertTrue(all(s['id'].islower() for s in record['edition']['sources']))
        self.assertTrue(record['audit']['approved'])

if __name__=='__main__':unittest.main()
