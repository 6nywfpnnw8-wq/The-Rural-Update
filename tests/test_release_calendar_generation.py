"""The production reporting schema cannot propose yesterday's date."""
import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from jsonschema import Draft202012Validator, ValidationError
from test_release import fixture, DATE
from release_research import reporting_schema
from release_core import SCHEMA

class CalendarGenerationTests(unittest.TestCase):
    def report(self):
        e=fixture();e.pop('podcast');return e
    def test_bounds_include_today_and_thirtieth_day(self):
        schema=reporting_schema(expected=DATE)
        values=schema['properties']['deadlines']['items']['properties']['date']['enum']
        self.assertEqual((values[0],values[-1],len(values)),(DATE,'2026-11-10',31))
    def test_past_deadline_rejected_in_generation(self):
        e=self.report();e['deadlines'][0]['date']='2026-10-10'
        with self.assertRaises(ValidationError):Draft202012Validator(reporting_schema(expected=DATE)).validate(e)
    def test_past_action_rejected_in_generation(self):
        e=self.report();e['actions'][0]['due_date']='2026-10-10'
        with self.assertRaises(ValidationError):Draft202012Validator(reporting_schema(expected=DATE)).validate(e)
    def test_no_replacement_event_or_due_date_is_required(self):
        e=self.report();e['deadlines']=[];e['actions'][0]['due_date']=None
        Draft202012Validator(reporting_schema(expected=DATE)).validate(e)
    def test_invalid_date_rejected(self):
        with self.assertRaises(ValueError):reporting_schema(expected='2026-02-30')
    def test_schema_builder_does_not_change_release_validator(self):
        original=copy.deepcopy(SCHEMA);reporting_schema(expected=DATE)
        self.assertEqual(SCHEMA,original)
    def test_fixed_source_catalog_is_preserved(self):
        catalog=fixture()['sources'];schema=reporting_schema(catalog,DATE)
        self.assertNotIn('sources',schema['properties'])
        self.assertEqual(schema['properties']['actions']['items']['properties']['source_ids']['items']['enum'],[s['id'] for s in catalog])

if __name__=='__main__':unittest.main()
