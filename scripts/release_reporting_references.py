"""Generate citation sets as fixed keys; preserve the publication array schema."""
from __future__ import annotations
import copy
import json
from jsonschema import Draft202012Validator
from release_core import digest
from release_diagnostics import error_details

METHOD = 'fixed-reporting-references-v1'


def generation_schema(schema, catalog):
    result = copy.deepcopy(schema)
    ids = [s['id'] for s in catalog]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Source catalog has no unique identifiers')

    def walk(node):
        for key, value in node.get('properties', {}).items():
            if key == 'source_ids':
                node['properties'][key] = {
                    'type': 'object', 'properties': {identifier: {'type': 'boolean'} for identifier in ids},
                    'required': ids, 'additionalProperties': False,
                }
            else:walk(value)
        if isinstance(node.get('items'), dict):walk(node['items'])
    walk(result)
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:raise ValueError('Duplicate reporting response field')
        result[key] = value
    return result


def _compile_references(value, catalog):
    value = copy.deepcopy(value)
    ids = [s['id'] for s in catalog]

    def walk(node):
        if isinstance(node, dict):
            for key, item in node.items():
                if key == 'source_ids':node[key] = [identifier for identifier in ids if item[identifier]]
                else:walk(item)
        elif isinstance(node, list):
            for item in node:walk(item)
    walk(value)
    return value


def compile_report(text, schema, catalog):
    value = json.loads(text, object_pairs_hook=_unique_object)
    Draft202012Validator(generation_schema(schema, catalog)).validate(value)
    value = _compile_references(value, catalog)
    # In particular, signals must still have two to four DISTINCT sources.
    # Fixed keys prevent duplicates; they do not satisfy a minimum by themselves.
    Draft202012Validator(schema).validate(value)
    return value


def replay_report(text, schema, catalog):
    """List every structural rejection in retained output without changing it."""
    result = {'method': METHOD, 'response_text_sha256': digest(text),
              'api_calls_made': 0, 'publication_authorized': False, 'findings': []}
    try:value = json.loads(text, object_pairs_hook=_unique_object)
    except (ValueError, TypeError) as error:
        result['findings'].append(error_details(error));return result
    errors = list(Draft202012Validator(generation_schema(schema, catalog)).iter_errors(value))
    result['generation_schema_passed'] = not errors
    if not errors:
        value = _compile_references(value, catalog)
        errors = list(Draft202012Validator(schema).iter_errors(value))
    for error in errors[:30]:
        finding = error_details(error)
        if error.validator in {'minItems', 'maxItems'}:
            finding['actual_items'] = len(error.instance)
            finding['required_' + ('minimum' if error.validator == 'minItems' else 'maximum')] = error.validator_value
        result['findings'].append(finding)
    result['publication_schema_passed'] = not errors
    return result
