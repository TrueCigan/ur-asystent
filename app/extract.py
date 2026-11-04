"""LLM structured slot/topic extraction (Task 4). Falls back to regex needed() when LLM is off/invalid."""
from __future__ import annotations

import json
import os
import re

EXTRACT_SCHEMA_HINT = """
Output JSON only:
{"intents":[...],"slot_updates":{...},"answers_pending":bool,"conflicts":[],"message_lang":"...","explicit_lang_switch":null}
Interpret short replies as answers to pending slots. Negations of second programme are NOT dwa_kierunki.
Nationality: Polish=>pl; other country/foreigner=>cudzoziemiec. karta pobytu=>pobyt_czasowy (not ochrona unless PESEL UKR).
"""

def extract_turn(message: str, profile: dict, pending_question: str | None, pending_slots: list, call_llm) -> dict | None:
    """Return parsed extraction dict or None to signal regex fallback."""
    if os.getenv("EXTRACTOR_LLM", "").strip() != "1":
        return None
    if not message:
        return None
    sys = (
        "You extract structured info for a university-assistant dialogue. "
        + EXTRACT_SCHEMA_HINT
        + f"\nKnown profile: {profile}. Pending: {pending_question} (slots: {pending_slots})."
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
    if not isinstance(data, dict) or "intents" not in data:
        return None
    return data


def apply_extraction(state_profile: dict, data: dict, min_conf: float = 0.7) -> tuple[dict, list]:
    """Merge high-confidence slot_updates; return (profile, conflicts)."""
    prof = dict(state_profile or {})
    conflicts = list(data.get("conflicts") or [])
    updates = data.get("slot_updates") or {}
    for slot, body in updates.items():
        if not isinstance(body, dict):
            continue
        conf = float(body.get("confidence") or 0)
        if conf < min_conf:
            continue
        val = body.get("value")
        if slot == "drugi_kierunek" and isinstance(val, bool):
            val = "tak" if val else "nie"
        if slot in prof and prof[slot] != val:
            conflicts.append({"slot": slot, "old": prof[slot], "new": val})
            continue
        if val is not None:
            prof[slot] = val
    return prof, conflicts
