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
)
