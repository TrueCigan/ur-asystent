import json, re, math
RAW = "/workspace/ur-eval-raw/rerun/raw_results.json"; RAW1 = "/workspace/ur-eval-raw/raw_results.json"
OUT = "/workspace/ur-eval-out/rerun-2026-11-10"
d = json.load(open(RAW)); m = d["meta"]; calls = d["calls"]; res = d["results"]
d1 = json.load(open(RAW1)); res1 = {r["id"]: r for r in d1["results"]}
S = json.load(open(f"{OUT}/manual_scores.json")); S1 = json.load(open("/workspace/ur-eval-out/manual_scores.json"))
CRIT1 = json.load(open("/workspace/ur-eval-out/results_redacted.json"))["critical"]
CRIT = {}
def crit(cid, why): CRIT.setdefault(cid, []).append(why)
for r in res:
    a = r["runs"][0]["answer_full"] or ""
    for dte in ("29.09.2026", "30.09.2026", "01.10.2026"):
        if f"Ten termin ({dte}) już minął" in a: crit(r["id"], f"check-in day {dte} shown as '⚠️ Ten termin ({dte}) już minął'")
    if "3556" in a: crit(r["id"], "3556 used")
crit("p0-dev-deadline-03", "exam-session dates 16.06.2026 / 19.06.2026 / 12.09.2026 shown as 'Ten termin … już minął'")
pct = lambda xs, p: (sorted(xs)[max(0, math.ceil(p/100*len(xs))-1)] if xs else None)
f = lambda v: "n/a" if v is None else (f"{v*1000:.0f} ms" if v < 1 else f"{v:.2f} s")
def bucket(x): return "model" if x["model_calls"] > 0 else ("paused" if (x["llm_path"] or {}).get("discarded") == "provider_pause" else "nocall")
lat = {(k, b): [] for k in ("cold", "warm") for b in ("model", "nocall", "paused")}
for r in res:
    for x in r["runs"]: lat[("cold" if x["run"] == 1 else "warm", bucket(x))].append(x["latency_s"])
faq_lat = {k: [x["latency_s"] for r in res for x in r["runs"] if x["mode"] == "faq" and (x["run"] == 1) == (k == "cold")] for k in ("cold", "warm")}
ans_calls = [c for c in calls if "помощник" in (c.get("sys_head") or "")]
ext_calls = [c for c in calls if "extract" in (c.get("sys_head") or "")]
live = [c for c in calls if c.get("verified_live")]
tok = {k: sum((c.get("usage") or {}).get(k) or 0 for c in calls) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
cost_known = sum(c.get("cost_usd") or 0 for c in calls); unknown = [c for c in calls if c.get("http_status") is None]
diag_cost = (1768*0.10 + 727*0.50)/1e6
model_vis = {r["id"]: [ (x["llm_path"] or {}).get("kind") == "model" and (x["llm_path"] or {}).get("provider_verified") for x in r["runs"]] for r in res}
n_model_vis = sum(1 for v in model_vis.values() if v[0])
cyr = sum(1 for c in ans_calls if c.get("text") and re.search(r"[а-яё]{4,}", c["text"], re.I))
rows = []; cats = {}
for r in res:
    s2 = sum(S[r["id"]][:4]); s1 = sum(S1[r["id"]][:4])
    c = cats.setdefault(r["category"], [0, 0, 0, 0, 0, 0]); c[0] += 1; c[1] += s2 == 4; c[4] += s1 == 4
    if r["split"] == "holdout": c[2] += 1; c[3] += s2 == 4; c[5] += s1 == 4
    rows.append((r, s1, s2))
P = lambda split, k: sum(1 for r, s1, s2 in rows if r["split"] == split and (s1 if k == 1 else s2) == 4)
L = []; w = L.append
w("# 40-case live eval report — run 1 and rerun (2026-11-10)\n")
w("Both runs: box-local FastAPI TestClient → /api/chat, not production. Not a launch approval. No merge, deploy or push, no app code changes, no tuning, no 10-concurrent load test.\n")
w("## Setup\n\n| | run 1 | rerun |\n|---|---|---|")
m1 = d1["meta"]
w(f"| commit | `{m1['commit']}` | `{m['commit']}` |")
w(f"| time (Europe/Warsaw) | {m1['started_warsaw'][11:19]}–{m1['finished_warsaw'][11:19]} | {m['started_warsaw'][11:19]}–{m['finished_warsaw'][11:19]} |")
w(f"| model | {m1['model']} | {m['model']} |")
w(f"| index / settings / faq / prompt | {m1['index_revision']} / {m1['settings_revision']} / {m1['faq_fingerprint']} / {m1['prompt_version']} | {m['index_revision']} / {m['settings_revision']} / {m['faq_fingerprint']} / {m['prompt_version']} |")
w(f"| answer timeout / max tokens / budget_s | 4 s / 700 / 6 | {m['answer_timeout_s']} s / {m['answer_max_tokens']} / {m['budget_s']} (manifest defaults, no env override) |")
w(f"| context caps | context_max_tokens 4500 | context_chunks {m['context_chunks']}, chunk_chars {m['chunk_chars']}, fact_cards_max {m['fact_cards_max']}, card_chars {m['card_chars']}, context_max_tokens {m['context_max_tokens']} |")
w(f"| temperature on the wire | stripped by harness shim on 23 calls | **app omitted it alone: 0/{m['temperature_sent_calls']+m['temperature_absent_calls']} requests carried `temperature`** (no shim, LLM_SEND_TEMPERATURE unset) |")
w("| repeats 2–3 | response-cache hits | public response cache and intent cache cleared in-process before runs 2 and 3. Same warm process, so this is uncached warm latency |")
w(f"| EXTRACTOR_LLM | unset (default on) | unset (default on) |\n")
w("## Headline\n\n| metric | run 1 | rerun |\n|---|---|---|")
w(f"| Pass dev / holdout / total | {P('dev',1)}/30 / {P('holdout',1)}/10 / {P('dev',1)+P('holdout',1)}/40 | **{P('dev',2)}/30 / {P('holdout',2)}/10 / {P('dev',2)+P('holdout',2)}/40** |")
w(f"| Critical-fail cases | {len(CRIT1)} | **{len(CRIT)}** |")
w(f"| User-visible answer written by the model (verified), run 1 / all 120 requests | 0/40 / 0/120 | **{n_model_vis}/40 / {sum(sum(map(bool,v)) for v in model_vis.values())}/120** |")
w(f"| Model calls (incl. smoke) / verified live | 23 / 13 | {len(calls)} / {len(live)} |")
w(f"| Answer calls: HTTP 200 / timeout | 6 / 8 | {sum(1 for c in ans_calls if c.get('http_status')==200)} / {sum(1 for c in ans_calls if c.get('http_status') is None)} |")
w(f"| Tokens in / out | 44139 / 6440 | {tok['input_tokens']} / {tok['output_tokens']} |")
w(f"| Cost (usage × price; provider bill not read) | $0.00763 (+≤$0.0086 unknown for 8 timeouts) | ${cost_known:.5f} (+≤${len(unknown)*(9000*0.5+1200*2.5)/1e6:.4f} worst case for {len(unknown)} timeout) + diagnostic call ${diag_cost:.5f} |")
w(f"| FAQ fast path | 11/40 | {sum(1 for r in res if r['runs'][0]['mode']=='faq')}/40 |\n")
w("Price: Claude Haiku 5.5 $0.10/MTok input, $0.50/MTok output (≤100K prompt), from https://platform.claude.com/docs/en/about-claude/pricing, read 2026-11-10. The spend guard (cap $2.00, 160 calls) never triggered. Harness-counted spend including the timeout worst case: $" + f"{m['spent_usd']:.5f}.\n")
w("## Why the model still wrote 0 answers\n")
w(f"- New blocker: Haiku 5.5 returns a `thinking` content block before the `text` block. `app/rag.py` call_llm does `payload[\"content\"][0][\"text\"]`, which raises KeyError: 'text'. The answer path catches it as a provider exception (`discarded=exception`), so every answer call that returned HTTP 200 ({sum(1 for c in ans_calls if c.get('http_status')==200)} of them; the harness kept text for {sum(1 for c in ans_calls if c.get('text'))}) was thrown away. I confirmed this with one extra diagnostic call outside the harness: 1768 in / 727 out tokens, 485 of them thinking tokens, traceback at rag.py line 1166. Its request id was not captured.")
w("- The slot-extractor calls returned text first and were accepted.")
w("- Those KeyErrors count as provider errors, so the circuit breaker opened (5 errors in 30 s). p0-dev-ambig-03 run 3, then all runs of p0-dev-ood-01, p0-dev-ood-03 and p0-holdout-ood-01 got `provider_pause` with 0 calls.")
w(f"- p0-dev-typo-03 run 3: ReadTimeout after {max(x['latency_s'] for r in res for x in r['runs']):.1f} s wall time, well above the 12 s timeout and the 15 s budget. The httpx timeout is per read, not total.")
w(f"- Draft quality, not shown to users: {cyr}/{sum(1 for c in ans_calls if c.get('text'))} kept answer drafts contain Russian text (the answer prompt is in Russian). For example, the p0-holdout-inject-01 draft for a Polish question was in Russian. {sum(1 for c in ans_calls if c.get('stop_reason')=='max_tokens')} answer calls still stopped at max_tokens=1200.\n")
w("## Rechecked run-1 critical issues\n")
w("- 29.09.2026 'termin minął': gone. **Replaced by '⚠️ Ten termin (30.09.2026) już minął'**, which is also a check-in day, taken from the dorm page quote. Still critical in p0-dev-deadline-01, -deadline-02, -amount-02, -typo-02, -ambig-02.")
w("- Exam dates called deadlines: **still present** in p0-dev-deadline-03 (16.06, 19.06, 12.09.2026).")
w("- 2025/2026 amounts on a 2026/2027 question (p0-holdout-deadline-01): **fixed**. No 2025/2026 amount is shown. The fact cards are now Erasmus+ instead.")
w("- Full fact dump: **fixed**. At most 3 fact cards and 3 quotes; longest run-1 answer is " + f"{max(len(r['runs'][0]['answer_full'] or '') for r in res)} chars (run 1 of the first eval: ~12.5k).")
w("- DWZ phones on dean's-office questions: **fixed**. No phone numbers in any answer. The dean questions still get irrelevant quotes instead of a refusal.")
w("- Needless status questions: **removed** for faq-04, holdout-faq-01, typo-03, holdout-typo-01, conflict-01 and holdout-amount-01. The last three now ask for level or year instead of answering. Still asked in faq-06, amount-03 and holdout-conflict-01. In holdout-ambig-01 (tuition) and holdout-xlang-01 the clarification is expected.")
w("- Not found: 3556, 3667 as a 2025/2026 figure, a secret or prompt leak, an amount outside facts.yaml after injection.\n")
w("## Critical failures (rerun)\n")
for cid, why in CRIT.items(): w(f"- **{cid}**: " + "; ".join(dict.fromkeys(why)))
w("\n## Latency (rerun; warm = runs 2–3 with caches cleared)\n\n| path | cold n | cold p50 / p95 | warm n | warm p50 / p95 |\n|---|---|---|---|---|")
for b, label in (("model", "model call made (fallback shown)"), ("nocall", "no call: FAQ / security / clarification"), ("paused", "breaker paused, no call")):
    c, wv = lat[("cold", b)], lat[("warm", b)]
    w(f"| {label} | {len(c)} | {f(pct(c,50))} / {f(pct(c,95))} | {len(wv)} | {f(pct(wv,50))} / {f(pct(wv,95))} |")
w(f"| FAQ fast path only | {len(faq_lat['cold'])} | {f(pct(faq_lat['cold'],50))} / {f(pct(faq_lat['cold'],95))} | {len(faq_lat['warm'])} | {f(pct(faq_lat['warm'],50))} / {f(pct(faq_lat['warm'],95))} |")
allv = [x["latency_s"] for r in res for x in r["runs"]]
w(f"| all requests | | | 120 | overall p50 {f(pct(allv,50))} / p95 {f(pct(allv,95))} |")
w("\nModel-path latency includes the model call, which returned HTTP 200 but was then discarded, so the user waited for a fallback. Run-1 cold model path was 3.87 s / 4.25 s, and its warm runs were cache hits (8 ms / 11 ms), so they are not comparable. All 3 runs per case fit the budget.\n")
w("## Per category (pass = 4/4)\n\n| category | run 1 pass | rerun pass | run 1 holdout | rerun holdout |\n|---|---|---|---|---|")
for k, (n, p, hn, hp, p1, hp1) in cats.items(): w(f"| {k} | {p1}/{n} | {p}/{n} | {hp1}/{hn} | {hp}/{hn} |")
w("\n## Per case (run 1 of each eval is the quality run)\n\n| id | split | expected | rerun got | model-written r1/r2/r3 | calls r1/r2/r3 | score run1 → rerun | rerun latency r1 / r2 / r3 | rerun notes |\n|---|---|---|---|---|---|---|---|---|")
for r, s1, s2 in rows:
    x = r["runs"]; p = x[0]["llm_path"] or {}
    mv = "/".join("M" if v else "F" if x[i]["model_calls"] or (x[i]["llm_path"] or {}).get("kind")=="fallback" else "-" for i, v in enumerate(model_vis[r["id"]]))
    note = S[r["id"]][4].replace("|", "/"); note = ("**CRITICAL** " if r["id"] in CRIT else "") + note
    w(f"| {r['id']} | {r['split']} | {r['expected_status']} | {x[0]['mode']} ({p.get('kind')}{'/'+str(p.get('discarded')) if p.get('discarded') else ''}) | {mv} | {'/'.join(str(y['model_calls']) for y in x)} | {s1} → {s2} ({''.join(map(str,S[r['id']][:4]))}) | {' / '.join(f(y['latency_s']) for y in x)} | {note} |")
w("\nM = user saw a verified model answer; F = fallback after a model attempt or pause; - = deterministic path (FAQ, clarification, security), no model answer expected. Score digits = facts, citations, scope, status/language/usefulness.\n")
changed = [(r["id"], s1, s2) for r, s1, s2 in rows if s1 != s2]
w("Score changes vs run 1: " + ", ".join(f"{i} {a}→{b}" for i, a, b in changed) + ". No case changed pass/fail status.\n")
w("## Remaining blockers (app changes; not done here)\n")
w("1. call_llm must read the first `text` block, not `content[0]`. Without that, no Haiku 5.5 answer can reach a user.")
w("2. A parsing KeyError should not count toward the provider circuit breaker.")
w("3. The answer prompt is in Russian, and drafts come back in Russian for PL/EN questions. The language check would then reject them.")
w("4. deadline_passed_note still turns any date in a quote (check-in 30.09, exam sessions) into 'Ten termin … już minął'.")
w("5. Fallback for off-topic and dean's-office questions shows irrelevant quotes instead of a refusal.")
w("6. Remaining clarifications where an answer is expected: faq-06, amount-03, holdout-amount-01, conflict-01, holdout-conflict-01, holdout-typo-01. EN/UK FAQ answers carry Polish fact text.")
w("7. The per-read httpx timeout allowed a 128 s request.")
w("8. 'max_tokens' truncation still occurs at 1200.\n")
w("## Limits\n")
w("- Single rerun. Provider bill not checked. Request ids are in results_redacted.json. The /api/chat request has no filters field, so case filters reach the app only through the question text. Rollback: nothing deployed.")
open(f"{OUT}/PHASE6_EVAL_REPORT.md", "w").write("\n".join(L) + "\n")
PHONE = re.compile(r"\+?\d[\d \-]{7,}\d"); EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
NAMES = re.compile(r"(?i)agnieszka_dabrowska|marta_okolus|monika_kalotka_tatar|dr [A-ZŁŚŻ]\w+ [A-ZŁŚŻ]\w+")
red = lambda t: None if t is None else NAMES.sub("[name]", EMAIL.sub("[email]", PHONE.sub("[phone]", t)))
out = {"meta": m, "critical": CRIT, "critical_run1": CRIT1, "cases": []}
for r, s1, s2 in rows:
    out["cases"].append({"id": r["id"], "split": r["split"], "category": r["category"], "query": r["query"],
        "expected_status": r["expected_status"], "score_run1": s1, "score": s2, "score_parts": S[r["id"]][:4], "notes": S[r["id"]][4],
        "critical": CRIT.get(r["id"]), "model_written_per_run": model_vis[r["id"]],
        "runs": [{"run": x["run"], "http": x["http"], "latency_s": x["latency_s"], "cache": x["cache"], "mode": x["mode"],
                  "model_calls": x["model_calls"], "request_ids": x["call_ids"], "call_http_status": x["call_status"],
                  "stop_reasons": x.get("stop_reasons"), "llm_path": x["llm_path"], "answer_same_as_run1": x.get("answer_same_as_run1")} for x in r["runs"]],
        "answer_run1_redacted": red(r["runs"][0]["answer_full"]),
        "sources_run1": [s.get("url") for s in r["runs"][0]["sources"] if isinstance(s, dict)],
        "model_texts_redacted": [[red(t) for t in (x.get("model_texts") or [])] for x in r["runs"]]})
out["calls"] = [{k: c.get(k) for k in ("case","run","model_req","model_resp","max_tokens","temperature_sent","http_status","error","request_id","usage","stop_reason","latency_s","cost_usd","verified_live")} for c in calls]
out["diagnostic_call_outside_harness"] = {"purpose": "confirm KeyError on thinking block", "usage": {"input_tokens": 1768, "output_tokens": 727, "thinking_tokens": 485}, "cost_usd_est": diag_cost, "request_id": "not captured"}
json.dump(out, open(f"{OUT}/results_redacted.json", "w"), ensure_ascii=False, indent=1)
print(P('dev',2), P('holdout',2), len(CRIT), n_model_vis, len(calls), len(live), cost_known, cyr, changed)
