"""Demo: social card + estimate with LLM off and flag on/off."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

# Force no LLM
for k in ("LLM_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
    os.environ.pop(k, None)
os.environ["LLM_PROVIDER"] = ""

from scenarios.social import (  # noqa: E402
    build_card, estimate, format_chat_answer, scenario_social_enabled,
)
import rag  # noqa: E402


def show(title, obj):
    print("\n===", title, "===")
    if isinstance(obj, dict):
        print(json.dumps(obj, ensure_ascii=False, indent=2)[:2500])
    else:
        print(obj)


def main():
    print("LLM enabled:", rag.llm_enabled())
    print("SCENARIO_SOCIAL default:", scenario_social_enabled())

    card = build_card("pl")
    show("CARD pl (excerpt)", {
        "title": card["title"],
        "year": card["amounts"]["academic_year"],
        "groups": card["amounts"]["groups"],
        "dorm_auto": card["dorm_topup"]["auto_included"],
        "caps": [{"year": c["academic_year"], "value": c["value"]} for c in card["caps"]],
        "checked": card.get("checked_at"),
    })

    for income, year in [("0", "2025/2026"), ("1200.01", "2025/2026"), ("2000", "2025/2026"), ("1000", "2026/2027")]:
        r = estimate(income, academic_year=year, interested_in_dorm_topup=True, lang="uk")
        show(f"ESTIMATE income={income} year={year}", {
            "result": r["result"],
            "ok": r["ok"],
            "group": r.get("income_group"),
            "base": r.get("base_amount_display"),
            "total": r.get("total_display"),
            "topup": (r.get("conditional_dorm_topup") or {}).get("amount_display"),
            "topup_in_total": (r.get("conditional_dorm_topup") or {}).get("included_in_total"),
            "message": r.get("message"),
        })

    os.environ["SCENARIO_SOCIAL"] = "1"
    print("\nSCENARIO_SOCIAL=1 → chat path")
    out = rag.answer("Jak dostać stypendium socjalne?", [], session_lang="pl")
    show("CHAT no-LLM", {
        "mode": out.get("mode"),
        "lang": out.get("lang"),
        "clarify": out.get("clarify"),
        "answer_head": (out.get("answer") or "")[:600],
        "has_placeholders": "{{" in (out.get("answer") or ""),
    })

    # Russian input → uk
    out_ru = rag.answer("Как получить социальную стипендию?", [], session_lang=None)
    show("CHAT ru→uk", {
        "lang": out_ru.get("lang"),
        "mode": out_ru.get("mode"),
        "answer_head": (out_ru.get("answer") or "")[:400],
    })

    os.environ.pop("SCENARIO_SOCIAL", None)
    out_off = rag.answer("Jak dostać stypendium socjalne?", [])
    show("CHAT flag OFF (legacy path mode)", {"mode": out_off.get("mode"), "clarify": out_off.get("clarify")})


if __name__ == "__main__":
    main()
