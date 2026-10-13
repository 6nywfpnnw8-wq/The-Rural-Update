"""Read-only compatibility tests against the actual repository, never production writes."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import release_core as core
import release_pipeline as pipeline
from test_release import fixture


@unittest.skipUnless((ROOT / 'index.html').is_file(), 'Requires the existing repository, not only the overlay ZIP')
class RepositoryCompatibilityTests(unittest.TestCase):
    def test_existing_required_assets(self):
        for relative in ('index.html', 'manifest.webmanifest', 'intelligence.js',
                         'signals-reference.js', 'archive/catalog.json',
                         'scripts/generate_podcast_audio.py', 'icons/icon-512.png'):
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file(), relative)
        manifest = json.loads((ROOT / 'manifest.webmanifest').read_text())
        self.assertTrue(manifest.get('start_url'))

    def test_existing_public_intelligence_exports(self):
        state = pipeline.migrate_legacy(ROOT)
        self.assertIsInstance(state['intelligence']['issues'], list)
        self.assertIsInstance(state['intelligence']['actions'], list)
        self.assertIsInstance(state['signals'], list)
        for group in (state['intelligence']['issues'], state['intelligence']['actions'], state['signals']):
            ids = [item['id'] for item in group]
            self.assertEqual(len(ids), len(set(ids)))

    def test_existing_archive_catalog(self):
        core.validate_catalog(ROOT, core.read_json(ROOT / 'archive/catalog.json'))

    def test_actual_template_compiles_in_temporary_directory(self):
        # The fixture is synthetic; only a temporary directory receives output.
        candidate = fixture()
        prior = pipeline.migrate_legacy(ROOT)
        intelligence = core.merge_intelligence(prior['intelligence'], candidate)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'index.html').write_text((ROOT / 'index.html').read_text(), encoding='utf-8')
            output = core.render(root, candidate, intelligence, prior['signals'],
                                 {'editions': []}, 'Synthetic compatibility test only')
        document = BeautifulSoup(output, 'html.parser')
        for section in ('today', 'signals', 'archive'):
            self.assertEqual(len(document.select('#page-' + section)), 1)
        self.assertEqual(len(document.select('#daily-audio')), 1)
        self.assertEqual([s.get('src') for s in document.find_all('script')],
                         ['web/release-runtime.js'])
        self.assertEqual(len(document.select('.tab-btn[data-tab]')), 3)


if __name__ == '__main__':
    unittest.main()
