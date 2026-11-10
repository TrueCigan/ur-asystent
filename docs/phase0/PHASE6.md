# Phase 6 note (2026-11-10)

Owner approval to start this slice: Kostya Prochan, 2026-11-10. No paid model call. Render was not changed. `EVAL_REAL` stays 0. `SCENARIO_SOCIAL` stays off. Mongolian answers stay off.

This slice is hardening, retention, backup checks, outage fallback, a runbook, local fake smoke, and an empty 40-case report. It is not the TZ Phase 6 definition of done. The 40-case score is still `not measured`. Holdout is not scored. Latency percentiles were not measured. The owner has not approved a public launch.

## What landed

- Offline checks lock the protections that already exist: instruction substitution in text and in a document frame, private and metadata addresses rejected before a fetch, secrets kept off the admin page and out of the admin log, and samples with no email or phone.
- In-process retention matches the TZ periods: technical rows 30 days, samples 7 days, summaries 90 days. Deletion runs when a note is written. There is no external scheduler. These rows are not a reconstructed request history, and they still disappear when the process restarts. The periods are not a GDPR compliance claim.
- Backup and restore go through the Phase 1 revision directory. Publish and rollback move `CURRENT` only. The running `data/index.npz` is unchanged, and publish does not crawl.
- A timeout, a refusal, and an unavailable provider use the existing fallback. The path makes one model call and no repair call. A fallback with no signed evidence does not contain 3667 or 3556.
- `docs/phase0/RUNBOOK.md` covers a local fake start, an index update, an outage, and rollback. Smoke on local fakes checks health, an FAQ answer with zero model calls, and a fallback answer.
- `docs/phase0/PHASE6_EVAL_REPORT.md` lists the 40 skeleton cases. Every score and latency cell is `not measured`.

## Explicitly not this phase

No paid eval, no `EVAL_REAL=1`, no 10-concurrent load test, no measured p50 or p95, and no 0–4 scores. No merge and no deploy. No Postgres, Redis, embeddings, external identity provider, MFA, or GDPR paperwork. No new FAQ amounts or deadlines. Rectorate launch remains a separate permission.

## Model-path defaults after the 2026-11-10 eval

The live run is recorded in `PHASE6_EVAL_REPORT.md` (12/40, not release-ready). These defaults change the app that a later rerun would call. They are not a new score.

- Answer HTTP timeout is 12 seconds (`ANSWER_TIMEOUT_S`, manifest `answer_timeout_s`). The previous 4 second value timed out on long prompts. Parse timeout stays 1 second.
- Max output tokens are 1200 (`ANSWER_MAX_TOKENS`). The previous cap was 700.
- Prompt context is 3 chunks of 400 characters (`ANSWER_CONTEXT_CHUNKS`, `ANSWER_CHUNK_CHARS`), plus at most 4 fact cards of 240 characters (`ANSWER_FACT_CARDS`, `ANSWER_CARD_CHARS`). The old prompt attached 6 source titles and 800-character excerpts. `context_max_tokens` stays 4500 as a ceiling, not a claim that a prompt is that small.
- `ANSWER_BUDGET_S` is 15 (1 second parse + 12 second answer + margin). The in-process request ceiling `REQUEST_BUDGET_SEC` stays 55 seconds, which is above the model timeout. The circuit breaker is unchanged: 5 provider errors inside 30 seconds, then generation pauses for 60 seconds and the existing fallback is used. One model call, no repair call.
- `temperature` is omitted when `LLM_MODEL` starts with `claude-haiku-5`. `LLM_SEND_TEMPERATURE=0` omits it for any model. `LLM_SEND_TEMPERATURE=1` sends it. Other models still send `temperature` 0.
- A fenced ```json object is parsed. `stop_reason` `max_tokens` is not accepted as an answer.
- Fallback shows at most 3 fact cards for the question, plus links. Staff phone lines stay out unless the question asks for that office. “Ten termin już minął” is only for an application or submission deadline, not a check-in date, an exam date, or a timetable date.
- A question that names an academic year does not show fact cards from another year. Status is not asked again when the question already states it, or when the topic is a yearly cap, Erasmus general information, or the doctoral stipend period / salary-act date. That decision is made before the slot extractor.
