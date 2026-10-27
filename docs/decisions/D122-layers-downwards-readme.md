# D122 — Слои — только сверху вниз; вход для человека — README
Статус: принято
Дата: 2026-10-24

## Контекст
—

## Решение
**Слои — только сверху вниз; вход для человека — README** (сессия 50; пользователь: «вся структура должна быть профессиональная… best practice… при добавлении нового функционала всё подчинено принципам»). Аудит нашёл: документ обещал «зависимости сверху вниз», а код нарушал (`infrastructure` → `Ledger`, цикл `application` ↔ `reporting`), тест этого не проверял; в корне не было README. Порядок: `i18n` → `domain` → `infrastructure` → `application` → `reporting` → `desktop`/`assistant`; слой импортирует только себя и слои ниже — `test_layers_depend_downwards_only`, новый пакет сначала в `LAYERS`. Перенесено без изменения логики: `chart_csv`, `Workspace` → `application` (движок файла — `infrastructure/company_file.py`); книги → `application/books.py`; реестр «Требует внимания» → `application/attention.py`; сбор по номеру e-qaimə, `open_invoices`, `invoice_rules` → `application`; `allocated_sql` → склад. Языки закреплены (ENGINEERING 4.9). `README.md` — вход для человека, `CLAUDE.md` — карта работы.

## Последствия
Код: `test_layers_depend_downwards_only`, `infrastructure/company_file.py`, `application/books.py`, `application/attention.py`.
