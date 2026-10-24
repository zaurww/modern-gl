# API для разработчиков — `modern_gl.api`, версия 1

Для тех, кто пишет скрипт или связывает другую программу с Modern GL (D130). Публично
только то, что описано здесь: оно меняется лишь вместе с `API_VERSION`. Всё остальное в
`modern_gl.*` — внутреннее и может поменяться в любом выпуске. Контракт держат тесты
`tests/test_api.py`: сломанный там тест — сломанный чужой скрипт.

## Python

```python
import json
from modern_gl.api import open_company

with open_company("Xəzər Ofis MMC.gl") as company:  # снимок: файл не меняется
    osv = company.trial_balance("2026-01-01", "2026-03-31")
    chart = company.chart_of_accounts()
    march = company.export_documents("2026-03-01", "2026-03-31")

with open_company("Başqa MMC.gl", write=True, actor="etax-ext") as company:
    result = company.import_documents(march, check=True)  # только сказать, что будет
    if result["ok"]:
        company.import_documents(march)  # черновики
```

| Что | Ответ |
|---|---|
| `open_company(path, write=False, actor="")` | компания из файла `.gl`. Без `write` — снимок в памяти (D80): файл можно держать открытым в программе. С `write` — сам файл; файл старой схемы сначала копируется и обновляется, как в программе |
| `Company.name`, `.read_only` | название, открыта ли только для чтения |
| `.chart_of_accounts()` | `{"accounts": [...]}` — код, имя, группа, родитель, класс, тип, субконто |
| `.trial_balance(date_from, date_to, book="common")` | ОСВ: `rows` и `total`, у каждой — `opening`, `turnover`, `closing` как `{"debit", "credit"}`; книга — `common`, `ifrs`, `tax` |
| `.export_documents(date_from, date_to, book="common")` | проведённые документы периода — файл обмена (`docs/EXCHANGE.md`) |
| `.import_documents(data, post=False, check=False)` | файл обмена → `{"ok", "new", "created", "existing", "errors"}`; `created`/`existing` — `{"id", "number"}`, `errors` — `{"id", "message"}` |
| `API_VERSION` | `1` |

Ответы — простые данные, готовые для JSON: суммы — строки в манатах с двумя знаками
(`"1234.50"`), даты — ISO. Ошибки: `FormatError` — файл не того вида; `ReadOnlyError` —
запись в компанию, открытую без `write`; `LedgerError` — правило учёта.

**Всё записанное — через правила программы.** API пишет только через `Ledger`: те же
проверки, что при вводе руками, журнал действий, автор — «API · <actor>» в шапке документа
(D82). Другого пути в базу нет — прямой SQL к файлу компании не поддерживается.

## Командная строка — `modern-gl-cli`

```sh
uv run modern-gl-cli chart "Xəzər.gl"
uv run modern-gl-cli trial-balance "Xəzər.gl" --from 2026-01-01 --to 2026-03-31 [--book ifrs]
uv run modern-gl-cli export "Xəzər.gl" --from 2026-03-01 --to 2026-03-31 > march.json
uv run modern-gl-cli import "Başqa.gl" march.json [--check] [--post] [--actor etax-ext]
```

Ответ — JSON в stdout; код возврата: 0 — прошло, 1 — ошибка в данных (`{"error": …}` или
`errors` импорта), 2 — неверная команда. `--lang az|ru` — язык сообщений.

## Чего пока нет
Справочники и остатки по субконто, карточка счёта, черновики по одному, внешние отчёты и
обработки — следующие шаги, `docs/EXTENSIBILITY.md`. AI-помощник (`docs/ASSISTANT.md`)
читает то же через MCP.
