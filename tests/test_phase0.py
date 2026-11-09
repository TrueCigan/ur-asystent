"""Phase 0 harness checks. No network and no live model."""
from __future__ import annotations

import inspect
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

os.environ["EVAL_REAL"] = "0"
os.environ["LLM_PROVIDER"] = "fake"
os.environ.pop("LLM_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)
os.environ["EMBEDDINGS_PROVIDER"] = "disabled"
os.environ["EMBED_PROVIDER"] = "disabled"
os.environ["SCENARIO_SOCIAL"] = "0"

import adapters  # noqa: E402
import clock  # noqa: E402
import phase0_eval  # noqa: E402
from facts import current_academic_year  # noqa: E402


def _boom(*_a, **_k):
    raise AssertionError("network call")


def test_eval_real_defaults_off_and_score_is_not_measured():
    os.environ["EVAL_REAL"] = "0"
    assert adapters.eval_real_enabled() is False
    cases = phase0_eval.load_cases()
    phase0_eval.validate(cases)
    assert phase0_eval.score_label(cases) == "not measured"
    assert len(phase0_eval.holdout_ids(cases)) == 10


def test_holdout_cannot_be_used_for_tuning():
    cases = phase0_eval.load_cases()
    phase0_eval.assert_allowed_for_tuning(["p0-dev-faq-01"], cases)
    try:
        phase0_eval.assert_allowed_for_tuning(["p0-holdout-faq-01"], cases)
    except RuntimeError as exc:
        assert "p0-holdout-faq-01" in str(exc)
    else:
        raise AssertionError("holdout id was accepted for tuning")


def test_fake_llm_modes_do_not_touch_the_network():
    import rag

    original = rag.httpx.post
    rag.httpx.post = _boom
    os.environ["LLM_PROVIDER"] = "fake"
    os.environ["EVAL_REAL"] = "0"
    try:
        for mode, expect in (
            ("ok", adapters._FAKE_OK),
            ("invalid_json", adapters._FAKE_INVALID),
            ("forbidden_citation", adapters._FAKE_FORBIDDEN),
        ):
            os.environ["FAKE_LLM_MODE"] = mode
            assert rag.call_llm([{"role": "user", "content": "x"}]) == expect
            assert adapters.complete([{"role": "user", "content": "x"}]) == expect
        for mode, code in (("timeout", "timeout"), ("429", "quota"), ("unavailable", "unavailable")):
            os.environ["FAKE_LLM_MODE"] = mode
            try:
                rag.call_llm([])
            except adapters.AdapterError as exc:
                assert exc.code == code
            else:
                raise AssertionError(f"{mode} did not fail closed")
        assert rag.llm_enabled() is False
    finally:
        rag.httpx.post = original
        os.environ["FAKE_LLM_MODE"] = "ok"
        os.environ["LLM_PROVIDER"] = "fake"


def test_real_provider_is_not_silently_faked():
    os.environ["LLM_PROVIDER"] = "anthropic"
    os.environ["LLM_API_KEY"] = "not-a-real-key"
    os.environ["EVAL_REAL"] = "0"
    try:
        assert adapters.production_llm_would_use_fake() is False
        try:
            adapters.complete([{"role": "user", "content": "do not send"}])
        except adapters.AdapterError as exc:
            assert exc.code == "unavailable"
        else:
            raise AssertionError("eval entry called a real provider")
    finally:
        os.environ["LLM_PROVIDER"] = "fake"
        os.environ.pop("LLM_API_KEY", None)


def test_embeddings_fake_are_isolated_and_real_is_blocked():
    import embed

    original = embed.httpx.post
    embed.httpx.post = _boom
    try:
        os.environ["EMBEDDINGS_PROVIDER"] = "fake"
        os.environ["EMBED_PROVIDER"] = "fake"
        rows = embed.embed_texts(["a", "a"])
        assert rows.shape == (2, adapters.FAKE_EMBED_DIM)
        assert adapters.FAKE_EMBED_DIM != 1536
        assert abs(float(rows[0] @ rows[0]) - 1.0) < 1e-5
        assert (rows[0] == rows[1]).all()
        os.environ["EMBEDDINGS_PROVIDER"] = "disabled"
        try:
            embed.embed_texts(["a"])
        except adapters.AdapterError as exc:
            assert exc.code == "unavailable"
        else:
            raise AssertionError("disabled embeddings ran")
        os.environ["EMBEDDINGS_PROVIDER"] = "gemini"
        os.environ["EMBED_PROVIDER"] = "gemini"
        os.environ["GEMINI_API_KEY"] = "not-a-real-key"
        os.environ["EVAL_REAL"] = "0"
        try:
            embed.embed_texts(["a"])
        except adapters.AdapterError as exc:
            assert exc.code == "unavailable"
        else:
            raise AssertionError("gemini embeddings called the network")
    finally:
        embed.httpx.post = original
        os.environ["EMBEDDINGS_PROVIDER"] = "disabled"
        os.environ["EMBED_PROVIDER"] = "disabled"
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ["EVAL_REAL"] = "0"


def test_warsaw_clock_does_not_replace_live_academic_year_helper():
    assert clock.academic_year("2026-09-30") == "2025/2026"
    assert clock.academic_year("2026-10-01") == "2026/2027"
    assert current_academic_year(date(2026, 9, 30)) == "2025/2026"
    assert current_academic_year(date(2026, 10, 1)) == "2026/2027"
    assert inspect.signature(current_academic_year).parameters["today"].default is None
    assert clock.offset_hours("2026-01-15T12:00:00") == 1
    assert clock.offset_hours("2026-07-15T12:00:00") == 2
    # 2026-03-29 is the spring-forward day. Noon is already CEST.
    assert clock.offset_hours("2026-03-29") == 2
    assert clock.offset_hours("2026-03-28T12:00:00") == 1
    winter = clock.as_of_datetime("2026-11-09")
    assert winter.tzinfo is not None
    assert winter.utcoffset().total_seconds() == 3600


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
