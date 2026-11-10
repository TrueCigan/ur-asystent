"""Offline checks for the rerun fixes. No network call to a paid model."""
from __future__ import annotations

import json
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
    assert "The application uses the channel" in text
    assert "Wirtualna Uczelnia" in text and "Moje stypendia" in text
    uk = try_fast_path("Куди подавати заяву на стипендію?", "uk")
    assert uk is not None
    assert "Wirtualna Uczelnia" in uk["answer"] and "Moje stypendia" in uk["answer"]
    missing = missing_faq_translations()
    assert ("faq-income-group-2025-2026", "en") in missing
    assert ("faq-doctoral-period", "uk") in missing
    assert ("faq-cap-2026-2027", "en") in missing
    assert ("faq-cap-2025-2026", "uk") in missing
    assert ("faq-submission-channel", "en") not in missing


def test_local_server_covers_text_errors_deadline_and_extractor():
    """Real 127.0.0.1 responses, including the HTTP 200 object call_llm reads."""
    from extract import extract_turn

    script = []

    class Local(BaseHTTPRequestHandler):
        def do_POST(self):
            spec = script.pop(0)
            if spec.get("slow"):
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
                return
            body = json.dumps(spec["body"]).encode("utf-8")
            self.send_response(spec["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("request-id", "local-req")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Local)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/v1/messages"
    saved = {
        "LLM_PROVIDER": os.environ.get("LLM_PROVIDER"),
        "LLM_API_KEY": os.environ.get("LLM_API_KEY"),
        "LLM_MODEL": os.environ.get("LLM_MODEL"),
        "EXTRACTOR_LLM": os.environ.get("EXTRACTOR_LLM"),
    }
    original = rag.post_with_deadline

    def via_local(remote, timeout_s, **kwargs):
        assert remote.startswith("https://api.anthropic.com/")
        return original(url, timeout_s, **kwargs)

    def call_local(messages, temperature=0, timeout=None, max_tokens=None, retries=0):
        return rag.call_llm(
            messages, temperature=temperature, timeout=timeout or 2,
            max_tokens=max_tokens or 200, retries=0,
        )

    try:
        rag.post_with_deadline = via_local
        os.environ["LLM_PROVIDER"] = "anthropic"
        os.environ["LLM_API_KEY"] = "offline-test-only"
        os.environ["LLM_MODEL"] = "claude-haiku-5-5"
        os.environ["EXTRACTOR_LLM"] = "1"
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]

        script.append({"status": 200, "body": {
            "content": [{"type": "text", "text": "plain answer"}],
            "stop_reason": "end_turn",
        }})
        direct = original(url, 2, json={"ping": 1})
        assert direct.status_code == 200
        assert direct.headers.get("request-id") == "local-req"
        assert direct.json()["content"][0]["text"] == "plain answer"

        script.append({"status": 200, "body": {
            "content": [{"type": "text", "text": "from call"}],
            "stop_reason": "end_turn",
        }})
        assert call_local(messages) == "from call"

        script.append({"status": 200, "body": {
            "content": [
                {"type": "thinking", "thinking": "hidden"},
                {"type": "text", "text": "visible"},
            ],
            "stop_reason": "end_turn",
        }})
        assert call_local(messages) == "visible"

        for status in (429, 500):
            script.append({"status": status, "body": {"error": status}})
            try:
                call_local(messages)
                raise AssertionError(f"HTTP {status} was accepted")
            except RuntimeError as exc:
                assert f"HTTP {status}" in str(exc)

        script.append({"slow": True})
        started = time.monotonic()
        try:
            call_local(messages, timeout=0.4)
            raise AssertionError("slow body was accepted")
        except RuntimeError as exc:
            assert "timeout" in str(exc).lower()
        assert time.monotonic() - started < 2.0

        script.append({"status": 200, "body": {
            "content": [
                {"type": "thinking", "thinking": "skip"},
                {"type": "text", "text": '{"intents":[],"slot_updates":{"status":"pl"},"conflicts":[]}'},
            ],
            "stop_reason": "end_turn",
        }})
        extracted = extract_turn("jestem studentem", {}, None, ["status"], call_local)
        assert extracted["slot_updates"]["status"] == "pl"
    finally:
        rag.post_with_deadline = original
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        server.shutdown()


def test_rerun2_schema_deadline_channel_and_clarifications():
    import json
    manifest = [{
        "n": 1, "chunk_id": "chunk-a",
        "url": "https://student.uniwersytetradom.pl/swiadczenia-dla-studentow-pomoc-materialna/",
        "title": "Świadczenia", "page": 2,
    }]
    draft = {
        "status": "answered",
        "answer": "Wniosek składa się w podanym kanale. [1]",
        "citations": [{
            "n": 1, "chunk_id": "chunk-a", "source_id": "src",
            "url": "https://evil.example/not-signed",
        }],
        "clarification_question": "który?",
        "unknown": "x",
        "unknowns": ["y"],
        "contact": "dziekanat",
    }
    accepted, reason = ac.accept_model_answer(json.dumps(draft), manifest, "pl")
    assert reason is None
    assert accepted["language"] == "pl"
    assert accepted["follow_up"] is None
    assert "evil.example" not in accepted["citations"][0]["url"]
    assert accepted["citations"][0]["chunk_id"] == "chunk-a"
    unbound = dict(draft, citations=[{"n": 1, "source_id": "only", "url": "https://evil.example/"}])
    rejected, why = ac.accept_model_answer(json.dumps(unbound), manifest, "pl")
    assert rejected is None and why == "forbidden_citation"
    settings = ac.load_prompt_settings()
    assert '"follow_up"' in settings["answer_prompt"]
    assert "chunk_id" in settings["answer_prompt"]

    dorm = rag.answer("Do kiedy składa się wniosek o akademik?", [])
    assert "domu studenckim" in (dorm.get("answer") or "")
    assert "15.05.2026" in (dorm.get("answer") or "")
    scholarship = rag.answer(
        "Który limit socjalne plus rektora obowiązuje 15 stycznia 2026 wewnątrz roku akademickiego 2025/2026?",
        [],
    )
    assert "15.05.2026" not in (scholarship.get("answer") or "")
    assert "wniosków o miejsce w domu studenckim" not in (scholarship.get("answer") or "")
    faculty = rag.answer("Pokaż zasady dla tego wydziału.", [])
    assert "15.05.2026" not in (faculty.get("answer") or "")
    assert "wniosków o miejsce w domu studenckim" not in (faculty.get("answer") or "")

    doctoral = rag.answer("Czy doktorant szkoły doktorskiej może dostać stypendium rektora?", [])
    assert "nie" in (doctoral.get("answer") or "").lower()
    english = rag.answer("rectors scholaship for a doctoral studnet", [])
    assert "no" in (english.get("answer") or "").lower()

    _topics, _prof, missing = rag.needed(
        "Czy data przepisu o wynagrodzeniu profesora ustala okres stypendium doktoranckiego?", "",
    )
    assert "status" not in missing
    _topics, _prof, missing = rag.needed("erazmus jak wyjechac na wymiane", "")
    assert missing == []
    _topics, _prof, missing = rag.needed("Czy mogę dostać stypendium rektora?", "")
    assert "status" in missing
    _topics, _prof, missing = rag.needed("Jak dostać stypendium socjalne?", "")
    assert "status" in missing


def test_citable_ids_match_the_manifest():
    import json
    fact_url = "https://student.uniwersytetradom.pl/domy-studenckie/"
    chunk_url = "https://student.uniwersytetradom.pl/swiadczenia-dla-studentow-pomoc-materialna/"
    rows = ac.assemble_citable(
        [{
            "id": "dorm_application_deadline",
            "title": "Termin wniosku o akademik",
            "url": fact_url,
            "text": "15.05.2026",
        }],
        [{"url": chunk_url, "title": "Świadczenia", "i": 2, "text": "fragment strony"}],
        chunk_n=1,
        chunk_chars=80,
    )
    assert [row["chunk_id"] for row in rows][0] == "dorm_application_deadline"
    assert rows[1]["chunk_id"].startswith("chunk-")
    assert rows[1]["chunk_id"] != chunk_url
    assert ac.stable_chunk_id({"url": chunk_url, "i": 2}) == rows[1]["chunk_id"]
    shown = [{"n": row["n"], "id": row["chunk_id"]} for row in rows]
    assert [item["id"] for item in shown] == [row["chunk_id"] for row in rows]

    def draft(n, cid, mark):
        return json.dumps({
            "status": "answered",
            "language": "pl",
            "answer": f"Termin jest w zatwierdzonym materiale. [{mark}]",
            "citations": [{"n": n, "chunk_id": cid}],
            "follow_up": None,
        })

    fact, reason = ac.accept_model_answer(draft(1, "dorm_application_deadline", 1), rows, "pl")
    assert reason is None
    assert fact["citations"][0]["url"] == fact_url
    assert "chunk_id" not in fact["citations"][0] or fact["citations"][0]["chunk_id"] == "dorm_application_deadline"
    chunk, reason = ac.accept_model_answer(draft(2, rows[1]["chunk_id"], 2), rows, "pl")
    assert reason is None
    assert chunk["citations"][0]["url"] == chunk_url
    rejected, why = ac.accept_model_answer(draft(1, "not-shown", 1), rows, "pl")
    assert rejected is None and why == "forbidden_citation"

    captured = {}

    def local_llm(messages, **_kwargs):
        payload = json.loads(messages[-1]["content"].split("\n\nReturn", 1)[0])
        captured["ids"] = payload["citable_ids"]
        cited = next(item for item in payload["citable_ids"] if item["id"] == "dorm_application_deadline")
        return draft(cited["n"], cited["id"], cited["n"])

    saved = {
        "LLM_PROVIDER": os.environ.get("LLM_PROVIDER"),
        "LLM_API_KEY": os.environ.get("LLM_API_KEY"),
        "LLM_MODEL": os.environ.get("LLM_MODEL"),
    }
    original = rag.call_llm
    try:
        os.environ["LLM_PROVIDER"] = "anthropic"
        os.environ["LLM_API_KEY"] = "offline-test-only"
        os.environ["LLM_MODEL"] = "claude-haiku-5-5"
        rag.call_llm = local_llm
        result = rag.answer("Podaj termin składania wniosku o dom studencki.", [])
    finally:
        rag.call_llm = original
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    assert captured["ids"], "prompt listed no citable ids"
    assert result.get("mode") == "answer-contract", result.get("llm_path")
    cited = (result.get("contract") or {}).get("citations") or []
    assert cited and cited[0]["chunk_id"] == "dorm_application_deadline"
    assert cited[0]["n"] == 1
    assert "[1]" in (result.get("contract") or {}).get("answer", "")
    assert cited[0]["url"].startswith("https://")
    prompt_ids = {item["id"] for item in captured["ids"]}
    assert "dorm_application_deadline" in prompt_ids
    assert all(not item["id"].startswith("http") for item in captured["ids"])


def test_probe_draft_is_renumbered_by_chunk_id():
    import json
    rows = ac.assemble_citable(
        [
            {"id": "dorm_prices", "title": "Ceny akademika", "url": "https://student.uniwersytetradom.pl/domy-studenckie/", "text": "ceny"},
            {"id": "dorm_application_deadline", "title": "Termin wniosku", "url": "https://student.uniwersytetradom.pl/domy-studenckie/", "text": "15.05.2026"},
            {"id": "submission_channel", "title": "Kanał", "url": "https://student.uniwersytetradom.pl/swiadczenia-dla-studentow-pomoc-materialna/", "text": "Wirtualna Uczelnia"},
        ],
        [
            {"url": "https://student.uniwersytetradom.pl/a", "title": "A", "i": 0, "text": "a"},
            {"url": "https://student.uniwersytetradom.pl/b", "title": "B", "i": 1, "text": "b"},
            {"url": "https://student.uniwersytetradom.pl/c", "title": "C", "i": 2, "text": "c"},
        ],
        chunk_n=3,
        chunk_chars=40,
    )
    assert [row["chunk_id"] for row in rows[:3]] == [
        "dorm_prices", "dorm_application_deadline", "submission_channel",
    ]
    draft = {
        "status": "answered",
        "language": "pl",
        "answer": "Termin [1]. Powtórzenie [2]. Kanał [3]. Poza listą [9].",
        "citations": [
            {"n": 1, "chunk_id": "dorm_application_deadline"},
            {"n": 2, "chunk_id": "dorm_application_deadline"},
            {"n": 3, "chunk_id": "submission_channel"},
        ],
        "follow_up": None,
    }
    accepted, reason = ac.accept_model_answer(json.dumps(draft), rows, "pl")
    assert reason is None
    assert [(item["n"], item["chunk_id"]) for item in accepted["citations"]] == [
        (1, "dorm_application_deadline"),
        (2, "submission_channel"),
    ]
    assert accepted["answer"] == "Termin [1]. Powtórzenie [1]. Kanał [2]. Poza listą ."
    assert accepted["citations"][0]["url"].startswith("https://student.uniwersytetradom.pl/")
    unknown = dict(draft, citations=[{"n": 1, "chunk_id": "not-shown"}])
    rejected, why = ac.accept_model_answer(json.dumps(unknown), rows, "pl")
    assert rejected is None and why == "forbidden_citation"
    prompt = ac.load_prompt_settings()["answer_prompt"]
    assert "submission_channel" in prompt
    assert "Numbering is done by the server" in prompt


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
        test_local_server_covers_text_errors_deadline_and_extractor,
        test_deadline_warning_ignores_quotes_and_exam_dates,
        test_faq_english_drops_polish_prose_and_lists_missing_leads,
        test_rerun2_schema_deadline_channel_and_clarifications,
        test_citable_ids_match_the_manifest,
        test_probe_draft_is_renumbered_by_chunk_id,
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
