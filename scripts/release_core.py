"""Deterministic release compilation. Model output is data, never executable code."""
from __future__ import annotations
import copy
import hashlib
import html
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from jsonschema import Draft202012Validator

TZ = ZoneInfo('America/Chicago')
BASE = 'https://6nywfpnnw8-wq.github.io/The-Rural-Update/'
STATUSES = ['Emerging','Building','Decision Window','Action Required','Implementation Watch',
            'Active Transition','Measurement Phase','Monitoring','Strategic Watch',
            'Completed','Superseded','Closed']
DOMAINS = ['cms.gov','hhs.gov','hrsa.gov','oklahoma.gov','congress.gov','federalregister.gov',
           'govinfo.gov','gao.gov','medpac.gov','healthit.gov','ahrq.gov','cdc.gov','nih.gov',
           'nist.gov','cisa.gov','fda.gov','kff.org','ruralhealth.us','ruralhealthinfo.org',
           'aha.org','openai.com','healthaffairs.org']

def obj(**properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def arr(items, low=0, high=30):
    return {'type':'array','items':items,'minItems':low,'maxItems':high}
S = {'type':'string'}
N = {'type':['string','null']}
IDS = arr(S,1,5)
SOURCE = obj(id=S,title=S,url=S,published_date=N)
STORY = obj(id=S,title=S,what_changed=S,why_it_matters=S,executive_question=S,
            category=S,change={'type':'string','enum':['New','Changed','Continuing']},
            policy_state={'type':'string','enum':['Final','Proposed','Announcement','Research','Monitoring']},source_ids=IDS)
ACTION = obj(id=S,title=S,due_date=N,next_step=S,suggested_function=S,issue_id=S,source_ids=IDS)
SIGNAL = obj(id=S,title=S,direction=S,confidence={'type':'string','enum':['High','Medium','Emerging']},
             horizon=S,executiveRisk=S,summary=S,why=S,source_ids=arr(S,2,4))
ISSUE = obj(id=S,title=S,status={'type':'string','enum':STATUSES},risk=S,horizon=S,
            relevance=arr(S,1,8),summary=S,nextMilestone=S,history_note=S,source_ids=IDS)
SCHEMA = obj(edition_date=S,title=S,bluf=S,stories=arr(STORY,5,5),actions=arr(ACTION,1,3),
             deadlines=arr(obj(date=S,title=S,description=S,
                 kind={'type':'string','enum':['Official deadline','Editorial checkpoint']},source_ids=IDS),0,8),
             signals=arr(SIGNAL,4,4),issue_updates=arr(ISSUE,0,8),sources=arr(SOURCE,5,20),
             podcast=obj(opening=S,bluf=S,developments=arr(S,3,3),oklahoma=S,signals=S,actions=S,deadlines=S,closing=S))

def canonical_url(url):
    u=urlsplit(url)
    return urlunsplit((u.scheme.lower(),u.netloc.lower(),u.path.rstrip('/'),
                      urlencode([(k,v) for k,v in parse_qsl(u.query) if not k.startswith('utm_')]),''))

def allowed_url(url):
    u=urlsplit(url)
    host=(u.hostname or '').lower()
    return u.scheme=='https' and not u.username and not u.password and u.port in (None,443) and any(host==d or host.endswith('.'+d) for d in DOMAINS)

def digest(data):
    return hashlib.sha256(data if isinstance(data,bytes) else data.encode()).hexdigest()

def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def read_json(path,default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else copy.deepcopy(default)

def podcast_body(edition):
    p=edition['podcast']
    return '\n\n'.join([p['opening'],p['bluf'],*p['developments'],p['oklahoma'],p['signals'],p['actions'],p['deadlines'],p['closing']])

def validate_edition(e, expected, retrieved=None):
    Draft202012Validator(SCHEMA).validate(e)
    assert e['edition_date']==expected, 'Edition date does not match requested date'
    date.fromisoformat(expected)
    assert 1700<=len(podcast_body(e).split())<=2000, 'Spoken body must contain 1700 to 2000 words'
    text=json.dumps(e,ensure_ascii=False)
    assert not re.search(r'draft pending|\bTODO\b|\bTBD\b|lorem ipsum|placeholder',text,re.I), 'Placeholder text'
    assert '\u2014' not in text, 'Use punctuation other than em dashes'
    assert not re.search(r'https?://|<[^>]+>',podcast_body(e)), 'Spoken body contains URLs or markup'
    for field in ['stories','actions','signals','issue_updates','sources']:
        ids=[x['id'] for x in e[field]]
        assert len(ids)==len(set(ids)), f'Duplicate {field} IDs'
        assert all(re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}',x) for x in ids), f'Unsafe {field} ID'
    sources={s['id']:s for s in e['sources']}
    assert len({urlsplit(s['url']).hostname for s in sources.values()})>=2, 'Need multiple source domains'
    for s in sources.values():
        assert allowed_url(s['url']), 'Source URL outside approved public domains'
        if s['published_date']:
            assert date.fromisoformat(s['published_date'])<=date.fromisoformat(expected), 'Future-dated source'
        if retrieved is not None:
            assert canonical_url(s['url']) in retrieved, 'Source not observed in research tool results'
    for field in ['stories','actions','deadlines','signals','issue_updates']:
        for item in e[field]:
            assert all(x in sources for x in item['source_ids']), 'Unresolved source reference'
    for deadline in e['deadlines']:
        delta=(date.fromisoformat(deadline['date'])-date.fromisoformat(expected)).days
        assert 0<=delta<=30, 'Deadline is not within the next 30 days'
    for a in e['actions']:
        if a['due_date']:
            assert date.fromisoformat(a['due_date'])>=date.fromisoformat(expected), 'Action due date is already past'
    assert len(e['bluf'].split())<=180, 'Executive BLUF is too long'
    return e

def safe_path(root, relative):
    p=Path(relative)
    assert not p.is_absolute() and '..' not in p.parts, 'Unsafe release path'
    full=(root/p).resolve()
    assert full.is_relative_to(root.resolve()), 'Path escaped release root'
    return full

def merge_intelligence(previous,e):
    state=copy.deepcopy(previous or {'issues':[],'actions':[]})
    by_id={i['id']:i for i in state.get('issues',[])}
    changes={k:[] for k in ['New','Changed','Continuing','Closed']}
    sources={s['id']:s for s in e['sources']}
    touched=set()
    for u in e['issue_updates']:
        old=by_id.get(u['id']); touched.add(u['id'])
        public={k:copy.deepcopy(v) for k,v in u.items() if k not in ('history_note','source_ids')}
        public['refs']=[[sources[s]['title'],sources[s]['url']] for s in u['source_ids']]
        changed=not old or any(old.get(k)!=public[k] for k in ('title','status','risk','horizon','summary','nextMilestone'))
        history=copy.deepcopy(old.get('history',[])) if old else []
        if changed:
            history.insert(0,[e['edition_date'],u['history_note']])
        public['evidence_status']='Source-checked '+e['edition_date']
        public['history']=history
        public['lastChanged']=e['edition_date'] if changed else old.get('lastChanged',e['edition_date'])
        by_id[u['id']]=public
        group='New' if not old else ('Closed' if changed and u['status'] in ('Closed','Superseded') else ('Changed' if changed else 'Continuing'))
        changes[group].append(u['title']+': '+u['history_note'] if changed else u['title'])
    for identifier,i in by_id.items():
        if identifier not in touched and i.get('status','').lower() not in ('closed','superseded','completed'):
            changes['Continuing'].append(i['title'])
    actions={a['id']:a for a in state.get('actions',[])}
    for a in e['actions']:
        if a['id'] in actions:
            # Never infer completion or actual employee progress from a news source.
            actions[a['id']].update(title=a['title'],due=a['due_date'] or 'Ongoing',next=a['next_step'])
        else:
            actions[a['id']]={'id':a['id'],'title':a['title'],'status':'Open','owner':a['suggested_function'],
                'owner_is_suggested':True,'due':a['due_date'] or 'Ongoing','next':a['next_step'],'source':a['issue_id']}
    return {'issues':list(by_id.values()),'actions':list(actions.values()),'changes':changes,'reviewed':e['edition_date']}

def esc(value): return html.escape(str(value or ''),quote=True)
def pill(status):
    slug=re.sub(r'[^a-z0-9]+','-',status.lower()).strip('-')
    return f'<span class="tracker-status status-{slug}">{esc(status)}</span>'
def refs(items):
    return ''.join(f'<a class="reading-link" href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(title)} ↗</a>' for title,url in items)
def card(title,body,extra=''):
    return f'<div class="card {extra}"><h2>{esc(title)}</h2>{body}</div>'

def tracker_html(state):
    rows=[]
    for i in state.get('issues',[]):
        history=''.join(f'<li><b>{esc(d)}:</b> {esc(v)}</li>' for d,v in i.get('history',[]))
        rows.append(f'<div class="tracker-row" id="issue-{esc(i["id"])}"><div class="tracker-top"><b>{esc(i["title"])}</b>{pill(i.get("status","Monitoring"))}</div><div class="tracker-meta"><span>Risk: {esc(i.get("risk"))}</span><span>Horizon: {esc(i.get("horizon"))}</span><span>Last changed: {esc(i.get("lastChanged"))}</span></div><p>{esc(i.get("summary"))}</p><p class="meta">{esc(i.get("evidence_status","Legacy record; re-verification pending"))}</p><p><b>Next milestone:</b> {esc(i.get("nextMilestone"))}</p><details><summary>Issue history and evidence</summary><ul>{history}</ul>{refs(i.get("refs",[]))}</details></div>')
    legend='<details><summary>Status color key</summary><div class="tracker-meta">'+''.join(pill(s) for s in STATUSES)+'</div><p>Colors show stage, not severity. Risk and horizon remain separate.</p></details>'
    out=card('Persistent Issue Tracker',legend+'<div class="tracker-grid">'+''.join(rows)+'</div>')
    action_rows=''.join(f'<div class="tracker-row"><b>{esc(a["title"])}</b><div>{pill(a.get("status","Open"))} Due: {esc(a.get("due"))}</div><p>Suggested function: {esc(a.get("owner"))}</p><p>{esc(a.get("next"))}</p></div>' for a in state.get('actions',[]))
    return out+card('Persistent Action Tracker','<p class="meta">Planning prompts, not verified assignments or staff progress. Carried-forward legacy statuses have not been independently verified.</p>'+action_rows)

def signal_html(signals):
    out=[]
    for s in signals:
        out.append(f'<div class="card" id="signal-{esc(s["id"])}"><h2>{esc(s["title"])}</h2><div class="tracker-meta"><span>{esc(s["direction"])}</span><span>Confidence: {esc(s["confidence"])}</span><span>Horizon: {esc(s["horizon"])}</span></div><p>{esc(s["summary"])}</p><p><b>Why it matters:</b> {esc(s["why"])}</p><p class="meta">Evidence reviewed: {esc(s.get("reviewed","Legacy reference, review date not recorded"))}</p>{refs(s.get("refs",[]))}</div>')
    return ''.join(out) or card('Signals & Trends','<p>No reviewed signals are available.</p>')

def archive_html(catalog):
    entries=sorted(catalog.get('editions',[]),key=lambda x:x['date'],reverse=True)
    body=''.join(f'<a class="edition-row" href="{esc(e["path"])}"><b>{esc(e["date"])}</b> {esc(e.get("title",e["date"]))}</a>' for e in entries if e.get('status')=='available')
    return card('Archive',f'<p class="meta">{len(entries)} preserved entries. Unpublished dates are not invented.</p>'+body)

def freeze_template(root):
    path=root/'templates/app.html'
    if path.exists(): return path.read_text(encoding='utf-8')
    soup=BeautifulSoup((root/'index.html').read_text(encoding='utf-8'),'html.parser')
    for s in soup.find_all('script'): s.decompose()
    for section in soup.select('.page'): section.clear()
    for old in soup.select('link[href="web/release.css"]'): old.decompose()
    css=soup.new_tag('link',rel='stylesheet',href='web/release.css'); soup.head.append(css)
    js=soup.new_tag('script',src='web/release-runtime.js'); js['defer']=''; soup.body.append(js)
    for btn in soup.select('.tab-btn'):
        onclick=btn.attrs.pop('onclick','')
        match=re.search(r"showTab\(['\"](\w+)",onclick)
        if match: btn['data-tab']=match.group(1)
        btn['type']='button'
    for n in soup.select('[id="intelligence-container"], [id="signals-reference-container"]'): n.decompose()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(str(soup),encoding='utf-8')
    return str(soup)

def render(root,e,state,signals,catalog,generated_at):
    sources={s['id']:s for s in e['sources']}
    def cite(ids): return refs([[sources[x]['title'],sources[x]['url']] for x in ids])
    soup=BeautifulSoup(freeze_template(root),'html.parser')
    soup.select_one('meta[name="edition-date"]')['content']=e['edition_date']
    fresh=soup.select_one('.fresh')
    fresh.clear(); fresh.append(BeautifulSoup(f'<span id="freshness">Edition {esc(e["edition_date"])}</span><span>Prepared {esc(generated_at)}</span>','html.parser'))
    status='<div class="statusbar">'+''.join(f'<div class="status"><strong>{n}</strong><span>{label}</span></div>' for n,label in [(5,'Priorities'),(sum('oklahoma' in (s['category']+' '+s['title']).lower() for s in e['stories']),'Oklahoma'),(len(e['deadlines']),'Deadlines'),(len(e['actions']),'Actions')])+'</div>'
    listen=card('Listen to this edition','<p class="meta">AI-generated narration. Public-source briefing.</p><p id="listen-state" role="status">Checking audio availability...</p><audio id="daily-audio" controls preload="none" hidden></audio><p id="listen-meta"></p><a id="listen-link" hidden>Open audio file</a> <a id="transcript-link" hidden>Read transcript</a>','listen-card')
    action=''.join(f'<div class="action-item"><div class="action-date">{esc(a["due_date"] or "Ongoing")}</div><div><b>{esc(a["title"])}</b><p>{esc(a["next_step"])}</p>{cite(a["source_ids"])}</div></div>' for a in e['actions'])
    changes=''.join(f'<details><summary><b>{len(v)}</b> {esc(k)}</summary><ul>'+''.join('<li>'+esc(x)+'</li>' for x in v)+'</ul></details>' for k,v in state['changes'].items())
    stories=''.join(f'<article class="story"><div class="story-head"><span class="rank">{n}</span><h3>{esc(s["title"])}</h3></div><span class="tag">{esc(s["category"])}</span><span class="tag">{esc(s["policy_state"])}</span><p>{esc(s["what_changed"])}</p><div class="lens"><b>Why it matters:</b> {esc(s["why_it_matters"])}<br><b>Executive question:</b> {esc(s["executive_question"])}</div>{cite(s["source_ids"])}</article>' for n,s in enumerate(e['stories'],1))
    snap='<div class="signal-grid">'+''.join(f'<a class="sig" data-tab="signals" href="#signal-{esc(s["id"])}"><b>{esc(s["title"])}</b><span>{esc(s["direction"])} · {esc(s["confidence"])} confidence</span></a>' for s in e['signals'])+'</div>'
    deadlines=''.join(f'<div class="deadline-row"><b class="deadline-date">{esc(d["date"])}</b><div><b>{esc(d["title"])}</b><p>{esc(d["description"])}</p><small>{esc(d["kind"])}</small>{cite(d["source_ids"])}</div></div>' for d in e['deadlines']) or '<p>No verified deadlines within the next 30 days.</p>'
    body=status+listen+card('Executive BLUF','<p>'+esc(e['bluf'])+'</p>','bluf')+card('Executive Actions',action,'actions')+card('Since the Last Edition',changes)+card('Top 5 Developments',stories)+card('Signals Snapshot',snap)+card('Deadline Watch',deadlines)+tracker_html(state)+card('Primary & Supporting Sources','<details><summary>Show sources</summary>'+refs([[s['title'],s['url']] for s in e['sources']])+'</details>')
    soup.select_one('#page-today').append(BeautifulSoup(body,'html.parser'))
    soup.select_one('#page-signals').append(BeautifulSoup(signal_html(signals),'html.parser'))
    soup.select_one('#page-archive').append(BeautifulSoup(archive_html(catalog),'html.parser'))
    assert len(soup.select('#page-today'))==1 and len(soup.select('#daily-audio'))==1
    return str(soup)

def historical_page(content):
    soup=BeautifulSoup(content,'html.parser')
    if soup.html: soup.html['data-archived']='true'
    for el in soup.find_all('script'): el.decompose()
    for el in soup.select('link[rel="manifest"]'): el.decompose()
    if soup.head:
        for b in soup.find_all('base'): b.decompose()
        soup.head.insert(0,soup.new_tag('base',href=BASE))
        s=soup.new_tag('script',src=BASE+'web/release-runtime.js'); s['defer']=''; soup.head.append(s)
        soup.head.append(soup.new_tag('link',rel='stylesheet',href=BASE+'web/release.css'))
    if soup.body:
        banner=soup.new_tag('p'); banner['class']='archive-banner'
        a=soup.new_tag('a',href=BASE); a.string='Historical edition | Return to current edition'
        banner.append(a); soup.body.insert(0,banner)
    for b in soup.select('.tab-btn'):
        match=re.search(r"showTab\(['\"](\w+)",b.attrs.pop('onclick',''))
        if match: b['data-tab']=match.group(1)
    return str(soup)

def validate_catalog(root,catalog):
    dates=[]
    for e in catalog.get('editions',[]):
        d=e['date']; date.fromisoformat(d); dates.append(d)
        assert e['path']==f'archive/{d}.html', 'Catalog filename/date mismatch'
        p=safe_path(root,e['path'])
        assert p.is_file() and p.stat().st_size>100, 'Catalog points to missing/empty archive'
        meta=BeautifulSoup(p.read_text(encoding='utf-8'),'html.parser').select_one('meta[name="edition-date"]')
        if meta: assert meta.get('content')==d, 'Archive content/date mismatch'
    assert len(dates)==len(set(dates)), 'Duplicate archive dates'

def assemble_site(root):
    site=root/'.site'
    if site.exists(): shutil.rmtree(site)
    site.mkdir()
    for name in ['index.html','manifest.webmanifest','sw.js','podcast.xml','podcast-art.png','the-rural-update-logo.png','release.json']:
        if (root/name).exists(): shutil.copy2(root/name,site/name)
    for name in ['archive','audio','transcript','icons','web','data']:
        if (root/name).exists(): shutil.copytree(root/name,site/name)
    # Expose only scripts attached to an approved release, not cached/draft material.
    for record_path in (root/'editions').glob('*.json'):
        record=read_json(record_path,{})
        script=root/f'podcast-script/{record_path.stem}.txt'
        if record.get('audit',{}).get('approved') and script.exists():
            (site/'podcast-script').mkdir(exist_ok=True)
            shutil.copy2(script,site/'podcast-script'/script.name)
    for temporary in site.rglob('*.tmp*'):
        if temporary.is_file(): temporary.unlink()
    (site/'.nojekyll').touch()
    for p in (site/'archive').glob('*.html'):
        p.write_text(historical_page(p.read_text(encoding='utf-8')),encoding='utf-8')
    return site

def create_manifest(site,edition,code_sha,audio_status,revision,paths):
    files={}
    for name in sorted(set(paths)):
        p=safe_path(site,name)
        assert p.is_file() and p.stat().st_size, 'Release artifact missing: '+name
        files[name]={'sha256':digest(p.read_bytes()),'bytes':p.stat().st_size}
    manifest={'schema_version':1,'edition_date':edition,'revision':revision,'code_sha':code_sha,
              'built_at':datetime.now(TZ).isoformat(),'audio_status':audio_status,'files':files}
    write_json(site/'release.json',manifest)
    return manifest

ITUNES='http://www.itunes.com/dtds/podcast-1.0.dtd'
PODCAST='https://podcastindex.org/namespace/1.0'

def update_feed(root,edition,published_at):
    path=root/'podcast.xml'; tree=ET.parse(path); channel=tree.getroot().find('channel')
    for ns,prefix in [(ITUNES,'itunes'),(PODCAST,'podcast'),('http://www.w3.org/2005/Atom','atom'),('http://purl.org/rss/1.0/modules/content/','content')]:
        ET.register_namespace(prefix,ns)
    d=edition['edition_date']; guid='the-rural-update-'+d
    for item in list(channel.findall('item')):
        if item.findtext('guid')==guid: channel.remove(item)
    audio=root/f'audio/{d}.mp3'
    item=ET.Element('item')
    for key,val in [('title',edition['title']),('description',edition['bluf']),('pubDate',format_datetime(datetime.fromisoformat(published_at)))]:
        ET.SubElement(item,key).text=val
    ET.SubElement(item,'guid',isPermaLink='false').text=guid
    ET.SubElement(item,'enclosure',url=BASE+f'audio/{d}.mp3?v='+digest(audio.read_bytes())[:16],length=str(audio.stat().st_size),type='audio/mpeg')
    duration=probe_audio(audio)
    ET.SubElement(item,f'{{{ITUNES}}}duration').text=f'{int(duration)//60}:{int(duration)%60:02d}'
    ET.SubElement(item,f'{{{PODCAST}}}transcript',url=BASE+f'transcript/{d}.html',type='text/html')
    channel.insert(0,item)
    stamp=channel.find('lastBuildDate')
    if stamp is None: stamp=ET.SubElement(channel,'lastBuildDate')
    stamp.text=format_datetime(datetime.now(TZ))
    ET.indent(tree); tree.write(path,encoding='utf-8',xml_declaration=True)

def probe_audio(path):
    raw=subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(path)],text=True,timeout=30)
    seconds=float(raw.strip()); assert seconds>0,'Empty audio'
    subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],check=True,timeout=90,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    return seconds
