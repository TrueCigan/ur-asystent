# Baseline текущего кода без платного API

Прогон 2026-11-09 на коммите `108c1dce42c72f2b6bb4cd14b46c76a3fea45c63`.
Этот отчёт поведение ассистента не меняет.

- Индекс: 6406 чанков (`data/meta.json.gz`)
- Эмбеддинги: выключены. `rag.load()` ставит `emb=None`. В прогоне `EMBEDDINGS_PROVIDER=disabled`
- `EVAL_REAL`: не задан, для адаптера это 0
- Режим: fake/off. Живая генерация: not measured
- Платные вызовы: 0. `POST /api/chat` живого сайта не вызывался
- `sim_student.py` не запускался, чтобы не перезаписать отслеживаемый `sim_results.md`
- Docker smoke в этом прогоне не запускался. Его по-прежнему гоняет job `eval-unit`

## Две строки

| Набор | Результат |
|---|---|
| Старый harness | `eval_dialogues --layer unit`: 103 cases, 0 failed, 0 skipped. `test_social_scenario.py`: 23 passed, 0 failed. `test_answer_contract.py`: 10 passed, 0 failed |
| Скелет 40 (`tests/phase0_cases.yaml`) | not measured |

Скелет не считается ни провалом, ни проходом. `approved_by` пуст, `facts_approved` везде false, `phase0_eval.score_label` возвращает `not measured`. Проверка файла и фейков (`test_phase0.py`) — 6 passed, 0 failed. Это проверка каркаса, не оценка качества ответов.

Старые 103 диалога остаются регрессией языка и слотов. Они не пересчитаны по шкале 0–4.
