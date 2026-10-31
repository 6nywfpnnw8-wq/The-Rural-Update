"""App releases retain evidence gates and never request narration or audio."""
import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'ops')]
from bs4 import BeautifulSoup
from jsonschema import ValidationError
import release_core as core
import release_pipeline as pipeline
import release_research as research
import release_verify as verifier
import release_evidence as evidence
import publisher_provider_check as provider
import check_openai_access as access
from release_publication import app_only, app_required_paths, complete_app_manifest
from release_narration import generation_schema
from release_diagnostics import DiagnosedFailure
from trigger_publisher import decide
from test_release import fixture
import test_release as legacy
from test_release_staged_research import bounded_fixture, response, selection_response, reporting_response
from test_release_credentials import research as research_response
from evidence_fixture import fake_source

DATE='2026-10-31'


def app_fixture(bounded=False):
    edition=bounded_fixture() if bounded else fixture()
    edition.pop('podcast')
    edition['edition_date']=DATE
    edition['actions'][0]['due_date']=DATE
    edition['deadlines'][0]['date']='2026-11-05'
    return edition


class AppSchemaAndResearchTests(unittest.TestCase):
    def test_format_cutover_and_legacy_validation(self):
        self.assertFalse(app_only('2026-10-30'))
        self.assertTrue(app_only(DATE))
        core.validate_edition(app_fixture(),DATE)
        core.validate_edition(fixture(),fixture()['edition_date'])
        self.assertNotIn('podcast',generation_schema(DATE)['properties'])
        self.assertIn('podcast',generation_schema('2026-10-30')['properties'])

    def test_new_editions_cannot_generate_a_podcast(self):
        edition=app_fixture();edition['podcast']=fixture()['podcast']
        with self.assertRaises(ValidationError):core.validate_edition(edition,DATE)
        prompt=pipeline.research_payload(DATE,{})
        self.assertNotIn('1700',prompt['input'])
        self.assertNotIn('podcast',prompt['text']['format']['schema']['properties'])

    def test_source_and_deadline_requirements_still_apply(self):
        edition=app_fixture();edition['signals'][0]['source_ids']=['missing','s2']
        with self.assertRaisesRegex(AssertionError,'source reference'):
            core.validate_edition(edition,DATE)
        edition=app_fixture();edition['deadlines'][0]['date']='2026-10-30'
        with self.assertRaisesRegex(AssertionError,'next 30 days'):
            core.validate_edition(edition,DATE)

    def test_staged_app_reporting_stops_before_narration_and_reuses_cache(self):
        edition=app_fixture(True);report=copy.deepcopy(edition);report.pop('sources')
        send=Mock(side_effect=[response('Verified source notes.',web=True),
                              selection_response(edition['sources']),reporting_response(report)])
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)/DATE
            core.write_json(cache/'attempts.json',{'attempts':1})
            payload={'model':'test','input':'Edition '+DATE,'tools':[{'type':'web_search'}]}
            with patch.object(research,'ensure_reporting_plan',return_value=None) as coverage:
                result=research.staged_request(payload,send,cache)
                coverage.assert_called_once()
                self.assertEqual(json.loads(pipeline.output_text(result)),edition)
                self.assertEqual(send.call_count,3)
                self.assertNotIn('narration',result['usage']['stages'])
                send.reset_mock(side_effect=True)
                send.side_effect=AssertionError('Repeated provider request')
                again=research.staged_request(payload,send,cache)
                self.assertEqual(result,again);send.assert_not_called()
            self.assertEqual(core.read_json(cache/'attempts.json'),{'attempts':1})
            self.assertFalse((cache/research.ENGINE/'narration.json').exists())

    def test_inadequate_coverage_stops_before_reporting(self):
        edition=app_fixture(True)
        send=Mock(side_effect=[response('Source notes.',web=True),selection_response(edition['sources'])])
        with tempfile.TemporaryDirectory() as tmp, patch.object(research,'ensure_reporting_plan',
                side_effect=RuntimeError('coverage incomplete')):
            with self.assertRaisesRegex(RuntimeError,'coverage incomplete'):
                research.staged_request({'model':'test','input':DATE,'tools':[]},send,Path(tmp)/DATE)
            self.assertEqual(send.call_count,2)

    def test_real_research_path_requires_fresh_complete_audit_without_narration(self):
        edition=app_fixture()
        api=Mock(side_effect=[response(edition,web=True),response({'review_complete':True,'findings':[]},web=True)])
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'RURAL_UPDATE_STRUCTURED_REVIEW':'true'}), \
             patch.object(pipeline,'request_api',api), patch.object(pipeline,'ensure_narration_length') as narration, \
             patch.object(evidence,'fetch_source',side_effect=fake_source):
            cache=Path(tmp)/DATE
            out=pipeline.research(DATE,{},cache)
            self.assertTrue(out['audit']['approved']);self.assertNotIn('podcast',out['edition'])
            self.assertEqual(api.call_count,2);narration.assert_not_called()
            self.assertEqual(core.read_json(cache/'attempts.json'),{'attempts':1})
            self.assertTrue(api.call_args_list[-1].args[0]['tools'])
            self.assertEqual(pipeline.research(DATE,{},cache),out)
            self.assertEqual(api.call_count,2)

    def test_incomplete_audit_cannot_approve_app(self):
        api=Mock(side_effect=[response(app_fixture(),web=True),
                             response({'review_complete':False,'findings':[]},web=True)])
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'RURAL_UPDATE_STRUCTURED_REVIEW':'true'}), \
             patch.object(pipeline,'request_api',api),patch.object(evidence,'fetch_source',side_effect=fake_source):
            cache=Path(tmp)/DATE
            with self.assertRaisesRegex(RuntimeError,'review is incomplete'):
                pipeline.research(DATE,{},cache)
            self.assertFalse((cache/'approved.json').exists())

    def test_blocking_app_finding_requires_correction_and_second_full_audit(self):
        finding={'id':'f1','kind':'unsupported_claim','path':'/stories/0/why_it_matters',
                 'quote':'Tests the compiler.','source_ids':['s1'],
                 'explanation':'The claim requires qualification.',
                 'required_change':'State this as a recommendation.'}
        plan={'replacements':[{'path':finding['path'],'before':finding['quote'],
              'after':'Leaders should test the compiler before relying on it.','addresses':['f1']}]}
        api=Mock(side_effect=[response(app_fixture(),web=True),
            response({'review_complete':True,'findings':[finding]},web=True),response(plan),
            response({'review_complete':True,'findings':[]},web=True)])
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'RURAL_UPDATE_STRUCTURED_REVIEW':'true'}), \
             patch.object(pipeline,'request_api',api),patch.object(evidence,'fetch_source',side_effect=fake_source):
            cache=Path(tmp)/DATE;out=pipeline.research(DATE,{},cache)
            self.assertTrue(out['audit']['approved']);self.assertEqual(api.call_count,4)
            self.assertNotIn('podcast',out['edition'])
            self.assertEqual(out['structured_review']['correction_calls'],1)
            self.assertEqual(core.read_json(cache/'attempts.json'),{'attempts':1})

    def test_format_change_does_not_reset_spent_research_budget(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(pipeline,'request_api') as api:
            cache=Path(tmp)/DATE;core.write_json(cache/'attempts.json',{'attempts':2})
            with self.assertRaises(DiagnosedFailure):pipeline.research(DATE,{},cache)
            api.assert_not_called()
            self.assertEqual(core.read_json(cache/'attempts.json'),{'attempts':2})


class AppDeliveryTests(unittest.TestCase):
    setUp=legacy.CompilerTests.setUp
    tearDown=legacy.CompilerTests.tearDown

    def build(self):
        edition=app_fixture()
        record={'edition':edition,'audit':{'approved':True,'issues':[]},
                'retrieved_urls':[core.canonical_url(s['url']) for s in edition['sources']],
                'research_at':'2026-10-31T05:40:00-05:00'}
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'research',return_value=record), \
             patch.object(pipeline,'migrate_legacy',return_value={'intelligence':{'issues':[],'actions':[]},'signals':[]}), \
             patch.object(pipeline,'audio_for',side_effect=AssertionError('Audio requested')) as audio, \
             patch.object(pipeline,'update_feed',side_effect=AssertionError('RSS requested')) as feed:
            result=pipeline.build(DATE)
            audio.assert_not_called();feed.assert_not_called()
            return result

    def test_complete_app_has_no_player_or_new_media(self):
        feed=(self.root/'podcast.xml').read_bytes()
        manifest=self.build()
        self.assertTrue(complete_app_manifest(manifest,DATE));self.assertNotIn('audio_status',manifest)
        doc=BeautifulSoup((self.root/'index.html').read_text(),'html.parser')
        self.assertEqual(doc.html['data-publication-mode'],'app')
        self.assertFalse(doc.select('#daily-audio, .listen-card'))
        self.assertEqual(len(doc.select('#page-today .story')),5)
        self.assertEqual(len(doc.select('.tab-btn')),3)
        for folder,suffix in [('podcast-script','txt'),('transcript','html'),('audio','mp3')]:
            self.assertFalse((self.root/f'{folder}/{DATE}.{suffix}').exists())
        self.assertEqual((self.root/'podcast.xml').read_bytes(),feed)

    def test_public_app_delivery_checks_hashes_without_media_tools(self):
        manifest=self.build()
        def get(path,headers=None):return 200,{},(self.root/'.site'/path).read_bytes()
        with patch.object(verifier,'public_get',side_effect=get),patch.object(verifier,'probe_audio') as audio:
            result=verifier.verify(DATE,manifest)
            self.assertTrue(result['complete']);self.assertEqual(result['publication_mode'],'app')
            self.assertTrue(app_required_paths(DATE).issubset(result['checked_files']))
            audio.assert_not_called()
            (self.root/'.site/data/signals.json').write_text('changed')
            with self.assertRaisesRegex(AssertionError,'hash/size mismatch'):verifier.verify(DATE,manifest)

    def test_app_manifest_cannot_skip_inventory_or_relabel_legacy_release(self):
        manifest=self.build();manifest['files'].pop('data/signals.json')
        with patch.object(verifier,'public_get',return_value=(200,{},json.dumps(manifest).encode())):
            with self.assertRaisesRegex(AssertionError,'Incomplete app'):verifier.verify(DATE)
        manifest['edition_date']='2026-10-30'
        with patch.object(verifier,'public_get',return_value=(200,{},json.dumps(manifest).encode())):
            with self.assertRaisesRegex(AssertionError,'historical edition'):verifier.verify('2026-10-30')

    def test_redeploy_complete_app_reuses_committed_artifacts(self):
        first=self.build()
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'research') as news,patch.object(pipeline,'audio_for') as audio:
            self.assertEqual(pipeline.build(DATE),first)
            news.assert_not_called();audio.assert_not_called()

    def test_unapproved_app_cannot_reach_compilation(self):
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'migrate_legacy',return_value={}), \
             patch.object(pipeline,'research',return_value={'audit':{'approved':False,'issues':['unsupported claim']}}):
            with self.assertRaisesRegex(AssertionError,'editorial audit'):pipeline.build(DATE)
        self.assertFalse((self.root/'release.json').exists())

    def test_complete_app_preflight_and_clock_do_not_request_more_generation(self):
        manifest=self.build();checker=Mock()
        result=provider.preflight(self.root,DATE,checker,Mock())
        self.assertTrue(result['skipped']);checker.assert_not_called()
        clock=decide(datetime.fromisoformat('2026-10-31T10:05:00+00:00'),manifest,[])
        self.assertEqual(clock['action'],'skip');self.assertFalse(clock['public_delivery_verified'])


class AppProviderAndWorkflowTests(unittest.TestCase):
    def test_app_capability_check_never_calls_media_endpoints(self):
        client=Mock();client.post.return_value=research_response()
        result=access.run_check(client,'test-model',include_audio=False)
        self.assertTrue(result['passed']);self.assertEqual(client.post.call_count,1)
        self.assertEqual(client.post.call_args.args[0],'responses')

    def test_daily_preflight_requests_only_app_capabilities(self):
        checker=Mock(return_value={'passed':True,'checks':[]})
        with tempfile.TemporaryDirectory() as tmp:
            provider.preflight(Path(tmp),DATE,checker,Mock())
        self.assertEqual(checker.call_args.kwargs,{'include_audio':False})

    def test_active_workflows_have_no_podcast_provider_or_media_dependency(self):
        daily=(ROOT/'.github/workflows/publish.yml').read_text()
        watchdog=(ROOT/'.github/workflows/publication-watchdog.yml').read_text()
        for source in (daily,watchdog):
            for forbidden in ('ffmpeg','ffprobe','OPENAI_TTS','release_prepared_audio.py'):
                self.assertNotIn(forbidden,source)
        for path in ('audio-integration.yml','integration-acceptance.yml'):
            self.assertNotIn('secrets.OPENAI_API_KEY',(ROOT/'.github/workflows'/path).read_text())
        self.assertIn('group: rural-update-single-publisher',daily)


if __name__=='__main__':unittest.main()
