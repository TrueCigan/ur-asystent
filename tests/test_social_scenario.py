"""Unit tests for verified social-scholarship scenario (no LLM)."""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

os.environ.pop("SCENARIO_SOCIAL", None)  # default off
os.environ.pop("FACTS_INJECT_UNVERIFIED", None)

from scenarios import social as S  # noqa: E402
from facts import income_group, load_facts  # noqa: E402


def _income_fact():
    return next(f for f in load_facts() if f.id == "social_income_threshold")


def test_flag_default_off():
    os.environ.pop("SCENARIO_SOCIAL", None)
    assert S.scenario_social_enabled() is False


def test_flag_on():
    os.environ["SCENARIO_SOCIAL"] = "1"
    assert S.scenario_social_enabled() is True
    os.environ.pop("SCENARIO_SOCIAL", None)


def test_card_no_llm_and_no_placeholders():
    card = S.build_card("pl")
    assert card["title"]
    assert card["amounts"]["groups"]
    assert card["amounts"]["academic_year"] == "2025/2026"
    assert card["dorm_topup"]["auto_included"] is False
    blob = str(card)
    assert "{{" not in blob
    assert "FACTS (" not in blob
    # Caps are period-separated, not auto-picked
    years = {c["academic_year"] for c in card["caps"]}
    assert "2025/2026" in years and "2026/2027" in years
    vals = {Decimal(str(c["value"])) for c in card["caps"]}
    assert Decimal("3560.60") in vals
    assert Decimal("3667.0") in vals or Decimal("3667") in vals


def test_card_i18n_uk_en():
    uk = S.build_card("uk")
    en = S.build_card("en")
    assert "Соціальн" in uk["title"] or "соціальн" in uk["title"].lower()
    assert "Social" in en["title"]


def test_group_boundaries_and_zero():
    fact = _income_fact()
    cases = [
        (Decimal("0.00"), "I", 1600.0),
        (Decimal("850.00"), "I", 1600.0),
        (Decimal("850.01"), "II", 1400.0),
        (Decimal("1200.00"), "II", 1400.0),
        (Decimal("1200.01"), "III", 1200.0),
        (Decimal("1550.00"), "III", 1200.0),
        (Decimal("1550.01"), "IV", 1000.0),
        (Decimal("1908.90"), "IV", 1000.0),
    ]
    for income, want_g, want_amt in cases:
        g, amt = income_group(income, fact.value)
        assert g == want_g, f"{income} → {g} want {want_g}"
        assert amt == want_amt


def test_estimate_zero_ok_dorm_not_in_total():
    r = S.estimate("0", academic_year="2025/2026", interested_in_dorm_topup=True, lang="pl")
    assert r["ok"] is True
    assert r["result"] == "amount_estimate"
    assert r["income_group"] == "I"
    assert r["base_amount"] == "1600.00"
    assert r["total_display_amount"] == "1600.00"
    assert r["conditional_dorm_topup"]["amount"] == "400.00"
    assert r["conditional_dorm_topup"]["included_in_total"] is False
    assert r["eligibility"] == "unknown"


def test_estimate_input_error_and_over_threshold():
    bad = S.estimate("-1", academic_year="2025/2026")
    assert bad["result"] == "input_error"
    over = S.estimate("1908.91", academic_year="2025/2026")
    assert over["result"] == "over_threshold"
    # 2026/2027 amounts not confirmed in FACTS table
    ny = S.estimate("1000", academic_year="2026/2027")
    assert ny["result"] == "amounts_not_confirmed"
    assert ny["ok"] is False


def test_estimate_dorm_included_only_when_conditions_true():
    r = S.estimate(
        "1100",
        academic_year="2025/2026",
        interested_in_dorm_topup=True,
        dorm_conditions_met=True,
    )
    assert r["ok"]
    assert r["income_group"] == "II"
    assert r["dorm_topup_included"] is True
    assert r["total_display_amount"] == "1800.00"


def test_chat_answer_no_placeholders():
    ans = S.format_chat_answer("uk")
    assert ans["mode"] == "scenario-social"
    assert "{{" not in ans["answer"]
    assert "FACTS (" not in ans["answer"]
    assert ans["lang"] == "uk"


def test_no_amount_duplication_in_scenario_yaml():
    import yaml
    raw = (ROOT / "data" / "scenarios" / "social_scholarship.yaml").read_text(encoding="utf-8")
    # scenario must reference facts, not embed 1600/1400 table
    data = yaml.safe_load(raw)
    assert data["fact_refs"]["income_and_amounts"] == "social_income_threshold"
    assert "1600" not in raw
    assert "1400" not in raw
    assert "3560" not in raw
    assert "3667" not in raw


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as e:
                failed += 1
                print("FAIL", name, "—", e)
    print(f"\n{failed} failed")
    sys.exit(min(failed, 100))
