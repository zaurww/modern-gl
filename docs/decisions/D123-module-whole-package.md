# D123 — Модуль — свой пакет целиком, чтение и запись
Статус: принято
Дата: 2026-10-24

## Контекст
—

## Решение
**Модуль — свой пакет целиком, чтение и запись** (сессия 50; «холодное чтение» свежим агентом: «документы говорят „модуль — свой пакет“, а запись банка и конвертации живёт внутри `application/ledger/`; новичок пойдёт в `application/bank/` за проводками и не найдёт их»). Запись модуля переехала в его пакет: `application/bank/` (`commands`, `account_commands`, `deposit_commands` → `BankModule`), `application/conversion/` (`calc` ← `conversions.py`, `commands` → `ConversionModule`), `application/eqaime/` (`eqaime_import/` + `portal` ← `eqaime_portal.py` + `commands` → `EqaimeModule`). `Ledger` держит только ручки `bank`/`conversion`/`eqaime` с импортом при первом обращении — при загрузке ядро модулей не знает (тест). Образец для нового модуля («Касса») — один: пакет в `application/`, `*Module` в его `__init__`, таблицы в `MODULE_TABLE`, пакет в `MODULE_CODE`. Логика не менялась.

## Последствия
Код: `application/ledger/`, `application/bank/`, `application/conversion/`, `conversions.py`, `application/eqaime/`, `eqaime_import/`, `eqaime_portal.py`, `application/`.
