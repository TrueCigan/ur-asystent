# Phase 3 note (2026-11-09)

Owner approval: Kostya Prochan, chat review 2026-11-09. No paid model call. Render was not changed. `SCENARIO_SOCIAL` stays off. The 40-case score stays `not measured`.

## What landed

- `app/answer_contract.py` checks the TZ intent and answer objects. Extra fields are rejected. Answer text is 1–3000 characters. Citations are at most five, with unique `n` and `chunk_id`. Every `[n]` must match a citation and the reverse.
- URL, title, and page are copied from the server manifest. A model-supplied URL is an extra field and is rejected. An unknown `chunk_id` falls back.
- Prompts are `data/prompts/parse_v1.txt` and `data/prompts/answer_v1.txt`. Settings in `data/prompts/manifest.yaml`: temperature 0, parse ≤300 tokens, answer ≤700, context ≤4500, timeouts 1s/4s, budget 6s. `allow_two_calls` is false, so the default path does not make a parse call plus an answer call.
- The generation path makes one model call. Invalid JSON, a timeout, or HTTP 429 becomes the existing verified fallback. There is no repair call.
- `POST /api/chat` is still JSON. `POST /api/chat/stream` sends `status`, `sources`, `answer`, `done`, and `error` only after the answer is checked. That is buffered streaming, not live model tokens. The page reads the stream and falls back to JSON if the stream is unavailable. Links stay `http(s)` with `rel="noopener noreferrer"`.
- The approved FAQ path fills the same answer object with `status=answered` and citations from the signed FAQ sources. It still makes no model or embedding call. No new FAQ facts were added.

## Still not Phase 4–6

No response cache, single-flight, or cost ledger. No `/admin/ai`. No live 0–4 score. No load test. The assistant still does not answer in Mongolian. Official faculty and programme ids are still unknown.
