"""Public delivery verification and one-incident-per-edition recovery/alerts."""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from release_diagnostics import current_failure_summary
import hashlib
BASE='https://6nywfpnnw8-wq.github.io/The-Rural-Update/'
TZ=ZoneInfo('America/Chicago')

def digest(data): return hashlib.sha256(data).hexdigest()
def read_json(path): return json.loads(path.read_text(encoding='utf-8'))
def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
def probe_audio(path):
    raw=subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(path)],text=True,timeout=30)
    seconds=float(raw.strip())
    if not seconds>0: raise RuntimeError('Empty audio')
    subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],check=True,timeout=90,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    return seconds

REPO='6nywfpnnw8-wq/The-Rural-Update'
ROOT=Path(__file__).resolve().parents[1]

def public_get(path, headers=None):
    assert re.fullmatch(r'[A-Za-z0-9_./-]+',path) and '..' not in Path(path).parts and not path.startswith('/'),'Unsafe verification path'
    req=urllib.request.Request(BASE+path+'?delivery_check='+str(time.time_ns()),headers={'User-Agent':'RuralUpdate-DeliveryVerifier/1',**(headers or {})})
    with urllib.request.urlopen(req,timeout=45) as response:
        content=response.read(35*1024*1024+1)
        assert len(content)<=35*1024*1024,'Unexpectedly large public artifact'
        return response.status,dict(response.headers.items()),content

def verify(expected_date,expected=None):
    status,headers,raw=public_get('release.json')
    assert status==200,'Public release record not available'
    manifest=json.loads(raw)
    assert manifest.get('schema_version')==1,'Unknown release schema'
    assert manifest.get('edition_date')==expected_date,'Public site is serving another edition'
    assert manifest.get('files'),'No public artifact inventory'
    if expected is not None:
        assert manifest==expected,'Public deployment does not match the validated release'
    required=['index.html','archive/catalog.json',f'archive/{expected_date}.html',f'transcript/{expected_date}.html']
    assert all(p in manifest['files'] for p in required),'Incomplete artifact inventory'
    if manifest.get('audio_status')=='complete':
        assert f'audio/{expected_date}.mp3' in manifest['files'] and 'podcast.xml' in manifest['files'],'Missing audio/feed inventory'
    checked=[]
    quality=None
    quality_path='data/audio-quality-'+expected_date+'.json'
    if expected_date>='2026-10-16' and manifest.get('audio_status')=='complete':
        assert quality_path in manifest['files'],'Narration completion evidence missing'
    if quality_path in manifest['files']:
        status,_,qdata=public_get(quality_path)
        info=manifest['files'][quality_path]
        assert status==200 and len(qdata)==info['bytes'] and digest(qdata)==info['sha256'],'Narration quality report hash mismatch'
        quality=json.loads(qdata)
        assert quality.get('complete') is True and quality.get('audio_sha256')==manifest['files'][f'audio/{expected_date}.mp3']['sha256'],'Narration completion evidence mismatch'

    for path,info in manifest['files'].items():
        status,headers,data=public_get(path)
        assert status==200,'Public artifact unavailable: '+path
        assert len(data)==info['bytes'] and digest(data)==info['sha256'],'Public hash/size mismatch: '+path
        if path.endswith('.mp3'):
            media_type=next((v for k,v in headers.items() if k.lower()=='content-type'),'')
            assert 'audio/' in media_type or 'octet-stream' in media_type,'Audio URL returned non-audio content'
            with tempfile.NamedTemporaryFile(suffix='.mp3') as f:
                f.write(data); f.flush(); duration=probe_audio(Path(f.name))
                assert 540<=duration<=900,'Unexpected public audio duration'
            status,range_headers,part=public_get(path,{'Range':'bytes=0-1023'})
            cr=next((v for k,v in range_headers.items() if k.lower()=='content-range'),'')
            assert status==206 and cr.startswith('bytes 0-1023/') and len(part)==1024,'Audio range requests are not working'
        if path=='podcast.xml' and manifest.get('audio_status')=='complete':
            import xml.etree.ElementTree as ET
            tree=ET.fromstring(data)
            items=[i for i in tree.findall('./channel/item') if i.findtext('guid')=='the-rural-update-'+expected_date]
            assert len(items)==1,'Episode is missing or duplicated in RSS'
            item=items[0]; enclosure=item.find('enclosure'); transcript=item.find('{https://podcastindex.org/namespace/1.0}transcript')
            assert enclosure is not None and f'audio/{expected_date}.mp3' in enclosure.get('url',''),'RSS audio mismatch'
            assert transcript is not None and f'transcript/{expected_date}.html' in transcript.get('url',''),'RSS transcript missing'
        checked.append(path)
    return {'edition_date':expected_date,'revision':manifest['revision'],'checked_at':datetime.now(TZ).isoformat(),
            'public_text_verified':True,'complete':manifest.get('audio_status')=='complete','checked_files':checked,'narration_completion_verified':bool(quality)}

def github(path,method='GET',body=None):
    token=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token: raise RuntimeError('GitHub alert/dispatch credentials missing')
    req=urllib.request.Request('https://api.github.com/repos/'+REPO+'/'+path,
        data=None if body is None else json.dumps(body).encode(),method=method,
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','Content-Type':'application/json',
                 'X-GitHub-Api-Version':'2022-11-28','User-Agent':'RuralUpdate-DeliveryVerifier/1'})
    with urllib.request.urlopen(req,timeout=30) as response:
        data=response.read()
        return json.loads(data) if data else {}

def incident(edition_date,message,healthy=False,recover=False,test=False):
    title=('[Publication test] ' if test else '[Publication] ')+edition_date+' delivery check'
    issues=github('issues?state=all&per_page=100')
    issue=next((x for x in issues if x.get('title')==title and 'pull_request' not in x),None)
    url=os.getenv('GITHUB_SERVER_URL','https://github.com')+'/'+REPO+'/actions/runs/'+os.getenv('GITHUB_RUN_ID','')
    if healthy:
        if issue and issue['state']=='open':
            github(f'issues/{issue["number"]}/comments','POST',{'body':'Public delivery verified at '+datetime.now(TZ).isoformat()+'. '+url})
            github(f'issues/{issue["number"]}','PATCH',{'state':'closed'})
        return
    body='@6nywfpnnw8-wq\n\n'+message+'\n\nLast check: '+datetime.now(TZ).isoformat()+'\nWorkflow: '+url+'\n\nNo credentials or unpublished source material are included in this incident.'
    if not issue:
        issue=github('issues','POST',{'title':title,'body':body})
    else:
        body+='\n\n'+('Recovery requested for this edition.' if 'Recovery requested for this edition.' in (issue.get('body') or '') else '')
        github(f'issues/{issue["number"]}','PATCH',{'state':'open','body':body})
    # One automatic dispatch per edition; the publisher still holds the global write lock.
    if recover and 'Recovery requested for this edition.' not in (issue.get('body') or ''):
        github(f'issues/{issue["number"]}','PATCH',{'body':body+'\n\nRecovery requested for this edition.'})
        github('actions/workflows/publish.yml/dispatches','POST',{'ref':'main','inputs':{'mode':'recover','edition_date':edition_date}})
    print('Incident: '+issue['html_url'])

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['verify','watch','alert','test-alert'])
    parser.add_argument('--date',default=''); parser.add_argument('--expected',default='')
    parser.add_argument('--recover',action='store_true'); parser.add_argument('--message',default='Publication did not complete. Review the linked run and validation artifacts.')
    args=parser.parse_args(); d=args.date or datetime.now(TZ).date().isoformat()
    if args.command in ('alert','test-alert'):
        message=args.message
        if args.command=='alert':
            detail=current_failure_summary(ROOT/'.release-cache'/d)
            if detail: message=detail+' '+message
        incident(d,message,test=args.command=='test-alert'); return 0
    expected=read_json(Path(args.expected)) if args.expected else None
    error=None; report=None
    for attempt,delay in enumerate([0,10,20,40]):
        if delay: time.sleep(delay)
        try:
            report=verify(d,expected); error=None; break
        except Exception as exc: error=str(exc)
    if report and report['complete']:
        write_json(ROOT/'.release-cache/delivery-report.json',report)
        if os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN'): incident(d,'',healthy=True)
        print(json.dumps(report)); return 0
    message=error or 'Web edition and transcript verified, but this edition has no validated audio yet.'
    write_json(ROOT/'.release-cache/delivery-report.json',{'edition_date':d,'complete':False,'error':message,'partial':report})
    if args.command=='watch': incident(d,message,recover=args.recover)
    print('::error::'+message,file=sys.stderr); return 1

if __name__=='__main__':
    try: sys.exit(main())
    except Exception as exc:
        print('::error::Delivery check/alert failed: '+str(exc),file=sys.stderr); sys.exit(1)
