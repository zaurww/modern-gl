# 2026-10-27, ветка `claude/audit-docs` (D188)

- Задача: внедрить результаты аудита документации. Сделано четырьмя коммитами:
  (1) `docs/DECISIONS.md` (252 КБ одной таблицей, строки до 7 181 символа) разобран
  скриптом `scripts/split_decisions.py` на 152 файла `docs/decisions/D001-<slug>.md` …
  `D152-<slug>.md` — текст ячеек без потерь (147 338 символов в ячейках, каждая найдена в
  своём файле целиком; «Ещё не решено» → `docs/decisions/OPEN.md`); индекс
  `docs/decisions/README.md` генерирует `scripts/decisions_index.py`; `tests/test_decisions.py`
  (форма, номера без пропусков, индекс актуален, ≥ D109 — контекст и решение ≤ 1 200
  символов; проверка перенесена из `test_docs_size.py`); `DECISIONS.md` — указатель;
  ссылки в `CLAUDE.md`, `README.md`, `CODE_QUALITY.md`, `CONCEPT.md` п. 8, `ENGINEERING.md` 4.8;
  (2) `README.en.md`; (3) `CONTRIBUTING.md`; (4) докстринги модулей `domain`, `dates`,
  `errors`, `infrastructure`.
- D188 (файл `docs/decisions/D188-adr-decision-files.md`): решения — файл на решение в
  формате ADR (статус, контекст, решение, последствия).
- Дрейф, не правился: `docs/STATUS.md:21` — тестов 1 452, ~5 мин с `-n auto`; `README.md:15`
  (число и время тестов) правит другая сессия; `docs/STATUS.md:28` и `CONCEPT.md:5` ещё
  говорят «`docs/DECISIONS.md`, искать `| D<номер> |`» — указатель на месте, но строку стоит
  обновить при следующей правке STATUS/CONCEPT.
- Осталось: «Контекст» у перенесённых решений — «—» (в таблице колонки не было);
  докстринги классов и функций (D101–D103, ~1 400) не писались — по задаче только модули.
