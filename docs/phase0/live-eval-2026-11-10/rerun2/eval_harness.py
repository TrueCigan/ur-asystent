"""RERUN-2 harness (2026-11-10, commit 50a2fcd): transport-level guard (httpx.HTTPTransport.handle_request), httpx.post untouched so the app wall-clock deadline path runs; no request shims; caches cleared before runs 2-3.
Live 40-case eval harness for ur-asystent (local box, not production).

Runs the app in-process via FastAPI TestClient on /api/chat. Does not modify app code.
- Key: read from ANTHROPIC_API_KEY, passed in-process as LLM_API_KEY. Never printed or written.
- Spend guard: wraps httpx.post. Only https://api.anthropic.com/v1/messages is allowed; every other
  outbound POST is blocked. Before each call: refuse if call cap reached or if
  spent + worst-case cost of this call > budget. After each call: cost from real usage tokens.
- Records per call: HTTP status, request-id, usage tokens, latency, model text (kept), stop_reason.
"""
from __future__ import annotations
import datetime, json, os, sys, time
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(os.environ.get("UR_REPO", "/workspace/ur-eval"))
OUT = Path(os.environ.get("UR_OUT", "/workspace/ur-eval-raw/rerun2"))
MODEL = "claude-haiku-5-5"
# https://platform.claude.com/docs/en/about-claude/pricing (fetched 2026-11-10), prompts <=100K tokens
P_IN, P_OUT, P_CACHE_W, P_CACHE_R = 0.10, 0.50, 0.125, 0.01   # USD / 1M tokens
P_IN_LONG, P_OUT_LONG = 0.50, 2.50
BUDGET_USD = 2.00
MAX_CALLS = 160
PACE_S = 3.3   # app limiter: 20/min per network id

os.environ["LLM_PROVIDER"] = "anthropic"
os.environ["LLM_MODEL"] = MODEL
os.environ["EVAL_REAL"] = "1"
os.environ["LLM_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY", "")
assert os.environ["LLM_API_KEY"], "ANTHROPIC_API_KEY missing"
for k in ("GEMINI_API_KEY", "EMBED_API_KEY"):
    os.environ.pop(k, None)
sys.path.insert(0, str(REPO / "app"))

import httpx
CALLS: list[dict] = []
STATE = {"spent": 0.0, "blocked": [], "guard_stop": None, "case": None, "run": None}


def _cost(u: dict) -> float:
    inp = int(u.get("input_tokens") or 0); out = int(u.get("output_tokens") or 0)
    cw = int(u.get("cache_creation_input_tokens") or 0); cr = int(u.get("cache_read_input_tokens") or 0)
    long_ = (inp + cw + cr) > 100_000
    pi, po = (P_IN_LONG, P_OUT_LONG) if long_ else (P_IN, P_OUT)
    return (inp * pi + out * po + cw * P_CACHE_W + cr * P_CACHE_R) / 1e6


_real_handle = httpx.HTTPTransport.handle_request


def guarded_handle(self, request):
    """Transport-level guard. httpx.post stays the original object, so the app keeps its own
    wall-clock post_with_deadline path. The body is buffered here so usage can be read."""
    url = str(request.url)
    if not url.startswith("https://api.anthropic.com/v1/messages"):
        STATE["blocked"].append(url.split("?")[0])
        raise httpx.ConnectError("eval harness: outbound host blocked", request=request)
    try:
        body = json.loads(request.content.decode("utf-8"))
    except Exception:
        body = {}
    STATE.setdefault("temp_sent", 0); STATE.setdefault("temp_absent", 0)
    STATE["temp_sent" if "temperature" in body else "temp_absent"] += 1
    est_in = len(json.dumps(body, ensure_ascii=False)) // 2 + 100
    worst = (est_in * P_IN_LONG + int(body.get("max_tokens") or 1400) * P_OUT_LONG) / 1e6
    if len(CALLS) >= MAX_CALLS or STATE["spent"] + worst > BUDGET_USD:
        STATE["guard_stop"] = STATE["guard_stop"] or {"case": STATE["case"], "run": STATE["run"],
                                                      "calls": len(CALLS), "spent": STATE["spent"]}
        raise httpx.ConnectError("eval harness: budget guard", request=request)
    t0 = time.perf_counter()
    rec = {"case": STATE["case"], "run": STATE["run"], "model_req": body.get("model"),
           "max_tokens": body.get("max_tokens"), "temperature_sent": "temperature" in body,
           "thinking_sent": body.get("thinking"), "output_config_sent": body.get("output_config"),
           "read_timeout_s": (request.extensions.get("timeout") or {}).get("read"),
           "sys_head": str(body.get("system", ""))[:60]}
    try:
        r = _real_handle(self, request)
        r.read()
    except Exception as e:
        rec.update(http_status=None, error=type(e).__name__, latency_s=round(time.perf_counter() - t0, 3))
        STATE["spent"] += worst
        CALLS.append(rec); raise
    rec["latency_s"] = round(time.perf_counter() - t0, 3)
    rec["http_status"] = r.status_code
    rec["request_id"] = r.headers.get("request-id") or r.headers.get("x-request-id")
    try:
        d = json.loads(r.content.decode("utf-8"))
    except Exception:
        d = {}
    u = d.get("usage") or {}
    rec["usage"] = {k: u.get(k) for k in ("input_tokens", "output_tokens",
                                         "cache_creation_input_tokens", "cache_read_input_tokens")}
    rec["thinking_tokens"] = (u.get("output_tokens_details") or {}).get("thinking_tokens")
    rec["model_resp"] = d.get("model"); rec["stop_reason"] = d.get("stop_reason")
    rec["content_types"] = [c.get("type") for c in d.get("content", []) if isinstance(c, dict)]
    rec["thinking_block"] = any(t in ("thinking", "redacted_thinking") for t in rec["content_types"])
    if r.status_code == 200:
        rec["text"] = "".join(c.get("text", "") for c in d.get("content", []) if c.get("type") == "text")
    else:
        err = d.get("error") or {}
        rec["error_type"] = err.get("type"); rec["error_message"] = str(err.get("message", ""))[:500]
    c = _cost(u) if u else None
    rec["cost_usd"] = c
    if c is None and r.status_code == 200:
        STATE["spent"] += worst
    elif c:
        STATE["spent"] += c
    rec["verified_live"] = bool(r.status_code == 200 and rec["request_id"] and rec.get("text"))
    CALLS.append(rec)
    return r


httpx.HTTPTransport.handle_request = guarded_handle


def main():
    import yaml
    tz = ZoneInfo("Europe/Warsaw")
    started = datetime.datetime.now(tz)
    import subprocess
    sha = subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(REPO), "status", "--porcelain"], text=True).strip()
    from fastapi.testclient import TestClient
    import server, rag, phase4
    from answer_contract import load_prompt_settings
    ps = load_prompt_settings()
    settings = phase4.load_settings()
    client = TestClient(server.app)
    t = time.perf_counter(); hz = client.get("/healthz").json(); idx_load_s = time.perf_counter() - t
    meta = {
        "started_warsaw": started.isoformat(), "commit": sha, "worktree_dirty": bool(dirty),
        "index_revision": phase4.index_revision(), "chunks": hz.get("chunks"), "index_load_s": round(idx_load_s, 3),
        "settings_revision": settings.get("revision"), "faq_fingerprint": phase4.faq_fingerprint(),
        "prompt_version": ps["version"], "allow_two_calls": ps["allow_two_calls"],
        "answer_max_tokens": ps["answer_max_tokens"], "answer_timeout_s": ps["answer_timeout_s"],
        "budget_s": ps.get("budget_s"), "context_chunks": ps.get("context_chunks"), "chunk_chars": ps.get("chunk_chars"),
        "fact_cards_max": ps.get("fact_cards_max"), "card_chars": ps.get("card_chars"),
        "context_max_tokens": ps.get("context_max_tokens"),
        "env_overrides": {k: os.environ.get(k) for k in ("ANSWER_TIMEOUT_S","ANSWER_MAX_TOKENS","ANSWER_BUDGET_S","ANSWER_CONTEXT_CHUNKS","ANSWER_CHUNK_CHARS","ANSWER_FACT_CARDS","ANSWER_CARD_CHARS","LLM_SEND_TEMPERATURE","EXTRACTOR_LLM","LLM_THINKING")},
        "temperature": ps["temperature"], "model": MODEL, "provider": "anthropic",
        "extractor_llm_env": os.environ.get("EXTRACTOR_LLM"), "embeddings": "disabled",
        "price_source": "https://platform.claude.com/docs/en/about-claude/pricing (also claude.com/pricing), fetched 2026-11-10",
        "prices_usd_per_mtok": {"input": P_IN, "output": P_OUT, "cache_write": P_CACHE_W, "cache_read": P_CACHE_R},
        "budget_usd": BUDGET_USD, "max_calls": MAX_CALLS, "stand": "box local TestClient, not production",
        "status_endpoint": client.get("/api/status").json(),
    }
    # 1. smoke
    STATE["case"], STATE["run"] = "smoke", 0
    try:
        sm = rag.call_llm([{"role": "system", "content": "Reply with the single word OK."},
                           {"role": "user", "content": "ping"}], temperature=0, max_tokens=16, timeout=12, retries=0)
        meta["smoke"] = {"ok": True, "text": sm[:20]}
    except Exception as e:
        meta["smoke"] = {"ok": False, "error": type(e).__name__}
    meta["smoke"]["call"] = {k: CALLS[-1].get(k) for k in ("http_status", "request_id", "verified_live", "usage", "model_resp", "content_types", "stop_reason", "thinking_sent", "output_config_sent", "temperature_sent", "error_type", "error_message", "latency_s")} if CALLS else None
    if not meta["smoke"]["ok"] or not CALLS or not CALLS[-1].get("verified_live"):
        (OUT / "raw_results.json").write_text(json.dumps({"meta": meta, "calls": CALLS}, ensure_ascii=False, indent=1))
        print("SMOKE FAILED"); return
    cases = yaml.safe_load((REPO / "tests" / "phase0_cases.yaml").read_text())["cases"]
    results = []
    for c in cases:
        if STATE["guard_stop"]:
            break
        runs = []
        for run in (1, 2, 3):
            if STATE["guard_stop"]:
                break
            STATE["case"], STATE["run"] = c["id"], run
            if run > 1:
                with phase4.CACHE._lock: phase4.CACHE.store.clear()
                with phase4.INTENT_CACHE._lock: phase4.INTENT_CACHE.store.clear()
            n0 = len(CALLS)
            time.sleep(PACE_S)
            t = time.perf_counter()
            resp = client.post("/api/chat", json={"question": c["query"]})
            lat = time.perf_counter() - t
            try:
                body = resp.json()
            except Exception:
                body = {"_raw": resp.text[:500]}
            calls = CALLS[n0:]
            runs.append({
                "run": run, "http": resp.status_code, "latency_s": round(lat, 4),
                "cache": body.get("cache"), "mode": body.get("mode"), "clarify": body.get("clarify"),
                "lang": body.get("lang"), "answer": None,
                "answer_same_as_run1": (body.get("answer") == runs[0].get("answer_full")) if runs else None,
                "answer_full": body.get("answer"),
                "sources": [{"title": s.get("title"), "url": s.get("url")} if isinstance(s, dict) else s
                            for s in (body.get("sources") or [])],
                "contract_status": (body.get("contract") or {}).get("status"),
                "llm_path": body.get("llm_path"), "topics": body.get("topics"),
                "model_calls": len(calls), "call_ids": [x.get("request_id") for x in calls],
                "call_status": [x.get("http_status") for x in calls],
                "call_sys_heads": [x.get("sys_head") for x in calls],
                "verified_live_calls": sum(1 for x in calls if x.get("verified_live")),
                "model_texts": [x.get("text") for x in calls],
                "stop_reasons": [x.get("stop_reason") for x in calls],
                "thinking_blocks": [x.get("thinking_block") for x in calls],
                "call_latency_s": [x.get("latency_s") for x in calls],
                "detail": body.get("detail"),
            })
        results.append({"id": c["id"], "split": c["split"], "category": c["category"], "query": c["query"],
                        "filters": c.get("filters"), "expected_status": c["expected_status"],
                        "required_facts": c["required_facts"], "facts_approved": c["facts_approved"],
                        "runs": runs})
        r1 = runs[0] if runs else {}
        print(c["id"], r1.get("http"), r1.get("mode"), r1.get("cache"), "calls", r1.get("model_calls"),
              "lat", r1.get("latency_s"), "spent", round(STATE["spent"], 5), flush=True)
    meta["finished_warsaw"] = datetime.datetime.now(tz).isoformat()
    meta["spent_usd"] = STATE["spent"]; meta["guard_stop"] = STATE["guard_stop"]
    meta["temperature_sent_calls"] = STATE.get("temp_sent", 0)
    meta["temperature_absent_calls"] = STATE.get("temp_absent", 0)
    meta["cache_bypass"] = "phase4.CACHE.store and phase4.INTENT_CACHE.store cleared in-process before runs 2 and 3 (same warm process)"
    meta["breaker_state_end"] = repr(getattr(phase4.BREAKER, "__dict__", {}))[:300]
    meta["blocked_hosts"] = STATE["blocked"]; meta["total_calls"] = len(CALLS)
    meta["verified_live_calls"] = sum(1 for x in CALLS if x.get("verified_live"))
    (OUT / "raw_results.json").write_text(json.dumps({"meta": meta, "calls": CALLS, "results": results},
                                                     ensure_ascii=False, indent=1))
    print("DONE calls", len(CALLS), "spent", STATE["spent"], "guard", STATE["guard_stop"])


if __name__ == "__main__":
    main()
