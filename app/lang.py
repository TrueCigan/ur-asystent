"""Session language policy: sticky lang with substantive switch, ru→uk, output validation.

Output languages: pl / en / uk only (redesign P3). Mongolian script → en. Russian → uk.
"""
from __future__ import annotations

import re

ALLOWED = ("pl", "en", "uk")
LANG_NAME = {"pl": "polski", "en": "English", "uk": "українська"}

_RU_MARKERS = re.compile(r"[ыэъЫЭЪёЁ]|\b(что|спасибо|вот|сколько|можно|привет|нужна|оформить)\b", re.I)
_UK_MARKERS = re.compile(r"[іїєґІЇЄҐ]")
_MN_MARKERS = re.compile(r"[өүӨҮ]")
_PL_MARKERS = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
_EN_STOP = re.compile(
    r"\b(the|and|how|what|when|where|scholarship|tuition|fees?|i'?m|i am|from|have|"
    r"full[- ]time|part[- ]time|bachelor|master'?s?|phd|doctoral|citizen|foreign|hello|"
    r"stationary|major|programme|program|degree|belarus|india)\b",
    re.I,
)
_PL_STOP = re.compile(
    r"\b(jak|czy|stypendium|opłat|jestem|studiuj|cudzoziem|rektor|zajęć|dzie[nń]|dobry|"
    r"jako|możesz|wniosek|termin)\b",
    re.I,
)
_UK_STOP = re.compile(
    r"\b(як|чи|стипенд|оплат|громадян|інозем|навчан|кошту|можете|навчаєтесь|джерела)\b",
    re.I,
)
_MN_STOP = re.compile(r"тэтгэлэг|оюутан|суралц|төлбөр|иргэн|мэргэжил|докторант|баярлалаа|сайн\s*байна", re.I)
_MIXED_TOKEN = re.compile(
    r"(?=\w*[A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ])(?=\w*[А-Яа-яІіЇїЄєҐґӨөҮүЁё])\w+",
)


def map_policy(lang: str) -> str:
    """ru → uk; legacy mn → en; unknown → pl."""
    if lang == "ru":
        return "uk"
    if lang == "mn":
        return "en"
    return lang if lang in ALLOWED else "pl"


def explicit_switch_request(text: str) -> str | None:
    """Detect explicit language switch. 'по-русски' / Mongolian → policy targets (uk / en)."""
    if not text:
        return None
    t = text.strip()
    if re.search(
        r"(?i)(?:odpowiedz|answer|reply|respond|write|switch|переключ|пиши|хариул).{0,25}"
        r"(?:po\s*polsku|in\s*polish|польськ|польш\s*хэлээр)"
        r"|(?:po\s*polsku|польською|польш\s*хэлээр)\s*(?:proszę|please|будь\s*ласка)?\s*$",
        t,
    ):
        return "pl"
    if re.search(
        r"(?i)(?:odpowiedz|answer|reply|respond|write|switch|переключ|пиши).{0,25}"
        r"(?:in\s*english|po\s*angielsku|англійськ|английск)"
        r"|(?:in\s*english|english\s*please|po\s*angielsku)\s*$",
        t,
    ):
        return "en"
    if re.search(
        r"(?i)(?:odpowiedz|answer|reply|переключ|пиши).{0,25}"
        r"(?:українськ|ukrainian|по\s*україн|на\s*украин)"
        r"|(?:українськ|по\s*україн)\w*\s*$",
        t,
    ):
        return "uk"
    if re.search(
        r"(?i)(?:odpowiedz|answer|reply|переключ|пиши|можешь|можеш|можешь\s*ответить).{0,40}"
        r"(?:русск|russian|по\s*русск|на\s*русск)|(?:по\s*русски|по-русски|in\s*russian|а\s+по-русски)",
        t,
    ):
        return "uk"
    if re.search(
        r"(?i)(?:odpowiedz|answer|хариул).{0,25}(?:монгол|mongolian)"
        r"|(?:монгол\s*хэлээр|in\s*mongolian)\s*$",
        t,
    ):
        return "en"  # no mn output
    return None


def detect_message_lang(text: str) -> tuple[str, float]:
    """(lang, confidence). Mongolian script → en (no mn in ALLOWED)."""
    if not text or not text.strip():
        return "pl", 0.0
    t = text.strip()
    words = re.findall(r"\w+", t, re.U)
    short = len(words) < 3
    letters = len(re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґӨөҮүЁёąćęłńóśźż]", t))

    # Mongolian letters / stopwords → English (policy: no mn replies)
    if _MN_MARKERS.search(t) or _MN_STOP.search(t):
        return "en", 0.9 if _MN_MARKERS.search(t) else 0.7
    if _UK_MARKERS.search(t):
        return "uk", 0.95
    if re.search(r"[а-яА-ЯёЁ]", t):
        if _RU_MARKERS.search(t) or re.search(r"\b(как|студент\s+из|нужна|стипендия)\b", t, re.I):
            return "ru", 0.9 if not short else 0.55
        return "uk", 0.55
    if _PL_MARKERS.search(t):
        return "pl", 0.9
    if _EN_STOP.search(t):
        conf = 0.9 if (len(words) >= 4 or letters >= 25) else (0.85 if not short else 0.5)
        return "en", conf
    if _PL_STOP.search(t):
        return "pl", 0.8 if not short else 0.45
    if _UK_STOP.search(t):
        return "uk", 0.75
    if short:
        return "pl", 0.2
    return "pl", 0.35


def resolve_session_lang(state_lang: str | None, message: str) -> str:
    sw = explicit_switch_request(message)
    if sw:
        return map_policy(sw)
    lang, conf = detect_message_lang(message)
    mapped = map_policy(lang)
    words = re.findall(r"\w+", message or "", re.U)
    letters = len(re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґӨөҮүЁёąćęłńóśźż]", message or ""))
    substantive = conf >= 0.85 and (len(words) >= 4 or letters >= 25)
    sticky = map_policy(state_lang) if state_lang else None
    if sticky and sticky in ALLOWED:
        if substantive and mapped != sticky and mapped in ALLOWED:
            return mapped
        return sticky
    return mapped if conf >= 0.6 else map_policy(state_lang or lang)


def sticky_lang_from_user_turns(turns: list[str], latest: str = "") -> str:
    """Walk prior user turns, then apply latest message (sticky / switch)."""
    state = None
    for turn in turns:
        if turn and turn.strip():
            state = resolve_session_lang(state, turn)
    if latest and latest.strip():
        state = resolve_session_lang(state, latest)
    return state or "pl"


def mixed_script_tokens(text: str) -> list[str]:
    """Tokens that mix Latin and Cyrillic letters (e.g. Statус, diплом)."""
    if not text:
        return []
    return _MIXED_TOKEN.findall(text)


def _strip_sources_block(text: str) -> str:
    lines, cut = [], False
    for line in (text or "").splitlines():
        if re.match(r"(?i)^\s*(źródła|sources|джерела|источники|эх\s*сурвалж)\s*:?\s*$", line.strip()):
            cut = True
            break
        if not cut:
            lines.append(line)
    return "\n".join(lines)


def english_prose_beyond_diacritics(text: str) -> bool:
    """English is a property of the prose, not of missing Polish diacritics.

    Quoted fragments are ignored. "Koszt programu wynosi 2600 EUR" has no
    ąćęłńóśźż and is still not English.
    """
    body = re.sub(r"«[^»]*»|\"[^\"]{0,240}\"|„[^“]{0,240}“", " ", text or "")
    polish = bool(re.search(r"\b(koszt|wynosi|programu|opłata|oplata|jest|dla|studia)\b", body, re.I))
    english = bool(re.search(r"\b(the|is|are|for|about|costs|fee|programme|program)\b", body, re.I))
    if polish and not english:
        return False
    return english


def output_lang_ok(answer: str, target: str) -> bool:
    """False if Russian, Mongolian, wrong language body, or mixed-script tokens."""
    if not answer or not answer.strip():
        return True
    target = map_policy(target)
    if target not in ALLOWED:
        target = "pl"
    body = _strip_sources_block(answer)
    if mixed_script_tokens(body) or mixed_script_tokens(answer):
        return False
    # Mongolian letters never OK in user-visible answers
    if _MN_MARKERS.search(body) or _MN_MARKERS.search(answer):
        return False
    if _MN_STOP.search(body):
        return False
    ru_hits = len(re.findall(r"[ыэъЫЭЪ]", body))
    ru_words = len(_RU_MARKERS.findall(body))
    uk_hits = len(_UK_MARKERS.findall(body))
    if ru_hits + ru_words >= 2 and ru_hits >= uk_hits:
        return False
    words = re.findall(r"\w+", body, re.U)
    if len(words) >= 30:
        detected, _conf = detect_message_lang(body)
        detected = map_policy(detected)
        if detected != target:
            if target == "uk" and uk_hits > 0 and ru_hits == 0:
                pass
            else:
                return False
    if target == "uk":
        if _PL_MARKERS.search(body) and uk_hits == 0 and len(words) >= 20:
            return False
        if ru_hits >= 2 and uk_hits == 0:
            return False
        if len(words) >= 20 and _PL_STOP.search(body) and uk_hits == 0 and not _UK_STOP.search(body):
            return False
        return True
    if target in ("pl", "en"):
        cyr = len(re.findall(r"[а-яА-ЯёЁіїєґөүІЇЄҐӨҮ]", body))
        if cyr > 0:
            return False
    # The e2e detector treats any Polish diacritic as Polish. An English answer
    # must not keep a Polish fact note or a Polish retrieval quote.
    if target == "en" and re.search(r"[ąćęłńóśźż]", body, re.I):
        return False
    return True
