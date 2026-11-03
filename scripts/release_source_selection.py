"""Choose from fixed observed sources without model-generated IDs or URLs.

Null excludes a source; metadata selects it. Object keys bind each choice to one
canonical observed URL. This is unapproved working material, not evidence review.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from release_core import allowed_url, canonical_url, digest
from release_diagnostics import MAX_SNAPSHOT_BYTES, redact, write_json

METHOD = 'fixed-source-selection-v1'
SLOT_METHOD = 'bounded-source-selection-v2'
MAX_CHOICES = 128
MIN_SELECTED = 5
MAX_SELECTED = 12


def source_choices(urls: list[str]) -> dict[str, str]:
    # Collapse only the aliases already recognized by the publication validator.
    # The representative remains an exact URL observed in real tool events.
    by_url = {}
    for url in sorted(set(urls)):
        if not allowed_url(url):
            raise ValueError('Source selection contains an unapproved URL')
        by_url.setdefault(canonical_url(url), url)
    if len(by_url) < 5:
        raise ValueError('Fewer than five distinct observed source URLs')
    if len(by_url) > MAX_CHOICES:
        raise ValueError('Source selection catalog exceeds safe size')
    choices = {'src-' + digest(url)[:16]: exact for url, exact in sorted(by_url.items())}
    if len(choices) != len(by_url):
        raise ValueError('Source selection identifier collision')
    return choices


def selection_schema(urls: list[str]) -> dict:
    metadata = {
        'type': ['object', 'null'],
        'properties': {
            'title': {'type': 'string', 'minLength': 1, 'maxLength': 220},
            'published_date': {'type': ['string', 'null'], 'pattern': r'^\d{4}-\d{2}-\d{2}$'},
        },
        'required': ['title', 'published_date'], 'additionalProperties': False,
    }
    keys = list(source_choices(urls))
    return {'type': 'object', 'properties': {'sources': {
        'type': 'object', 'properties': {key: metadata for key in keys},
        'required': keys, 'additionalProperties': False,
    }}, 'required': ['sources'], 'additionalProperties': False}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate source selection field')
        result[key] = value
    return result


def retain_selection(text: str, cache: Path, identity: str, *, method=METHOD) -> dict:
    return retain_stage_output(text, cache, identity, 'sources', method=method)


def retain_stage_output(text: str, cache: Path, identity: str, stage: str, *, method=None) -> dict:
    """Retain visible completion only, excluding raw API envelopes and reasoning.

    Keep rejected output as well as passing output so an error can be replayed.
    Redacted snapshots cannot later serve as original recovery material.
    """
    if stage not in {'sources', 'reporting_plan', 'reporting', 'narration'}:
        raise ValueError('Invalid retained response stage')
    raw = text.encode('utf-8')
    fingerprint = digest(raw)
    if len(raw) > MAX_SNAPSHOT_BYTES:
        return {'retained': False, 'reason': 'size_limit', 'sha256': fingerprint}
    cleaned = redact(text)
    relative = 'stage-responses/' + stage + '-' + fingerprint[:16] + '.json'
    write_json(Path(cache) / relative, {
        'schema_version': 1, 'method': method or (METHOD if stage == 'sources' else 'staged-visible-output-v1'), 'identity': identity,
        'stage': stage, 'publication_authorized': False,
        'sha256': fingerprint, 'redacted': cleaned != text, 'output_text': cleaned,
    })
    return {'retained': True, 'file': relative, 'redacted': cleaned != text,
            'sha256': fingerprint}


def compile_selection(text: str, urls: list[str]) -> list[dict]:
    value = json.loads(text, object_pairs_hook=_unique_object)
    Draft202012Validator(selection_schema(urls)).validate(value)
    return [dict(id=key, url=url, **value['sources'][key])
            for key, url in source_choices(urls).items() if value['sources'][key] is not None]


def bounded_selection_schema(urls: list[str]) -> dict:
    """Five required choices and seven optional choices make overflow impossible.

    IDs remain publisher-supplied enums and URLs never come from the model.
    Duplicate IDs still fail local validation; no entry is silently discarded.
    Historical map completions remain replayable through compile_selection.
    """
    item = {'type': 'object', 'properties': {
        'id': {'type': 'string', 'enum': list(source_choices(urls))},
        'title': {'type': 'string', 'minLength': 1, 'maxLength': 220},
        'published_date': {'type': ['string', 'null'], 'pattern': r'^\d{4}-\d{2}-\d{2}$'},
    }, 'required': ['id', 'title', 'published_date'], 'additionalProperties': False}
    properties = {}
    for index in range(MAX_SELECTED):
        properties['source_' + str(index + 1)] = {
            **item, 'type': 'object' if index < MIN_SELECTED else ['object', 'null']}
    return {'type': 'object', 'properties': {'sources': {
        'type': 'object', 'properties': properties,
        'required': list(properties), 'additionalProperties': False,
    }}, 'required': ['sources'], 'additionalProperties': False}


def compile_bounded_selection(text: str, urls: list[str]) -> list[dict]:
    value = json.loads(text, object_pairs_hook=_unique_object)
    Draft202012Validator(bounded_selection_schema(urls)).validate(value)
    choices = source_choices(urls)
    rows = [dict(item, url=choices[item['id']])
            for item in value['sources'].values() if item is not None]
    if len({s['id'] for s in rows}) != len(rows):
        raise ValueError('Duplicate source catalog identifier')
    return sorted(rows, key=lambda s: list(choices).index(s['id']))
