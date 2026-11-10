"""Offline checks for the live-eval fixes. No network and no holdout tuning."""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ["EVAL_REAL"] = "0"
os.environ["SCENARIO_SOCIAL"] = "0"
os.environ["LLM_PROVIDER"] = "fake"
os.environ.pop("LLM_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("LLM_SEND_TEMPERATURE", None)
os.environ.pop("ANSWER_TIMEOUT_S", None)
os.environ.pop("ANSWER_MAX_TOKENS", None)
os.environ.pop("ANSWER_BUDGET_S", None)
os.environ.pop("ANSWER_CONTEXT_CHUNKS", None)
os.environ.pop("ANSWER_CHUNK_CHARS", None)
os.environ.pop("ANSWER_FACT_CARDS", None)
os.environ.pop("ANSWER_CARD_CHARS", None)

import answer_contract as ac  # noqa: E402
import rag  # noqa: E402
from deadlines import parse_deadlines, render_deadline_notes  # noqa: E402
from facts import (  # noqa: E402
    fallback_facts,
    load_facts,
    render_facts_for_user,
    select_facts,
    strip_staff_contacts,
)


def test_haiku_request_omits_temperature():
    import httpx

    captured = {}
    original = httpx.post

    class Resp:
        status_code = 200
        headers = {}

        def json(self):
            return {"content": [{"text": "ok"}], "stop_reason": "end_turn"}

    def fake_post(url, *args, **kwargs):
        captured["url"] = url
        captured["body"] = kwargs["json"]
        return Resp()

    saved = {
        "LLM_PROVIDER": os.environ.get("LLM_PROVIDER"),
        "LLM_MODEL": os.environ.get("LLM_MODEL"),
        "LLM_API_KEY": os.environ.get("LLM_API_KEY"),
        "LLM_SEND_TEMPERATURE": os.environ.get("LLM_SEND_TEMPERATURE"),
    }
    httpx.post = fake_post
    try:
        os.environ["LLM_PROVIDER"] = "anthropic"
        os.environ["LLM_API_KEY"] = "offline-test-only"
        os.environ["LLM_MODEL"] = "claude-haiku-5-5"
        os.environ.pop("LLM_SEND_TEMPERATURE", None)
        rag.call_llm(
            [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
            temperature=0, timeout=1, max_tokens=20, retries=0,
        )
        assert captured["url"] == "https://api.anthropic.com/v1/messages"
        assert "temperature" not in captured["body"]
        assert captured["body"]["model"] == "claude-haiku-5-5"
        assert captured["body"]["thinking"] == {"type": "disabled"}
        assert captured["body"]["output_config"]["effort"] == "high"

        os.environ["LLM_MODEL"] = "claude-sonnet-4-5"
        rag.call_llm(
            [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
            temperature=0, timeout=1, max_tokens=20, retries=0,
        )
        assert captured["body"]["temperature"] == 0

        os.environ["LLM_SEND_TEMPERATURE"] = "0"
        rag.call_llm(
            [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
            temperature=0, timeout=1, max_tokens=20, retries=0,
        )
        assert "temperature" not in captured["body"]

        os.environ["LLM_MODEL"] = "claude-haiku-5-5"
        os.environ["LLM_SEND_TEMPERATURE"] = "1"
        rag.call_llm(
            [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
            temperature=0, timeout=1, max_tokens=20, retries=0,
        )
        assert captured["body"]["temperature"] == 0
    finally:
        httpx.post = original
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_timeout_tokens_and_context_defaults():
    settings = ac.load_prompt_settings()
    assert settings["answer_timeout_s"] == 12
    assert settings["answer_max_tokens"] == 2000
    assert settings["budget_s"] == 15
    assert settings["parse_timeout_s"] == 1
    assert settings["context_chunks"] == 3
    assert settings["chunk_chars"] == 400
    assert settings["fact_cards_max"] == 4
    assert settings["card_chars"] == 240
    assert settings["context_max_tokens"] == 4500
    assert rag.REQUEST_BUDGET_SEC >= settings["answer_timeout_s"]
    os.environ["ANSWER_TIMEOUT_S"] = "9"
    os.environ["ANSWER_MAX_TOKENS"] = "900"
    os.environ["ANSWER_CONTEXT_CHUNKS"] = "2"
    try:
        overridden = ac.load_prompt_settings()
        assert overridden["answer_timeout_s"] == 9
        assert overridden["answer_max_tokens"] == 900
        assert overridden["context_chunks"] == 2
    finally:
        os.environ.pop("ANSWER_TIMEOUT_S", None)
        os.environ.pop("ANSWER_MAX_TOKENS", None)
        os.environ.pop("ANSWER_CONTEXT_CHUNKS", None)


def test_fenced_json_is_parsed_and_truncation_is_rejected():
    fenced = """```json
{"status":"no_answer","language":"pl","answer":"Brak potwierdzonych danych [1].","citations":[{"n":1,"chunk_id":"help:swiadczenia"}],"follow_up":null}
```"""
    data, reason = ac.parse_json_object("  \n" + fenced + "\n")
    assert reason is None and data["status"] == "no_answer"
    bare = """```
{"status":"answered","language":"pl"}
```"""
    data, reason = ac.parse_json_object(bare)
    assert data is not None and reason is None
    data, reason = ac.parse_json_object("hello")
    assert data is None and reason == "invalid_schema"
    data, reason = ac.parse_json_object('{"status":"answered"')
    assert data is None and reason == "truncated"
    manifest = [{
        "n": 1,
        "chunk_id": "help:swiadczenia",
        "url": "https://student.uniwersytetradom.pl/swiadczenia-dla-studentow-pomoc-materialna/",
        "title": "Świadczenia",
        "page": None,
        "text": "",
    }]
    accepted, why = ac.accept_model_answer(fenced, manifest, "pl", stop_reason="end_turn")
    assert accepted is not None and why is None
    accepted, why = ac.accept_model_answer(fenced, manifest, "pl", stop_reason="max_tokens")
    assert accepted is None and why == "truncated"


def test_fallback_cards_phones_deadlines_and_year():
    facts = load_facts()
    erasmus = select_facts(facts, ["erasmus"], {}, question="Jak złożyć wniosek Erasmus?")
    shown = fallback_facts(erasmus, "Jak złożyć wniosek Erasmus?", ["erasmus"])
    assert 1 <= len(shown) <= 3
    assert all(fact.id != "erasmus_dwz_contact" for fact in shown)
    dumped = strip_staff_contacts(render_facts_for_user(erasmus, "pl"), "Jak złożyć wniosek Erasmus?")
    assert "+48" not in dumped
    assert "dabrowska" not in dumped.lower()
    contact = strip_staff_contacts(
        render_facts_for_user(erasmus, "pl"),
        "Jaki jest telefon do DWZ?",
    )
    assert "+48" in contact

    today = date(2026, 11, 10)
    checkin = render_deadline_notes(parse_deadlines(
        "Kwaterowanie 29.09–01.10.2026. Egzamin pisemny 03.03.2026. Plan zajęć 12.10.2026.",
        today,
    ), "pl", today)
    assert "minął" not in checkin
    application = render_deadline_notes(parse_deadlines(
        "Wniosek o akademik składa się do 15.05.2026.",
        today,
    ), "pl", today)
    assert "15.05.2026" in application
    assert "minął" in application

    later = "Jakie kwoty i grupy dochodu obowiązują w roku akademickim 2026/2027?"
    picked = select_facts(
        facts, ["stypendium_socjalne", "stypendium_rektora"], {}, question=later,
    )
    ids = {fact.id for fact in picked}
    assert "rector_social_cap_monthly_2025_2026" not in ids
    assert "social_income_threshold" not in ids
    assert "rector_social_cap_monthly" in ids
    earlier = (
        "Który limit socjalne plus rektora obowiązuje 15 stycznia 2026 "
        "wewnątrz roku akademickiego 2025/2026?"
    )
    picked = select_facts(
        facts, ["stypendium_socjalne", "stypendium_rektora"], {}, question=earlier,
    )
    ids = {fact.id for fact in picked}
    assert "rector_social_cap_monthly_2025_2026" in ids
    assert "rector_social_cap_monthly" not in ids
    rendered = render_facts_for_user(picked, "pl")
    assert "3556" not in rendered


def test_dev_questions_do_not_ask_status_again():
    samples = [
        "Czy doktorant szkoły doktorskiej może dostać stypendium rektora?",
        "rectors scholaship for a doctoral studnet",
        "Który limit socjalne plus rektora obowiązuje 15 stycznia 2026 wewnątrz roku akademickiego 2025/2026?",
        "Jakie są stawki Erasmus+ na wyjazd?",
        "Na jaki okres obowiązuje stypendium doktoranckie?",
    ]
    for question in samples:
        _topics, _prof, missing = rag.needed(question, "")
        assert "status" not in missing, question
    _topics, _prof, missing = rag.needed("Czy mogę dostać stypendium rektora?", "")
    assert "status" in missing


def main():
    tests = [
        test_haiku_request_omits_temperature,
        test_timeout_tokens_and_context_defaults,
        test_fenced_json_is_parsed_and_truncation_is_rejected,
        test_fallback_cards_phones_deadlines_and_year,
        test_dev_questions_do_not_ask_status_again,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
