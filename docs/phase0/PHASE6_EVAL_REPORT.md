# 40-case live eval report — run 1 and rerun (2026-11-10)

Both runs: box-local FastAPI TestClient → /api/chat, not production. Not a launch approval. No merge, deploy or push, no app code changes, no tuning, no 10-concurrent load test.

## Setup

| | run 1 | rerun |
|---|---|---|
| commit | `9c8f2b912a468902b9bd5fcd2b8aaadf18629717` | `16b30661a2fc00146278c1fcd21d17d54e9cfbc2` |
| time (Europe/Warsaw) | 11:06:20–11:14:10 | 11:42:45–11:57:18 |
| model | claude-haiku-5-5 | claude-haiku-5-5 |
| index / settings / faq / prompt | af3842f4dc7cc47f215f / 2026-11-09 / f30d3cf29797d9f73339 / v1 | af3842f4dc7cc47f215f / 2026-11-09 / f30d3cf29797d9f73339 / v1 |
| answer timeout / max tokens / budget_s | 4 s / 700 / 6 | 12 s / 1200 / 15 (manifest defaults, no env override) |
| context caps | context_max_tokens 4500 | context_chunks 3, chunk_chars 400, fact_cards_max 4, card_chars 240, context_max_tokens 4500 |
| temperature on the wire | stripped by harness shim on 23 calls | **app omitted it alone: 0/57 requests carried `temperature`** (no shim, LLM_SEND_TEMPERATURE unset) |
| repeats 2–3 | response-cache hits | public response cache and intent cache cleared in-process before runs 2 and 3. Same warm process, so this is uncached warm latency |
| EXTRACTOR_LLM | unset (default on) | unset (default on) |

## Headline

| metric | run 1 | rerun |
|---|---|---|
| Pass dev / holdout / total | 10/30 / 2/10 / 12/40 | **10/30 / 2/10 / 12/40** |
| Critical-fail cases | 14 | **6** |
| User-visible answer written by the model (verified), run 1 / all 120 requests | 0/40 / 0/120 | **0/40 / 0/120** |
| Model calls (incl. smoke) / verified live | 23 / 13 | 57 / 54 |
| Answer calls: HTTP 200 / timeout | 6 / 8 | 40 / 1 |
| Tokens in / out | 44139 / 6440 | 79550 / 43882 |
| Cost (usage × price; provider bill not read) | $0.00763 (+≤$0.0086 unknown for 8 timeouts) | $0.02990 (+≤$0.0075 worst case for 1 timeout) + diagnostic call $0.00054 |
| FAQ fast path | 11/40 | 11/40 |

Price: Claude Haiku 5.5 $0.10/MTok input, $0.50/MTok output (≤100K prompt), from https://platform.claude.com/docs/en/about-claude/pricing, read 2026-11-10. The spend guard (cap $2.00, 160 calls) never triggered. Harness-counted spend including the timeout worst case: $0.03378.

## Why the model still wrote 0 answers

- New blocker: Haiku 5.5 returns a `thinking` content block before the `text` block. `app/rag.py` call_llm does `payload["content"][0]["text"]`, which raises KeyError: 'text'. The answer path catches it as a provider exception (`discarded=exception`), so every answer call that returned HTTP 200 (40 of them; the harness kept text for 38) was thrown away. I confirmed this with one extra diagnostic call outside the harness: 1768 in / 727 out tokens, 485 of them thinking tokens, traceback at rag.py line 1166. Its request id was not captured.
- The slot-extractor calls returned text first and were accepted.
- Those KeyErrors count as provider errors, so the circuit breaker opened (5 errors in 30 s). p0-dev-ambig-03 run 3, then all runs of p0-dev-ood-01, p0-dev-ood-03 and p0-holdout-ood-01 got `provider_pause` with 0 calls.
- p0-dev-typo-03 run 3: ReadTimeout after 127.9 s wall time, well above the 12 s timeout and the 15 s budget. The httpx timeout is per read, not total.
- Draft quality, not shown to users: 8/38 kept answer drafts contain Russian text (the answer prompt is in Russian). For example, the p0-holdout-inject-01 draft for a Polish question was in Russian. 14 answer calls still stopped at max_tokens=1200.

## Rechecked run-1 critical issues

- 29.09.2026 'termin minął': gone. **Replaced by '⚠️ Ten termin (30.09.2026) już minął'**, which is also a check-in day, taken from the dorm page quote. Still critical in p0-dev-deadline-01, -deadline-02, -amount-02, -typo-02, -ambig-02.
- Exam dates called deadlines: **still present** in p0-dev-deadline-03 (16.06, 19.06, 12.09.2026).
- 2025/2026 amounts on a 2026/2027 question (p0-holdout-deadline-01): **fixed**. No 2025/2026 amount is shown. The fact cards are now Erasmus+ instead.
- Full fact dump: **fixed**. At most 3 fact cards and 3 quotes; longest run-1 answer is 5087 chars (run 1 of the first eval: ~12.5k).
- DWZ phones on dean's-office questions: **fixed**. No phone numbers in any answer. The dean questions still get irrelevant quotes instead of a refusal.
- Needless status questions: **removed** for faq-04, holdout-faq-01, typo-03, holdout-typo-01, conflict-01 and holdout-amount-01. The last three now ask for level or year instead of answering. Still asked in faq-06, amount-03 and holdout-conflict-01. In holdout-ambig-01 (tuition) and holdout-xlang-01 the clarification is expected.
- Not found: 3556, 3667 as a 2025/2026 figure, a secret or prompt leak, an amount outside facts.yaml after injection.

## Critical failures (rerun)

- **p0-dev-deadline-01**: check-in day 30.09.2026 shown as '⚠️ Ten termin (30.09.2026) już minął'
- **p0-dev-deadline-02**: check-in day 30.09.2026 shown as '⚠️ Ten termin (30.09.2026) już minął'
- **p0-dev-amount-02**: check-in day 30.09.2026 shown as '⚠️ Ten termin (30.09.2026) już minął'
- **p0-dev-typo-02**: check-in day 30.09.2026 shown as '⚠️ Ten termin (30.09.2026) już minął'
- **p0-dev-ambig-02**: check-in day 30.09.2026 shown as '⚠️ Ten termin (30.09.2026) już minął'
- **p0-dev-deadline-03**: exam-session dates 16.06.2026 / 19.06.2026 / 12.09.2026 shown as 'Ten termin … już minął'

## Latency (rerun; warm = runs 2–3 with caches cleared)

| path | cold n | cold p50 / p95 | warm n | warm p50 / p95 |
|---|---|---|---|---|
| model call made (fallback shown) | 19 | 4.26 s / 6.73 s | 37 | 5.19 s / 6.96 s |
| no call: FAQ / security / clarification | 18 | 9 ms / 52 ms | 36 | 10 ms / 19 ms |
| breaker paused, no call | 3 | 176 ms / 217 ms | 7 | 174 ms / 243 ms |
| FAQ fast path only | 11 | 9 ms / 52 ms | 22 | 10 ms / 15 ms |
| all requests | | | 120 | overall p50 176 ms / p95 6.66 s |

Model-path latency includes the model call, which returned HTTP 200 but was then discarded, so the user waited for a fallback. Run-1 cold model path was 3.87 s / 4.25 s, and its warm runs were cache hits (8 ms / 11 ms), so they are not comparable. All 3 runs per case fit the budget.

## Per category (pass = 4/4)

| category | run 1 pass | rerun pass | run 1 holdout | rerun holdout |
|---|---|---|---|---|
| faq_programs_contacts | 2/8 | 2/8 | 0/1 | 0/1 |
| deadlines_years_relative | 0/6 | 0/6 | 0/2 | 0/2 |
| amounts_conditions | 1/4 | 1/4 | 0/1 | 0/1 |
| cross_language | 2/4 | 2/4 | 1/1 | 1/1 |
| typos_aliases | 1/4 | 1/4 | 0/1 | 0/1 |
| ambiguity_faculty | 2/4 | 2/4 | 1/1 | 1/1 |
| no_answer_ood | 1/4 | 1/4 | 0/1 | 0/1 |
| conflict_stale | 1/3 | 1/3 | 0/1 | 0/1 |
| injection | 2/3 | 2/3 | 0/1 | 0/1 |

## Per case (run 1 of each eval is the quality run)

| id | split | expected | rerun got | model-written r1/r2/r3 | calls r1/r2/r3 | score run1 → rerun | rerun latency r1 / r2 / r3 | rerun notes |
|---|---|---|---|---|---|---|---|---|
| p0-dev-faq-01 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | 4 → 4 (1111) | 52 ms / 10 ms / 10 ms | FAQ path, unchanged from run 1. |
| p0-dev-faq-02 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | 4 → 4 (1111) | 9 ms / 10 ms / 9 ms | FAQ path, unchanged. |
| p0-dev-faq-03 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | 3 → 3 (1110) | 8 ms / 9 ms / 9 ms | FAQ path, unchanged: Polish prose inside EN answer. |
| p0-dev-faq-04 | dev | answered | wyszukiwanie (fallback/exception) | F/F/F | 1/1/1 | 1 → 3 (1110) | 6.45 s / 6.39 s / 6.70 s | No status question now. Model call HTTP 200 but discarded (app KeyError on thinking block) → fallback: '[F1] Czy doktorant może dostać stypendium rektora: nie (2026/2027)' + R-32 URL, plus doctoral-stipend amount cards; banner 'Model językowy chwilowo niedostępny'. |
| p0-dev-faq-05 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | 3 → 3 (1110) | 10 ms / 10 ms / 12 ms | FAQ path, unchanged: Polish prose in UK answer. |
| p0-dev-faq-06 | dev | answered | doprecyzowanie (clarification) | F/F/F | 1/1/1 | 1 → 1 (0010) | 2.96 s / 2.38 s / 2.78 s | Unchanged: status clarification (facts_approved=false row). |
| p0-dev-faq-07 | dev | no_answer | wyszukiwanie (fallback/exception) | F/F/F | 1/1/1 | 0 → 1 (1000) | 2.76 s / 3.11 s / 3.42 s | Expected no_answer. Fallback of 3 irrelevant chunk quotes (MOPS form, WFP rules). No fact dump, no DWZ phones, no invented dean contact. |
| p0-holdout-faq-01 | holdout | answered | wyszukiwanie (fallback/exception) | F/F/F | 1/1/1 | 1 → 3 (1110) | 6.58 s / 5.42 s / 6.36 s | No status question. Fallback in EN with 'nie (2026/2027)' left in Polish, plus stipend amounts; banner. |
| p0-dev-deadline-01 | dev | answered | wyszukiwanie (fallback/exception) | F/F/F | 1/1/1 | 2 → 2 (1100) | 6.66 s / 6.69 s / 6.78 s | **CRITICAL** Fallback (KeyError). 2026-05-15 and domy-studenckie URL present. 29.09 note gone, but now '⚠️ Ten termin (30.09.2026) już minął' — 30.09 is also a check-in day. |
| p0-dev-deadline-02 | dev | partial | wyszukiwanie (fallback/exception) | F/F/F | 1/1/1 | 1 → 1 (0100) | 5.84 s / 6.40 s / 6.37 s | **CRITICAL** Same text as deadline-01: dorm only, scholarship window missing, 30.09.2026 as passed termin. |
| p0-dev-deadline-03 | dev | clarification | wyszukiwanie (fallback/exception) | F/F/F | 1/1/1 | 0 → 0 (0000) | 3.69 s / 5.77 s / 5.19 s | **CRITICAL** Expected clarification. Fallback quotes exam-session timetable and adds 'Ten termin (16.06.2026) / (19.06.2026) / (12.09.2026) już minął'. |
| p0-dev-deadline-04 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | 3 → 3 (1110) | 9 ms / 9 ms / 8 ms | FAQ path, unchanged: Polish summary line in EN answer. |
| p0-holdout-deadline-01 | holdout | answered | wyszukiwanie (fallback/exception) | F/F/F | 1/1/1 | 2 → 3 (1110) | 6.73 s / 6.46 s / 5.84 s | Fallback. No 2025/2026 amounts now. Window appears in a quote from Stypendia socjalne ('od 01.09.2026 do 05.10.2026') and in a correct 'już minął' note, but the 3 fact cards are Erasmus+ (wrong topic). |
| p0-holdout-deadline-02 | holdout | clarification | wyszukiwanie (fallback/exception) | F/F/F | 1/1/1 | 0 → 1 (1000) | 3.61 s / 4.44 s / 4.23 s | Expected clarification. Fallback of irrelevant quotes (foreigner admission, fees). No deadline note, nothing invented. |
| p0-dev-amount-01 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | 4 → 4 (1111) | 9 ms / 15 ms / 10 ms | FAQ path, unchanged. |
| p0-dev-amount-02 | dev | clarification | wyszukiwanie (fallback/exception) | F/F/F | 1/1/1 | 0 → 0 (0000) | 6.65 s / 6.23 s / 6.47 s | **CRITICAL** Expected clarification with the not-automatic rule. Fallback: dorm prices, channel, dorm deadline; rule not shown; 30.09.2026 as passed termin. |
| p0-dev-amount-03 | dev | answered | doprecyzowanie (clarification) | F/F/F | 1/1/1 | 1 → 1 (0010) | 1.84 s / 1.86 s / 1.41 s | Unchanged: status clarification. |
| p0-holdout-amount-01 | holdout | partial | doprecyzowanie (clarification) | F/F/F | 1/1/1 | 1 → 1 (0010) | 1.67 s / 1.55 s / 2.29 s | Status question removed, but still a clarification (level) instead of the expected partial answer that the caps are separate. |
| p0-dev-xlang-01 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | 3 → 3 (1110) | 8 ms / 19 ms / 8 ms | FAQ path, unchanged. |
| p0-dev-xlang-02 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | 3 → 3 (1110) | 9 ms / 9 ms / 9 ms | FAQ path, unchanged. |
| p0-dev-xlang-03 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | 4 → 4 (1111) | 10 ms / 9 ms / 11 ms | FAQ path, unchanged. |
| p0-holdout-xlang-01 | holdout | clarification | doprecyzowanie (clarification) | -/-/- | 0/0/0 | 4 → 4 (1111) | 10 ms / 10 ms / 10 ms | Unchanged English clarification, 0 calls. FLAG: MN-vs-EN answer language still an open owner decision. |
| p0-dev-typo-01 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | 4 → 4 (1111) | 9 ms / 10 ms / 8 ms | FAQ path, unchanged. |
| p0-dev-typo-02 | dev | answered | wyszukiwanie (fallback/exception) | F/F/F | 1/1/1 | 2 → 2 (1100) | 6.48 s / 6.96 s / 6.63 s | **CRITICAL** Same as deadline-01 (30.09.2026 as passed termin). |
| p0-dev-typo-03 | dev | answered | wyszukiwanie (fallback/exception) | F/F/F | 1/1/1 | 1 → 3 (1110) | 4.06 s / 5.58 s / 127.89 s | No status question. EN fallback with 'nie (2026/2027)' in Polish, stipend amounts, 'may be outdated' warnings. |
| p0-holdout-typo-01 | holdout | answered | doprecyzowanie (clarification) | -/-/- | 0/0/0 | 1 → 1 (0010) | 8 ms / 927 ms / 13 ms | Status removed, but still a clarification (level, year) instead of the 2026/2027 Erasmus steps. 0 calls. |
| p0-dev-ambig-01 | dev | clarification | doprecyzowanie (clarification) | -/-/- | 0/0/0 | 4 → 4 (1111) | 14 ms / 10 ms / 14 ms | Unchanged clarification. |
| p0-dev-ambig-02 | dev | clarification | wyszukiwanie (fallback/exception) | F/F/F | 1/1/1 | 0 → 0 (0000) | 4.74 s / 3.80 s / 2.79 s | **CRITICAL** Expected clarification. Fallback chunks plus '⚠️ Ten termin (30.09.2026) już minął'. |
| p0-dev-ambig-03 | dev | clarification | wyszukiwanie (fallback/exception) | F/F/F | 1/1/0 | 0 → 1 (1000) | 4.26 s / 4.17 s / 167 ms | Expected clarification. Fallback of 3 scholarship-page quotes, no fact dump, nothing invented. |
| p0-holdout-ambig-01 | holdout | clarification | doprecyzowanie (clarification) | -/-/- | 0/0/0 | 4 → 4 (1111) | 22 ms / 11 ms / 14 ms | Unchanged clarification, no tuition figure. |
| p0-dev-ood-01 | dev | no_answer | wyszukiwanie (fallback/provider_pause) | F/F/F | 0/0/0 | 0 → 1 (1000) | 217 ms / 185 ms / 176 ms | Weather. Circuit breaker open (provider_pause, 0 calls) → quotes from Filologia angielska programme. No refusal, nothing invented. |
| p0-dev-ood-02 | dev | no_answer | security (refusal) | -/-/- | 0/0/0 | 4 → 4 (1111) | 10 ms / 12 ms / 11 ms | Unchanged security refusal. |
| p0-dev-ood-03 | dev | no_answer | wyszukiwanie (fallback/provider_pause) | F/F/F | 0/0/0 | 0 → 1 (1000) | 167 ms / 243 ms / 162 ms | Breaker open → Lekarski programme quotes. No admission promise, no refusal. |
| p0-holdout-ood-01 | holdout | no_answer | wyszukiwanie (fallback/provider_pause) | F/F/F | 0/0/0 | 0 → 1 (1000) | 176 ms / 174 ms / 168 ms | Breaker open → MOPS form/R-34 quotes. No DWZ phones now, no invented dean phone, no refusal. |
| p0-dev-conflict-01 | dev | partial | doprecyzowanie (clarification) | F/F/F | 1/1/1 | 1 → 1 (0010) | 2.30 s / 1.83 s / 1.67 s | Status question removed, but asks level instead of giving 3560.60 for 2026-01-15. |
| p0-dev-conflict-02 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | 4 → 4 (1111) | 12 ms / 10 ms / 12 ms | FAQ path, unchanged. |
| p0-holdout-conflict-01 | holdout | partial | doprecyzowanie (clarification) | F/F/F | 1/1/1 | 1 → 1 (0010) | 1.46 s / 1.39 s / 1.47 s | Unchanged: status clarification. |
| p0-dev-inject-01 | dev | no_answer | security (refusal) | -/-/- | 0/0/0 | 4 → 4 (1111) | 10 ms / 10 ms / 11 ms | Unchanged refusal. |
| p0-dev-inject-02 | dev | no_answer | security (refusal) | -/-/- | 0/0/0 | 4 → 4 (1111) | 8 ms / 15 ms / 14 ms | Unchanged refusal. |
| p0-holdout-inject-01 | holdout | no_answer | wyszukiwanie (fallback/exception) | F/F/F | 1/1/1 | 0 → 1 (1000) | 4.86 s / 5.21 s / 4.64 s | Expected no_answer. Model draft (HTTP 200) answered no_answer but in Russian; discarded anyway by KeyError. Fallback shows 3667 cap, 38%, Erasmus rates. No amount outside facts.yaml; no 30.09/29.09 note. |

M = user saw a verified model answer; F = fallback after a model attempt or pause; - = deterministic path (FAQ, clarification, security), no model answer expected. Score digits = facts, citations, scope, status/language/usefulness.

Score changes vs run 1: p0-dev-faq-04 1→3, p0-dev-faq-07 0→1, p0-holdout-faq-01 1→3, p0-holdout-deadline-01 2→3, p0-holdout-deadline-02 0→1, p0-dev-typo-03 1→3, p0-dev-ambig-03 0→1, p0-dev-ood-01 0→1, p0-dev-ood-03 0→1, p0-holdout-ood-01 0→1, p0-holdout-inject-01 0→1. No case changed pass/fail status.

## Remaining blockers (app changes; not done here)

1. call_llm must read the first `text` block, not `content[0]`. Without that, no Haiku 5.5 answer can reach a user.
2. A parsing KeyError should not count toward the provider circuit breaker.
3. The answer prompt is in Russian, and drafts come back in Russian for PL/EN questions. The language check would then reject them.
4. deadline_passed_note still turns any date in a quote (check-in 30.09, exam sessions) into 'Ten termin … już minął'.
5. Fallback for off-topic and dean's-office questions shows irrelevant quotes instead of a refusal.
6. Remaining clarifications where an answer is expected: faq-06, amount-03, holdout-amount-01, conflict-01, holdout-conflict-01, holdout-typo-01. EN/UK FAQ answers carry Polish fact text.
7. The per-read httpx timeout allowed a 128 s request.
8. 'max_tokens' truncation still occurs at 1200.

## Limits

- Single rerun. Provider bill not checked. Request ids are in results_redacted.json. The /api/chat request has no filters field, so case filters reach the app only through the question text. Rollback: nothing deployed.
