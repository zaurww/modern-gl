# Modern GL — Functional & Non-functional Specification

**Version:** 0.1 (draft)  
**Date:** 2026-10-19  
**Status:** Requirements baseline, not an implementation contract  
**Target:** Local Windows accounting application for one accountant, designed for future multi-user and API deployment.

## 1. Product vision

Build a **fast, visually polished, keyboard-first general ledger** for accounting consultants who post journals manually. Preserve the productive workflows of 1C 7.7 while using Unicode, modern modular architecture and multiple parallel books (e.g. common, IFRS, tax). Start on one Windows computer with one or more companies; make it possible to grow to centralized multi-user use and bank integrations without rewriting the accounting domain.

### Priorities (in order)
1. Accounting integrity and traceable historical data.
2. Fast, reliable keyboard data entry and excellent UI / reporting design.
3. Support for multiple companies and multiple accounting layers.
4. Predictable performance at large data volumes.
5. Modularity, testability, extensibility and controlled upgrades.

## 2. Scope and boundaries

### MVP / initial prototype
- Windows desktop application (PySide6/Qt), single user, local SQLite storage.
- Create, switch between and configure independent companies.
- Importable/editable chart of accounts. One selectable chart-of-accounts template may be the user's familiar *second chart of accounts* from 1C 7.7 **after obtaining the actual template**; support custom charts. Do not assume the account codes or names.
- Keyboard-focused journal entry: transaction date, posting date (if needed), description, debit/credit account(s), amount, currency, layer, optional analytics; ability to edit drafts, duplicate entries and search accounts.
- Double-entry general ledger; immutable audit trail for posted entries, controlled reversal and correction.
- Layers `common`, `ifrs`, `tax` with user-selected book/report views. General framework should not hardcode a maximum number of layers.
- Trial balance / turnover-saldo (ОСВ), account card, journal and drill-down to originating transactions.
- Basic import/export: CSV and Excel; PDF report rendering is optional for MVP if it delays correctness.
- Persistent user settings for table layouts and shortcuts; Unicode AZ/RU/EN content.
- Tests for posting invariants, books, reports, isolation and performance.

### Explicitly outside MVP
- Payroll, inventory movements, depreciation engine, e-invoicing, tax filing, statutory document workflows, bank API connectivity, external user accounts, automatic AI posting, cloud sync, mobile apps.
- General-purpose third-party plugin marketplace and microservices.

These features may be added later behind stable application interfaces.

## 3. Accounting domain model

**Core entities:**
- `Company`: legal entity, base/functional currency, fiscal calendar, settings.
- `Account`: company-specific code stored as *text*, name, hierarchy, active flag, allowable posting / analytics rules.
- `JournalEntry`: id, company, date, period, number, memo, status (`draft`, `posted`, `reversed`), layer, creator / timestamps, source identifier, correction reference.
- `JournalLine`: entry id, line number, account id, debit or credit amount in functional currency using exact decimal types, transaction currency and amounts/rate when applicable, analytic dimensions.
- `Layer`: stable identifier, name, configuration; `common` base layer and optional overlays.
- `Counterparty` and other dimension definitions/values (initial scope to be constrained).
- `FiscalPeriod`, `AuditEvent`, `SourceAttachmentReference` (attachment storage is optional initially).

### Domain rules (must hold transactionally)
1. Each posted entry has at least two lines; total debit equals total credit **per company and functional currency** using exact decimal arithmetic and defined currency rounding policy.
2. All journal lines use accounts and analytics belonging to the entry's company. Transactions cannot cross company boundaries.
3. Drafts may be edited; posted entries cannot be silently mutated or hard-deleted. Correct via reversal / new linked entry; all actions are auditable.
4. A closed period blocks postings and corrections unless specifically reopened through an authorized workflow.
5. Date / entry numbering rules must be deterministic and testable; duplicate external references handled explicitly.
6. Monetary values never use binary floating-point; FX rates and local/foreign currency amounts require explicit rounding policy and auditability.
7. Every accounting query must explicitly scope by company, status, date/period and requested reporting book.

## 4. Multi-layer accounting — critical MVP design

### Intended semantics (proposed; confirm with examples before coding)
- The base layer `common` stores transactions shared across books.
- Overlay layers `ifrs` and `tax` store additive adjustment journals only.
- IFRS view = posted `common` + posted `ifrs`.
- Tax view = posted `common` + posted `tax`.
- Common-only view = posted `common`.
- Comparative report = common, IFRS adjustments, IFRS final, tax adjustments, tax final (depending on chosen accounts and mappings).
- A posted Common journal that should not apply to one book is neutralized by an **explicit reversing/offsetting adjustment within that overlay**, preserving a traceable chain; never invisibly exclude data.
- Some tax-only items (e.g. permanent/timing differences not appropriately expressed as GL postings) may require a future **tax register** separate from ledger. Do not pretend all tax concepts map to journal entries.
- Different accounting bases might eventually need different chart mappings; MVP uses **one chart per company**, with a future mapping interface if required.

### Example (illustrative, account codes not authoritative)
Equipment acquired: Common Dr PPE 12,000 / Cr Payables 12,000. IFRS-only monthly depreciation 200; Tax-only monthly depreciation 300. Resulting respective net book values depend on the postings included in each book.

### Open questions requiring explicit design decisions
- Are layer postings *exclusive* to one overlay, or should layers support inheritance and arbitrary combinations beyond Common+one overlay?
- Will historic Common postings ever be replaced by overlay-specific classifications? The proposed mechanism is explicit adjustments.
- Are balances needed at layer level even if a specific layer is not independently balanced? Proposed rule: each individual overlay journal is balanced.
- Tax book reporting: actual GL balances vs tax reconciliation register?
- How should accounts and analytic dimensions map into BS/P&L for different reporting bases?

Do not implement layer calculation until concrete examples and acceptance tests are approved.

## 5. UI and UX requirements

**Design direction:** professional, compact, high-information-density desktop app; clean typographic hierarchy, consistent spacing, alignment, numeric formatting and dark/light theme possibility. The application must prioritize frequent tasks over decorative dashboards.

**Journal entry workflow:**
- Keyboard-first end-to-end navigation (Tab, Shift+Tab, Enter, Escape and configurable shortcuts).
- Fast account selection by account code or fuzzy name; no modal popup for routine actions if avoidable.
- Duplicate prior entry; rapid repetitive entry; optional templates later.
- Clearly visible company, date and layer to prevent cross-book errors.
- Immediate validation before saving, without blocking UI or losing entered data.
- Search/filter/sort of journal with persistent preferences.

**Reports:**
- OSV/trial balance with opening balance, debit/credit movements, closing balance; reporting period, company, layer selector; totals and optional hierarchical grouping by account.
- Direct drill-down from any balance/movement to account card and source journal.
- Consistent columns, aligned decimals, customizable widths and clear print/export output.
- Export should preserve values and sorting/filter context where feasible.

**UI engineering:** use Qt model/view (e.g. QTableView with a proper data model), virtualized/paginated loading; do not create a widget object per ledger cell. Long-running queries operate outside the UI thread with cancellation/status feedback.

## 6. Target architecture

**Modular monolith** rather than microservices. Suggested modules: `companies`, `chart_of_accounts`, `ledger`, `layers`, `currencies`, `dimensions`, `reporting`, `import_export`, `persistence`, `desktop`.

**Technology baseline (proposed):** Python, PySide6/Qt, SQLAlchemy, Alembic, SQLite for single-user local prototype, pytest. PostgreSQL through a **server/API boundary** for later simultaneous multi-user access. Never share the SQLite `.db` file for concurrent edits over a network share.

**Architecture constraints:**
- UI calls application/use-case services; UI has no posting/calculation SQL.
- Ledger domain rules do not depend on PySide6, SQLite or import file formats.
- Reporting reads from a defined read model/query layer, not screen-specific aggregations.
- Modules have explicit contracts; no direct use of other modules' internal persistence tables without an agreed interface.
- API integration is an adapter: external data arrives into a staging/reconciliation workflow and cannot directly mutate posted journals.
- Account and company IDs are stable; business codes are attributes and may change under controlled policies.
- Schema changes via versioned migrations, including tested upgrade/backup/recovery.
- Backwards compatibility and deliberate versioning for application interfaces.
- Avoid premature plugin frameworks and complex abstractions until demanded by concrete use cases.

### Illustrative directory layout
```text
modern-gl/
  src/modern_gl/
    domain/
      ledger/
      layers/
      companies/
      accounts/
    application/
    infrastructure/
      persistence/
      imports/
    ui/desktop/
    reporting/
  tests/
    unit/
    integration/
    performance/
  migrations/
  docs/
  pyproject.toml
```
The final layout may change, provided architectural boundaries remain clear.

## 7. Performance & scalability

### Test workload assumptions (not guarantees)
- Milestones: 10k, 100k, 1M, 5M journal **lines**, stretch test 10M; record transactions and lines separately.
- Single-user Windows PC, SSD, warm vs cold cache explicitly noted; representative account distribution, date range, layers and analytics.
- Compare at least one company with multiple companies; test large journals, high-cardinality counterparties and reporting period filters.

### Initial performance objectives (provisional, subject to benchmarking)
| Operation | Goal under stated workload |
|---|---|
| Save a simple balanced entry | p95 <= 100 ms under representative local workload |
| Open first page of journal | p95 <= 500 ms |
| Switch company / book view | p95 <= 500 ms for visible screen transition excluding long background recomputation |
| OSV for a year across 1M journal lines | target <= 2 s on agreed reference PC/query set |
| Scroll journal | UI remains responsive, no full-table preloading |

These are **design targets, not measured results**. Some may need revision after the first benchmark, particularly complex multi-dimensional OSV.

### Required technical controls
1. Use keyset pagination or database-backed row-window loading for large journals; avoid fetching all rows into Python for the UI.
2. Use `GROUP BY` / optimized database queries for report calculations rather than loading the entire ledger into pandas.
3. Create indexes based on actual query plans (commonly company, posting status, date, account, layer); measure write overhead of excessive indexes.
4. Never duplicate Common journal rows for IFRS and Tax views.
5. Only if profiling shows a need, add period balance snapshots / materialized aggregates, with transaction-safe invalidation and rebuild when history is corrected.
6. Use background workers for imports and large reports; UI stays responsive.
7. Automate benchmarks and detect regressions alongside correctness tests.
8. Keep data retention, backup, recovery and database maintenance procedures documented.

### Benchmark acceptance method
- Generate deterministic synthetic journal data (10k → 100k → 1M → 5M lines), all entries balanced, using multiple companies/layers/currencies and realistic account distribution.
- Verify numerical correctness of OSV against independent reference calculations on small and sampled large datasets.
- Record PC specifications, dataset size, DB size, indexes, query plans, cold/warm runs, median/p95 timing and UI responsiveness.
- Benchmark journal entry, first page, filters, drill-down, OSV, layer comparisons, export, backup and restore.
- Optimization must not alter calculated balances or audit history.

## 8. Security, reliability, upgradeability
- Single-user does not mean no audit: maintain author/time/source metadata and reliable posting history from v0.1.
- Backups with integrity checks; explicit user-managed or scheduled backup workflow before real client use.
- Atomic write transactions; robust crash recovery; periodic SQLite integrity checks.
- Protect confidentiality and avoid embedding real client data into development logs, fixtures or AI prompts.
- Confirm regulatory retention, data privacy and audit requirements before production use.
- Never mark the MVP ready for client accounting until accounting correctness, backup/restore and import reconciliation have been tested.

## 9. Development slices & acceptance

**Slice 0 — repo foundations**: project setup, CI/tests, linting, environment, package reproducibility, architectural conventions.

**Slice 1 — balanced entry**: one company, configurable minimal chart, create/draft/post/reverse entry, SQLite persistence, audit record, keyboard entry form. **Acceptance:** posted entries survive restart and all invalid/unbalanced entries are rejected atomically.

**Slice 2 — accounts & OSV**: account card, trial balance, drill-down, deterministic reports. **Acceptance:** opening + turnover = closing by account, total debits/credits reconcile, source drill-down correct.

**Slice 3 — Common/IFRS/Tax**: configurable layer assignment, per-book reports and comparison. **Acceptance:** `Common+IFRS` and `Common+Tax` results exactly match independent fixtures; adjustments do not modify Common history.

**Slice 4 — multi-company and speed**: second company, hard isolation, compact table workflows, paginated journal, performance benchmark. **Acceptance:** no leak between companies and documented performance measurements.

**Slice 5 — reliability / pilot**: import anonymized sample or selected trial entries from 1C, reconcile balances and currency amounts, backups/restore, upgrade migration tests. **Acceptance:** signed-off reconciliation for agreed periods and books.

## 10. Decisions recorded / decisions pending

### Agreed user requirements
- Begin locally on user's Windows PC for one and then multiple companies.
- Excellent app/report design and exceptionally fast manual posting workflow.
- Option for the familiar 1C second chart of accounts and customizable chart.
- Optional parallel IFRS and tax layers with Common shared entries.
- Long-term modularity, extensibility, API-readiness and efficient handling of substantial datasets.

### Proposed engineering decisions (reviewable)
- PySide6/Qt + Python + SQLite + SQLAlchemy/Alembic.
- Modular monolith / domain-core separation.
- One chart per company for initial version; balanced overlay adjustments.
- Server/API + PostgreSQL if simultaneous multi-user write access becomes necessary.

### Not yet decided
- Exact 1C chart-of-accounts template to import.
- Functional currency and exchange rate sources / date policy.
- Exact analytic dimensions needed at launch (counterparty, contract, cost center, site, etc.).
- How to represent tax reconciliations not appropriately modeled as GL entries.
- Expected volume and target hardware specifications.
- Report formatting, dark/light design direction and detailed shortcuts.

## 11. Immediate next action

Before writing substantial code, approve **three worked examples** that include Common, IFRS-only, Tax-only and reversing/adjusting entries; then build **Slice 1** as an executable desktop proof of concept with real SQLite persistence and automated tests. Profile it early and capture the baseline in `docs/benchmarks.md`.
