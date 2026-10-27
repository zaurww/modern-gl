# 2026-10-27 — claude/strict-conversion (D170)

Пользователь: «давай» — следующий пакет strict pyright после `ledger`: `application/conversion`.

- 10 ошибок: подсубконто в `posting_line` без типа (`Sequence[int | None]`), строка
  таблицы в `_store` — голый `tuple`, `rates` — `default_factory=dict` без типов.
- `conversion` — в `strict` и в обязательных докстрингах (ruff D100–D105): 9 докстрингов.
- По `application/` под strict осталось 600 — «Долг» 8; меньше всего — `quick_entry` (35).
  Логика не менялась, тесты зелёные.
