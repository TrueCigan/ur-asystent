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

## Redesign freeze (round 7+)

Seven live QA rounds showed that regex / string-substitution post-processors fix one symptom and break a neighbour (amount stripper holes, channel garble, FOLLOW-UP leaks, Mongolian replies).

**Freeze rules while the redesign lands:**

1. **No new answer-mutating regex** in `app/rag.py` (no more `_collapse_channel_phrases`-style patches, no new strip notes).
2. **Figures** go through the structured path (`app/render.py` + fact placeholders) — Phases 1+.
3. **Output languages** target `{pl, en, uk}` only (Phase 3); Russian input → Ukrainian.
4. One git branch / PR per redesign phase (`redesign/p0-…` … `redesign/p6-…`). Merge only with green required checks; never Bypass.
5. Golden fixtures under `origin: r7-*` / `property_check` lock the bugs until the phase that fixes them; cases may use `expect_fail_until: redesign/pN` so the harness prints **SKIP** (not PASS/FAIL) until that phase.

See `CURSOR_REDESIGN_PLAN_round7.md` for phase order: P0 fixtures → P1 render → P2 delete strippers → P3 lang → P4 slots → P5 corpus → P6 CI.

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
