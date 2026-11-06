"""Canonical facts loader and injection (Task 3). Unverified facts stay out unless opted in."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_FACTS_CACHE: list["Fact"] | None = None


def current_academic_year(today: date | None = None) -> str:
    """Academic year boundary: 1 October."""
    d = today or date.today()
    if d.month >= 10:
        return f"{d.year}/{d.year + 1}"
    return f"{d.year - 1}/{d.year}"


def _year_key(y: str | None) -> tuple[int, int]:
    if not y or not re.match(r"^\d{4}/\d{4}$", str(y)):
        return (0, 0)
    a, b = str(y).split("/")
    return (int(a), int(b))


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


_TUITION_FACT_IDS = (
    "tuition_english_programmes",
    "tuition_polish_part_time_I",
)


def select_facts(
    facts: list[Fact],
    topics: list[str],
    profile: dict | None = None,
    include_unverified: bool | None = None,
    today: date | None = None,
    question: str | None = None,
) -> list[Fact]:
    """Prefer current academic year per fact id; else latest. Never mix two years of the same id."""
    if include_unverified is None:
        include_unverified = os.getenv("FACTS_INJECT_UNVERIFIED", "").strip() == "1"
    profile = profile or {}
    tset = set(topics or [])
    cur = current_academic_year(today)
    by_id: dict[str, list[Fact]] = {}
    for f in facts:
        if tset and f.topic and not (tset & set(f.topic)):
            continue
        if not _profile_matches(f, profile):
            continue
        # Special-act text names PESEL UKR. Unknown residence is not that status.
        if f.id == "ukr_special_act" and profile.get("pobyt") != "ukr":
            continue
        verified = f.status == "verified" and f.value is not None
        if verified or (include_unverified and f.value is not None):
            by_id.setdefault(f.id, []).append(f)
    selected = []
    for _fid, rows in by_id.items():
        exact = [r for r in rows if r.academic_year == cur]
        if exact:
            selected.append(exact[0])
            continue
        # no year / latest
        rows_sorted = sorted(rows, key=lambda r: _year_key(r.academic_year), reverse=True)
        selected.append(rows_sorted[0])
    # Facts-first tuition (P5): always attach matching tuition cards for oplaty
    if "oplaty" in tset:
        selected = _ensure_tuition_facts(selected, facts, profile, question or "", include_unverified)
    return selected


def _ensure_tuition_facts(
    selected: list[Fact],
    facts: list[Fact],
    profile: dict,
    question: str,
    include_unverified: bool,
) -> list[Fact]:
    have = {f.id for f in selected}
    q = question or ""
    want_en = bool(re.search(
        r"(?i)english|angielsk|mechanical\s*eng|international\s*business|IB\s*&?\s*F",
        q,
    )) or profile.get("status") == "cudzoziemiec"
    want_pl = bool(re.search(
        r"(?i)języku\s*polsk|polish[- ]language|niestacjonarn|zaoczn|part[-\s]?time|czesne",
        q,
    )) or profile.get("status") == "pl"
    for fid in _TUITION_FACT_IDS:
        if fid in have:
            continue
        if fid == "tuition_english_programmes" and not want_en:
            continue
        if fid == "tuition_polish_part_time_I" and not want_pl:
            continue
        cand = [f for f in facts if f.id == fid]
        for f in cand:
            verified = f.status == "verified" and f.value is not None
            if not (verified or (include_unverified and f.value is not None)):
                continue
            # Soft match: ignore poziom mismatch so II questions still get I-cycle table + note
            soft_prof = dict(profile)
            soft_prof.pop("poziom", None)
            if _profile_matches(f, soft_prof) or not f.applies_to:
                selected.append(f)
                have.add(fid)
                break
    return selected


def _parse_pl_num(s: str) -> float | None:
    d = _parse_pl_decimal(s)
    return float(d) if d is not None else None


def _parse_pl_decimal(s: str) -> Decimal | None:
    raw = (s or "").strip().replace(" ", "").replace("\u00a0", "")
    if not raw:
        return None
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _groups_table(groups: Any) -> list[dict]:
    """Normalize groups to list of {group, min, max, amount?} with Decimal bounds."""
    if not groups:
        return []
    if isinstance(groups, list):
        out = []
        for row in groups:
            if not isinstance(row, dict):
                continue
            try:
                lo = Decimal(str(row.get("min", 0)))
                hi = Decimal(str(row.get("max", 0)))
            except (InvalidOperation, ValueError):
                continue
            out.append({
                "group": str(row.get("group") or row.get("id") or ""),
                "min": lo,
                "max": hi,
                "amount": row.get("amount"),
            })
        return out
    if isinstance(groups, dict):
        # social_income_threshold shape: groups + amounts
        ranges = groups.get("groups") if "groups" in groups else groups
        amounts = groups.get("amounts") or {}
        out = []
        if isinstance(ranges, dict):
            for g, span in ranges.items():
                if not isinstance(span, str) or "-" not in span:
                    continue
                a, b = span.split("-", 1)
                lo, hi = _parse_pl_decimal(a), _parse_pl_decimal(b)
                if lo is None or hi is None:
                    continue
                out.append({"group": str(g), "min": lo, "max": hi, "amount": amounts.get(g)})
        return out
    return []


def income_group(income_per_person: float | Decimal | str, groups: Any) -> tuple[str | None, float | None]:
    """Deterministic income → (group, amount). Bounds inclusive; Decimal comparisons."""
    try:
        if isinstance(income_per_person, Decimal):
            income = income_per_person
        else:
            income = Decimal(str(income_per_person))
    except (InvalidOperation, ValueError, TypeError):
        return None, None
    table = _groups_table(groups)
    if not table:
        return None, None
    for row in sorted(table, key=lambda r: r["min"]):
        if row["min"] <= income <= row["max"]:
            amt = row.get("amount")
            if amt is None:
                return row["group"], None
            try:
                return row["group"], float(Decimal(str(amt)))
            except (InvalidOperation, ValueError):
                return row["group"], None
    return None, None


_INCOME_RE = re.compile(
    r"(?i)(-?\d[\d\s.,]*)\s*(?:zł|zl|pln)?\s*"
    r"(?:na\s*osob\w*|per\s*person|/os\b|на\s*особ\w*|на\s*человека|нэг\s*хүнд)",
)


def extract_income(text: str) -> float | None:
    """Parse income amount from free text. Preserves a leading minus (invalid for estimate)."""
    m = _INCOME_RE.search(text or "")
    if not m:
        # softer: "dochod ... 1500" / "income ... -10"
        m = re.search(
            r"(?i)(?:doch[oó]d|income|доход|дохід|орлого).{0,40}?"
            r"(-?\d[\d\s.,]*)\s*(?:zł|zl|pln)?",
            text or "",
        )
    if not m:
        return None
    return _parse_pl_num(m.group(1))


def computed_income_line(income: float, groups: Any, academic_year: str | None, lang: str = "pl") -> str | None:
    g, amt = income_group(income, groups)
    if not g:
        return None
    year = f" ({academic_year})" if academic_year else ""
    amt_s = f"{amt:,.0f}".replace(",", " ") if amt is not None else "?"
    labels = {
        "pl": f"Twoja grupa dochodowa: {g} → {amt_s} zł/mies.{year}",
        "en": f"Your income group: {g} → {amt_s} PLN/month{year}",
        "uk": f"Ваша група доходу: {g} → {amt_s} злотих/міс.{year}",
        "mn": f"Таны орлогын бүлэг: {g} → {amt_s} zł/сар{year}",
    }
    return labels.get(lang, labels["pl"])


def format_fact_value(val: Any, unit: str = "", lang: str = "pl", indent: str = "  ") -> str:
    """Human-readable fact value — never Python ``str(dict)`` / ``repr``."""
    u = f" {unit}" if unit else ""
    if isinstance(val, dict):
        note = val.get("note")
        items = [(k, v) for k, v in val.items() if k != "note"]
        if not items and note is not None:
            return f"({note})" if not isinstance(note, (dict, list)) else format_fact_value(note, unit, lang, indent)
        lines: list[str] = []
        for k, v in items:
            if isinstance(v, (dict, list)):
                lines.append(f"{indent}- {k}:")
                nested = format_fact_value(v, unit, lang, indent + "  ")
                for nl in nested.splitlines():
                    lines.append(nl if nl.startswith(indent) else f"{indent}  {nl}")
            else:
                lines.append(f"{indent}- {k}: {v}{u}")
        if note is not None and not isinstance(note, (dict, list)):
            lines.append(f"{indent}({note})")
        return "\n".join(lines) if lines else ""
    if isinstance(val, (list, tuple)):
        lines = []
        for item in val:
            if isinstance(item, (dict, list)):
                lines.append(f"{indent}-")
                nested = format_fact_value(item, unit, lang, indent + "  ")
                for nl in nested.splitlines():
                    lines.append(nl if nl.startswith(indent) else f"{indent}  {nl}")
            else:
                lines.append(f"{indent}- {item}{u}")
        return "\n".join(lines)
    return f"{val}{u}"


def _fact_entry_lines(f: Fact, i: int, lang: str, *, for_user: bool) -> list[str]:
    label = f.i18n_label.get(lang) or f.i18n_label.get("pl") or f.id
    unit = f.unit or ""
    year = f" ({f.academic_year})" if f.academic_year else ""
    unver = " (unverified)" if f.status != "verified" else ""
    src = ""
    if not for_user and f.source.get("url"):
        src = f" | source: {f.source['url']}"
    body = format_fact_value(f.value, unit=unit if not isinstance(f.value, (dict, list)) else "", lang=lang)
    if isinstance(f.value, (dict, list)):
        head_unit = f" {unit}" if unit else ""
        head = f"[F{i}] {label}{head_unit}{year}{unver}{src}:"
        return [head] + ([body] if body else [])
    return [f"[F{i}] {label}: {body}{year}{unver}{src}"]


def render_facts_block(facts: list[Fact], lang: str = "pl", computed_lines: list[str] | None = None) -> str:
    """Machine header for the LLM prompt only."""
    if not facts and not computed_lines:
        return ""
    lines = ["FACTS (authoritative — quote exactly, cite as [F1], [F2], …):"]
    for i, f in enumerate(facts, 1):
        lines.extend(_fact_entry_lines(f, i, lang, for_user=False))
    for j, line in enumerate(computed_lines or [], 1):
        lines.append(f"[F{len(facts) + j}] COMPUTED: {line}")
    return "\n".join(lines)


def render_facts_for_user(facts: list[Fact], lang: str = "pl", computed_lines: list[str] | None = None) -> str:
    """User-visible facts block — no 'authoritative / quote exactly' header."""
    if not facts and not computed_lines:
        return ""
    lines: list[str] = []
    for i, f in enumerate(facts, 1):
        lines.extend(_fact_entry_lines(f, i, lang, for_user=True))
    for j, line in enumerate(computed_lines or [], 1):
        lines.append(f"[F{len(facts) + j}] {line}")
    return "\n".join(lines)


# EN thousands (3,667 / 1,000.50), EU thousands (3.667 / 3 667,50), plain decimals, 3–5 digit ints
_AMOUNT_RE = re.compile(
    r"(?<![\d.,])("
    r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"
    r"|\d{1,3}(?:[ .\u00a0]\d{3})+(?:,\d{1,2})?"
    r"|\d+[.,]\d{2}"
    r"|\d{3,5}"
    r")\s*(?:zł|zl|PLN|EUR|euro|€)",
    re.I,
)


def parse_amount_token(raw: str) -> Decimal | None:
    """Parse a numeric amount token; EN commas are thousands, PL ``,dd`` is decimal."""
    s = (raw or "").replace("\u00a0", "").replace(" ", "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d{1,2})?", s):
        s = s.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", s):
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        left, _, right = s.partition(",")
        if len(right) == 3 and left.isdigit() and len(left) <= 3 and right.isdigit():
            s = left + right  # EN thousands fallback e.g. 3,667
        else:
            s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def amounts_in(text: str) -> set[Decimal]:
    out: set[Decimal] = set()
    if not text:
        return out
    for m in _AMOUNT_RE.finditer(text):
        val = parse_amount_token(m.group(1))
        if val is not None:
            out.add(val)
    return out


def _collect_nums(obj, out: set[Decimal], depth: int = 0):
    if depth > 4 or obj is None:
        return
    if isinstance(obj, (int, float, Decimal)) and not isinstance(obj, bool):
        out.add(Decimal(str(obj)))
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_nums(v, out, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_nums(v, out, depth + 1)
    elif isinstance(obj, str):
        out |= amounts_in(obj + " zł")


def fact_amounts(facts: list[Fact]) -> set[Decimal]:
    out: set[Decimal] = set()
    for f in facts:
        _collect_nums(f.value, out)
    return out


def strip_unknown_amounts(text: str, allowed: set[Decimal]) -> tuple[str, bool]:
    """Silently remove currency amounts not in ``allowed``. Never leaves a dangling ``3,`` / ``1,``."""
    if not text or not allowed:
        return text or "", False
    unknown = amounts_in(text) - allowed
    if not unknown:
        return text, False

    def _repl(m: re.Match) -> str:
        raw = m.group(0)
        # Refuse partial strip: digit/comma immediately before the match belongs to a larger token
        start = m.start()
        if start > 0 and text[start - 1] in "0123456789.,":
            return raw
        got = amounts_in(raw)
        if got and got <= unknown:
            return ""
        return raw

    cleaned = _AMOUNT_RE.sub(_repl, text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).rstrip()
    # Collapse artefacts like "3,/month" if a bad match somehow slipped through
    cleaned = re.sub(r"(?<!\d)\d{1,3},(?=\s*/|\s*$)", "", cleaned)
    return cleaned, cleaned != text
