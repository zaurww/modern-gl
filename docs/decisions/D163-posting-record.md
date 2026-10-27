# D163 — Проводка как значение — PostingRecord
Статус: принято
Дата: 2026-10-27

## Контекст
Список колонок проводки синхронизировался вручную в четырёх местах: вставка, сторно, сравнение при перепроведении, содержимое перестроения.

## Решение
`ledger/posting_record.PostingRecord` (frozen dataclass): `COLUMNS` в порядке таблицы `postings`, `from_input`, `from_row`, `params`, `negated`, `as_dict`. Вставка, красное сторно, сравнение содержимого, снимок для журнала действий и `POSTING_CONTENT` перестроения — через неё. Новая колонка проводки — одно поле здесь; тест сверяет со схемой.

## Последствия
Код: `application/ledger/posting_record.py`. Тест: `tests/test_audit_application.py`.
