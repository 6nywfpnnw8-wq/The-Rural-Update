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
