# Архитектура Phase 0

Одна страница. Стек остаётся Python / FastAPI / файловый индекс. Порты ниже — план, не новый рантайм. Phase 1 не начат.

## Сейчас → будущий порт

| Порт ТЗ | Сейчас | Файл |
|---|---|---|
| UI / API | `POST /api/chat`, карточка соцстипендии, `/healthz`, `/api/status` | `app/server.py`, `app/static/index.html` |
| LLM.answer | Прямой HTTP, если задан реальный провайдер и ключ. `LLM_PROVIDER=fake` возвращает фиксированную строку и не открывает сеть | `app/rag.py` `call_llm`, `app/adapters.py` |
| LLM.parse | Слоты через `extract_turn`, только когда живой LLM включён | `app/extract.py` |
| Embeddings.embed | В индексе выключены (`emb=None`). `disabled` и `fake` не ходят в сеть. Реальный провайдер при `EVAL_REAL=0` получает ошибку `unavailable`, не поддельный вектор | `app/embed.py`, `app/adapters.py` |
| Clock | Eval-часы Europe/Warsaw с `as_of`. Живой `facts.current_academic_year()` по-прежнему берёт `date.today()` сервера | `app/clock.py`, `app/facts.py` |
| SourceFetcher / DocumentExtractor | Офлайн-краулер без SSRF-проверок | `app/crawl.py` |
| SearchRepository | BM25 + символьные n-граммы, RRF, файл `data/index.npz` | `app/rag.py`, `app/index.py`, `app/topic_policy.py` |
| Cache | Нет кэша ответов. Лимит в памяти процесса | `app/server.py` |
| RateLimiter | 20 / 10 мин на IP, 1000 / час, семафор 3 | `app/server.py` |
| Telemetry | Строка лога с длительностью. Туда же попадает IP | `app/server.py` |
| JobQueue | Нет. Индекс коммитится в git | `Dockerfile` |
| Сессия | HMAC в браузере | `app/session.py` |
| Факты | YAML, рендер плейсхолдеров | `data/facts.yaml`, `app/facts.py`, `app/render.py` |
| Соцстипендия без LLM | Флаг выключен по умолчанию | `app/scenarios/social.py` |

Домен по-прежнему импортирует HTTP из `app/rag.py`. Выделять слои в этой фазе не нужно.

## Какая фаза трогает какой порт

Только очередь. В Phase 0 эти порты не строятся.

| Фаза | Порты | Смысл |
|---|---|---|
| 1 ingestion | SourceFetcher, DocumentExtractor, JobQueue, SearchRepository | allowlist, HTML/PDF, ревизии, SSRF |
| 2 retrieval | SearchRepository, FAQ, синонимы | hard filters, fast path, FTS без ключа |
| 3 answer | LLM.parse, LLM.answer | схемы §6, цитаты, фолбэк, SSE |
| 4 speed/cost | Cache, RateLimiter, Clock, Telemetry | ключ кэша без session id, бюджет |
| 5 admin | отдельного порта нет | `/admin/ai`, RBAC, аудит |
| 6 hardening | все внешние порты | нагрузка, retention, финальный eval |

Eval Phase 0 живёт отдельно от старых 103 диалогов: `tests/phase0_cases.yaml`, `app/phase0_eval.py`. Пока `approved_by` пуст, оценка скелета — `not measured`.
