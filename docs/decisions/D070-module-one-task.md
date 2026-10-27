# D70 — Модуль — одна задача; крупный модуль делится на пакет
Статус: принято
Дата: —

## Контекст
—

## Решение
**Модуль — одна задача; крупный модуль делится на пакет** (сессия 21, пользователь: «важна чистота и простота кода… чтобы опытные разработчики не ругали»). Ориентир — до ~600 строк на модуль; больше — повод делить по задачам, а не по размеру. Модуль превращается в пакет с тем же именем, `__init__` реэкспортирует прежний публичный API (импорты в остальном коде не меняются); классы use case собираются из групп-миксинов, как `Ledger` (`Inventory` — так же). Перенос — отдельным коммитом, код переносится как есть, тесты не меняются. Разделены: `application/inventory`, `ledger/documents` (→ `validation`, `document_import`, `revaluation`), `desktop/inventory_document_page`, `landed_cost_page`, `postings` (общие помощники ячеек → `desktop/cell_editing.py`), `reports_page`. Большие классы-страницы делятся в сессии 22 на форму (`form.py`: поля строятся методами, общие вызовы — «крючки») и группы-классы по задачам, которые собирает страница; так разделены `BankOperationPage`, `MainWindow` (`CompanyFiles` ← `OpenPages` ← `MainWindow`), `InventoryDocumentPage`, `InventoryLinesModel`, `PostingsModel`; поиск в списке ячейки — один `cell_editing.resolve_choice`. В сессии 23 так же разделены `DocumentPage`, `conversion_page`, `directories_page`, окно e-qaimə, `reporting/inventory`; длинные `__init__` — методы `_build_…`. Процесс проверок — `docs/CODE_QUALITY.md`: пределы (модуль 600 строк, класс 500, функция 80) проверяет `tests/test_code_size.py`; сегодняшние превышения — список долга `OVER_LIMIT`, который может только уменьшаться; регулярный обзор — в конце каждой сессии и полный по чек-листу раз в ~5 сессий.

## Последствия
Код: `application/inventory`, `ledger/documents`, `desktop/inventory_document_page`, `desktop/cell_editing.py`, `form.py`, `reporting/inventory`, `docs/CODE_QUALITY.md`, `tests/test_code_size.py`.
