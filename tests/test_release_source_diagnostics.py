import copy
import json
import unittest
from test_release import fixture
from release_source_diagnostics import inspect_source_labels


class SourceDiagnosticsTests(unittest.TestCase):
    def test_intact_relationships(self):
        report = inspect_source_labels(fixture())
        self.assertEqual(report['unresolved_references'], [])
        self.assertEqual(report['source_count'], 5)
        self.assertFalse(report['publication_authorized'])

    def test_case_only_mismatch_is_distinguished_without_repair(self):
        candidate = fixture(); candidate['stories'][0]['source_ids'] = ['S1']
        before = copy.deepcopy(candidate)
        report = inspect_source_labels(candidate)
        self.assertEqual(candidate, before)
        self.assertEqual(report['unresolved_references'][0], {
            'path': '/stories/0/source_ids/0', 'is_string': True,
            'casefold_matches': 1, 'canonical_matches': 1})

    def test_unknown_source_is_not_assigned(self):
        candidate = fixture(); candidate['actions'][0]['source_ids'] = ['UNKNOWN']
        report = inspect_source_labels(candidate)
        self.assertEqual(report['unresolved_references'][0]['canonical_matches'], 0)
        self.assertNotIn('UNKNOWN', json.dumps(report))

    def test_source_values_and_urls_are_not_exposed(self):
        candidate = fixture(); candidate['sources'][0]['id'] = 'Private secret label'
        candidate['sources'][0]['url'] = 'https://example.invalid/private'
        report = inspect_source_labels(candidate)
        self.assertNotIn('Private', json.dumps(report))
        self.assertNotIn('https:', json.dumps(report))

    def test_collisions_reported_not_merged(self):
        candidate = fixture(); candidate['sources'][1]['id'] = 'S1'
        report = inspect_source_labels(candidate)
        self.assertEqual(report['canonical_collision_count'], 1)
        self.assertEqual(len(candidate['sources']), 5)

if __name__ == '__main__': unittest.main()
