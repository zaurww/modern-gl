# D77 — Движок базы знает только `infrastructure`; SQL — общий для SQLite и PostgreSQL
Статус: принято
Дата: 2026-10-22

## Контекст
—

## Решение
**Движок базы знает только `infrastructure`; SQL — общий для SQLite и PostgreSQL** (сессия 29; подготовка к возможной многопользовательской версии, не переход). Типы соединения, строки и ошибок (`Connection`, `Row`, `IntegrityError`, `DatabaseError`, `Error`), справочные запросы о схеме (`table_names`, `column_names`, `foreign_key_columns`) и id новой строки (`insert`) — в `infrastructure/db.py`; остальной код не импортирует `sqlite3`. В запросах — только то, что одинаково работает в обоих: `string_agg` вместо `GROUP_CONCAT` (SQLite ≥ 3.44), `ON CONFLICT` вместо `INSERT OR`, `COALESCE`, сортировка по `id`, а не `rowid`. Страж — `test_architecture.py::test_database_engine_only_in_infrastructure`. Плейсхолдеры `?` не меняем: при переходе их переведёт адаптер в `db.py`. Схему PostgreSQL при переходе пишем заново по текущей (деньги — `BIGINT`), а не повтором миграций SQLite. Файл на компанию (`workspace`, `backup`) остаётся SQLite-специфичным: на сервере это другая задача.

## Последствия
Код: `infrastructure/db.py`, `test_architecture.py::test_database_engine_only_in_infrastructure`, `db.py`.
