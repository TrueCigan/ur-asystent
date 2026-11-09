# Asystent studenta UR (prototyp RAG)

Czat-asystent dla studentów Uniwersytetu Radomskiego (uniwersytetradom.pl): stypendia, Erasmus+, opłaty, plany zajęć, regulaminy, cudzoziemcy, doktoranci. Odpowiada po polsku, wyłącznie na podstawie oficjalnych stron (ze źródłami i datami); najpierw dopytuje o sytuację studenta.

## Wdrożenie (Render, plan Free, bez karty)
1. Wgraj ten folder do repozytorium GitHub.
2. Render → **New → Blueprint** (lub **Web Service**) → wybierz repozytorium; Runtime: **Docker**, Plan: **Free**, Health check: `/healthz`.
3. Dodaj zmienną środowiskową `GEMINI_API_KEY` (klucz z Google AI Studio). Nie wpisuj klucza do plików!
4. Po zbudowaniu adres ma postać `https://ur-asystent.onrender.com`. Darmowa usługa usypia po 15 min bez ruchu – pierwsze otwarcie trwa ok. 1 min.

Pamięć: ~225 MB RSS (limit Render Free: 512 MB). Indeks jest gotowy w `data/` (index.npz + meta.json.gz), serwer go nie buduje.

## Деплой (по-русски)
GitHub (загрузить файлы через веб) → Render: New → Blueprint/Web Service → Docker, Free → переменная `GEMINI_API_KEY` → дождаться сборки → ссылка `*.onrender.com`. Сервер занимает ~225 МБ при лимите 512 МБ.

## Struktura
- `app/server.py`, `app/static/index.html` – FastAPI + czat (limity: 20 pytań / 10 min na IP).
- `app/rag.py` – wyszukiwanie hybrydowe (BM25 + char n-gram TF-IDF, fuzja RRF), dopytywanie, wywołanie Gemini (API zgodne z OpenAI, fallback modeli).
- `app/index.py` – budowa lekkiego indeksu (numpy/scipy, float16, słownik 60k n-gramów, maks. 400 n-gramów na fragment).
- `app/crawl.py` – crawler (wymaga `requirements-crawl.txt`); `data/docs.jsonl.gz` – zebrane dokumenty. Plany zajęć: WTEiI, WEiF, WM, WPiA, WNMiNoZ, WFP (`python crawl.py plans`).

## Aktualizacja danych (lokalnie)
```bash
pip install -r requirements-crawl.txt
cd app && python crawl.py plans && python index.py   # plany + indeks → commit
# pełny korpus: python crawl.py && python index.py
```

Zmienne: `GEMINI_API_KEY` (wymagany na żywym czacie), `LLM_PROVIDER=gemini`, opcjonalnie `LLM_MODEL`.
Lokalny szablon bez sekretów: `.env.example` (`LLM_PROVIDER=fake`, `EVAL_REAL=0`). To nie jest szablon produkcji Render.
Phase 0 (karta, fakes, 40 przypadków, baseline): `docs/phase0/README.md`.

```bash
python3 tests/eval_dialogues.py --repo . --layer unit
python3 tests/test_social_scenario.py
python3 tests/test_answer_contract.py
python3 tests/test_phase0.py
```
