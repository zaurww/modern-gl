-- The month of an expense moves from the purchase to its line (D134 practice, D-new1): an
-- e-qaimə whose lines belong to different months, a line split by months. A purchase then
-- has one accrual document per month — `inventory_accruals`; `inventory_documents` loses
-- expense_date and accrual_document_id. SQLite cannot drop a column a foreign key uses:
-- the table is rebuilt as in 0047 (rows, ids and column order stay; indexes and triggers
-- are made again). Foreign keys are off meanwhile (db.migrate).
PRAGMA legacy_alter_table = ON;

-- the line's month: the purchase's, for every line without an item --------------------
-- (the lines of posted documents are guarded by a trigger: it steps aside for the move)
ALTER TABLE inventory_lines ADD COLUMN expense_date TEXT
    CHECK (expense_date IS NULL OR expense_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]');
DROP TRIGGER inventory_lines_posted_no_update;
UPDATE inventory_lines SET expense_date = (
    SELECT d.expense_date FROM inventory_documents d
    WHERE d.id = inventory_lines.document_id AND d.doc_type = 'receipt'
)
WHERE item_id IS NULL;
CREATE TRIGGER inventory_lines_posted_no_update BEFORE UPDATE ON inventory_lines
WHEN (SELECT status FROM inventory_documents WHERE id = OLD.document_id) = 'posted'
  OR (SELECT status FROM inventory_documents WHERE id = NEW.document_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted inventory document is immutable'); END;

-- the accruals of a purchase, one GL document per month ------------------------------
CREATE TABLE inventory_accruals (
    id             INTEGER PRIMARY KEY,
    company_id     INTEGER NOT NULL REFERENCES companies(id),
    document_id    INTEGER NOT NULL,
    expense_date   TEXT NOT NULL
        CHECK (expense_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    gl_document_id INTEGER NOT NULL,
    FOREIGN KEY (company_id, document_id)
        REFERENCES inventory_documents(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, gl_document_id) REFERENCES documents(company_id, id),
    UNIQUE (document_id, expense_date),
    UNIQUE (gl_document_id),
    UNIQUE (company_id, id)
);
INSERT INTO inventory_accruals (company_id, document_id, expense_date, gl_document_id)
SELECT company_id, id, expense_date, accrual_document_id
FROM inventory_documents WHERE accrual_document_id IS NOT NULL;

-- inventory_documents without expense_date and accrual_document_id -------------------
DROP VIEW document_owners;
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
    incoming_reason     TEXT CHECK (
        incoming_reason IS NULL
        OR incoming_reason IN ('surplus', 'contribution', 'production', 'gift')
    ),
    awaits_invoice      INTEGER NOT NULL DEFAULT 0
        CHECK (awaits_invoice IN (0, 1)
               AND (awaits_invoice = 0 OR (doc_type = 'receipt' AND invoice IS NULL))),
    CHECK ((doc_type = 'incoming') = (incoming_reason IS NOT NULL)),
    FOREIGN KEY (company_id, gl_document_id) REFERENCES documents(company_id, id),
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
                                     invoice, invoice_kind, incoming_reason, awaits_invoice)
SELECT id, company_id, number, doc_date, doc_type, memo, status, landed_cost_type_id,
       gl_document_id, created_at, posted_at, vat_rate, allocation_method, currency_id,
       currency_rate, invoice, invoice_kind, incoming_reason, awaits_invoice
FROM inventory_documents;
DROP TABLE inventory_documents;
ALTER TABLE inventory_documents_new RENAME TO inventory_documents;
CREATE INDEX inventory_documents_by_company_date
    ON inventory_documents (company_id, status, doc_date, id);
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

-- the accruals are the purchase's documents, as before (D75) ---------------------------
CREATE VIEW document_owners AS
SELECT company_id, gl_document_id AS document_id, 'inventory' AS module, 'made' AS role,
       id AS owner_id, number AS owner_number
FROM inventory_documents WHERE gl_document_id IS NOT NULL
UNION ALL
SELECT a.company_id, a.gl_document_id, 'inventory', 'made', d.id, d.number
FROM inventory_accruals a
JOIN inventory_documents d ON d.company_id = a.company_id AND d.id = a.document_id
UNION ALL
SELECT company_id, document_id, 'conversion', 'made', id, NULL
FROM currency_conversions WHERE document_id IS NOT NULL
UNION ALL
SELECT company_id, credit_document_id, 'conversion', 'made', id, NULL
FROM currency_conversions WHERE credit_document_id IS NOT NULL
UNION ALL
SELECT company_id, document_id, 'bank', 'made', id, NULL
FROM bank_operations WHERE document_id IS NOT NULL
UNION ALL
SELECT c.company_id, c.source_document_id, 'landed_cost', 'uses', d.id, d.number
FROM landed_cost_charges c
JOIN inventory_documents d ON d.company_id = c.company_id AND d.id = c.document_id
WHERE c.source_document_id IS NOT NULL;

PRAGMA legacy_alter_table = OFF;
