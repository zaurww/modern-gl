# Modern GL

A desktop general ledger for an accountant in Azerbaijan: debit/credit postings with
subconto (analytics) in the style of 1C 7.7, several companies (one file per company),
parallel books (general / IFRS / tax). Modules on top of the core: bank, inventory,
purchases and sales, currency conversion, e-qaimə and ƏDV DH from the e-taxes portal, an AI
assistant (MCP). The interface is Azerbaijani (default) and Russian.

Python ≥ 3.12, PySide6, SQLite. One `*.gl` file is one company.

## Run and check

```sh
uv sync                      # dependencies (uv.lock)
uv run modern-gl             # companies are *.gl files in "Documents/Modern GL" (--data <folder>); --demo, --demo-year
uv run pytest -q -n auto     # all tests in parallel (pytest-xdist)
uv run ruff check . && uv run ruff format --check .
uv run pyright               # 0 errors
```

On Linux without a display: `QT_QPA_PLATFORM=offscreen` and the libraries `libegl1 libgl1
libxkbcommon0 libfontconfig1 libdbus-1-3` (see `.github/workflows/ci.yml`). Screenshots:
`uv run python scripts/screenshots.py <folder>`. Developer entry points: `modern-gl-cli`
(JSON output, `docs/API.md`) and `modern-gl-mcp` (the AI assistant, `docs/ASSISTANT.md`).

## How it is built

Layers, top down. A layer imports only itself and the layers below it; a test checks this
(`tests/test_architecture.py::test_layers_depend_downwards_only`).

| Layer | Package `src/modern_gl/…` | Responsible for | Not there |
|---|---|---|---|
| Interface | `desktop` | pages, forms, tables (PySide6) | SQL, accounting rules, transactions |
| Assistant | `assistant` | MCP server for an AI: the same reports and use cases | accounting logic of its own |
| API | `api` | for developers: `modern_gl.api`, `modern-gl-cli` (`docs/API.md`) | accounting logic of its own |
| Reports | `reporting` | trial balance, account card, balance sheet, P&L, cash flow, inventory, e-qaimə — read only, aggregation in SQL | writes |
| Use cases | `application` | `Ledger` and the modules (writes, one transaction per use case), shared reads (`queries`, `catalog`, `books`), module hook points, company files | Qt |
| Engine | `infrastructure` | `sqlite3` only here: connection, migrations, company file, backups, CSV/Excel, portals | accounting rules |
| Domain | `domain` | money (integer minor units), dates, periods, formulas | SQL, Qt |
| Texts | `i18n`, `i18n_az` | `tr()` and translations | — |

Key rules, each guarded by a test:

- **The core knows nothing about modules.** The core is the ledger, the chart of accounts and
  the directories. A module (bank, inventory, conversion, e-qaimə) is its own package in
  `application/`, its own tables in its own migration, its own pages in `desktop/`; it meets
  the core only through postings and a few hook points.
- **Money is integer minor units** (qəpik), never `float`. Posted documents are never
  changed without a trace.
- **Schema changes only by migrations** `infrastructure/migrations/NNNN_*.sql`; a written
  migration never changes (hashes in a test). Every table has `company_id NOT NULL`, composite
  foreign keys `(company_id, id)` and an index on every reference.
- **Size:** module ≤ 600 lines, class ≤ 500, function ≤ 80, complexity ≤ 12.
- **A window opens no transaction** and writes no SQL: a use case is one method of
  `Ledger`/`Inventory`.

## Where to read next

The project documents are in Russian (decisions, commit messages and documents are Russian by
rule D122; code is English).

1. `docs/CONCEPT.md` — the frame: why the program exists, the accounting model, the data.
   Changes only by the owner's decision.
2. `docs/ARCHITECTURE.md` — how it is built: layers, core and modules, data, interface, checks.
   The look of pages and reports — `docs/DESIGN.md`.
3. `docs/ENGINEERING.md` — engineering rules and the checklist for a new feature; the «Долг»
   (debt) section lists known deviations.
4. `docs/decisions/` — the decision log, one file per decision (`D001-…` … `D152-…`), index
   in `docs/decisions/README.md`. Code and documents refer to the numbers; a decision wins
   over any other document.
5. `docs/STATUS.md` — what exists and what is next; module documents: `INVENTORY.md`,
   `REPORTING.md`, `BOOKS.md`, `EQAIME_RECONCILIATION.md`, `ASSISTANT.md`, `API.md`,
   `EXCHANGE.md`.

`CLAUDE.md` at the root is the condensed working map (package structure and rules) read at
the start of every session by the AI assistant and by developers. `README.md` is the Russian
original of this page, with a glossary of the untranslated words (e-qaimə, ƏDV, VÖEN, subconto).

## Contributing

One branch per task in its own worktree, tests with hand-computed figures for any accounting
change, green `ruff`, `pyright` and `pytest` before a commit, a decision file for anything that
changes the meaning of entered data — see `CONTRIBUTING.md`.

## Licences of bundled resources

The Inter font — OFL, Lucide icons — ISC; licence files are in `src/modern_gl/desktop/resources/`.
