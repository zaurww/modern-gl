# Modern GL — Architecture Decision & Technical Design

**Version:** 0.1 (draft)  
**Date:** 2026-10-19  
**Companion:** `SPEC.md` v0.1  
**Status:** Proposed architecture; decisions marked *open* require prototyping / accounting sign-off.

## 1. Architectural objectives

Build a local, Windows-first, keyboard-centric double-entry general ledger for one accountant and multiple companies. First deployment: PySide6 desktop + local SQLite. Future deployment: multiple desktop clients communicating with a service backed by PostgreSQL; optionally a browser UI. Do **not** attach accounting logic to the desktop forms or write raw SQL inside report widgets.

Non-negotiable invariants: balanced posted journals; traceable revisions and reversals; strict company isolation; reproducible reports; deterministic arithmetic; configurable charts of accounts; flexible accounting views (`common`, `ifrs`, `tax`); Unicode; good perceived performance; upgradeable schema.

## 2. Architectural style

**Modular monolith with ports/adapters.** A single Python distribution, internally split into domain, application, infrastructure and presentation layers. No distributed services or arbitrary runtime plugin framework in the MVP.

```text
PySide6 views / keyboard commands / Qt table models
                     |
                application API
    use cases / DTOs / auth context / Unit of Work
                     |
          domain model and policies
companies, accounts, journals, layers, analytics
                     |
          repository contracts (ports)
                     |
 SQLAlchemy implementations / migrations / SQLite

Future: REST API adapter -> same application use cases
        SQLAlchemy PostgreSQL adapter -> same repository ports
```

**Dependency direction:** presentation -> application -> domain. Infrastructure implements domain/application ports; domain imports neither Qt nor SQLAlchemy. Keep accounting rules in domain services and use cases, not database triggers alone. Database constraints are defense in depth.

### Suggested repository layout

```text
modern-gl/
  pyproject.toml
  README.md
  SPEC.md
  ARCHITECTURE.md
  AGENTS.md
  src/modern_gl/
    domain/
      companies/       accounts/      journals/
      books/           currencies/    dimensions/
    application/
      commands/        queries/       dto/
      ports/           services/
    infrastructure/
      db/models/       db/repositories/
      db/migrations/   export/
    desktop/
      views/           viewmodels/     qtmodels/
      shortcuts/       styling/
    reporting/
      definitions/     queries/       formatting/
    bootstrap/
  tests/
    unit/              integration/   accounting_cases/
    performance/       ui/
  scripts/
    seed_demo.py       generate_load.py
```

Module boundaries are conceptual and may be organized as vertical feature packages later. Avoid a monolithic `utils.py` or one global mutable database session.

## 3. Persistence design: conceptual schema

Use stable IDs (UUID/ULID or 64-bit surrogate keys; decision pending), and an additional human-facing per-company journal number. IDs must never be reused. Use TEXT/Unicode for account codes; no float types for money.

| Entity | Key fields / relationships | Purpose |
|---|---|---|
| `companies` | id, name, base_currency, timezone, status | Tenant/accounting entity |
| `fiscal_periods` | company_id, from/to, close_state | Posting windows |
| `chart_templates` | id, label, version | Optional starting chart template |
| `accounts` | company_id, code, name, parent_id, active, account_type | Independent company chart |
| `dimensions` / `dimension_values` | company_id, kind, code, name | Counterparties, cost centers, contracts etc. |
| `books` | company_id, code, name, status | Named report/book view (IFRS, Tax, etc.) |
| `layers` | company_id, code, name, status | Posting strata (Common, IFRS adj., Tax adj.) |
| `book_layers` | book_id, layer_id, precedence/order | Defines which postings form a book |
| `journal_entries` | company_id, id, number, date, description, status, layer_id, source_ref, reversal_of, created_at, posted_at | Journal header |
| `journal_lines` | journal_entry_id, company_id, account_id, side, amount_minor/decimal, currency, fx info | At least two lines per posted entry |
| `line_dimensions` | journal_line_id, dimension_value_id | Optional flexible dimensions |
| `audit_events` | company_id, entity_id, actor, action, timestamp, before/after metadata | Append-only audit trail |
| `import_batches` / `import_items` | company_id, source, source_key, checksum, status | Idempotent imports (future) |
| `closing_balances` | company_id, book_id, cutoff, account_id, dimensions, debit/credit/net, version | Optional validated report accelerator (future) |

Additional indexes and uniqueness constraints: unique `(company_id, account_code)`; unique `(company_id, journal_number)` if applicable; indexes on journal `(company_id, status, date, id)`, line `(company_id, account_id, journal_entry_id)`, entries by `(company_id, layer_id, date)`, dimensions by line and value. Choose/validate index order using measured query plans, not by indiscriminately indexing every column.

**Data isolation:** every application read/write has an explicit `company_id`. Join ownership must be verified: account, dimension and layer must belong to the same company as journal. The database should enforce composite foreign keys where practical, while application tests enforce all cases. Do not share raw SQLite file over network drives for simultaneous writers.

### Monetary representation

- Store functional/base amounts in **integer minor units** where scale is fixed (e.g., AZN cents) *or* exact `NUMERIC`/decimal with explicit scale. **Open decision:** monetary policy for currencies with variable decimals and FX valuations. Never binary floating point for postings.
- Keep transaction-currency amount separately from functional-currency amount; store FX rate/source/date and rounding rule needed to reproduce accounting amounts.
- Model `Money` using Python `Decimal`; define precision, quantization and balancing currency by explicit policy. Tax/IFRS rules for FX are outside initial posting engine.
- Amount and direction are separate (positive amount + debit/credit side), or one signed base amount by convention. Adopt **one** representation consistently.

## 4. Journal lifecycle and correctness

States: `draft` -> `posted`; `draft` may be edited/deleted with audit policy; `posted` is immutable in financial meaning. Corrections use reversal and new posting, linked to the original. Every report uses **posted** entries only by default. A reversal is an ordinary balanced journal with `reversal_of` link. Do not physically delete posted rows.

In one atomic transaction: validate active company/period/accounts/layer, at least two lines, every line positive amount, one monetary unit policy, balance base currency debits to credits, ensure referenced dimension ownership, assign journal number, write header+lines+audit event, commit. If any validation fails, rollback entirely.

For concurrency later, use transaction boundaries, unique source keys and retry/idempotency strategy; never use UI-generated sequential numbers as the authoritative ID. Include `created_at`, `posted_at`, and `effective_date` explicitly; consider period locking and authorized adjustments of previously closed periods.

## 5. Accounting layers and report books

**Do not equate layer with book.** A layer is where a posting is recorded; a book is a *view* combining selected layers. This separation makes the architecture extensible.

Initial configuration:

| Layer | Usage |
|---|---|
| `common` | Entries applicable to both bases |
| `ifrs_adj` | IFRS-only adjustments |
| `tax_adj` | Tax-only adjustments / permitted tax ledger entries |

| Book | Layers included |
|---|---|
| `COMMON` | common |
| `IFRS` | common + ifrs_adj |
| `TAX` | common + tax_adj |

Each journal belongs to **exactly one layer**, and is physically stored once. A report for book `IFRS` filters postings by included layer IDs and company/date; it does not copy Common journals. A cross-book comparison can show Common, IFRS adjustments, IFRS total, Tax adjustments, Tax total and variance.

### Handling accounting differences

- **Additive differences:** if the common ledger has no depreciation entry, recognize 200 in `ifrs_adj` and 300 in `tax_adj` (illustrative).
- **Replacement differences:** if Common has 250 depreciation, do not post only 200 in IFRS (that would produce 450). In IFRS adjustment layer reverse the effect of common 250, then post IFRS 200, or use explicit delta -50 if policy permits. Both require audit links and readable report presentation.
- **Non-posting tax adjustments:** e.g. non-deductible costs/tax bases may belong in separate tax registers linked to journal lines, rather than artificial balanced GL entries. Design module contracts for this; not required for MVP.
- **Deferred tax:** computed from temporary differences with traceable supporting register; not simply IFRS minus Tax GL balances.
- **Account mapping:** initially one chart per company shared by books. Distinct charts per book are out of MVP; introduce mapping/versioning if later needed.

**Open decisions:** Must every company have `common` by default? Can a company choose just one book? Can books include exclusion or override rules? **Recommendation v0.1:** no magic exclusions; transparent posted reversing/delta entries only; `book_layers` configuration is explicit, versioned and auditable. Changes to historical book composition require governance because they change report results.

## 6. Reporting architecture

Queries in SQL, formatting in presentation/export. No loading all journal rows into pandas/Python just to compute totals. Initial reports:

1. Journal list, filtered by company, date range, layer/book, account and dimensions.
2. Account card with beginning balance, dated debits/credits, running balance, drill-down to entry.
3. Turnover / trial balance with opening debit/credit, period movements, closing debit/credit, optional per-dimension groupings.
4. IFRS-vs-Tax comparative turnovers by account.

**Correct balance logic:** report opening balances from all posted entries dated before `from_date`, changes from `from_date` through `to_date` inclusive, both respecting book composition, company and dimensions. Debit and credit sign conventions and contra accounts must be specified and tested; an account's normal balance should not silently hide negative balances. Nested account rollups must not double-count parents and children.

SQL should aggregate narrow indexed data; use window functions for running balance where appropriate. Paginate journal/account-card queries via **keyset/cursor pagination** on stable `(date, entry_id, line_id)` ordering rather than huge OFFSET pages. Qt table models fetch 100–500 rows per request (tunable), not all rows. Exports stream/batch records if large.

**Caching:** start without complex balance materialization. Profile first. If needed, add immutable period snapshots/materialized aggregates with an invalidation strategy whenever backdated entries, book configuration or account hierarchy change. Snapshot values are accelerators only; ledger remains source of truth.

## 7. Desktop UI and responsiveness

PySide6 `QTableView` + `QAbstractTableModel`; do not use a widget instance per cell. Optimize for keyboard-centric entry: fast account-code completion, Tab/Enter movement, duplicate last row, keyboard-only new/post, predictive dimensions, reversible undo in drafts, direct drilldown from balances. Use virtualized/paged models, column-width persistence and coherent typography, accessibility and DPI scaling. No modal dialog for each trivial task.

Long-running reports/imports run off the UI thread, and never use Qt widgets from worker threads. Each operation has progress/cancel/errors where practical; database connection/session lifetimes must be thread-safe. UI must not issue raw SQL or house financial calculations. Separate display formatting (AZ/RU/EN locale) from numeric persistence.

## 8. Performance service-level objectives (provisional)

On a documented Windows machine with SSD, warm cache and defined test dataset, target *p95*:

| Scenario | Aspirational objective |
|---|---|
| Save a simple journal entry | <= 100 ms |
| Display first journal page | <= 500 ms |
| Switch company / book | <= 500 ms for visible UI state |
| Annual TB, 1,000,000 journal lines | <= 2 seconds for defined dimensions and indexes |
| Search/cursor page, 10,000,000 lines | Interactive without freezing UI; benchmark target TBD |

These are **acceptance targets, not proven performance**. Distinguish operation counts from journal-line counts, cold from warm cache, and single-account from multidimensional reports. Benchmark at 10k, 100k, 1m, 5m and 10m lines. Record database size, index size, process RAM, query plan, p50/p95 duration and hardware. Check slowest paths before implementing aggregates.

SQLite single-writer limitation is acceptable for local solo use; benchmark bulk import and index maintenance. Set journal mode / transaction pragmas deliberately and document crash/recovery behavior. Plan for PostgreSQL before multiuser deployment, not as a shared SQLite file.

## 9. API readiness and integrations

Application commands/queries are use-case interfaces that can be called by PySide6 today or an HTTP adapter tomorrow. API has versioned DTOs, explicit company/user identity, idempotency key and source reference. Never expose database tables as the external API contract.

Future bank flow: bank connector -> immutable inbound staging records -> dedupe / reconciliation -> proposed entries -> human review / rule engine -> application `PostJournal` -> immutable posted ledger. Bank imports must be repeatable without duplicate postings. Connections, credentials and PII handled in secured infrastructure modules and logs scrubbed. Actual bank API availability is a separate integration prerequisite.

## 10. Migration, backup, security and audit

- Alembic schema migrations with applied version tracking; do not edit production tables ad hoc.
- Backup local SQLite via supported online backup API or app-controlled clean shutdown, not careless file copy during writes. Periodically **restore-test** backups.
- A multi-company desktop user interface still enforces company boundaries; later server architecture requires server-side authorization and potentially database row-level defense.
- Log meaningful changes (creation, posting, reversal, layer/book configuration, period-close events) with actor/time and correlation/source metadata. Audit trail alone is not tamper-proof; backups and permissions matter.
- Encrypt sensitive data at rest or use platform-supported storage if threat model warrants; never hardcode API credentials.
- Pre-release compatibility tests: SQLite vs PostgreSQL for date handling, decimal semantics, foreign keys, collation, isolation and migrations.

## 11. Testing strategy

**Unit:** Decimal rounding, debit/credit balance, entity validation, period closure, book membership, replacement of common postings, date inclusivity, account hierarchy.

**Integration:** transaction rollback on partial entry, SQLite FK enforcement, company isolation, migrations up/down where safe, report queries and accounting reconciliation.

**Golden accounting fixtures:** an explicit sample with Common purchase, IFRS adjustment, Tax adjustment, common replacement/reversal, opening balances and expected per-book trial balances. Reports must reconcile to source journals; total debits = total credits (within base currency policy).

**Performance:** reproducible synthetic data generator with realistic account/date skew and dimensions; automated p95 report and regression alert. UI smoke: 1,000 visible-row navigations, no blocking while reports run.

## 12. First vertical slice (delivery order)

1. Repository scaffolding, lint/type/test commands, architecture checks and `AGENTS.md`.
2. Schema/migrations: companies, accounts, layers, books, book_layers, journals, lines, audit_events.
3. Domain `PostJournal` + `ReverseJournal` with automated accounting fixtures.
4. SQL trial balance for a single book and a two-book comparison; test Common/IFRS/Tax.
5. PySide6 shell, company selector, journal entry and journal browser.
6. ОСВ and account card with drill-down; Excel/CSV export.
7. Synthetic 1m-line benchmark, profile/refine indexes, UI responsiveness test.
8. Import anonymized sample from 1C 7.7; reconcile account-level trial balance and reporting periods.

**Definition of done for first slice:** two isolated companies, user-configurable chart, balanced postings, Common+adjustments, correct IFRS/Tax reports, drilldown, safe persistence/restart, automated tests, no blocking table loads, documented backup/restore and measured performance. No bank APIs or third-party plugin system required yet.

## 13. Decisions requiring explicit confirmation

- Exact 1C 7.7 second chart of accounts template and account hierarchy/source file.
- Chart account mapping and analytical dimensions to include in MVP (counterparty, contract, project, branch etc.).
- Currency precision and FX handling; book-specific functional currency, if any.
- Whether tax reporting is GL-style ledger only or also non-posting tax registers.
- Adjustment policy: full reversal/repost vs posted delta; define transparent report labels.
- Numbering and fiscal period closure policy, handling late backdated postings.
- One SQLite database for all companies vs separate database per company. **Provisional preference:** one database with strict company keys for first prototype; reassess backup/portability requirements.
- Prototype performance hardware and realistic data distribution; confirm targets with benchmarks.

## 14. Architecture decision log

| ADR | Decision | Status |
|---|---|---|
| 001 | Desktop PySide6/Qt first | Proposed |
| 002 | Modular monolith; ports/adapters | Proposed |
| 003 | SQLite single-user, PostgreSQL server later | Proposed |
| 004 | Independent books formed by configured layers | Proposed |
| 005 | Immutable posted journals; explicit reversals | Proposed |
| 006 | SQL reporting + keyset pagination, optional validated aggregates | Proposed |
| 007 | One configurable company chart shared across books in MVP | Proposed |
| 008 | Exact-decimal accounting with documented money policy | Open: storage format |

**Guiding constraint:** Build the smallest complete ledger slice without sacrificing auditability, correctness or future extension points. Prefer measured simplification over speculative frameworks.
