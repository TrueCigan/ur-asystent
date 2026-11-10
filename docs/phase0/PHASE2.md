# Phase 2 note (2026-11-09)

Owner approval: Kostya Prochan, chat review 2026-11-09. No paid model call. Render was not changed. `SCENARIO_SOCIAL` stays off by default. The 40-case score stays `not measured`.

## What landed

- `data/faq.yaml` has 9 entries. `data/synonyms.yaml` has 22 exact aliases. Both point only at facts already signed in `data/facts.yaml`.
- The fast path is `app/faq_fast.py`. Score is `0.65 * alias_match + 0.25 * token_coverage + 0.10 * scope_match`. Exact alias match is 1. It answers only at confidence ≥ 0.95 and margin ≥ 0.15, with one topic for that language. One keyword, a negation, a compound question, a relative deadline, or a missing year on a year-scoped fact does not take the path.
- `app/query_norm.py` keeps the original text. The search copy is NFKC, trimmed, lowercased, with typographic hyphens folded. Diacritics, digits, dates, and negation words stay.
- `app/intent_code.py` uses a closed term list in code. `data/canonical_ids.yaml` has no faculty or programme ids. An explicit unknown id asks for clarification.
- `app/hard_filter.py` filters before the limit. `app/rag.py` uses that only when the caller passes `hard_filters`. Ordinary search is unchanged. Embeddings are not added.

Signed facts used by the FAQ: `submission_channel`, `dorm_application_deadline`, `social_income_threshold`, `doctoral_rector_eligible`, `rector_cycle_eligibility`, `doctoral_stipend_period`, `rector_social_cap_monthly`, `rector_social_cap_monthly_2025_2026`, `erasmus_application_2026_2027`, `erasmus_rates_2026_2027`.

Not turned into FAQ answers: English-programme tuition, disability amounts, the owner recollection 3556, and any long-term traineeship monthly rate. The holdout Erasmus wording is not an alias and was not used to set the threshold.

A year-scoped fact does not answer a question that does not state that year. “Do kiedy składa się wniosek o akademik?” therefore stays on the normal search path. The same question with 2026/2027 can take the fast path. 3667 and 3560.60 stay on separate entries.

## Still not Phase 3–6

No answer-schema or SSE rewrite, no response cache, no `/admin/ai`, no live 0–4 scoring, no load test. The Mongolian greeting is unchanged. Whether the assistant should answer in Mongolian is still an open owner decision.
