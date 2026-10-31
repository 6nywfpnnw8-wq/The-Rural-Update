"""Optional external clock. It may start the existing publisher, never publish.

Default is read-only dry-run. --execute requires a separately configured,
repository-scoped Actions token. No OpenAI credential or content-write permission
is needed here. A failed/unknown POST is never immediately retried.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from release_publication import app_only, complete_app_manifest

REPO = '6nywfpnnw8-wq/The-Rural-Update'
API = 'https://api.github.com/repos/' + REPO + '/actions/workflows/publish.yml'
PUBLIC = 'https://6nywfpnnw8-wq.github.io/The-Rural-Update/release.json'
TZ = ZoneInfo('America/Chicago')
ACTIVE = {'queued','in_progress','waiting','pending','requested'}


def decide(now: datetime, release: dict | None, runs: list[dict], mode: str = 'publish') -> dict:
    if now.tzinfo is None:
        raise ValueError('Clock must be timezone-aware')
    if mode not in {'publish', 'diagnose'}:
        raise ValueError('External clock mode must be publish or diagnose')
    local = now.astimezone(TZ)
    day = local.date().isoformat()
    base = {'edition_date':day,'observed_at':local.isoformat(),
            'public_delivery_verified':False,'mode':mode}
    if not 5 <= local.hour < 7:
        return {**base,'action':'skip','reason':'outside_0500_0700_Central'}
    main = [r for r in runs if r.get('head_branch') == 'main']
    if any(r.get('status') in ACTIVE for r in main):
        return {**base,'action':'skip','reason':'publisher_already_active'}
    if mode == 'diagnose':
        # A read-only dispatch can validate the Render-to-GitHub path without
        # consuming the editorial attempt allowance or touching the public site.
        return {**base,'action':'dispatch','reason':'read_only_diagnostic_requested'}
    complete=(complete_app_manifest(release,day) if release and app_only(day) else
              bool(release and release.get('audio_status')=='complete'))
    if release and release.get('edition_date') == day and complete:
        # The publisher's full verifier, not this metadata test, establishes delivery.
        return {**base,'action':'skip','reason':'current_complete_manifest_present'}
    if release and release.get('edition_date','') > day:
        return {**base,'action':'alert','reason':'unexpected_future_release_date'}
    # Diagnostic handoff runs have a run-name marker and do not consume the
    # conservative publisher-run budget. Older/unmarked runs remain counted.
    publish_runs = [r for r in main
                    if 'mode=diagnose' not in str(r.get('display_title','')).lower()]
    today = []
    for r in publish_runs:
        stamp=r.get('run_started_at') or r.get('created_at')
        try:
            started=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            if started.tzinfo is None: raise ValueError('missing timezone')
        except (ValueError,AttributeError):
            return {**base,'action':'alert','reason':'unreadable_run_timestamp'}
        if started.astimezone(TZ).date()==local.date():
            today.append(r)
    # Conservative attempt count includes manual invocations and reruns. The
    # publisher has a second, authoritative content-attempt ledger of its own.
    attempts=sum(max(1,int(r.get('run_attempt',1))) for r in today)
    if attempts>=2:
        return {**base,'action':'alert','reason':'two_publisher_attempts_already_observed',
                'observed_attempts':attempts}
    return {**base,'action':'dispatch','reason':'current_complete_release_missing',
            'observed_attempts':attempts}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise RuntimeError('Unexpected redirect; request not followed')


class Client:
    def __init__(self,token: str = ''):
        self.token=token
        self.opener=urllib.request.build_opener(NoRedirect())
    def get(self,url: str,authenticated: bool = False):
        headers={'User-Agent':'RuralUpdate-ExternalClock/1','Accept':'application/json',
                 'Cache-Control':'no-cache'}
        if authenticated:
            if not url.startswith(API+'/'):
                raise ValueError('Token may be sent only to the fixed workflow endpoint')
            if self.token: headers['Authorization']='Bearer '+self.token
            headers['X-GitHub-Api-Version']='2022-11-28'
        req=urllib.request.Request(url,headers=headers)
        with self.opener.open(req,timeout=25) as response:
            raw=response.read(4*1024*1024+1)
        if len(raw)>4*1024*1024:
            raise RuntimeError('Unexpectedly large metadata response')
        return json.loads(raw)
    def dispatch(self,edition_date: str, mode: str = 'publish'):
        if not self.token:
            raise RuntimeError('GITHUB_ACTIONS_TOKEN is not configured')
        if mode not in {'publish', 'diagnose'}:
            raise ValueError('External clock mode must be publish or diagnose')
        payload={'ref':'main','inputs':{'mode':mode,'edition_date':edition_date}}
        req=urllib.request.Request(API+'/dispatches',data=json.dumps(payload).encode(),method='POST',
            headers={'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json',
                     'Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28',
                     'User-Agent':'RuralUpdate-ExternalClock/1'})
        with self.opener.open(req,timeout=25) as response:
            if response.status not in (200,201,202,204):
                raise RuntimeError('Dispatch was not accepted')
        # Return only acceptance, not an invented run ID or claim of completion.
        return {'dispatch_accepted':True,'publication_complete':False}


def run_once(client: Client,now: datetime,execute: bool = False,mode: str = 'publish') -> dict:
    early=decide(now,None,[],mode)
    if early['reason']=='outside_0500_0700_Central':return early
    try:
        release=client.get(PUBLIC+'?clock='+str(int(now.timestamp())))
        if not isinstance(release,dict):raise ValueError('Invalid release metadata')
    except (urllib.error.URLError,ValueError,RuntimeError):
        release=None
    data=client.get(API+'/runs?branch=main&per_page=100',authenticated=True)
    if not isinstance(data,dict) or not isinstance(data.get('workflow_runs'),list):
        raise RuntimeError('Cannot inspect workflow state; no dispatch attempted')
    runs=data['workflow_runs']
    if len(runs)>=100:
        oldest=runs[-1].get('created_at','')
        if not oldest or oldest[:10]>=now.astimezone(TZ).date().isoformat():
            raise RuntimeError('Run-history window is incomplete; no dispatch attempted')
    result=decide(now,release,runs,mode)
    result['dry_run']=not execute
    if result['action']=='dispatch' and execute:
        # Recheck pending/running jobs immediately before dispatch. The existing
        # publisher's shared lock is still authoritative against a narrow race.
        second=client.get(API+'/runs?branch=main&per_page=100',authenticated=True)
        if not isinstance(second.get('workflow_runs'),list):raise RuntimeError('Final run-state check failed')
        result=decide(now,release,second['workflow_runs'],mode);result['dry_run']=False
        if result['action']=='dispatch':result.update(client.dispatch(result['edition_date'],mode=mode))
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',help='Allow one dispatch after checks; default is read-only')
    parser.add_argument('--mode',choices=['publish','diagnose'],default='publish',
                        help='Dispatch publish, or a read-only diagnostic workflow run')
    args=parser.parse_args()
    try:
        result=run_once(Client(os.getenv('GITHUB_ACTIONS_TOKEN','')),datetime.now(TZ),args.execute,args.mode)
        print(json.dumps(result,sort_keys=True))
        return 1 if result['action']=='alert' else 0
    except urllib.error.HTTPError as exc:
        print(json.dumps({'action':'alert','reason':'http_failure','http_status':exc.code,
                          'dispatch_state':'unknown_if_POST_was_sent','retry_attempted':False}),file=sys.stderr)
    except Exception as exc:
        # Never expose credentials, raw HTTP bodies, response prose or URLs from exceptions.
        print(json.dumps({'action':'alert','reason':'external_clock_error',
                          'error_category':type(exc).__name__,'retry_attempted':False}),file=sys.stderr)
    return 1

if __name__=='__main__':sys.exit(main())

