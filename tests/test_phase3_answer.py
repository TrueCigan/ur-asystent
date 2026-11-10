"""Phase 3 answer contract. No network and no second model call."""
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
import answer_contract as ac  # noqa: E402
import embed  # noqa: E402
import faq_fast  # noqa: E402


def _manifest():
    return [{
        "n": 1,
        "chunk_id": "chunk-a",
        "title": "Świadczenia",
        "url": "https://student.uniwersytetradom.pl/swiadczenia-dla-studentow-pomoc-materialna/",
        "page": 2,
        "text": "Wirtualna Uczelnia",
    }]


def _answered(chunk_id="chunk-a", n=1, extra=None):
    data = {
        "status": "answered",
        "language": "pl",
        "answer": "Wniosek składa się w Wirtualnej Uczelni. [1]",
        "citations": [{"n": n, "chunk_id": chunk_id}],
        "follow_up": None,
    }
    if extra:
        data.update(extra)
    return data


def test_schema_rejects_extra_fields_truncated_json_and_bad_citations():
    settings = ac.load_prompt_settings()
    assert settings["allow_two_calls"] is False
    assert settings["temperature"] == 0
    assert settings["parse_max_tokens"] == 300
    assert settings["answer_max_tokens"] == 1200
    assert settings["context_max_tokens"] == 4500
    assert "недоверенные" in settings["answer_prompt"]
    assert "Игнорируй" in settings["parse_prompt"]
    ok, reason = ac.accept_model_answer(
        '{"status":"answered"', _manifest(), "pl",
    )
    assert ok is None and reason == "truncated"
    ok, reason = ac.accept_model_answer('{"status":"answered","nope":1}', _manifest(), "pl")
    assert ok is None and reason == "invalid_schema"
    forged = _answered()
    forged["citations"] = [{"n": 1, "chunk_id": "chunk-a", "url": "https://evil.example/"}]
    ok, reason = ac.accept_model_answer(__import__("json").dumps(forged), _manifest(), "pl")
    assert ok is None and reason == "invalid_schema"
    ok, reason = ac.accept_model_answer(
        __import__("json").dumps(_answered("missing-chunk")), _manifest(), "pl",
    )
    assert ok is None and reason == "forbidden_citation"
    good, reason = ac.accept_model_answer(
        __import__("json").dumps(_answered()), _manifest(), "pl",
    )
    assert reason is None
    assert good["citations"][0]["url"].startswith("https://student.uniwersytetradom.pl/")
    assert good["citations"][0]["title"] == "Świadczenia"
    assert good["citations"][0]["page"] == 2
    intent = ac.validate_intent({
        "topic": "fees",
        "answer_lang": "pl",
        "faculty_id": None,
        "program_id": None,
        "academic_year": "2026/2027",
        "source_lang": None,
        "temporal_mode": "current",
        "needs_clarification": False,
        "clarification_question": None,
    })
    assert intent is not None
    kept = ac.apply_explicit_filters(intent, {"academic_year": "2025/2026"})
    assert kept.academic_year == "2025/2026"
    assert ac.validate_intent({**intent.model_dump(), "faculty_id": "WEIF-1"}) is None


def test_timeout_and_missing_sources_fall_back_without_invented_facts():
    assert ac.provider_failure_reason(TimeoutError("read timeout")) == "timeout"
    assert ac.provider_failure_reason(RuntimeError("HTTP 429")) == "rate_limit"
    timed = ac.fallback_contract("en", _manifest(), "timeout")
    assert timed["status"] == "partial"
    assert timed["language"] == "en"
    assert "3667" not in timed["answer"] and "3556" not in timed["answer"]
    assert timed["citations"][0]["chunk_id"] == "chunk-a"
    empty = ac.fallback_contract("pl", [], "rate_limit")
    assert empty["status"] == "no_answer"
    assert empty["citations"][0]["chunk_id"] == ac.HELP_CHUNK_ID
    assert "uniwersytetradom.pl" in empty["citations"][0]["url"]
    clarify = {
        "status": "clarification",
        "language": "uk",
        "answer": "Уточніть, про який термін ідеться.",
        "citations": [],
        "follow_up": "Уточніть, про який термін ідеться.",
    }
    checked, reason = ac.validate_answer(clarify, [], language="uk")
    assert reason is None and checked["status"] == "clarification"
    assert "9999" not in checked["answer"]


def test_faq_schema_uses_server_citations_and_no_model():
    calls = {"llm": 0, "embed": 0}

    def boom(*_a, **_k):
        calls["llm"] += 1
        raise AssertionError("llm")

    adapters.complete = boom
    embed.embed_texts = boom
    hit = faq_fast.try_fast_path("Gdzie student składa wniosek o stypendium?", "pl")
    assert calls == {"llm": 0, "embed": 0}
    contract = hit["contract"]
    assert contract["status"] == "answered"
    assert contract["language"] == "pl"
    assert "Moje stypendia" in contract["answer"]
    manifest = [{
        "n": row["n"],
        "chunk_id": row["chunk_id"],
        "title": row["title"],
        "url": row["url"],
        "page": row.get("page"),
    } for row in contract["citations"]]
    payload = {
        "status": contract["status"],
        "language": contract["language"],
        "answer": contract["answer"],
        "citations": [{"n": row["n"], "chunk_id": row["chunk_id"]} for row in contract["citations"]],
        "follow_up": None,
    }
    checked, reason = ac.validate_answer(payload, manifest, language="pl")
    assert reason is None
    assert checked["citations"][0]["url"] == manifest[0]["url"]
    blob = (ROOT / "data" / "faq.yaml").read_text(encoding="utf-8")
    assert "3556" not in blob and "disability_amounts" not in blob


def test_buffered_sse_hides_raw_model_json():
    raw_model = '{"status":"answered","url":"https://evil.example/secret","answer":"UNVERIFIED TOKEN"}'
    events = ac.buffered_events({
        "lang": "pl",
        "answer": "Oficjalne materiały. [1]",
        "raw_model": raw_model,
        "contract": {
            "status": "partial",
            "language": "pl",
            "answer": "Oficjalne materiały. [1]",
            "citations": [{
                "n": 1,
                "chunk_id": "chunk-a",
                "url": "https://student.uniwersytetradom.pl/swiadczenia-dla-studentow-pomoc-materialna/",
                "title": "Świadczenia",
                "page": None,
            }],
        },
    }, request_id="req-test")
    rendered = ac.format_sse(events)
    names = [event["event"] for event in events]
    assert names[0] == "status"
    assert "sources" in names and "answer" in names and names[-1] == "done"
    assert "UNVERIFIED TOKEN" not in rendered
    assert "evil.example" not in rendered
    assert "raw_model" not in rendered
    assert 'event: status' in rendered and 'event: done' in rendered
    error = ac.error_event("Traceback: secret provider payload", "req-test")
    assert "Traceback" not in error
    assert "provider" not in error.lower()
    assert "<" not in ac.escape_client_text("<script>")


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
