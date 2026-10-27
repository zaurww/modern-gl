# D158 — Модули — композиция, не наследование ядра (уточняет D123)
Статус: принято
Дата: 2026-10-27

## Контекст
`BankModule` наследовал 40 публичных методов ядра (`ledger.bank.add_account` работал), одинаковые имена в складе и ядре имели разный смысл (`_document`, `_require_open_period`), склад имел два пути к ядру.

## Решение
Запись модуля (`BankModule`, `ConversionModule`, `EqaimeModule`, `Inventory`) строится на `ledger/module.ModuleBase`: соединение, автор, `self.ledger` — ядро, которое модуль вызывает, и `self.documents` — `ModuleDocuments(ledger)`: GL-документы модуля (`new`, `get`, `write`, `rebuild`, `rebuild_each` порциями, `unpost`, `remove`, `require_changeable`). Модуль не наследует команды ядра; к его внутренностям ходит только через `ModuleDocuments`. Ручки `ledger.bank` и т. п. передают модулю свой `Ledger`. Новый модуль («Касса») — так же.

## Последствия
Код: `application/ledger/module.py`. Тест: `test_architecture.py::test_a_module_calls_the_core_and_is_not_the_core`.
