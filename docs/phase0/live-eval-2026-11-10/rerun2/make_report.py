import json, re, math, collections, sys
sys.path.insert(0, "/workspace/ur-eval/app")
from answer_contract import parse_json_object, AnswerIn
from pydantic import ValidationError
RAW = "/workspace/ur-eval-raw/rerun2/raw_results.json"; OUT = "/workspace/ur-eval-out/rerun2-2026-11-10"
d = json.load(open(RAW)); m = d["meta"]; calls = d["calls"]; res = d["results"]
S = json.load(open(f"{OUT}/manual_scores.json"))
S1 = json.load(open("/workspace/ur-eval-out/manual_scores.json")); SR = json.load(open("/workspace/ur-eval-out/rerun-2026-11-10/manual_scores.json"))
CRIT1 = json.load(open("/workspace/ur-eval-out/results_redacted.json"))["critical"]
CRITR = json.load(open("/workspace/ur-eval-out/rerun-2026-11-10/results_redacted.json"))["critical"]
STOP = open("/workspace/ur-eval-raw/rerun2/stopped-attempt/STOP_NOTE.md").read()
CRIT = {}
def crit(cid, why): CRIT.setdefault(cid, []).append(why)
for r in res:
    a = r["runs"][0]["answer_full"] or ""
    for dte in ("29.09.2026", "30.09.2026", "01.10.2026", "16.06.2026", "19.06.2026", "12.09.2026"):
        if f"({dte}) już minął" in a: crit(r["id"], f"'{dte}' shown as passed deadline")
    if "3556" in a: crit(r["id"], "3556 used")
crit("p0-holdout-deadline-01", "scholarship question: unlabeled '⚠️ Ten termin (15.05.2026) już minął (dziś: 2026-11-10).' — 15.05.2026 is the dorm deadline")
crit("p0-dev-ambig-03", "bare 'stypendium': unlabeled '⚠️ Ten termin (15.05.2026) już minął' (dorm deadline) next to the scholarship window")
crit("p0-dev-ambig-02", "faculty-rules question: unlabeled '⚠️ Ten termin (15.05.2026) już minął' and '⚠️ Ten termin (01.09.2026 – 05.10.2026) już minął' + late-application hint")
pct = lambda xs, p: (sorted(xs)[max(0, math.ceil(p/100*len(xs))-1)] if xs else None)
f = lambda v: "n/a" if v is None else (f"{v*1000:.0f} ms" if v < 1 else f"{v:.2f} s")
def bucket(x):
    if x["model_calls"] > 0: return "model"
    return {"faq": "faq", "no_answer": "noans", "security": "sec", "doprecyzowanie": "clar"}.get(x["mode"], "other")
lat = collections.defaultdict(list)
for r in res:
    for x in r["runs"]: lat[("cold" if x["run"] == 1 else "warm", bucket(x))].append(x["latency_s"])
ans_calls = [c for c in calls if (c.get("sys_head") or "").startswith("You are the assistant")]
ext_calls = [c for c in calls if c not in ans_calls and c["case"] != "smoke" and c.get("max_tokens") != 16]
live = [c for c in calls if c.get("verified_live")]
tok = {k: sum((c.get("usage") or {}).get(k) or 0 for c in calls) for k in ("input_tokens", "output_tokens")}
cost = sum(c.get("cost_usd") or 0 for c in calls)
model_vis = {r["id"]: [(x["llm_path"] or {}).get("kind") == "model" and bool((x["llm_path"] or {}).get("provider_verified")) and not (x["llm_path"] or {}).get("discarded") for x in r["runs"]] for r in res}
n_model_vis = sum(1 for v in model_vis.values() if v[0])
# offline replay of kept drafts (no API calls)
why = collections.Counter(); keys = collections.Counter(); schema_ok = 0; lang_drafts = collections.Counter()
for c in ans_calls:
    data, err = parse_json_object(c["text"], c.get("stop_reason"))
    if data is None: why["parse:" + str(err)] += 1; continue
    keys.update(data.keys())
    a = str(data.get("answer") or "")
    lang_drafts["uk/ru (Cyrillic)" if re.search(r"[а-яёіїєґ]{4,}", a, re.I) else ("pl" if re.search(r"[ąćęłńóśźż]", a) else "en/other")] += 1
    try: AnswerIn.model_validate(data); schema_ok += 1
    except ValidationError as e:
        for er in e.errors(): why[f"{er['type']}:{er['loc'][0]}"] += 1
fenced = sum(1 for c in ans_calls if (c.get("text") or "").lstrip().startswith("```"))
rows = []; cats = {}
for r in res:
    sc = [sum(X[r["id"]][:4]) for X in (S1, SR, S)]
    c = cats.setdefault(r["category"], [0, 0, [0, 0, 0], [0, 0, 0]]); c[0] += 1
    if r["split"] == "holdout": c[1] += 1
    for i in range(3):
        c[2][i] += sc[i] == 4
        if r["split"] == "holdout": c[3][i] += sc[i] == 4
    rows.append((r, sc))
P = lambda split, i: sum(1 for r, sc in rows if r["split"] == split and sc[i] == 4)
L = []; w = L.append
w("# 40-case live eval report — run 1, rerun 1, rerun 2 (2026-11-10)\n")
w("All runs: box-local FastAPI TestClient → /api/chat, not production. Not a launch approval. No merge, deploy or push, no app code changes, no tuning, no 10-concurrent load test.\n")
w("## Setup (rerun 2)\n")
w(f"- Commit `{m['commit']}` (parent 50a2fcddd9a98f5f9208bcb1f0d72c4d7c5778c8), branch cursor/phase-0-harness-ac61, clean worktree.")
w(f"- Time: {m['started_warsaw'][11:19]}–{m['finished_warsaw'][11:19]} Europe/Warsaw. Model `{m['model']}`, Anthropic.")
w(f"- Index `{m['index_revision']}` ({m['chunks']} chunks), settings `{m['settings_revision']}`, faq `{m['faq_fingerprint']}`, prompt `{m['prompt_version']}`.")
w(f"- App defaults, with no env overrides (LLM_THINKING, LLM_SEND_TEMPERATURE, EXTRACTOR_LLM unset): ANSWER_TIMEOUT_S {m['answer_timeout_s']} (whole request, post_with_deadline), ANSWER_MAX_TOKENS {m['answer_max_tokens']}, budget_s {m['budget_s']}, context_chunks {m['context_chunks']}, chunk_chars {m['chunk_chars']}, fact_cards_max {m['fact_cards_max']}, card_chars {m['card_chars']}.")
w("- On the wire, the app sent `thinking: {type: disabled}` and `output_config: {effort: high}` on every call, and `temperature` on 0 of 46 calls. The harness did not change any request field.")
w("- Harness: spend guard at `httpx.HTTPTransport.handle_request` with a $2.00 cap and 160 calls. Only api.anthropic.com/v1/messages is allowed. `httpx.post` was left untouched, so the app's own post_with_deadline path ran. Runs 2–3 cleared the response and intent caches in-process: uncached and warm.")
sm = m["smoke"]["call"]
w(f"- Smoke (rag.call_llm, max_tokens 16, timeout 12): HTTP {sm['http_status']}, `{sm['request_id']}`, content {sm['content_types']}, text \"{m['smoke']['text']}\", stop_reason {sm['stop_reason']}, {sm['latency_s']} s. The app returned it with no exception.\n")
w("## Three-run comparison\n\n| metric | run 1 (9c8f2b9) | rerun 1 (16b3066) | rerun 2 (799d60a) |\n|---|---|---|---|")
w(f"| Pass total / dev / holdout | {P('dev',0)+P('holdout',0)}/40 / {P('dev',0)}/30 / {P('holdout',0)}/10 | {P('dev',1)+P('holdout',1)}/40 / {P('dev',1)}/30 / {P('holdout',1)}/10 | **{P('dev',2)+P('holdout',2)}/40 / {P('dev',2)}/30 / {P('holdout',2)}/10** |")
w(f"| Critical-fail cases | {len(CRIT1)} | {len(CRITR)} | **{len(CRIT)}** |")
w(f"| Model-written user answers (run 1 of each) | 0/40 | 0/40 | **{n_model_vis}/40** ({sum(sum(v) for v in model_vis.values())}/120 requests) |")
w(f"| Why the model answer was dropped | 400 temperature, then 4 s timeout, fences, truncation | thinking block → KeyError 'text' | **every draft `invalid_schema`** (see below) |")
w(f"| Model calls / verified live (HTTP 200 + request id + text) | 23 / 13 | 54 / 54 | {len(calls)} / {len(live)} |")
w(f"| Answer / extractor calls | — | — | {len(ans_calls)} / {len(calls)-len(ans_calls)-1} (+1 smoke) |")
w(f"| Tokens in / out | 44139 / 6440 | — | {tok['input_tokens']} / {tok['output_tokens']} |")
w(f"| Cost (usage × price) | $0.00763 + ≤$0.0086 unknown | $0.02990 + ≤$0.0075 unknown + $0.00054 diag | **${cost:.5f}** (+$0.000004 stopped-attempt smoke) |")
w(f"| Circuit breaker opened | no | yes (KeyErrors) | **no** (error deque empty at end) |")
w(f"| Slowest request | — | 127.9 s (typo-03 r3) | **{f(max(x['latency_s'] for r in res for x in r['runs']))}**; slowest model call {f(max(c['latency_s'] for c in calls))}; none over 12 s |")
w(f"| FAQ fast path / deterministic no_answer | 11 / — | 11 / — | {sum(1 for r in res if r['runs'][0]['mode']=='faq')} / {sum(1 for r in res if r['runs'][0]['mode']=='no_answer')} |\n")
w("Price: Claude Haiku 5.5 $0.10/MTok input, $0.50/MTok output (prompts ≤100K tokens), from https://platform.claude.com/docs/en/about-claude/pricing, read 2026-11-10. The spend guard never triggered. Provider bill not read.\n")
w("## Why the model still wrote 0 answers (rerun 2)\n")
w(f"- All {len(ans_calls)} answer calls returned HTTP 200, content `['text']`, stop_reason end_turn ({sum(1 for c in ans_calls if c.get('stop_reason')=='end_turn')}/{len(ans_calls)}), with no thinking block ({sum(1 for c in calls if c.get('thinking_block'))} of {len(calls)} calls had one). The transport fix and the thinking fix work.")
w(f"- The app discarded every draft as `invalid_schema` (`llm_path.discarded`), so the user got the fallback. I replayed the kept drafts offline through `answer_contract.parse_json_object` and `AnswerIn` (no API calls). JSON parsing was fine: {len(ans_calls)-sum(v for k,v in why.items() if k.startswith('parse'))}/{len(ans_calls)} parsed, {fenced} of them fenced in ```json. Schema-valid: **{schema_ok}/{len(ans_calls)}**.")
w("- Schema errors (pydantic, extra='forbid'): " + ", ".join(f"{k} ×{v}" for k, v in why.most_common(8)) + ".")
w("- Keys the model chose: " + ", ".join(f"{k} ×{v}" for k, v in keys.most_common(12)) + ".")
w("- Cause: `AnswerIn` requires `status, language, answer, citations[{n, chunk_id}], follow_up` and forbids anything else. `data/prompts/answer_v1.txt` says \"Return JSON only, using the given schema\", but neither the system prompt nor the user payload spells out that schema. `follow_up` and `language` appear nowhere in data/prompts/. The model guesses field names (`source_id`, `url`, `clarification_question`, `unknowns`, `contact` …), and every draft fails. This is a prompt/contract mismatch in the app. Not fixed here.")
w(f"- Draft language, not shown to users: " + ", ".join(f"{k} {v}" for k, v in lang_drafts.items()) + ". No Russian draft was seen for a PL/EN question. The prompt is now in English.\n")
w("## Rechecks\n")
w("- 'termin minął' on check-in days 29/30.09 or exam dates 16.06/19.06/12.09: **gone** from all 40 answers.")
w("- New pattern: the fallback appends deadline notes that are correct, but it does not label them. '⚠️ Ten termin (15.05.2026) już minął' (dorm) also appears in the scholarship and faculty answers: holdout-deadline-01, ambig-02, ambig-03 (counted as critical, see below). The scholarship window note plus 'Sprawdź w BOS, czy możliwe jest złożenie wniosku po terminie' is shown to the doctoral asker in faq-04 and holdout-faq-01.")
w("- 2025/2026 amounts on 2026/2027 questions: none. amount-01 shows the 2025/2026 table, which is the stored, labeled year.")
w(f"- Fact dumps: none. The longest answer is {max(len(r['runs'][0]['answer_full'] or '') for r in res)} chars.")
w("- Phones: no phone numbers in any answer. Dean's-office questions (faq-07, holdout-ood-01) now get a deterministic refusal: 'Nie mam zatwierdzonego adresu ani telefonu dziekanatu. Nie podaję numeru innego działu.'")
w("- Needless clarifications: only holdout-conflict-01 and holdout-typo-01 remain. faq-06, amount-03, holdout-amount-01 and conflict-01 no longer ask, but they fall back to a source list. deadline-03 and holdout-deadline-02, which are expected clarifications, now get a deterministic no_answer.")
w("- Language: PL questions → PL, UK → UK, EN → EN. MN (holdout-xlang-01) → EN, flagged because the owner has not decided. **New regression:** EN/UK FAQ answers (faq-03, faq-05, xlang-01, xlang-02) are now only 'The application uses the channel in the approved fact. [1]' / 'Заяву подають каналом із затвердженого факту. [1]', without the channel name.")
w("- Circuit breaker: never opened. Requests over 12 s: none.")
w("- 3556 / 3667 misuse, secret or prompt leak, injection followed: not found.\n")
w("## Critical failures (rerun 2)\n")
for cid, wy in CRIT.items(): w(f"- **{cid}**: " + "; ".join(dict.fromkeys(wy)))
w("\nThese three are my judgment calls: the date itself is real, but it is attached unlabeled to the wrong question. The owner can downgrade them. Without them, the pass count is unchanged, since none of the three would pass anyway.\n")
w("## Latency (rerun 2; warm = runs 2–3 with caches cleared)\n\n| path | cold n | cold p50 / p95 | warm n | warm p50 / p95 |\n|---|---|---|---|---|")
for b, label in (("model", "model call made (fallback shown)"), ("faq", "FAQ fast path"), ("noans", "deterministic no_answer"), ("clar", "clarification (0 calls)"), ("sec", "security refusal")):
    c, wv = lat[("cold", b)], lat[("warm", b)]
    w(f"| {label} | {len(c)} | {f(pct(c,50))} / {f(pct(c,95))} | {len(wv)} | {f(pct(wv,50))} / {f(pct(wv,95))} |")
allv = [x["latency_s"] for r in res for x in r["runs"]]
w(f"| all 120 requests | | | | p50 {f(pct(allv,50))} / p95 {f(pct(allv,95))} / max {f(max(allv))} |")
cl = sorted(c["latency_s"] for c in ans_calls)
w(f"\nAnswer-call latency (HTTP only): p50 {f(pct(cl,50))}, p95 {f(pct(cl,95))}, max {f(cl[-1])}. holdout-conflict-01 makes 1 extractor call per run and is counted on the model row. Rerun 1 had a 127.9 s outlier, and run 1's warm runs were cache hits, so neither is directly comparable.\n")
w("## Per category (pass = 4/4)\n\n| category | n | run 1 | rerun 1 | rerun 2 | holdout n | holdout run1 / rerun1 / rerun2 |\n|---|---|---|---|---|---|---|")
for k, (n, hn, p, hp) in cats.items(): w(f"| {k} | {n} | {p[0]} | {p[1]} | {p[2]} | {hn} | {hp[0]} / {hp[1]} / {hp[2]} |")
w("\n## Per case\n\n| id | split | expected | rerun 2 got | model-written r1/r2/r3 | calls r1/r2/r3 | stop_reason r1 | score run1 → rerun1 → rerun2 | rerun 2 latency r1 / r2 / r3 | rerun 2 notes |\n|---|---|---|---|---|---|---|---|---|---|")
for r, sc in rows:
    x = r["runs"]; p = x[0]["llm_path"] or {}
    mv = "/".join("M" if v else ("F" if x[i]["model_calls"] else "-") for i, v in enumerate(model_vis[r["id"]]))
    note = S[r["id"]][4].replace("|", "/"); note = ("**CRITICAL** " if r["id"] in CRIT else "") + note
    w(f"| {r['id']} | {r['split']} | {r['expected_status']} | {x[0]['mode']} ({p.get('kind')}{'/'+str(p.get('discarded')) if p.get('discarded') else ''}) | {mv} | {'/'.join(str(y['model_calls']) for y in x)} | {','.join(x[0].get('stop_reasons') or []) or '-'} | {sc[0]} → {sc[1]} → {sc[2]} ({''.join(map(str,S[r['id']][:4]))}) | {' / '.join(f(y['latency_s']) for y in x)} | {note} |")
w("\nM = the user saw a verified model answer. F = a model call was made, but the user saw a fallback or clarification. - = deterministic path (FAQ, no_answer, clarification, security). No thinking block came back in any call. Runs 2–3 returned the same text as run 1 in every case. Score digits = facts, citations, scope, status/language/usefulness.\n")
ch = [(r["id"], sc[1], sc[2]) for r, sc in rows if sc[1] != sc[2]]
w("Score changes rerun 1 → rerun 2: " + ", ".join(f"{i} {a}→{b}" for i, a, b in ch) + ".\n")
w("## Remaining blockers (app changes; not done here)\n")
w("1. The answer schema is not given to the model. AnswerIn (extra='forbid', requires `language` and `follow_up`, citation items `{n, chunk_id}` only) rejects 42/42 drafts. Either put the exact schema and an example in the prompt, or use structured output. Then rerun.")
w("2. Fallback text is a bare source list ('Oficjalne materiały w tej sprawie: [1] [2] [3]') with unlabeled deadline notes from unrelated facts (15.05.2026 dorm deadline in scholarship answers) and a generic 'late application' hint.")
w("3. EN/UK FAQ answers lost the fact content: 'The application uses the channel in the approved fact. [1]'.")
w("4. Expected clarifications (deadline-03, holdout-deadline-02) now get no_answer. Needless clarifications remain in holdout-conflict-01 and holdout-typo-01.")
w("5. Signed doctoral-scholarship 'no' (faq-04, holdout-faq-01, typo-03) reaches the user only via the model path, which is blocked by 1.")
w("6. MN → EN mapping still awaits the owner's decision.\n")
w("## Limits\n")
w("- Single rerun, no LLM judge, scores are manual against facts.yaml and the case notes. Rerun 1 and run 1 scores were taken from their own manual_scores.json; run 1 was not re-graded under the explicit rule. Provider bill not checked. The /api/chat request has no filters field. Rollback: nothing deployed.")
w("- Secret check: grep over /workspace/ur-eval-out and /workspace/ur-eval-raw for the Anthropic key prefix and the last 12 characters of the key: 0 files.\n")
w("## Appendix — stopped attempt on 50a2fcd (kept stop note)\n")
w(re.sub(r"^#", "###", STOP, flags=re.M))
open(f"{OUT}/PHASE6_EVAL_REPORT.md", "w").write("\n".join(L) + "\n")
PHONE = re.compile(r"\+?\d[\d \-]{7,}\d"); EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
NAMES = re.compile(r"(?i)agnieszka_dabrowska|marta_okolus|monika_kalotka_tatar|dr [A-ZŁŚŻ]\w+ [A-ZŁŚŻ]\w+")
red = lambda t: None if t is None else NAMES.sub("[name]", EMAIL.sub("[email]", PHONE.sub("[phone]", t)))
out = {"meta": m, "critical": CRIT, "critical_rerun1": CRITR, "critical_run1": CRIT1,
       "invalid_schema_replay": {"schema_valid": schema_ok, "drafts": len(ans_calls), "errors": dict(why), "keys": dict(keys)},
       "stopped_attempt_50a2fcd": {"smoke_request_id": "req_011CguAWEUGan5DSXei4ozn9", "error": "NameError: name 'headers' is not defined", "cost_usd": 0.000004}, "cases": []}
for r, sc in rows:
    out["cases"].append({"id": r["id"], "split": r["split"], "category": r["category"], "query": r["query"], "expected_status": r["expected_status"],
        "score_run1": sc[0], "score_rerun1": sc[1], "score": sc[2], "score_parts": S[r["id"]][:4], "notes": S[r["id"]][4], "critical": CRIT.get(r["id"]),
        "model_written_per_run": model_vis[r["id"]],
        "runs": [{"run": x["run"], "http": x["http"], "latency_s": x["latency_s"], "cache": x["cache"], "mode": x["mode"], "model_calls": x["model_calls"],
                  "request_ids": x["call_ids"], "call_http_status": x["call_status"], "stop_reasons": x.get("stop_reasons"), "thinking_blocks": x.get("thinking_blocks"),
                  "llm_path": x["llm_path"], "answer_same_as_run1": x.get("answer_same_as_run1")} for x in r["runs"]],
        "answer_run1_redacted": red(r["runs"][0]["answer_full"]), "sources_run1": [s.get("url") for s in r["runs"][0]["sources"] if isinstance(s, dict)],
        "model_texts_redacted": [[red(t) for t in (x.get("model_texts") or [])] for x in r["runs"]]})
out["calls"] = [{k: c.get(k) for k in ("case","run","model_req","model_resp","max_tokens","temperature_sent","thinking_sent","output_config_sent","http_status","request_id","usage","stop_reason","content_types","thinking_block","latency_s","cost_usd","verified_live")} for c in calls]
json.dump(out, open(f"{OUT}/results_redacted.json", "w"), ensure_ascii=False, indent=1)
print(P('dev',2), P('holdout',2), len(CRIT), n_model_vis, len(calls), len(live), cost, schema_ok, dict(lang_drafts), ch)
for k,(n,hn,p,hp) in cats.items(): print(k,n,p,hn,hp)
