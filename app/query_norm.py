"""Search-copy normalization for the FAQ path.

The original string is kept. The search copy is NFKC, trimmed, lowercased,
with typographic hyphens folded and spaces collapsed. Diacritics, digits,
dates, and negation words stay.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_HYPHENS = str.maketrans({
    "\u00ad": "",
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
})
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class NormalizedQuery:
    original: str
    search: str


def normalize_query(text: str) -> NormalizedQuery:
    original = text or ""
    search = unicodedata.normalize("NFKC", original)
    search = search.translate(_HYPHENS)
    search = _SPACES.sub(" ", search).strip().lower()
    return NormalizedQuery(original=original, search=search)
