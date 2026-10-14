"""Read-only citation relationship diagnostics. No source text or URLs in reports."""
from __future__ import annotations
import re

GROUPS = ('stories', 'actions', 'deadlines', 'signals', 'issue_updates')
MESSAGES = frozenset({
    'Source list is malformed', 'Source identifiers are missing or duplicated',
    'Source identifier has no safe canonical form',
    'Canonical source identifiers would collide',
    'Source reference was unresolved before normalization',
})


def inspect_source_labels(candidate: dict) -> dict:
    sources = candidate.get('sources', [])
    if not isinstance(sources, list):
        return {'source_list_valid': False}
    labels = [s.get('id') for s in sources if isinstance(s, dict)]
    strings = [s for s in labels if isinstance(s, str) and s]
    exact = set(strings)
    canonical = lambda s: re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')
    unresolved = []
    references = 0
    for group in GROUPS:
        items = candidate.get(group, [])
        if not isinstance(items, list):
            continue
        for i, item in enumerate(items):
            ids = item.get('source_ids', []) if isinstance(item, dict) else []
            if not isinstance(ids, list):
                continue
            for n, identifier in enumerate(ids):
                references += 1
                if isinstance(identifier, str) and identifier in exact:
                    continue
                if len(unresolved) < 30:
                    unresolved.append({
                        'path': f'/{group}/{i}/source_ids/{n}',
                        'is_string': isinstance(identifier, str),
                        'casefold_matches': sum(identifier.casefold() == s.casefold() for s in exact)
                            if isinstance(identifier, str) else 0,
                        'canonical_matches': sum(canonical(identifier) == canonical(s) for s in exact)
                            if isinstance(identifier, str) and canonical(identifier) else 0,
                    })
    return {
        'source_count': len(sources), 'source_label_count': len(strings),
        'duplicate_label_count': len(strings) - len(exact),
        'invalid_syntax_count': sum(not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', s) for s in strings),
        'no_canonical_form_count': sum(not canonical(s) for s in strings),
        'canonical_collision_count': len(exact) - len({canonical(s) for s in exact}),
        'reference_count': references, 'unresolved_references': unresolved,
        'publication_authorized': False,
    }
