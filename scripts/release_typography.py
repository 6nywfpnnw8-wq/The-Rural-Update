"""Deterministic prose typography. Never changes URLs, IDs, facts, or approval."""
from __future__ import annotations
import copy
import re

# Structured values are deliberately outside this allowlist. Source titles are
# display prose, but the source URL and provenance identity are never rewritten.
PROSE_FIELDS = frozenset({
    'title', 'bluf', 'what_changed', 'why_it_matters', 'executive_question',
    'category', 'next_step', 'suggested_function', 'direction', 'horizon',
    'executiveRisk', 'summary', 'why', 'risk', 'nextMilestone', 'history_note',
    'description', 'relevance',
})
BREAK = re.compile(r'[ \t]*\u2014[ \t]*')


def normalize_edition_typography(edition: dict) -> tuple[dict, list[dict]]:
    """Return a copy with prose em dashes converted to spaced ASCII hyphens.

    No model request, omitted text, padding, truncation, or approval is involved.
    Reports contain field paths/counts, never draft paragraphs. The existing
    schema, word-count, content, provenance, and evidence checks still run next.
    """
    result = copy.deepcopy(edition)
    changes = []

    def walk(value, path, prose=False, podcast=False):
        if isinstance(value, dict):
            return {key: walk(item, path + '/' + key,
                              podcast or key in PROSE_FIELDS,
                              podcast or (path == '' and key == 'podcast'))
                    for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item, path + '/' + str(n), prose, podcast)
                    for n, item in enumerate(value)]
        if isinstance(value, str) and (prose or podcast):
            count = value.count('\u2014')
            if count:
                changes.append({'path': path, 'replacements': count})
                return BREAK.sub(' - ', value)
        return value

    return walk(result, ''), changes


def normalize_source_identifiers(edition: dict) -> tuple[dict, list[dict]]:
    """Canonicalize opaque source labels with one-to-one reference preservation.

    This does not add, remove, merge, or edit sources. Unknown references and
    colliding identifiers are rejected instead of silently attached to a source.
    """
    import hashlib
    result = copy.deepcopy(edition)
    sources = result.get('sources')
    if not isinstance(sources, list):
        raise ValueError('Source list is malformed')
    ids = [s.get('id') if isinstance(s, dict) else None for s in sources]
    if not all(isinstance(v, str) and v for v in ids) or len(ids) != len(set(ids)):
        raise ValueError('Source identifiers are missing or duplicated')
    mapping = {}
    for identifier in ids:
        if re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', identifier):
            normalized = identifier
        else:
            normalized = re.sub(r'[^a-z0-9]+', '-', identifier.lower()).strip('-')
            if not normalized:
                raise ValueError('Source identifier has no safe canonical form')
            if len(normalized) > 80:
                suffix = hashlib.sha256(identifier.encode()).hexdigest()[:12]
                normalized = normalized[:65].rstrip('-') + '-' + suffix
        mapping[identifier] = normalized
    if len(set(mapping.values())) != len(mapping):
        raise ValueError('Canonical source identifiers would collide')
    changes = []

    def references(value, path=''):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'source_ids':
                    if not isinstance(child, list) or not all(isinstance(v, str) and v in mapping for v in child):
                        raise ValueError('Source reference was unresolved before normalization')
                    value[key] = [mapping[v] for v in child]
                    count = sum(a != b for a, b in zip(child, value[key]))
                    if count: changes.append({'path': path + '/source_ids', 'replacements': count})
                else:
                    references(child, path + '/' + key)
        elif isinstance(value, list):
            for n, child in enumerate(value): references(child, path + '/' + str(n))

    references(result)
    for n, source in enumerate(sources):
        original = source['id']; source['id'] = mapping[original]
        if original != source['id']:
            changes.append({'path': f'/sources/{n}/id', 'replacements': 1})
    return result, changes
