# D163 — Ruff строже: bandit, имена, pytest, без print и закомментированного кода
Статус: принято
Дата: 2026-10-27

## Контекст
Аудит линтера: `select` держал ошибки и стиль, но не безопасность (urlopen, XML, subprocess),
не имена исключений, не стиль pytest; `print`, лишние лямбды и функции на 20 аргументов
проходили молча.

## Решение
В `ruff` добавлены `S`, `T20`, `ERA`, `PT`, `N`, `PLW`, `PLC0414/0206/0207`, `PLR0913`
(`max-args = 8`; ветка `claude/audit-lint`). Находки исправлены в коде: исключения —
`…Error`, `urlopen` только по `https://`, лишние лямбды убраны (у `clicked` — оставлены с
причиной: сигнал передаёт `checked`), длинные списки аргументов складов — `StoredLine`,
`Movement`. Глушение — только с причиной в строке или в `per-file-ignores`. Не включены:
`PLR2004` (коды отчётов и колонки), `PLC0415` (ленивые импорты модулей, D123),
`PLR0911/0912/0915` (сложность — C90 ≤ 12 и `test_code_size`), `PT018`, `D`/`ANN` (типы —
pyright). `S608` выключен: SQL собирается из имён в коде, значения — параметрами; это стережёт
`test_sql_takes_values_as_parameters_not_text`.

## Последствия
Код: `pyproject.toml` (`[tool.ruff.lint]`), `tests/test_architecture.py` (`IDENTIFIER_PARAMS`),
`application/inventory/model.py` (`StoredLine`, `Movement`).
