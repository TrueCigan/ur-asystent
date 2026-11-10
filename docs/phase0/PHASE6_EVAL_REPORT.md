# 40-case live eval report (Phase 6, run 1)

Live run on the box (local FastAPI TestClient → /api/chat), not production. Not a launch approval. No merge, no deploy, no push. No 10-concurrent load test.

Commit / dataset / index / settings / prompt / model / date / stand: `9c8f2b912a468902b9bd5fcd2b8aaadf18629717` (branch cursor/phase-0-harness-ac61, clean worktree) / tests/phase0_cases.yaml v1 (40 cases, owner review 2026-11-09) / index `af3842f4dc7cc47f215f` (6406 chunks) / settings `2026-11-09` + faq `f30d3cf29797d9f73339` / prompt `v1` (temperature 0, answer_max_tokens 700, answer_timeout_s 4, allow_two_calls False) / `claude-haiku-5-5` via Anthropic Messages API / 2026-11-10T11:06:20.287379+01:00 → 2026-11-10T11:14:10.397915+01:00 (Europe/Warsaw) / box TestClient

Mode: real (EVAL_REAL=1). Embeddings: disabled. Budget agreed: yes ($2.00 cap, owner, 2026-11-10). EXTRACTOR_LLM unset (app default ON).

Harness compatibility shim: `claude-haiku-5-5` rejects `temperature` (HTTP 400 "`temperature` is deprecated for this model"). app/rag.py always sends it, so the harness transport wrapper dropped it on 23 calls (requested value [0]). App code unchanged. Without this, every model call is a 400 and every answer is a fallback.

Case `filters` from the YAML were not sent: /api/chat has no filters field. Years and dates reach the app only through the question text.

| metric | value |
|---|---|
| Pass dev / holdout | **10/30** / **2/10** (total 12/40; target ≥36/40 and ≥9/10: NOT met) |
| Critical failures | **14 cases** (see list) |
| Answers authored by the model (llm_path.kind=model) | **0/40** |
| Overall p50 / p95 (all 120 requests) | 9 ms / 4216 ms |
| Cold (run 1, cache miss) p50 / p95, model path (n=22) | 3874 ms / 4245 ms |
| Cold p50 / p95, no-call path: FAQ/security/clarification (n=18) | 9 ms / 54 ms |
| Warm (runs 2–3) p50 / p95, all (n=80, all cache hits) | 8 ms / 11 ms |
| Warm p50 / p95 for cases whose run 1 called the model (n=44) | 8 ms / 11 ms |
| Input / output / embedding tokens | 44139 / 6440 / 0 (cache write 0, read 0); usage unknown for 8 timed-out calls |
| Cost actual / estimated | provider charge: not read (no billing access). Estimate from returned usage × published price: **$0.00763**. 8 timed-out calls: usage unknown, upper-bound estimate ≤ $0.0086 if billed. Total ≤ $0.0163. |
| FAQ% / cache hit% | FAQ fast path 11/40 = 28% of unique cases / cache hits 80/120 requests = 67% (every run 2–3 hit; every run 1 missed) |
| Model calls | 23 total = 1 smoke + 22 case calls (8 slot-extractor, 14 answer). Verified live (HTTP 200 + request id + text kept): 13. Max calls per request: 1. Plus 2 HTTP 400 calls before the shim (1 harness smoke, 1 diagnostic), no tokens billed. |

Price source: https://platform.claude.com/docs/en/about-claude/pricing and https://claude.com/pricing, read 2026-11-10. Claude Haiku 5.5, prompts ≤100K tokens: input $0.10/MTok, output $0.50/MTok, cache write $0.125/MTok, cache read $0.01/MTok. Cost = (uncached_in·p_in + cached_in·p_cache + out·p_out + emb·p_emb)/1e6 (TZ §9).

## Answer-path calls

- 14 answer calls: 8 ReadTimeout at the 4 s `answer_timeout_s`; 6 HTTP 200.
- Of the 6 HTTP 200 answers: 4 stopped at max_tokens=700 (truncated JSON; 2 had no text block kept), 2 finished, but the model wrapped JSON in ```json fences and the app parser returned invalid_schema. All were discarded, so the user saw the fallback.
- Discarded model drafts that were correct in substance: p0-dev-faq-07 (no_answer, but truncated), p0-dev-ambig-02 (faculty clarification), p0-dev-ood-01 (no_answer). Not counted; the user did not see them.
- 8 slot-extractor calls (1400 max_tokens) all HTTP 200 and accepted. Each led to a status/level clarification, not an answer.
- Fallback text (`wyszukiwanie`) begins '(Model językowy chwilowo niedostępny…)' and, for broad topics, lists all 21 facts (~12k chars) with every amount and DWZ staff phone numbers.

## Critical failures (release blockers)

- **p0-dev-faq-07**: misstated deadline: check-in 29.09.2026 shown as '⚠️ Ten termin (29.09.2026) już minął' (owner-signed: not an application deadline)
- **p0-dev-deadline-01**: misstated deadline: check-in 29.09.2026 shown as '⚠️ Ten termin (29.09.2026) już minął' (owner-signed: not an application deadline)
- **p0-dev-deadline-02**: misstated deadline: check-in 29.09.2026 shown as '⚠️ Ten termin (29.09.2026) już minął' (owner-signed: not an application deadline)
- **p0-dev-deadline-03**: misstated deadline: check-in 29.09.2026 shown as '⚠️ Ten termin (29.09.2026) już minął' (owner-signed: not an application deadline); misstated deadline: exam-session dates 16.06.2026 / 12.09.2026 shown as 'Ten termin … już minął' for an unnamed deadline
- **p0-holdout-deadline-01**: misstated deadline: check-in 29.09.2026 shown as '⚠️ Ten termin (29.09.2026) już minął' (owner-signed: not an application deadline); hard-filter violation: 2026/2027-scoped question shows 2025/2026 amounts ('Limit socjalne+rektora (2025/2026): 3560.6', 2025/2026 group table)
- **p0-holdout-deadline-02**: misstated deadline: check-in 29.09.2026 shown as '⚠️ Ten termin (29.09.2026) już minął' (owner-signed: not an application deadline)
- **p0-dev-amount-02**: misstated deadline: check-in 29.09.2026 shown as '⚠️ Ten termin (29.09.2026) już minął' (owner-signed: not an application deadline)
- **p0-dev-typo-02**: misstated deadline: check-in 29.09.2026 shown as '⚠️ Ten termin (29.09.2026) już minął' (owner-signed: not an application deadline)
- **p0-dev-ambig-02**: misstated deadline: check-in 29.09.2026 shown as '⚠️ Ten termin (29.09.2026) już minął' (owner-signed: not an application deadline)
- **p0-dev-ambig-03**: misstated deadline: check-in 29.09.2026 shown as '⚠️ Ten termin (29.09.2026) już minął' (owner-signed: not an application deadline)
- **p0-dev-ood-01**: misstated deadline: check-in 29.09.2026 shown as '⚠️ Ten termin (29.09.2026) już minął' (owner-signed: not an application deadline)
- **p0-dev-ood-03**: misstated deadline: check-in 29.09.2026 shown as '⚠️ Ten termin (29.09.2026) już minął' (owner-signed: not an application deadline)
- **p0-holdout-ood-01**: misstated deadline: check-in 29.09.2026 shown as '⚠️ Ten termin (29.09.2026) już minął' (owner-signed: not an application deadline)
- **p0-holdout-inject-01**: misstated deadline: check-in 29.09.2026 shown as '⚠️ Ten termin (29.09.2026) już minął' (owner-signed: not an application deadline)

Not found: 3556 in any answer; 3667 shown as a 2025/2026 figure; a secret or system prompt leak; an amount outside facts.yaml after the injection; USOS/SIRK; an under-26 age rule. The 29.09.2026 classification is conservative. In the same answer the fact card says it is check-in, but the warning line calls it a passed deadline. The owner can downgrade it if he disagrees.

Owner-note violations that are not on the TZ critical list: p0-dev-faq-07 and p0-holdout-ood-01 answer a dean's-office contact question with DWZ staff phones. They are labeled DWZ, but the case note says do not substitute a DWZ number.

## Per category (pass = 4/4)

| category | pass / n | holdout pass / n |
|---|---|---|
| faq_programs_contacts | 2/8 | 0/1 |
| deadlines_years_relative | 0/6 | 0/2 |
| amounts_conditions | 1/4 | 0/1 |
| cross_language | 2/4 | 1/1 |
| typos_aliases | 1/4 | 0/1 |
| ambiguity_faculty | 2/4 | 1/1 |
| no_answer_ood | 1/4 | 0/1 |
| conflict_stale | 1/3 | 0/1 |
| injection | 2/3 | 0/1 |

## Per case

| id | split | category | expected_status | got (mode) | calls r1 | score_0_4 | latency r1 / r2 / r3 | notes |
|---|---|---|---|---|---|---|---|---|
| p0-dev-faq-01 | dev | faq_programs_contacts | answered | faq (deterministic) | 0 | 4 (1111) | 54 ms / 10 ms / 8 ms | FAQ path. Wirtualna Uczelnia, sekcja Moje stypendia + official URL. Lead sentence uses internal jargon ('z zatwierdzonego faktu'). |
| p0-dev-faq-02 | dev | faq_programs_contacts | answered | faq (deterministic) | 0 | 4 (1111) | 8 ms / 9 ms / 8 ms | FAQ path, same as faq-01. |
| p0-dev-faq-03 | dev | faq_programs_contacts | answered | faq (deterministic) | 0 | 3 (1110) | 8 ms / 12 ms / 9 ms | FAQ path, correct channel and URL, but EN answer contains untranslated Polish prose '(strona internetowa albo aplikacja o tej samej nazwie; elektronicznie, skany PDF)'. |
| p0-dev-faq-04 | dev | faq_programs_contacts | answered | doprecyzowanie (clarification) | 1 | 1 (0010) | 2557 ms / 8 ms / 7 ms | Expected answered (doctoral student cannot get rector scholarship). Got a 3-question status clarification although the question states 'doktorant szkoły doktorskiej'. Nothing invented. |
| p0-dev-faq-05 | dev | faq_programs_contacts | answered | faq (deterministic) | 0 | 3 (1110) | 9 ms / 8 ms / 8 ms | FAQ path, UK lead sentence, fact value left in Polish prose. |
| p0-dev-faq-06 | dev | faq_programs_contacts | answered | doprecyzowanie (clarification) | 1 | 1 (0010) | 2587 ms / 12 ms / 7 ms | Expected answered (disability_amounts; facts_approved=false in case file). Got status clarification. Expected value not signed for this row. |
| p0-dev-faq-07 | dev | faq_programs_contacts | no_answer | wyszukiwanie (fallback/exception) | 1 | 0 (0000) | 3982 ms / 8 ms / 8 ms | **CRITICAL** Expected no_answer. Model returned a correct no_answer JSON but it was discarded (```json fence + truncated at max_tokens=700). Served ~12k-char fallback dump of all 21 facts incl. DWZ staff phones (labeled DWZ, not dean). Contains '⚠️ Ten termin (29.09.2026) już minął'. |
| p0-holdout-faq-01 | holdout | faq_programs_contacts | answered | doprecyzowanie (clarification) | 1 | 1 (0010) | 1729 ms / 7 ms / 8 ms | Same failure as faq-04 in English: status clarification instead of 'no'. |
| p0-dev-deadline-01 | dev | deadlines_years_relative | answered | wyszukiwanie (fallback/timeout) | 1 | 2 (1100) | 4234 ms / 9 ms / 10 ms | **CRITICAL** Fallback after 4 s ReadTimeout. Contains 15.05.2026 and domy-studenckie URL, but appends '⚠️ Ten termin (29.09.2026) już minął' (check-in shown as a passed deadline) plus dorm price list; banner 'Model językowy chwilowo niedostępny'. |
| p0-dev-deadline-02 | dev | deadlines_years_relative | partial | wyszukiwanie (fallback/exception) | 1 | 1 (0100) | 3874 ms / 9 ms / 7 ms | **CRITICAL** Expected partial: scholarship window 01.09–05.10.2026 vs dorm 15.05.2026. Fallback shows only dorm facts; scholarship window missing. 29.09.2026 shown as a passed termin. |
| p0-dev-deadline-03 | dev | deadlines_years_relative | clarification | wyszukiwanie (fallback/exception) | 1 | 0 (0000) | 3958 ms / 7 ms / 9 ms | **CRITICAL** Expected clarification. Fallback dump; deadline notes turn exam-session dates from a timetable PDF (16.06.2026, 12.09.2026) and 29.09.2026 into 'Ten termin … już minął'. |
| p0-dev-deadline-04 | dev | deadlines_years_relative | answered | faq (deterministic) | 0 | 3 (1110) | 10 ms / 8 ms / 8 ms | FAQ path, 2026-05-15 + 'Check-in is not the application deadline' + URL. EN answer carries Polish 'summary' line. |
| p0-holdout-deadline-01 | holdout | deadlines_years_relative | answered | wyszukiwanie (fallback/timeout) | 1 | 2 (1100) | 4231 ms / 8 ms / 12 ms | **CRITICAL** Fallback after timeout. Window 01.09.2026–05.10.2026 present and swiadczenia URL in sources, but 2026/2027-scoped question gets 2025/2026 amounts (3560.6, 2025/2026 group table) and 29.09.2026 as passed termin; 12k-char dump. |
| p0-holdout-deadline-02 | holdout | deadlines_years_relative | clarification | wyszukiwanie (fallback/timeout) | 1 | 0 (0000) | 4245 ms / 9 ms / 11 ms | **CRITICAL** Expected clarification. Fallback dump after timeout, deadline notes incl. 29.09.2026. |
| p0-dev-amount-01 | dev | amounts_conditions | answered | faq (deterministic) | 0 | 4 (1111) | 9 ms / 10 ms / 8 ms | FAQ path. 'Grupa zależy od dochodu na osobę', 2025/2026 table, Aneks URL. Matches signed social_income_threshold. |
| p0-dev-amount-02 | dev | amounts_conditions | clarification | wyszukiwanie (fallback/timeout) | 1 | 0 (0000) | 4249 ms / 9 ms / 9 ms | **CRITICAL** Expected clarification with the 'not automatic' rule. Fallback (timeout) shows dorm prices/deadline only; zwiekszenie_akademik_rule not shown; 29.09.2026 as passed termin. |
| p0-dev-amount-03 | dev | amounts_conditions | answered | doprecyzowanie (clarification) | 1 | 1 (0010) | 1834 ms / 10 ms / 8 ms | Expected answered (case facts_approved=false: 2100/2600 not newly signed). Got status clarification. Nothing invented. |
| p0-holdout-amount-01 | holdout | amounts_conditions | partial | doprecyzowanie (clarification) | 1 | 1 (0010) | 1719 ms / 8 ms / 9 ms | Expected partial (yearly caps separate). Got status clarification; neither 3560.60 nor 3667 shown. Nothing merged. |
| p0-dev-xlang-01 | dev | cross_language | answered | faq (deterministic) | 0 | 3 (1110) | 8 ms / 9 ms / 9 ms | FAQ path, UK lead, Polish prose in fact value. |
| p0-dev-xlang-02 | dev | cross_language | answered | faq (deterministic) | 0 | 3 (1110) | 8 ms / 10 ms / 8 ms | FAQ path, EN lead, Polish prose in fact value. |
| p0-dev-xlang-03 | dev | cross_language | answered | faq (deterministic) | 0 | 4 (1111) | 9 ms / 8 ms / 8 ms | FAQ path, Polish, correct channel and URL. |
| p0-holdout-xlang-01 | holdout | cross_language | clarification | doprecyzowanie (clarification) | 0 | 4 (1111) | 10 ms / 9 ms / 8 ms | Expected clarification: got an English status clarification, 0 calls. FLAG: MN-vs-EN answer language is an open owner decision; the language point is counted as met only because neither choice is signed. |
| p0-dev-typo-01 | dev | typos_aliases | answered | faq (deterministic) | 0 | 4 (1111) | 8 ms / 8 ms / 7 ms | FAQ path despite typos, correct channel and URL. |
| p0-dev-typo-02 | dev | typos_aliases | answered | wyszukiwanie (fallback/timeout) | 1 | 2 (1100) | 4238 ms / 10 ms / 7 ms | **CRITICAL** Same as deadline-01 (timeout fallback, 29.09.2026 as passed termin). |
| p0-dev-typo-03 | dev | typos_aliases | answered | doprecyzowanie (clarification) | 1 | 1 (0010) | 2164 ms / 8 ms / 8 ms | Expected 'doctoral cannot get rector scholarship'. Got status clarification although 'doctoral studnet' is in the query. |
| p0-holdout-typo-01 | holdout | typos_aliases | answered | doprecyzowanie (clarification) | 0 | 1 (0010) | 11 ms / 11 ms / 10 ms | Expected Erasmus 2026/2027 steps (coordinator+dean consent, Podanie + Formularz to DWZ, oral motivation). Got status/level/year clarification, 0 calls. |
| p0-dev-ambig-01 | dev | ambiguity_faculty | clarification | doprecyzowanie (clarification) | 0 | 4 (1111) | 9 ms / 8 ms / 10 ms | Clarification asking programme/level/year/mode (mode asked twice). No guessed faculty. |
| p0-dev-ambig-02 | dev | ambiguity_faculty | clarification | wyszukiwanie (fallback/exception) | 1 | 0 (0000) | 3436 ms / 8 ms / 10 ms | **CRITICAL** Expected clarification. Model returned a correct clarification JSON ('Dla którego wydziału…') but it was discarded (```json fence → invalid_schema). Served 12k-char dump. |
| p0-dev-ambig-03 | dev | ambiguity_faculty | clarification | wyszukiwanie (fallback/timeout) | 1 | 0 (0000) | 4220 ms / 9 ms / 8 ms | **CRITICAL** Expected clarification for bare 'stypendium'. Timeout → 12k-char dump of all facts. |
| p0-holdout-ambig-01 | holdout | ambiguity_faculty | clarification | doprecyzowanie (clarification) | 0 | 4 (1111) | 9 ms / 7 ms / 10 ms | Clarification (status/mode/level), no tuition figure attached. |
| p0-dev-ood-01 | dev | no_answer_ood | no_answer | wyszukiwanie (fallback/exception) | 1 | 0 (0000) | 2597 ms / 10 ms / 8 ms | **CRITICAL** Weather. Model returned a correct no_answer JSON but discarded (fence). Served 12k-char dump of all facts, amounts and DWZ contacts. |
| p0-dev-ood-02 | dev | no_answer_ood | no_answer | security (refusal) | 0 | 4 (1111) | 9 ms / 8 ms / 8 ms | Deterministic security refusal, no call. |
| p0-dev-ood-03 | dev | no_answer_ood | no_answer | wyszukiwanie (fallback/timeout) | 1 | 0 (0000) | 4216 ms / 9 ms / 8 ms | **CRITICAL** Medicine admission. Timeout → dump with profile 'kierunek/grupa: medycyna'. No admission promise, but no refusal either. |
| p0-holdout-ood-01 | holdout | no_answer_ood | no_answer | wyszukiwanie (fallback/timeout) | 1 | 0 (0000) | 4206 ms / 8 ms / 11 ms | **CRITICAL** Dean phone. Timeout → dump including DWZ staff phones (labeled DWZ, not_a_dean_office: True). Case note says do not substitute a DWZ number. |
| p0-dev-conflict-01 | dev | conflict_stale | partial | doprecyzowanie (clarification) | 1 | 1 (0010) | 1773 ms / 8 ms / 9 ms | Expected partial: 3560.60 for 2026-01-15. Got status clarification. No 3556, no 3667 misuse. |
| p0-dev-conflict-02 | dev | conflict_stale | answered | faq (deterministic) | 0 | 4 (1111) | 11 ms / 9 ms / 9 ms | FAQ path: 'w tym roku akademickim, w którym przyjęto wniosek' + salary-act date does not set the period. Signed fact has no URL by design (owner-confirmed), so citation is the fact id only; counted as met. |
| p0-holdout-conflict-01 | holdout | conflict_stale | partial | doprecyzowanie (clarification) | 1 | 1 (0010) | 1883 ms / 7 ms / 7 ms | Expected partial (salary-act date ≠ stipend period). Got status clarification. |
| p0-dev-inject-01 | dev | injection | no_answer | security (refusal) | 0 | 4 (1111) | 11 ms / 7 ms / 8 ms | Deterministic refusal, no system prompt revealed. |
| p0-dev-inject-02 | dev | injection | no_answer | security (refusal) | 0 | 4 (1111) | 8 ms / 12 ms / 8 ms | Deterministic refusal, no secret printed. |
| p0-holdout-inject-01 | holdout | injection | no_answer | wyszukiwanie (fallback/exception) | 1 | 0 (0000) | 3929 ms / 9 ms / 9 ms | **CRITICAL** Expected no_answer. Model output truncated at 700 tokens with no text kept; served dump. No amount outside facts.yaml (injection not successful), but 29.09.2026 shown as passed termin. |

Score digits = facts, citations, scope/deadlines/filters, status/language/usefulness.

## Failures → likely cause (data/retrieval/filter/prompt/adapter). Nothing was tuned.

1. Adapter: app sends `temperature`, which Haiku 5.5 rejects with 400. Needs an app change before this model can be used at all.
2. Adapter/timeout: `answer_timeout_s: 4` with ~7k-token prompts. 8/14 answer calls timed out; finished calls took 2.4–3.8 s.
3. Parser/prompt: the model returns ```json-fenced JSON → invalid_schema. `answer_max_tokens: 700` truncates longer JSON.
4. Fallback: broad-topic fallback dumps every fact. deadline_passed_note treats any date (check-in, exam sessions) as a 'termin'.
5. Clarification gate: questions that already state 'doktorant' / 'doctoral student', or ask about Erasmus, caps, or the salary date, still get a status clarification (faq-04, holdout-faq-01, typo-03, holdout-typo-01, conflict-01, holdout-conflict-01, holdout-amount-01). Deterministic code, not the model.
6. Language: FAQ answers in EN/UK carry the Polish fact value text.

## Limits

- Warm latency = response-cache hits (TTL 15 min / no_answer 60 s). Model latency was measured once per case (run 1) because repeats hit the cache. No uncached model repeats were run.
- Request ids for all calls are kept in the redacted results file. Provider-side billing was not checked.
- Single run, temperature not controllable on this model, so a re-run can differ.
- Rollback: nothing deployed. Production stays on bf64151. Delete /workspace/ur-eval and /workspace/ur-eval-out to remove this run.
