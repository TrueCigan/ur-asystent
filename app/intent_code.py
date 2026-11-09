"""Closed-vocabulary intent. Patterns live in code, not in loaded data."""
from __future__ import annotations

import re
from dataclasses import dataclass

from query_norm import normalize_query

# Literal terms only. This is not a regex loaded from YAML.
TOPIC_TERMS = {
    "submission_channel": ("wniosek", "application", "заяв"),
    "akademik": ("akademik", "dorm", "гуртож"),
    "stypendium_socjalne": ("socjaln", "social scholarship", "соціальн"),
    "stypendium_rektora": ("rektora", "rector", "ректора"),
    "doktoranckie": ("doktoranc", "doctoral stipend", "докторськ"),
    "erasmus": ("erasmus", "еразм"),
}

_YEAR = re.compile(r"\b(20\d{2})\s*[/\-]\s*(20\d{2})\b")
_ID_FIELD = re.compile(
    r"\b(?:faculty_id|program_id|wydzial_id|kierunek_id)\s*[:=]\s*([a-z0-9_-]+)"
)
_NEGATION = {"nie", "not", "without", "bez", "не", "ні"}
_COMPOUND = (" i czy ", " oraz czy ", " and whether ", " and what ", " та чи ")
_RELATIVE_DEADLINE = (
    "wczoraj",
    "yesterday",
    "вчора",
    "zeszłym tygodniu",
    "last week",
    "минулого тижня",
)


@dataclass(frozen=True)
class Intent:
    topics: tuple[str, ...]
    academic_year: str | None
    faculty_id: str | None
    program_id: str | None
    unknown_id: bool
    negated: bool
    compound: bool
    relative_deadline: bool


def known_ids(kind: str, table: dict | None = None) -> set[str]:
    """Official faculty/program ids. The approved catalogue is empty."""
    if table is None:
        table = load_canonical_ids()
    return {str(item) for item in (table.get(kind) or [])}


def load_canonical_ids() -> dict:
    from pathlib import Path
    import yaml

    path = Path(__file__).resolve().parents[1] / "data" / "canonical_ids.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {"faculties": list(raw.get("faculties") or []), "programs": list(raw.get("programs") or [])}


def parse_intent(text: str, ids: dict | None = None) -> Intent:
    norm = normalize_query(text).search
    topics = tuple(
        topic for topic, terms in TOPIC_TERMS.items()
        if any(term in norm for term in terms)
    )
    year = None
    match = _YEAR.search(norm)
    if match:
        year = f"{match.group(1)}/{match.group(2)}"
    table = ids if ids is not None else load_canonical_ids()
    faculty_id = None
    program_id = None
    unknown = False
    for found in _ID_FIELD.finditer(norm):
        value = found.group(1)
        field = found.group(0)
        if field.startswith("program") or field.startswith("kierunek"):
            program_id = value
            if value not in known_ids("programs", table):
                unknown = True
        else:
            faculty_id = value
            if value not in known_ids("faculties", table):
                unknown = True
    tokens = set(norm.split())
    return Intent(
        topics=topics,
        academic_year=year,
        faculty_id=faculty_id,
        program_id=program_id,
        unknown_id=unknown,
        negated=bool(tokens & _NEGATION),
        compound=(norm.count("?") > 1) or any(marker in f" {norm} " for marker in _COMPOUND),
        relative_deadline=any(phrase in norm for phrase in _RELATIVE_DEADLINE),
    )
