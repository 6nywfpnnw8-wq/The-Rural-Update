"""Speech completeness checks. Independent ASR receives audio, never the script.
Small sentence-bounded WAV segments avoid concatenated MP3 header ambiguity.
ASR checks completeness, not clinical or numerical accuracy.
"""
from __future__ import annotations
import difflib,json,os,re,subprocess,time,urllib.error,urllib.request,uuid,wave
from pathlib import Path
from release_core import digest,read_json,write_json,podcast_body,probe_audio

NUMBERS=set(('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million billion first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth thirtieth').split())

NORMALIZATION_VERSION = 5

def tokens(text):
    # Documented orthographic equivalents, not fuzzy semantic substitutions.
    text=text.lower().replace('\u2019', "'").replace('\u2018', "'")
    text=re.sub(r'\bpassthrough(s?)\b', r'pass through\1', text)
    text=re.sub(r'\bsubaward(s?)\b', r'sub award\1', text)
    # Same spoken forms observed in retained, independently transcribed audio.
    text=re.sub(r'\btradeoff(s?)\b', r'trade off\1', text)
    text=re.sub(r'\bforego\b', 'forgo', text)
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

def segments(text,max_words=170,max_parts=24,allow_clauses=False):
    units=[]
    for sentence in re.split(r'(?<=[.!?])\s+',text.strip()):
        if len(sentence.split())<=max_words:
            units.append(sentence);continue
        clauses=re.split(r'(?<=[;:])\s+',sentence) if allow_clauses else [sentence]
        if len(clauses)<2 or any(len(clause.split())>max_words for clause in clauses):
            raise ValueError('Narration sentence exceeds the speech segment limit')
        units.extend(clauses)
    parts=[];current=[]
    for unit in units:
        if current and len((' '.join(current)+' '+unit).split())>max_words:
            parts.append(' '.join(current));current=[]
        current.append(unit)
    if current: parts.append(' '.join(current))
    if not parts or len(parts)>max_parts: raise ValueError('Speech segment count is outside limits')
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
    if out.exists():
        saved=read_json(out)
        if (saved.get('script_sha256')==digest(script) and
                saved.get('normalization_version')==NORMALIZATION_VERSION):return saved
    tail=cache/'inspection-tail.wav'
    run(['ffmpeg','-y','-v','error','-sseof','-90','-i',str(audio),'-ar','24000','-ac','1','-c:a','pcm_s16le',str(tail)])
    text=transcribe(tail,cache); result=ending_check(script,text)
    report={'normalization_version':NORMALIZATION_VERSION,'audio_sha256':digest(audio.read_bytes()),'script_sha256':digest(script),'result':result,'recognized_tail':text[-900:]}
    write_json(out,report);return report

MAX_SPEECH_REQUESTS = 64
MAX_ACCEPTED_PARTS = 48


def speech_payload(text,model,voice):
    return {'model':model,'voice':voice,'input':text,
            'instructions':'Read every word through the complete final sentence. Calm professional American English. Natural pauses. Approximately 145 to 155 words per minute.',
            'response_format':'wav','speed':1.0}


def split_failed_segment(text):
    """One subdivision at sentence or explicit clause boundaries, with no text loss."""
    sentences=re.split(r'(?<=[.!?])\s+',text.strip())
    if len(sentences)<2:sentences=re.split(r'(?<=[;:])\s+',text.strip())
    if len(sentences)<2:raise RuntimeError('Failed single-sentence audio requires review')
    longest=max(len(s.split()) for s in sentences)
    target=max(longest,(len(text.split())+1)//2)
    children=segments(text,max_words=target,max_parts=4,allow_clauses=True)
    if not 2<=len(children)<=4:raise RuntimeError('Failed audio cannot be subdivided safely')
    assert ' '.join(text.split())==' '.join(' '.join(children).split()),'Audio subdivision lost text'
    return children


def collect_verified_segments(body,cache,request,model,voice):
    """Short initial passages; one bounded subdivision for failed passages.

    Legacy 170-word work is reused when its exact first payload already exists.
    Exhausted ledgers are never reset. Every accepted leaf must pass the same ASR
    thresholds. A script-word partition proves that assembly cannot omit a leaf.
    """
    folder=cache/'audio-v2';folder.mkdir(parents=True,exist_ok=True)
    legacy=segments(body,max_words=170,allow_clauses=True)
    first_key=digest(json.dumps(speech_payload(legacy[0],model,voice),sort_keys=True))
    use_legacy=any((folder/(first_key+f'-{n}.wav')).exists() for n in range(2))
    parts=legacy if use_legacy else segments(body,max_words=90,max_parts=32,allow_clauses=True)
    accepted=[];accepted_text=[];reports=[];position=0

    def visit(text,origin,depth):
        nonlocal position
        if len(accepted)>=MAX_ACCEPTED_PARTS:raise RuntimeError('Accepted audio segment limit reached')
        payload=speech_payload(text,model,voice)
        key=digest(json.dumps(payload,sort_keys=True));ledger=folder/(key+'-attempts.json')
        state=read_json(ledger,{'attempts':0})
        if type(state.get('attempts')) is not int or not 0<=state['attempts']<=2:
            raise RuntimeError('Invalid speech attempt ledger')
        for attempt in range(2):
            part=folder/(key+f'-{attempt}.wav')
            if not part.exists():
                if state['attempts']>=2:break
                spent=sum(read_json(p,{}).get('attempts',0) for p in folder.glob('*-attempts.json'))
                if spent>=MAX_SPEECH_REQUESTS:raise RuntimeError('Daily speech request budget reached')
                state['attempts']+=1;write_json(ledger,state)
                data=request(payload,'audio/speech',True)
                temp=part.with_suffix('.tmp.wav');temp.write_bytes(data);probe_audio(temp);temp.replace(part)
            recognized=transcribe(part,folder);result=coverage(text,recognized)
            row={'index':len(accepted),'original_index':origin,'split_depth':depth,
                 'attempt':attempt+1,'text_sha256':digest(text),
                 'normalized_text_sha256':digest(' '.join(text.split())),
                 'audio_sha256':digest(part.read_bytes()),**result}
            if result['passed']:
                row['start_word']=position;position+=len(text.split());row['end_word']=position
                accepted.append(part);accepted_text.append(text)
            reports.append(row)
            write_json(cache/'audio-quality-progress.json',{'normalization_version':NORMALIZATION_VERSION,'parts':reports,
                'source_parts':len(parts),'accepted_leaf_parts':len(accepted),
                'maximum_split_depth':1,'complete':False})
            if result['passed']:return
        if depth>=1:raise RuntimeError(f'Incomplete subdivided audio segment {origin+1}; publication blocked')
        for child in split_failed_segment(text):visit(child,origin,depth+1)

    for number,text in enumerate(parts):visit(text,number,0)
    if ' '.join(body.split())!=' '.join(' '.join(accepted_text).split()):
        raise RuntimeError('Accepted audio segments do not cover the complete script in order')
    return accepted,reports,len(parts)


def build_audio(edition,cache,output,request):
    body=podcast_body(edition)
    model=os.getenv('OPENAI_TTS_MODEL','gpt-4o-mini-tts');voice=os.getenv('OPENAI_TTS_VOICE','cedar')
    accepted,report_parts,source_parts=collect_verified_segments(body,cache,request,model,voice)
    folder=cache/'audio-v2'
    combined=folder/'assembled.wav';total=0
    with wave.open(str(combined),'wb') as dest:
        dest.setnchannels(1);dest.setsampwidth(2);dest.setframerate(24000)
        for i,p in enumerate(accepted):
            pcm=folder/f'pcm-{i}.wav';run(['ffmpeg','-y','-v','error','-i',str(p),'-ar','24000','-ac','1','-c:a','pcm_s16le',str(pcm)])
            with wave.open(str(pcm),'rb') as src:
                count=src.getnframes();total+=count;dest.writeframes(src.readframes(count))
    output.parent.mkdir(parents=True,exist_ok=True);temp=output.with_suffix('.tmp.mp3')
    from release_audio_timing import timing_plan, encoder_arguments, validate_output_duration
    timing=timing_plan(total/24000)
    write_json(cache/'audio-quality-timing.json',{'edition_date':edition['edition_date'],
        'source_frames':total,'source_sample_rate':24000,'script_sha256':digest(body),
        'accepted_parts':len(accepted),'publication_authorized':False,**timing})
    run(['ffmpeg','-y','-v','error','-i',str(combined),*encoder_arguments(timing),
         '-c:a','libmp3lame','-b:a','128k','-write_xing','1',str(temp)])
    seconds=probe_audio(temp)
    validate_output_duration(seconds,timing)
    tail=inspect_ending(temp,body,folder)
    if not tail['result']['passed']:raise RuntimeError('Assembled episode closing narration is incomplete')
    temp.replace(output)
    report={'schema_version':2,'normalization_version':NORMALIZATION_VERSION,'edition_date':edition['edition_date'],'audio_sha256':digest(output.read_bytes()),'script_sha256':digest(body),'duration_seconds':seconds,'expected_parts':len(accepted),'accepted_parts':len(accepted),'original_parts':source_parts,'parts':report_parts,'ending_check':tail['result'],'timing_adjustment':timing,'complete':True,'method':'Independent audio-only ASR of each segment and assembled tail; numeric formats normalized. Not a word-for-word accuracy guarantee.'}
    write_json(cache/'audio-quality.json',report)
    return seconds


