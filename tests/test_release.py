"""Offline fault-injection tests. Synthetic test text is never a publishable edition."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_core as core
import release_pipeline as pipeline
import release_verify as verifier
from bs4 import BeautifulSoup

DATE='2026-10-11'

def fixture():
    p=' '.join(['Planning information supports careful review and explicit documented decisions today.']*18)
    # Exactly 180 words in each of ten spoken segments.
    assert len(p.split())==180
    sources=[{'id':'s'+str(n),'title':'Test source '+str(n),'url':('https://www.cms.gov/' if n%2 else 'https://oklahoma.gov/')+'test-'+str(n),'published_date':'2026-10-10'} for n in range(1,6)]
    e={'edition_date':DATE,'title':'Synthetic validation fixture','bluf':'Synthetic validation fixture only.',
      'sources':sources,'stories':[],'actions':[{'id':'review','title':'Review evidence','due_date':DATE,'next_step':'Review supporting information.','suggested_function':'Leadership','issue_id':'policy','source_ids':['s1']}],
      'deadlines':[{'date':'2026-10-15','title':'Review checkpoint','description':'Editorial checkpoint.','kind':'Editorial checkpoint','source_ids':['s1']}],
      'signals':[],'issue_updates':[{'id':'policy','title':'Policy test','status':'Building','risk':'High','horizon':'1-3 months','relevance':['CAH'],'summary':'Synthetic test evidence.','nextMilestone':'Review','history_note':'Synthetic evidence updated.','source_ids':['s1']}],
      'podcast':{'opening':p,'bluf':p,'developments':[p,p,p],'oklahoma':p,'signals':p,'actions':p,'deadlines':p,'closing':p}}
    for n in range(5):
      e['stories'].append({'id':'story-'+str(n),'title':'Synthetic development '+str(n),'what_changed':'Synthetic test content.','why_it_matters':'Tests the compiler.','executive_question':'Does validation work?','category':'Oklahoma','change':'Continuing','policy_state':'Monitoring','source_ids':['s'+str(n+1)]})
    for n in range(4):
      e['signals'].append({'id':'signal-'+str(n),'title':'Synthetic signal '+str(n),'direction':'Stable','confidence':'Medium','horizon':'1-3 months','executiveRisk':'Moderate','summary':'Synthetic test.','why':'Tests source links.','source_ids':['s1','s2']})
    return e

class ValidationTests(unittest.TestCase):
    def test_valid_schema_and_word_count(self): core.validate_edition(fixture(),DATE)
    def test_wrong_date_rejected(self):
        with self.assertRaises(AssertionError): core.validate_edition(fixture(),'2026-10-12')
    def test_short_script_rejected(self):
        e=fixture(); e['podcast']['opening']='Too short.'
        with self.assertRaises(AssertionError): core.validate_edition(e,DATE)
    def test_unsupported_source_rejected(self):
        with self.assertRaises(AssertionError): core.validate_edition(fixture(),DATE,set())
    def test_future_source_rejected(self):
        e=fixture(); e['sources'][0]['published_date']='2027-01-01'
        with self.assertRaises(AssertionError): core.validate_edition(e,DATE)
    def test_private_url_rejected(self):
        e=fixture(); e['sources'][0]['url']='https://127.0.0.1/secrets'
        with self.assertRaises(AssertionError): core.validate_edition(e,DATE)
    def test_host_suffix_attack_rejected(self): self.assertFalse(core.allowed_url('https://cms.gov.attacker.test/a'))
    def test_old_deadline_rejected(self):
        e=fixture(); e['deadlines'][0]['date']='2026-10-01'
        with self.assertRaises(AssertionError): core.validate_edition(e,DATE)
    def test_far_deadline_rejected(self):
        e=fixture(); e['deadlines'][0]['date']='2026-12-31'
        with self.assertRaises(AssertionError): core.validate_edition(e,DATE)
    def test_duplicate_ids_rejected(self):
        e=fixture(); e['stories'][1]['id']=e['stories'][0]['id']
        with self.assertRaises(AssertionError): core.validate_edition(e,DATE)
    def test_source_provenance_not_from_arbitrary_text(self):
        r={'output':[{'type':'message','content':[{'type':'output_text','text':'https://www.cms.gov/test'}]}]}
        self.assertEqual(pipeline.retrieved_urls(r),set())
    def test_incomplete_response_rejected(self):
        with self.assertRaises(AssertionError): pipeline.output_text({'status':'incomplete'})
    def test_path_traversal_rejected(self):
        with self.assertRaises(AssertionError): core.safe_path(Path('/tmp/site'),'../outside')
    def test_no_inferred_action_completion(self):
        prior={'issues':[],'actions':[{'id':'review','status':'Open','title':'Old review'}]}
        state=core.merge_intelligence(prior,fixture())
        self.assertEqual(state['actions'][0]['status'],'Open')
    def test_history_not_duplicated(self):
        state=core.merge_intelligence(None,fixture())
        again=core.merge_intelligence(state,fixture())
        self.assertEqual(len(again['issues'][0]['history']),1)
    def test_unresolved_issue_carried_forward(self):
        state=core.merge_intelligence({'issues':[{'id':'legacy','title':'Legacy','status':'Monitoring'}],'actions':[]},fixture())
        self.assertTrue(any(i['id']=='legacy' for i in state['issues']))

class CompilerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.root.joinpath('index.html').write_text('''<!doctype html><html><head><meta name="edition-date" content="2026-10-08"><link rel="manifest" href="manifest.webmanifest"><style>.card{padding:12px}</style></head><body><div class="fresh"></div><button class="tab-btn" onclick="showTab('today',this)">Today</button><button class="tab-btn" onclick="showTab('signals',this)">Signals</button><button class="tab-btn" onclick="showTab('archive',this)">Archive</button><section id="page-today" class="page active"></section><section id="page-signals" class="page"></section><section id="page-archive" class="page"></section><script src="intelligence.js"></script></body></html>''')
        core.write_json(self.root/'manifest.webmanifest',{'name':'The Rural Update','start_url':'./index.html'})
        self.root.joinpath('podcast.xml').write_text('<rss version="2.0"><channel><title>Test feed</title></channel></rss>')
        self.root.joinpath('podcast-art.png').write_bytes(b'test-image')
        src=Path(__file__).resolve().parents[1]
        import shutil
        shutil.copytree(src/'web',self.root/'web'); shutil.copy2(src/'sw.js',self.root/'sw.js')
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        subprocess.run(['git','-C',str(self.root),'add','.'],check=True)
        subprocess.run(['git','-C',str(self.root),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','fixture'],check=True)
    def tearDown(self): self.tmp.cleanup()
    def approved(self):
        return {'edition':fixture(),'audit':{'approved':True,'issues':[]},'retrieved_urls':[core.canonical_url(s['url']) for s in fixture()['sources']], 'research_at':'2026-10-11T05:40:00-05:00'}
    def build(self,audio_failure=False):
        def audio(e,cache,out):
            out.parent.mkdir(exist_ok=True); out.write_bytes(b'ID3synthetic-test-bytes')
            if audio_failure: raise RuntimeError('Simulated audio outage')
            core.write_json(cache/'audio-quality.json',{'complete':True,'audio_sha256':core.digest(out.read_bytes()),'script_sha256':core.digest(core.podcast_body(e))})
            return 720
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'research',return_value=self.approved()),patch.object(pipeline,'migrate_legacy',return_value={'intelligence':{'issues':[],'actions':[]},'signals':[]}),patch.object(pipeline,'audio_for',side_effect=audio),patch.object(core,'probe_audio',return_value=720):
            return pipeline.build(DATE)
    def test_complete_bundle_and_same_day_archive(self):
        m=self.build(); self.assertEqual(m['audio_status'],'complete')
        self.assertTrue((self.root/'archive/2026-10-08.html').exists())
        self.assertTrue((self.root/f'archive/{DATE}.html').exists())
        core.validate_catalog(self.root,core.read_json(self.root/'archive/catalog.json'))
    def test_exact_noop_rerun_no_paid_calls(self):
        first=self.build()
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'research',side_effect=AssertionError('No research allowed')):
            again=pipeline.build(DATE)
        self.assertEqual(first,again)
    def test_audio_failure_publishes_text_only(self):
        m=self.build(True); self.assertEqual(m['audio_status'],'unavailable')
        self.assertNotIn(f'audio/{DATE}.mp3',m['files'])
        self.assertIn(f'transcript/{DATE}.html',m['files'])
        self.assertFalse((self.root/f'audio/{DATE}.mp3').exists())
    def test_no_duplicate_runtime_or_tracker(self):
        self.build(); soup=BeautifulSoup((self.root/'index.html').read_text(),'html.parser')
        self.assertEqual([s.get('src') for s in soup.find_all('script')],['web/release-runtime.js'])
        self.assertEqual(len(soup.select('#issue-policy')),1)
    def test_archive_served_with_return_control(self):
        self.build(); text=(self.root/'.site/archive/2026-10-08.html').read_text()
        self.assertIn('Return to current edition',text); self.assertNotIn('src="intelligence.js"',text)
    def test_no_draft_or_credentials_deployed(self):
        self.root.joinpath('.release-cache').mkdir(); self.root.joinpath('.release-cache/secret').write_text('not public')
        self.build(); self.assertFalse((self.root/'.site/.release-cache').exists())
        self.assertFalse((self.root/'.site/scripts').exists())
    def test_corrupt_inventory_detected(self):
        self.build(); self.root.joinpath('index.html').write_text('corrupted')
        with patch.object(pipeline,'ROOT',self.root):
            with self.assertRaises(AssertionError): pipeline.build(DATE)
    def test_unsafe_html_escaped(self):
        e=fixture(); e['bluf']='<script>alert(1)</script>'
        s=core.merge_intelligence(None,e)
        output=core.render(self.root,e,s,[],{'editions':[]},'test')
        self.assertIn('&lt;script&gt;',output); self.assertNotIn('<script>alert',output)
    def test_missing_archive_is_failure(self):
        with self.assertRaises(AssertionError):
            core.validate_catalog(self.root,{'editions':[{'date':DATE,'path':f'archive/{DATE}.html'}]})
    def test_past_release_cannot_replace_newer(self):
        self.build()
        with patch.object(pipeline,'ROOT',self.root):
            with self.assertRaises(AssertionError): pipeline.build('2026-10-10')
    def test_public_hash_mismatch_fails(self):
        m=self.build()
        def getter(path,headers=None):
            return (200,{},json.dumps(m).encode()) if path=='release.json' else (200,{},b'wrong content')
        with patch.object(verifier,'public_get',side_effect=getter):
            with self.assertRaises(AssertionError): verifier.verify(DATE,m)
    def test_text_only_recovery_keeps_same_change_log(self):
        self.build(True)
        state=core.read_json(self.root/'data/intelligence.json'); signals=core.read_json(self.root/'data/signals.json')
        def audio(e,cache,out):
            out.write_bytes(b'ID3recovered')
            core.write_json(cache/'audio-quality.json',{'complete':True,'audio_sha256':core.digest(out.read_bytes()),'script_sha256':core.digest(core.podcast_body(e))})
            return 720
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'migrate_legacy',return_value={'intelligence':state,'signals':signals}),patch.object(pipeline,'research',side_effect=AssertionError('Do not regenerate approved text')),patch.object(pipeline,'audio_for',side_effect=audio),patch.object(core,'probe_audio',return_value=720):
            m=pipeline.build(DATE)
        self.assertEqual(m['audio_status'],'complete')
        self.assertEqual(core.read_json(self.root/'data/intelligence.json')['changes'],state['changes'])
    def test_disjoint_concurrent_repository_write_survives(self):
        self._concurrent_commit(False)
    def test_conflicting_repository_write_is_not_overwritten(self):
        self._concurrent_commit(True)
    def _concurrent_commit(self,conflict):
        with tempfile.TemporaryDirectory() as td:
            remote=Path(td)/'remote.git'; other=Path(td)/'other'
            subprocess.run(['git','init','--bare','-q',str(remote)],check=True)
            subprocess.run(['git','-C',str(self.root),'branch','-M','main'],check=True)
            subprocess.run(['git','-C',str(self.root),'remote','add','origin',str(remote)],check=True)
            subprocess.run(['git','-C',str(self.root),'push','-qu','origin','main'],check=True)
            subprocess.run(['git','clone','-q','-b','main',str(remote),str(other)],check=True)
            (other/('index.html' if conflict else 'notes.md')).write_text('Concurrent edit')
            subprocess.run(['git','-C',str(other),'add','.'],check=True)
            subprocess.run(['git','-C',str(other),'-c','user.name=Other','-c','user.email=other@example.invalid','commit','-qm','concurrent'],check=True)
            subprocess.run(['git','-C',str(other),'push','-q'],check=True)
            self.root.joinpath('index.html').write_text('Prepared release')
            with patch.object(pipeline,'ROOT',self.root):
                if conflict:
                    with self.assertRaises(AssertionError): pipeline.commit_outputs(DATE)
                else: pipeline.commit_outputs(DATE)
            final=subprocess.check_output(['git','--git-dir',str(remote),'show','main:index.html'],text=True)
            self.assertEqual(final,'Concurrent edit' if conflict else 'Prepared release')
    def test_alert_recovery_deduplicated(self):
        existing={'number':1,'title':'[Publication] '+DATE+' delivery check','body':'Recovery requested for this edition.','state':'open','html_url':'https://github.com/test/issue/1'}
        with patch.object(verifier,'github') as g:
            g.side_effect=lambda path,*a,**kw: [existing] if path.startswith('issues?') else {}
            verifier.incident(DATE,'Test outage',recover=True)
        self.assertFalse(any('dispatches' in call.args[0] for call in g.call_args_list))

if __name__=='__main__': unittest.main()
