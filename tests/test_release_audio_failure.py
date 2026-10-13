"""Ensure RSS failures do not discard the valid text-only release or prior feed."""
import unittest
from unittest.mock import patch
import test_release as fixtures
import release_pipeline as pipeline


class PodcastFinalizationTests(unittest.TestCase):
    def setUp(self):
        self.compiler = fixtures.CompilerTests(methodName='test_complete_bundle_and_same_day_archive')
        self.compiler.setUp()
        self.addCleanup(self.compiler.tearDown)

    def test_feed_failure_keeps_text_and_prior_feed(self):
        root = self.compiler.root
        feed = root / 'podcast.xml'
        original = feed.read_bytes()

        def fail_feed(*args):
            feed.write_text('<rss>incomplete output', encoding='utf-8')
            raise RuntimeError('Simulated feed-generation interruption')

        with patch.object(pipeline, 'update_feed', side_effect=fail_feed):
            manifest = self.compiler.build()
        self.assertEqual(manifest['audio_status'], 'unavailable')
        self.assertEqual(feed.read_bytes(), original)
        self.assertNotIn(f'audio/{fixtures.DATE}.mp3', manifest['files'])
        self.assertIn(f'transcript/{fixtures.DATE}.html', manifest['files'])
        self.assertNotIn('audio_published_at', manifest)
        self.assertFalse((root / f'audio/{fixtures.DATE}.mp3').exists())

    def test_first_feed_failure_removes_partial_feed(self):
        root = self.compiler.root
        feed = root / 'podcast.xml'
        feed.unlink()

        def fail_feed(*args):
            feed.write_text('<rss>incomplete output', encoding='utf-8')
            raise RuntimeError('Simulated first-feed failure')

        with patch.object(pipeline, 'update_feed', side_effect=fail_feed):
            manifest = self.compiler.build()
        self.assertEqual(manifest['audio_status'], 'unavailable')
        self.assertFalse(feed.exists())
        self.assertNotIn('podcast.xml', manifest['files'])
        self.assertIn(f'transcript/{fixtures.DATE}.html', manifest['files'])


if __name__ == '__main__':
    unittest.main()
