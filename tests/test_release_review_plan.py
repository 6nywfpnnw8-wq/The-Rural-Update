"""Validate submitted editorial plans offline; never approve their evidence."""
import unittest
from pathlib import Path
import release_core as core
from release_editorial import fingerprint

class SubmittedPlanTests(unittest.TestCase):
    def test_reviewed_plans_have_valid_structure_and_checksums(self):
        folder=Path(__file__).resolve().parents[1]/'editorial-review'
        for path in folder.glob('*.json'):
            with self.subTest(path=path.name):
                plan=core.read_json(path)
                self.assertIs(plan['publication_authorized'],False)
                self.assertEqual(plan['edition_date'],path.stem)
                self.assertEqual(fingerprint(plan['candidate']),plan['candidate_sha256'])
                core.validate_edition(plan['candidate'],path.stem)
                self.assertEqual(set(plan['reviewed_source_urls']),{s['url'] for s in plan['candidate']['sources']})

if __name__=='__main__': unittest.main()
