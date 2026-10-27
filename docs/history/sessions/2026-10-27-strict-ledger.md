# 2026-10-27 — claude/strict-ledger (D170)

Пользователь: «давай 2» — очередь после `erp-practices`: strict pyright для `application/ledger`.

- 130 ошибок, почти все от голых `dict`/`tuple` в общих местах: детали журнала действий —
  `Mapping[str, object]` (`write_audit`, `with_reason`, `_audit`), `as_dict`, `params`,
  `Contents` у перестроения (`module.py`), типы пустых списков и `default_factory`.
- 14 — закрытые методы ядра из `ModuleDocuments`: это дверь ядра для модулей, открывать
  их нельзя (журнал переписал бы проведённое в обход правил) — `reportPrivateUsage` выключен
  в одном `module.py` с объяснением; снаружи пакета внутренности `Ledger` никто не трогает.
- `ledger` — в `strict`; по `application/` осталось 609 (было 769) — «Долг» 8, дальше —
  `conversion` (12). Логика не менялась, тесты зелёные.
