# D166 — Типы: тесты под pyright, ядро — strict, докстринги ядра обязательны
Статус: принято
Дата: 2026-10-27

## Контекст
pyright проверял только `src` в режиме standard: 29 000 строк тестов и скрипты — без
типов (285 ошибок), ядро допускало Unknown в параметрах и ответах (127 ошибок strict),
у 85 публичных классов и функций ядра не было докстрингов (ветка `claude/audit-types`).

## Решение
`[tool.pyright] include` — `src`, `tests`, `scripts`; `strict` — `domain`, `api` и файлы
`infrastructure` (`db.py` — временно нет, его правит `claude/audit-journal`). В тестах —
сужение `assert … is not None` и `isinstance`, помощники с типами `tests/helpers/qt.py`,
`excel.py`; `pyright: ignore` — только с причиной в строке. Ответы API — `dict[str, Any]`
(JSON) и TypedDict, без смены поведения и `API_VERSION`. ruff `D100`–`D105` (только
наличие докстринга) обязательны в `domain`, `infrastructure`, `api`, `application/ledger`
(отрицательный шаблон в `per-file-ignores`). `application/` в strict — по пакету:
`ledger` → модули.

## Последствия
`pyproject.toml` (`[tool.pyright]`, `extend-select`, `per-file-ignores`). Новый модуль ядра
сразу strict и с докстрингами. Долг: `db.py` в strict (4 ошибки: `@contextmanager` →
`Generator`) и D103 (5 функций); `application/` под strict — 769 ошибок (ledger 128, bank
107, inventory 76, exchange 72, vat 68, eqaime 41, quick_entry 35, conversion 13, файлы
верхнего уровня 229).
