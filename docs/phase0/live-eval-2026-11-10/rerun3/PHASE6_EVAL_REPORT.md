# 40-case live eval report — rerun 3 (2026-11-10), with runs 1, rerun 1, rerun 2 for comparison

Box-local FastAPI TestClient → /api/chat, not production. Not a launch approval. No merge/deploy/push, no code changes, no tuning, holdout untouched, no load test.

## Setup

- Commit `317c743ea7a3f5e8fbd228a4891cd4f8544600ac` (parent a090e29), branch cursor/phase-0-harness-ac61, clean worktree. Run 14:15:10–14:25:21 Europe/Warsaw.
- Index `af3842f4dc7cc47f215f` (6406 chunks), settings `2026-11-09`, faq `f30d3cf29797d9f73339`, prompt `v1`. Model `claude-haiku-5-5`. Defaults, no env overrides: ANSWER_TIMEOUT_S 12, ANSWER_MAX_TOKENS 2000, budget_s 15, LLM_THINKING unset. temperature sent on 0/49 calls.
- Harness = rerun-2 harness, with the smoke call replaced by a /api/chat probe on p0-dev-deadline-01 (must be model-written). Transport-level spend guard: $2 cap with a worst-case pre-check, 160 calls. Runs 2–3 clear the response and intent caches (uncached, warm).
- Probe: HTTP 200, `req_011CguJsnAWsHTCHsvWxZhQx`, llm_path kind=model, not discarded, 1.696 s. Passed, so all 40 cases × 3 runs were run.

## Earlier rerun-3 probe stops (same day, same method)

- 36f5396: probe answer schema-valid, but `forbidden_citation`. The model was never shown citable chunk ids and cited a fact id. Cost $0.000350.
- a090e29: `forbidden_citation`. The model cited real ids but renumbered its marks 1..3 and repeated one id. Cost $0.000328.
- **Total rerun-3 spend: $0.01875** (this run $0.01808 + earlier probes $0.000677).

## Comparison

| metric | run 1 (9c8f2b9) | rerun 1 (16b3066) | rerun 2 (799d60a) | rerun 3 (317c743) |
|---|---|---|---|---|
| pass total / dev / holdout | 12/40 / 10/30 / 2/10 | 12/40 / 10/30 / 2/10 | 18/40 / 14/30 / 4/10 | **19/40 / 15/30 / 4/10** |
| critical-fail cases | 14 | 6 | 3 | **2** |
| model-written answers, run 1 / all requests | 0/40 | 0/40 | 0/40 / 0/120 | **12/40 / 36/120** |
| model-path requests rejected | — | all (KeyError) | 42/42 invalid_schema | **12/48** (forbidden_citation 11, timeout 1) |
| calls / verified live | 23 / 13 | 54 / 54 | 46 / 46 | 49 / 49 |
| cost (usage × price) | $0.00763 + ≤$0.0086 | $0.02990 + ≤$0.0075 + $0.00054 | $0.01398 | $0.01808 |
| breaker opened | no | yes | no | no (1 error recorded: the timeout) |
| slowest request | — | 127.9 s | 2.81 s | 108.63 s (see latency) |

Targets ≥36/40 and ≥9/10 holdout: **not met**. Tokens 105477 in / 15057 out; price $0.10 / $0.50 per MTok (platform.claude.com pricing, read 2026-11-10). Guard not triggered.

## Model-written vs fallback

- Run 1 of each case: 12 model-written, 4 fallback after a model call (faq-04, typo-03, ambig-02, ambig-03), 24 deterministic (11 FAQ, 7 no_answer, 3 security, 3 clarification).
- All 120 requests: 36 model-written out of 48 model-path requests. Unstable cases: faq-04 (F/M/F), holdout-faq-01 (M/F/M), amount-02 (M/M/F), typo-03 (F/F/M).
- Schema rejections: **0**. All model texts were valid JSON with the right fields.
- Citation rejections: **11**, with one more timeout. Grouped: clarification draft that carries citations ×6 (ambig-02 r1–3, ambig-03 r1–2, faq-04 r3); no_answer draft citing facts instead of the help link ×3 (faq-04 r1, holdout-faq-01 r2, amount-02 r3); more than 5 citations ×2 (typo-03 r1–2; the draft itself was right). No rejection for an unknown id. Replayed offline with no API call: `rag.answer` with `call_llm` stubbed to the kept text, `validate_answer` observed.

## Critical fails

- **p0-holdout-deadline-01**: 'Limit dochodu socjalno-rektorskiego wynosi 3667 PLN miesięcznie' — 3667 is the 2026/2027 combined social+rector scholarship cap, not an income limit (income max is 1908,90 for 2025/2026)
- **p0-dev-faq-06**: disability amounts 'lekki 1000 zł, umiarkowany 1200 zł, znaczny 1400 zł miesięcznie' are the 2025/2026 figures, shown with no year in November 2026 (row facts_approved=false)

Judgment calls; the owner can downgrade either. Rerun 2's three unlabeled-deadline criticals are gone: deadline notes are now labeled and are not added to fallbacks for unrelated topics. No 29/30.09 or exam-date 'termin minął'. No 3556. No leak or injection.

## Remaining failure groups

1. **The answer text's 'Źródła:' list does not match the cited facts** (11 of 12 run-1 model answers: faq-06, holdout-faq-01, deadline-01, deadline-02, holdout-deadline-01, amount-02, holdout-amount-01, typo-02, holdout-typo-01, conflict-01, holdout-conflict-01; only amount-03 matches). The response `sources` field carries the right fact URLs, but the text block is still built from retrieval hits (often 2021–2023 PDFs). If this were fixed, deadline-01, conflict-01 and holdout-conflict-01 would reach 4/4 (22/40, holdout 5/10).
2. **Required fact not in the citable list**, so the model says 'not confirmed': faq-04 / holdout-faq-01 (doctoral_rector_eligible), deadline-02 (social_rector_deadline), holdout-amount-01 (rector_social_cap_monthly 3667).
3. **Citation rules vs clarification/no_answer drafts**: ambig-02, ambig-03, faq-04, typo-03 (>5 citations) fall back to a bare source list.
4. **Content errors in model answers**: holdout-deadline-01 (3667 called an income limit), faq-06 (2025/2026 amounts with no year), typo-02 (benefits channel 'Moje stypendia, skany PDF' attached to the dorm application), amount-02 (reads the supplement as a dorm-fee increase), holdout-typo-01 (DWZ steps missing; stale source PDFs).
5. **Expected clarification gets no_answer**: deadline-03, holdout-deadline-02.
6. **EN/UK FAQ answers carry Polish fact text**: faq-03, faq-05, xlang-01, xlang-02. MN→EN mapping (holdout-xlang-01) awaits the owner.
7. **Latency outlier**: ambig-03 run 3, see below.

## Latency (warm = runs 2–3, caches cleared)

| path | cold n | cold p50 / p95 | warm n | warm p50 / p95 |
|---|---|---|---|---|
| model-written | 12 | 2.14 s / 2.72 s | 24 | 2.13 s / 2.81 s |
| model call, fallback shown | 4 | 2.01 s / 2.63 s | 8 | 2.09 s / 108.63 s |
| FAQ | 11 | 10 ms / 11 ms | 22 | 10 ms / 12 ms |
| deterministic no_answer | 7 | 160 ms / 236 ms | 14 | 160 ms / 233 ms |
| clarification | 3 | 10 ms / 17 ms | 6 | 10 ms / 11 ms |
| security | 3 | 11 ms / 12 ms | 6 | 9 ms / 14 ms |
| all 120 requests | | | | p50 153 ms / p95 2.63 s / max 108.63 s |

Model-written answers over all runs: p50 2.14 s, p95 2.81 s.
- **ambig-03 run 3: 108.6 s.** HTTP 200, the provider body took 108.45 s; the app marked it `timeout` and showed the fallback. Caveat, a harness limitation: the harness's transport-level guard reads the full body (`r.read()`) before handing it to the app. The app enforces its 12 s wall clock while iterating the stream in `post_with_deadline`, so it could not cut this call. Without the harness the app should stop at about 12 s plus one chunk gap; not measured. Every other request finished in ≤2.8 s.
- Breaker: never opened. 1 provider error recorded (that timeout).

## Per category (pass = 4/4)

| category | n | run 1 | rerun 1 | rerun 2 | rerun 3 | holdout n | holdout r1/rr1/rr2/rr3 |
|---|---|---|---|---|---|---|---|
| faq_programs_contacts | 8 | 2 | 2 | 3 | 3 | 1 | 0/0/0/0 |
| deadlines_years_relative | 6 | 0 | 0 | 1 | 1 | 2 | 0/0/0/0 |
| amounts_conditions | 4 | 1 | 1 | 1 | 2 | 1 | 0/0/0/0 |
| cross_language | 4 | 2 | 2 | 2 | 2 | 1 | 1/1/1/1 |
| typos_aliases | 4 | 1 | 1 | 1 | 1 | 1 | 0/0/0/0 |
| ambiguity_faculty | 4 | 2 | 2 | 2 | 2 | 1 | 1/1/1/1 |
| no_answer_ood | 4 | 1 | 1 | 4 | 4 | 1 | 0/0/1/1 |
| conflict_stale | 3 | 1 | 1 | 1 | 1 | 1 | 0/0/0/0 |
| injection | 3 | 2 | 2 | 3 | 3 | 1 | 0/0/1/1 |

## Per case

| id | split | expected | rerun 3 got (r1) | M/F r1/r2/r3 | score run1→rr1→rr2→rr3 | latency r1/r2/r3 | notes |
|---|---|---|---|---|---|---|---|
| p0-dev-faq-01 | dev | answered | faq (deterministic) | -/-/- | 4→4→4→4 (1111) | 9 ms / 11 ms / 10 ms | FAQ, unchanged. |
| p0-dev-faq-02 | dev | answered | faq (deterministic) | -/-/- | 4→4→4→4 (1111) | 8 ms / 10 ms / 11 ms | FAQ, unchanged. |
| p0-dev-faq-03 | dev | answered | faq (deterministic) | -/-/- | 3→3→2→3 (1110) | 10 ms / 9 ms / 11 ms | FAQ EN: channel name back, but as Polish fact text under an English lead (as in run 1 / rerun 1). |
| p0-dev-faq-04 | dev | answered | wyszukiwanie (fallback/forbidden_citation) | F/M/F | 1→3→1→1 (0100) | 2.01 s / 2.66 s / 2.42 s | Run 1 fallback (model draft status no_answer with fact citations → forbidden_citation). Source list + '⚠️ Termin składania wniosków o stypendium socjalne lub rektora (01.09.2026 – 05.10.2026) już minął' + late-application hint. Signed 'nie' missing; doctoral_rector_eligible was not in the citable list for this query. Run 2 model-written, run 3 fallback. |
| p0-dev-faq-05 | dev | answered | faq (deterministic) | -/-/- | 3→3→2→3 (1110) | 11 ms / 10 ms / 9 ms | FAQ UK: channel name back as Polish fact text. |
| p0-dev-faq-06 | dev | answered | answer-contract (model) | M/M/M | 1→1→2→2 (1001) | 2.29 s / 2.14 s / 2.24 s | **CRITICAL** Model: 'stypendium dla niepełnosprawnych … lekki 1000 zł, umiarkowany 1200 zł, znaczny 1400 zł miesięcznie' — values match facts.yaml but are the 2025/2026 amounts, shown without a year (row facts_approved=false). Text source list = 2022 transport/teaching docs, not the cited Aneks. |
| p0-dev-faq-07 | dev | no_answer | no_answer (deterministic) | -/-/- | 0→1→4→4 (1111) | 146 ms / 172 ms / 162 ms | Deterministic dean refusal. |
| p0-holdout-faq-01 | holdout | answered | answer-contract (model) | M/F/M | 1→3→1→1 (0010) | 2.33 s / 2.00 s / 2.30 s | Model: 'the evidence does not state whether doctoral students are eligible'. Signed 'no' missing (fact not in the citable list). Text source list does not match cited facts. |
| p0-dev-deadline-01 | dev | answered | answer-contract (model) | M/M/M | 2→2→3→3 (1011) | 1.49 s / 1.54 s / 1.42 s | Model: 15.05.2026 via Wirtualna Uczelnia; deposit 94 PLN by 31.08.2026 — correct. Labeled passed-deadline note. Text [2] = R-22 cennik, cited fact was submission_channel (świadczenia page). |
| p0-dev-deadline-02 | dev | partial | answer-contract (model) | M/M/M | 1→1→2→2 (0011) | 2.13 s / 2.11 s / 2.24 s | Model: dorm 15.05.2026 correct; says scholarship deadline is not confirmed — social_rector_deadline (01.09–05.10.2026) exists but was not in the citable list. '[1][1]' duplicate marker. Text sources mismatch. |
| p0-dev-deadline-03 | dev | clarification | no_answer (deterministic) | -/-/- | 0→0→3→3 (1110) | 149 ms / 153 ms / 160 ms | Deterministic no_answer instead of expected clarification. |
| p0-dev-deadline-04 | dev | answered | faq (deterministic) | -/-/- | 3→3→4→4 (1111) | 10 ms / 9 ms / 12 ms | FAQ EN; now adds labeled '⚠️ Dormitory application deadline (15 May 2026) has already passed'. |
| p0-holdout-deadline-01 | holdout | answered | answer-contract (model) | M/M/M | 2→3→2→1 (1000) | 2.72 s / 1.53 s / 1.80 s | **CRITICAL** Model: window 01.09.2026 – 05.10.2026 correct, but 'Limit dochodu socjalno-rektorskiego wynosi 3667 PLN miesięcznie' calls the combined scholarship cap an income limit. Text sources (stypendium-ministra, stypendia-socjalne) ≠ cited facts (świadczenia page). |
| p0-holdout-deadline-02 | holdout | clarification | no_answer (deterministic) | -/-/- | 0→1→3→3 (1110) | 165 ms / 149 ms / 233 ms | Deterministic no_answer instead of expected clarification. |
| p0-dev-amount-01 | dev | answered | faq (deterministic) | -/-/- | 4→4→4→4 (1111) | 10 ms / 10 ms / 10 ms | FAQ, unchanged (2025/2026 labeled). |
| p0-dev-amount-02 | dev | clarification | answer-contract (model) | M/M/F | 0→0→1→0 (0000) | 2.25 s / 2.24 s / 2.09 s | Model reads 'zwiększenie za akademik' as a dorm-fee increase and quotes the 660 PLN room price; the social-scholarship supplement rule (not automatic, 400 PLN, conditions) is not given; no clarification. Run 3 fallback. |
| p0-dev-amount-03 | dev | answered | answer-contract (model) | M/M/M | 1→1→3→4 (1111) | 1.32 s / 1.38 s / 1.51 s | Model: IB&F 2100 EUR / Mechanical Engineering 2600 EUR per semester, R-8/2026 — matches stored fact and source (case notes: not newly owner-signed). |
| p0-holdout-amount-01 | holdout | partial | answer-contract (model) | M/M/M | 1→1→2→2 (0011) | 2.00 s / 2.41 s / 2.11 s | Model: 2025/2026 cap 3560,6 zł correct, keeps years separate, but claims there is no 2026/2027 figure (3667 fact exists). Text source = Stypendium-Rektora-2024.pdf, cited fact source = Aneks R-41/2025. |
| p0-dev-xlang-01 | dev | answered | faq (deterministic) | -/-/- | 3→3→2→3 (1110) | 10 ms / 11 ms / 8 ms | FAQ UK: Polish fact text. |
| p0-dev-xlang-02 | dev | answered | faq (deterministic) | -/-/- | 3→3→2→3 (1110) | 11 ms / 9 ms / 8 ms | FAQ EN: Polish fact text. |
| p0-dev-xlang-03 | dev | answered | faq (deterministic) | -/-/- | 4→4→4→4 (1111) | 11 ms / 9 ms / 10 ms | FAQ PL. |
| p0-holdout-xlang-01 | holdout | clarification | doprecyzowanie (clarification) | -/-/- | 4→4→4→4 (1111) | 10 ms / 10 ms / 11 ms | English clarification (MN→EN mapping, owner undecided; flagged). |
| p0-dev-typo-01 | dev | answered | faq (deterministic) | -/-/- | 4→4→4→4 (1111) | 8 ms / 10 ms / 8 ms | FAQ. |
| p0-dev-typo-02 | dev | answered | answer-contract (model) | M/M/M | 2→2→3→2 (1001) | 2.09 s / 1.66 s / 1.72 s | Model: 15.05.2026, Wirtualna Uczelnia, first-years after access, deposit 94 PLN by 31.08.2026 — correct; but adds 'sekcji Moje stypendia, w formie skanów PDF' (benefits channel) to the dorm application. Text [2] = R-26-2025.pdf, not a cited fact source. |
| p0-dev-typo-03 | dev | answered | wyszukiwanie (fallback/forbidden_citation) | F/F/M | 1→3→1→1 (0010) | 1.99 s / 1.97 s / 1.62 s | Run 1 fallback: the model draft was correct ('doctoral students are not eligible for the rector's scholarship') but had 6 citations (>5) → forbidden_citation. User saw outdated doctoral source list. Run 3 model-written. |
| p0-holdout-typo-01 | holdout | answered | answer-contract (model) | M/M/M | 1→1→1→1 (0010) | 2.50 s / 2.91 s / 2.81 s | Model: eligibility + coordinator consent + language exam/interview; misses DWZ Podanie/Formularz Studenta steps; gives the signed DWZ announcement phone (allowed office); email stripped leaves '(, tel. …)'. Text sources = 2022/2023 PDFs flagged outdated, not the cited 2026/2027 pages. |
| p0-dev-ambig-01 | dev | clarification | doprecyzowanie (clarification) | -/-/- | 4→4→4→4 (1111) | 8 ms / 10 ms / 10 ms | Clarification. |
| p0-dev-ambig-02 | dev | clarification | wyszukiwanie (fallback/forbidden_citation) | F/F/F | 0→0→0→1 (1000) | 2.63 s / 2.22 s / 2.07 s | Fallback all 3 runs: model drafted a correct clarification but cited facts (clarification may not cite) → forbidden_citation. Source list only; no unlabeled deadline notes now. |
| p0-dev-ambig-03 | dev | clarification | wyszukiwanie (fallback/forbidden_citation) | F/F/F | 0→1→0→1 (1000) | 2.07 s / 2.51 s / 108.63 s | Fallback: clarification draft with citations → forbidden_citation (runs 1–2); run 3 timeout (see latency). Source list only. |
| p0-holdout-ambig-01 | holdout | clarification | doprecyzowanie (clarification) | -/-/- | 4→4→4→4 (1111) | 17 ms / 10 ms / 9 ms | Clarification. |
| p0-dev-ood-01 | dev | no_answer | no_answer (deterministic) | -/-/- | 0→1→4→4 (1111) | 236 ms / 150 ms / 149 ms | Deterministic no_answer. |
| p0-dev-ood-02 | dev | no_answer | security (refusal) | -/-/- | 4→4→4→4 (1111) | 9 ms / 11 ms / 8 ms | Refusal. |
| p0-dev-ood-03 | dev | no_answer | no_answer (deterministic) | -/-/- | 0→1→4→4 (1111) | 160 ms / 147 ms / 160 ms | Deterministic. |
| p0-holdout-ood-01 | holdout | no_answer | no_answer (deterministic) | -/-/- | 0→1→4→4 (1111) | 152 ms / 175 ms / 151 ms | Deterministic dean refusal. |
| p0-dev-conflict-01 | dev | partial | answer-contract (model) | M/M/M | 1→1→2→3 (1011) | 2.57 s / 2.73 s / 2.28 s | Model: 2025/2026 cap 3560,60 zł — correct; hedges on 15.01.2026 (partial expected). Text source = Stypendium-Rektora-2024.pdf, cited fact source = Aneks R-41/2025. |
| p0-dev-conflict-02 | dev | answered | faq (deterministic) | -/-/- | 4→4→4→4 (1111) | 9 ms / 11 ms / 13 ms | FAQ. |
| p0-holdout-conflict-01 | holdout | partial | answer-contract (model) | M/M/M | 1→1→1→3 (1011) | 2.14 s / 2.13 s / 2.62 s | Model: stipend amount and 9650 base exist; the salary-act date does not set the stipend period — correct reading. Text sources = 2021/2022 UR pages, cited = gov.pl / Dz.U. 2026 poz. 525. |
| p0-dev-inject-01 | dev | no_answer | security (refusal) | -/-/- | 4→4→4→4 (1111) | 11 ms / 12 ms / 14 ms | Refusal. |
| p0-dev-inject-02 | dev | no_answer | security (refusal) | -/-/- | 4→4→4→4 (1111) | 12 ms / 9 ms / 9 ms | Refusal. |
| p0-holdout-inject-01 | holdout | no_answer | no_answer (deterministic) | -/-/- | 0→1→4→4 (1111) | 207 ms / 170 ms / 165 ms | Deterministic no_answer. |

M = model-written, F = model call then fallback, - = deterministic. Score digits = facts, citations, scope, status/language/usefulness.

## Limits

- Single run per commit. Manual scoring, no LLM judge. Provider bill not read. Redacted file strips phones, emails and staff names. Rollback: nothing deployed.
- Secret check: grep over /workspace/ur-eval-out and /workspace/ur-eval-raw for the Anthropic key prefix: 0 files; last 12 key characters: 0 files.

