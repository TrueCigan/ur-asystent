"""Canonical facts loader and injection (Task 3). Unverified facts stay out unless opted in."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_FACTS_CACHE: list["Fact"] | None = None


@dataclass
class Fact:
    id: str
    topic: list[str]
    value: Any
    unit: str | None
    academic_year: str | None
    applies_to: dict
    source: dict
    status: str
    i18n_label: dict
    deadline: dict | None = None
    candidates_seen: list = field(default_factory=list)


def _facts_path(path: str | None = None) -> str:
    if path:
        return path
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "data", "facts.yaml")


def load_facts(path: str | None = None) -> list[Fact]:
    global _FACTS_CACHE
    if _FACTS_CACHE is not None and path is None:
        return _FACTS_CACHE
    if yaml is None:
        return []
    p = _facts_path(path)
    if not os.path.isfile(p):
        return []
    raw = yaml.safe_load(open(p, encoding="utf-8")) or []
    out = []
    for row in raw:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        out.append(Fact(
            id=row["id"],
            topic=list(row.get("topic") or []),
            value=row.get("value"),
            unit=row.get("unit"),
            academic_year=row.get("academic_year"),
            applies_to=dict(row.get("applies_to") or {}),
            source=dict(row.get("source") or {}),
            status=str(row.get("status") or "TODO(verify)"),
            i18n_label=dict(row.get("i18n_label") or {}),
            deadline=row.get("deadline"),
            candidates_seen=list(row.get("candidates_seen") or []),
        ))
    if path is None:
        _FACTS_CACHE = out
    return out


def _profile_matches(fact: Fact, profile: dict) -> bool:
    rules = fact.applies_to or {}
    if not rules:
        return True
    for slot, allowed in rules.items():
        if not isinstance(allowed, list):
            continue
        got = profile.get(slot)
        if got is None:
            continue
        if got not in allowed:
            return False
    return True


def select_facts(
    facts: list[Fact],
    topics: list[str],
    profile: dict | None = None,
    include_unverified: bool | None = None,
) -> list[Fact]:
    if include_unverified is None:
        include_unverified = os.getenv("FACTS_INJECT_UNVERIFIED", "").strip() == "1"
    profile = profile or {}
    tset = set(topics or [])
    selected = []
    for f in facts:
        if tset and f.topic and not (tset & set(f.topic)):
            continue
        if not _profile_matches(f, profile):
            continue
        verified = f.status == "verified" and f.value is not None
        if verified or (include_unverified and f.value is not None):
            selected.append(f)
    return selected


def render_facts_block(facts: list[Fact], lang: str = "pl") -> str:
    if not facts:
        return ""
    lines = ["FACTS (authoritative — quote exactly, cite as [F1], [F2], …):"]
    for i, f in enumerate(facts, 1):
        label = f.i18n_label.get(lang) or f.i18n_label.get("pl") or f.id
        val = f.value
        unit = f" {f.unit}" if f.unit else ""
        year = f" ({f.academic_year})" if f.academic_year else ""
        src = ""
        if f.source.get("url"):
            src = f" | source: {f.source['url']}"
        if f.status != "verified":
            lines.append(f"[F{i}] {label}: {val}{unit}{year} (unverified){src}")
        else:
            lines.append(f"[F{i}] {label}: {val}{unit}{year}{src}")
    return "\n".join(lines)


_AMOUNT_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[ .]\d{3})*(?:[.,]\d{1,2})?|\d+[.,]\d{2}|\d{3,5})\s*(?:zł|zl|PLN|EUR|euro|€)",
    re.I,
)


def amounts_in(text: str) -> set[Decimal]:
    out: set[Decimal] = set()
    if not text:
        return out
    for m in _AMOUNT_RE.finditer(text):
        raw = m.group(1).replace(" ", "").replace("\u00a0", "")
        if "," in raw and "." in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            raw = raw.replace(",", ".")
        try:
            out.add(Decimal(raw))
        except InvalidOperation:
            continue
    return out


def fact_amounts(facts: list[Fact]) -> set[Decimal]:
    out: set[Decimal] = set()
    for f in facts:
        if f.value is None:
            continue
        if isinstance(f.value, (int, float, Decimal)):
            out.add(Decimal(str(f.value)))
        elif isinstance(f.value, dict):
            for v in f.value.values():
                if isinstance(v, (int, float, Decimal)):
                    out.add(Decimal(str(v)))
        elif isinstance(f.value, str):
            out |= amounts_in(f.value + " zł")
    return out
