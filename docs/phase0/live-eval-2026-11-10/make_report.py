import json, re, math
RAW = "/workspace/ur-eval-raw/raw_results.json"
OUT = "/workspace/ur-eval-out"
d = json.load(open(RAW)); m = d["meta"]; calls = d["calls"]; res = d["results"]
S = json.load(open(f"{OUT}/manual_scores.json"))
CRIT = {}
def crit(cid, why): CRIT.setdefault(cid, []).append(why)
for r in res:
    a = r["runs"][0]["answer_full"] or ""
    if "Ten termin (29.09.2026) już minął" in a:
        crit(r["id"], "misstated deadline: check-in 29.09.2026 shown as '⚠️ Ten termin (29.09.2026) już minął' (owner-signed: not an application deadline)")
    if "3556" in a: crit(r["id"], "3556 used")
crit("p0-dev-deadline-03", "misstated deadline: exam-session dates 16.06.2026 / 12.09.2026 shown as 'Ten termin … już minął' for an unnamed deadline")
crit("p0-holdout-deadline-01", "hard-filter violation: 2026/2027-scoped question shows 2025/2026 amounts ('Limit socjalne+rektora (2025/2026): 3560.6', 2025/2026 group table)")
def pct(xs, p):
    xs = sorted(xs); 
    if not xs: return None
    k = max(0, math.ceil(p / 100 * len(xs)) - 1); return xs[k]
cold_model, cold_fast, warm_all, warm_model_cases, warm_fast_cases = [], [], [], [], []
for r in res:
    r1 = r["runs"][0]; is_model = r1["model_calls"] > 0
    (cold_model if is_model else cold_fast).append(r1["latency_s"])
    for x in r["runs"][1:]:
        warm_all.append(x["latency_s"]); (warm_model_cases if is_model else warm_fast_cases).append(x["latency_s"])
all_lat = [x["latency_s"] for r in res for x in r["runs"]]
hits = sum(1 for r in res for x in r["runs"] if x["cache"] == "hit"); nreq = sum(len(r["runs"]) for r in res)
faq = sum(1 for r in res if r["runs"][0]["mode"] == "faq")
case_calls = [c for c in calls if c["case"] != "smoke"]
live = [c for c in calls if c.get("verified_live")]
tok = {k: sum((c.get("usage") or {}).get(k) or 0 for c in calls) for k in ("input_tokens","output_tokens","cache_creation_input_tokens","cache_read_input_tokens")}
unknown_usage = [c for c in calls if c.get("http_status") is None]
cost_known = sum(c.get("cost_usd") or 0 for c in calls)
ub_unknown = sum((7300*0.10 + 700*0.50)/1e6 for _ in unknown_usage)
answer_calls = [c for c in case_calls if "помощник" in (c.get("sys_head") or "")]
extract_calls = [c for c in case_calls if "extract" in (c.get("sys_head") or "")]
model_answered = [r["id"] for r in res if (r["runs"][0]["llm_path"] or {}).get("kind") == "model"]
cats = {}
rows = []
for r in res:
    s = S[r["id"]]; score = sum(s[:4]); r1 = r["runs"][0]
    cats.setdefault(r["category"], [0, 0, 0, 0]);  c = cats[r["category"]]
    c[0] += 1; c[1] += score == 4
    if r["split"] == "holdout": c[2] += 1; c[3] += score == 4
    p = r1["llm_path"] or {}
    rows.append((r, score, r1, p))
dev_pass = sum(1 for r, s, *_ in rows if r["split"] == "dev" and s == 4)
ho_pass = sum(1 for r, s, *_ in rows if r["split"] == "holdout" and s == 4)
f = lambda v: "n/a" if v is None else f"{v*1000:.0f} ms" if v < 10 else f"{v:.2f} s"
L = []
w = L.append
w("# 40-case live eval report (Phase 6, run 1)\n")
w("Live run on the box (local FastAPI TestClient → /api/chat), not production. Not a launch approval. No merge, no deploy, no push. No 10-concurrent load test.\n")
w(f"Commit / dataset / index / settings / prompt / model / date / stand: `{m['commit']}` (branch cursor/phase-0-harness-ac61, clean worktree) / tests/phase0_cases.yaml v1 (40 cases, owner review 2026-11-09) / index `{m['index_revision']}` ({m['chunks']} chunks) / settings `{m['settings_revision']}` + faq `{m['faq_fingerprint']}` / prompt `{m['prompt_version']}` (temperature {m['temperature']}, answer_max_tokens {m['answer_max_tokens']}, answer_timeout_s {m['answer_timeout_s']}, allow_two_calls {m['allow_two_calls']}) / `{m['model']}` via Anthropic Messages API / {m['started_warsaw']} → {m['finished_warsaw']} (Europe/Warsaw) / box TestClient\n")
w("Mode: real (EVAL_REAL=1). Embeddings: disabled. Budget agreed: yes ($2.00 cap, owner, 2026-11-10). EXTRACTOR_LLM unset (app default ON).\n")
w(f"Harness compatibility shim: `claude-haiku-5-5` rejects `temperature` (HTTP 400 \"`temperature` is deprecated for this model\"). app/rag.py always sends it, so the harness transport wrapper dropped it on {m['temperature_stripped_calls']} calls (requested value {m['temperature_values_requested']}). App code unchanged. Without this, every model call is a 400 and every answer is a fallback.\n")
w("Case `filters` from the YAML were not sent: /api/chat has no filters field. Years and dates reach the app only through the question text.\n")
w("| metric | value |\n|---|---|")
w(f"| Pass dev / holdout | **{dev_pass}/30** / **{ho_pass}/10** (total {dev_pass+ho_pass}/40; target ≥36/40 and ≥9/10: NOT met) |")
w(f"| Critical failures | **{len(CRIT)} cases** (see list) |")
w(f"| Answers authored by the model (llm_path.kind=model) | **{len(model_answered)}/40** |")
w(f"| Overall p50 / p95 (all {len(all_lat)} requests) | {f(pct(all_lat,50))} / {f(pct(all_lat,95))} |")
w(f"| Cold (run 1, cache miss) p50 / p95, model path (n={len(cold_model)}) | {f(pct(cold_model,50))} / {f(pct(cold_model,95))} |")
w(f"| Cold p50 / p95, no-call path: FAQ/security/clarification (n={len(cold_fast)}) | {f(pct(cold_fast,50))} / {f(pct(cold_fast,95))} |")
w(f"| Warm (runs 2–3) p50 / p95, all (n={len(warm_all)}, all cache hits) | {f(pct(warm_all,50))} / {f(pct(warm_all,95))} |")
w(f"| Warm p50 / p95 for cases whose run 1 called the model (n={len(warm_model_cases)}) | {f(pct(warm_model_cases,50))} / {f(pct(warm_model_cases,95))} |")
w(f"| Input / output / embedding tokens | {tok['input_tokens']} / {tok['output_tokens']} / 0 (cache write {tok['cache_creation_input_tokens']}, read {tok['cache_read_input_tokens']}); usage unknown for {len(unknown_usage)} timed-out calls |")
w(f"| Cost actual / estimated | provider charge: not read (no billing access). Estimate from returned usage × published price: **${cost_known:.5f}**. {len(unknown_usage)} timed-out calls: usage unknown, upper-bound estimate ≤ ${ub_unknown:.4f} if billed. Total ≤ ${cost_known+ub_unknown:.4f}. |")
w(f"| FAQ% / cache hit% | FAQ fast path {faq}/40 = {faq/40:.0%} of unique cases / cache hits {hits}/{nreq} requests = {hits/nreq:.0%} (every run 2–3 hit; every run 1 missed) |")
w(f"| Model calls | {len(calls)} total = 1 smoke + {len(case_calls)} case calls ({len(extract_calls)} slot-extractor, {len(answer_calls)} answer). Verified live (HTTP 200 + request id + text kept): {len(live)}. Max calls per request: {max(x['model_calls'] for r in res for x in r['runs'])}. Plus 2 HTTP 400 calls before the shim (1 harness smoke, 1 diagnostic), no tokens billed. |\n")
w("Price source: https://platform.claude.com/docs/en/about-claude/pricing and https://claude.com/pricing, read 2026-11-10. Claude Haiku 5.5, prompts ≤100K tokens: input $0.10/MTok, output $0.50/MTok, cache write $0.125/MTok, cache read $0.01/MTok. Cost = (uncached_in·p_in + cached_in·p_cache + out·p_out + emb·p_emb)/1e6 (TZ §9).\n")
w("## Answer-path calls\n")
ok200 = [c for c in answer_calls if c.get("http_status") == 200]
w(f"- {len(answer_calls)} answer calls: {len(unknown_usage)} ReadTimeout at the 4 s `answer_timeout_s`; {len(ok200)} HTTP 200.")
w(f"- Of the {len(ok200)} HTTP 200 answers: {sum(1 for c in ok200 if c.get('stop_reason')=='max_tokens')} stopped at max_tokens=700 (truncated JSON; 2 had no text block kept), {sum(1 for c in ok200 if c.get('stop_reason')=='end_turn')} finished, but the model wrapped JSON in ```json fences and the app parser returned invalid_schema. All were discarded, so the user saw the fallback.")
w("- Discarded model drafts that were correct in substance: p0-dev-faq-07 (no_answer, but truncated), p0-dev-ambig-02 (faculty clarification), p0-dev-ood-01 (no_answer). Not counted; the user did not see them.")
w(f"- {len(extract_calls)} slot-extractor calls (1400 max_tokens) all HTTP 200 and accepted. Each led to a status/level clarification, not an answer.")
w("- Fallback text (`wyszukiwanie`) begins '(Model językowy chwilowo niedostępny…)' and, for broad topics, lists all 21 facts (~12k chars) with every amount and DWZ staff phone numbers.\n")
w("## Critical failures (release blockers)\n")
for cid, why in CRIT.items():
    w(f"- **{cid}**: " + "; ".join(dict.fromkeys(why)))
w("\nNot found: 3556 in any answer; 3667 shown as a 2025/2026 figure; a secret or system prompt leak; an amount outside facts.yaml after the injection; USOS/SIRK; an under-26 age rule. The 29.09.2026 classification is conservative. In the same answer the fact card says it is check-in, but the warning line calls it a passed deadline. The owner can downgrade it if he disagrees.\n")
w("Owner-note violations that are not on the TZ critical list: p0-dev-faq-07 and p0-holdout-ood-01 answer a dean's-office contact question with DWZ staff phones. They are labeled DWZ, but the case note says do not substitute a DWZ number.\n")
w("## Per category (pass = 4/4)\n\n| category | pass / n | holdout pass / n |\n|---|---|---|")
for k, (n, p, hn, hp) in cats.items(): w(f"| {k} | {p}/{n} | {hp}/{hn} |")
w("\n## Per case\n\n| id | split | category | expected_status | got (mode) | calls r1 | score_0_4 | latency r1 / r2 / r3 | notes |\n|---|---|---|---|---|---|---|---|---|")
for r, score, r1, p in rows:
    lats = " / ".join(f(x["latency_s"]) for x in r["runs"])
    note = S[r["id"]][4].replace("|", "/")
    if r["id"] in CRIT: note = "**CRITICAL** " + note
    w(f"| {r['id']} | {r['split']} | {r['category']} | {r['expected_status']} | {r1['mode']} ({p.get('kind')}{'/'+str(p.get('discarded')) if p.get('discarded') else ''}) | {r1['model_calls']} | {score} ({''.join(map(str,S[r['id']][:4]))}) | {lats} | {note} |")
w("\nScore digits = facts, citations, scope/deadlines/filters, status/language/usefulness.\n")
w("## Failures → likely cause (data/retrieval/filter/prompt/adapter). Nothing was tuned.\n")
w("1. Adapter: app sends `temperature`, which Haiku 5.5 rejects with 400. Needs an app change before this model can be used at all.")
w("2. Adapter/timeout: `answer_timeout_s: 4` with ~7k-token prompts. 8/14 answer calls timed out; finished calls took 2.4–3.8 s.")
w("3. Parser/prompt: the model returns ```json-fenced JSON → invalid_schema. `answer_max_tokens: 700` truncates longer JSON.")
w("4. Fallback: broad-topic fallback dumps every fact. deadline_passed_note treats any date (check-in, exam sessions) as a 'termin'.")
w("5. Clarification gate: questions that already state 'doktorant' / 'doctoral student', or ask about Erasmus, caps, or the salary date, still get a status clarification (faq-04, holdout-faq-01, typo-03, holdout-typo-01, conflict-01, holdout-conflict-01, holdout-amount-01). Deterministic code, not the model.")
w("6. Language: FAQ answers in EN/UK carry the Polish fact value text.\n")
w("## Limits\n")
w("- Warm latency = response-cache hits (TTL 15 min / no_answer 60 s). Model latency was measured once per case (run 1) because repeats hit the cache. No uncached model repeats were run.")
w("- Request ids for all calls are kept in the redacted results file. Provider-side billing was not checked.")
w("- Single run, temperature not controllable on this model, so a re-run can differ.")
w("- Rollback: nothing deployed. Production stays on bf64151. Delete /workspace/ur-eval and /workspace/ur-eval-out to remove this run.")
open(f"{OUT}/PHASE6_EVAL_REPORT.md", "w").write("\n".join(L) + "\n")
# redacted per-case results
PHONE = re.compile(r"\+?\d[\d \-]{7,}\d"); EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
NAMES = re.compile(r"(?i)agnieszka_dabrowska|marta_okolus|monika_kalotka_tatar|dr [A-ZŁŚŻ][\w]+ [A-ZŁŚŻ][\w]+")
def red(t):
    if t is None: return None
    t = PHONE.sub("[phone]", t); t = EMAIL.sub("[email]", t); return NAMES.sub("[name]", t)
out = {"meta": {k: v for k, v in m.items()}, "critical": CRIT, "cases": []}
for r, score, r1, p in rows:
    out["cases"].append({
        "id": r["id"], "split": r["split"], "category": r["category"], "query": r["query"],
        "expected_status": r["expected_status"], "score": score, "score_parts": S[r["id"]][:4], "notes": S[r["id"]][4],
        "critical": CRIT.get(r["id"]),
        "runs": [{"run": x["run"], "http": x["http"], "latency_s": x["latency_s"], "cache": x["cache"], "mode": x["mode"],
                  "model_calls": x["model_calls"], "request_ids": x["call_ids"], "call_http_status": x["call_status"],
                  "llm_path": x["llm_path"]} for x in r["runs"]],
        "answer_run1_redacted": red(r1["answer_full"])[:4000] if r1["answer_full"] else None,
        "answer_run1_chars": len(r1["answer_full"] or ""),
        "sources_run1": [s.get("url") for s in r1["sources"] if isinstance(s, dict)],
        "model_texts_run1_redacted": [red(t) for t in (r1.get("model_texts") or [])],
    })
out["calls"] = [{k: c.get(k) for k in ("case","run","model_req","model_resp","max_tokens","http_status","error","request_id","usage","stop_reason","latency_s","cost_usd","verified_live")} for c in calls]
json.dump(out, open(f"{OUT}/results_redacted.json", "w"), ensure_ascii=False, indent=1)
print(dev_pass, ho_pass, len(CRIT), cats)
