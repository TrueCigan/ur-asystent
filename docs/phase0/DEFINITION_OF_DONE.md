# Phase 0 — definition of done

Фаза закрыта, когда выполнено всё ниже. Phase 1 не начинается из этого документа.

- Карточка: `docs/phase0/PROJECT_CARD.md`. Неизвестное остаётся неизвестным.
- Архитектура на одну страницу: `docs/phase0/ARCHITECTURE.md`.
- Пример окружения: `.env.example`. Секреты пустые, `LLM_PROVIDER=fake`, эмбеддинги `disabled`, `EVAL_REAL=0`, `UNIVERSITY_TIMEZONE=Europe/Warsaw`, `SCENARIO_SOCIAL=0`.
- Фейки: `app/adapters.py`, часы: `app/clock.py`. При `EVAL_REAL=0` адаптеры не открывают сеть. Реальный провайдер с ключом не подменяется фейком.
- Скелет 40 кейсов: `tests/phase0_cases.yaml`. 30 dev и 10 holdout. `approved_by` пустой. Holdout нельзя передавать в подбор порогов (`app/phase0_eval.py`).
- Baseline: `docs/phase0/BASELINE.md`. Две строки — старый harness и скелет 40. Скелет = `not measured`.
- Расхождение деплоя и монгольский: `docs/phase0/DEPLOY_AND_LANGUAGE.md`.
- Бэклог 1–6: `docs/phase0/BACKLOG.md`.
- CI: job `eval-unit` остаётся бесплатным гейтом и падает, если `EVAL_REAL=1`. Job `eval-e2e*` не становится обязательным зелёным.
- Платных вызовов нет. `POST /api/chat` живого сайта не вызывался. Render не менялся.

Повторяемая офлайн-команда из корня репозитория:

```bash
python3 tests/eval_dialogues.py --repo . --layer unit
python3 tests/test_social_scenario.py
python3 tests/test_answer_contract.py
python3 tests/test_phase0.py
```

`EVAL_REAL` должен быть пустым или `0`. Ключи в окружение не подставлять.
