from pathlib import Path
p=Path('scripts/release_narration.py')
s=p.read_text()
old='    schema=copy.deepcopy(PODCAST_SCHEMA)'
assert s.count(old)==1
# The original schema intentionally reuses a shared string-type dict. deepcopy
# preserves that alias, so per-field patterns require a de-aliased JSON copy.
s=s.replace(old,'    schema=json.loads(json.dumps(PODCAST_SCHEMA))')
p.write_text(s)
