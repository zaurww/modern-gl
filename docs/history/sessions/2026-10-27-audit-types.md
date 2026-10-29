# 2026-10-27, ветка claude/audit-types (D-new — типы и докстринги ядра)

- **Тесты и скрипты под pyright**: было 285 ошибок, стало 0. Помощники с типами —
  `tests/helpers/qt.py`, `tests/helpers/excel.py`; одно `pyright: ignore` (тест, что float
  отвергается). Найдено: мёртвая ветка `ledger.companies` в `test_assistant`, dict вместо
  `Row` в `test_audit_application`, `invoice=None` в помощниках ƏDV.
- **strict для ядра**: domain 52 → 0, infrastructure 44 → 0 (без `db.py`: 4 ошибки
  `Iterator` → `Generator`, временно вне strict — правит `claude/audit-journal`), api 31 → 0.
  Дерево формулы — dataclass вместо кортежей; `ImportAnswer` (TypedDict) у API.
- **Докстринги**: 80 в domain, infrastructure, api, application/ledger; ruff D100–D105
  обязательны там (`db.py` — 5 функций, временно исключён).
- **Долг (для «Долга» в ENGINEERING при слиянии)**: `application/` под strict — 769 ошибок:
  ledger 128, bank 107, inventory 76, exchange 72, vat 68, eqaime 41, quick_entry 35,
  conversion 13, файлы верхнего уровня 229 (chart_csv, journal_import — по ~80). План: по
  пакету — сначала `ledger`, затем модули; пакет добавлять в `strict`, когда он чист.
