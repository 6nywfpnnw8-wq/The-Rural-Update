"""One-time review-branch preparation. Never publishes content or invokes an API."""
from pathlib import Path
import json,hashlib,shutil,sys
ROOT=Path.cwd(); STAGED=Path(__file__).resolve().parent

def change(path,old,new):
    p=ROOT/path;s=p.read_text()
    if s.count(old)!=1:raise RuntimeError('Patch anchor mismatch: '+path)
    p.write_text(s.replace(old,new),encoding='utf-8')

def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

# New module and tests are copied as readable source, not executed from staging.
shutil.copy2(STAGED/'release_audio.py',ROOT/'scripts/release_audio.py')
shutil.copy2(STAGED/'test_audio.py',ROOT/'tests/test_release_audio_completeness.py')
change('scripts/release_audio.py',"    if out.exists():return read_json(out)","    if out.exists():\n        saved=read_json(out)\n        if saved.get('script_sha256')==digest(script):return saved")

p=ROOT/'scripts/release_pipeline.py';s=p.read_text();start=s.index('def audio_for(');end=s.index('\ndef build(',start)
s=s[:start]+"def audio_for(edition,cache,output):\n    from release_audio import build_audio\n    return build_audio(edition,cache,output,request_api)\n"+s[end:];p.write_text(s)
change('scripts/release_pipeline.py','from release_narration import ensure_narration_length','from release_narration import ensure_narration_length, generation_schema')
change('scripts/release_pipeline.py',"'name':'rural_update_edition','strict':True,'schema':SCHEMA", "'name':'rural_update_edition','strict':True,'schema':generation_schema()")
change('scripts/release_pipeline.py','        audio_for(e,cache,audio)\n',"""        audio_for(e,cache,audio)
        quality=read_json(cache/'audio-quality.json',{})
        assert quality.get('complete') is True and quality.get('audio_sha256')==digest(audio.read_bytes()),'Audio completion evidence missing or mismatched'
        assert quality.get('script_sha256')==digest(body),'Audio completion evidence refers to another script'
        write_json(root/f'data/audio-quality-{date_string}.json',quality)
""")
change('scripts/release_pipeline.py','        if audio.exists(): audio.unlink()',"        (root/f'data/audio-quality-{date_string}.json').unlink(missing_ok=True)\n        if audio.exists(): audio.unlink()")
change('scripts/release_pipeline.py',"paths.extend([f'audio/{date_string}.mp3','podcast-art.png'])","paths.extend([f'audio/{date_string}.mp3','podcast-art.png',f'data/audio-quality-{date_string}.json'])")
change('scripts/release_pipeline.py','Earlier public intelligence is context only, NOT independently verified evidence:',"""Use short lowercase hyphenated identifiers without duplicates. Prefer 6-10 exact,
substantive HTML primary sources; the source collector does not parse PDFs.
Source publication dates must be ISO YYYY-MM-DD or null. A page-modification date
is not necessarily an award date. Complete every field and closing sentence.
Follow the schema's per-section word budgets: opening 50-70, BLUF 150-180,
each of the three developments 300-320, Oklahoma 220-250, signals 160-180,
actions 150-170, deadlines 70-90, closing 50-65. These total 1750-1965 words.
Add no new facts or repetitive filler merely to meet length. Use practical analysis
and clearly framed questions based on the verified reporting.
Earlier public intelligence is context only, NOT independently verified evidence:""")

change('scripts/release_editorial.py','    parts = Path(relative).parts',"    stage = plan.get('base_stage', 'content')\n    if stage not in ('content','generated'):\n        raise ValueError('Reviewed correction stage is invalid')\n    parts = Path(relative).parts")
change('scripts/release_editorial.py',"not parts[1].startswith('content-')","not parts[1].startswith(stage+'-')")
change('scripts/release_editorial.py',"_read_snapshot(cache / relative, expected, 'content')","_read_snapshot(cache / relative, expected, stage)")

change('scripts/release_narration.py',"PODCAST_SCHEMA = SCHEMA['properties']['podcast']", """PODCAST_SCHEMA = SCHEMA['properties']['podcast']
WORD_BOUNDS={'opening':(50,70),'bluf':(150,180),'developments':(300,320),
             'oklahoma':(220,250),'signals':(160,180),'actions':(150,170),
             'deadlines':(70,90),'closing':(50,65)}

def bounded_podcast_schema():
    schema=copy.deepcopy(PODCAST_SCHEMA)
    for name,(low,high) in WORD_BOUNDS.items():
        field=schema['properties'][name]
        if name=='developments':field=field['items']
        field['pattern']=r'^(\\S+\\s+){'+str(low-1)+','+str(high-1)+r'}\\S+$'
    return schema

def generation_schema():
    schema=copy.deepcopy(SCHEMA)
    schema['properties']['podcast']=bounded_podcast_schema()
    for group in ('stories','actions','signals','issue_updates','sources'):
        schema['properties'][group]['items']['properties']['id']={
            'type':'string','pattern':r'^[a-z0-9][a-z0-9-]{0,79}$'}
    return schema
""")
change('scripts/release_narration.py','        count = len(podcast_body(candidate).split())',"        from release_diagnostics import Diagnostics\n        Diagnostics(cache,edition['edition_date']).capture('narration-revision',candidate)\n        count = len(podcast_body(candidate).split())")
change('scripts/release_narration.py',"'strict': True, 'schema': PODCAST_SCHEMA", "'strict': True, 'schema': bounded_podcast_schema()")
change('scripts/release_narration.py','opening 60; bluf 160; developments 350 EACH (three items); oklahoma 180;\nsignals 120; actions 150; deadlines 80; closing 50. Total target: 1850 words.', 'opening 60; bluf 165; developments 310 EACH (three items); oklahoma 235;\nsignals 170; actions 160; deadlines 80; closing 55. Total target: 1855 words.\nThe schema enforces a bounded word range for each field. Follow those ranges.')

change('scripts/release_diagnostics.py','    # Report a safe exception category without leaking source text or raw API payloads.',"""    for field in ('stories','actions','signals','issue_updates','sources'):
        if raw in ('Duplicate '+field+' IDs','Unsafe '+field+' ID'):
            return {'rule':'identifier','message':'Invalid or duplicate identifier','path':'/'+field}
    if raw in ('Model response incomplete or failed','Model returned no output text','Research did not use web search'):
        return {'rule':'research_response','message':raw,'path':'/'}
    if re.fullmatch(r'Spoken body has [0-9]+ words after 2 revisions; required 1700 to 2000. Publication blocked.',raw):
        return {'rule':'spoken_word_count','message':raw,'path':'/podcast'}
    # Report a safe exception category without leaking source text or raw API payloads.""")
change('scripts/release_diagnostics.py',"    stage = report.get('stage', 'validation')", "    if rule in ('identifier','research_response','spoken_word_count'):\n        return 'Validation rule '+rule+' failed at '+pointer_from_report(report.get('path','/'))\n    stage = report.get('stage', 'validation')")

change('scripts/release_verify.py','    checked=[]',"""    checked=[]
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
""")
change('scripts/release_verify.py',"'checked_files':checked}","'checked_files':checked,'narration_completion_verified':bool(quality)}")

change('.github/workflows/publish.yml','      - name: Prepare and atomically save validated release',"""      - name: Inspect the reported October 14 cutoff without changing its audio
        if: steps.edition.outputs.date == '2026-10-16' && (env.MODE == 'publish' || env.MODE == 'recover')
        continue-on-error: true
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          python3 - <<'PY'
          import sys,json,pathlib
          sys.path.insert(0,'scripts')
          from release_audio import inspect_ending
          from generate_podcast_audio import spoken_body
          audio=pathlib.Path('audio/2026-10-14.mp3')
          text=spoken_body(pathlib.Path('podcast-script/2026-10-14.txt').read_text())
          cache=pathlib.Path('.release-cache/2026-10-16')
          report=inspect_ending(audio,text,cache/'legacy-audio')
          (cache/'legacy-audio-inspection.json').write_text(json.dumps(report,indent=2))
          print('October 14 ending present:',report['result']['passed'])
          PY
      - name: Prepare and atomically save validated release""")
change('.github/workflows/publish.yml','            .release-cache/*/audit-bound.json','            .release-cache/*/audit-bound.json\n            .release-cache/*/audio-quality*.json\n            .release-cache/*/legacy-audio-inspection.json')

change('tests/test_release.py','            return 720\n',"            core.write_json(cache/'audio-quality.json',{'complete':True,'audio_sha256':core.digest(out.read_bytes()),'script_sha256':core.digest(core.podcast_body(e))})\n            return 720\n")
change('tests/test_release.py',"def audio(e,cache,out): out.write_bytes(b'ID3recovered'); return 720", "def audio(e,cache,out):\n            out.write_bytes(b'ID3recovered')\n            core.write_json(cache/'audio-quality.json',{'complete':True,'audio_sha256':core.digest(out.read_bytes()),'script_sha256':core.digest(core.podcast_body(e))})\n            return 720")

candidate=json.loads((STAGED/'candidate.json').read_text())
sys.path.insert(0,str(ROOT/'scripts'))
from release_core import validate_edition,podcast_body
validate_edition(candidate,'2026-10-16')
plan={'schema_version':1,'edition_date':'2026-10-16','base_stage':'generated',
 'base_snapshot':'candidates/generated-eff271a40de955d0.json',
 'base_candidate_sha256':'eff271a40de955d041a2214c91c57e5c9651fe2bf1de28b79fcf0470be9fe50b',
 'candidate_sha256':fingerprint(candidate),'publication_authorized':False,
 'reason':'Explicit October 16 primary-source editorial recovery under user deployment request. No research counters reset; exact retained base required; one fresh audit still required.',
 'reviewed_source_urls':[x['url'] for x in candidate['sources']],'candidate':candidate}
(ROOT/'editorial-review/2026-10-16.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
print('Prepared source patch and reviewed candidate; spoken words:',len(podcast_body(candidate).split()))
