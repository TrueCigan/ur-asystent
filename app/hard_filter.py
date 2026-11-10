"""Hard filters run before a result limit.

A missing year, faculty, program, validity bound, or revision does not match
an explicit constraint. It is not treated as “applies to everyone”.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FilterDecision:
    status: str
    rows: list
    reason: str | None = None


def _field(row, name):
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def apply_hard_filters(rows, constraints: dict | None) -> list:
    constraints = constraints or {}
    year = constraints.get("academic_year")
    faculty = constraints.get("faculty_id")
    program = constraints.get("program_id")
    as_of = constraints.get("as_of")
    revision = constraints.get("active_revision")
    kept = []
    for row in rows or []:
        if _field(row, "active") is False:
            continue
        if revision is not None and _field(row, "revision") != revision:
            continue
        if year is not None and _field(row, "academic_year") != year:
            continue
        if faculty is not None and _field(row, "faculty_id") != faculty:
            continue
        if program is not None and _field(row, "program_id") != program:
            continue
        if as_of is not None:
            start = _field(row, "valid_from")
            end = _field(row, "valid_to")
            if not start or not end or not (str(start) <= str(as_of) <= str(end)):
                continue
        kept.append(row)
    return kept


def limit_after_filters(rows, limit: int, constraints: dict | None) -> FilterDecision:
    """Reject an unknown explicit id before any row is returned."""
    constraints = constraints or {}
    if constraints.get("unknown_id"):
        return FilterDecision(status="clarify", rows=[], reason="unknown_id")
    filtered = apply_hard_filters(rows, constraints)
    return FilterDecision(status="ok", rows=filtered[: max(0, int(limit))])
