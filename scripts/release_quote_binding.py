"""Bind reviewer quotations without changing candidate claims or audit findings.

Only exact quotations, first-letter sentence capitalization, and an exact labeled
ISO date literal are accepted. No fuzzy match, paraphrase, ellipsis, unit/date
normalization, or dropped finding is permitted.
"""
from __future__ import annotations
import re


def quote_binding(quote: str, field: str, path: str) -> str | None:
    if not isinstance(quote, str) or not isinstance(field, str) or not quote.strip():
        return None
    if quote in field:
        return 'exact'
    # A reviewer may capitalize the beginning of an excerpt taken after a
    # semicolon. Preserve every subsequent character, including case and units.
    if (len(quote) > 1 and 'A' <= quote[0] <= 'Z'
            and quote[0].lower() + quote[1:] in field):
        return 'initial_sentence_capitalization'
    # A model sometimes quotes the field label with a scalar date. Bind only the
    # exact field name and full value, never a date inferred from another field.
    if (re.fullmatch(r'/actions/[0-9]+/due_date', path)
            and re.fullmatch(r'\d{4}-\d{2}-\d{2}', field)
            and quote in ('due_date: "' + field + '"', "due_date: '" + field + "'")):
        return 'exact_labeled_date'
    return None


def finding_binding(finding: dict, fields: dict[str, str]) -> str | None:
    """Locate a long exact advisory quotation without editing the saved review.

    A blocking finding is never relocated. An advisory with a required change,
    short/ambiguous quotation, paraphrase, or unknown original path still fails.
    Only one exact occurrence among the caller's allowed prose fields can bind.
    """
    path, quote = finding.get('path'), finding.get('quote')
    if path not in fields or not isinstance(quote, str):
        return None
    if quote_binding(quote, fields[path], path) is not None:
        return path
    if (finding.get('kind') != 'advisory' or finding.get('required_change') != ''
            or len(quote) < 40 or len(quote.split()) < 6):
        return None
    matches = [p for p, text in fields.items() if quote in text]
    if len(matches) != 1 or fields[matches[0]].count(quote) != 1:
        return None
    return matches[0]
