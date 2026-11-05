"""URL normalisation: undo double-encoding (%25…) then re-quote safely."""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit, quote, unquote


def normalize_url(u: str) -> str:
    if not u:
        return u
    raw = u.strip()
    # Loop unquote while %25 remains (double-encoded)
    prev = None
    while prev != raw and "%25" in raw:
        prev = raw
        raw = unquote(raw)
    # Also unquote once more if still percent-encoded path
    if "%" in raw:
        raw = unquote(raw)
    parts = urlsplit(raw)
    path = quote(parts.path, safe="/%:@")
    # Keep query/fragment lightly quoted
    query = quote(unquote(parts.query), safe="=&%")
    frag = quote(unquote(parts.fragment), safe="")
    return urlunsplit((parts.scheme, parts.netloc, path, query, frag))
