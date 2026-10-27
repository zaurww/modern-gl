# 2026-10-27, ветка claude/audit-lint (D-new-ruff-strict)

Просьба: ужесточить ruff по итогам аудита — новые правила включить, находки исправить, а не глушить.

- Включены `S`, `T20`, `ERA`, `PT`, `N`, `PLW`, `PLC0414/0206/0207`, `PLR0913` (≤ 8); выключены с
  причиной в `pyproject.toml`: `S608`, `PT018`, `PLR2004`, `PLC0415`, `PLR0911/0912/0915`, `D`/`ANN`.
- Исправлено: 6 исключений → `…Error` (API не задет), 4 переменные цикла, 11 лишних лямбд (4 оставлены
  с причиной: `clicked` передаёт `checked` в необязательный параметр, одну подменяет тест), `x as x`,
  `urlopen` только по `https://`, `_insert_line`/`_insert_movement` → `StoredLine`/`Movement`.
- `S608` стережёт `test_sql_takes_values_as_parameters_not_text`: текстовый параметр в SQL f-строке
  (имена таблиц — `IDENTIFIER_PARAMS`); вставку через локальную переменную не видит.
- Временно в `per-file-ignores`: `main_window/window.py`, `company_files.py` — правит
  `claude/audit-window`, убрать при слиянии.

Проверено: `ruff check`, `ruff format --check`, `pyright` — 0; `pytest -n auto` зелёный.
