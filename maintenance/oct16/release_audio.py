"""Speech completeness checks. Independent ASR receives audio, never the script.
Small sentence-bounded WAV segments avoid concatenated MP3 header ambiguity.
ASR checks completeness, not clinical or numerical accuracy.
"""
from __future__ import annotations
import difflib,json,os,re,subprocess,time,urllib.error,urllib.request,uuid,wave
from pathlib import Path
from release_core import digest,read_json,write_json,podcast_body,probe_audio

NUMBERS=set(('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million billion first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth thirtieth').split())

def tokens(text):
    out=[]
    for t in re.findall(r'[a-z]+|[0-9]+',text.lower().replace("'",'')):
        t='num' if t in NUMBERS or t.isdigit() else t
        if t!='num' or not out or out[-1]!='num': out.append(t)
    return out

def coverage(expected,actual):
    a,b=tokens(expected),tokens(actual)
    if not a or not b: return {'coverage':0.0,'opening':0.0,'ending':0.0,'passed':False}
    def score(x,y): return sum(m.size for m in difflib.SequenceMatcher(None,x,y,autojunk=False).get_matching_blocks())/max(1,len(x))
    whole=score(a,b); opening=score(a[:12],b[:20]); ending=score(a[-16:],b[-24:]); final=score(a[-6:],b[-8:])
    return {'coverage':round(whole,4),'opening':round(opening,4),'ending':round(ending,4),'final_words':round(final,4),'passed':whole>=.88 and opening>=.83 and ending>=.88 and final>=.9 and len(b)<=len(a)*1.3}

def ending_check(expected,actual):
    a,b=tokens(expected)[-24:],tokens(actual)[-36:]
    def score(x,y): return sum(m.size for m in difflib.SequenceMatcher(None,x,y,autojunk=False).get_matching_blocks())/max(1,len(x))
    value=score(a,b); final=score(a[-6:],b[-8:])
    return {'ending':round(value,4),'final_words':round(final,4),'passed':bool(a) and value>=.88 and final>=.9}

def segments(text,max_words=170):
    units=re.split(r'(?<=[.!?])\s+',text.strip()); parts=[]; current=[]
    for unit in units:
        if len(unit.split())>max_words: raise ValueError('Narration sentence exceeds the speech segment limit')
        if current and len((' '.join(current)+' '+unit).split())>max_words:
            parts.append(' '.join(current));current=[]
        current.append(unit)
    if current: parts.append(' '.join(current))
    if not parts or len(parts)>24: raise ValueError('Speech segment count is outside limits')
    assert ' '.join(text.split())==' '.join(' '.join(parts).split()),'Speech segmentation lost source text'
    return parts

def transcribe(path,cache):
    audio=path.read_bytes(); key=digest(audio); record=cache/('asr-'+key+'.json')
    if record.exists():
        d=read_json(record)
        if d.get('audio_sha256')==key and isinstance(d.get('text'),str):return d['text']
    token=os.environ.get('OPENAI_API_KEY')
    if not token:raise RuntimeError('Audio completeness check requires configured API credentials')
    if len(audio)>24*1024*1024:raise ValueError('Audio transcription request exceeds file limit')
    boundary='ru'+uuid.uuid4().hex; data=[]
    for name,value in [('model','gpt-4o-mini-transcribe'),('response_format','json'),('language','en')]:
        data.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    data.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="segment.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode(),audio,f'\r\n--{boundary}--\r\n'.encode()])
    req=urllib.request.Request('https://api.openai.com/v1/audio/transcriptions',data=b''.join(data),headers={'Authorization':'Bearer '+token,'Content-Type':'multipart/form-data; boundary='+boundary})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req,timeout=120) as response: result=json.load(response)
            text=result.get('text')
            if not isinstance(text,str) or not text.strip():raise RuntimeError('Transcription returned no text')
            write_json(record,{'audio_sha256':key,'text':text});return text
        except urllib.error.HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt==2:raise RuntimeError(f'Audio transcription HTTP {exc.code}') from None
        except (TimeoutError,urllib.error.URLError):
            if attempt==2:raise RuntimeError('Audio transcription transport failed') from None
        time.sleep(2**attempt)
    raise RuntimeError('Transcription attempt limit reached')

def run(command):
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=120)

def inspect_ending(audio,script,cache):
    cache.mkdir(parents=True,exist_ok=True); out=cache/('ending-'+digest(audio.read_bytes())+'.json')
    if out.exists():return read_json(out)
    tail=cache/'inspection-tail.wav'
    run(['ffmpeg','-y','-v','error','-sseof','-90','-i',str(audio),'-ar','24000','-ac','1','-c:a','pcm_s16le',str(tail)])
    text=transcribe(tail,cache); result=ending_check(script,text)
    report={'audio_sha256':digest(audio.read_bytes()),'script_sha256':digest(script),'result':result,'recognized_tail':text[-900:]}
    write_json(out,report);return report

def build_audio(edition,cache,output,request):
    body=podcast_body(edition); parts=segments(body)
    folder=cache/'audio-v2';folder.mkdir(parents=True,exist_ok=True)
    model=os.getenv('OPENAI_TTS_MODEL','gpt-4o-mini-tts');voice=os.getenv('OPENAI_TTS_VOICE','cedar')
    accepted=[];report_parts=[]
    for number,text in enumerate(parts):
        payload={'model':model,'voice':voice,'input':text,'instructions':'Read every word through the complete final sentence. Calm professional American English. Natural pauses. Approximately 145 to 155 words per minute.','response_format':'wav','speed':1.0}
        key=digest(json.dumps(payload,sort_keys=True)); ledger=folder/(key+'-attempts.json')
        state=read_json(ledger,{'attempts':0}); good=False
        for attempt in range(2):
            part=folder/(key+f'-{attempt}.wav')
            if not part.exists():
                if state['attempts']>=2:break
                state['attempts']+=1;write_json(ledger,state)
                data=request(payload,'audio/speech',True)
                temp=part.with_suffix('.tmp.wav');temp.write_bytes(data);probe_audio(temp);temp.replace(part)
            recognized=transcribe(part,folder); result=coverage(text,recognized)
            report_parts.append({'index':number,'attempt':attempt+1,'text_sha256':digest(text),'audio_sha256':digest(part.read_bytes()),**result})
            write_json(cache/'audio-quality-progress.json',{'parts':report_parts,'expected_parts':len(parts),'complete':False})
            if result['passed']:
                accepted.append(part);good=True;break
        if not good:raise RuntimeError(f'Incomplete spoken segment {number+1}; audio publication blocked')
    combined=folder/'assembled.wav';total=0
    with wave.open(str(combined),'wb') as dest:
        dest.setnchannels(1);dest.setsampwidth(2);dest.setframerate(24000)
        for i,p in enumerate(accepted):
            pcm=folder/f'pcm-{i}.wav';run(['ffmpeg','-y','-v','error','-i',str(p),'-ar','24000','-ac','1','-c:a','pcm_s16le',str(pcm)])
            with wave.open(str(pcm),'rb') as src:
                count=src.getnframes();total+=count;dest.writeframes(src.readframes(count))
    output.parent.mkdir(parents=True,exist_ok=True);temp=output.with_suffix('.tmp.mp3')
    run(['ffmpeg','-y','-v','error','-i',str(combined),'-c:a','libmp3lame','-b:a','128k','-write_xing','1',str(temp)])
    seconds=probe_audio(temp)
    if abs(seconds-total/24000)>1:raise RuntimeError('Assembled audio duration does not match all decoded segments')
    if not 540<=seconds<=900:raise RuntimeError('Episode audio outside the 9 to 15 minute release limit')
    tail=inspect_ending(temp,body,folder)
    if not tail['result']['passed']:raise RuntimeError('Assembled episode closing narration is incomplete')
    temp.replace(output)
    report={'schema_version':1,'edition_date':edition['edition_date'],'audio_sha256':digest(output.read_bytes()),'script_sha256':digest(body),'duration_seconds':seconds,'expected_parts':len(parts),'accepted_parts':len(accepted),'parts':report_parts,'ending_check':tail['result'],'complete':True,'method':'Independent audio-only ASR of each segment and assembled tail; numeric formats normalized. Not a word-for-word accuracy guarantee.'}
    write_json(cache/'audio-quality.json',report)
    return seconds
