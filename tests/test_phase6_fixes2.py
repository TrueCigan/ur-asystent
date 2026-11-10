"""Offline checks for the rerun fixes. No network call to a paid model."""
from __future__ import annotations

import os
import sys
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ["EVAL_REAL"] = "0"
os.environ["SCENARIO_SOCIAL"] = "0"
os.environ["LLM_PROVIDER"] = "fake"
os.environ.pop("LLM_API_KEY", None)
os.environ.pop("LLM_THINKING", None)
os.environ.pop("ANSWER_MAX_TOKENS", None)

import answer_contract as ac  # noqa: E402
import phase4  # noqa: E402
import rag  # noqa: E402
from deadlines import notes_from_signed_deadlines  # noqa: E402
from facts import load_facts  # noqa: E402
from faq_fast import missing_faq_translations, try_fast_path  # noqa: E402


def test_text_blocks_ignore_thinking_and_haiku_disables_it():
    text = rag.anthropic_visible_text({
        "content": [
            {"type": "thinking", "thinking": "hidden"},
            {"type": "redacted_thinking", "data": "x"},
            {"type": "text", "text": "hello "},
            {"type": "text", "text": "there"},
        ]
    })
    assert text == "hello there"
    only = rag.anthropic_visible_text({"content": [{"type": "text", "text": "plain"}]})
    assert only == "plain"
    try:
        rag.anthropic_visible_text({"content": [{"type": "thinking", "thinking": "only"}]})
        raise AssertionError("expected format error")
    except rag.ModelFormatError:
        pass
    os.environ["LLM_MODEL"] = "claude-haiku-5-5"
    os.environ.pop("LLM_THINKING", None)
    fields = rag.thinking_fields("claude-haiku-5-5")
    assert fields["thinking"] == {"type": "disabled"}
    assert fields["output_config"]["effort"] == "high"
    os.environ["LLM_THINKING"] = "adaptive"
    assert rag.thinking_fields("claude-haiku-5-5") == {}
    os.environ.pop("LLM_THINKING", None)
    assert rag.thinking_fields("claude-sonnet-4-5") == {}


def test_format_errors_do_not_open_the_breaker():
    phase4.BREAKER.errors.clear()
    phase4.BREAKER.open_until = 0.0
    phase4.FORMAT_NOTES.clear()
    for _ in range(6):
        assert rag.record_model_failure(rag.ModelFormatError("no text block")) == "format"
    assert phase4.BREAKER.is_open() is False
    assert len(phase4.FORMAT_NOTES) == 6
    now = time.time()
    for _ in range(5):
        rag.record_model_failure(TimeoutError("Anthropic timeout"))
    assert phase4.BREAKER.is_open(now) is True
    phase4.BREAKER.errors.clear()
    phase4.BREAKER.open_until = 0.0


def test_wall_clock_timeout_stops_a_slow_body():
    class Slow(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            for _ in range(40):
                try:
                    self.wfile.write(b" ")
                    self.wfile.flush()
                except Exception:
                    return
                time.sleep(0.15)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        try:
            rag.post_with_deadline(f"http://127.0.0.1:{port}/", 0.4, json={"ping": 1})
            raise AssertionError("slow body was accepted")
        except Exception as exc:
            assert rag.is_transport_failure(exc), type(exc)
        elapsed = time.monotonic() - started
        assert elapsed < 2.0, elapsed
    finally:
        server.shutdown()


def test_deadline_warning_ignores_quotes_and_exam_dates():
    facts = load_facts()
    by_id = {fact.id: fact for fact in facts}
    quote = (
        "Kwaterowanie 30.09.2026. Egzamin 16.06.2026, 19.06.2026 i 12.09.2026. "
        "Plan zajęć 12.10.2026."
    )
    notes = notes_from_signed_deadlines([], "pl", date(2026, 11, 10))
    assert "minął" not in notes
    assert "30.09" not in notes
    assert "16.06" not in quote or "16.06" not in notes
    dorm = notes_from_signed_deadlines(
        [by_id["dorm_application_deadline"]], "pl", date(2026, 11, 10),
    )
    assert "15.05.2026" in dorm
    assert "30.09" not in dorm
    assert "16.06" not in dorm


def test_faq_english_drops_polish_prose_and_lists_missing_leads():
    answer = try_fast_path("Where do I submit a scholarship application?", "en")
    assert answer is not None
    text = answer["answer"]
    assert "elektronicznie" not in text
    assert "The application uses the channel" in text
    missing = missing_faq_translations()
    assert ("faq-income-group-2025-2026", "en") in missing
    assert ("faq-doctoral-period", "uk") in missing
    assert ("faq-cap-2026-2027", "en") in missing
    assert ("faq-cap-2025-2026", "uk") in missing
    assert ("faq-submission-channel", "en") not in missing


def test_dev_cases_answer_or_refuse_without_irrelevant_quotes():
    samples = {
        "Który temat opisuje świadczenie przy orzeczeniu o niepełnosprawności?": "niepełnospraw",
        "Which stored fact covers tuition for programmes in English?": "English",
        "Który limit socjalne plus rektora obowiązuje 15 stycznia 2026 wewnątrz roku akademickiego 2025/2026?": "3560",
    }
    for question, needle in samples.items():
        _topics, _prof, missing = rag.needed(question, "")
        assert missing == [], question
        result = rag.answer(question, [])
        assert result.get("clarify") is False, question
        assert needle.lower() in (result.get("answer") or "").lower(), question
    weather = rag.answer("Jaka będzie pogoda w Radomiu w weekend?", [])
    assert weather.get("mode") == "no_answer"
    assert "Filologia" not in (weather.get("answer") or "")
    medicine = rag.answer("Czy dostanę się na medycynę w tym roku?", [])
    assert medicine.get("mode") == "no_answer"
    assert "Nie mogę przewidzieć" in (medicine.get("answer") or "")
    dean = rag.answer("Jaki jest adres strony kontaktowej dziekanatu?", [])
    assert dean.get("mode") == "no_answer"
    assert "+48" not in (dean.get("answer") or "")
    assert "dziekanatu" in (dean.get("answer") or "")
    settings = ac.load_prompt_settings()
    assert settings["answer_max_tokens"] == 2000
    assert "120 words" in settings["answer_prompt"]
    assert "Russian" in settings["answer_prompt"]


def main():
    tests = [
        test_text_blocks_ignore_thinking_and_haiku_disables_it,
        test_format_errors_do_not_open_the_breaker,
        test_wall_clock_timeout_stops_a_slow_body,
        test_deadline_warning_ignores_quotes_and_exam_dates,
        test_faq_english_drops_polish_prose_and_lists_missing_leads,
        test_dev_cases_answer_or_refuse_without_irrelevant_quotes,
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
