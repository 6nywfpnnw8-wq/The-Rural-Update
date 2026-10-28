"""Read retained speech and ASR failures without generation or cache writes."""
from __future__ import annotations
import argparse,json,re,shutil
from pathlib import Path
from release_core import digest,podcast_body,validate_edition
from release_audio import segments,split_failed_segment,coverage,tokens,NORMALIZATION_VERSION
from release_diagnostics import redact


def read_json(path):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('Unsafe audio inspection path')
    if not path.is_file() or path.stat().st_size>2000000:
        raise ValueError('Missing or oversized audio inspection record')
    value=json.loads(path.read_text())
    if redact(value)!=value:raise ValueError('Audio inspection failed credential screening')
    return value


def inspect_failure(body,cache,out):
    cache=Path(cache);out=Path(out)
    if out.resolve().is_relative_to(cache.resolve()):
        raise ValueError('Audio inspection must not write inside the cache')
    progress=read_json(cache/'audio-quality-progress.json')
    failed=[row for row in progress.get('parts',[]) if row.get('passed') is False]
    if not failed:raise ValueError('No retained failed audio comparison')
    target=failed[-1];sha=target.get('text_sha256','')
    if not re.fullmatch('[a-f0-9]{64}',sha):raise ValueError('Invalid failed passage hash')
    expected=set()
    for words,limit in ((90,32),(170,24)):
        try:plan=segments(body,max_words=words,max_parts=limit,allow_clauses=True)
        except ValueError:continue
        index=target.get('original_index')
        if len(plan)!=progress.get('source_parts') or type(index) is not int or not 0<=index<len(plan):continue
        if target.get('split_depth')==0:pieces=[plan[index]]
        elif target.get('split_depth')==1:
            try:pieces=split_failed_segment(plan[index])
            except RuntimeError:continue
        else:raise ValueError('Unexpected audio subdivision depth')
        expected.update(text for text in pieces if digest(text)==sha)
    if len(expected)!=1:raise ValueError('Failed passage does not match the approved script')
    passage=expected.pop();folder=cache/'audio-v2'
    wanted=list(dict.fromkeys(row['audio_sha256'] for row in failed if row.get('text_sha256')==sha))
    if not 1<=len(wanted)<=2 or any(not re.fullmatch('[a-f0-9]{64}',s) for s in wanted):
        raise ValueError('Unexpected failed speech attempt inventory')
    wavs=list(folder.glob('*.wav'))
    if len(wavs)>128:raise ValueError('Retained audio inventory exceeds inspection limit')
    found={};total=0
    for path in wavs:
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise ValueError('Unsafe retained audio path')
        size=path.stat().st_size
        if size>8000000:continue
        total+=size
        if total>268435456:raise ValueError('Retained audio inventory exceeds byte limit')
        audio_sha=digest(path.read_bytes())
        if audio_sha in wanted:found[audio_sha]=path
    if set(found)!=set(wanted):raise ValueError('Failed speech bytes are missing or changed')
    out.mkdir(parents=True,exist_ok=True);rows=[]
    for audio_sha in wanted:
        result=read_json(folder/('asr-'+audio_sha+'.json'))
        if result.get('audio_sha256')!=audio_sha or not isinstance(result.get('text'),str):
            raise ValueError('Retained ASR does not match the failed speech bytes')
        dest=out/(audio_sha+'.wav')
        if dest.is_symlink():raise ValueError('Unsafe inspection output')
        shutil.copyfile(found[audio_sha],dest)
        rows.append({'audio_sha256':audio_sha,'text_sha256':sha,'expected':passage,
                     'recognized':result['text'],'expected_tokens':tokens(passage),
                     'recognized_tokens':tokens(result['text']),
                     'comparison':coverage(passage,result['text'])})
    report={'edition_date':cache.name,'operation':'retained_audio_inspection',
            'script_sha256':digest(body),'original_normalization_version':progress.get('normalization_version'),
            'normalization_version':NORMALIZATION_VERSION,'cache_modified':False,'api_calls_made':0,
            'publication_attempted':False,'publication_authorized':False,'rows':rows}
    target=out/'inspection.json'
    if target.is_symlink():raise ValueError('Unsafe inspection output')
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--date',required=True)
    parser.add_argument('--root',type=Path,default=Path('.'))
    parser.add_argument('--output',type=Path,default=Path('audio-inspection'))
    args=parser.parse_args()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',args.date):raise ValueError('Invalid inspection date')
    record=read_json(args.root/'editions'/(args.date+'.json'))
    if record.get('audit',{}).get('approved') is not True or record['audit'].get('issues'):
        raise ValueError('Audio inspection requires an approved edition')
    edition=record['edition'];validate_edition(edition,args.date)
    report=inspect_failure(podcast_body(edition),args.root/'.release-cache'/args.date,args.output)
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}))


if __name__=='__main__':main()
