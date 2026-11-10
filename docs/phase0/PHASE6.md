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
- Max output tokens are 2000 (`ANSWER_MAX_TOKENS`). The previous caps were 700, then 1200. The answer prompt asks for 120 words or fewer. Truncated `max_tokens` output is still rejected.
- Prompt context is 3 chunks of 400 characters (`ANSWER_CONTEXT_CHUNKS`, `ANSWER_CHUNK_CHARS`), plus at most 4 fact cards of 240 characters (`ANSWER_FACT_CARDS`, `ANSWER_CARD_CHARS`). The old prompt attached 6 source titles and 800-character excerpts. `context_max_tokens` stays 4500 as a ceiling, not a claim that a prompt is that small.
- `ANSWER_BUDGET_S` is 15 (1 second parse + 12 second answer + margin). The in-process request ceiling `REQUEST_BUDGET_SEC` stays 55 seconds, which is above the model timeout. One model call, no repair call.
- `temperature` is omitted when `LLM_MODEL` starts with `claude-haiku-5`. `LLM_SEND_TEMPERATURE=0` omits it for any model. `LLM_SEND_TEMPERATURE=1` sends it. Other models still send `temperature` 0.
- Claude Haiku 5.5 thinks unless the request turns it off. The app sends `thinking: {type: "disabled"}` and `output_config.effort: high` for model names starting with `claude-haiku-5`, and whenever `LLM_THINKING=disabled`. `LLM_THINKING=adaptive` leaves the default on. Source: https://platform.claude.com/docs/en/build-with-claude/thinking (Haiku 5.5 accepts `disabled` at effort high or below; `budget_tokens` returns HTTP 400). The reader uses content blocks with `type` `text` and ignores `thinking` and `redacted_thinking`.
- `ANSWER_TIMEOUT_S` is a single wall-clock budget for connect, write, and the whole response body. A slow stream cannot reset it per chunk.
- The circuit breaker still opens after 5 transport failures in 30 seconds (timeout, connection error, HTTP 429, HTTP 5xx) and pauses for 60 seconds. A missing text block or a schema error is logged with `note_format_error` and does not open the breaker.
- A fenced ```json object is parsed. `stop_reason` `max_tokens` is not accepted as an answer.
- The answer prompt states the `AnswerIn` fields. Unknown extra fields are dropped. A missing `language` is filled from the question language, and a missing `follow_up` becomes null. A citation still needs `n` and `chunk_id` from the server manifest. A `source_id` or a model URL is not a citation.
- A passed-deadline line is added only when that signed deadline's topic matches the question, and the line names what the deadline is for. The dormitory date 15.05.2026 is not attached to a scholarship or faculty answer.
- An English or Ukrainian submission-channel FAQ keeps the signed channel string, including `Wirtualna Uczelnia` and `Moje stypendia`. The surrounding lead stays the approved template.
- Fallback shows at most 3 fact cards for the question, plus links. Staff phone lines stay out unless the question asks for that office. “Ten termin już minął” is attached only from a signed application deadline (`dorm_application_deadline`, `social_rector_deadline`). A retrieved quote, a check-in date, an exam date, or a timetable date does not produce that warning.
- An English or Ukrainian FAQ lead is not followed by untranslated Polish fact prose. Entries with no approved lead in that language stay in Polish. No machine translation was added. Missing English and Ukrainian leads: `faq-income-group-2025-2026`, `faq-doctoral-period`, `faq-cap-2026-2027`, `faq-cap-2025-2026`. English exists and Ukrainian does not: `faq-dorm-deadline-2026-2027`, `faq-rector-who-2026-2027`, `faq-erasmus-application-2026-2027`, `faq-erasmus-study-rates-2026-2027`.
- A weather question, an admission prediction, a dean's-office contact question with no signed dean fact, and an untopiced question below retrieval score 0.05 with no campus cue return `no_answer`. The signed benefits page is the only link. No dean phone is invented.
- A question that names an academic year does not show fact cards from another year. Status is not asked again when the question already states it, or when the topic is a yearly cap, Erasmus general information, or the doctoral stipend period / salary-act date. That decision is made before the slot extractor.
