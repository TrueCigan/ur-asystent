"""Phase 2 retrieval guards. No network, no holdout tuning, no live model."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ["EVAL_REAL"] = "0"
os.environ["SCENARIO_SOCIAL"] = "0"
os.environ.pop("LLM_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)

import adapters  # noqa: E402
import embed  # noqa: E402
import faq_fast  # noqa: E402
import hard_filter  # noqa: E402
import intent_code  # noqa: E402
import query_norm  # noqa: E402
import rag  # noqa: E402
import yaml  # noqa: E402


def test_normalize_keeps_negation_digits_dates_and_diacritics():
    raw = "  NIE\u2013składa   2026\u2013/2027  wczoraj  "
    got = query_norm.normalize_query(raw)
    assert got.original == raw
    assert "nie" in got.search
    assert "składa" in got.search
    assert "2026" in got.search
    assert "wczoraj" in got.search
    assert "\u2013" not in got.search
    composed = query_norm.normalize_query("a\u0301")
    assert composed.original == "a\u0301"
    assert composed.search == "á"


def test_hard_filters_run_before_limit_and_null_is_not_everyone():
    rows = [
        {"academic_year": None, "active": True, "revision": "2026-11-09", "name": "null-year"},
        {"academic_year": "2025/2026", "active": True, "revision": "2026-11-09", "name": "old"},
        {"academic_year": "2026/2027", "active": False, "revision": "2026-11-09", "name": "inactive"},
        {"academic_year": "2026/2027", "active": True, "revision": "other", "name": "old-rev"},
        {"academic_year": "2026/2027", "active": True, "revision": "2026-11-09", "valid_from": None, "valid_to": None, "name": "open"},
        {"academic_year": "2026/2027", "active": True, "revision": "2026-11-09", "valid_from": "2026-09-01", "valid_to": "2026-10-05", "name": "window"},
    ]
    decision = hard_filter.limit_after_filters(rows, 1, {
        "academic_year": "2026/2027",
        "active_revision": "2026-11-09",
        "as_of": "2026-10-01",
    })
    assert decision.status == "ok"
    assert [row["name"] for row in decision.rows] == ["window"]
    unknown = hard_filter.limit_after_filters(
        [{"faculty_id": None, "active": True, "name": "everyone"}],
        5,
        {"unknown_id": True, "faculty_id": "weif-1"},
    )
    assert unknown.status == "clarify"
    assert unknown.rows == []


def test_faq_path_makes_no_llm_or_embedding_call():
    calls = {"llm": 0, "embed": 0}

    def boom_llm(*_args, **_kwargs):
        calls["llm"] += 1
        raise AssertionError("llm")

    def boom_embed(*_args, **_kwargs):
        calls["embed"] += 1
        raise AssertionError("embed")

    adapters.complete = boom_llm
    embed.embed_texts = boom_embed
    hit = faq_fast.try_fast_path("Gdzie student składa wniosek o stypendium?", "pl")
    assert hit["mode"] == "faq"
    assert hit["faq_id"] == "faq-submission-channel"
    assert "Moje stypendia" in hit["answer"]
    assert calls == {"llm": 0, "embed": 0}
    answered = rag.answer("Gdzie student składa wniosek o stypendium?", [])
    assert answered["mode"] == "faq"
    assert calls == {"llm": 0, "embed": 0}


def test_unknown_faculty_ambiguous_alias_and_one_keyword():
    unknown = faq_fast.try_fast_path(
        "faculty_id: WEIF-1 Gdzie student składa wniosek o stypendium?",
        "pl",
    )
    assert unknown["mode"] == "clarify"
    assert unknown["faq_id"] is None
    yearless = faq_fast.try_fast_path("Do kiedy składa się wniosek o akademik?", "pl")
    assert yearless is None
    stated = faq_fast.try_fast_path(
        "What is the dorm application deadline for academic year 2026/2027?",
        "en",
    )
    assert stated["mode"] == "faq"
    assert "2026-05-15" in stated["answer"]
    assert faq_fast.try_fast_path("stypendium", "pl") is None
    assert faq_fast.heuristic(0.0, 1.0, 1.0) < faq_fast.CONFIDENCE_MIN
    negated = faq_fast.try_fast_path("Nie gdzie student składa wniosek o stypendium?", "pl")
    assert negated is None
    compound = faq_fast.try_fast_path(
        "Gdzie student składa wniosek o stypendium i czy to ten sam termin co akademik?",
        "pl",
    )
    assert compound is None
    relative = faq_fast.try_fast_path("Czy termin wniosku o akademik minął wczoraj?", "pl")
    assert relative is None

    catalog = {
        "revision": "2026-11-09",
        "entries": {
            "a": {"id": "a", "topic": "akademik", "fact_ids": [], "academic_year": None, "revision": "2026-11-09", "active": True, "lead": {"pl": "a"}},
            "b": {"id": "b", "topic": "erasmus", "fact_ids": [], "academic_year": None, "revision": "2026-11-09", "active": True, "lead": {"pl": "b"}},
        },
        "aliases": [
            {"entry": "a", "topic": "akademik", "lang": "pl", "search": "wspolny alias"},
            {"entry": "b", "topic": "erasmus", "lang": "pl", "search": "wspolny alias"},
        ],
    }
    assert faq_fast.try_fast_path("wspolny alias", "pl", catalog=catalog) is None
    intent = intent_code.parse_intent("program_id: NOT-A-REAL-ID")
    assert intent.unknown_id is True
    assert intent_code.known_ids("faculties") == set()
    assert intent_code.known_ids("programs") == set()


def test_year_caps_stay_separate_and_unsigned_facts_are_absent():
    new = faq_fast.try_fast_path(
        "Jaki jest łączny limit stypendium socjalnego i rektora w roku 2026/2027?",
        "pl",
    )
    old = faq_fast.try_fast_path(
        "Jaki jest łączny limit stypendium socjalnego i rektora w roku 2025/2026?",
        "pl",
    )
    assert new["faq_id"] == "faq-cap-2026-2027"
    assert old["faq_id"] == "faq-cap-2025-2026"
    assert "3667" in new["answer"]
    assert "3560" not in new["answer"]
    assert "3560" in old["answer"]
    assert "3667" not in old["answer"]
    assert "3556" not in old["answer"] and "3556" not in new["answer"]
    blob = (ROOT / "data" / "faq.yaml").read_text(encoding="utf-8")
    blob += (ROOT / "data" / "synonyms.yaml").read_text(encoding="utf-8")
    for banned in ("3556", "tuition_english", "disability_amounts"):
        assert banned not in blob
    period = faq_fast.try_fast_path("Na jaki okres obowiązuje stypendium doktoranckie?", "pl")
    assert period["faq_id"] == "faq-doctoral-period"
    assert "3570" not in period["answer"]
    rates = faq_fast.try_fast_path(
        "Jakie są miesięczne stawki Erasmus+ na studia w roku 2026/2027?",
        "pl",
    )
    assert "praktyki" in rates["answer"].lower() or "traineeship" in rates["answer"].lower() or "praktyk" in rates["answer"].lower()
    cases = yaml.safe_load((ROOT / "tests" / "phase0_cases.yaml").read_text(encoding="utf-8"))
    holdout = next(row["query"] for row in cases["cases"] if row["id"] == "p0-holdout-typo-01")
    assert holdout not in blob
    faq = yaml.safe_load((ROOT / "data" / "faq.yaml").read_text(encoding="utf-8"))
    synonyms = yaml.safe_load((ROOT / "data" / "synonyms.yaml").read_text(encoding="utf-8"))
    assert len(faq["entries"]) == 9
    assert len(synonyms["aliases"]) == 22


def test_search_applies_explicit_year_filter_without_embeddings():
    calls = {"embed": 0}

    def boom(*_args, **_kwargs):
        calls["embed"] += 1
        raise AssertionError("embed")

    embed.embed_texts = boom
    hits = rag.search("stypendium", k=3, profile={"hard_filters": {"academic_year": "2026/2027"}})
    assert hits == []
    assert calls["embed"] == 0


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as exc:
                failed += 1
                print("FAIL", name, type(exc).__name__, exc)
    print(f"\n{failed} failed")
    raise SystemExit(1 if failed else 0)
