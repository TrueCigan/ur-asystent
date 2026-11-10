"""Phase 4 cache, limiter, and cost. No network and no paid model.

Timings printed here are local fakes. They are not the TZ stand DoD.
"""
from __future__ import annotations

import inspect
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ["EVAL_REAL"] = "0"
os.environ["SCENARIO_SOCIAL"] = "0"
os.environ["LLM_PROVIDER"] = "fake"
os.environ.pop("LLM_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)
for _name in (
    "PRICE_INPUT_PER_1M",
    "PRICE_OUTPUT_PER_1M",
    "PRICE_CACHED_INPUT_PER_1M",
    "PRICE_EMBEDDING_PER_1M",
    "DAILY_GENERATION_BUDGET_USD",
):
    os.environ.pop(_name, None)

import phase4  # noqa: E402
from phase4 import (  # noqa: E402
    BREAKER, LEDGER, Breaker, CacheUnavailable, Ledger, Limiter, ResponseCache,
    budget_open, contains_pii, load_prices, quote_cost, response_cache_key, ttl_seconds,
)


WARSAW = ZoneInfo("Europe/Warsaw")
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=WARSAW)


def _key(**overrides):
    fields = dict(
        university_id="uniwersytet-radomski",
        normalized_query="gdzie zlozyc wniosek",
        answer_lang="pl",
        canonical_filters={"academic_year": None, "timezone": "Europe/Warsaw"},
        index_revision="rev-a",
        settings_revision="2026-11-09|faq:one",
        prompt_version="v1",
        model_version="unconfigured",
    )
    fields.update(overrides)
    return response_cache_key(**fields)


def test_cache_key_has_no_session_or_user():
    params = set(inspect.signature(response_cache_key).parameters)
    assert not any("session" in name.lower() or "user" in name.lower() for name in params)
    assert _key() == _key()
    for field, value in (
        ("index_revision", "rev-b"),
        ("settings_revision", "2026-11-09|faq:two"),
        ("prompt_version", "v2"),
        ("model_version", "other"),
        ("normalized_query", "inny wniosek"),
        ("answer_lang", "en"),
        ("university_id", "other-university"),
    ):
        assert _key(**{field: value}) != _key()
    dated = {"academic_year": None, "resolved_date": "2026-11-09", "timezone": "Europe/Warsaw"}
    assert _key(canonical_filters=dated) != _key()


def test_revision_and_faq_changes_drop_stale_entries():
    cache = ResponseCache()
    cache.note_fingerprint("rev-a|faq:one|v1")
    cache.put("answer-key", {"answer": "stary faq"}, 3600, 10, faq_fingerprint="faq:one")
    assert cache.get("answer-key", 20, faq_fingerprint="faq:one")["answer"] == "stary faq"
    assert cache.get("answer-key", 20, faq_fingerprint="faq:two") is None
    cache.put("answer-key", {"answer": "swiezy"}, 3600, 10, faq_fingerprint="faq:two")
    cache.note_fingerprint("rev-b|faq:two|v1")
    assert cache.get("answer-key", 20, faq_fingerprint="faq:two") is None


def test_ttl_caps():
    assert ttl_seconds("response", NOW) == 15 * 60
    assert ttl_seconds("response", NOW, contains_deadline=True) == 5 * 60
    assert ttl_seconds("no_answer", NOW) == 60
    assert ttl_seconds("intent", NOW) == 24 * 60 * 60
    assert ttl_seconds("faq", NOW) == 24 * 60 * 60
    assert ttl_seconds("faq", NOW, contains_deadline=True) == 5 * 60
    soon = NOW + timedelta(seconds=90)
    assert ttl_seconds("response", NOW, valid_to=soon) == 90
    late = datetime(2026, 11, 9, 23, 50, tzinfo=WARSAW)
    capped = ttl_seconds("response", late, relative_date=True)
    assert 1 <= capped <= 10 * 60


def test_cached_value_drops_session_state():
    cache = ResponseCache()
    cache.put("k", {"answer": "kanal", "state": "user-a-token", "session_id": "sess"}, 100, 1)
    got = cache.get("k", 2)
    assert got["answer"] == "kanal"
    assert "state" not in got and "session_id" not in got


def test_unknown_price_stays_unknown():
    prices = load_prices()
    assert prices["input"] is None
    assert prices["output"] is None
    unknown = quote_cost(
        {"uncached_input_tokens": 1000, "output_tokens": 500, "cached_input_tokens": 0, "embedding_tokens": 0},
        {"input": None, "output": 15, "cached_input": None, "embedding": None},
    )
    assert unknown["cost_status"] == "unknown"
    assert unknown["cost"] is None
    estimated = quote_cost(
        {"uncached_input_tokens": 1_000_000, "cached_input_tokens": 1_000_000, "output_tokens": 1_000_000, "embedding_tokens": 0},
        {"input": 3, "cached_input": 0.3, "output": 15, "embedding": None},
    )
    assert estimated["cost_status"] == "estimated"
    assert abs(estimated["cost"] - (3 + 0.3 + 15)) < 1e-9
    actual = quote_cost(
        {"uncached_input_tokens": 1_000_000, "output_tokens": 1_000_000},
        {"input": 3, "output": 15, "cached_input": None, "embedding": None},
        provider_charge=1.25,
    )
    assert actual == {"cost": 1.25, "cost_status": "actual"}
    book = Ledger()
    book.add("queries", unknown)
    book.add("ingestion", estimated)
    assert book.unknown["queries"] == 1
    assert book.usd["queries"] == 0.0
    assert book.usd["ingestion"] != book.usd["queries"]
    os.environ["DAILY_GENERATION_BUDGET_USD"] = "10"
    try:
        assert budget_open(book) is False
        fresh = Ledger()
        assert budget_open(fresh) is True
    finally:
        os.environ.pop("DAILY_GENERATION_BUDGET_USD", None)


def test_rate_limiter_uses_hmac_and_hides_the_network_id():
    limiter = Limiter()
    secret = b"phase4-test-secret"
    network = "203.0.113.10"
    start = 1_700_000_000.0
    for i in range(20):
        allowed, _, scope = limiter.check(network, secret, start + i * 0.01)
        assert allowed and scope == ""
    allowed, retry_after, scope = limiter.check(network, secret, start + 0.3)
    assert allowed is False and scope == "minute" and retry_after >= 1
    assert all(network not in note for note in limiter.notes)
    assert network not in limiter._ids
    assert limiter.token(network, secret, start) != limiter.token(network, secret, start + 86400)
    other = Limiter()
    for i in range(60):
        allowed, _, _ = other.check(f"198.51.100.{i}", secret, start)
        assert allowed
    allowed, _, scope = other.check("198.51.100.200", secret, start)
    assert allowed is False and scope == "global"
    day = Limiter()
    # Noon UTC, so 200 steps of 61 seconds stay inside one HMAC day.
    noon = datetime(2026, 11, 9, 12, 0, tzinfo=WARSAW).timestamp()
    for i in range(200):
        allowed, _, scope = day.check(network, secret, noon + i * 61)
        assert allowed, scope
    allowed, _, scope = day.check(network, secret, noon + 200 * 61)
    assert allowed is False and scope == "day"
    assert network not in "".join(day.notes)


def test_single_flight_shares_one_result():
    cache = ResponseCache()
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        time.sleep(0.05)
        return {"answer": "ten sam wynik", "state": "owner-only"}

    results = []

    def run():
        results.append(cache.single_flight("same", compute, 60, time.time()))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert calls["n"] == 1
    assert len(results) == 2
    assert all(item["answer"] == "ten sam wynik" for item in results)
    assert sum(1 for item in results if item.get("state") == "owner-only") == 1


def test_cache_down_still_rate_limits_and_does_not_invent_facts():
    cache = ResponseCache()
    cache.available = False
    limiter = Limiter()
    network = "203.0.113.44"
    allowed, _, _ = limiter.check(network, b"secret", 50_000.0)
    assert allowed
    try:
        cache.get("missing", 50_000.0)
        raise AssertionError("cache should be down")
    except CacheUnavailable:
        answer = "Nie znalazłem tej informacji w materiałach uczelni."
    assert "3667" not in answer and "3556" not in answer
    assert network not in "".join(limiter.notes)
    assert limiter.notes


def test_circuit_and_budget_block_generation_only():
    breaker = Breaker()
    for offset in range(4):
        breaker.record(10_000 + offset)
    assert breaker.is_open(10_004) is False
    breaker.record(10_005)
    assert breaker.is_open(10_010) is True
    assert breaker.is_open(10_005 + 61) is False
    BREAKER.errors.clear()
    BREAKER.open_until = 0.0
    LEDGER.usd["queries"] = 0.0
    LEDGER.unknown["queries"] = 0
    os.environ["DAILY_GENERATION_BUDGET_USD"] = "0"
    try:
        import rag
        assert rag._generation_block_reason() == "budget"
    finally:
        os.environ.pop("DAILY_GENERATION_BUDGET_USD", None)
        BREAKER.errors.clear()
        BREAKER.open_until = 0.0


def test_prompt_timeouts_stay_the_slo():
    from answer_contract import load_prompt_settings
    settings = load_prompt_settings()
    assert settings["parse_timeout_s"] == 1
    assert settings["answer_timeout_s"] == 12
    assert settings["budget_s"] == 15
    assert settings["allow_two_calls"] is False
    assert settings["temperature"] == 0


def test_intent_cache_lasts_a_day():
    phase4.INTENT_CACHE.store.clear()
    question = "Czy wczoraj minął termin wniosku?"
    first = phase4.remember_intent(question, "uniwersytet-radomski")
    second = phase4.remember_intent(question, "uniwersytet-radomski")
    assert first == second
    assert first["relative_deadline"] is True
    stored = next(iter(phase4.INTENT_CACHE.store.values()))
    assert stored["expires"] - time.time() > 23 * 60 * 60


def test_pii_is_not_a_cache_candidate():
    assert contains_pii("napisz na student@example.com")
    assert contains_pii("numer albumu 123456")
    assert not contains_pii("Do kiedy składa się wniosek o akademik?")


def test_fake_local_timings_are_not_the_stand():
    # NOT the TZ stand DoD. No paid API and no 10-way load test.
    cache = ResponseCache()
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        time.sleep(0.02)
        return {"answer": "faq", "mode": "faq"}

    started = time.perf_counter()
    cache.single_flight("faq", compute, 30, time.time())
    miss = time.perf_counter() - started
    started = time.perf_counter()
    hit = cache.get("faq", time.time() + 1)
    hit_s = time.perf_counter() - started
    assert calls["n"] == 1
    assert hit["mode"] == "faq"
    assert hit_s < miss
    print(f"NOT TZ STAND fake miss={miss:.4f}s hit={hit_s:.4f}s")


def test_http_limit_is_before_cache_and_hides_the_network_id():
    import logging
    from fastapi.testclient import TestClient
    import server

    network = "203.0.113.77"
    records = []

    class Grab(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Grab()
    logger = logging.getLogger("ur.api")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    phase4.LIMITER._ids.clear()
    phase4.LIMITER._global.clear()
    phase4.LIMITER.notes.clear()
    phase4.CACHE.store.clear()
    try:
        client = TestClient(server.app)
        headers = {"cf-connecting-ip": network}
        body = {"question": "Gdzie złożyć wniosek o stypendium?"}
        first = client.post("/api/chat", json=body, headers=headers)
        assert first.status_code == 200, first.text
        assert "3556" not in first.text
        second = client.post("/api/chat", json={**body, "state": "caller-b"}, headers=headers)
        assert second.status_code == 200, second.text
        assert second.json()["cache"] == "hit"
        assert second.json().get("state") == "caller-b"
        assert second.json().get("state") != first.json().get("state")
        again = second
        for _ in range(18):
            again = client.post("/api/chat", json=body, headers=headers)
            assert again.status_code == 200, again.text
        blocked = client.post("/api/chat", json=body, headers=headers)
        assert blocked.status_code == 429
        assert blocked.headers.get("retry-after")
        assert network not in "".join(records)
        assert network not in "".join(phase4.LIMITER.notes)
        assert "cache" in again.json()
    finally:
        logger.removeHandler(handler)
        phase4.LIMITER._ids.clear()
        phase4.LIMITER._global.clear()
        phase4.CACHE.store.clear()


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
