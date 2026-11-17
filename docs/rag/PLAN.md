# RAG для ассистента K4 — план (шаг 0)

Ветка `feature/rag-assistant`, создана от `main` (`5b8c68f`, Merge pull request #2). Код на шаге 0 не менялся.

## Исходное состояние (проверено запуском)

| Проверка | Результат |
| --- | --- |
| `python -m pip install -e .` | установлено без ошибок |
| `python -m unittest discover -s tests` (SQLite) | 220 тестов за 77 с: OK, 1 пропущен (проверка только для PostgreSQL), упавших 0 |
| `npm ci && npm test` (apps/web) | 3 файла, 18 тестов — все прошли |
| `npx tsc --noEmit` | без ошибок |

Окружение: Windows, Python из `.venv\Scripts` (в инструкции — `.venv/bin`, это одно и то же для Linux). numpy 2.5.5 уже стоит как зависимость `onnxruntime`, но в `pyproject.toml` явно не указан.

## Что подтвердилось и что нет в описании репозитория

| Утверждение из инструкции | По коду |
| --- | --- |
| `knowledge.py` — 15 правил и свой BM25 | **Частично.** В `knowledge.py` только 15 правил (`DOCUMENTS`). BM25 (`Index`), `stem` (6 букв) и `tokens` с `STOP` лежат в `engine.py:42–80` |
| `engine.answer` синхронный, на регулярных выражениях | Да, `engine.py:136` |
| RAG заменяет только финальный блок `INDEX.search` + fallback | **Не полностью.** См. «Точка встраивания» ниже: вопросы про стипендию, апелляцию, академ и перевод отвечают из правил **до** финального поиска |
| GigaChat только перефразирует | Да: `router.ask` → `giga.rephrase` для `kind in ("rule", "me")`, `router.py:75–80` |
| `gigachat.py`: токен 25 мин, семафор 1, размыкатель после 5 ошибок, TLS не отключается, тела не логируются | Да. Эмбеддингов нет. Исключения: `GigaChatUnavailable`, `GigaChatBlacklisted`, `GigaChatInvalid` |
| CI гоняет SQLite и PostgreSQL | **Частично.** Все тесты — на SQLite; на PostgreSQL в CI только `tests.test_auth tests.test_db` |
| Проверки прав staff — в `accounts/policy.py` | **Нет.** В `accounts/policy.py` только `can_view_student_profile` и `schedule_email`; staff-проверки раскиданы по модулям (`role not in ("staff", "admin")`) и есть `student_requests/policy.py`. Новые права для базы знаний добавлю в `accounts/policy.py`, как требует шаг 10 |
| Маскировщик персональных данных | Есть: `redbutton/stage1.mask_pdn` (e-mail, телефоны, ФИО автора). Переиспользую; номера зачёток и паспортов (длинные цифры) добавлю отдельным правилом, не меняя поведение «Красной кнопки» |
| CSRF | Глобальный middleware в `accounts/router.py:163` для всех небезопасных методов — новые эндпойнты получают его автоматически |
| Фронт: `kind` и `sources` | `AssistantPage.tsx:14`: `sources: {id, title}[]`; `kind` ответа на экране не используется (только `action.kind`). Новые поля добавляются без ломки |
| `python -m hse_schedule.cli` | Работает: в `cli.py:359` есть `if __name__ == "__main__"` |

## Точка встраивания RAG (шаг 9)

Текущий порядок в `engine.answer`:

1. Защиты: `INJECTION`, `OTHERS` → `kind="guard"` — **не трогаем**.
2. Консультация, пропуски (`attendance` + посещаемость студента) — **не трогаем** (смешаны с личными данными).
3. «Сделай за меня»: справки, военкомат, выписка, пересдача, матпомощь → `kind="draft"` — **не трогаем**.
4. Правило по ключевому слову: `acad-leave` (202), `transfer` (204), `appeal` (209), `scholarship` (211) → `_rule(...)`, `kind="rule"`.
5. «Про меня»: заявки, пары, дедлайны, баллы по дисциплине, общая успеваемость → `kind="me"` — **не трогаем**.
6. Приветствие → `kind="hello"`.
7. **Финал:** `INDEX.search(text)` при оценке ≥ 1.2 → `_rule`, иначе `kind="fallback"` с `handoff` (297–303).

Предположение инструкции (RAG только вместо п. 7) верно для п. 7, но тест шага 9 «вопрос про стипендию → источник из документа 04» при таком подходе не пройдёт: слово «стипенди» перехватывает п. 4 раньше. См. вопрос 1.

Технически: `engine.answer` синхронная, RAG асинхронный (БД, сеть). План — не делать `answer` асинхронной, а вернуть из неё признак «нужен поиск по базе» (`Reply(kind="search", ...)` с исходными действиями п. 4), а сам `await answer_from_kb(...)` вызвать в `router.ask`. При `RAG_ENABLED=false` признак не возвращается и поведение прежнее байт в байт.

## Что есть → что меняем

| Файл | Сейчас | Изменение | Шаг |
| --- | --- | --- | --- |
| `pyproject.toml` | numpy не указан; нет группы `kb` | `numpy` в runtime; `[project.optional-dependencies] kb = [pdfplumber, beautifulsoup4]`; package-data `assistant/kb/*.json` | 1, 3, 5 |
| `.env.example` | ключи GigaChat | `GIGACHAT_EMBED_MODEL`, `RAG_ENABLED` с комментариями | 2, 9 |
| `hse_schedule/gigachat.py` | `chat_json`, `rephrase` | `async embed(texts, model=None)`: тот же токен, семафор, размыкатель, исключения; батчи | 2 |
| `hse_schedule/cli.py` | `serve`, `reset-demo`, … | `gigachat-probe`, `kb-build`, `kb-embed`, `kb-stats`, `kb-eval` | 2, 5, 7 |
| `hse_schedule/assistant/engine.py` | BM25 внутри | вынести `stem/tokens/STOP` в `assistant/textsearch.py` (импорт обратно, поведение то же); признак «искать в базе» за флажком | 6, 9 |
| `hse_schedule/assistant/router.py` | `engine.answer` → `rephrase` | загрузка `Retriever` при старте; вызов `answer_from_kb`; источники в `sources`; лимит 30/60 сохраняется | 9 |
| `hse_schedule/accounts/policy.py` | 2 функции | `can_manage_kb(user)` | 10 |
| `hse_schedule/db.py`, `migrations/env.py`, `tests/test_db.py` | список модулей с моделями | добавить `assistant.kb` | 3 |
| `.github/workflows/tests.yml` | PostgreSQL: `test_auth test_db` | + `tests.test_kb_store` | 3 |
| `apps/web/src/features/assistant/AssistantPage.tsx` | источник одной строкой | карточки источников с цитатой; состояния `kb_extract`, `kb_refusal`; скелетон | 11 |
| `apps/web/src/features/staff/*`, `routes.tsx` | — | раздел «Пробелы базы» | 11 |
| `README.md`, `docs/PROCESS.md` | нет раздела RAG | раздел «RAG» в PROCESS (строка после каждого шага); строка K4 в README | каждый, 12 |

## Новые файлы

- `docs/rag/PLAN.md`, `NOTES.md`, `EVAL.md`, `README.md`
- `tools/rag_dataset/generate.py`, `verify.py`; `tools/rag_eval/eval_retrieval.py`
- `rag_test_data/` — 11 PDF, 3 HTML, `manifest.json`, `questions.json`, `README.md`
- `hse_schedule/assistant/textsearch.py` — общая токенизация для старого индекса и BM25 базы
- `hse_schedule/assistant/kb/`: `__init__.py`, `models.py`, `store.py`, `parse_pdf.py`, `parse_html.py`, `chunker.py`, `ingest.py`, `retriever.py`, `thresholds.json`, `answerer.py`, `prompts.py`, `router.py`
- Миграция **`0008_knowledge_base.py`**, `down_revision = '0007'` (текущая head — `0007_redbutton`)
- Тесты: `test_gigachat_embed.py`, `test_kb_store.py`, `test_kb_chunker.py`, `test_kb_cli.py`, `test_kb_retriever.py`, `test_kb_eval.py`, `test_kb_answerer.py`, `test_assistant_rag.py`, `test_kb_gaps.py`; vitest для экрана ассистента

## Риски

1. **Утечка данных студента в GigaChat уже сейчас.** `router.ask` отправляет в `rephrase` исходный вопрос без маскировки и ответы `kind="me"` — а в них баллы, заявки, расписание. Это нарушает жёсткое правило 2 этого плана. См. вопрос 2.
2. **Ключа GigaChat на этой машине нет** — он только на сервере в `/opt/mgimo/app.env`. Пробный вызов эмбеддингов (шаг 2), `kb-embed` (шаг 5) и векторные режимы оценки (шаг 7) локально не измерить. См. вопрос 3.
3. **Эндпойнт и тариф эмбеддингов не проверены.** В клиенте `GIGACHAT_API_URL=https://api.giga.chat/v1`; есть ли там `/embeddings`, какая модель доступна по ключу `GIGACHAT_API_PERS` и тарифицируются ли эмбеддинги отдельно — выяснит шаг 2 по документации и одному вызову.
4. **Freemium: один поток.** Эмбеддинг запроса пользователя делит семафор с «Красной кнопкой» и `rephrase`; при занятой очереди поиск уходит в режим `bm25_only` — это и есть требуемое поведение, но гибрид будет срабатывать не всегда.
5. **Малая выборка.** 15 вопросов — оценка ориентировочная, пороги калибруются на них же (переобучение на тест). Так и будет написано в `EVAL.md`.
6. **Ветка от `main`.** В `main` нет фикса очистки PostgreSQL в тестах (`9479dde` на `feat/campus-benchmark-upgrades`): без него `test_kb_store` на PostgreSQL может упасть так же, как падали тесты на сервере. См. вопрос 4.
7. **Память процесса.** Матрица векторов в памяти: для ~200–400 фрагментов это сотни КБ; демо работает одним процессом, `reload()` подменяет состояние атомарно.

## Вопросы

1. **Стипендия, апелляция, академ, перевод.** При `RAG_ENABLED=true` отвечать на них через RAG (сохранив их кнопки: мастер «Хочу взять академ», «Красная кнопка» и т. п.), а не только в финальном блоке? Без этого тест шага 9 про стипендию не пройдёт. **Предлагаю: да**, только для этих четырёх веток `_rule`; черновики, «про меня», пропуски и защиты не трогаю.
2. **`rephrase` и данные студента.** Отключить перефразирование для ответов `kind="me"` и маскировать вопрос перед `rephrase`? **Предлагаю: да**, на шаге 9 (несколько строк в `router.py`, тест на то, что баллы не уходят в GigaChat).
3. **Вызовы с настоящим ключом.** Разрешаешь запускать `gigachat-probe`, `kb-embed` и `kb-eval` на сервере (ключ остаётся только в `app.env`, в вывод не попадает)? Иначе векторная часть будет помечена «не измерено».
4. **Фикс тестов PostgreSQL.** Перенести коммит `9479dde` в эту ветку (cherry-pick) на шаге 3?
