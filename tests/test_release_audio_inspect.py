"""Retained speech inspection must be bound to bytes and never spend attempts."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_audio_inspect as inspect
from release_core import digest


class AudioInspectionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.cache=Path(temp.name)/'2026-10-28';self.folder=self.cache/'audio-v2';self.folder.mkdir(parents=True)
        self.out=Path(temp.name)/'output'
        self.body='The approved speech includes Medicaid contracting and passthroughs.'
        data=b'known retained speech bytes';self.sha=digest(data)
        (self.folder/'speech-0.wav').write_bytes(data)
        self.asr=self.folder/('asr-'+self.sha+'.json')
        self.asr.write_text(json.dumps({'audio_sha256':self.sha,'text':self.body.replace('passthroughs','pass throughs')}))
        (self.folder/'speech-attempts.json').write_text('{"attempts":2}')
        self.quality=self.cache/'audio-quality-progress.json'
        self.progress={'normalization_version':4,'source_parts':1,'parts':[{'original_index':0,
            'split_depth':0,'passed':False,'text_sha256':digest(self.body),'audio_sha256':self.sha}]}
        self.quality.write_text(json.dumps(self.progress))

    def test_read_only_inspection_keeps_ledgers_and_makes_no_asr_call(self):
        before={p:p.read_bytes() for p in self.cache.rglob('*') if p.is_file()}
        with patch('release_audio.transcribe',side_effect=AssertionError('No paid ASR call')):
            report=inspect.inspect_failure(self.body,self.cache,self.out)
        self.assertEqual(report['api_calls_made'],0)
        self.assertFalse(report['cache_modified'])
        self.assertTrue(all(p.read_bytes()==data for p,data in before.items()))
        self.assertEqual(set(before),{p for p in self.cache.rglob('*') if p.is_file()})
        self.assertEqual((self.out/(self.sha+'.wav')).read_bytes(),b'known retained speech bytes')

    def test_changed_script_or_audio_cannot_be_substituted(self):
        with self.assertRaisesRegex(ValueError,'approved script'):
            inspect.inspect_failure(self.body+' Changed.',self.cache,self.out)
        (self.folder/'speech-0.wav').write_bytes(b'different speech bytes')
        with self.assertRaisesRegex(ValueError,'missing or changed'):
            inspect.inspect_failure(self.body,self.cache,self.out)

    def test_mismatched_asr_record_is_rejected(self):
        self.asr.write_text(json.dumps({'audio_sha256':'0'*64,'text':self.body}))
        with self.assertRaisesRegex(ValueError,'ASR'):
            inspect.inspect_failure(self.body,self.cache,self.out)

    def test_output_cannot_modify_cache(self):
        with self.assertRaisesRegex(ValueError,'must not write'):
            inspect.inspect_failure(self.body,self.cache,self.cache/'output')


if __name__=='__main__':unittest.main()
