"""LLM structured slot/topic extraction (Task 4). Falls back to regex needed() when LLM is off/invalid."""
from __future__ import annotations

import json
import os
import re

EXTRACT_SCHEMA_HINT = """
Output JSON only:
{"intents":[...],"slot_updates":{...},"answers_pending":bool,"conflicts":[],"message_lang":"...","explicit_lang_switch":null}
Interpret short replies as answers to pending slots. Negations of second programme are NOT dwa_kierunki.
Nationality: Polish / Polish student => pl; other country/foreigner => cudzoziemiec.
pobyt=ukr ONLY if temporary protection / PESEL UKR / ochrona czasowa / охорона is stated — NEVER from "из Украины" / "з України" alone (that is cudzoziemiec without pobyt=ukr).
karta pobytu => pobyt_czasowy.
status=doktorant / poziom=SD ONLY on self-identification (jestem doktorantem / I'm a PhD student / szkoła doktorska).
Mentions of "stypendium doktoranckie" as a TOPIC do NOT set status=doktorant.
"nie jestem doktorantem" / "tylko licencjat" → clear doktorant; keep I/bachelor if stated.
Disability degree words (znaczna / значительная / considerable) => niepelnosprawnosc=tak — do NOT leave that slot missing.
Never clear a filled slot unless explicit negation/conflict.
Never invent arithmetic percentages; amounts come from facts.
"""

_SLOT_ENUMS = {
    "status": {"pl", "cudzoziemiec", "doktorant", "bezpanstwowiec"},
    "tryb": {"stacjonarne", "niestacjonarne"},
    "poziom": {"I", "II", "SD", "jednolite"},
    "rok": {"1", "2", "3", "4", "5", "6"},
    "drugi_kierunek": {"tak", "nie", "pytanie"},
    "niepelnosprawnosc": {"tak", "nie"},
    "pobyt": {"ukr", "karta_polaka", "pobyt_czasowy", "pobyt_staly"},
}


def extractor_llm_enabled() -> bool:
    """Default ON when a chat LLM is configured; set EXTRACTOR_LLM=0 for regex-only."""
    flag = os.getenv("EXTRACTOR_LLM", "").strip().lower()
    if flag in ("0", "false", "off", "no"):
        return False
    if flag in ("1", "true", "on", "yes"):
        return True
    prov = (os.getenv("LLM_PROVIDER") or "").lower()
    if prov == "gemini":
        return bool(os.getenv("GEMINI_API_KEY") or os.getenv("LLM_API_KEY"))
    if prov == "ollama":
        return True
    if prov:
        return bool(os.getenv("LLM_API_KEY"))
    return bool(os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY"))


def extract_turn(
    message: str,
    profile: dict,
    pending_question: str | None,
    pending_slots: list,
    call_llm,
    *,
    original_question: str | None = None,
    intents: list | None = None,
    user_turns: list | None = None,
) -> dict | None:
    """Return parsed extraction dict or None to signal regex fallback.

    Preferred path for R5-3 when regex leaves clarifying slots unanswered.
    Pass full dialogue state so the model does not re-invent filled slots (P4).
    """
    if not extractor_llm_enabled():
        return None
    if not message or not call_llm:
        return None
    allowed = ", ".join(sorted(_SLOT_ENUMS))
    recent = list(user_turns or [])[-6:]
    state_blob = {
        "profile": profile or {},
        "pending_slots": pending_slots or [],
        "pending_question": pending_question,
        "original_question": original_question,
        "intents": intents or [],
        "user_turns": recent,
    }
    sys = (
        "You extract structured student-profile slots for Uniwersytet Radomski assistant. "
        + EXTRACT_SCHEMA_HINT
        + f"\nAllowed slots: {allowed}. Use null when unknown. "
        "Never set niepelnosprawnosc unless the message mentions disability. "
        "Negations of second programme / no previous degree → drugi_kierunek=nie.\n"
        f"Dialogue state: {json.dumps(state_blob, ensure_ascii=False)}"
    )
    try:
        raw = call_llm(
            [{"role": "system", "content": sys}, {"role": "user", "content": f"<<<{message}>>>"}],
            temperature=0.0,
        )
    except Exception:
        return None
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    # Normalize: allow slot_updates without intents
    data.setdefault("intents", [])
    data.setdefault("conflicts", [])
    return data


def apply_extraction(state_profile: dict, data: dict, min_conf: float = 0.7) -> tuple[dict, list]:
    """Merge high-confidence slot_updates; return (profile, conflicts). Validate enums."""
    prof = dict(state_profile or {})
    conflicts = list(data.get("conflicts") or [])
    updates = data.get("slot_updates") or {}
    for slot, body in updates.items():
        if slot not in _SLOT_ENUMS:
            continue
        if not isinstance(body, dict):
            # allow bare string values from simpler models
            if body is None:
                continue
            body = {"value": body, "confidence": 1.0}
        conf = float(body.get("confidence") or 0)
        if conf < min_conf:
            continue
        val = body.get("value")
        if val is None:
            continue
        if slot == "drugi_kierunek" and isinstance(val, bool):
            val = "tak" if val else "nie"
        if slot == "rok":
            val = str(val).strip()
        allowed = _SLOT_ENUMS[slot]
        if val not in allowed:
            continue
        if slot in prof and prof[slot] != val:
            # Never overwrite a filled slot without an explicit conflict record (P4)
            conflicts.append({"slot": slot, "old": prof[slot], "new": val, "reason": "conflict"})
            continue
        if slot in prof and prof[slot] == val:
            continue
        prof[slot] = val
    return prof, conflicts
