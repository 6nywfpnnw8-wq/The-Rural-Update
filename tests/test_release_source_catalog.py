"""Fixed references prevent invented source labels; evidence audit still required."""
import copy,json,sys,unittest
from pathlib import Path
from jsonschema import Draft202012Validator,ValidationError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_research as sr
from release_core import SCHEMA
from release_narration import bounded_podcast_schema
from test_release_staged_research import response,bounded_fixture

class SourceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.e=bounded_fixture();self.sources=self.e['sources'];self.urls=[s['url'] for s in self.sources]
        self.report=copy.deepcopy(self.e);self.report.pop('podcast');self.report.pop('sources')
    def test_unknown_reference_is_schema_rejected(self):
        self.report['signals'][0]['source_ids'][0]='made-up-reference'
        with self.assertRaises(ValidationError):Draft202012Validator(sr.reporting_schema(self.sources)).validate(self.report)
    def test_source_array_cannot_be_rewritten_by_reporting(self):
        self.report['sources']=self.sources
        with self.assertRaises(ValidationError):Draft202012Validator(sr.reporting_schema(self.sources)).validate(self.report)
    def test_only_observed_urls_can_enter_catalog(self):
        bad=copy.deepcopy(self.sources);bad[0]['url']='https://www.cms.gov/invented-url'
        with self.assertRaises(ValidationError):sr.validate_source_catalog(bad,self.urls)
    def test_duplicate_ids_not_merged(self):
        bad=copy.deepcopy(self.sources);bad[0]['id']=bad[1]['id']
        with self.assertRaises(ValueError):sr.validate_source_catalog(bad,self.urls)
    def test_duplicate_urls_not_counted_as_two_references(self):
        bad=copy.deepcopy(self.sources);bad[0]['url']=bad[1]['url']
        with self.assertRaises(ValueError):sr.validate_source_catalog(bad,self.urls)
    def test_duplicate_references_rejected_locally(self):
        self.report['signals'][0]['source_ids']=[self.sources[0]['id']]*2
        with self.assertRaises(ValueError):sr.validate_reference_bindings(self.report,self.sources)
    def test_catalog_schema_does_not_mutate_release_schema(self):
        original=json.dumps(SCHEMA,sort_keys=True)
        sr.reporting_schema(self.sources);sr.source_catalog_schema(self.urls)
        self.assertEqual(original,json.dumps(SCHEMA,sort_keys=True))
    def test_stub_section_rejected_even_when_total_qualifies(self):
        podcast=copy.deepcopy(self.e['podcast']);podcast['developments'][1]='developments-1'
        podcast['oklahoma']+=' '+('Word '*400)
        with self.assertRaises(ValidationError):Draft202012Validator(bounded_podcast_schema()).validate(podcast)
    def test_generated_prose_cannot_claim_retrieval(self):
        with self.assertRaises(ValueError):sr.observed_html_urls({'notes':' '.join(self.urls),'web_search_items':[]})
    def test_pdf_urls_not_offered_to_html_collector(self):
        discovery={'web_search_items':response('notes',web=True)['output'][:1]}
        discovery['web_search_items'][0]['action']['sources'].append({'url':'https://www.cms.gov/a.pdf'})
        self.assertNotIn('https://www.cms.gov/a.pdf',sr.observed_html_urls(discovery))

if __name__=='__main__':unittest.main()
