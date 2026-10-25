"""Development isolation, persistent request ceilings, and nonpublication controls."""
import copy
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / name) for name in ('scripts', 'ops')]
import integration_acceptance as acceptance
import release_pipeline as publisher
import release_research as research
from release_core import digest, read_json, write_json
from release_integration_budget import DevelopmentTransport, DevelopmentBudgetExceeded
from test_release_staged_research import bounded_fixture, response, DATE


class HTTPResponse(io.BytesIO):
    status = 200
    headers = {'Content-Type': 'application/json'}
    def geturl(self):return 'https://api.openai.com/v1/responses'


def request(name='reporting'):
    payload = {'model': 'gpt-5-mini', 'input': 'Do not retain this request prompt',
               'max_output_tokens': 100, 'text': {'format': {'name': name}}}
    return urllib.request.Request('https://api.openai.com/v1/responses',
                                  data=json.dumps(payload).encode(), method='POST')


class DevelopmentTransportTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.state = Path(self.t.name)
        self.upstream = Mock(side_effect=lambda *a, **k: HTTPResponse(json.dumps(response('Visible test output')).encode()))
        self.transport = DevelopmentTransport(self.state, self.upstream)

    def test_stage_limit_persists_across_instances(self):
        with self.transport(request()) as r:self.assertEqual(json.load(r)['status'], 'completed')
        with DevelopmentTransport(self.state, self.upstream)(request()):pass
        with self.assertRaises(DevelopmentBudgetExceeded):self.transport(request())
        self.assertEqual(self.upstream.call_count, 2)
        self.assertEqual(len(read_json(self.transport.ledger)['requests']), 2)

    def test_discovery_and_source_selection_are_blocked_before_submission(self):
        for name in ('sources', 'other', None):
            with self.assertRaises(RuntimeError):self.transport(request(name))
        self.upstream.assert_not_called()

    def test_excessive_token_request_is_blocked_before_submission(self):
        req = request();value = json.loads(req.data);value['max_output_tokens'] = 100000
        req.data = json.dumps(value).encode()
        with self.assertRaisesRegex(RuntimeError, 'output-token'):self.transport(req)
        self.upstream.assert_not_called()

    def test_nonprovider_writes_are_blocked(self):
        req = urllib.request.Request('https://api.github.com/repos/example/repo', data=b'{}', method='POST')
        with self.assertRaises(RuntimeError):self.transport(req)
        self.upstream.assert_not_called()

    def test_reservation_precedes_transport_and_response_is_retained(self):
        def upstream(req, **kwargs):
            rows = read_json(self.transport.ledger)['requests']
            self.assertEqual(rows[-1]['state'], 'reserved')
            return HTTPResponse(json.dumps(response('Visible test output')).encode())
        self.transport.upstream = upstream
        with self.transport(request()):
            self.assertTrue((self.state / 'provider-responses/001.json').exists())
        saved = read_json(self.state / 'provider-responses/001.json')
        self.assertIs(saved['publication_authorized'], False)
        self.assertEqual(saved['visible_text'], 'Visible test output')

    def test_prompts_and_reasoning_are_excluded_and_credentials_redacted(self):
        raw = response('test-dev-secret-123456');raw['output'].insert(0, {'type': 'reasoning', 'summary': 'Hidden internal text'})
        self.transport.upstream = Mock(return_value=HTTPResponse(json.dumps(raw).encode()))
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-dev-secret-123456'}):
            with self.transport(request()):pass
        saved = (self.state / 'provider-responses/001.json').read_text()
        for value in ('test-dev-secret-123456', 'Hidden internal text', 'Do not retain this request prompt'):
            self.assertNotIn(value, saved)

    def test_http_retries_consume_actual_submission_counts(self):
        self.transport.upstream = Mock(side_effect=urllib.error.HTTPError('https://api.openai.com', 429, '', {}, None))
        for _ in range(2):
            with self.assertRaises(urllib.error.HTTPError):self.transport(request())
        with self.assertRaises(DevelopmentBudgetExceeded):self.transport(request())
        self.assertEqual(self.transport.upstream.call_count, 2)

    def test_ambiguous_submission_is_not_automatically_repeated(self):
        self.transport.upstream = Mock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError):self.transport(request())
        with self.assertRaisesRegex(RuntimeError, 'Ambiguous'):self.transport(request())
        self.assertEqual(self.transport.upstream.call_count, 1)

    def test_missing_ledger_after_provider_work_is_not_a_fresh_budget(self):
        with self.transport(request()):pass
        self.transport.ledger.unlink()
        with self.assertRaisesRegex(RuntimeError, 'ledger is missing'):self.transport(request())
        self.assertEqual(self.upstream.call_count, 1)

    def test_modified_budget_limits_fail_closed(self):
        with self.transport(request()):pass
        ledger = read_json(self.transport.ledger);ledger['limits']['responses'] = 500
        write_json(self.transport.ledger, ledger)
        with self.assertRaises(RuntimeError):self.transport(request())
        self.assertEqual(self.upstream.call_count, 1)


class IntegrationIsolationTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name);self.state = self.root / '.integration-state'
        write_json(self.root / 'release.json', {'edition_date': '2026-10-10'})
        (self.root / 'index.html').write_text('<html><head></head><body>Existing public edition</body></html>')
        write_json(self.root / 'data/intelligence.json', {'issues': [], 'actions': []})
        write_json(self.root / 'data/signals.json', [])
        cache = self.root / '.release-cache' / DATE;self.cache = cache
        write_json(cache / 'attempts.json', {'attempts': 2})
        write_json(cache / 'retained-discovery-continuation-used.json', {'spent': True})
        with patch.object(publisher, 'MODEL', 'gpt-5-mini'):
            payload = publisher.research_payload(DATE, publisher.migrate_legacy(self.root))
        identity = digest(json.dumps({'engine': research.ENGINE, 'model': payload['model'], 'context': payload['input']}, sort_keys=True))
        discovery = {'notes': 'Retained synthetic source notes.', 'web_search_items': research._web_items(response('notes', web=True)), 'usage': None}
        research._save(cache / research.ENGINE / 'discovery.json', identity, discovery)
        research._save(cache / research.ENGINE / 'sources.json', identity, {'sources': bounded_fixture()['sources'], 'usage': None})
        self.plan = {'schema_version': 1, 'request_id': 'integration-test-1', 'edition_date': DATE,
                     'source_count': 5, 'publication_authorized': False, 'identity': identity,
                     'production_ledger_sha256': digest((cache / 'attempts.json').read_bytes()),
                     'discovery_sha256': digest((cache / research.ENGINE / 'discovery.json').read_bytes()),
                     'sources_sha256': digest((cache / research.ENGINE / 'sources.json').read_bytes())}

    def prepare(self):
        with patch.object(publisher, 'MODEL', 'gpt-5-mini'):
            return acceptance.prepare_workspace(self.root, self.state, self.plan)

    def test_only_upstream_stages_are_seeded(self):
        before = acceptance.production_inventory(self.root, DATE)
        workspace, payload = self.prepare();cache = workspace / '.release-cache' / DATE
        self.assertTrue((cache / research.ENGINE / 'sources.json').exists())
        self.assertFalse((cache / 'attempts.json').exists())
        self.assertFalse((cache / 'retained-discovery-continuation-used.json').exists())
        self.assertFalse((workspace / 'repair-authorizations').exists())
        self.assertEqual(acceptance.production_inventory(self.root, DATE), before)

    def test_changed_retained_source_file_stops_before_copy(self):
        p = self.cache / research.ENGINE / 'sources.json';p.write_text(p.read_text() + '\n')
        with self.assertRaises(RuntimeError):self.prepare()
        self.assertFalse((self.state / 'workspace').exists())

    def test_changed_editorial_context_cannot_trigger_new_discovery(self):
        write_json(self.root / 'data/intelligence.json', {'issues': [{'id': 'changed'}]})
        with self.assertRaisesRegex(RuntimeError, 'editorial context'):self.prepare()

    def test_production_ledger_change_is_rejected(self):
        write_json(self.cache / 'attempts.json', {'attempts': 0})
        with self.assertRaises(RuntimeError):self.prepare()

    def test_test_plan_cannot_authorize_publication(self):
        self.plan['publication_authorized'] = True
        with self.assertRaises(RuntimeError):self.prepare()

    def test_already_published_seed_is_rejected(self):
        write_json(self.root / 'release.json', {'edition_date': DATE})
        with self.assertRaisesRegex(RuntimeError, 'unpublished edition'):self.prepare()

    def test_corrupted_local_file_fails_before_audio_or_network(self):
        site = self.state / 'workspace/.site';site.mkdir(parents=True)
        (site / 'index.html').write_text('wrong')
        manifest = {'edition_date': DATE, 'files': {'index.html': {'bytes': 5, 'sha256': digest('right')}}}
        write_json(site / 'release.json', manifest)
        with self.assertRaisesRegex(AssertionError, 'hash or size'):acceptance.local_verify(site.parent, manifest)

    def test_dry_run_makes_no_provider_calls_and_writes_acceptance_report(self):
        log = self.root / '.integration-output/offline-tests.log';log.parent.mkdir()
        log.write_text('Ran 20 tests in 1.0s\n\nOK\n')
        with patch.object(acceptance.subprocess, 'check_output', return_value='a' * 40 + '\n'), \
             patch.object(publisher, 'MODEL', 'gpt-5-mini'), patch.object(urllib.request, 'urlopen') as network:
            result = acceptance.run(self.root, self.plan, live=False)
        network.assert_not_called()
        self.assertEqual(result['result'], 'not_run')
        self.assertEqual(result['stages']['production_unchanged']['status'], 'pass')
        self.assertTrue((self.root / '.integration-output/acceptance.html').exists())

    def test_failed_offline_controls_cannot_access_provider(self):
        with patch.object(acceptance.subprocess, 'check_output', return_value='a' * 40 + '\n'), \
             patch.object(urllib.request, 'urlopen') as network:
            result = acceptance.run(self.root, self.plan, live=True)
        network.assert_not_called();self.assertEqual(result['result'], 'fail')

    def test_workflow_has_no_publication_permissions_or_production_cache_save(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / '.github/workflows/integration-acceptance.yml').read_text()
        for forbidden in ('contents: write', 'pages: write', 'issues: write', 'id-token: write', 'schedule:', '--commit'):
            self.assertNotIn(forbidden, text)
        self.assertIn('persist-credentials: false', text)
        self.assertIn('deployment: false', text)
        self.assertIn('path: .integration-state', text)
        self.assertIn('group: rural-update-single-publisher', text)


if __name__ == '__main__':unittest.main()
