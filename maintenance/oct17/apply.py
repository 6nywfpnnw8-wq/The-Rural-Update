"""Apply only the readable, locally tested source changes on the review branch."""
from pathlib import Path
p=Path('scripts/release_research.py');s=p.read_text()
assert "ENGINE = 'staged-research-v2'" in s
s=s.replace('from release_core import SCHEMA, TZ, digest, read_json, write_json','from release_core import SCHEMA, TZ, digest, read_json, write_json, allowed_url, canonical_url')
s=s.replace("ENGINE = 'staged-research-v2'","ENGINE = 'staged-research-v3'")
s=s.replace("STAGES = {'discovery', 'reporting', 'narration',","STAGES = {'discovery', 'sources', 'reporting', 'narration',")
s=s.replace('def reporting_schema() -> dict:','def reporting_schema(catalog: list[dict] | None = None) -> dict:')
s=s.replace('    walk(schema)\n    return schema\n', '''    walk(schema)
    if catalog is not None:
        identifiers=[item['id'] for item in catalog]
        if not identifiers or len(identifiers)!=len(set(identifiers)):
            raise ValueError('Source catalog has no unique identifiers')
        schema['properties'].pop('sources')
        schema['required'].remove('sources')
        def bind(node):
            for key,child in node.get('properties',{}).items():
                if key=='source_ids':
                    child['items']={'type':'string','enum':identifiers}
                else:bind(child)
            if isinstance(node.get('items'),dict):bind(node['items'])
        bind(schema)
    return schema


def observed_html_urls(discovery: dict) -> list[str]:
    # Only actual tool events count; a URL typed into model prose is insufficient.
    found=set()
    for item in discovery.get('web_search_items',[]):
        action=item.get('action') or {}
        urls=[x.get('url') for x in action.get('sources',[]) if isinstance(x,dict)]
        urls.extend(action.get('urls',[]))
        urls.append(action.get('url'))
        for url in urls:
            if not isinstance(url,str):continue
            try:
                if allowed_url(url) and not re.search(r'\\.pdf(?:[?#]|$)',url,re.I):
                    found.add(url)
            except ValueError:continue
    if len(found)<5:raise ValueError('Fewer than five observed readable-source URLs')
    return sorted(found)


def source_catalog_schema(urls: list[str]) -> dict:
    items=json.loads(json.dumps(SCHEMA['properties']['sources']['items']))
    items['properties']['id']={'type':'string','pattern':r'^[a-z0-9][a-z0-9-]{0,79}$'}
    items['properties']['title']={'type':'string','maxLength':220}
    items['properties']['url']={'type':'string','enum':urls}
    items['properties']['published_date']={'type':['string','null'],
                                           'pattern':r'^\\d{4}-\\d{2}-\\d{2}$'}
    return {'type':'object','properties':{'sources':{'type':'array','items':items,
                'minItems':5,'maxItems':12}},'required':['sources'],'additionalProperties':False}


def validate_source_catalog(catalog,urls):
    Draft202012Validator(source_catalog_schema(urls)).validate({'sources':catalog})
    ids=[s['id'] for s in catalog]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate source catalog identifier')
    unique={canonical_url(s['url']) for s in catalog}
    if len(unique)!=len(catalog):raise ValueError('Duplicate source catalog URL')
    return catalog


def validate_reference_bindings(report: dict,catalog: list[dict]):
    # This metadata check does not assert that a document substantiates a claim.
    # Exact HTTP retrieval and the separate whole-edition audit remain mandatory.
    expected={s['id'] for s in catalog}
    for group in ('stories','actions','deadlines','signals','issue_updates'):
        for index,item in enumerate(report.get(group,[])):
            refs=item.get('source_ids',[])
            if not refs or len(refs)!=len(set(refs)) or any(v not in expected for v in refs):
                raise ValueError('Unresolved reference at '+group+'/'+str(index)+'/source_ids')
    return report
''')
s=s.replace('Three small requests replace one search-plus-long-JSON generation request.','Discovery, a fixed catalog, reporting, and narration have separate budgets.')
s=s.replace("    schema=reporting_schema()\n    reporting=", '''    urls=observed_html_urls(discovery)
    selected=_cached(folder/'sources.json',identity)
    if selected is None:
        req={**common,'max_output_tokens':4000,
             'instructions':(
                 'Select five to twelve substantive sources for this rural-health briefing. '
                 'Use only the exact URLs in the allowed catalog and facts in the research notes. '
                 'Choose enough relevant sources to support four signals with at least two '
                 'references each, not unrelated pages to satisfy a count. Give each source '
                 'one unique short lowercase hyphenated ID. Use an actual publication date '
                 'only when known; otherwise null. Do not confuse modified dates with new '
                 'announcements. This is source selection, not source verification or approval. '
                 'Return only source metadata, not a briefing or narration.'),
             'input':json.dumps({'research_notes':discovery['notes'],'allowed_urls':urls},ensure_ascii=False),
             'text':{'format':{'type':'json_schema','name':'sources','strict':True,
                               'schema':source_catalog_schema(urls)}}}
        raw=send(req)
        value=json.loads(_text(raw))
        catalog=validate_source_catalog(value['sources'],urls)
        selected={'sources':catalog,'usage':raw.get('usage')}
        _save(folder/'sources.json',identity,selected)
    catalog=validate_source_catalog(selected['sources'],urls)
    schema=reporting_schema(catalog)
    reporting=''')
s=s.replace("'resolvable source_ids, and ISO dates or null. Do not treat a last-modified date '","'source_ids only from the supplied fixed catalog, and ISO dates or null. Do not treat a last-modified date '")
s=s.replace("'input':json.dumps({'editorial_request':context,'research_notes':discovery['notes']},ensure_ascii=False),","'input':json.dumps({'editorial_request':context,'research_notes':discovery['notes'],\n                                 'fixed_sources':catalog},ensure_ascii=False),")
s=s.replace('        Draft202012Validator(schema).validate(value)\n        reporting=','        Draft202012Validator(schema).validate(value)\n        validate_reference_bindings(value,catalog)\n        reporting=')
s=s.replace("    Draft202012Validator(schema).validate(reporting['edition'])\n    narration=","    Draft202012Validator(schema).validate(reporting['edition'])\n    validate_reference_bindings(reporting['edition'],catalog)\n    from release_narration import bounded_podcast_schema\n    narration=")
s=s.replace("'schema':json.loads(json.dumps(SCHEMA['properties']['podcast']))","'schema':bounded_podcast_schema()")
s=s.replace("Draft202012Validator(SCHEMA['properties']['podcast']).validate(value)","Draft202012Validator(bounded_podcast_schema()).validate(value)")
s=s.replace("    edition=copy.deepcopy(reporting['edition'])","    Draft202012Validator(bounded_podcast_schema()).validate(narration['podcast'])\n    edition=copy.deepcopy(reporting['edition'])\n    edition['sources']=copy.deepcopy(catalog)")
s=s.replace("[('discovery',discovery),('reporting',reporting),('narration',narration)]","[('discovery',discovery),('sources',selected),('reporting',reporting),('narration',narration)]")
p.write_text(s)
p=Path('tests/test_release_staged_research.py');s=p.read_text()
s=s.replace('from test_release import fixture,DATE',"from test_release import fixture,DATE\nfrom release_narration import bounded_podcast_schema\n\ndef bounded_fixture():\n    e=fixture()\n    words={'opening':60,'bluf':165,'developments':310,'oklahoma':235,\n           'signals':170,'actions':160,'deadlines':80,'closing':55}\n    for k,n in words.items():\n        e['podcast'][k]=[' '.join(['Test']*n)]*3 if k=='developments' else ' '.join(['Test']*n)\n    return e")
s=s.replace("'sources':[{'url':'https://www.cms.gov/test-1'}]","'sources':[{'url':s['url']} for s in fixture()['sources']]")
s=s.replace("self.e=fixture();self.report=copy.deepcopy(self.e);self.report.pop('podcast')","self.e=bounded_fixture();self.report=copy.deepcopy(self.e);self.report.pop('podcast');self.report.pop('sources')")
s=s.replace("response('Verified public evidence notes.',web=True),response(self.report)","response('Verified public evidence notes.',web=True),response({'sources':self.e['sources']}),response(self.report)")
s=s.replace('test_three_stages_only_first_has_tools','test_four_stages_only_first_has_tools').replace('self.assertEqual(send.call_count,3)','self.assertEqual(send.call_count,4)')
s=s.replace("calls[1]['text']['format']['schema']['properties']","calls[2]['text']['format']['schema']['properties']")
s=s.replace("self.assertEqual(calls[2]['text']['format']['schema'],SCHEMA['properties']['podcast'])","self.assertEqual(calls[3]['text']['format']['schema'],bounded_podcast_schema())")
s=s.replace("response('notes',web=True),response('half output',status='incomplete')","response('notes',web=True),response({'sources':self.e['sources']}),response('half output',status='incomplete')")
s=s.replace("response('notes',web=True),response(self.report),response('half',status='incomplete')","response('notes',web=True),response({'sources':self.e['sources']}),response(self.report),response('half',status='incomplete')")
s=s.replace("bad.pop('sources')","bad.pop('title')").replace("response('notes',web=True),response(bad)","response('notes',web=True),response({'sources':self.e['sources']}),response(bad)")
s=s.replace('self.assertEqual(send.call_count,2)','self.assertEqual(send.call_count,3)')
p.write_text(s)
p=Path('tests/test_release_reporting_resume.py');s=p.read_text()
s=s.replace('from test_release_staged_research import response','from test_release_staged_research import response,bounded_fixture')
s=s.replace("response('Retained source notes',web=True),raw","response('Retained source notes',web=True),response({'sources':fixture()['sources']}),raw")
s=s.replace("e=fixture();brief=copy.deepcopy(e);brief.pop('podcast')","e=bounded_fixture();brief=copy.deepcopy(e);brief.pop('podcast');brief.pop('sources')")
p.write_text(s)
import shutil
shutil.copy2(Path(__file__).with_name('test_source_catalog.py'),'tests/test_release_source_catalog.py')
print('Prepared source and test changes. No API call or publication performed.')
