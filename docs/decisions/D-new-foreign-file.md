# D-new — Чужой SQLite-файл не принимается; WAL после миграций; «файл занят»
Статус: принято
Дата: 2026-10-27

## Контекст
`application_id` 0 — значение любой чужой базы: файл с таблицей `notes` получал 54 миграции и падал на «no company in file» с ложным «файл не изменён». WAL включался до миграции.

## Решение
`application_id` 0 принимается только у пустого файла (новый) или у файла с таблицей `companies` (наш до 0046); иначе — «это не файл компании Modern GL» до миграций, байты не меняются; так же для снимка (D80). `journal_mode = WAL` — после `migrate()`: неудачное обновление оставляет заголовок прежним. У `connect`/`connect_reader` явный `timeout` (5 с); «database is locked» — `BusyError(LedgerError)`: «Файл компании занят другой программой — закройте её и повторите».

## Последствия
Код: `infrastructure/db.py` (`_check_application_id`, `connect`, `BusyError`). Тесты: `tests/test_database.py`, `tests/test_transactions.py`.
