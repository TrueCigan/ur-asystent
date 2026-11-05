"""Single owner for deadline-passed warnings (Task 2 / R5-7)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

_MONTH_NUM = {
    "jan": 1, "january": 1, "sty": 1, "stycznia": 1, "styczen": 1, "січ": 1, "січня": 1,
    "feb": 2, "february": 2, "lut": 2, "lutego": 2, "лют": 2, "лютого": 2,
    "mar": 3, "march": 3, "marca": 3, "берез": 3, "березня": 3,
    "apr": 4, "april": 4, "kwi": 4, "kwietnia": 4, "квіт": 4, "квітня": 4,
    "may": 5, "maja": 5, "май": 5, "трав": 5, "травня": 5,
    "jun": 6, "june": 6, "cze": 6, "czerwca": 6, "черв": 6, "червня": 6,
    "jul": 7, "july": 7, "lip": 7, "lipca": 7, "лип": 7, "липня": 7,
    "aug": 8, "august": 8, "sie": 8, "sierpnia": 8, "серп": 8, "серпня": 8,
    "sep": 9, "sept": 9, "september": 9, "wrz": 9, "wrzesnia": 9, "вер": 9, "вересня": 9,
    "oct": 10, "october": 10, "paz": 10, "padziernika": 10, "października": 10, "жовп": 10, "жовтня": 10,
    "nov": 11, "november": 11, "lis": 11, "listopada": 11, "лист": 11, "листопада": 11,
    "dec": 12, "december": 12, "gru": 12, "grudnia": 12, "груд": 12, "грудня": 12,
}

_DEADLINE_CTX = re.compile(
    r"(?i)(?:do|until|by|termin|deadline|nie\s+później\s+niż|nie\s+pozniej\s+niz|"
    r"до|не\s*пізніше|składa\s*się\s*do|wpłacić\s*do|wplacic\s*do|"
    r"registration\s+closes|opłat\w*\s*do|wniosek.{0,20}do|zadatek.{0,20}do|"
    r"zakwaterowanie\s+w\s+terminie|закрывається|закривається)",
)

_EXCLUDE_CTX = re.compile(
    r"(?i)(?:z\s+dnia|dated|uchwał|zarządzen|regulation|aktualizac|updated|"
    r"egzamin|exam|екзамен|о\s+\d{1,2}:\d{2}|zaktualizowana|"
    r"uchwała\s*nr|zarządzenie\s*nr|\bBIP\b|resolution|postanowien|"
    r"enter\s+into\s+force|wchodzi\s+w\s+życie|strona\s+zaktualizowana)",
)


@dataclass
class Deadline:
    start: date | None
    end: date
    label_key: str
    source_url: str | None = None


def _fold(token: str) -> str:
    """NFKD + drop combining marks; ł/Ł → l."""
    t = (token or "").replace("ł", "l").replace("Ł", "L")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^a-zа-яіїєґ]", "", t.lower())


def _month_num(token: str) -> int | None:
    mon = _fold(token)
    if not mon:
        return None
    if mon in _MONTH_NUM:
        return _MONTH_NUM[mon]
    pref = mon[:3]
    for k, v in _MONTH_NUM.items():
        if mon.startswith(k) or k.startswith(pref) or _fold(k).startswith(pref):
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


def _ctx_ok(text: str, start: int, end: int) -> bool:
    """Require deadline cue nearby; reject regulation/exam/update dates."""
    left = text[max(0, start - 40):start]
    right = text[end:min(len(text), end + 20)]
    window = left + text[start:end] + right
    if _EXCLUDE_CTX.search(window):
        return False
    if _DEADLINE_CTX.search(left) or _DEADLINE_CTX.search(text[max(0, start - 40):end]):
        return True
    return False


def _merge_windows(found: list[Deadline], text: str) -> list[Deadline]:
    """Merge only partial/full ranges already parsed as one Deadline; keep separate 'do' deadlines."""
    # Ranges already have start+end. Multiple until/yearless in one sentence stay separate
    # (e.g. "do 1 października … do 15 października" → 2 notes).
    out = []
    for d in found:
        if d.label_key in ("range", "partial_range", "range_month", "window"):
            # collapse duplicate identical ends
            if any(x.end == d.end and x.start == d.start for x in out):
                continue
        out.append(d)
    return out


def parse_deadlines(text: str, today: date | None = None) -> list[Deadline]:
    """Find ranges first, then contextual singles / month-names."""
    if not text:
        return []
    today = today or date.today()
    covered: list[tuple[int, int]] = []
    found: list[Deadline] = []

    def overlaps(a: int, b: int) -> bool:
        return any(not (b <= s or a >= e) for s, e in covered)

    # Full ranges: od dd.mm.yyyy do dd.mm.yyyy
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

    # Partial ranges: 29.09–1.10.2026 (inherit year; if start month > end month → year-1)
    for m in re.finditer(
        r"(?<!\d)(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?\s*[–—−\-]\s*(\d{1,2})[./](\d{1,2})[./](\d{4})",
        text,
    ):
        if overlaps(m.start(), m.end()):
            continue
        ey = int(m.group(6))
        em, ed = int(m.group(5)), int(m.group(4))
        sm, sd = int(m.group(2)), int(m.group(1))
        sy = int(m.group(3)) if m.group(3) else ey
        if not m.group(3) and sm > em:
            sy = ey - 1
        start = _safe_date(sy, sm, sd)
        end = _safe_date(ey, em, ed)
        if not end:
            continue
        covered.append((m.start(), m.end()))
        found.append(Deadline(start=start, end=end, label_key="partial_range"))

    # Ranges with month names: 1–5 października 2026
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

    # Multi-month move-in windows: 29–30 września i 1 października 2026
    for m in re.finditer(
        r"(?i)(\d{1,2})(?:\s*[–—−\-]\s*(\d{1,2}))?\s+([A-Za-zÀ-žа-яА-ЯіІїЇєЄґҐ]+)\s+i\s+"
        r"(\d{1,2})\s+([A-Za-zÀ-žа-яА-ЯіІїЇєЄґҐ]+)\s+(\d{4})",
        text,
    ):
        if overlaps(m.start(), m.end()):
            continue
        cue = text[max(0, m.start() - 60):m.end() + 30]
        if not re.search(r"(?i)kwaterowanie|zakwaterowanie|move-?in|заселен|wprowadz", cue):
            continue
        mon_a = _month_num(m.group(3))
        mon_b = _month_num(m.group(5))
        if not mon_a or not mon_b:
            continue
        y = int(m.group(6))
        d_start = int(m.group(1))
        d_mid = int(m.group(2)) if m.group(2) else d_start
        d_end = int(m.group(4))
        start = _safe_date(y, mon_a, d_start)
        mid = _safe_date(y, mon_a, d_mid)
        end = _safe_date(y, mon_b, d_end)
        if not start or not end:
            continue
        if mid and mid > end:
            end = mid
        covered.append((m.start(), m.end()))
        found.append(Deadline(start=start, end=end, label_key="window"))

    # Prefixed single: until/by/do + date (always contextual)
    for m in re.finditer(
        r"(?:after|until|by|po\s+dniu|po|do|до|не\s*пізніше(?:\s*ніж)?|"
        r"termin|deadline|składa\s*się\s*do|wpłacić\s*do|opłat\w*\s*do|"
        r"закривається|закрывается)\s+"
        r"(?:(\d{1,2})[./](\d{1,2})[./](\d{4})"
        r"|(\d{1,2})\s+([A-Za-zÀ-žа-яА-ЯіІїЇєЄґҐ]+)\s+(\d{4})"
        r"|(\d{1,2})\s+([A-Za-zÀ-žа-яА-ЯіІїЇєЄґҐ]+)\b)",
        text, re.I,
    ):
        if overlaps(m.start(), m.end()):
            continue
        # Prefixed match is already a deadline cue; only skip clear "dated/z dnia" regulation stamps
        left = text[max(0, m.start() - 40):m.start()]
        if re.search(r"(?i)(?:z\s+dnia|dated|uchwał\w*\s+nr|aktualizac|zaktualizowana)", left):
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

    # Bare numeric singles — only with deadline context
    for m in re.finditer(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)", text):
        if overlaps(m.start(), m.end()):
            continue
        if not _ctx_ok(text, m.start(), m.end()):
            continue
        end = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if not end:
            continue
        covered.append((m.start(), m.end()))
        found.append(Deadline(start=None, end=end, label_key="single"))

    # Month-name with year — only with deadline context
    for m in re.finditer(
        r"(?<!\d)(\d{1,2})\s+([A-Za-zÀ-žа-яА-ЯіІїЇєЄґҐ]+)\s+(\d{4})",
        text, re.I,
    ):
        if overlaps(m.start(), m.end()):
            continue
        if not _ctx_ok(text, m.start(), m.end()):
            continue
        mon = _month_num(m.group(2))
        if not mon:
            continue
        end = _safe_date(int(m.group(3)), mon, int(m.group(1)))
        if not end:
            continue
        covered.append((m.start(), m.end()))
        found.append(Deadline(start=None, end=end, label_key="month_year"))

    # Yearless month-name: "do 15 maja" / "do 1 października"
    for m in re.finditer(
        r"(?:do|до|by|until|po|opłat\w*\s*do|wpłacić\s*do)\s+(\d{1,2})\s+([A-Za-zÀ-žа-яА-ЯіІїЇєЄґҐ]+)\b(?!\s*\d{4})",
        text, re.I,
    ):
        if overlaps(m.start(), m.end()):
            continue
        if _EXCLUDE_CTX.search(text[max(0, m.start() - 40):m.end() + 20]):
            continue
        mon = _month_num(m.group(2))
        if not mon:
            continue
        end = _yearless_date(mon, int(m.group(1)), today)
        if not end:
            continue
        covered.append((m.start(), m.end()))
        found.append(Deadline(start=None, end=end, label_key="yearless"))

    return _merge_windows(found, text)


def render_deadline_notes(
    deadlines: list[Deadline],
    lang: str = "pl",
    today: date | None = None,
    topics: list[str] | None = None,
) -> str:
    """Exactly one localized line per passed window; dates formatted by code."""
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
        if d.start and d.start != d.end:
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
    tset = set(topics or [])
    if notes and (tset & {"stypendium_socjalne", "stypendium_rektora", "stypendium_niepeln", "akademik"}):
        hint = {
            "pl": "Sprawdź w BOS, czy możliwe jest złożenie wniosku po terminie.",
            "en": "Check with the Student Service Office whether a late application is possible.",
            "uk": "Перевірте в BOS, чи можливе подання заяви після терміну.",
            "mn": "Хугацаа хэтэрсний дараа өргөдөл гаргах боломжтой эсэхийг BOS-оос лавлана уу.",
        }.get(lang)
        if hint:
            notes.append(hint)
    return "\n" + "\n".join(notes)


def strip_llm_deadline_notes(text: str) -> str:
    """Remove LLM-written passed-deadline lines/phrases so code owns the warning (R6-4)."""
    if not text:
        return text
    lines = []
    for line in text.splitlines():
        # Drop whole lines that are only a ⚠️ / “termin minął” warning
        if re.search(r"(?i)^\s*⚠️", line) and re.search(
            r"(?i)minął|passed|минув|өнгөрсөн", line
        ):
            continue
        if re.search(
            r"(?i)^\s*(termin\s+(już\s+)?minął|deadline.{0,40}already\s+passed|"
            r"термін.{0,40}минув)\s*$",
            line,
        ):
            continue
        # Strip inline phrases; keep the date / content
        line = re.sub(r"(?i)\s*[–—−\-:]?\s*termin\s+(już\s+)?minął\b", "", line)
        line = re.sub(r"(?i)\s*[–—−\-:]?\s*deadline\s+has\s+already\s+passed\b", "", line)
        line = re.sub(r"(?i)\s*[–—−\-:]?\s*термін\s+(уже\s+)?минув\b", "", line)
        line = re.sub(r"[ \t]{2,}", " ", line).rstrip()
        if line.strip():
            lines.append(line)
    return "\n".join(lines).rstrip()


def deadline_passed_note(text: str, lang: str = "pl", today: date | None = None, topics: list[str] | None = None) -> str:
    """Compat wrapper for harness / rag.answer."""
    today = today or date.today()
    return render_deadline_notes(parse_deadlines(text or "", today), lang, today, topics=topics)
