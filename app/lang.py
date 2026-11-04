"""Session language policy: sticky lang, ru→uk, output validation."""
from __future__ import annotations

import re

ALLOWED = ("pl", "en", "uk", "mn")
LANG_NAME = {"pl": "polski", "en": "English", "uk": "українська", "mn": "монгол"}

_RU_MARKERS = re.compile(r"[ыэъЫЭЪёЁ]|\b(что|спасибо|вот|сколько|можно|привет|нужна|оформить)\b", re.I)
_UK_MARKERS = re.compile(r"[іїєґІЇЄҐ]")
_MN_MARKERS = re.compile(r"[өүӨҮ]")
_PL_MARKERS = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
_EN_STOP = re.compile(
    r"\b(the|and|how|what|when|where|scholarship|tuition|fees?|i'?m|i am|"
    r"full[- ]time|part[- ]time|bachelor|master'?s?|phd|doctoral|citizen|foreign|hello)\b",
    re.I,
)
_PL_STOP = re.compile(r"\b(jak|czy|stypendium|opłat|jestem|studiuj|cudzoziem|rektor|zajęć|dzie[nń]|dobry)\b", re.I)
_UK_STOP = re.compile(r"\b(як|чи|стипенд|оплат|громадян|інозем|навчан|кошту)\b", re.I)
_MN_STOP = re.compile(r"тэтгэлэг|оюутан|суралц|төлбөр|иргэн|мэргэжил|докторант|баярлалаа|сайн\s*байна", re.I)


def map_policy(lang: str) -> str:
    """ru -> uk, unknown -> pl."""
    if lang == "ru":
        return "uk"
    return lang if lang in ALLOWED else "pl"


def explicit_switch_request(text: str) -> str | None:
    """Detect explicit language switch. 'по-русски' maps to uk (policy)."""
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
    # Prośba o rosyjski → ukraiński (polityka produktu)
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
        return "mn"
    return None


def detect_message_lang(text: str) -> tuple[str, float]:
    """(lang, confidence). Low confidence for short / no-script messages."""
    if not text or not text.strip():
        return "pl", 0.0
    t = text.strip()
    words = re.findall(r"\w+", t, re.U)
    short = len(words) < 3

    if _MN_MARKERS.search(t) or _MN_STOP.search(t):
        return "mn", 0.95 if _MN_MARKERS.search(t) else 0.75
    if _UK_MARKERS.search(t):
        return "uk", 0.95
    if re.search(r"[а-яА-ЯёЁ]", t):
        if _RU_MARKERS.search(t) or re.search(r"\b(как|студент\s+из|нужна|стипендия)\b", t, re.I):
            return "ru", 0.9 if not short else 0.55
        return "uk", 0.55  # Cyrillic without clear ru/uk markers
    if _PL_MARKERS.search(t):
        return "pl", 0.9
    if _EN_STOP.search(t):
        return "en", 0.85 if not short else 0.5
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
    if state_lang and state_lang in ALLOWED:
        return state_lang  # sticky — short replies ("daily", "cudzoziemiec") must not flip
    lang, conf = detect_message_lang(message)
    return map_policy(lang) if conf >= 0.6 else map_policy(state_lang or lang)


def sticky_lang_from_user_turns(turns: list[str], latest: str = "") -> str:
    """Walk prior user turns, then apply latest message (sticky)."""
    state = None
    for turn in turns:
        if turn and turn.strip():
            state = resolve_session_lang(state, turn)
    if latest and latest.strip():
        state = resolve_session_lang(state, latest)
    return state or "pl"


def output_lang_ok(answer: str, target: str) -> bool:
    """False if Russian dominates or script clearly mismatches target."""
    if not answer or not answer.strip():
        return True
    target = map_policy(target)
    # Russian markers must not dominate any allowed answer language
    ru_hits = len(re.findall(r"[ыэъЫЭЪ]", answer))
    ru_words = len(_RU_MARKERS.findall(answer))
    uk_hits = len(_UK_MARKERS.findall(answer))
    mn_hits = len(_MN_MARKERS.findall(answer))
    if ru_hits + ru_words >= 2 and ru_hits >= uk_hits:
        return False
    if target == "mn":
        # MN answers should have өү or be Latin-light Cyrillic with MN markers; pure Russian fail
        if ru_hits >= 2 and mn_hits == 0 and uk_hits == 0:
            return False
        return True
    if target == "uk":
        if ru_hits >= 2 and uk_hits == 0:
            return False
        return True
    if target in ("pl", "en"):
        cyr = len(re.findall(r"[а-яА-ЯёЁіїєґөүІЇЄҐӨҮ]", answer))
        lat = len(re.findall(r"[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", answer))
        if cyr > lat * 2 and cyr > 20:
            return False
    return True
