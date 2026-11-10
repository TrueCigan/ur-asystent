# Phase 5 note (2026-11-09)

Owner approval: Kostya Prochan, chat review 2026-11-09. No paid model call. Render was not changed. `SCENARIO_SOCIAL` stays off. The 40-case score stays `not measured`.

## What landed

- `/admin/ai` and `/api/admin/ai/*` stay closed until a signed role token is present. The roles are viewer, editor, and admin. A viewer can read. An editor can preview. Only an admin can publish the FAQ active flags, publish or roll back a file-index revision, or save settings. Changing requests also need the CSRF value returned with that token. There is no external identity provider and no MFA integration.
- The overview reads the in-process Phase 4 notes for this process: requests today, FAQ and generated shares of those requests, cache hits over cache lookups, no_answer, clarification, and error counts, plus USD and the budget. Each percentage names its denominator. A missing token price is marked `unknown` and is not shown as zero. p50 and p95 are `not measured`.
- Samples are redacted notes with date, path, error, total time, versions, and source ids. The raw question, network id, session id, and user id are not fields. Parse, retrieval, and answer stage times stay `not measured`; only the request total we already timed is stored.
- Sources reuse the Phase 1 file-index revisions. A dry-run reports the revision id and does not write `CURRENT`. Publish and rollback require confirmation and append an audit row with the role, not a secret.
- FAQ rows show validity, scope, and fact ids. Overlapping active entries are listed before any publish. Publish can only turn an existing entry on or off. It does not add amounts, deadlines, faculty ids, or the unsigned 3556 figure.
- Quality lists schema topics that have no FAQ entry and states that the 40-case 0–4 score is not measured.
- Settings for TTLs, limits, the model name, and prices are validated, previewed, then saved by an admin. Values cannot rise above the existing caps. Secret fields are rejected. Flags such as Mongolian answers are shown and are not writable. Nothing here asks for or displays an API key.

## Explicitly not this phase

No Postgres `query_log`, Redis, or embeddings. No GDPR paperwork, external IdP, or MFA. No live load test, no measured p50/p95, and no scored 40-case run. The admin notes live in the process and are not a durable history. Mongolian answers stay off.
