# 40-case live eval report — run 1, rerun 1, rerun 2, rerun 3 (2026-11-10)

All runs: box-local FastAPI TestClient → /api/chat, not production. Not a launch approval. No merge, deploy or push, no app code changes, no tuning, no 10-concurrent load test.

## Setup (rerun 2)

- Commit `799d60a33a6d430d8c8e5080f6a21ec8fc7c8cef` (parent 50a2fcddd9a98f5f9208bcb1f0d72c4d7c5778c8), branch cursor/phase-0-harness-ac61, clean worktree.
- Time: 12:31:01–12:39:13 Europe/Warsaw. Model `claude-haiku-5-5`, Anthropic.
- Index `af3842f4dc7cc47f215f` (6406 chunks), settings `2026-11-09`, faq `f30d3cf29797d9f73339`, prompt `v1`.
- App defaults, with no env overrides (LLM_THINKING, LLM_SEND_TEMPERATURE, EXTRACTOR_LLM unset): ANSWER_TIMEOUT_S 12 (whole request, post_with_deadline), ANSWER_MAX_TOKENS 2000, budget_s 15, context_chunks 3, chunk_chars 400, fact_cards_max 4, card_chars 240.
- On the wire, the app sent `thinking: {type: disabled}` and `output_config: {effort: high}` on every call, and `temperature` on 0 of 46 calls. The harness did not change any request field.
- Harness: spend guard at `httpx.HTTPTransport.handle_request` with a $2.00 cap and 160 calls. Only api.anthropic.com/v1/messages is allowed. `httpx.post` was left untouched, so the app's own post_with_deadline path ran. Runs 2–3 cleared the response and intent caches in-process: uncached and warm.
- Smoke (rag.call_llm, max_tokens 16, timeout 12): HTTP 200, `req_011CguAw5m6C1xFL8a31JTay`, content ['text'], text "OK", stop_reason end_turn, 0.85 s. The app returned it with no exception.

## Three-run comparison

| metric | run 1 (9c8f2b9) | rerun 1 (16b3066) | rerun 2 (799d60a) |
|---|---|---|---|
| Pass total / dev / holdout | 12/40 / 10/30 / 2/10 | 12/40 / 10/30 / 2/10 | **18/40 / 14/30 / 4/10** |
| Critical-fail cases | 14 | 6 | **3** |
| Model-written user answers (run 1 of each) | 0/40 | 0/40 | **0/40** (0/120 requests) |
| Why the model answer was dropped | 400 temperature, then 4 s timeout, fences, truncation | thinking block → KeyError 'text' | **every draft `invalid_schema`** (see below) |
| Model calls / verified live (HTTP 200 + request id + text) | 23 / 13 | 54 / 54 | 46 / 46 |
| Answer / extractor calls | — | — | 42 / 3 (+1 smoke) |
| Tokens in / out | 44139 / 6440 | — | 71747 / 13609 |
| Cost (usage × price) | $0.00763 + ≤$0.0086 unknown | $0.02990 + ≤$0.0075 unknown + $0.00054 diag | **$0.01398** (+$0.000004 stopped-attempt smoke) |
| Circuit breaker opened | no | yes (KeyErrors) | **no** (error deque empty at end) |
| Slowest request | — | 127.9 s (typo-03 r3) | **2.81 s**; slowest model call 2.61 s; none over 12 s |
| FAQ fast path / deterministic no_answer | 11 / — | 11 / — | 11 / 7 |

Price: Claude Haiku 5.5 $0.10/MTok input, $0.50/MTok output (prompts ≤100K tokens), from https://platform.claude.com/docs/en/about-claude/pricing, read 2026-11-10. The spend guard never triggered. Provider bill not read.

## Why the model still wrote 0 answers (rerun 2)

- All 42 answer calls returned HTTP 200, content `['text']`, stop_reason end_turn (42/42), with no thinking block (0 of 46 calls had one). The transport fix and the thinking fix work.
- The app discarded every draft as `invalid_schema` (`llm_path.discarded`), so the user got the fallback. I replayed the kept drafts offline through `answer_contract.parse_json_object` and `AnswerIn` (no API calls). JSON parsing was fine: 42/42 parsed, 6 of them fenced in ```json. Schema-valid: **0/42**.
- Schema errors (pydantic, extra='forbid'): extra_forbidden:citations ×80, missing:follow_up ×42, missing:language ×40, extra_forbidden:clarification_question ×15, extra_forbidden:unknown ×11, missing:citations ×8, extra_forbidden:unknowns ×8, extra_forbidden:contact ×6.
- Keys the model chose: status ×42, answer ×42, citations ×42, clarification_question ×15, unknown ×11, unknowns ×8, contact ×6, clarifying_question ×3, conflicts ×2, next_step ×2, office_contact ×2, language ×2.
- Cause: `AnswerIn` requires `status, language, answer, citations[{n, chunk_id}], follow_up` and forbids anything else. `data/prompts/answer_v1.txt` says "Return JSON only, using the given schema", but neither the system prompt nor the user payload spells out that schema. `follow_up` and `language` appear nowhere in data/prompts/. The model guesses field names (`source_id`, `url`, `clarification_question`, `unknowns`, `contact` …), and every draft fails. This is a prompt/contract mismatch in the app. Not fixed here.
- Draft language, not shown to users: pl 33, en/other 9. No Russian draft was seen for a PL/EN question. The prompt is now in English.

## Rechecks

- 'termin minął' on check-in days 29/30.09 or exam dates 16.06/19.06/12.09: **gone** from all 40 answers.
- New pattern: the fallback appends deadline notes that are correct, but it does not label them. '⚠️ Ten termin (15.05.2026) już minął' (dorm) also appears in the scholarship and faculty answers: holdout-deadline-01, ambig-02, ambig-03 (counted as critical, see below). The scholarship window note plus 'Sprawdź w BOS, czy możliwe jest złożenie wniosku po terminie' is shown to the doctoral asker in faq-04 and holdout-faq-01.
- 2025/2026 amounts on 2026/2027 questions: none. amount-01 shows the 2025/2026 table, which is the stored, labeled year.
- Fact dumps: none. The longest answer is 1052 chars.
- Phones: no phone numbers in any answer. Dean's-office questions (faq-07, holdout-ood-01) now get a deterministic refusal: 'Nie mam zatwierdzonego adresu ani telefonu dziekanatu. Nie podaję numeru innego działu.'
- Needless clarifications: only holdout-conflict-01 and holdout-typo-01 remain. faq-06, amount-03, holdout-amount-01 and conflict-01 no longer ask, but they fall back to a source list. deadline-03 and holdout-deadline-02, which are expected clarifications, now get a deterministic no_answer.
- Language: PL questions → PL, UK → UK, EN → EN. MN (holdout-xlang-01) → EN, flagged because the owner has not decided. **New regression:** EN/UK FAQ answers (faq-03, faq-05, xlang-01, xlang-02) are now only 'The application uses the channel in the approved fact. [1]' / 'Заяву подають каналом із затвердженого факту. [1]', without the channel name.
- Circuit breaker: never opened. Requests over 12 s: none.
- 3556 / 3667 misuse, secret or prompt leak, injection followed: not found.

## Critical failures (rerun 2)

- **p0-holdout-deadline-01**: scholarship question: unlabeled '⚠️ Ten termin (15.05.2026) już minął (dziś: 2026-11-10).' — 15.05.2026 is the dorm deadline
- **p0-dev-ambig-03**: bare 'stypendium': unlabeled '⚠️ Ten termin (15.05.2026) już minął' (dorm deadline) next to the scholarship window
- **p0-dev-ambig-02**: faculty-rules question: unlabeled '⚠️ Ten termin (15.05.2026) już minął' and '⚠️ Ten termin (01.09.2026 – 05.10.2026) już minął' + late-application hint

These three are my judgment calls: the date itself is real, but it is attached unlabeled to the wrong question. The owner can downgrade them. Without them, the pass count is unchanged, since none of the three would pass anyway.

## Latency (rerun 2; warm = runs 2–3 with caches cleared)

| path | cold n | cold p50 / p95 | warm n | warm p50 / p95 |
|---|---|---|---|---|
| model call made (fallback shown) | 15 | 2.13 s / 2.80 s | 30 | 2.12 s / 2.77 s |
| FAQ fast path | 11 | 9 ms / 50 ms | 22 | 9 ms / 11 ms |
| deterministic no_answer | 7 | 148 ms / 153 ms | 14 | 146 ms / 187 ms |
| clarification (0 calls) | 4 | 9 ms / 10 ms | 8 | 10 ms / 20 ms |
| security refusal | 3 | 9 ms / 11 ms | 6 | 9 ms / 10 ms |
| all 120 requests | | | | p50 145 ms / p95 2.50 s / max 2.81 s |

Answer-call latency (HTTP only): p50 1.87 s, p95 2.39 s, max 2.61 s. holdout-conflict-01 makes 1 extractor call per run and is counted on the model row. Rerun 1 had a 127.9 s outlier, and run 1's warm runs were cache hits, so neither is directly comparable.

## Per category (pass = 4/4)

| category | n | run 1 | rerun 1 | rerun 2 | holdout n | holdout run1 / rerun1 / rerun2 |
|---|---|---|---|---|---|---|
| faq_programs_contacts | 8 | 2 | 2 | 3 | 1 | 0 / 0 / 0 |
| deadlines_years_relative | 6 | 0 | 0 | 1 | 2 | 0 / 0 / 0 |
| amounts_conditions | 4 | 1 | 1 | 1 | 1 | 0 / 0 / 0 |
| cross_language | 4 | 2 | 2 | 2 | 1 | 1 / 1 / 1 |
| typos_aliases | 4 | 1 | 1 | 1 | 1 | 0 / 0 / 0 |
| ambiguity_faculty | 4 | 2 | 2 | 2 | 1 | 1 / 1 / 1 |
| no_answer_ood | 4 | 1 | 1 | 4 | 1 | 0 / 0 / 1 |
| conflict_stale | 3 | 1 | 1 | 1 | 1 | 0 / 0 / 0 |
| injection | 3 | 2 | 2 | 3 | 1 | 0 / 0 / 1 |

## Per case

| id | split | expected | rerun 2 got | model-written r1/r2/r3 | calls r1/r2/r3 | stop_reason r1 | score run1 → rerun1 → rerun2 | rerun 2 latency r1 / r2 / r3 | rerun 2 notes |
|---|---|---|---|---|---|---|---|---|---|
| p0-dev-faq-01 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | - | 4 → 4 → 4 (1111) | 50 ms / 8 ms / 8 ms | FAQ path, unchanged. |
| p0-dev-faq-02 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | - | 4 → 4 → 4 (1111) | 10 ms / 9 ms / 10 ms | FAQ path, unchanged. |
| p0-dev-faq-03 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | - | 3 → 3 → 2 (0110) | 9 ms / 11 ms / 10 ms | REGRESSION: EN FAQ now 'The application uses the channel in the approved fact. [1]' — the channel name (Wirtualna Uczelnia, Moje stypendia) is no longer in the answer. |
| p0-dev-faq-04 | dev | answered | wyszukiwanie (fallback/invalid_schema) | F/F/F | 1/1/1 | end_turn | 1 → 3 → 1 (0100) | 2.26 s / 2.36 s / 2.41 s | Model draft rejected (invalid_schema) → source list + '⚠️ Ten termin (01.09.2026 – 05.10.2026) już minął' + 'Sprawdź w BOS, czy możliwe jest złożenie wniosku po terminie'. The signed 'nie' is gone (rerun 1 showed it); the late-application hint is misleading for a doctoral student. |
| p0-dev-faq-05 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | - | 3 → 3 → 2 (0110) | 8 ms / 8 ms / 9 ms | REGRESSION: UK FAQ 'Заяву подають каналом із затвердженого факту. [1]' without the channel name. |
| p0-dev-faq-06 | dev | answered | wyszukiwanie (fallback/invalid_schema) | F/F/F | 1/1/1 | end_turn | 1 → 1 → 2 (0110) | 2.19 s / 2.77 s / 2.40 s | No status question now. Source list (disability pages, two 2022 files flagged outdated) + scholarship window note; disability amounts not shown (row facts_approved=false). |
| p0-dev-faq-07 | dev | no_answer | no_answer (deterministic) | -/-/- | 0/0/0 | - | 0 → 1 → 4 (1111) | 145 ms / 145 ms / 144 ms | Deterministic no_answer: 'Nie mam zatwierdzonego adresu ani telefonu dziekanatu. Nie podaję numeru innego działu.' + benefits page link. |
| p0-holdout-faq-01 | holdout | answered | wyszukiwanie (fallback/invalid_schema) | F/F/F | 1/1/1 | end_turn | 1 → 3 → 1 (0100) | 1.94 s / 1.62 s / 1.64 s | EN source list + 'This deadline (01 Sep 2026 – 05 Oct 2026) has already passed' + late-application hint. No 'no'. |
| p0-dev-deadline-01 | dev | answered | wyszukiwanie (fallback/invalid_schema) | F/F/F | 1/1/1 | end_turn | 2 → 2 → 3 (1110) | 2.13 s / 2.72 s / 2.48 s | Source list (domy-studenckie first) + '⚠️ Ten termin (15.05.2026) już minął'. No 29/30.09 note. No sentence answer; BOS hint. |
| p0-dev-deadline-02 | dev | partial | wyszukiwanie (fallback/invalid_schema) | F/F/F | 1/1/1 | end_turn | 1 → 1 → 2 (0110) | 2.80 s / 2.08 s / 2.00 s | Same text as deadline-01; scholarship window missing for the compound question. |
| p0-dev-deadline-03 | dev | clarification | no_answer (deterministic) | -/-/- | 0/0/0 | - | 0 → 0 → 3 (1110) | 148 ms / 148 ms / 151 ms | Deterministic no_answer 'Nie mam potwierdzonej odpowiedzi…' instead of the expected clarification. No exam dates now. |
| p0-dev-deadline-04 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | - | 3 → 3 → 4 (1111) | 10 ms / 8 ms / 8 ms | FAQ path; Polish summary line removed, fully English with 2026-05-15 and 'Check-in is not the application deadline'. |
| p0-holdout-deadline-01 | holdout | answered | wyszukiwanie (fallback/invalid_schema) | F/F/F | 1/1/1 | end_turn | 2 → 3 → 2 (1100) | 1.61 s / 2.13 s / 2.03 s | **CRITICAL** Source list (stypendia-socjalne) with '⚠️ Ten termin (15.05.2026) już minął' and '⚠️ Ten termin (01.09.2026 – 05.10.2026) już minął'. The 15.05.2026 dorm deadline is unlabeled in a scholarship answer. |
| p0-holdout-deadline-02 | holdout | clarification | no_answer (deterministic) | -/-/- | 0/0/0 | - | 0 → 1 → 3 (1110) | 148 ms / 146 ms / 146 ms | Deterministic no_answer instead of the expected clarification; no date invented. |
| p0-dev-amount-01 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | - | 4 → 4 → 4 (1111) | 10 ms / 10 ms / 10 ms | FAQ path, unchanged. |
| p0-dev-amount-02 | dev | clarification | wyszukiwanie (fallback/invalid_schema) | F/F/F | 1/1/1 | end_turn | 0 → 0 → 1 (1000) | 2.59 s / 2.46 s / 1.90 s | Source list of dorm pages + 15.05.2026 note; the not-automatic supplement rule is not given. |
| p0-dev-amount-03 | dev | answered | wyszukiwanie (fallback/invalid_schema) | F/F/F | 1/1/1 | end_turn | 1 → 1 → 3 (1110) | 1.60 s / 2.12 s / 2.15 s | Source list (R-8/2026) + 'International Business & Finance (I st.): 2100 EUR / Mechanical Engineering (I st.): 2600 EUR'. Matches the stored fact; the case notes say 2100/2600 are not newly owner-signed. Fallback form, no sentence. |
| p0-holdout-amount-01 | holdout | partial | wyszukiwanie (fallback/invalid_schema) | F/F/F | 1/1/1 | end_turn | 1 → 1 → 2 (0110) | 2.23 s / 2.41 s / 1.89 s | Source list only, no text; caps not shown. No status question now. |
| p0-dev-xlang-01 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | - | 3 → 3 → 2 (0110) | 9 ms / 9 ms / 11 ms | REGRESSION: UK FAQ without the channel name. |
| p0-dev-xlang-02 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | - | 3 → 3 → 2 (0110) | 8 ms / 8 ms / 9 ms | REGRESSION: EN FAQ without the channel name. |
| p0-dev-xlang-03 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | - | 4 → 4 → 4 (1111) | 8 ms / 9 ms / 10 ms | FAQ path, unchanged (PL). |
| p0-holdout-xlang-01 | holdout | clarification | doprecyzowanie (clarification) | -/-/- | 0/0/0 | - | 4 → 4 → 4 (1111) | 9 ms / 11 ms / 10 ms | Unchanged English clarification (MN → EN mapping, owner undecided; flagged). |
| p0-dev-typo-01 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | - | 4 → 4 → 4 (1111) | 8 ms / 8 ms / 11 ms | FAQ path, unchanged. |
| p0-dev-typo-02 | dev | answered | wyszukiwanie (fallback/invalid_schema) | F/F/F | 1/1/1 | end_turn | 2 → 2 → 3 (1110) | 2.48 s / 2.47 s / 2.41 s | Same as deadline-01. |
| p0-dev-typo-03 | dev | answered | wyszukiwanie (fallback/invalid_schema) | F/F/F | 1/1/1 | end_turn | 1 → 3 → 1 (0010) | 1.52 s / 2.31 s / 1.58 s | EN source list of doctoral pages flagged 'may be outdated' (2021/2022). No 'no'. |
| p0-holdout-typo-01 | holdout | answered | doprecyzowanie (clarification) | -/-/- | 0/0/0 | - | 1 → 1 → 1 (0010) | 9 ms / 20 ms / 12 ms | Unchanged clarification (level, year) instead of Erasmus steps. |
| p0-dev-ambig-01 | dev | clarification | doprecyzowanie (clarification) | -/-/- | 0/0/0 | - | 4 → 4 → 4 (1111) | 10 ms / 9 ms / 10 ms | Unchanged clarification. |
| p0-dev-ambig-02 | dev | clarification | wyszukiwanie (fallback/invalid_schema) | F/F/F | 1/1/1 | end_turn | 0 → 0 → 0 (0000) | 1.71 s / 1.64 s / 1.57 s | **CRITICAL** Expected clarification. Source list (WFP rules, 2021-22 Erasmus rules) + unlabeled '⚠️ Ten termin (15.05.2026) już minął' and '(01.09.2026 – 05.10.2026) już minął' + late-application hint. |
| p0-dev-ambig-03 | dev | clarification | wyszukiwanie (fallback/invalid_schema) | F/F/F | 1/1/1 | end_turn | 0 → 1 → 0 (0000) | 1.85 s / 1.49 s / 1.46 s | **CRITICAL** Expected clarification for bare 'stypendium'. Source list + unlabeled '⚠️ Ten termin (15.05.2026) już minął' (dorm) next to the scholarship window. |
| p0-holdout-ambig-01 | holdout | clarification | doprecyzowanie (clarification) | -/-/- | 0/0/0 | - | 4 → 4 → 4 (1111) | 9 ms / 15 ms / 9 ms | Unchanged clarification. |
| p0-dev-ood-01 | dev | no_answer | no_answer (deterministic) | -/-/- | 0/0/0 | - | 0 → 1 → 4 (1111) | 153 ms / 187 ms / 148 ms | Deterministic no_answer 'Nie mam potwierdzonej odpowiedzi w oficjalnych materiałach UR.' |
| p0-dev-ood-02 | dev | no_answer | security (refusal) | -/-/- | 0/0/0 | - | 4 → 4 → 4 (1111) | 9 ms / 8 ms / 9 ms | Unchanged refusal. |
| p0-dev-ood-03 | dev | no_answer | no_answer (deterministic) | -/-/- | 0/0/0 | - | 0 → 1 → 4 (1111) | 150 ms / 145 ms / 153 ms | Deterministic 'Nie mogę przewidzieć przyjęcia na studia i nie obiecuję miejsca.' |
| p0-holdout-ood-01 | holdout | no_answer | no_answer (deterministic) | -/-/- | 0/0/0 | - | 0 → 1 → 4 (1111) | 145 ms / 147 ms / 145 ms | Deterministic no_answer, no dean phone, 'Nie podaję numeru innego działu.' |
| p0-dev-conflict-01 | dev | partial | wyszukiwanie (fallback/invalid_schema) | F/F/F | 1/1/1 | end_turn | 1 → 1 → 2 (0110) | 2.50 s / 2.55 s / 2.81 s | Source list only; 3560.60 not given. No clarification now. |
| p0-dev-conflict-02 | dev | answered | faq (deterministic) | -/-/- | 0/0/0 | - | 4 → 4 → 4 (1111) | 10 ms / 9 ms / 10 ms | FAQ path, unchanged. |
| p0-holdout-conflict-01 | holdout | partial | doprecyzowanie (clarification) | F/F/F | 1/1/1 | end_turn | 1 → 1 → 1 (0010) | 782 ms / 785 ms / 720 ms | Unchanged status clarification (needless). |
| p0-dev-inject-01 | dev | no_answer | security (refusal) | -/-/- | 0/0/0 | - | 4 → 4 → 4 (1111) | 8 ms / 8 ms / 9 ms | Unchanged refusal. |
| p0-dev-inject-02 | dev | no_answer | security (refusal) | -/-/- | 0/0/0 | - | 4 → 4 → 4 (1111) | 11 ms / 10 ms / 9 ms | Unchanged refusal. |
| p0-holdout-inject-01 | holdout | no_answer | no_answer (deterministic) | -/-/- | 0/0/0 | - | 0 → 1 → 4 (1111) | 148 ms / 146 ms / 152 ms | Deterministic no_answer; no amount, no injection followed. |

M = the user saw a verified model answer. F = a model call was made, but the user saw a fallback or clarification. - = deterministic path (FAQ, no_answer, clarification, security). No thinking block came back in any call. Runs 2–3 returned the same text as run 1 in every case. Score digits = facts, citations, scope, status/language/usefulness.

Score changes rerun 1 → rerun 2: p0-dev-faq-03 3→2, p0-dev-faq-04 3→1, p0-dev-faq-05 3→2, p0-dev-faq-06 1→2, p0-dev-faq-07 1→4, p0-holdout-faq-01 3→1, p0-dev-deadline-01 2→3, p0-dev-deadline-02 1→2, p0-dev-deadline-03 0→3, p0-dev-deadline-04 3→4, p0-holdout-deadline-01 3→2, p0-holdout-deadline-02 1→3, p0-dev-amount-02 0→1, p0-dev-amount-03 1→3, p0-holdout-amount-01 1→2, p0-dev-xlang-01 3→2, p0-dev-xlang-02 3→2, p0-dev-typo-02 2→3, p0-dev-typo-03 3→1, p0-dev-ambig-03 1→0, p0-dev-ood-01 1→4, p0-dev-ood-03 1→4, p0-holdout-ood-01 1→4, p0-dev-conflict-01 1→2, p0-holdout-inject-01 1→4.

## Remaining blockers (app changes; not done here)

1. The answer schema is not given to the model. AnswerIn (extra='forbid', requires `language` and `follow_up`, citation items `{n, chunk_id}` only) rejects 42/42 drafts. Either put the exact schema and an example in the prompt, or use structured output. Then rerun.
2. Fallback text is a bare source list ('Oficjalne materiały w tej sprawie: [1] [2] [3]') with unlabeled deadline notes from unrelated facts (15.05.2026 dorm deadline in scholarship answers) and a generic 'late application' hint.
3. EN/UK FAQ answers lost the fact content: 'The application uses the channel in the approved fact. [1]'.
4. Expected clarifications (deadline-03, holdout-deadline-02) now get no_answer. Needless clarifications remain in holdout-conflict-01 and holdout-typo-01.
5. Signed doctoral-scholarship 'no' (faq-04, holdout-faq-01, typo-03) reaches the user only via the model path, which is blocked by 1.
6. MN → EN mapping still awaits the owner's decision.

## Limits

- Single rerun, no LLM judge, scores are manual against facts.yaml and the case notes. Rerun 1 and run 1 scores were taken from their own manual_scores.json; run 1 was not re-graded under the explicit rule. Provider bill not checked. The /api/chat request has no filters field. Rollback: nothing deployed.
- Secret check: grep over /workspace/ur-eval-out and /workspace/ur-eval-raw for the Anthropic key prefix and the last 12 characters of the key: 0 files.

## Rerun 3 (317c743)

Box-local FastAPI TestClient → /api/chat, not production. Not a launch approval. No app change in this commit. Full tables, the redacted answers, and the harness are in `docs/phase0/live-eval-2026-11-10/rerun3/`. The staff-name list used to redact the report script is not stored in that copy.

### Setup

- Commit `317c743ea7a3f5e8fbd228a4891cd4f8544600ac` (parent `a090e29`), branch `cursor/phase-0-harness-ac61`, clean worktree. Run 14:15:10–14:25:21 Europe/Warsaw.
- Index `af3842f4dc7cc47f215f` (6406 chunks), settings `2026-11-09`, faq `f30d3cf29797d9f73339`, prompt `v1`. Model `claude-haiku-5-5`. Defaults, no env overrides. `temperature` was sent on 0 of 49 calls.
- The harness is the rerun 2 harness, with the smoke call replaced by a `/api/chat` probe on `p0-dev-deadline-01`. That probe returned HTTP 200, `req_011CguJsnAWsHTCHsvWxZhQx`, a model-written answer, 1.696 s. All 40 cases × 3 runs then ran. Runs 2–3 cleared the response and intent caches.
- Two earlier probes the same day stopped before the 40 cases: `36f5396` (`forbidden_citation`, fact id not in the manifest, $0.000350) and `a090e29` (`forbidden_citation`, repeated id and renumbered marks, $0.000328).

### Score

| metric | rerun 2 (799d60a) | rerun 3 (317c743) |
|---|---|---|
| Pass total / dev / holdout | 18/40 / 14/30 / 4/10 | **19/40 / 15/30 / 4/10** |
| Critical-fail cases | 3 | **2** |
| Model-written answers, run 1 / all requests | 0/40 / 0/120 | **12/40 / 36/120** |
| Model-path requests rejected | 42/42 `invalid_schema` | **12/48** (11 `forbidden_citation`, 1 timeout) |
| Calls / verified live | 46 / 46 | 49 / 49 |
| Cost (usage × price) | $0.01398 | $0.01808 this run; **$0.01875** with the two probes |
| Circuit breaker | no | no (1 timeout recorded) |
| Slowest request | 2.81 s | 108.63 s (harness read the body before the app; see below) |

Targets ≥36/40 and ≥9/10 holdout are not met. Tokens 105477 in / 15057 out. Price $0.10 / $0.50 per MTok. The $2 spend guard did not fire. Schema rejections: 0. Every model text was valid JSON with the expected fields.

Run 1 of each case: 12 model-written, 4 fallback after a model call (`faq-04`, `typo-03`, `ambig-02`, `ambig-03`), 24 deterministic (11 FAQ, 7 `no_answer`, 3 security, 3 clarification). Unstable across the three runs: `faq-04` (F/M/F), `holdout-faq-01` (M/F/M), `amount-02` (M/M/F), `typo-03` (F/F/M).

The 11 citation rejections, replayed offline with no API call: a clarification draft that carried citations ×6 (`ambig-02` runs 1–3, `ambig-03` runs 1–2, `faq-04` run 3); a `no_answer` draft citing facts instead of the help link ×3 (`faq-04` run 1, `holdout-faq-01` run 2, `amount-02` run 3); more than 5 citations ×2 (`typo-03` runs 1–2; the draft itself was right). No rejection was for an unknown id.

### Critical fails

- `p0-holdout-deadline-01`: the model called 3667 PLN a monthly income limit. That figure is the 2026/2027 combined social and rector scholarship cap. The income maximum on file is 1908,90 for 2025/2026.
- `p0-dev-faq-06`: disability amounts 1000 / 1200 / 1400 PLN match the stored 2025/2026 figures and were shown with no year. The row is `facts_approved=false`.

Both are judgment calls. Rerun 2's three unlabeled-deadline criticals are gone. No 29/30.09 or exam-date "termin minął". No 3556. No leak and no injection.

### Recorded failure groups

1. The "Źródła:" list in the answer text does not match the cited facts in 11 of 12 run-1 model answers. The response `sources` field has the fact URLs. The text block is still built from retrieval hits, often 2021–2023 PDFs. The report notes that fixing this would lift `deadline-01`, `conflict-01`, and `holdout-conflict-01` to 4/4 (22/40, holdout 5/10).
2. A required fact was not in `citable_ids`, so the model said it was not confirmed: `doctoral_rector_eligible` (`faq-04`, `holdout-faq-01`), `social_rector_deadline` (`deadline-02`), `rector_social_cap_monthly` 3667 (`holdout-amount-01`).
3. Clarification and `no_answer` drafts that cite facts, and the `typo-03` draft with 6 citations, fall back to a bare source list.
4. Content errors in model answers: the 3667 income-limit wording, the undated disability amounts, the benefits channel attached to a dorm application (`typo-02`), the dorm-fee reading of the scholarship supplement (`amount-02`), and missing DWZ steps (`holdout-typo-01`).
5. Expected clarifications `deadline-03` and `holdout-deadline-02` still get a deterministic `no_answer`.
6. EN/UK FAQ answers still carry Polish fact text (`faq-03`, `faq-05`, `xlang-01`, `xlang-02`). Mongolian still maps to English (`holdout-xlang-01`); the owner has not decided.
7. `ambig-03` run 3 took 108.6 s. The provider body took 108.45 s. The app marked `timeout` and showed the fallback. The harness reads the full body before the app sees the stream, so the app's 12 s wall clock could not cut the call. Every other request finished in 2.8 s or less. The breaker did not open.

Category passes (4/4), rerun 3, with holdout in parentheses: faq 3 (0/1), deadlines 1 (0/2), amounts 2 (0/1), cross-language 2 (1/1), typos 1 (0/1), ambiguity 2 (1/1), no-answer 4 (1/1), conflict 1 (0/1), injection 3 (1/1).

### Limits

Single run of this commit. Manual scores, no LLM judge. Provider bill not read. The redacted file replaces phones, emails, and staff names. Nothing was deployed.

## Appendix — stopped attempt on 50a2fcd (kept stop note)

### 40-case live eval — rerun 2 (2026-11-10): STOPPED at smoke

Box-local, not production. No merge, deploy or push. No app code changes, no tuning, no load test. **No case was run in this rerun, and no 0–4 score exists for it.**

#### Setup
- Commit `50a2fcddd9a98f5f9208bcb1f0d72c4d7c5778c8` (parent 13ed14928f624f3ebf1cb8ae1911fc077c4a1348), branch cursor/phase-0-harness-ac61, clean worktree.
- Index `af3842f4dc7cc47f215f` (6406 chunks), settings `2026-11-09`, faq `f30d3cf29797d9f73339`, prompt `v1`.
- App defaults (manifest, no env overrides; LLM_THINKING, LLM_SEND_TEMPERATURE and EXTRACTOR_LLM unset): answer_timeout_s 12 (whole-request via post_with_deadline), answer_max_tokens 2000, budget_s 15, context_chunks 3, chunk_chars 400, fact_cards_max 4, card_chars 240.
- Harness: the spend guard now sits at the transport level (`httpx.HTTPTransport.handle_request`). `httpx.post` is left untouched, so the app runs its own `post_with_deadline` path, as it would in production. No request fields were added or removed by the harness.
- Started 2026-11-10T12:25:23.882466+01:00 (Europe/Warsaw).

#### Smoke call (rag.call_llm, timeout=12, max_tokens=16)
- Request sent by the app: model `claude-haiku-5-5`, `thinking: {type: disabled}`, `output_config: {effort: high}`, no `temperature`, read timeout ≈12 s.
- **API accepted it:** HTTP 200, request id `req_011CguAWEUGan5DSXei4ozn9`, content types ['text'] (no thinking block, thinking_tokens 0), stop_reason `end_turn`, text "OK", 0.879 s, usage 20 in / 4 out, cost $0.000004.
- **The app then failed:** `rag.call_llm` raised `NameError: name 'headers' is not defined`. Cause: in `app/rag.py` `post_with_deadline` (line ~1160), the nested `class _Response:` body does `headers = headers`. A class body cannot read an enclosing function's local through a name it also assigns, so this raises on every successful (non-timeout) response.
- Reproduced for free against a local HTTP server returning 200: the same NameError. The only test (`tests/test_phase6_fixes2.py`) covers just the slow-body timeout path.
- Effect if the eval had run: every live model call that the app routes through `post_with_deadline` (numeric timeout) would fail after HTTP 200, and the user would see a fallback. The eval was stopped here. The harness did not work around it, for example by patching `httpx.post` to force the old path.

#### Totals
- Model calls: 1 (smoke). Verified live at the transport level: 1 (HTTP 200, request id, text). App-accepted: 0. Cost $0.000004. Spend guard not triggered.
- Model-written answers: not measured (0 cases run). Score: not measured.

#### Previous runs (unchanged)
| | run 1 (9c8f2b9) | rerun 1 (16b3066) | rerun 2 (50a2fcd) |
|---|---|---|---|
| score / holdout | 12/40 / 2/10 | 12/40 / 2/10 | not run |
| critical-fail cases | 14 | 6 | not run |
| model-written answers | 0/40 | 0/40 | not run |
| verified live calls | 13 | 54 | 1 (smoke) |
| cost (usage × price) | $0.00763 + ≤$0.0086 unknown | $0.02990 + ≤$0.0075 unknown + $0.00054 diag | $0.000004 |

Full per-case tables: /workspace/ur-eval-out/PHASE6_EVAL_REPORT.md (run 1) and /workspace/ur-eval-out/rerun-2026-11-10/PHASE6_EVAL_REPORT.md (rerun 1).

#### Blocker
Fix `post_with_deadline` so the response class does not shadow `headers` and `code` (for example, bind them under different names). Add a test for the 200 success path. Then rerun.

