# Phase 1 note (2026-11-09)

Owner review: Kostya Prochan, chat review 2026-11-09. Render was not changed. No paid model call.

## What landed

- `tests/phase0_cases.yaml` records that review in `approved_by`. The 0–4 score stays `not measured`.
- The only case that refused Erasmus for lack of data is `p0-holdout-typo-01` (26th case in the file). It now expects the 2026/2027 DWZ path: faculty coordinator and dean, then Podanie do Prorektora and Formularz Studenta at DWZ, oral motivation at the interview, no written letter to the dean.
- File order 36 is `p0-dev-conflict-02`, the doctoral period question. It was not a no-data refusal. It now expects the owner rule: the stipend lasts during the academic year in which the application was accepted. The review text called the Erasmus refusal “case 36”; the file order does not match that number, so the Erasmus change follows the case that actually refused for missing data.
- File order 24–26 are typo questions, not refusals. They were not rewritten into refusals. Existing safe refusals (out of domain, secrets, injection, missing dean contact) stay refusals.
- Confirmed facts are in `data/facts.yaml`. The 2025/2026 cap value remains 3560.60. The owner’s 3556 is only a note. 3667 stays the 2026/2027 cap. English-programme tuition amounts were not signed.
- Crawl hosts move to `data/allowlist.yaml`. `app/crawl.py` no longer keeps an open redirecting client.

## Allowlist after the 2026-11-09 owner decision

Kostya Prochan approved only the official fact domains. Five hosts that were off are now enabled: `euczelnia.uniwersytetradom.pl`, `sjo.uniwersytetradom.pl`, `www.erasmusplus.org.pl`, `www.gov.pl`, `dziennikustaw.gov.pl`.

The eleven hosts that were already enabled stay enabled: `uniwersytetradom.pl`, `student.uniwersytetradom.pl`, `dwz.uniwersytetradom.pl`, `rekrutacja.uniwersytetradom.pl`, `bip.uniwersytetradom.pl`, `wteii.uniwersytetradom.pl`, `weif.uniwersytetradom.pl`, `wm.uniwersytetradom.pl`, `wpia.uniwersytetradom.pl`, `wnminoz.uniwersytetradom.pl`, `wfp.uniwersytetradom.pl`.

Still disabled: `kn.uniwersytetradom.pl`, `wicit.uniwersytetradom.pl`, `static1.squarespace.com`, `isap.sejm.gov.pl`, `odyseusz.msz.gov.pl`.

## Still not Phase 2–6

No FAQ fast path, no answer-schema/SSE rewrite, no response cache, no `/admin/ai`, no scored 40-case run.
