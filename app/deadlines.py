"""Single owner for deadline-passed warnings (Task 2)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_MONTH_NUM = {
    "jan": 1, "january": 1, "sty": 1, "stycznia": 1, "styczeń": 1, "січ": 1, "січня": 1,
    "feb": 2, "february": 2, "lut": 2, "lutego": 2, "лют": 2, "лютого": 2,
    "mar": 3, "march": 3, "marca": 3, "берез": 3, "березня": 3,
    "apr": 4, "april": 4, "kwi": 4, "kwietnia": 4, "квіт": 4, "квітня": 4,
    "may": 5, "maja": 5, "май": 5, "трав": 5, "травня": 5,
    "jun": 6, "june": 6, "cze": 6, "czerwca": 6, "черв": 6, "червня": 6,
    "jul": 7, "july": 7, "lip": 7, "lipca": 7, "лип": 7, "липня": 7,
    "aug": 8, "august": 8, "sie": 8, "sierpnia": 8, "серп": 8, "серпня": 8,
    "sep": 9, "sept": 9, "september": 9, "wrz": 9, "września": 9, "вер": 9, "вересня": 9,
    "oct": 10, "october": 10, "paź": 10, "paz": 10, "października": 10, "жовп": 10, "жовтня": 10,
    "nov": 11, "november": 11, "lis": 11, "listopada": 11, "лист": 11, "листопада": 11,
    "dec": 12, "december": 12, "gru": 12, "grudnia": 12, "груд": 12, "грудня": 12,
}


@dataclass
class Deadline:
    start: date | None
    end: date
    label_key: str
    source_url: str | None = None


def _month_num(token: str) -> int | None:
    mon = re.sub(r"[^a-zа-яіїєґ]", "", (token or "").lower())
    if not mon:
        return None
    if mon in _MONTH_NUM:
        return _MONTH_NUM[mon]
    for k, v in _MONTH_NUM.items():
        if mon.startswith(k) or k.startswith(mon[:3]):
            return v
    return None


def _fmt(d: date, lang: str) -> str:
    if lang == "en":
        return d.strftime("%d %b %Y")
    return d.strftime("%d.%m.%Y")


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _yearless_date(month: int, day: int, today: date) -> date | None:
    """Most recent occurrence of month/day that is ≤ today; else upcoming this year."""
    d = _safe_date(today.year, month, day)
    if d is None:
        return None
    if d > today:
        return _safe_date(today.year - 1, month, day) or d
    return d


def parse_deadlines(text: str, today: date | None = None) -> list[Deadline]:
    """Find ranges first (record spans), then singles / month-names outside those spans."""
    if not text:
        return []
    today = today or date.today()
    covered: list[tuple[int, int]] = []
    found: list[Deadline] = []

    def overlaps(a: int, b: int) -> bool:
        return any(not (b <= s or a >= e) for s, e in covered)

    # Ranges: od dd.mm.yyyy do dd.mm.yyyy / dd.mm.yyyy – dd.mm.yyyy
    for m in re.finditer(
        r"(?:od\s+)?(\d{1,2})[./](\d{1,2})[./](\d{4})\s*(?:[–—−\-]|do)\s*(?:do\s+)?(\d{1,2})[./](\d{1,2})[./](\d{4})",
        text, re.I,
    ):
        start = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        end = _safe_date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
        if not end:
            continue
        covered.append((m.start(), m.end()))
        found.append(Deadline(start=start, end=end, label_key="range"))

    # Ranges with month names: 1–5 października 2026 / od 1 do 5 października 2026
    for m in re.finditer(
        r"(?:od\s+)?(\d{1,2})\s*[–—−\-do]+\s*(\d{1,2})\s+([A-Za-zÀ-žа-яА-ЯіІїЇєЄґҐ]+)\s+(\d{4})",
        text, re.I,
    ):
        mon = _month_num(m.group(3))
        if not mon or overlaps(m.start(), m.end()):
            continue
        y = int(m.group(4))
        start = _safe_date(y, mon, int(m.group(1)))
        end = _safe_date(y, mon, int(m.group(2)))
        if not end:
            continue
        covered.append((m.start(), m.end()))
        found.append(Deadline(start=start, end=end, label_key="range_month"))

    # Prefixed single: after|until|by|po|do|до|не пізніше + date
    for m in re.finditer(
        r"(?:after|until|by|po\s+dniu|po|do|до|не\s*пізніше(?:\s*ніж)?)\s+"
        r"(?:(\d{1,2})[./](\d{1,2})[./](\d{4})"
        r"|(\d{1,2})\s+([A-Za-zÀ-žа-яА-ЯіІїЇєЄґҐ]+)\s+(\d{4})"
        r"|(\d{1,2})\s+([A-Za-zÀ-žа-яА-ЯіІїЇєЄґҐ]+)\b)",
        text, re.I,
    ):
        if overlaps(m.start(), m.end()):
            continue
        end = None
        if m.group(1):
            end = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        elif m.group(4):
            mon = _month_num(m.group(5))
            if mon:
                end = _safe_date(int(m.group(6)), mon, int(m.group(4)))
        elif m.group(7):
            mon = _month_num(m.group(8))
            if mon:
                end = _yearless_date(mon, int(m.group(7)), today)
        if not end:
            continue
        covered.append((m.start(), m.end()))
        found.append(Deadline(start=None, end=end, label_key="until"))

    # Bare numeric singles outside ranges
    for m in re.finditer(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)", text):
        if overlaps(m.start(), m.end()):
            continue
        end = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if not end:
            continue
        covered.append((m.start(), m.end()))
        found.append(Deadline(start=None, end=end, label_key="single"))

    # Month-name with year outside ranges
    for m in re.finditer(
        r"(?<!\d)(\d{1,2})\s+([A-Za-zÀ-žа-яА-ЯіІїЇєЄґҐ]+)\s+(\d{4})",
        text, re.I,
    ):
        if overlaps(m.start(), m.end()):
            continue
        mon = _month_num(m.group(2))
        if not mon:
            continue
        end = _safe_date(int(m.group(3)), mon, int(m.group(1)))
        if not end:
            continue
        covered.append((m.start(), m.end()))
        found.append(Deadline(start=None, end=end, label_key="month_year"))

    # Yearless month-name: "do 15 maja" (if not already covered by prefixed)
    for m in re.finditer(
        r"(?:do|до|by|until|po)\s+(\d{1,2})\s+([A-Za-zÀ-žа-яА-ЯіІїЇєЄґҐ]+)\b(?!\s*\d{4})",
        text, re.I,
    ):
        if overlaps(m.start(), m.end()):
            continue
        mon = _month_num(m.group(2))
        if not mon:
            continue
        end = _yearless_date(mon, int(m.group(1)), today)
        if not end:
            continue
        covered.append((m.start(), m.end()))
        found.append(Deadline(start=None, end=end, label_key="yearless"))

    return found


def render_deadline_notes(deadlines: list[Deadline], lang: str = "pl", today: date | None = None) -> str:
    """Exactly one localized line per passed end date; dates formatted by code."""
    today = today or date.today()
    by_end: dict[date, Deadline] = {}
    for d in deadlines:
        if d.end < today:
            by_end[d.end] = d
    if not by_end:
        return ""
    notes = []
    for end in sorted(by_end):
        d = by_end[end]
        if d.start:
            disp = f"{_fmt(d.start, lang)} – {_fmt(d.end, lang)}"
        else:
            disp = _fmt(d.end, lang)
        msg = {
            "pl": f"⚠️ Ten termin ({disp}) już minął (dziś: {today.isoformat()}).",
            "en": f"⚠️ This deadline ({disp}) has already passed (today: {today.isoformat()}).",
            "uk": f"⚠️ Цей термін ({disp}) уже минув (сьогодні: {today.isoformat()}).",
            "mn": f"⚠️ Энэ хугацаа ({disp}) өнгөрсөн (өнөөдөр: {today.isoformat()}).",
        }.get(lang) or f"⚠️ Ten termin ({disp}) już minął (dziś: {today.isoformat()})."
        if msg not in notes:
            notes.append(msg)
    return "\n" + "\n".join(notes)


def strip_llm_deadline_notes(text: str) -> str:
    """Remove LLM-written passed-deadline lines so code owns the warning."""
    if not text:
        return text
    lines = []
    for line in text.splitlines():
        if re.search(
            r"(?i)⚠️.*(minął|passed|минув|өнгөрсөн)|termin już minął|deadline.{0,40}already\s+passed|"
            r"термін.{0,40}минув",
            line,
        ):
            continue
        lines.append(line)
    return "\n".join(lines).rstrip()


def deadline_passed_note(text: str, lang: str = "pl") -> str:
    """Compat wrapper for harness / rag.answer."""
    return render_deadline_notes(parse_deadlines(text or "", date.today()), lang, date.today())
