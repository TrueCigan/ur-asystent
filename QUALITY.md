# Jakość odpowiedzi asystenta UR

Standard jak dla urzędu: bezpośrednia odpowiedź z faktów w korpusie, warunki dla profilu, kroki + oficjalne URL, bez BOS-only gdy źródła odpowiadają.

## Tematy (TOPIC_POLICY)

| Topic | Preferowane źródła |
|---|---|
| `stypendium_socjalne` | student.uniwersytetradom.pl (stypendia-socjalne, świadczenia, R-41/R-32) |
| `stypendium_rektora` | student – stypendium rektora / świadczenia |
| `stypendium_niepeln` | student – niepełnosprawność / świadczenia |
| `doktoranckie` | student – szkoła doktorska |
| `oplaty` | rekrutacja, student, BIP (wysokość opłat) |
| `erasmus` | dwz.uniwersytetradom.pl |
| `plan` | strony wydziałów (weif, wteii, …) |
| `cudzoziemcy` | rekrutacja-cudzoziemcow |
| `dwa_kierunki` | student – świadczenia / regulamin |

Polityka: `app/topic_policy.py` (boost/penalize URL, force-hits, substance regex). Retrieval i bramka jakości: `app/rag.py` (`search`, `ensure_canonical_hits`, `answer`).

## Złota regresja

```bash
# bez LLM (domyślnie) – tryb wyszukiwania
.venv/Scripts/python.exe app/sim_student.py

# z LLM (opcjonalnie)
SIM_LLM=1 .venv/Scripts/python.exe app/sim_student.py
```

Exit ≠ 0 przy dowolnym FAIL. Raport: `sim_results.md`.

Asserts: `expect_url` / `expect_host`, `forbid_url_family`, `forbid_bos_only`, `expect_substr`, `max_clarify_turns`, `expect_profile_pobyt`.

## Przy FAIL

1. Sprawdź, czy kanoniczna strona jest w crawl/indeksie (`data/`).
2. Doprecyzuj `TOPIC_POLICY` (boost / force / penalize) – nie „podkręcaj” promptu LLM jako pierwszego kroku.
3. Uruchom ponownie `sim_student.py` do PASS.

## Method for the next verified topic

Use this for dormitory prices, the rector's scholarship, Erasmus+, and tuition. The steps transfer. The amounts, years, and eligibility rules do not: each topic needs its own checked sources. Do not copy a social-scholarship figure into another topic.

Record one row per defect: symptom, the smallest repro, the root cause, the fix, the regression, and the evidence SHA. Independent QA checks that exact SHA. The author of the fix does not call that check a pass.

Order of proof, and stop when the next step needs a paid model: offline test, then one HTTP or browser repro with the model off, then the Docker smoke in `eval-unit`, then at most one `eval-e2e-pr` run. A green workflow with `eval-e2e-pr` skipped or `continue-on-error` is not a green e2e. `[skip e2e]` in the HEAD commit skips only that live job. `[skip ci]` would also skip the unit tests and the Docker smoke, so do not use it for this.

What held up on the social-scholarship work (`3133929` and the commits under it):

- A signed session keeps income and year after the form drops `scenario_context`. Fix: those estimate fields apply only when this request sends them again. Other profile slots stay.
- Empty history was sent into slot gating, so a cap or English-fee question was clarified instead of answered.
- `pobyt=ukr` / PESEL UKR is not inferred from Ukrainian citizenship alone.
- Group I in the 2025/2026 annex starts at 0,01 zł. Zero is a valid input and is outside the published band.
- Saying “I live in DS3” does not meet the dorm supplement conditions. 1400 and a separate 400 are not an 1800 total.
- A disability question that never states status may ask for status. It must not ask again for a degree the person already gave.
- The image must contain `data/scenarios`. A COPY line is not a runtime pass. `scripts/ci_docker_smoke.sh` is.
- Fact URLs in the answer have to be cited verified facts or retrieved pages, with fact id on the source. Do not harvest URLs out of the generated sentence. A made-up URL stays untrusted.
- Doctoral self-identification belongs to the speaker only. The closest subject before the role decides: `я` / `jestem` / `I am` counts; `вона`, `він`, `вони`, `ми`, `она`, `kolega`, `she`, `he`, `they`, `we` do not. A quoted example, a negation, and a bare `є аспірантом` do not write the profile. The copula `є` is not the pronoun `я`. A word boundary is still required, because `для аспіранта` ends in `я`. A third-person question does not become the speaker’s status, and a missing status still asks who the person is.
- Doctoral money has two layers and two sources. The gov.pl page dated 26.02.2024 lists 3570,50, 5500,50 and 1071,15. It does not establish 2026/2027 or 01.01.2026. The professor salary of 9650, for pay due from 01.01.2026, is Dz.U. 2026 poz. 525 of 14.04.2026: https://dziennikustaw.gov.pl/DU/2026/525 . That URL belongs to the salary fact only. It is not a stipend decision, and a salary date does not date the stipend. 37% and 57% are the bases; the supplement is 30% of the pre-evaluation base. 6571,65 is 5500,50 + 1071,15. The stipend period is not confirmed. A fact named in prose without its own official URL is not a finished source.

- An English answer is not English if it still contains a Polish fact note or a Polish retrieval quote. The live language check treats any of `ąćęłńóśźż` as Polish, including inside an otherwise English tuition reply. Keep the verified amount (`2100 EUR`) and drop the untranslated note and the raw quote from the English text. The session language being English is not enough.

What did not work: clearing only the visible form, treating 0,00 as group I, mixing the 3560,60 and 3667 caps, calling the workflow green while the advisory e2e job was red, rounding 6571,65 to 6571, matching `я` inside `для`, calling the 2024 stipend page proof of a 2026 period, and treating a Polish quotation under an English header as an English answer.

The four-case runner on `140c846` (workflow run 42198353726, about 4.4 seconds) printed PASS. That result is **LLM UNCONFIRMED**. The log has no success status, no request id, and no model reply. The offline fallback already satisfies those four assertions, so a text match is not a model call. Do not describe that batch as a successful live or model run. A short wall clock without a request id is not a generation.

A product pass and a verified model path are different results. `6296e7a` recorded transport metadata, and its contract, unit, and Docker checks passed (Docker job on run 42200679975). The path check on that SHA still demanded a model reply on every live turn. A clarification or a security refusal has no model call, so the next 15-case run would have failed those turns for the wrong reason.

The reply path is now typed. `clarification`, `refusal`, and `deterministic` may meet the case text with `provider_verified` false. They are not labeled as a model success. A case marked `requires_model` fails when the final text is a fallback, including a connection error and a 200 whose text was discarded. A transport error is not given a free pass on other cases either. An accepted typed 200 can set `provider_verified` in a mock. `external_run` stays false: the typed record is not a claim that a live provider was called. The future CI trace prints the whole redacted answer with mode and provider. Cutting it at 240 characters can hide the fee or the language. Keys, cookies, and session tokens are not written into that trace.

English acceptance is the prose, not the absence of `ąćęłńóśźż`. "The fee at Łódź is 2600 EUR" stays English. "Koszt programu wynosi 2600 EUR" does not. The e2e `lang_in` detector still treats any of those letters, anywhere in the answer, as Polish. That assertion was not weakened. A programme check must reject a wrong binding, such as Mechanical Engineering at 2100 EUR, instead of appending 2100 beside it. International Business & Finance stays 2100 EUR. Mechanical Engineering is 2600 EUR.

Still open, and not claimed from that runner: whether a real model keeps English on the two tuition turns, and whether 3667 replaces 3560,60 inside the 2025/2026 academic year after 01.01.2026. Do not merge those stipend figures. `SCENARIO_SOCIAL` stays off in the deployed service.

## Verified scenario: social scholarship

Product switch: `SCENARIO_SOCIAL=1` (default **off**).

- Card + estimate: `GET/POST /api/scenarios/social-scholarship` — **no LLM**, figures from `data/facts.yaml` via `data/scenarios/social_scholarship.yaml` refs.
- Amounts are year-scoped (`social_income_threshold` = 2025/2026). Cap 3560,60 (2025/2026) and 3667 (2026/2027) are separate facts, not auto-merged.
- Dorm +400 is conditional (Regulamin § 12); not added to the estimate total unless `dorm_conditions_met=true`.
- Chat under the flag answers this topic with localized copy only (no generative wrapper).

## Redesign freeze (round 7+)

Seven live QA rounds showed that regex / string-substitution post-processors fix one symptom and break a neighbour (amount stripper holes, channel garble, FOLLOW-UP leaks, Mongolian replies).

**Freeze rules while the redesign lands:**

1. **No new answer-mutating regex** in `app/rag.py` (no more `_collapse_channel_phrases`-style patches, no new strip notes).
2. **Figures** go through the structured path (`app/render.py` + fact placeholders) — Phases 1+.
3. **Output languages** target `{pl, en, uk}` only (Phase 3); Russian input → Ukrainian.
4. One git branch / PR per redesign phase (`redesign/p0-…` … `redesign/p6-…`). Merge only with green required checks; never Bypass.
5. Golden fixtures under `origin: r7-*` / `property_check` lock the bugs until the phase that fixes them; cases may use `expect_fail_until: redesign/pN` so the harness prints **SKIP** (not PASS/FAIL) until that phase.

See `CURSOR_REDESIGN_PLAN_round7.md` for phase order: P0 fixtures → P1 render → P2 delete strippers → P3 lang → P4 slots → P5 corpus → P6 CI.

### PR e2e subset (`e2e_pr`)

Mark a case with top-level `e2e_pr: true` when it must run on every PR that has `LLM_API_KEY` (workflow job `eval-e2e-pr`). Keep the subset small (≈10–15 cases): language, stripper/marker holes, slots, derived totals, tuition corpus.

```bash
python tests/eval_dialogues.py --repo . --layer e2e --e2e-pr --runs 1
```

Nightly / workflow_dispatch still runs the full e2e layer (`--runs 3`).

### Structured answer JSON (Phase 1+)

Model output (JSON only):

```json
{
  "lang": "uk",
  "template": "Po ocenie: {{F:doctoral_stipend_amount.po_ocenie_srodokresowej}}. Z orzeczeniem: +{{F:doctoral_disability_topup_monthly}} = {{C:doctoral_with_disability_po}}.",
  "fact_ids": ["doctoral_stipend_amount", "doctoral_disability_topup_monthly"],
  "source_ids": [1, 2],
  "computed_need": ["doctoral_with_disability_po"]
}
```

Server (`app/render.py`) substitutes `{{F:…}}` / `{{C:…}}` from `data/facts.yaml` and code-derived totals. Templates with raw `3667 zł`-style money are rejected.
)
