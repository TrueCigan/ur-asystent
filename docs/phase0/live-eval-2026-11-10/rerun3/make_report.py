import json, re, math, collections
RAW = "/workspace/ur-eval-raw/rerun3/raw_results.json"; OUT = "/workspace/ur-eval-out/rerun3-2026-11-10"
d = json.load(open(RAW)); m = d["meta"]; calls = d["calls"]; res = d["results"]; pr = m["probe"]
S = json.load(open(f"{OUT}/manual_scores.json"))
S1 = json.load(open("/workspace/ur-eval-out/manual_scores.json")); SR1 = json.load(open("/workspace/ur-eval-out/rerun-2026-11-10/manual_scores.json")); SR2 = json.load(open("/workspace/ur-eval-out/rerun2-2026-11-10/manual_scores.json"))
CRIT = {"p0-holdout-deadline-01": "'Limit dochodu socjalno-rektorskiego wynosi 3667 PLN miesięcznie' — 3667 is the 2026/2027 combined social+rector scholarship cap, not an income limit (income max is 1908,90 for 2025/2026)",
        "p0-dev-faq-06": "disability amounts 'lekki 1000 zł, umiarkowany 1200 zł, znaczny 1400 zł miesięcznie' are the 2025/2026 figures, shown with no year in November 2026 (row facts_approved=false)"}
PREV_SPEND = {"36f5396 probe (forbidden_citation: ids not shown)": 0.0003497, "a090e29 probe (forbidden_citation: duplicate id / n mismatch)": 0.0003276}
pct = lambda xs, p: (sorted(xs)[max(0, math.ceil(p/100*len(xs))-1)] if xs else None)
f = lambda v: "n/a" if v is None else (f"{v*1000:.0f} ms" if v < 1 else f"{v:.2f} s")
lp = lambda x: x["llm_path"] or {}
def bucket(x):
    if x["model_calls"]: return "model_ok" if lp(x).get("kind") == "model" else "model_fb"
    return {"faq": "faq", "no_answer": "noans", "security": "sec", "doprecyzowanie": "clar"}.get(x["mode"], "other")
lat = collections.defaultdict(list)
for r in res:
    for x in r["runs"]: lat[("cold" if x["run"] == 1 else "warm", bucket(x))].append(x["latency_s"])
allx = [x for r in res for x in r["runs"]]
mw = sum(1 for x in allx if lp(x).get("kind") == "model" and not lp(x).get("discarded"))
mpath = [x for x in allx if x["model_calls"]]
disc = collections.Counter(lp(x).get("discarded") for x in mpath if lp(x).get("discarded"))
mw1 = sum(1 for r in res if lp(r["runs"][0]).get("kind") == "model")
fb1 = sum(1 for r in res if r["runs"][0]["model_calls"] and lp(r["runs"][0]).get("kind") != "model")
cost = sum(c.get("cost_usd") or 0 for c in calls)
tok = {k: sum((c.get("usage") or {}).get(k) or 0 for c in calls) for k in ("input_tokens", "output_tokens")}
REJ = [("p0-dev-faq-04", 1, "status no_answer with fact citations (no_answer may cite only the help link)"),
       ("p0-dev-faq-04", 3, "status clarification with citations (clarification may not cite)"),
       ("p0-holdout-faq-01", 2, "no_answer with fact citations"),
       ("p0-dev-amount-02", 3, "no_answer with fact citations"),
       ("p0-dev-typo-03", 1, "6 citations > 5 (draft was correct: 'doctoral students are not eligible')"),
       ("p0-dev-typo-03", 2, "6 citations > 5 (same correct draft)"),
       ("p0-dev-ambig-02", 1, "clarification with citations"), ("p0-dev-ambig-02", 2, "clarification with citations"), ("p0-dev-ambig-02", 3, "clarification with citations"),
       ("p0-dev-ambig-03", 1, "clarification with citations"), ("p0-dev-ambig-03", 2, "clarification with citations")]
rows = []; cats = {}
for r in res:
    sc = [sum(X[r["id"]][:4]) for X in (S1, SR1, SR2, S)]
    c = cats.setdefault(r["category"], [0, 0, [0]*4, [0]*4]); c[0] += 1; c[1] += r["split"] == "holdout"
    for i in range(4):
        c[2][i] += sc[i] == 4
        if r["split"] == "holdout": c[3][i] += sc[i] == 4
    rows.append((r, sc))
P = lambda split, i: sum(1 for r, sc in rows if r["split"] == split and sc[i] == 4)
L = []; w = L.append
w("# 40-case live eval report — rerun 3 (2026-11-10), with runs 1, rerun 1, rerun 2 for comparison\n")
w("Box-local FastAPI TestClient → /api/chat, not production. Not a launch approval. No merge/deploy/push, no code changes, no tuning, holdout untouched, no load test.\n")
w("## Setup\n")
w(f"- Commit `{m['commit']}` (parent a090e29), branch cursor/phase-0-harness-ac61, clean worktree. Run {m['started_warsaw'][11:19]}–{m['finished_warsaw'][11:19]} Europe/Warsaw.")
w(f"- Index `{m['index_revision']}` ({m['chunks']} chunks), settings `{m['settings_revision']}`, faq `{m['faq_fingerprint']}`, prompt `{m['prompt_version']}`. Model `{m['model']}`. Defaults, no env overrides: ANSWER_TIMEOUT_S {m['answer_timeout_s']}, ANSWER_MAX_TOKENS {m['answer_max_tokens']}, budget_s {m['budget_s']}, LLM_THINKING unset. temperature sent on {m['temperature_sent_calls']}/{m['temperature_sent_calls']+m['temperature_absent_calls']} calls.")
w("- Harness = rerun-2 harness, with the smoke call replaced by a /api/chat probe on p0-dev-deadline-01 (must be model-written). Transport-level spend guard: $2 cap with a worst-case pre-check, 160 calls. Runs 2–3 clear the response and intent caches (uncached, warm).")
pc = pr["calls"][0]
w(f"- Probe: HTTP {pr['http']}, `{pc['request_id']}`, llm_path kind=model, not discarded, {pr['latency_s']} s. Passed, so all 40 cases × 3 runs were run.\n")
w("## Earlier rerun-3 probe stops (same day, same method)\n")
w("- 36f5396: probe answer schema-valid, but `forbidden_citation`. The model was never shown citable chunk ids and cited a fact id. Cost $0.000350.")
w("- a090e29: `forbidden_citation`. The model cited real ids but renumbered its marks 1..3 and repeated one id. Cost $0.000328.")
w(f"- **Total rerun-3 spend: ${cost + sum(PREV_SPEND.values()):.5f}** (this run ${cost:.5f} + earlier probes ${sum(PREV_SPEND.values()):.6f}).\n")
w("## Comparison\n\n| metric | run 1 (9c8f2b9) | rerun 1 (16b3066) | rerun 2 (799d60a) | rerun 3 (317c743) |\n|---|---|---|---|---|")
w(f"| pass total / dev / holdout | {P('dev',0)+P('holdout',0)}/40 / {P('dev',0)}/30 / {P('holdout',0)}/10 | {P('dev',1)+P('holdout',1)}/40 / {P('dev',1)}/30 / {P('holdout',1)}/10 | {P('dev',2)+P('holdout',2)}/40 / {P('dev',2)}/30 / {P('holdout',2)}/10 | **{P('dev',3)+P('holdout',3)}/40 / {P('dev',3)}/30 / {P('holdout',3)}/10** |")
w(f"| critical-fail cases | 14 | 6 | 3 | **{len(CRIT)}** |")
w(f"| model-written answers, run 1 / all requests | 0/40 | 0/40 | 0/40 / 0/120 | **{mw1}/40 / {mw}/120** |")
w(f"| model-path requests rejected | — | all (KeyError) | 42/42 invalid_schema | **{sum(disc.values())}/{len(mpath)}** ({', '.join(f'{k} {v}' for k,v in disc.items())}) |")
w(f"| calls / verified live | 23 / 13 | 54 / 54 | 46 / 46 | {len(calls)} / {sum(1 for c in calls if c.get('verified_live'))} |")
w(f"| cost (usage × price) | $0.00763 + ≤$0.0086 | $0.02990 + ≤$0.0075 + $0.00054 | $0.01398 | ${cost:.5f} |")
w(f"| breaker opened | no | yes | no | no (1 error recorded: the timeout) |")
w(f"| slowest request | — | 127.9 s | 2.81 s | {f(max(x['latency_s'] for x in allx))} (see latency) |\n")
w(f"Targets ≥36/40 and ≥9/10 holdout: **not met**. Tokens {tok['input_tokens']} in / {tok['output_tokens']} out; price $0.10 / $0.50 per MTok (platform.claude.com pricing, read 2026-11-10). Guard not triggered.\n")
w("## Model-written vs fallback\n")
w(f"- Run 1 of each case: {mw1} model-written, {fb1} fallback after a model call (faq-04, typo-03, ambig-02, ambig-03), {40-mw1-fb1} deterministic (11 FAQ, 7 no_answer, 3 security, 3 clarification).")
w(f"- All 120 requests: {mw} model-written out of {len(mpath)} model-path requests. Unstable cases: faq-04 (F/M/F), holdout-faq-01 (M/F/M), amount-02 (M/M/F), typo-03 (F/F/M).")
w("- Schema rejections: **0**. All model texts were valid JSON with the right fields.")
w(f"- Citation rejections: **{len(REJ)}**, with one more timeout. Grouped: clarification draft that carries citations ×6 (ambig-02 r1–3, ambig-03 r1–2, faq-04 r3); no_answer draft citing facts instead of the help link ×3 (faq-04 r1, holdout-faq-01 r2, amount-02 r3); more than 5 citations ×2 (typo-03 r1–2; the draft itself was right). No rejection for an unknown id. Replayed offline with no API call: `rag.answer` with `call_llm` stubbed to the kept text, `validate_answer` observed.\n")
w("## Critical fails\n")
for k, v in CRIT.items(): w(f"- **{k}**: {v}")
w("\nJudgment calls; the owner can downgrade either. Rerun 2's three unlabeled-deadline criticals are gone: deadline notes are now labeled and are not added to fallbacks for unrelated topics. No 29/30.09 or exam-date 'termin minął'. No 3556. No leak or injection.\n")
w("## Remaining failure groups\n")
w("1. **The answer text's 'Źródła:' list does not match the cited facts** (11 of 12 run-1 model answers: faq-06, holdout-faq-01, deadline-01, deadline-02, holdout-deadline-01, amount-02, holdout-amount-01, typo-02, holdout-typo-01, conflict-01, holdout-conflict-01; only amount-03 matches). The response `sources` field carries the right fact URLs, but the text block is still built from retrieval hits (often 2021–2023 PDFs). If this were fixed, deadline-01, conflict-01 and holdout-conflict-01 would reach 4/4 (22/40, holdout 5/10).")
w("2. **Required fact not in the citable list**, so the model says 'not confirmed': faq-04 / holdout-faq-01 (doctoral_rector_eligible), deadline-02 (social_rector_deadline), holdout-amount-01 (rector_social_cap_monthly 3667).")
w("3. **Citation rules vs clarification/no_answer drafts**: ambig-02, ambig-03, faq-04, typo-03 (>5 citations) fall back to a bare source list.")
w("4. **Content errors in model answers**: holdout-deadline-01 (3667 called an income limit), faq-06 (2025/2026 amounts with no year), typo-02 (benefits channel 'Moje stypendia, skany PDF' attached to the dorm application), amount-02 (reads the supplement as a dorm-fee increase), holdout-typo-01 (DWZ steps missing; stale source PDFs).")
w("5. **Expected clarification gets no_answer**: deadline-03, holdout-deadline-02.")
w("6. **EN/UK FAQ answers carry Polish fact text**: faq-03, faq-05, xlang-01, xlang-02. MN→EN mapping (holdout-xlang-01) awaits the owner.")
w("7. **Latency outlier**: ambig-03 run 3, see below.\n")
w("## Latency (warm = runs 2–3, caches cleared)\n\n| path | cold n | cold p50 / p95 | warm n | warm p50 / p95 |\n|---|---|---|---|---|")
for b, label in (("model_ok", "model-written"), ("model_fb", "model call, fallback shown"), ("faq", "FAQ"), ("noans", "deterministic no_answer"), ("clar", "clarification"), ("sec", "security")):
    c, wv = lat[("cold", b)], lat[("warm", b)]
    w(f"| {label} | {len(c)} | {f(pct(c,50))} / {f(pct(c,95))} | {len(wv)} | {f(pct(wv,50))} / {f(pct(wv,95))} |")
av = [x["latency_s"] for x in allx]; avx = sorted(av)[:-1]
w(f"| all 120 requests | | | | p50 {f(pct(av,50))} / p95 {f(pct(av,95))} / max {f(max(av))} |")
mo = [x["latency_s"] for x in allx if bucket(x) == "model_ok"]
w(f"\nModel-written answers over all runs: p50 {f(pct(mo,50))}, p95 {f(pct(mo,95))}.")
w("- **ambig-03 run 3: 108.6 s.** HTTP 200, the provider body took 108.45 s; the app marked it `timeout` and showed the fallback. Caveat, a harness limitation: the harness's transport-level guard reads the full body (`r.read()`) before handing it to the app. The app enforces its 12 s wall clock while iterating the stream in `post_with_deadline`, so it could not cut this call. Without the harness the app should stop at about 12 s plus one chunk gap; not measured. Every other request finished in ≤2.8 s.")
w("- Breaker: never opened. 1 provider error recorded (that timeout).\n")
w("## Per category (pass = 4/4)\n\n| category | n | run 1 | rerun 1 | rerun 2 | rerun 3 | holdout n | holdout r1/rr1/rr2/rr3 |\n|---|---|---|---|---|---|---|---|")
for k, (n, hn, p, hp) in cats.items(): w(f"| {k} | {n} | {p[0]} | {p[1]} | {p[2]} | {p[3]} | {hn} | {'/'.join(map(str,hp))} |")
w("\n## Per case\n\n| id | split | expected | rerun 3 got (r1) | M/F r1/r2/r3 | score run1→rr1→rr2→rr3 | latency r1/r2/r3 | notes |\n|---|---|---|---|---|---|---|---|")
for r, sc in rows:
    x = r["runs"]; p = lp(x[0])
    mv = "/".join(("M" if lp(y).get("kind") == "model" else "F") if y["model_calls"] else "-" for y in x)
    note = ("**CRITICAL** " if r["id"] in CRIT else "") + S[r["id"]][4].replace("|", "/")
    w(f"| {r['id']} | {r['split']} | {r['expected_status']} | {x[0]['mode']} ({p.get('kind')}{'/'+str(p.get('discarded')) if p.get('discarded') else ''}) | {mv} | {sc[0]}→{sc[1]}→{sc[2]}→{sc[3]} ({''.join(map(str,S[r['id']][:4]))}) | {' / '.join(f(y['latency_s']) for y in x)} | {note} |")
w("\nM = model-written, F = model call then fallback, - = deterministic. Score digits = facts, citations, scope, status/language/usefulness.\n")
w("## Limits\n")
w("- Single run per commit. Manual scoring, no LLM judge. Provider bill not read. Redacted file strips phones, emails and staff names. Rollback: nothing deployed.")
w("- Secret check: KEYCHECK\n")
open(f"{OUT}/PHASE6_EVAL_REPORT.md", "w").write("\n".join(L) + "\n")
PHONE = re.compile(r"\+?\d[\d \-]{7,}\d"); EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
NAMES = re.compile(r"(?i)dr [A-ZŁŚŻ]\w+ [A-ZŁŚŻ]\w+")  # staff-name list used at run time is not stored in this copy
red = lambda t: None if t is None else NAMES.sub("[name]", EMAIL.sub("[email]", PHONE.sub("[phone]", t)))
out = {"meta": {k: v for k, v in m.items() if k != "probe"}, "probe": {k: pr[k] for k in ("case", "http", "latency_s", "mode", "llm_path", "ok")} | {"request_ids": [c["request_id"] for c in pr["calls"]]},
       "earlier_rerun3_probes": PREV_SPEND, "total_rerun3_spend_usd": cost + sum(PREV_SPEND.values()), "critical": CRIT,
       "citation_rejections": [{"case": a, "run": b, "reason": c} for a, b, c in REJ], "discarded_counts": dict(disc), "cases": []}
for r, sc in rows:
    out["cases"].append({"id": r["id"], "split": r["split"], "category": r["category"], "query": r["query"], "expected_status": r["expected_status"],
        "scores": {"run1": sc[0], "rerun1": sc[1], "rerun2": sc[2], "rerun3": sc[3]}, "score_parts": S[r["id"]][:4], "notes": red(S[r["id"]][4]), "critical": CRIT.get(r["id"]),
        "runs": [{"run": x["run"], "http": x["http"], "latency_s": x["latency_s"], "mode": x["mode"], "model_calls": x["model_calls"], "request_ids": x["call_ids"],
                  "stop_reasons": x["stop_reasons"], "llm_path": x["llm_path"], "answer_redacted": red(x["answer_full"]),
                  "sources": [s.get("url") for s in x["sources"] if isinstance(s, dict)], "model_text_redacted": [red(t) for t in x["model_texts"] or []]} for x in r["runs"]]})
out["calls"] = [{k: c.get(k) for k in ("case","run","http_status","request_id","usage","stop_reason","content_types","thinking_block","temperature_sent","latency_s","cost_usd","verified_live")} for c in calls]
json.dump(out, open(f"{OUT}/results_redacted.json", "w"), ensure_ascii=False, indent=1)
print(P('dev',3), P('holdout',3), mw1, fb1, mw, len(mpath), dict(disc), cost, pct(av,50), pct(av,95), pct(mo,50), pct(mo,95))
