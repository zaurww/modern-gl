-- Quantitative/value inventory register. Inventory documents generate an ordinary
-- GL document atomically; quantities never live in accounting postings.

ALTER TABLE companies ADD COLUMN last_inventory_number INTEGER NOT NULL DEFAULT 0;

CREATE TABLE inventory_units (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    code       TEXT NOT NULL CHECK (TRIM(code) <> ''),
    name       TEXT NOT NULL CHECK (TRIM(name) <> ''),
    precision  INTEGER NOT NULL DEFAULT 3 CHECK (precision BETWEEN 0 AND 6),
    active     INTEGER NOT NULL DEFAULT 1,
    UNIQUE (company_id, code),
    UNIQUE (company_id, id)
);

-- An inventory item/warehouse owns a normal subconto value. This keeps the GL and
-- inventory catalogs referring to the same stable value without duplicating names.
CREATE TABLE inventory_items (
    id                   INTEGER PRIMARY KEY,
    company_id           INTEGER NOT NULL,
    subconto_value_id    INTEGER NOT NULL,
    unit_id              INTEGER NOT NULL,
    inventory_account_id INTEGER NOT NULL,
    FOREIGN KEY (company_id, subconto_value_id)
        REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, unit_id)
        REFERENCES inventory_units(company_id, id),
    FOREIGN KEY (company_id, inventory_account_id)
        REFERENCES accounts(company_id, id),
    UNIQUE (company_id, subconto_value_id),
    UNIQUE (company_id, id)
);

CREATE TABLE warehouses (
    id                INTEGER PRIMARY KEY,
    company_id        INTEGER NOT NULL,
    subconto_value_id INTEGER NOT NULL,
    FOREIGN KEY (company_id, subconto_value_id)
        REFERENCES subconto_values(company_id, id),
    UNIQUE (company_id, subconto_value_id),
    UNIQUE (company_id, id)
);

CREATE TABLE landed_cost_types (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    code       TEXT,
    name       TEXT NOT NULL CHECK (TRIM(name) <> ''),
    active     INTEGER NOT NULL DEFAULT 1,
    UNIQUE (company_id, code),
    UNIQUE (company_id, name),
    UNIQUE (company_id, id)
);

CREATE TABLE inventory_documents (
    id             INTEGER PRIMARY KEY,
    company_id     INTEGER NOT NULL REFERENCES companies(id),
    number         INTEGER NOT NULL,
    doc_date       TEXT NOT NULL
        CHECK (doc_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    doc_type       TEXT NOT NULL CHECK (
        doc_type IN ('opening', 'receipt', 'issue', 'transfer', 'landed_cost')
    ),
    memo           TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL CHECK (status IN ('draft', 'posted')),
    landed_cost_type_id INTEGER,
    gl_document_id INTEGER,
    created_at     TEXT NOT NULL,
    posted_at      TEXT,
    FOREIGN KEY (company_id, gl_document_id) REFERENCES documents(company_id, id),
    FOREIGN KEY (company_id, landed_cost_type_id)
        REFERENCES landed_cost_types(company_id, id),
    UNIQUE (company_id, number),
    UNIQUE (company_id, id),
    UNIQUE (gl_document_id)
);

-- Quantity is an integer in millionths of an item's base unit. Money is minor units.
CREATE TABLE inventory_lines (
    id                   INTEGER PRIMARY KEY,
    company_id           INTEGER NOT NULL,
    document_id          INTEGER NOT NULL,
    line_no              INTEGER NOT NULL,
    item_id              INTEGER NOT NULL,
    warehouse_id         INTEGER,
    to_warehouse_id      INTEGER,
    quantity             INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    amount               INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),
    inventory_amount     INTEGER NOT NULL DEFAULT 0 CHECK (inventory_amount >= 0),
    expense_amount       INTEGER NOT NULL DEFAULT 0 CHECK (expense_amount >= 0),
    offset_account_id    INTEGER,
    offset_sc1           INTEGER,
    offset_sc2           INTEGER,
    offset_sc3           INTEGER,
    source_receipt_line_id INTEGER,
    memo                 TEXT NOT NULL DEFAULT '',
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
    UNIQUE (document_id, line_no),
    UNIQUE (company_id, id)
);

CREATE TABLE stock_movements (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL,
    document_id INTEGER NOT NULL,
    line_id     INTEGER NOT NULL,
    doc_date    TEXT NOT NULL,
    item_id     INTEGER NOT NULL,
    warehouse_id INTEGER NOT NULL,
    movement_type TEXT NOT NULL CHECK (
        movement_type IN (
            'opening', 'receipt', 'issue', 'transfer_out', 'transfer_in', 'landed_cost'
        )
    ),
    quantity    INTEGER NOT NULL,
    amount      INTEGER NOT NULL,
    CHECK (quantity <> 0 OR amount <> 0),
    FOREIGN KEY (company_id, document_id)
        REFERENCES inventory_documents(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, line_id)
        REFERENCES inventory_lines(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, item_id) REFERENCES inventory_items(company_id, id),
    FOREIGN KEY (company_id, warehouse_id) REFERENCES warehouses(company_id, id)
);

-- Issues consume receipt/opening lines FIFO only to preserve landed-cost lineage.
-- Their monetary valuation remains moving weighted average.
CREATE TABLE stock_consumptions (
    id              INTEGER PRIMARY KEY,
    company_id      INTEGER NOT NULL,
    document_id     INTEGER NOT NULL,
    issue_line_id   INTEGER NOT NULL,
    receipt_line_id INTEGER NOT NULL,
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    FOREIGN KEY (company_id, document_id)
        REFERENCES inventory_documents(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, issue_line_id)
        REFERENCES inventory_lines(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, receipt_line_id)
        REFERENCES inventory_lines(company_id, id),
    UNIQUE (issue_line_id, receipt_line_id)
);

CREATE TABLE landed_cost_expense_allocations (
    id                    INTEGER PRIMARY KEY,
    company_id            INTEGER NOT NULL,
    document_id           INTEGER NOT NULL,
    landed_cost_line_id   INTEGER NOT NULL,
    issue_line_id         INTEGER NOT NULL,
    amount                INTEGER NOT NULL CHECK (amount > 0),
    FOREIGN KEY (company_id, document_id)
        REFERENCES inventory_documents(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, landed_cost_line_id)
        REFERENCES inventory_lines(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, issue_line_id)
        REFERENCES inventory_lines(company_id, id),
    UNIQUE (landed_cost_line_id, issue_line_id)
);

CREATE INDEX inventory_documents_by_company_date
    ON inventory_documents (company_id, status, doc_date, id);
CREATE INDEX stock_movements_by_balance
    ON stock_movements (company_id, item_id, warehouse_id, doc_date, id);
CREATE INDEX stock_movements_by_document ON stock_movements (document_id);
CREATE INDEX stock_consumptions_by_receipt ON stock_consumptions (receipt_line_id);

-- Posted inventory data is immutable. The application may first change only the
-- status back to draft in an open period, then remove the generated rows atomically.
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
)
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;

CREATE TRIGGER inventory_documents_posted_no_delete BEFORE DELETE ON inventory_documents
WHEN OLD.status = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document cannot be deleted'); END;

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

CREATE TRIGGER stock_consumptions_posted_no_insert BEFORE INSERT ON stock_consumptions
WHEN (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER stock_consumptions_posted_no_update BEFORE UPDATE ON stock_consumptions
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
  OR (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER stock_consumptions_posted_no_delete BEFORE DELETE ON stock_consumptions
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;

CREATE TRIGGER landed_allocations_posted_no_insert
BEFORE INSERT ON landed_cost_expense_allocations
WHEN (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER landed_allocations_posted_no_update
BEFORE UPDATE ON landed_cost_expense_allocations
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
  OR (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
CREATE TRIGGER landed_allocations_posted_no_delete
BEFORE DELETE ON landed_cost_expense_allocations
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;
