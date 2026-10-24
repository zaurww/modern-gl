-- Every reference stays inside the company, every reference is a FOREIGN KEY, every date
-- has its format checked (docs/ENGINEERING.md 3.2, 3.4, 3.5; debts 4, 7, 8; session 49).
--
-- SQLite changes a constraint only by rebuilding the table (new table, copy, drop, rename):
-- the rows, ids and column order stay as they were; the indexes and the triggers of a
-- rebuilt table are made again below. Foreign keys are off while this runs (db.migrate)
-- and the references are checked before it commits.
--
--   debt 4: postings.currency_id, subconto_kinds.owner_kind_id, subconto_values.parent_id /
--     owner_id / currency_id, inventory_documents.accrual_document_id → composite FKs
--     (company_id, x); the triggers of 0008/0009/0027 that stood in for them go away.
--   debt 7: inventory_documents.currency_id, landed_cost_charges.currency_id (0013),
--     inventory_lines.cost_sc1..3 (0023) get their FOREIGN KEY.
--   debt 8: dates of bank_statements, bank_portal_loads, bank_portal_reconciled,
--     eqaime_portal, eqaime_portal_changes, eqaime_reconciled, stock_movements and
--     companies.closed_through get CHECK (… GLOB 'YYYY-MM-DD').
PRAGMA legacy_alter_table = ON;

-- companies: closed_through is a date -------------------------------------------------
CREATE TABLE companies_new (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT NOT NULL,
    base_currency         TEXT NOT NULL DEFAULT 'AZN',
    closed_through        TEXT  -- documents dated on or before it cannot be posted
        CHECK (closed_through IS NULL
               OR closed_through GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    created_at            TEXT NOT NULL,
    last_number           INTEGER NOT NULL DEFAULT 0,
    last_inventory_number INTEGER NOT NULL DEFAULT 0,
    parallel_books        INTEGER NOT NULL DEFAULT 0 CHECK (parallel_books IN (0, 1)),
    mode                  TEXT NOT NULL DEFAULT 'full' CHECK (mode IN ('full', 'stock')),
    tax_id                TEXT
        CHECK (tax_id IS NULL OR (length(tax_id) = 10 AND tax_id NOT GLOB '*[^0-9]*'))
);
INSERT INTO companies_new (id, name, base_currency, closed_through, created_at, last_number,
                           last_inventory_number, parallel_books, mode, tax_id)
SELECT id, name, base_currency, closed_through, created_at, last_number,
       last_inventory_number, parallel_books, mode, tax_id
FROM companies;
DROP TABLE companies;
ALTER TABLE companies_new RENAME TO companies;

-- subconto_kinds: the owner directory is of the same company ---------------------------
CREATE TABLE subconto_kinds_new (
    id            INTEGER PRIMARY KEY,
    company_id    INTEGER NOT NULL REFERENCES companies(id),
    code          TEXT NOT NULL,
    name          TEXT NOT NULL,
    owner_kind_id INTEGER,
    FOREIGN KEY (company_id, owner_kind_id) REFERENCES subconto_kinds(company_id, id),
    UNIQUE (company_id, code),
    UNIQUE (company_id, id)
);
INSERT INTO subconto_kinds_new (id, company_id, code, name, owner_kind_id)
SELECT id, company_id, code, name, owner_kind_id FROM subconto_kinds;
DROP TABLE subconto_kinds;
ALTER TABLE subconto_kinds_new RENAME TO subconto_kinds;

-- subconto_values: currency, owner and parent are of the same company ------------------
CREATE TABLE subconto_values_new (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL,
    kind_id     INTEGER NOT NULL,
    code        TEXT,
    name        TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    currency_id INTEGER,
    owner_id    INTEGER,
    nonresident INTEGER NOT NULL DEFAULT 0 CHECK (nonresident IN (0, 1)),
    tax_id      TEXT CHECK (tax_id IS NULL OR TRIM(tax_id) <> ''),
    country     TEXT CHECK (country IS NULL OR TRIM(country) <> ''),
    legal_name  TEXT CHECK (legal_name IS NULL OR TRIM(legal_name) <> ''),
    parent_id   INTEGER,
    is_group    INTEGER NOT NULL DEFAULT 0 CHECK (is_group IN (0, 1)),
    FOREIGN KEY (company_id, kind_id)     REFERENCES subconto_kinds(company_id, id),
    FOREIGN KEY (company_id, currency_id) REFERENCES currencies(company_id, id),
    FOREIGN KEY (company_id, owner_id)    REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, parent_id)   REFERENCES subconto_values(company_id, id),
    UNIQUE (kind_id, code),
    UNIQUE (company_id, id)
);
INSERT INTO subconto_values_new (id, company_id, kind_id, code, name, active, currency_id,
                                 owner_id, nonresident, tax_id, country, legal_name,
                                 parent_id, is_group)
SELECT id, company_id, kind_id, code, name, active, currency_id, owner_id, nonresident,
       tax_id, country, legal_name, parent_id, is_group
FROM subconto_values;
DROP TABLE subconto_values;
ALTER TABLE subconto_values_new RENAME TO subconto_values;
CREATE INDEX subconto_values_parent ON subconto_values (company_id, parent_id);
CREATE INDEX subconto_values_owner  ON subconto_values (company_id, owner_id);
CREATE INDEX subconto_values_tax_id ON subconto_values (company_id, tax_id);

-- postings: the currency is of the same company ----------------------------------------
CREATE TABLE postings_new (
    id                INTEGER PRIMARY KEY,
    company_id        INTEGER NOT NULL,
    document_id       INTEGER NOT NULL,
    line_no           INTEGER NOT NULL,
    debit_account_id  INTEGER NOT NULL,
    credit_account_id INTEGER NOT NULL,
    amount            INTEGER NOT NULL CHECK (amount <> 0),
    dt_sc1 INTEGER, dt_sc2 INTEGER, dt_sc3 INTEGER,
    ct_sc1 INTEGER, ct_sc2 INTEGER, ct_sc3 INTEGER,
    memo              TEXT NOT NULL DEFAULT '',
    currency_id       INTEGER,
    currency_amount   INTEGER CHECK ((currency_id IS NULL) = (currency_amount IS NULL)),
    invoice           TEXT
        CHECK (invoice IS NULL OR (TRIM(invoice) <> '' AND invoice = upper(invoice))),
    invoice_kind      TEXT
        CHECK (invoice_kind IS NULL OR (invoice_kind = 'customs' AND invoice IS NOT NULL)),
    FOREIGN KEY (company_id, document_id) REFERENCES documents(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, debit_account_id)  REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, credit_account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, dt_sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, dt_sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, dt_sc3) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, ct_sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, ct_sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, ct_sc3) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, currency_id) REFERENCES currencies(company_id, id),
    UNIQUE (document_id, line_no)
);
INSERT INTO postings_new (id, company_id, document_id, line_no, debit_account_id,
                          credit_account_id, amount, dt_sc1, dt_sc2, dt_sc3, ct_sc1, ct_sc2,
                          ct_sc3, memo, currency_id, currency_amount, invoice, invoice_kind)
SELECT id, company_id, document_id, line_no, debit_account_id, credit_account_id, amount,
       dt_sc1, dt_sc2, dt_sc3, ct_sc1, ct_sc2, ct_sc3, memo, currency_id, currency_amount,
       invoice, invoice_kind
FROM postings;
DROP TABLE postings;
ALTER TABLE postings_new RENAME TO postings;
CREATE INDEX postings_by_debit   ON postings (company_id, debit_account_id);
CREATE INDEX postings_by_credit  ON postings (company_id, credit_account_id);
CREATE INDEX postings_by_invoice ON postings (company_id, invoice) WHERE invoice IS NOT NULL;
CREATE TRIGGER postings_posted_no_insert BEFORE INSERT ON postings
WHEN (SELECT status FROM documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted document is immutable'); END;
CREATE TRIGGER postings_posted_no_update BEFORE UPDATE ON postings
WHEN (SELECT status FROM documents WHERE id = OLD.document_id) = 'posted'
  OR (SELECT status FROM documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted document is immutable'); END;
CREATE TRIGGER postings_posted_no_delete BEFORE DELETE ON postings
WHEN (SELECT status FROM documents WHERE id = OLD.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted document is immutable'); END;

-- inventory_documents: accrual document and currency are of the same company ----------
CREATE TABLE inventory_documents_new (
    id                  INTEGER PRIMARY KEY,
    company_id          INTEGER NOT NULL REFERENCES companies(id),
    number              INTEGER NOT NULL,
    doc_date            TEXT NOT NULL
        CHECK (doc_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    doc_type            TEXT NOT NULL CHECK (
        doc_type IN (
            'opening', 'receipt', 'incoming', 'issue', 'transfer', 'landed_cost', 'sale'
        )
    ),
    memo                TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL CHECK (status IN ('draft', 'posted')),
    landed_cost_type_id INTEGER,
    gl_document_id      INTEGER,
    created_at          TEXT NOT NULL,
    posted_at           TEXT,
    vat_rate            INTEGER CHECK (vat_rate IS NULL OR vat_rate BETWEEN 0 AND 10000),
    allocation_method   TEXT
        CHECK (allocation_method IS NULL OR allocation_method IN ('value', 'quantity', 'manual')),
    currency_id         INTEGER,
    currency_rate       INTEGER CHECK (currency_rate IS NULL OR currency_rate > 0),
    invoice             TEXT
        CHECK (invoice IS NULL OR (TRIM(invoice) <> '' AND invoice = upper(invoice))),
    invoice_kind        TEXT
        CHECK (invoice_kind IS NULL OR (invoice_kind = 'customs' AND invoice IS NOT NULL)),
    expense_date        TEXT
        CHECK (expense_date IS NULL OR expense_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    accrual_document_id INTEGER,
    incoming_reason     TEXT CHECK (
        incoming_reason IS NULL
        OR incoming_reason IN ('surplus', 'contribution', 'production', 'gift')
    ),
    awaits_invoice      INTEGER NOT NULL DEFAULT 0
        CHECK (awaits_invoice IN (0, 1)
               AND (awaits_invoice = 0 OR (doc_type = 'receipt' AND invoice IS NULL))),
    CHECK ((doc_type = 'incoming') = (incoming_reason IS NOT NULL)),
    FOREIGN KEY (company_id, gl_document_id) REFERENCES documents(company_id, id),
    FOREIGN KEY (company_id, accrual_document_id) REFERENCES documents(company_id, id),
    FOREIGN KEY (company_id, landed_cost_type_id)
        REFERENCES landed_cost_types(company_id, id),
    FOREIGN KEY (company_id, currency_id) REFERENCES currencies(company_id, id),
    UNIQUE (company_id, number),
    UNIQUE (company_id, id),
    UNIQUE (gl_document_id)
);
INSERT INTO inventory_documents_new (id, company_id, number, doc_date, doc_type, memo, status,
                                     landed_cost_type_id, gl_document_id, created_at, posted_at,
                                     vat_rate, allocation_method, currency_id, currency_rate,
                                     invoice, invoice_kind, expense_date, accrual_document_id,
                                     incoming_reason, awaits_invoice)
SELECT id, company_id, number, doc_date, doc_type, memo, status, landed_cost_type_id,
       gl_document_id, created_at, posted_at, vat_rate, allocation_method, currency_id,
       currency_rate, invoice, invoice_kind, expense_date, accrual_document_id,
       incoming_reason, awaits_invoice
FROM inventory_documents;
DROP TABLE inventory_documents;
ALTER TABLE inventory_documents_new RENAME TO inventory_documents;
CREATE INDEX inventory_documents_by_company_date
    ON inventory_documents (company_id, status, doc_date, id);
CREATE UNIQUE INDEX inventory_documents_by_accrual
    ON inventory_documents (accrual_document_id) WHERE accrual_document_id IS NOT NULL;
CREATE INDEX inventory_documents_awaiting
    ON inventory_documents (company_id, awaits_invoice, doc_date);
CREATE TRIGGER inventory_documents_posted_no_update BEFORE UPDATE ON inventory_documents
WHEN OLD.status = 'posted' AND NOT (
        NEW.status = 'draft'
    AND NEW.company_id = OLD.company_id
    AND NEW.number = OLD.number
    AND NEW.doc_date = OLD.doc_date
    AND NEW.doc_type = OLD.doc_type
    AND NEW.memo = OLD.memo
    AND NEW.landed_cost_type_id IS OLD.landed_cost_type_id
    AND NEW.gl_document_id IS OLD.gl_document_id
    AND NEW.created_at = OLD.created_at
    AND NEW.vat_rate IS OLD.vat_rate
    AND NEW.allocation_method IS OLD.allocation_method
    AND NEW.currency_id IS OLD.currency_id
    AND NEW.currency_rate IS OLD.currency_rate
    AND NEW.invoice IS OLD.invoice
    AND NEW.invoice_kind IS OLD.invoice_kind
    AND NEW.incoming_reason IS OLD.incoming_reason
)
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER inventory_documents_posted_no_delete BEFORE DELETE ON inventory_documents
WHEN OLD.status = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document cannot be deleted'); END;

-- inventory_lines: the subconto of the cost side are references too --------------------
CREATE TABLE inventory_lines_new (
    id                     INTEGER PRIMARY KEY,
    company_id             INTEGER NOT NULL,
    document_id            INTEGER NOT NULL,
    line_no                INTEGER NOT NULL,
    item_id                INTEGER,  -- NULL: a service line of a sale
    warehouse_id           INTEGER,
    to_warehouse_id        INTEGER,
    quantity               INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    amount                 INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),
    inventory_amount       INTEGER NOT NULL DEFAULT 0 CHECK (inventory_amount >= 0),
    expense_amount         INTEGER NOT NULL DEFAULT 0 CHECK (expense_amount >= 0),
    offset_account_id      INTEGER,
    offset_sc1             INTEGER,
    offset_sc2             INTEGER,
    offset_sc3             INTEGER,
    source_receipt_line_id INTEGER,
    memo                   TEXT NOT NULL DEFAULT '',
    vat_amount             INTEGER NOT NULL DEFAULT 0 CHECK (vat_amount >= 0),
    currency_amount        INTEGER CHECK (currency_amount IS NULL OR currency_amount >= 0),
    cost_account_id        INTEGER,
    cost_sc1               INTEGER,
    cost_sc2               INTEGER,
    cost_sc3               INTEGER,
    FOREIGN KEY (company_id, document_id)
        REFERENCES inventory_documents(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, item_id) REFERENCES inventory_items(company_id, id),
    FOREIGN KEY (company_id, warehouse_id) REFERENCES warehouses(company_id, id),
    FOREIGN KEY (company_id, to_warehouse_id) REFERENCES warehouses(company_id, id),
    FOREIGN KEY (company_id, offset_account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, offset_sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, offset_sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, offset_sc3) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, source_receipt_line_id)
        REFERENCES inventory_lines(company_id, id),
    FOREIGN KEY (company_id, cost_account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, cost_sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, cost_sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, cost_sc3) REFERENCES subconto_values(company_id, id),
    UNIQUE (document_id, line_no),
    UNIQUE (company_id, id)
);
INSERT INTO inventory_lines_new (id, company_id, document_id, line_no, item_id, warehouse_id,
                                 to_warehouse_id, quantity, amount, inventory_amount,
                                 expense_amount, offset_account_id, offset_sc1, offset_sc2,
                                 offset_sc3, source_receipt_line_id, memo, vat_amount,
                                 currency_amount, cost_account_id, cost_sc1, cost_sc2, cost_sc3)
SELECT id, company_id, document_id, line_no, item_id, warehouse_id, to_warehouse_id, quantity,
       amount, inventory_amount, expense_amount, offset_account_id, offset_sc1, offset_sc2,
       offset_sc3, source_receipt_line_id, memo, vat_amount, currency_amount, cost_account_id,
       cost_sc1, cost_sc2, cost_sc3
FROM inventory_lines;
DROP TABLE inventory_lines;
ALTER TABLE inventory_lines_new RENAME TO inventory_lines;
CREATE INDEX inventory_lines_by_item ON inventory_lines (company_id, item_id);
CREATE TRIGGER inventory_lines_posted_no_insert BEFORE INSERT ON inventory_lines
WHEN (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER inventory_lines_posted_no_update BEFORE UPDATE ON inventory_lines
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
  OR (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER inventory_lines_posted_no_delete BEFORE DELETE ON inventory_lines
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;

-- landed_cost_charges: the currency is a reference -------------------------------------
CREATE TABLE landed_cost_charges_new (
    id                 INTEGER PRIMARY KEY,
    company_id         INTEGER NOT NULL,
    document_id        INTEGER NOT NULL,
    line_no            INTEGER NOT NULL,
    cost_type_id       INTEGER,
    account_id         INTEGER,
    sc1                INTEGER,
    sc2                INTEGER,
    sc3                INTEGER,
    amount             INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),
    vat_amount         INTEGER NOT NULL DEFAULT 0 CHECK (vat_amount >= 0),
    source_document_id INTEGER,
    source_line_no     INTEGER,
    memo               TEXT NOT NULL DEFAULT '',
    currency_id        INTEGER,
    currency_rate      INTEGER CHECK (currency_rate IS NULL OR currency_rate > 0),
    currency_amount    INTEGER CHECK (currency_amount IS NULL OR currency_amount >= 0),
    CHECK ((source_document_id IS NULL) = (source_line_no IS NULL)),
    FOREIGN KEY (company_id, document_id)
        REFERENCES inventory_documents(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, cost_type_id) REFERENCES landed_cost_types(company_id, id),
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, sc3) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, source_document_id) REFERENCES documents(company_id, id),
    FOREIGN KEY (company_id, currency_id) REFERENCES currencies(company_id, id),
    UNIQUE (document_id, line_no),
    UNIQUE (company_id, id)
);
INSERT INTO landed_cost_charges_new (id, company_id, document_id, line_no, cost_type_id,
                                     account_id, sc1, sc2, sc3, amount, vat_amount,
                                     source_document_id, source_line_no, memo, currency_id,
                                     currency_rate, currency_amount)
SELECT id, company_id, document_id, line_no, cost_type_id, account_id, sc1, sc2, sc3, amount,
       vat_amount, source_document_id, source_line_no, memo, currency_id, currency_rate,
       currency_amount
FROM landed_cost_charges;
DROP TABLE landed_cost_charges;
ALTER TABLE landed_cost_charges_new RENAME TO landed_cost_charges;
CREATE INDEX landed_cost_charges_by_source
    ON landed_cost_charges (company_id, source_document_id, source_line_no);
CREATE TRIGGER landed_cost_charges_posted_no_insert BEFORE INSERT ON landed_cost_charges
WHEN (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER landed_cost_charges_posted_no_update BEFORE UPDATE ON landed_cost_charges
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
  OR (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER landed_cost_charges_posted_no_delete BEFORE DELETE ON landed_cost_charges
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;

-- stock_movements: doc_date is a date -------------------------------------------------
CREATE TABLE stock_movements_new (
    id            INTEGER PRIMARY KEY,
    company_id    INTEGER NOT NULL,
    document_id   INTEGER NOT NULL,
    line_id       INTEGER NOT NULL,
    doc_date      TEXT NOT NULL
        CHECK (doc_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    item_id       INTEGER NOT NULL,
    warehouse_id  INTEGER NOT NULL,
    movement_type TEXT NOT NULL CHECK (
        movement_type IN (
            'opening', 'receipt', 'issue', 'transfer_out', 'transfer_in', 'landed_cost'
        )
    ),
    quantity      INTEGER NOT NULL,
    amount        INTEGER NOT NULL,
    CHECK (quantity <> 0 OR amount <> 0),
    FOREIGN KEY (company_id, document_id)
        REFERENCES inventory_documents(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, line_id)
        REFERENCES inventory_lines(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, item_id) REFERENCES inventory_items(company_id, id),
    FOREIGN KEY (company_id, warehouse_id) REFERENCES warehouses(company_id, id)
);
INSERT INTO stock_movements_new (id, company_id, document_id, line_id, doc_date, item_id,
                                 warehouse_id, movement_type, quantity, amount)
SELECT id, company_id, document_id, line_id, doc_date, item_id, warehouse_id, movement_type,
       quantity, amount
FROM stock_movements;
DROP TABLE stock_movements;
ALTER TABLE stock_movements_new RENAME TO stock_movements;
CREATE INDEX stock_movements_by_balance
    ON stock_movements (company_id, item_id, warehouse_id, doc_date, id);
CREATE INDEX stock_movements_by_document ON stock_movements (document_id);
CREATE INDEX stock_movements_line ON stock_movements (company_id, line_id);
CREATE TRIGGER stock_movements_posted_no_insert BEFORE INSERT ON stock_movements
WHEN (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER stock_movements_posted_no_update BEFORE UPDATE ON stock_movements
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
  OR (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER stock_movements_posted_no_delete BEFORE DELETE ON stock_movements
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;

-- bank: the periods of statements, portal loads and reconciliations are dates ---------
CREATE TABLE bank_statements_new (
    id           INTEGER PRIMARY KEY,
    company_id   INTEGER NOT NULL REFERENCES companies(id),
    account_id   INTEGER NOT NULL,
    value_id     INTEGER,
    date_from    TEXT NOT NULL CHECK (date_from GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    date_to      TEXT NOT NULL CHECK (date_to GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    bank_closing INTEGER,  -- minor units of the place's currency
    source       TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'file', 'api')),
    CHECK (date_to >= date_from),
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, value_id) REFERENCES subconto_values(company_id, id),
    UNIQUE (company_id, id)
);
INSERT INTO bank_statements_new (id, company_id, account_id, value_id, date_from, date_to,
                                 bank_closing, source)
SELECT id, company_id, account_id, value_id, date_from, date_to, bank_closing, source
FROM bank_statements;
DROP TABLE bank_statements;
ALTER TABLE bank_statements_new RENAME TO bank_statements;
CREATE INDEX bank_statements_place
    ON bank_statements (company_id, account_id, value_id, date_from);
CREATE INDEX bank_statements_value ON bank_statements (company_id, value_id);

CREATE TABLE bank_portal_loads_new (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    account_id INTEGER NOT NULL,
    value_id   INTEGER,
    date_from  TEXT NOT NULL CHECK (date_from GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    date_to    TEXT NOT NULL CHECK (date_to GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    loaded_at  TEXT NOT NULL,
    operations INTEGER NOT NULL DEFAULT 0 CHECK (operations >= 0),  -- the portal's, done
    CHECK (date_to >= date_from),
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, value_id) REFERENCES subconto_values(company_id, id),
    UNIQUE (company_id, id)
);
INSERT INTO bank_portal_loads_new (id, company_id, account_id, value_id, date_from, date_to,
                                   loaded_at, operations)
SELECT id, company_id, account_id, value_id, date_from, date_to, loaded_at, operations
FROM bank_portal_loads;
DROP TABLE bank_portal_loads;
ALTER TABLE bank_portal_loads_new RENAME TO bank_portal_loads;
CREATE INDEX bank_portal_loads_place
    ON bank_portal_loads (company_id, account_id, value_id, date_from);
CREATE INDEX bank_portal_loads_value ON bank_portal_loads (company_id, value_id);

CREATE TABLE bank_portal_reconciled_new (
    id             INTEGER PRIMARY KEY,
    company_id     INTEGER NOT NULL REFERENCES companies(id),
    account_id     INTEGER NOT NULL,
    value_id       INTEGER,
    date_from      TEXT NOT NULL CHECK (date_from GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    date_to        TEXT NOT NULL CHECK (date_to GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    reconciled_at  TEXT NOT NULL,
    portal_opening INTEGER NOT NULL,
    portal_in      INTEGER NOT NULL CHECK (portal_in >= 0),
    portal_out     INTEGER NOT NULL CHECK (portal_out >= 0),
    books_opening  INTEGER NOT NULL,
    books_in       INTEGER NOT NULL CHECK (books_in >= 0),
    books_out      INTEGER NOT NULL CHECK (books_out >= 0),
    CHECK (date_to >= date_from),
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, value_id) REFERENCES subconto_values(company_id, id),
    UNIQUE (company_id, id)
);
INSERT INTO bank_portal_reconciled_new (id, company_id, account_id, value_id, date_from,
                                        date_to, reconciled_at, portal_opening, portal_in,
                                        portal_out, books_opening, books_in, books_out)
SELECT id, company_id, account_id, value_id, date_from, date_to, reconciled_at,
       portal_opening, portal_in, portal_out, books_opening, books_in, books_out
FROM bank_portal_reconciled;
DROP TABLE bank_portal_reconciled;
ALTER TABLE bank_portal_reconciled_new RENAME TO bank_portal_reconciled;
CREATE INDEX bank_portal_reconciled_place
    ON bank_portal_reconciled (company_id, account_id, value_id, date_from);
CREATE INDEX bank_portal_reconciled_value ON bank_portal_reconciled (company_id, value_id);

-- e-qaimə portal: dates of the invoice, of a change and of a reconciled period ---------
CREATE TABLE eqaime_portal_new (
    id            INTEGER PRIMARY KEY,
    company_id    INTEGER NOT NULL REFERENCES companies(id),
    outgoing      INTEGER NOT NULL CHECK (outgoing IN (0, 1)),  -- 1 sent (a sale)
    number        TEXT NOT NULL CHECK (TRIM(number) <> ''),  -- normalized: domain/invoice.py
    portal_id     TEXT NOT NULL DEFAULT '',  -- for invoice/{id}
    source_system TEXT NOT NULL DEFAULT '',
    doc_date      TEXT NOT NULL  -- of the e-qaimə on the portal (createdAt)
        CHECK (doc_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    party_tin     TEXT NOT NULL DEFAULT '',
    party_name    TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL,  -- as the API names it
    kind          TEXT NOT NULL DEFAULT '',
    type          TEXT NOT NULL DEFAULT '',
    total         INTEGER NOT NULL,  -- with ƏDV
    vat           INTEGER NOT NULL,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    UNIQUE (company_id, outgoing, number),
    UNIQUE (company_id, id)
);
INSERT INTO eqaime_portal_new (id, company_id, outgoing, number, portal_id, source_system,
                               doc_date, party_tin, party_name, status, kind, type, total, vat,
                               first_seen, last_seen)
SELECT id, company_id, outgoing, number, portal_id, source_system, doc_date, party_tin,
       party_name, status, kind, type, total, vat, first_seen, last_seen
FROM eqaime_portal;
DROP TABLE eqaime_portal;
ALTER TABLE eqaime_portal_new RENAME TO eqaime_portal;

CREATE TABLE eqaime_portal_changes_new (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    portal_id  INTEGER NOT NULL,  -- eqaime_portal.id
    seen_at    TEXT NOT NULL,
    old_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    old_date   TEXT NOT NULL CHECK (old_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    new_date   TEXT NOT NULL CHECK (new_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    old_tin    TEXT NOT NULL,
    new_tin    TEXT NOT NULL,
    old_total  INTEGER NOT NULL,
    new_total  INTEGER NOT NULL,
    old_vat    INTEGER NOT NULL,
    new_vat    INTEGER NOT NULL,
    FOREIGN KEY (company_id, portal_id) REFERENCES eqaime_portal(company_id, id)
);
INSERT INTO eqaime_portal_changes_new (id, company_id, portal_id, seen_at, old_status,
                                       new_status, old_date, new_date, old_tin, new_tin,
                                       old_total, new_total, old_vat, new_vat)
SELECT id, company_id, portal_id, seen_at, old_status, new_status, old_date, new_date,
       old_tin, new_tin, old_total, new_total, old_vat, new_vat
FROM eqaime_portal_changes;
DROP TABLE eqaime_portal_changes;
ALTER TABLE eqaime_portal_changes_new RENAME TO eqaime_portal_changes;
CREATE INDEX eqaime_portal_changes_entry ON eqaime_portal_changes (company_id, portal_id);

CREATE TABLE eqaime_reconciled_new (
    company_id    INTEGER NOT NULL REFERENCES companies(id),
    outgoing      INTEGER NOT NULL CHECK (outgoing IN (0, 1)),
    date_from     TEXT NOT NULL CHECK (date_from GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    date_to       TEXT NOT NULL
        CHECK (date_to GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]' AND date_to >= date_from),
    reconciled_at TEXT NOT NULL,
    PRIMARY KEY (company_id, outgoing, date_from, date_to)
);
INSERT INTO eqaime_reconciled_new (company_id, outgoing, date_from, date_to, reconciled_at)
SELECT company_id, outgoing, date_from, date_to, reconciled_at FROM eqaime_reconciled;
DROP TABLE eqaime_reconciled;
ALTER TABLE eqaime_reconciled_new RENAME TO eqaime_reconciled;

PRAGMA legacy_alter_table = OFF;
