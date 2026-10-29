# 2026-10-27 — claude/audit-application (D-new ×2)

Аудит слоя `application`: побочные эффекты, дубли, ошибки, наследование ядра модулями.

- Геттер `_layer_id` больше не пишет; книги включает сценарий документа (`_show_books_for`).
  «Субконто по виду» — одна `common.fill_subconto` вместо семи копий. Карта ссылок
  `where_used` читается раз на версию схемы. «Не найден» — `NotFoundError`, строка обмена —
  `FormatError`, четыре `assert` — явные проверки. `answers.py` → `reporting/` (api без assistant).
- **D-new «Модули — композиция, не наследование ядра» (уточняет D123):** запись модуля
  (`BankModule`, `ConversionModule`, `EqaimeModule`, `Inventory`) строится на
  `ledger/module.ModuleBase`: соединение, автор, общие поиски `LedgerBase`, `self.ledger` —
  ядро, которое модуль вызывает, и `self.documents` — `ModuleDocuments(ledger)`: GL-документы
  модуля (`new`, `get`, `write`, `rebuild`, `rebuild_each` с загрузкой порциями, `unpost`,
  `remove`, `require_changeable`). Модуль не наследует `DocumentCommands`/`SubcontoCommands`/
  `ChartCommands`: `ledger.bank.add_account` — не вызов, в модуле нет одноимённых методов
  ядра с другим смыслом; к внутренностям `Ledger` модуль ходит только через `ModuleDocuments`
  (страж `test_a_module_calls_the_core_and_is_not_the_core`). Ручки `ledger.bank` и т. п.
  передают модулю свой `Ledger`. Новый модуль («Касса») — так же.
- **D-new «PostingRecord»:** проводка как значение — `ledger/posting_record.PostingRecord`
  (frozen dataclass): `COLUMNS` в порядке таблицы `postings`, `from_input`, `from_row`,
  `params`, `negated`, `as_dict`; вставка, красное сторно, сравнение содержимого при
  перепроведении, снимок для журнала действий и `POSTING_CONTENT` перестроения — через неё.
  Новая колонка проводки — одно поле и одно имя здесь (тест сверяет со схемой).
- Было → стало: `BankModule` 15 классов в MRO, 60 публичных методов (40 — ядра) → 10, 20 (0);
  `ConversionModule` 10, 45 (40) → 5, 5 (0); `EqaimeModule` 4, 3 → 5, 4; склад — один путь к
  ядру (`_document` → `_inventory_document`, `_require_open_period` → `_require_inventory_open`).
- Замер на демо-годе (1 247 операций банка, лучшее из 3): перестроение банка за год 46,0 →
  39,5 мс, конвертации 2,2 → 2,1, перенос 50 операций туда и обратно 11,5 → 10,2, операция
  из 40 строк 1,4 → 1,2 мс. Остальное — построение проводок и сравнение, по документу.
- Не сделано: `post_receipt`/`create_receipt_draft`/`update_receipt_draft` сохранили прежние
  аргументы (их вызывают desktop и ~60 тестов в параллельных ветках) — это обёртки над
  `ReceiptHeader` и `post_new_receipt`/`save_receipt_draft`/`change_receipt_draft`; конвертации
  при перестроении читаются по одной (их единицы). Общие документы не правились.

Проверено: `pytest -n auto` (1469), `ruff`, `pyright` — 0 ошибок.
