# Phase 4 note (2026-11-09)

Owner approval: Kostya Prochan, chat review 2026-11-09. No paid model call. Render was not changed. `SCENARIO_SOCIAL` stays off. The 40-case score stays `not measured`.

## What landed

- `app/phase4.py` keeps an in-process public cache. The key is SHA256 of university id, normalized query, answer language, sorted filters, index revision, settings revision, prompt version, and model version. Session id and user id are not inputs. The stored value drops the HMAC session token. A question with an email, a long digit run, or an album number skips the cache.
- TTLs follow the TZ: 15 minutes, 5 minutes when the answer is about a deadline, 60 seconds for `no_answer`, 24 hours for intent, and at most 24 hours for FAQ. A nearer `valid_to` shortens the TTL. A relative date puts the resolved Warsaw date into the filters and also caps the TTL at the next local midnight. Changing the index revision, FAQ, synonyms, settings, or prompt changes the key and clears older entries.
- Identical in-flight requests share one computation. The rate limit runs before the cache: 20/minute and 200/day on a short-lived HMAC of the network id, 60/minute globally, and at most 10 concurrent generations. Over the limit the API returns 429 with `Retry-After`. A full generation slot returns 503. The raw network id is not stored and is not written to the `ur.api` log. If the cache is marked down, the same limiter still runs and the pipeline answer is returned unchanged.
- After 5 provider errors in 30 seconds, generation pauses for 60 seconds and the existing verified fallback is used. There is still one model call on the normal path. `allow_two_calls` stays false. Parse 1s, answer 4s, and the 6s budget stay the SLO in `data/prompts/manifest.yaml`.
- Cost uses USD per 1M input, output, cached input, and embedding tokens: `(uncached_in * p_in + cached_in * p_cache + out * p_out + emb * p_emb) / 1e6`. A provider charge replaces the estimate. An unknown price used by a non-zero token count stays `cost_status=unknown` with no numeric cost. Query spend and ingestion spend are separate. `data/prices.yaml` leaves the example prices empty. That file is not a live bill. A configured `DAILY_GENERATION_BUDGET_USD` stops new model calls and leaves FAQ, search, and templates. An empty budget does not invent a cap.

## Explicitly not this phase

No Postgres `query_log`, Redis, pgvector, or embeddings. The shipped index has no query-embedding cache. No admin UI. No live 10-concurrent load test, no measured p50/p95, and no claim of a 50% cost saving. No scored 40-case run. Mongolian answers stay off. No new faculty or programme ids, and no new tuition, disability, or 3556 figure.

Any timing printed by `tests/test_phase4_speed.py` is a local fake labeled `NOT TZ STAND`. It is not the stand DoD.
