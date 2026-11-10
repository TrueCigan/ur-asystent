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
