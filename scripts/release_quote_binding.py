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
